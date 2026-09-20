"""自动化系统的持久化：全局开关、规则文件、执行历史/运行记录。

文件：
- `data/config/automation.json`          全局开关（enabled / dry_run / schedules_enabled / disabled_rules）
- `data/config/rules/<id>.json`          规则（一文件一规则）
- `data/action_history.json`             冷却时间、每任务执行次数、幂等指纹、规则失败计数、定时下次触发
- `data/action_runs.json`                长动作运行记录（进程重启后把 running 标记为 interrupted）
- `data/locks/`                          任务级互斥锁文件
"""

from __future__ import annotations

import json
import os
import random
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config import DATA_DIR
from dates import now_iso

RULES_DIR = DATA_DIR / "config" / "rules"
AUTOMATION_FILE = DATA_DIR / "config" / "automation.json"
HISTORY_FILE = DATA_DIR / "action_history.json"
RUNS_FILE = DATA_DIR / "action_runs.json"
LOCKS_DIR = DATA_DIR / "locks"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "dry_run": False,
    "schedules_enabled": True,
    "disabled_rules": [],
    "failure_threshold": 3,
}

_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


@contextmanager
def _locked() -> Iterator[None]:
    """进程内可重入锁 + 跨进程文件锁（与账号模块同一套路）。

    **同线程嵌套安全**：`flock` 对同一文件的第二个 fd 会阻塞，所以嵌套时只复用
    外层锁（`delete_rule` 里 `update_history` 就是嵌套调用）。
    """
    with _LOCK:
        depth = getattr(_LOCK_STATE, "depth", 0)
        _LOCK_STATE.depth = depth + 1
        handle = None
        try:
            LOCKS_DIR.mkdir(parents=True, exist_ok=True)
            if depth == 0:
                handle = open(LOCKS_DIR / ".automation.lock", "a+", encoding="utf-8")
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except ImportError:  # pragma: no cover - 非 POSIX
                    pass
            yield
        finally:
            _LOCK_STATE.depth = depth
            if handle is not None:
                handle.close()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ 全局开关


def load_settings() -> Dict[str, Any]:
    """每次现读（改完立即生效，不需要重启）。"""
    data = _read_json(AUTOMATION_FILE, None)
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        settings.update({k: v for k, v in data.items() if v is not None})
    settings["disabled_rules"] = list(settings.get("disabled_rules") or [])
    return settings


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _locked():
        current = load_settings()
        for key, value in (patch or {}).items():
            if value is None:
                continue
            current[key] = value
        _write_json(AUTOMATION_FILE, current)
    return current


def ensure_defaults() -> None:
    """首次运行时落一份 automation.json 与示例规则（默认全量启用）。"""
    Automation = DEFAULT_SETTINGS
    if not AUTOMATION_FILE.is_file():
        _write_json(AUTOMATION_FILE, Automation)
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    if not any(RULES_DIR.glob("*.json")):
        for rule in DEFAULT_RULES:
            _write_json(RULES_DIR / f"{rule['id']}.json", rule)


# ------------------------------------------------------------------ 规则


def load_rules() -> List[Dict[str, Any]]:
    """读取所有规则文件（一文件一规则；也兼容一个文件里放列表）。"""
    rules: List[Dict[str, Any]] = []
    if not RULES_DIR.is_dir():
        return rules
    for path in sorted(RULES_DIR.glob("*.json")):
        data = _read_json(path, None)
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            rule = dict(item)
            rule.setdefault("enabled", True)
            rule.setdefault("trigger", {"type": "inspection_completed"})
            rule.setdefault("condition", {})
            rule.setdefault("guard", {})
            rule["_file"] = path.name
            rules.append(rule)
    return rules


def save_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """写回规则文件（保留 `_file` 指向的文件名）。"""
    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
        raise ValueError("规则缺少 id")
    payload = {k: v for k, v in rule.items() if not k.startswith("_")}
    path = RULES_DIR / str(rule.get("_file") or f"{rule_id}.json")
    with _locked():
        _write_json(path, payload)
    return payload


def set_rule_enabled(rule_id: str, enabled: bool) -> Dict[str, Any]:
    for rule in load_rules():
        if str(rule.get("id")) == str(rule_id):
            rule["enabled"] = bool(enabled)
            return save_rule(rule)
    raise KeyError(f"规则不存在：{rule_id}")


def find_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    for rule in load_rules():
        if str(rule.get("id")) == str(rule_id):
            return rule
    return None


