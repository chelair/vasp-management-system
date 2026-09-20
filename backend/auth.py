"""用户与会话底座（账号体系第 1 步：只提供基础设施，**不接入任何接口**）。

本模块只做三件事，供后续「认证中间件 / 登录接口 / 授权过滤」复用：

1. **密码**：`hashlib.scrypt` + 随机 salt，编码为 `scrypt$n$r$p$salt_hex$hash_hex`；
   校验用 `hmac.compare_digest`（常量时间）。
2. **会话**：`secrets.token_urlsafe(32)` 生成 token，服务端**只存 sha256(token)**，
   所以 `data/` 泄露也拿不到可用 token。
3. **存储**：`data/users/users.json`（用户）与 `data/users/sessions.json`（会话），
   原子写（临时文件 + `os.replace`）+ 文件锁（POSIX `fcntl.flock`）+ 权限 0600/0700。

首次启动：`users.json` 不存在时自动创建默认管理员（`zouyuxi`），随机初始密码
同时打印到 stdout 与日志，并提示立即用 `scripts/set_password.py` 修改。

依赖：**只用标准库**（hashlib / hmac / json / os / secrets / threading / fcntl）。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from config import DATA_DIR

logger = logging.getLogger("vasp.auth")

# ------------------------------------------------------------------ 常量

USERS_DIR = DATA_DIR / "users"
USERS_FILE = USERS_DIR / "users.json"
SESSIONS_FILE = USERS_DIR / "sessions.json"
LOCK_FILE = USERS_DIR / ".auth.lock"
#: 账号审计（与作业动作写同一份 JSONL，便于统一消费）
AUDIT_FILE = DATA_DIR / "audit" / "actions.jsonl"
#: 会话条数超过这个阈值时，创建会话前顺手清理过期会话（避免文件无限增长）
SESSION_PURGE_THRESHOLD = 100

#: 首次启动自动创建的管理员用户名
DEFAULT_ADMIN_USERNAME = "zouyuxi"
#: 角色：admin 看全部 / user 只看自己的项目 / agent 供智能体长期 token 使用
ROLES = ("admin", "user", "agent")

#: 会话有效期（天），可用环境变量覆盖
SESSION_TTL_DAYS = int(os.environ.get("AUTH_SESSION_TTL_DAYS", "14"))
#: `last_seen` 最多多久刷新一次（秒），避免每次校验都写盘
LAST_SEEN_TOUCH_SECONDS = 300
#: 密码最短长度（建号/改密时校验）
MIN_PASSWORD_LENGTH = 8

#: scrypt 参数（n=2^14 ≈ 16MB 内存，登录一次约 30–80ms，可随机器调整）
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_LEN = 32

try:  # POSIX：跨进程文件锁
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX（开发机）退化为进程内锁
    fcntl = None  # type: ignore[assignment]

_LOCAL_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


class AuthError(Exception):
    """账号相关业务错误（用户名重复、密码太短、用户不存在等）。"""


# ------------------------------------------------------------------ 时间


def now_iso() -> str:
    """本地时区 ISO 时间字符串（与项目其它模块口径一致）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _future_iso(days: Optional[int] = None, seconds: Optional[int] = None) -> str:
    delta = timedelta(days=days if days is not None else SESSION_TTL_DAYS)
    if seconds is not None:
        delta = timedelta(seconds=seconds)
    return (datetime.now(timezone.utc).astimezone() + delta).isoformat(timespec="seconds")


# ------------------------------------------------------------------ 加锁与读写


def ensure_users_dir() -> Path:
    """创建 data/users/（权限尽量 0700）。"""
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(USERS_DIR, 0o700)
    except OSError:  # pragma: no cover - 非 POSIX 或权限不足
        pass
    return USERS_DIR


@contextmanager
def _locked() -> Iterator[None]:
    """进程内可重入锁 + 跨进程文件锁（POSIX）。所有读写都在锁内完成。

    嵌套调用是安全的：同线程第二次进入只复用外层锁（`flock` 对同一文件
    的第二个 fd 会阻塞，同进程嵌套必须避免）。
    """
    with _LOCAL_LOCK:
        depth = getattr(_LOCK_STATE, "depth", 0)
        _LOCK_STATE.depth = depth + 1
        handle = None
        try:
            ensure_users_dir()
            if depth == 0:
                handle = open(LOCK_FILE, "a+", encoding="utf-8")
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            _LOCK_STATE.depth = depth
            if handle is not None:
                if fcntl is not None:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except OSError:  # pragma: no cover
                        pass
                handle.close()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取 %s 失败（按空处理）：%s", path, e)
        return default


