"""远程操作封装（Paramiko）：执行命令 / 上传 / 下载 / 递归建目录 + 常驻连接池。

支持本地模拟模式（环境变量 VASP_SSH_MOCK=1，模拟根目录 VASP_MOCK_REMOTE_ROOT，
默认 data/mock_remote）：远程路径按原样映射到模拟根目录下的本地文件，
`python3 <script> <in> <out>` 命令改为本地 Python 执行，便于离线测试巡检流程。

连接池：同一服务器复用一条常驻 SSH 连接（exec_command 串行化，避免并发冲突），
每 30 秒发送 Paramiko 传输层保活包，后台每 60 秒再做一次应用层保活
（echo ok 实测往返延迟，写入连接池状态供前端展示），空闲 5 分钟自动回收，
连接断开后下次调用自动重连。
"""

import os
import base64
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from config import DATA_DIR, load_servers

# ---------- 常驻连接池 ----------

_ssh_lock = threading.RLock()
_ssh_clients: Dict[str, Dict[str, Any]] = {}
_ssh_exec_locks: Dict[str, threading.Lock] = {}
_pruner_started = False

IDLE_TIMEOUT_SECONDS = 300
KEEPALIVE_SECONDS = 30
KEEPALIVE_PING_SECONDS = 60  # 应用层保活间隔（echo ok 实测延迟）
PRUNE_INTERVAL_SECONDS = 60
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY = 2.0  # 秒，按尝试次数递增（2s / 4s）


def _mock_enabled() -> bool:
    return os.environ.get("VASP_SSH_MOCK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _mock_root() -> Path:
    return Path(
        os.environ.get("VASP_MOCK_REMOTE_ROOT", str(DATA_DIR / "mock_remote"))
    )


def mock_enabled() -> bool:
    """是否处于本地模拟模式（VASP_SSH_MOCK=1）。"""
    return _mock_enabled()


def mock_local_path(remote_path: str) -> Path:
    """模拟模式下远程绝对路径对应的本地路径（非 mock 模式调用无意义）。"""
    return _local_path(remote_path)


def _local_path(remote_path: str) -> Path:
    """模拟模式下把远程绝对路径映射为本地路径。"""
    return _mock_root() / str(remote_path).lstrip("/")


#: 模拟模式下支持 `echo <base64> | base64 -d | bash`（提交/续算/建 NEB 等都用它）
_MOCK_B64_BASH = re.compile(r"echo\s+([A-Za-z0-9+/=]+)\s*\|\s*base64\s+-d\s*\|\s*bash")


def _mock_shell_prefixes() -> list:
    """模拟模式下需要重写的远程绝对路径前缀（按长度倒序匹配）。"""
    prefixes = set()
    for cfg in load_servers().values():
        for key in ("remote_base", "home", "root", "scratch_root"):
            value = str((cfg or {}).get(key) or "").strip()
            if value.startswith("/") and value != "/":
                prefixes.add(value.rstrip("/"))
    # 脚本里按绝对路径调用的公共工具目录
    prefixes.update(
        {
            "/data/gpfs03/mdye/VTST",
            "/data/gpfs03/mdye/projects/potcar",
            "/opt/ibm/lsfsuite",
        }
    )
    return sorted(prefixes, key=len, reverse=True)


def _mock_rewrite_paths(text: str) -> str:
    """把脚本里的远程绝对路径重写到模拟根目录，让 bash 脚本能本地跑起来。

    必须**单遍替换**（前缀按长度倒序进正则的 alternation）：否则先替换长前缀后，
    短前缀（如 `home` = `/data/gpfs03/mdye`）会把刚写好的模拟根路径再包一层。
    """
    root = str(_mock_root())
    prefixes = _mock_shell_prefixes()
    if not prefixes:
        return text
    pattern = re.compile("|".join(re.escape(prefix) for prefix in prefixes))
    return pattern.sub(lambda m: root + m.group(0), text)


def _mock_run(command: str, timeout: int) -> Dict[str, Any]:
    """模拟模式执行：python 脚本直跑；base64 bash 脚本重写路径后本地 bash 执行。

    - `python3 <脚本> <参数…>`：脚本与参数按模拟根映射后由当前解释器执行（原有行为）；
    - `echo <b64> | base64 -d | bash`：解码 → 路径重写 → `bash` 执行，工作目录为模拟根，
      并把 `<模拟根>/_mock_bin` 放进 PATH（测试可放 bsub 等打桩脚本）；
    - 其他命令一律返回"不支持的远程命令"。
    """
    parts = command.strip().split()
    if parts and parts[0] in ("python3", "python"):
        script = _local_path(parts[1])
        args = [_local_path(part) for part in parts[2:]]
        try:
            proc = subprocess.run(
                [sys.executable, str(script), *[str(a) for a in args]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"mock timeout（{timeout}s）", "exit_code": 1}
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }

    match = _MOCK_B64_BASH.search(command)
    if match:
        try:
            script = base64.b64decode(match.group(1)).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            return {"stdout": "", "stderr": f"mock: base64 解码失败：{e}", "exit_code": 1}
        script = _mock_rewrite_paths(script)
        root = _mock_root()
        shim = root / "_mock_bin"
        shim.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PATH"] = f"{shim}:{env.get('PATH', '')}"
        env["VASP_SSH_MOCK"] = "1"
        try:
            proc = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(root),
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"mock timeout（{timeout}s）", "exit_code": 1}
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }

    return {"stdout": "", "stderr": "mock: 不支持的远程命令", "exit_code": 1}


