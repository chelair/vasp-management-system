"""托管计划工具：AI 只写结构化意图（计划/优先级/资源规则），不能提交或停止作业。

与 `topic_tools` 同一套受限合同：参数必须完全匹配声明，未知字段直接拒绝；
真正的执行仍走 `automation.gateway`，且受执行开关与授权约束。
"""

from __future__ import annotations

import managed_plan
import managed_schedule

_TOOL_KEYS = ("goal", "stages", "task_overrides", "resource_rules")


def tool(name, description, properties, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required),
                           "additionalProperties": False},
        },
    }


STAGE = {
    "type": "object",
    "properties": {
        "stage_id": {"type": "string", "maxLength": 64},
        "title": {"type": "string", "maxLength": 200},
        "task_ids": {"type": "array", "items": {"type": "string", "maxLength": 200}, "minItems": 1, "maxItems": 50},
        "due": {"type": "string", "maxLength": 40},
        "timezone": {"type": "string", "maxLength": 64},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        "source_quote": {"type": "string", "maxLength": 2000},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["title", "task_ids"],
    "additionalProperties": False,
}

OVERRIDE = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "maxLength": 200},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        "locked": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["task_id"],
    "additionalProperties": False,
}

RULES = {
    "type": "object",
    "properties": {
        "queues_allowed": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 20},
        "queues_denied": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 20},
        "paid_allowed": {"type": "boolean"},
        "max_nodes": {"type": "integer", "minimum": 1, "maximum": 64},
        "max_cores": {"type": "integer", "minimum": 1, "maximum": 100000},
        "cores_per_node": {"type": "integer", "minimum": 1, "maximum": 1024},
        "max_walltime_hours": {"type": "number", "minimum": 0.1, "maximum": 720},
        "max_core_hours": {"type": "number", "minimum": 0.1, "maximum": 10000000},
        "max_submissions": {"type": "integer", "minimum": 1, "maximum": 1000},
        "soft_kill": {"type": "boolean"},
    },
    "additionalProperties": False,
}

TOOLS = [
    tool(
        "get_managed_plans",
        "只读查看当前项目的托管计划、任务优先级、阶段交付与候选排序（不触发SSH、不提交）。用户问“现在排到哪/为什么还没开始/下一步是什么”时先用它。",
        {"plan_id": {"type": "string", "maxLength": 100}},
    ),
    tool(
        "create_managed_plan",
        "把用户一句话目标保存成项目托管计划：阶段交付、任务级优先级、允许的队列与额度上限。只写结构化意图，不提交作业；用户没说清楚的（目标、队列、额度）不要编造，直接问。同一个项目已有计划时不要重复建，改用 update_managed_plan。",
        {"goal": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 2000},
                                                    "summary": {"type": "string", "maxLength": 500}},
                  "required": ["text"], "additionalProperties": False},
         "stages": {"type": "array", "items": STAGE, "maxItems": 20},
         "task_overrides": {"type": "array", "items": OVERRIDE, "maxItems": 200},
         "resource_rules": RULES},
        ("goal",),
    ),
    tool(
        "update_managed_plan",
        "修改已有托管计划：暂停/恢复、调整阶段与交付时间、改任务优先级、改资源规则。AI不能结束计划（ended），也不能覆盖人工锁定的任务优先级；被拒绝时如实告诉用户。",
        {"plan_id": {"type": "string", "maxLength": 100},
         "revision": {"type": "integer", "minimum": 1},
         "status": {"type": "string", "enum": ["active", "paused"]},
         "goal_summary": {"type": "string", "maxLength": 500},
         "stages": {"type": "array", "items": STAGE, "maxItems": 20},
         "task_overrides": {"type": "array", "items": OVERRIDE, "maxItems": 200},
         "resource_rules": RULES},
        ("plan_id", "revision"),
    ),
    tool(
        "set_task_priority",
        "单独调整某个任务的优先级或锁定状态（例如用户说“这个任务这周先做”“别再动这个任务”）。人工锁定的任务AI不能改，只能提示用户。",
        {"plan_id": {"type": "string", "maxLength": 100},
         "revision": {"type": "integer", "minimum": 1},
         "task_id": {"type": "string", "maxLength": 200},
         "priority": {"type": "integer", "minimum": 0, "maximum": 100},
         "locked": {"type": "boolean"},
         "reason": {"type": "string", "maxLength": 500}},
        ("plan_id", "revision", "task_id"),
    ),
]


def _spec(name):
    return next(t["function"]["parameters"] for t in TOOLS if t["function"]["name"] == name)


def _validate(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须为对象")
    spec = _spec(name)
    extra = set(arguments) - set(spec["properties"])
    if extra:
        raise ValueError("托管工具不接受字段：" + ", ".join(sorted(extra)))
    missing = set(spec["required"]) - set(arguments)
    if missing:
        raise ValueError("托管工具缺少字段：" + ", ".join(sorted(missing)))


def _plan_of(project, plan_id, user):
    plan = managed_plan.get(str(plan_id), user)
    if str(plan.get("project")) != str(project.get("name")):
        raise ValueError("该托管计划不属于当前项目")
    return plan


def dispatch(project, user, name, arguments):
    _validate(name, arguments)
    if name == "get_managed_plans":
        plan_id = arguments.get("plan_id")
        if plan_id:
            plan = _plan_of(project, plan_id, user)
            return {"plan": managed_plan.public(plan), "summary": managed_schedule.summary(plan, project)}
        items = []
        for plan in managed_plan.list_plans(user, project=str(project.get("name"))):
            summary = managed_schedule.summary(plan, project)
            items.append({
                "plan_id": plan.get("id"),
                "status": plan.get("status"),
                "revision": plan.get("revision"),
                "goal": plan.get("goal"),
                "next": summary.get("next"),
                "counts": summary.get("counts"),
                "needs_user": summary.get("needs_user"),
            })
        return {"plans": items, "note": "只读；执行开关未开启时不会自动推进"}

    if name == "create_managed_plan":
        payload = {"project": project.get("name")}
        for key in _TOOL_KEYS:
            if key in arguments:
                payload[key] = arguments[key]
        plan = managed_plan.create(user, payload)
        return {"plan": managed_plan.public(plan), "summary": managed_schedule.summary(plan, project),
                "note": "计划已保存；未提交任何作业"}

    plan = _plan_of(project, arguments["plan_id"], user)
    revision = arguments["revision"]
    if name == "update_managed_plan":
        changes = {key: arguments[key] for key in ("status", "goal_summary", "stages", "task_overrides", "resource_rules")
                   if key in arguments}
        if not changes:
            raise ValueError("没有要修改的内容")
        updated = managed_plan.patch(plan["id"], user, revision, changes, source="ai")
        return {"plan": managed_plan.public(updated), "summary": managed_schedule.summary(updated, project),
                "note": "计划已更新；不会自动提交作业"}

    item = {"task_id": arguments["task_id"]}
    for key in ("priority", "locked", "reason"):
        if key in arguments:
            item[key] = arguments[key]
    if len(item) == 1:
        raise ValueError("请给出新的优先级或锁定状态")
    updated = managed_plan.patch(plan["id"], user, revision, {"task_overrides": [item]}, source="ai")
    return {"plan": managed_plan.public(updated), "summary": managed_schedule.summary(updated, project)}
