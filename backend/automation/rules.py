"""规则层：加载规则、构建任务上下文、匹配条件、解析定时 scope。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from storage import load_db
from task_paths import free_energy_frac_task, is_continuation_task

from automation import store

#: 条件里不能出现这些"仅供内部"的键
_RESERVED = {"trigger", "action", "guard", "enabled", "id", "description"}

#: 允许出现在 condition 里的字段（与 build_context() 的输出对齐；未知字段会被拒绝，
#: 否则规则会静默地永不命中）
CONDITION_KEYS = {
    "task_id", "model_name", "task_type", "status", "job_id",
    "project", "project_id", "owner",
    "is_continuation", "archived", "converged",
    "group_type", "group_role", "group_id", "group_name",
    "source_dir",
    "frac_task_id", "frac_status", "frac_missing",
    "initial_task_id", "final_task_id", "initial_converged", "final_converged",
    "images_created",
}


def build_context(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """任务的判定上下文（规则 condition 里能用的字段都来自这里）。"""
    group = task.get("group") or {}
    group_type = group.get("group_type")
    status = str(task.get("status") or "")
    ctx: Dict[str, Any] = {
        "task_id": str(task.get("task_id") or ""),
        "model_name": str(task.get("model_name") or ""),
        "task_type": str(task.get("task_type") or ""),
        "status": status,
        "job_id": task.get("job_id"),
        "project": str(project.get("name") or ""),
        "project_id": str(project.get("project_id") or ""),
        "owner": project.get("owner"),
        "is_continuation": is_continuation_task(task),
        "archived": status == "archived",
        # opt / frac / ele：completed 即视为已收敛；unconverged / zombied 未收敛
        "converged": status == "completed",
        "group_type": group_type,
        "group_role": group.get("group_role"),
        "group_id": group.get("group_id"),
        "group_name": group.get("name"),
        "source_dir": task.get("continuation_dir") or task.get("remote_dir"),
    }

    frac = free_energy_frac_task(project, task) if group_type == "free_energy" else None
    ctx["frac_task_id"] = (frac or {}).get("task_id")
    ctx["frac_status"] = (frac or {}).get("status")
    # frac 子任务存在但还没开始 → 缺 frac 输入
    ctx["frac_missing"] = bool(frac) and str(frac.get("status") or "pending") in ("pending", "queued")

    if group_type == "neb":
        members = [
            t
            for t in project.get("tasks", [])
            if (t.get("group") or {}).get("group_id") == group.get("group_id")
        ]
        initial = next(
            (t for t in members if (t.get("group") or {}).get("group_role") == "initial_opt"),
            None,
        )
        final = next(
            (t for t in members if (t.get("group") or {}).get("group_role") == "final_opt"),
            None,
        )
        ctx["initial_task_id"] = (initial or {}).get("task_id")
        ctx["final_task_id"] = (final or {}).get("task_id")
        ctx["initial_converged"] = str((initial or {}).get("status") or "") == "completed"
        ctx["final_converged"] = str((final or {}).get("status") or "") == "completed"
        # 建过映像后接口会写 input_source（poscar_from=.../CONTCAR）
        ctx["images_created"] = bool(task.get("input_source"))
    return ctx


def condition_matches(condition: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[bool, str]:
    """返回 (是否命中, 未命中原因)。上下文缺字段视为未命中（不猜）。"""
    for key, expected in (condition or {}).items():
        if key in _RESERVED:
            continue
        if key not in ctx:
            return False, f"上下文缺少字段 {key}"
        actual = ctx.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False, f"{key}={actual!r} 不在 {list(expected)} 内"
        elif isinstance(expected, bool):
            if bool(actual) != expected:
                return False, f"{key}={actual!r} 与期望 {expected} 不符"
        elif actual != expected:
            return False, f"{key}={actual!r} 与期望 {expected!r} 不符"
    return True, ""


def trigger_type(rule: Dict[str, Any]) -> str:
    return str((rule.get("trigger") or {}).get("type") or "")


def enabled_rules() -> List[Dict[str, Any]]:
    settings = store.load_settings()
    disabled = {str(x) for x in settings.get("disabled_rules") or []}
    return [
        rule
        for rule in store.load_rules()
        if rule.get("enabled") and str(rule.get("id")) not in disabled
    ]


def resolve_scope(db: Dict[str, Any], scope: Optional[str]) -> Iterable[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """定时规则的目标范围：`all` / `project:<名称>`；只返回可见性无关的全部任务。"""
    text = str(scope or "all").strip()
    for project in db.get("projects", []):
        if text not in ("all", "*") and text != f"project:{project.get('name')}":
            continue
        for task in project.get("tasks", []):
            yield project, task


def match_task(
    rule: Dict[str, Any], project: Dict[str, Any], task: Dict[str, Any]
) -> Tuple[bool, str, Dict[str, Any]]:
    ctx = build_context(project, task)
    ok, reason = condition_matches(rule.get("condition") or {}, ctx)
    return ok, reason, ctx


def schedules() -> List[Dict[str, Any]]:
    """定时规则清单（含 cron / scope），供前端"定时任务"列表与调度线程使用。"""
    out = []
    for rule in store.load_rules():
        if trigger_type(rule) != "schedule":
            continue
        trigger = rule.get("trigger") or {}
        mode = str(trigger.get("mode") or ("cron" if trigger.get("cron") else "after"))
        out.append(
            {
                "id": rule.get("id"),
                "enabled": bool(rule.get("enabled")),
                "mode": mode,
                "cron": str(trigger.get("cron") or ""),
                "after_seconds": trigger.get("after_seconds"),
                "scope": str(trigger.get("scope") or "all"),
                "action": rule.get("action"),
                "condition": rule.get("condition") or {},
                "guard": rule.get("guard") or {},
                "description": rule.get("description"),
            }
        )
    return out