def create_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """新建规则文件；同名规则已存在时抛 KeyError。"""
    rule_id = str(rule.get("id") or "").strip()
    if find_rule(rule_id) is not None:
        raise KeyError(f"规则已存在：{rule_id}")
    payload = {k: v for k, v in rule.items() if not k.startswith("_")}
    with _locked():
        _write_json(RULES_DIR / f"{rule_id}.json", payload)
    return payload


def delete_rule(rule_id: str) -> bool:
    """删除规则文件，并清掉它的历史（冷却/计数/失败数/定时下次触发）。"""
    target = str(rule_id)
    rule = find_rule(target)
    if rule is None:
        return False
    path = RULES_DIR / str(rule.get("_file") or f"{target}.json")
    with _locked():
        try:
            path.unlink()
        except FileNotFoundError:
            return False

        def mutate(history: Dict[str, Any]) -> None:
            history["next_runs"].pop(target, None)
            history["next_crons"].pop(target, None)
            history["rule_failures"].pop(target, None)

        update_history(mutate)
    # 从熔断禁用列表里移除（规则都没了）
    settings = load_settings()
    disabled = [str(x) for x in settings.get("disabled_rules") or [] if str(x) != target]
    if disabled != list(settings.get("disabled_rules") or []):
        save_settings({"disabled_rules": disabled})
    return True


# ------------------------------------------------------------------ 历史 / 运行记录


_EMPTY_HISTORY: Dict[str, Any] = {
    "cooldowns": {},      # "task|action" -> ISO 时间（上次执行）
    "counts": {},         # "task|action" -> 累计次数
    "fingerprints": {},   # 幂等指纹 -> {at, run_id, status}
    "rule_failures": {},  # rule_id -> 连续失败次数
    "next_runs": {},      # schedule_id -> 下次触发时间
    "next_crons": {},     # schedule_id -> 计算 next_run 时用的 cron（改了要重算）
    "last_fired": {},     # schedule_id -> 上次触发时间（"N 秒后执行一次"用来看是否已执行）
    "last_results": {},   # "task|action" -> {at, status, reason}
}


def load_history() -> Dict[str, Any]:
    data = _read_json(HISTORY_FILE, None)
    history = {k: dict(v) if isinstance(v, dict) else {} for k, v in _EMPTY_HISTORY.items()}
    if isinstance(data, dict):
        for key in history:
            if isinstance(data.get(key), dict):
                history[key].update(data[key])
    return history


def save_history(history: Dict[str, Any]) -> None:
    with _locked():
        _write_json(HISTORY_FILE, history)


def update_history(mutate) -> Dict[str, Any]:
    """在锁内读改写历史（mutate 直接改 dict）。"""
    with _locked():
        history = load_history()
        mutate(history)
        _write_json(HISTORY_FILE, history)
    return history


def load_runs() -> Dict[str, Any]:
    data = _read_json(RUNS_FILE, None)
    return data if isinstance(data, dict) else {"runs": []}


def save_runs(runs: Dict[str, Any]) -> None:
    with _locked():
        _write_json(RUNS_FILE, runs)


def update_runs(mutate) -> Dict[str, Any]:
    with _locked():
        runs = load_runs()
        mutate(runs)
        _write_json(RUNS_FILE, runs)
    return runs


def new_run_id() -> str:
    return f"run_{now_iso().replace(':', '').replace('-', '').replace('+', '_')}_{random.randint(1000, 9999)}"


# ------------------------------------------------------------------ 默认规则

DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "id": "opt-unconverged-continuation",
        "enabled": True,
        "description": "结构优化结束但力未收敛 → 自动创建续算",
        "trigger": {"type": "inspection_completed"},
        "condition": {"task_type": "opt", "status": ["unconverged", "zombied"], "is_continuation": False},
        "action": "task.continuation",
        "guard": {"cooldown_seconds": 1800, "max_runs_per_task": 5},
    },
    {
        "id": "opt-completed-missing-frac",
        "enabled": True,
        "description": "自由能结构优化已收敛但还没有 frac 输入 → 生成频率矫正文件",
        "trigger": {"type": "inspection_completed"},
        "condition": {
            "task_type": "opt",
            "status": "completed",
            "group_type": "free_energy",
            "frac_missing": True,
        },
        "action": "frac.create",
        "guard": {"cooldown_seconds": 1800, "max_runs_per_task": 2},
    },
    {
        "id": "nightly-unconverged-scan",
        "enabled": True,
        "description": "每天 02:00 扫描未收敛任务并续算",
        "trigger": {"type": "schedule", "cron": "0 2 * * *", "scope": "all"},
        "condition": {"task_type": "opt", "status": ["unconverged", "zombied"], "is_continuation": False},
        "action": "task.continuation",
        "guard": {"cooldown_seconds": 1800, "max_runs_per_task": 5},
    },
]
