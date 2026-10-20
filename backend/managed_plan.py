"""巡检后项目托管：计划、任务级优先级与资源规则（只保存意图，不代替任务真相）。

用户一句话 → AI 写成结构化计划：项目目标、阶段交付、任务级优先级/锁定、
允许的队列与额度上限。本模块只做校验与持久化：

- 任务/作业状态仍以项目库（`storage`）与执行台账（`automation.ledger`）为准；
- 真正的提交仍走 `automation.gateway`，本模块不连接 SSH、不提交作业；
- 计划只记录"谁在什么时候把哪条用户原话变成了哪条规则"，便于回溯。

文件：`data/managed_plan.json`；schema：`managed-plan.1`。
锁与原子写复用 `automation.store`（同一把文件锁，避免与自动化互相覆盖）。
"""

from __future__ import annotations

import copy
import json
import math
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DATA_DIR
from dates import now_iso

SCHEMA = "managed-plan.1"
FILE = DATA_DIR / "managed_plan.json"

PLAN_STATUSES = ("active", "paused", "ended")
SOURCES = ("human", "ai")
PRIORITY_MIN, PRIORITY_MAX = 0, 100

_QUEUE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_STAGE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

#: 首版缺省资源上限：只当"用户没明说时的保守上限"，不会自动扩大授权范围。
DEFAULT_RESOURCE_RULES = {
    "queues_allowed": [],
    "queues_denied": [],
    "paid_allowed": False,
    "max_nodes": 2,
    "max_cores": 64,
    "cores_per_node": 24,
    "max_walltime_hours": 24.0,
    "max_core_hours": 2000.0,
    "max_submissions": 5,
    "soft_kill": True,
}

_RULE_LIMITS = {
    "max_nodes": (1, 64),
    "max_cores": (1, 100000),
    "cores_per_node": (1, 1024),
    "max_walltime_hours": (0.1, 720.0),
    "max_core_hours": (0.1, 10_000_000.0),
    "max_submissions": (1, 1000),
}

_STAGE_KEYS = {"stage_id", "title", "task_ids", "due", "timezone", "priority", "source_quote", "reason"}
_OVERRIDE_KEYS = {"task_id", "priority", "locked", "reason"}
_PATCH_KEYS = {"goal_summary", "stages", "task_overrides", "resource_rules", "status"}


class ManagedError(ValueError):
    """可预期的用户错误；`code` 由路由映射成 HTTP 状态码。"""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


# ------------------------------------------------------------------ 读写


def _empty() -> dict:
    return {"schema": SCHEMA, "plans": {}}


def _load() -> dict:
    if not FILE.exists():
        return _empty()
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"托管计划文件损坏，已阻止使用：{exc}") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("plans"), dict):
        raise ValueError("托管计划文件版本不兼容或结构损坏，已阻止使用")
    return data


def _locked_doc():
    from automation.store import _locked

    return _locked()


# ------------------------------------------------------------------ 校验


def _text(value, field: str, max_len: int, required: bool = False) -> str:
    if value is None:
        if required:
            raise ManagedError(f"缺少{field}")
        return ""
    if not isinstance(value, str):
        raise ManagedError(f"{field}必须是文本")
    value = value.strip()
    if required and not value:
        raise ManagedError(f"缺少{field}")
    if len(value) > max_len:
        raise ManagedError(f"{field}过长（最多 {max_len} 字）")
    return value


