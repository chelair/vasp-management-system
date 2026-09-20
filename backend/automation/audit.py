"""自动化审计：规则匹配与动作执行结果，写 `data/audit/actions.jsonl`。

字段（在作业/账号审计的字段基础上扩展）：
`at / username / project / task_id / remote_dir / command / result`
（保持与既有记录兼容），另外追加
`trigger / trigger_id / action / status / reason / elapsed_ms / details / rule_id / run_id`。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from config import DATA_DIR
from automation.store import LOCKS_DIR

AUDIT_FILE = DATA_DIR / "audit" / "actions.jsonl"

#: 自动化写入的记录都带 `automation: true`，前端"决策日志"按它过滤
STATUSES = ("success", "failed", "skipped", "blocked", "dry_run")


def write(
    *,
    action: str,
    status: str,
    task_id: str = "",
    project: str = "",
    trigger: str = "",
    trigger_id: str = "",
    reason: str = "",
    elapsed_ms: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    rule_id: str = "",
    run_id: str = "",
    remote_dir: str = "",
    username: str = "automation",
) -> Dict[str, Any]:
    """追加一条自动化审计记录并返回它（status 非枚举值时原样写入，便于排障）。"""
    record: Dict[str, Any] = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "username": username or "automation",
        "project": project,
        "task_id": task_id,
        "remote_dir": remote_dir,
        "command": action or "automation",
        "result": status,
        "automation": True,
        "action": action,
        "status": status,
        "trigger": trigger,
        "trigger_id": trigger_id,
        "reason": reason,
    }
    if rule_id:
        record["rule_id"] = rule_id
    if run_id:
        record["run_id"] = run_id
    if elapsed_ms is not None:
        record["elapsed_ms"] = int(elapsed_ms)
    if details:
        record["details"] = details
    try:
        LOCKS_DIR.mkdir(parents=True, exist_ok=True)
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return record


def read_recent(limit: int = 200, *, only_automation: bool = True) -> list:
    """读取最近若干条审计（默认只看自动化记录），用于决策日志页。"""
    if not AUDIT_FILE.is_file():
        return []
    try:
        # 审计文件是追加写的 JSONL，体积不大，直接从尾部读
        with open(AUDIT_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-max(limit * 3, 200):]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if only_automation and not record.get("automation"):
            continue
        out.append(record)
        if len(out) >= limit:
            break
    return out