def _get_client(server_name: str):
    """建立 Paramiko SSH 连接（密钥认证优先，配置了 password 则用密码）。"""
    servers = load_servers()
    cfg = servers.get(server_name)
    if cfg is None:
        raise ValueError(f"服务器 '{server_name}' 未在 servers.json 中配置")
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("缺少依赖 paramiko，请运行：pip install -r requirements.txt")

    connect_kwargs = dict(
        hostname=cfg["host"],
        port=int(cfg.get("port", 22)),
        username=cfg["user"],
        timeout=10,
        banner_timeout=10,
    )
    if cfg.get("password"):
        connect_kwargs["password"] = str(cfg["password"])
    else:
        connect_kwargs["key_filename"] = os.path.expanduser(
            cfg.get("key_path", "~/.ssh/id_rsa")
        )
    # 瞬时网络故障（DNS 解析失败 / 连接超时）自动重试，避免巡检一次抖动就失败
    last_err: Exception = RuntimeError("SSH 连接失败")
    for attempt in range(1, CONNECT_RETRIES + 1):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(**connect_kwargs)
            return client
        except Exception as e:  # noqa: BLE001 - 所有连接类错误都可重试
            last_err = e
            try:
                client.close()
            except Exception:
                pass
            if attempt < CONNECT_RETRIES:
                time.sleep(CONNECT_RETRY_DELAY * attempt)
    raise last_err


def _exec_lock(server_name: str) -> threading.Lock:
    with _ssh_lock:
        return _ssh_exec_locks.setdefault(server_name, threading.Lock())


def _client_active(client) -> bool:
    transport = client.get_transport()
    return bool(transport and transport.is_active())


def _acquire_client(server_name: str):
    """获取常驻连接；不存在或已断开时自动新建。"""
    with _ssh_lock:
        entry = _ssh_clients.get(server_name)
        if entry and _client_active(entry["client"]):
            entry["last_used"] = time.time()
            return entry["client"]
        if entry:
            try:
                entry["client"].close()
            except Exception:
                pass
            _ssh_clients.pop(server_name, None)
    client = _get_client(server_name)
    try:
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(KEEPALIVE_SECONDS)
    except Exception:
        pass
    with _ssh_lock:
        _ssh_clients[server_name] = {"client": client, "last_used": time.time()}
    return client


def _drop_client(server_name: str) -> None:
    with _ssh_lock:
        entry = _ssh_clients.pop(server_name, None)
    if entry:
        try:
            entry["client"].close()
        except Exception:
            pass


def _prune_idle_clients() -> None:
    now = time.time()
    with _ssh_lock:
        stale = [
            name
            for name, entry in _ssh_clients.items()
            if now - entry["last_used"] > IDLE_TIMEOUT_SECONDS
        ]
    for name in stale:
        _drop_client(name)


def _ping(server_name: str) -> float:
    """应用层保活：实测一条 echo 命令往返延迟（毫秒）并写入连接池条目。

    连接异常时抛出（run_remote 已负责丢弃失效连接），调用方按需再清理。
    """
    start = time.perf_counter()
    r = run_remote(server_name, "echo ok", timeout=30)
    latency_ms = round((time.perf_counter() - start) * 1000)
    if r.get("exit_code") != 0:
        raise RuntimeError(
            (r.get("stderr") or r.get("stdout") or "").strip() or "保活命令执行失败"
        )
    with _ssh_lock:
        entry = _ssh_clients.get(server_name)
        if entry:
            entry["latency_ms"] = latency_ms
            entry["latency_at"] = time.time()
    return latency_ms


def _background_loop() -> None:
    """后台维护循环：定时应用层保活（顺带实测延迟）+ 空闲连接回收。"""
    while True:
        time.sleep(KEEPALIVE_PING_SECONDS)
        try:
            with _ssh_lock:
                names = list(_ssh_clients.keys())
            for name in names:
                try:
                    _ping(name)
                except Exception:  # noqa: BLE001 - 单次保活失败不中断循环
                    _drop_client(name)
        except Exception:  # noqa: BLE001 - 保活轮次异常不中断循环
            pass
        try:
            _prune_idle_clients()
        except Exception:
            pass


def ensure_pruner() -> None:
    """确保后台维护线程只启动一次（定时保活 + 空闲回收）。"""
    global _pruner_started
    with _ssh_lock:
        if _pruner_started:
            return
        _pruner_started = True
    threading.Thread(target=_background_loop, daemon=True).start()