def _integer(value, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManagedError(f"{field}必须是整数")
    if not low <= value <= high:
        raise ManagedError(f"{field}需在 {low} 到 {high} 之间")
    return value


def _number(value, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManagedError(f"{field}必须是数字")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ManagedError(f"{field}需在 {low} 到 {high} 之间")
    return value


def _queue_name(value, field: str) -> str:
    if not isinstance(value, str) or not _QUEUE_RE.fullmatch(value.strip()):
        raise ManagedError(f"{field}含非法队列名（只允许字母、数字、下划线、点、短横线）")
    return value.strip()


def _queue_list(value, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ManagedError(f"{field}必须是最多 20 个队列名的列表")
    out = []
    for item in value:
        name = _queue_name(item, field)
        if name not in out:
            out.append(name)
    return out


def _timezone(value) -> str:
    name = _text(value, "时区", 64) or "Asia/Shanghai"
    try:
        ZoneInfo(name)
    except Exception:  # noqa: BLE001 - 未知时区一律拒绝
        raise ManagedError("时区无效，请使用 IANA 名称，如 Asia/Shanghai") from None
    return name


def _due(value, field: str = "交付日期") -> str:
    text = _text(value, field, 40)
    if not text:
        return ""
    try:
        if len(text) == 10:
            datetime.strptime(text, "%Y-%m-%d")
        else:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ManagedError(f"{field}格式应为 YYYY-MM-DD 或 ISO 时间") from None
    return text


def _bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise ManagedError(f"{field}必须是布尔值")
    return value


# ------------------------------------------------------------------ 项目与任务


def _project(name, user) -> dict:
    import permissions
    from storage import load_db

    wanted = _text(name, "项目", 200, True)
    project = next((p for p in load_db().get("projects", []) if str(p.get("name")) == wanted), None)
    if project is None:
        raise ManagedError("项目不存在", 404)
    permissions.ensure_project_owner(project, user)
    return project


def _task_map(project: dict) -> dict:
    return {str(t.get("task_id")): t for t in project.get("tasks", []) or []}


def _ensure_task(tasks: dict, task_id, field: str = "任务") -> str:
    tid = _text(task_id, field, 200, True)
    if tid not in tasks:
        raise ManagedError(f"{field}不属于当前项目：{tid}")
    return tid


def _ensure_owner(plan: dict, user) -> dict:
    """按当前项目库重新校验归属；项目归属变化则拒绝继续使用旧计划。"""
    import auth
    import permissions

    project = _project(plan.get("project"), user)
    if auth.normalize_username(project.get("owner")) != plan.get("owner"):
        raise permissions.PermissionDenied("项目归属已变化，请重新创建托管计划")
    return project


# ------------------------------------------------------------------ 规范化


def _stages(raw, tasks: dict) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 20:
        raise ManagedError("阶段列表最多 20 个")
    out = []
    seen_ids = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ManagedError("阶段必须是对象")
        unknown = set(item) - _STAGE_KEYS
        if unknown:
            raise ManagedError("阶段含不支持的字段：" + ", ".join(sorted(unknown)))
        title = _text(item.get("title"), "阶段标题", 200, True)
        task_ids = item.get("task_ids")
        if not isinstance(task_ids, list) or not 1 <= len(task_ids) <= 50:
            raise ManagedError("每个阶段需要 1 至 50 个任务")
        cleaned = []
        for tid in task_ids:
            value = _ensure_task(tasks, tid, "阶段任务")
            if value not in cleaned:
                cleaned.append(value)
        stage_id = _text(item.get("stage_id"), "阶段ID", 64) or f"st_{uuid.uuid4().hex[:8]}"
        if not _STAGE_ID_RE.fullmatch(stage_id):
            raise ManagedError("阶段ID只允许字母、数字、下划线、短横线")
        if stage_id in seen_ids:
            raise ManagedError(f"阶段ID重复：{stage_id}")
        seen_ids.add(stage_id)
        out.append(
            {
                "stage_id": stage_id,
                "title": title,
                "task_ids": cleaned,
                "due": _due(item.get("due")),
                "timezone": _timezone(item.get("timezone")),
                "priority": _integer(item.get("priority", 0), "阶段优先级", PRIORITY_MIN, PRIORITY_MAX),
                "source_quote": _text(item.get("source_quote"), "阶段来源原话", 2000),
                "reason": _text(item.get("reason"), "阶段理由", 500),
            }
        )
    return out


def _overrides(raw, tasks: dict, existing: dict, source: str) -> dict:
    merged = copy.deepcopy(existing or {})
    if raw is None:
        return merged
    if not isinstance(raw, list) or len(raw) > 200:
        raise ManagedError("任务优先级最多 200 条")
    for item in raw:
        if not isinstance(item, dict):
            raise ManagedError("任务优先级必须是对象")
        unknown = set(item) - _OVERRIDE_KEYS
        if unknown:
            raise ManagedError("任务优先级含不支持的字段：" + ", ".join(sorted(unknown)))
        tid = _ensure_task(tasks, item.get("task_id"), "任务")
        current = merged.get(tid) or {}
        if current.get("locked") and source != "human":
            raise ManagedError(f"任务 {tid} 的优先级已被人工锁定，AI 不能覆盖", 409)
        merged[tid] = {
            "priority": _integer(item.get("priority", current.get("priority", 0)), "任务优先级", PRIORITY_MIN, PRIORITY_MAX),
            "locked": _bool(item.get("locked", current.get("locked", False)), "任务锁定"),
            "reason": _text(item.get("reason", current.get("reason")), "任务优先级理由", 500),
            "source": source,
            "updated_at": now_iso(),
        }
    return merged


def _rules(raw, base: dict) -> dict:
    rules = copy.deepcopy(base)
    if raw is None:
        return rules
    if not isinstance(raw, dict):
        raise ManagedError("资源规则必须是对象")
    unknown = set(raw) - set(base)
    if unknown:
        raise ManagedError("资源规则含不支持的字段：" + ", ".join(sorted(unknown)))
    if "queues_allowed" in raw:
        rules["queues_allowed"] = _queue_list(raw.get("queues_allowed"), "允许队列")
    if "queues_denied" in raw:
        rules["queues_denied"] = _queue_list(raw.get("queues_denied"), "禁用队列")
    overlap = set(rules["queues_allowed"]) & set(rules["queues_denied"])
    if overlap:
        raise ManagedError("队列不能既允许又禁用：" + ", ".join(sorted(overlap)))
    if "paid_allowed" in raw:
        rules["paid_allowed"] = _bool(raw.get("paid_allowed"), "付费队列开关")
    if "soft_kill" in raw:
        rules["soft_kill"] = _bool(raw.get("soft_kill"), "软结束开关")
    for key, (low, high) in _RULE_LIMITS.items():
        if key in raw:
            if key in ("max_walltime_hours", "max_core_hours"):
                rules[key] = _number(raw.get(key), key, low, high)
            else:
                rules[key] = _integer(raw.get(key), key, int(low), int(high))
    return rules


# ------------------------------------------------------------------ 审计


def _audit(user, project: dict, action: str, plan: dict, reason: str, details: dict | None = None) -> None:
    try:
        import permissions
        from automation import audit

        audit.write(
            action=action,
            status="success",
            project=str(project.get("name") or plan.get("project") or ""),
            trigger="managed",
            trigger_id=str(plan.get("id") or ""),
            reason=reason,
            username=permissions.username_of(user),
            details=details or {},
        )
    except Exception:  # noqa: BLE001 - 审计失败不影响已落库的计划
        pass


# ------------------------------------------------------------------ 对外操作


def public(plan: dict) -> dict:
    return copy.deepcopy(plan)


def create(user, payload: dict) -> dict:
    """创建托管计划；只接受结构化字段，不替用户编造未提供的目标。"""
    if not isinstance(payload, dict):
        raise ManagedError("参数必须是对象")
    unknown = set(payload) - {"project", "goal", "stages", "task_overrides", "resource_rules"}
    if unknown:
        raise ManagedError("不支持的字段：" + ", ".join(sorted(unknown)))
    import auth

    project = _project(payload.get("project"), user)
    tasks = _task_map(project)
    goal = payload.get("goal")
    if not isinstance(goal, dict):
        raise ManagedError("缺少 goal（用户原话与目标摘要）")
    unknown = set(goal) - {"text", "summary"}
    if unknown:
        raise ManagedError("goal 含不支持的字段：" + ", ".join(sorted(unknown)))
    plan = {
        "id": "plan_" + uuid.uuid4().hex[:16],
        "schema": SCHEMA,
        "project": str(project.get("name")),
        "server": str(project.get("server") or ""),
        "owner": auth.normalize_username(project.get("owner")),
        "status": "active",
        "goal": {
            "text": _text(goal.get("text"), "用户原话", 2000, True),
            "summary": _text(goal.get("summary"), "目标摘要", 500),
        },
        "stages": _stages(payload.get("stages"), tasks),
        "task_overrides": _overrides(payload.get("task_overrides"), tasks, {}, "human"),
        "resource_rules": _rules(payload.get("resource_rules"), DEFAULT_RESOURCE_RULES),
        "revision": 1,
        "history": [],
        "created_by": _username(user),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    _append_history(plan, user, "human", "create", f"创建计划：{plan['goal']['summary'] or plan['goal']['text'][:60]}")
    with _locked_doc():
        doc = _load()
        doc["plans"][plan["id"]] = plan
        from automation.store import _write_json

        _write_json(FILE, doc)
    _audit(user, project, "managed.plan.create", plan, "创建托管计划",
           {"stages": len(plan["stages"]), "tasks": len(plan["task_overrides"])})
    return public(plan)


def get(plan_id: str, user) -> dict:
    pid = _text(plan_id, "计划ID", 100, True)
    doc = _load()
    plan = doc["plans"].get(pid)
    if plan is None:
        raise ManagedError("托管计划不存在", 404)
    _ensure_owner(plan, user)
    return public(plan)


def list_plans(user, project: str | None = None) -> list:
    import permissions
    from storage import load_db

    db = load_db()
    names = {str(p.get("name")) for p in permissions.visible_projects(db, user)}
    if project:
        names &= {_text(project, "项目", 200, True)}
    plans = [copy.deepcopy(p) for p in _load()["plans"].values() if str(p.get("project")) in names]
    plans.sort(key=lambda p: str(p.get("updated_at") or ""), reverse=True)
    return plans


def patch(plan_id: str, user, revision, changes: dict, source: str = "human") -> dict:
    """按版本号修改计划；人工可以覆盖锁定，AI 不能。"""
    if source not in SOURCES:
        raise ManagedError("修改来源无效")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ManagedError("缺少计划版本号 revision")
    if not isinstance(changes, dict) or not changes:
        raise ManagedError("没有要修改的内容")
    unknown = set(changes) - _PATCH_KEYS
    if unknown:
        raise ManagedError("不支持的修改字段：" + ", ".join(sorted(unknown)))
    pid = _text(plan_id, "计划ID", 100, True)
    with _locked_doc():
        doc = _load()
        plan = doc["plans"].get(pid)
        if plan is None:
            raise ManagedError("托管计划不存在", 404)
        project = _ensure_owner(plan, user)
        if plan.get("revision") != revision:
            raise ManagedError("计划已被更新，请重新读取后再改", 409)
        if plan.get("status") == "ended":
            raise ManagedError("计划已结束，请新建计划", 409)
        tasks = _task_map(project)
        summary = []
        if "status" in changes:
            status = changes["status"]
            if status not in PLAN_STATUSES or status == "ended" and source != "human":
                raise ManagedError("状态只能是 active/paused；结束计划需人工操作")
            plan["status"] = status
            summary.append(f"状态改为 {status}")
        if "goal_summary" in changes:
            plan["goal"]["summary"] = _text(changes.get("goal_summary"), "目标摘要", 500)
            summary.append("更新目标摘要")
        if "stages" in changes:
            plan["stages"] = _stages(changes.get("stages"), tasks)
            summary.append(f"阶段改为 {len(plan['stages'])} 个")
        if "task_overrides" in changes:
            plan["task_overrides"] = _overrides(changes.get("task_overrides"), tasks, plan.get("task_overrides") or {}, source)
            summary.append("更新任务优先级")
        if "resource_rules" in changes:
            plan["resource_rules"] = _rules(changes.get("resource_rules"), plan.get("resource_rules") or DEFAULT_RESOURCE_RULES)
            summary.append("更新资源规则")
        _append_history(plan, user, source, "patch", "；".join(summary) or "修改计划")
        plan["revision"] = int(plan.get("revision") or 0) + 1
        plan["updated_at"] = now_iso()
        from automation.store import _write_json

        _write_json(FILE, doc)
    _audit(user, project, "managed.plan.patch", plan, "；".join(summary) or "修改计划", {"changes": sorted(changes)})
    return public(plan)


def set_status(plan_id: str, user, status: str) -> dict:
    return patch(plan_id, user, _revision_of(plan_id, user), {"status": status}, source="human")


def set_task_priority(plan_id: str, user, task_id: str, priority=None, locked=None, reason: str = "", source: str = "human") -> dict:
    """单独设置任务优先级/锁定；AI 调用时 source='ai'，人工锁定不可被 AI 覆盖。"""
    item = {"task_id": task_id}
    if priority is not None:
        item["priority"] = priority
    if locked is not None:
        item["locked"] = locked
    if reason:
        item["reason"] = reason
    return patch(plan_id, user, _revision_of(plan_id, user), {"task_overrides": [item]}, source=source)


def _revision_of(plan_id: str, user) -> int:
    return int(get(plan_id, user).get("revision") or 1)


def _append_history(plan: dict, user, source: str, action: str, detail: str) -> None:
    history = plan.setdefault("history", [])
    history.append({"at": now_iso(), "by": _username(user), "source": source, "action": action, "detail": detail[:1000]})
    del history[:-50]


def _username(user) -> str:
    try:
        import permissions

        return permissions.username_of(user)
    except Exception:  # noqa: BLE001
        return ""