def _write_json(path: Path, data: Any) -> None:
    """原子写 + 权限 0600（先写临时文件再 os.replace）。"""
    ensure_users_dir()
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # pragma: no cover
        pass
    os.replace(tmp, path)


# ------------------------------------------------------------------ 密码


def generate_password(length: int = 16) -> str:
    """生成随机密码（去掉易混淆字符 O0Il1）。"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^*-_+"
    return "".join(secrets.choice(alphabet) for _ in range(max(length, MIN_PASSWORD_LENGTH)))


def hash_password(password: str) -> str:
    """scrypt 哈希，返回 `scrypt$n$r$p$salt_hex$hash_hex`（salt 随机 16B）。"""
    text = str(password or "")
    if not text:
        raise AuthError("密码不能为空")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(text, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    import hashlib

    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_LEN
    )


def verify_password(password: str, encoded: str) -> bool:
    """常量时间校验；编码格式不认识或参数异常一律返回 False（不抛错）。"""
    try:
        scheme, n_text, r_text, p_text, salt_hex, hash_hex = str(encoded).split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        actual = _scrypt(
            str(password or ""),
            bytes.fromhex(salt_hex),
            int(n_text),
            int(r_text),
            int(p_text),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, AttributeError, TypeError):
        return False
    except Exception as e:  # noqa: BLE001 - scrypt 参数不合法（内存上限等）也算校验失败
        logger.warning("密码校验异常：%s", e)
        return False


def check_password_policy(password: str) -> None:
    """密码策略：非空且长度 ≥ MIN_PASSWORD_LENGTH。"""
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")


# ------------------------------------------------------------------ 用户


def normalize_username(username: Any) -> str:
    """用户名统一小写、去空白（查找与创建都用它，避免大小写不一致）。"""
    return str(username or "").strip().lower()


def _empty_users() -> Dict[str, Any]:
    return {"version": 1, "users": []}


def load_users_doc() -> Dict[str, Any]:
    """读取 users.json（不存在的返回空结构；**不会**自动建号）。"""
    data = _read_json(USERS_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        return _empty_users()
    return data


def list_users() -> List[Dict[str, Any]]:
    return [dict(u) for u in load_users_doc().get("users", [])]


def find_user(username: Any) -> Optional[Dict[str, Any]]:
    target = normalize_username(username)
    for user in load_users_doc().get("users", []):
        if normalize_username(user.get("username")) == target:
            return dict(user)
    return None


def find_user_by_id(user_id: Any) -> Optional[Dict[str, Any]]:
    target = str(user_id or "")
    for user in load_users_doc().get("users", []):
        if str(user.get("user_id") or "") == target:
            return dict(user)
    return None


def create_user(
    username: str,
    password: Optional[str] = None,
    role: str = "user",
    enabled: bool = True,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """建号；不传密码则生成随机密码。

    返回 `(用户记录, 明文密码或 None)` —— 明文只在"本次生成的"情况下回传，
    调用方负责打印一次，之后系统里只留哈希。
    """
    name = normalize_username(username)
    if not name:
        raise AuthError("用户名不能为空")
    if role not in ROLES:
        raise AuthError(f"角色仅支持 {'/'.join(ROLES)}")
    plain = str(password) if password else generate_password()
    check_password_policy(plain)
    with _locked():
        doc = _read_json(USERS_FILE, None)
        if not isinstance(doc, dict) or not isinstance(doc.get("users"), list):
            doc = _empty_users()
        users = doc["users"]
        if any(normalize_username(u.get("username")) == name for u in users):
            raise AuthError(f"用户已存在：{name}")
        record = {
            "user_id": f"usr_{secrets.token_hex(6)}",
            "username": name,
            "password_hash": hash_password(plain),
            "role": role,
            "enabled": bool(enabled),
            "created_at": now_iso(),
        }
        users.append(record)
        _write_json(USERS_FILE, doc)
    logger.info("已创建用户 %s（role=%s enabled=%s）", name, role, bool(enabled))
    return dict(record), (plain if not password else None)


def _update_user(username: Any, mutate) -> Dict[str, Any]:
    """在锁内按用户名修改用户记录（mutate 直接改 dict）。"""
    name = normalize_username(username)
    with _locked():
        doc = _read_json(USERS_FILE, None)
        if not isinstance(doc, dict) or not isinstance(doc.get("users"), list):
            doc = _empty_users()
        for user in doc["users"]:
            if normalize_username(user.get("username")) == name:
                mutate(user)
                _write_json(USERS_FILE, doc)
                return dict(user)
    raise AuthError(f"用户不存在：{name}")


def set_password(username: str, password: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """改密；不传密码则生成随机密码。返回 `(用户记录, 明文密码或 None)`。"""
    plain = str(password) if password else generate_password()
    check_password_policy(plain)
    updated = _update_user(username, lambda u: u.update({"password_hash": hash_password(plain)}))
    # 改密后旧会话全部失效（凭据变更即下线，避免旧 token 继续可用）
    revoked = revoke_user_sessions(updated["user_id"])
    logger.info("已更新用户 %s 的密码（吊销会话 %d 个）", updated.get("username"), revoked)
    return updated, (plain if not password else None)


def set_enabled(username: str, enabled: bool) -> Dict[str, Any]:
    """启用/禁用；禁用同时吊销该用户全部会话。"""
    updated = _update_user(username, lambda u: u.update({"enabled": bool(enabled)}))
    if not enabled:
        revoke_user_sessions(updated["user_id"])
    logger.info("用户 %s 已%s", updated.get("username"), "启用" if enabled else "禁用")
    return updated


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    """校验用户名+密码；成功返回用户记录，失败返回 None。

    注意：**失败次数限速放在登录接口层**（第 2 步），本函数只做凭据校验。
    """
    user = find_user(username)
    if not user or not user.get("enabled"):
        # 用户不存在/已禁用也走一次哈希，避免通过响应时间判断账号是否存在
        verify_password(password, user.get("password_hash", "") if user else "")
        return None
    if not verify_password(password, str(user.get("password_hash") or "")):
        return None
    return user


# ------------------------------------------------------------------ 会话


def hash_token(token: str) -> str:
    """token → sha256 十六进制（服务端只存这个）。"""
    return sha256(str(token or "").encode("utf-8")).hexdigest()


def audit(
    event: str,
    result: str,
    username: str = "",
    ip: str = "",
    detail: str = "",
) -> None:
    """账号审计：登录成功/失败、登出、长期 token 签发与吊销。

    与作业动作写同一份 `data/audit/actions.jsonl`（字段兼容 + 额外 `ip`/`detail`）；
    审计失败不影响主流程。
    """
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "at": now_iso(),
            "username": normalize_username(username) or "-",
            "project": "",
            "task_id": "",
            "remote_dir": "",
            "command": f"auth.{event}",
            "result": result,
            "ip": ip or "-",
        }
        if detail:
            record["detail"] = detail
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 - 审计失败不影响登录
        logger.warning("写账号审计失败：%s", e)


def new_session_id() -> str:
    return f"sess_{secrets.token_hex(8)}"


def session_key(session: Dict[str, Any]) -> str:
    """会话标识：优先 `session_id`；历史记录（第 1 步写的）回退用 token_hash 前缀。"""
    sid = str(session.get("session_id") or "").strip()
    if sid:
        return sid
    digest = str(session.get("token_hash") or "")
    return f"sess_{digest[:16]}" if digest else ""


def create_session(
    user: Dict[str, Any],
    name: Optional[str] = None,
    ttl_days: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
    kind: str = "session",
    created_by: Optional[str] = None,
    never_expires: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """为用户创建会话 / 长期 token，返回 `(明文 token, 记录)`；明文只在此刻出现一次。

    - `kind="session"`：登录会话（滑动续期）；`kind="token"`：给脚本/智能体的长期 token；
    - `never_expires=True` 时 `expires_at` 为 None（永不过期，仅 admin 可签发）。
    """
    if not user or not user.get("user_id"):
        raise AuthError("创建会话需要一个有效用户记录")
    if never_expires:
        expires_at: Optional[str] = None
    else:
        expires_at = _future_iso(days=ttl_days, seconds=ttl_seconds)
    token = secrets.token_urlsafe(32)
    record = {
        "session_id": new_session_id(),
        "token_hash": hash_token(token),
        "user_id": str(user["user_id"]),
        "username": str(user.get("username") or ""),
        "created_at": now_iso(),
        "last_seen": now_iso(),
        "expires_at": expires_at,
        "name": str(name or "").strip() or None,
        "kind": kind,
        "created_by": created_by,
    }
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        if not isinstance(doc, dict) or not isinstance(doc.get("sessions"), list):
            doc = {"version": 1, "sessions": []}
        # 会话条数偏多时顺手清理过期项（长期运行下避免文件无限增长）
        if len(doc["sessions"]) >= SESSION_PURGE_THRESHOLD:
            doc["sessions"] = [s for s in doc["sessions"] if not is_expired(s)]
        doc["sessions"].append(record)
        _write_json(SESSIONS_FILE, doc)
    return token, dict(record)


def _load_sessions() -> List[Dict[str, Any]]:
    doc = _read_json(SESSIONS_FILE, None)
    if not isinstance(doc, dict) or not isinstance(doc.get("sessions"), list):
        return []
    return [dict(s) for s in doc["sessions"]]


def list_sessions(user_id: Optional[str] = None, include_expired: bool = False) -> List[Dict[str, Any]]:
    """列出会话 / 长期 token（默认过滤已过期；`token_hash` 只回显前 12 位）。"""
    out: List[Dict[str, Any]] = []
    for session in _load_sessions():
        if user_id and str(session.get("user_id")) != str(user_id):
            continue
        if not include_expired and is_expired(session):
            continue
        item = dict(session)
        digest = str(item.get("token_hash") or "")
        item["token_hash"] = f"{digest[:12]}…" if digest else ""
        item["session_id"] = session_key(session)
        item.setdefault("kind", "session")
        item.setdefault("username", "")
        out.append(item)
    out.sort(key=lambda s: str(s.get("created_at") or ""), reverse=True)
    return out


def is_expired(session: Dict[str, Any]) -> bool:
    expires = _parse_iso(session.get("expires_at"))
    if expires is None:
        return False  # 无过期时间（长期 token）永不过期
    return expires <= datetime.now(timezone.utc).astimezone()


def _find_session_index(sessions: List[Dict[str, Any]], *, token_hash: str = "", session_id: str = "") -> int:
    for index, item in enumerate(sessions):
        if token_hash and str(item.get("token_hash") or "") == token_hash:
            return index
        if session_id and session_key(item) == session_id:
            return index
    return -1


def _touch(
    sessions: List[Dict[str, Any]],
    index: int,
    *,
    extend_seconds: Optional[int],
) -> bool:
    """更新 last_seen（每 5 分钟一次）与滑动续期（漂移 ≥1h 才写）。返回是否变化。"""
    session = sessions[index]
    now = datetime.now(timezone.utc).astimezone()
    changed = False
    last = _parse_iso(session.get("last_seen"))
    if last is None or (now - last).total_seconds() >= LAST_SEEN_TOUCH_SECONDS:
        session["last_seen"] = now_iso()
        changed = True
    expires = _parse_iso(session.get("expires_at"))
    if extend_seconds and expires is not None:
        target = now + timedelta(seconds=extend_seconds)
        if (target - expires).total_seconds() >= 3600:  # 至少漂移 1 小时才续期，避免每请求写盘
            session["expires_at"] = target.isoformat(timespec="seconds")
            changed = True
    return changed


def find_session_by_token(token: str) -> Optional[Dict[str, Any]]:
    """按 token 查会话（不校验有效期、不更新 last_seen；登出/管理用）。"""
    digest = hash_token(token)
    if not digest:
        return None
    for session in _load_sessions():
        if str(session.get("token_hash") or "") == digest:
            return session
    return None


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    target = str(session_id or "")
    for session in _load_sessions():
        if session_key(session) == target:
            return session
    return None


def delete_session(session_id: str) -> bool:
    """按 session_id 删除会话（吊销长期 token 用）。"""
    target = str(session_id or "")
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        sessions = doc.get("sessions") if isinstance(doc, dict) else None
        if not isinstance(sessions, list):
            return False
        kept = [s for s in sessions if session_key(s) != target]
        if len(kept) == len(sessions):
            return False
        doc["sessions"] = kept
        _write_json(SESSIONS_FILE, doc)
    return True


def verify_token(
    token: str,
    touch: bool = True,
    extend_seconds: Optional[int] = None,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """校验 token，返回 `(会话, 用户)`；无效/过期/用户被禁用一律 None。

    `touch=True` 时更新 `last_seen`（每 5 分钟最多一次）；`extend_seconds` 传入时
    做**滑动续期**（每次请求把有效期推到 now+14 天，但只有漂移 ≥1h 才真正写盘）。
    """
    digest = hash_token(token)
    if not digest:
        return None
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        sessions = doc.get("sessions") if isinstance(doc, dict) else None
        if not isinstance(sessions, list):
            return None
        index = _find_session_index(sessions, token_hash=digest)
        if index < 0:
            return None
        session = dict(sessions[index])
        if is_expired(session):
            return None
        user = find_user_by_id(session.get("user_id"))
        if user is None or not user.get("enabled"):
            return None
        if touch or extend_seconds:
            if _touch(sessions, index, extend_seconds=extend_seconds if touch else None):
                _write_json(SESSIONS_FILE, doc)
                session = dict(sessions[index])
    return session, user


def revoke_token(token: str) -> bool:
    """吊销单个 token（登出）。"""
    digest = hash_token(token)
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        sessions = doc.get("sessions") if isinstance(doc, dict) else None
        if not isinstance(sessions, list):
            return False
        kept = [s for s in sessions if str(s.get("token_hash") or "") != digest]
        if len(kept) == len(sessions):
            return False
        doc["sessions"] = kept
        _write_json(SESSIONS_FILE, doc)
    return True


def revoke_user_sessions(user_id: str) -> int:
    """吊销某用户全部会话（改密/禁用/强制下线），返回吊销条数。"""
    target = str(user_id or "")
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        sessions = doc.get("sessions") if isinstance(doc, dict) else None
        if not isinstance(sessions, list):
            return 0
        kept = [s for s in sessions if str(s.get("user_id")) != target]
        removed = len(sessions) - len(kept)
        if removed:
            doc["sessions"] = kept
            _write_json(SESSIONS_FILE, doc)
    return removed


def purge_expired_sessions() -> int:
    """清掉已过期会话，返回清理条数（启动时调用一次即可）。"""
    with _locked():
        doc = _read_json(SESSIONS_FILE, None)
        sessions = doc.get("sessions") if isinstance(doc, dict) else None
        if not isinstance(sessions, list):
            return 0
        kept = [s for s in sessions if not is_expired(s)]
        removed = len(sessions) - len(kept)
        if removed:
            doc["sessions"] = kept
            _write_json(SESSIONS_FILE, doc)
    return removed


# ------------------------------------------------------------------ 首次启动


def ensure_users_file(print_password: bool = True) -> Dict[str, Any]:
    """幂等：`users.json` 不存在（或没有任何用户）时创建默认管理员。

    返回 `{"created": bool, "username": str, "password": str|None,
    "user_id": str|None, "users_file": str}`；并发/重复调用只会创建一次。
    """
    ensure_users_dir()
    result: Dict[str, Any] = {
        "created": False,
        "username": None,
        "password": None,
        "user_id": None,
        "users_file": str(USERS_FILE),
    }
    with _locked():
        doc = _read_json(USERS_FILE, None)
        if isinstance(doc, dict) and doc.get("users"):
            return result
        plain = generate_password()
        record = {
            "user_id": f"usr_{secrets.token_hex(6)}",
            "username": DEFAULT_ADMIN_USERNAME,
            "password_hash": hash_password(plain),
            "role": "admin",
            "enabled": True,
            "created_at": now_iso(),
        }
        _write_json(USERS_FILE, {"version": 1, "users": [record]})
        result.update(
            {"created": True, "username": DEFAULT_ADMIN_USERNAME, "password": plain, "user_id": record["user_id"]}
        )

    banner = (
        "\n"
        "=" * 68 + "\n"
        "  已初始化管理员账号（首次启动自动创建）\n"
        f"  用户名：{DEFAULT_ADMIN_USERNAME}\n"
        f"  初始密码：{result['password']}\n"
        "  ⚠️ 请立即修改：python scripts/set_password.py "
        f"{DEFAULT_ADMIN_USERNAME}\n"
        f"  用户文件：{USERS_FILE}\n" + "=" * 68
    )
    logger.warning(
        "首次启动：已创建管理员 %s（user_id=%s），初始密码见 stdout / 下方日志；请立即修改密码",
        DEFAULT_ADMIN_USERNAME,
        result["user_id"],
    )
    logger.warning("初始密码：%s", result["password"])
    if print_password:
        print(banner, flush=True)
    return result


def sessions_file() -> Path:
    """会话文件路径（供接口层/脚本显示用）。"""
    return SESSIONS_FILE