def warmup_connection(server_name: str) -> None:
    """系统启动时后台预热常驻连接（失败静默，后续操作按需重连）。"""
    if _mock_enabled():
        return
    try:
        _acquire_client(server_name)
        ensure_pruner()
        try:
            _ping(server_name)
        except Exception:  # noqa: BLE001 - 首次保活失败不阻塞，后台循环会重试
            pass
        print(f"[ssh] 常驻连接已建立：{server_name}")
    except Exception as e:  # noqa: BLE001 - 启动预热失败不阻塞系统
        print(f"[ssh] 预热连接失败 {server_name}：{e}")


def get_pool_status() -> Dict[str, Any]:
    """连接池状态（顶栏真实连接指示用）。"""
    if _mock_enabled():
        servers = load_servers()
        first = next(iter(servers), "")
        cfg = servers.get(first, {})
        return {
            "connected": True,
            "mock": True,
            "server": first or None,
            "host": cfg.get("host"),
            "user": cfg.get("user"),
            "lastUsedAt": None,
            "idleSeconds": None,
            "latencyMs": None,
            "latencyAt": None,
        }
    with _ssh_lock:
        entries = list(_ssh_clients.items())
    for name, entry in entries:
        if _client_active(entry["client"]):
            last_used = entry.get("last_used")
            cfg = load_servers().get(name, {})
            return {
                "connected": True,
                "mock": False,
                "server": name,
                "host": cfg.get("host"),
                "user": cfg.get("user"),
                "lastUsedAt": (
                    datetime.fromtimestamp(last_used).isoformat(timespec="seconds")
                    if last_used
                    else None
                ),
                "idleSeconds": round(time.time() - last_used, 1) if last_used else None,
                "latencyMs": entry.get("latency_ms"),
                "latencyAt": (
                    datetime.fromtimestamp(entry["latency_at"]).isoformat(
                        timespec="seconds"
                    )
                    if entry.get("latency_at")
                    else None
                ),
            }
    return {
        "connected": False,
        "mock": False,
        "server": None,
        "host": None,
        "user": None,
        "lastUsedAt": None,
        "idleSeconds": None,
        "latencyMs": None,
        "latencyAt": None,
    }


def run_remote(server_name: str, command: str, timeout: int = 30) -> Dict[str, object]:
    """在指定服务器执行命令，返回 {stdout, stderr, exit_code}。

    使用常驻连接池执行：复用连接避免重复握手，连接异常时自动断开并抛出，
    下次调用会重新建立连接。
    """
    if _mock_enabled():
        return _mock_run(command, timeout)

    ensure_pruner()
    lock = _exec_lock(server_name)
    with lock:
        client = _acquire_client(server_name)
        try:
            # 显式 UTF-8 编码，避免中文路径/命令在传输时被按本地编码破坏
            _stdin, stdout, stderr = client.exec_command(
                command.encode("utf-8"), timeout=timeout
            )
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            with _ssh_lock:
                entry = _ssh_clients.get(server_name)
                if entry:
                    entry["last_used"] = time.time()
            return {"stdout": out, "stderr": err, "exit_code": exit_code}
        except Exception:
            # 连接可能已断开：丢弃以便下次重连
            _drop_client(server_name)
            raise


def upload_file(
    server_name: str, local_path: str, remote_path: str, timeout: int = 60
) -> bool:
    """上传本地文件到远程路径，失败时抛出异常。"""
    local = Path(local_path)
    if not local.is_file():
        raise FileNotFoundError(f"本地文件不存在：{local_path}")
    if _mock_enabled():
        target = _local_path(remote_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, target)
        return True

    ensure_pruner()
    lock = _exec_lock(server_name)
    with lock:
        client = _acquire_client(server_name)
        sftp = client.open_sftp()
        try:
            sftp.put(str(local), remote_path)
            return True
        finally:
            sftp.close()


def download_file(
    server_name: str, remote_path: str, local_path: str, timeout: int = 60
) -> bool:
    """下载远程文件到本地；远程不存在/为空或失败时返回 False。"""
    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    if _mock_enabled():
        src = _local_path(remote_path)
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, local)
            return True
        return False

    ensure_pruner()
    lock = _exec_lock(server_name)
    with lock:
        client = _acquire_client(server_name)
        sftp = client.open_sftp()
        try:
            stat = sftp.stat(remote_path)
            if stat.st_size <= 0:
                return False
            sftp.get(remote_path, str(local))
            return True
        except FileNotFoundError:
            return False
        finally:
            sftp.close()


def mkdir_remote(server_name: str, remote_path: str, timeout: int = 30) -> None:
    """在远程服务器递归创建目录（mkdir -p），失败时抛出异常。"""
    if _mock_enabled():
        _local_path(remote_path).mkdir(parents=True, exist_ok=True)
        return

    ensure_pruner()
    lock = _exec_lock(server_name)
    with lock:
        client = _acquire_client(server_name)
        _stdin, stdout, stderr = client.exec_command(
            f"mkdir -p '{remote_path}'".encode("utf-8"), timeout=timeout
        )
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            detail = (
                stderr.read().decode("utf-8", errors="replace")
                or stdout.read().decode("utf-8", errors="replace")
            ).strip()
            raise RuntimeError(
                f"远程创建目录失败 {remote_path}：{detail or f'退出码 {exit_code}'}"
            )
