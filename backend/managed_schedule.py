"""托管候选排序与资源方案评分（确定性函数，不调用模型、不提交作业）。

两层决策，顺序固定：

1. **先排任务**：按"人工覆盖 > 阶段优先级"排序，阶段交付日期只做同日期的次序；
2. **再选资源**：在已授权队列内枚举少量配置，先硬过滤（禁用/付费/超限/布局不合法），
   再用当前快照做启发式评分。

评分只依据一次共享采集的快照（`cluster_probe` / `cluster_status`），
不把空闲核数或队列 PEND 数说成精确等待时间；拿不到真实快照就等待，不猜。
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

READY = ("pending",)
CONTINUE = ("unconverged", "zombied")
IN_FLIGHT = ("queued", "running")

INTENTS = {
    **{s: "first_submit" for s in READY},
    **{s: "continuation" for s in CONTINUE},
    **{s: "in_flight" for s in IN_FLIGHT},
}

_DEFAULT_TZ = "Asia/Shanghai"
_RISK_SCORE = {"low": 6.0, "medium": 0.0, "high": -6.0}
_HEURISTIC = "评分只依据当前集群快照与已授权规则，是启发式排序，不代表精确排队时间，也不承诺更多核更快或更省"


# ------------------------------------------------------------------ 任务层


def _due_epoch(stage) -> float | None:
    if not stage:
        return None
    due = str(stage.get("due") or "").strip()
    if not due:
        return None
    try:
        if len(due) == 10:
            moment = datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=ZoneInfo(stage.get("timezone") or _DEFAULT_TZ))
        else:
            moment = datetime.fromisoformat(due.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=ZoneInfo(stage.get("timezone") or _DEFAULT_TZ))
    except (ValueError, KeyError):
        return None
    return moment.timestamp()


def _stage_map(plan: dict) -> dict:
    """任务 → 阶段；同一任务出现在多个阶段时取交付最早的那个。"""
    picked = {}
    for stage in plan.get("stages") or []:
        epoch = _due_epoch(stage)
        for tid in stage.get("task_ids") or []:
            current = picked.get(tid)
            if current is None:
                picked[tid] = stage
            elif epoch is not None and (_due_epoch(current) is None or epoch < _due_epoch(current)):
                picked[tid] = stage
    return picked


def _priority(plan: dict, task_id: str, stage) -> tuple[int, str, bool]:
    override = (plan.get("task_overrides") or {}).get(task_id)
    if override:
        return int(override.get("priority") or 0), "override", bool(override.get("locked"))
    if stage:
        return int(stage.get("priority") or 0), "stage", False
    return 0, "default", False


def candidates(plan: dict, project: dict) -> list:
    """当前项目里参与托管的候选任务（含不可推进的在跑任务，供界面解释）。"""
    stages = _stage_map(plan)
    rows = []
    for order, task in enumerate(project.get("tasks") or []):
        if task.get("archived") is True:
            continue
        tid = str(task.get("task_id") or "")
        status = str(task.get("status") or "")
        intent = INTENTS.get(status)
        if not tid or not intent:
            continue
        if intent == "in_flight":
            action = None
            reason = "作业已在队列/运行中，等待巡检结果"
        elif intent == "first_submit":
            action = "task.submit"
            reason = "输入已就绪，可首发提交"
        else:
            action = "task.continuation"
            reason = "上次运行未收敛/中断，可续算"
        stage = stages.get(tid)
        priority, source, locked = _priority(plan, tid, stage)
        epoch = _due_epoch(stage)
        if stage and stage.get("due"):
            reason += f"；阶段「{stage.get('title')}」交付 {stage.get('due')}"
        rows.append(
            {
                "task_id": tid,
                "task_name": str(task.get("model_name") or task.get("name") or tid),
                "task_type": str(task.get("task_type") or ""),
                "status": status,
                "intent": intent,
                "action": action,
                "priority": priority,
                "priority_source": source,
                "locked": locked,
                "stage_id": (stage or {}).get("stage_id"),
                "stage_title": (stage or {}).get("title"),
                "due": (stage or {}).get("due") or "",
                "due_epoch": epoch,
                "order": order,
                "reason": reason,
            }
        )
    rows.sort(
        key=lambda r: (
            r["action"] is None,
            -r["priority"],
            r["due_epoch"] if r["due_epoch"] is not None else math.inf,
            r["order"],
        )
    )
    return rows


def summary(plan: dict, project: dict) -> dict:
    rows = candidates(plan, project)
    actionable = [r for r in rows if r["action"]]
    counts = {"ready": 0, "continuation": 0, "in_flight": 0}
    for row in rows:
        key = "ready" if row["intent"] == "first_submit" else row["intent"]
        counts[key] = counts.get(key, 0) + 1
    needs_user = []
    if plan.get("status") == "paused":
        needs_user.append("计划已暂停：不会自动推进")
    if plan.get("status") == "ended":
        needs_user.append("计划已结束：需要新建计划")
    if not actionable and plan.get("status") == "active":
        needs_user.append("暂无可推进任务（没有待提交或待续算任务）")
    return {
        "plan_id": plan.get("id"),
        "project": plan.get("project"),
        "status": plan.get("status"),
        "revision": plan.get("revision"),
        "goal": plan.get("goal"),
        "counts": counts,
        "next": actionable[0] if actionable else None,
        "waiting": actionable[1:],
        "needs_user": needs_user,
        "candidates": rows,
    }


# ------------------------------------------------------------------ 资源层


def freshness(snapshot, now: datetime | None = None, max_age_seconds: int | None = None) -> dict:
    """快照是否可作自动提交依据：必须真实、未过期、足够新。"""
    if not isinstance(snapshot, dict):
        return {"ok": False, "reason": "尚未采集集群快照，无法选资源方案"}
    source = str(snapshot.get("source") or "")
    if source != "real":
        return {"ok": False, "reason": "当前集群状态是模拟数据或缺少真实采集，不能作为自动提交依据"}
    if snapshot.get("stale"):
        return {"ok": False, "reason": "集群快照已被标记为过期，需要重新采集"}
    queried = str(snapshot.get("queriedAt") or "")
    try:
        moment = datetime.fromisoformat(queried)
        if moment.tzinfo is None:
            moment = moment.astimezone()
    except ValueError:
        return {"ok": False, "reason": "集群快照时间无法识别"}
    current = now or datetime.now(moment.tzinfo)
    age = max(0.0, (current - moment).total_seconds())
    limit = max_age_seconds
    if limit is None:
        ttl = snapshot.get("cacheTtlSeconds")
        limit = int(ttl) * 2 if isinstance(ttl, (int, float)) and ttl > 0 else 600
    if age > limit:
        return {"ok": False, "reason": f"集群快照已 {int(age)} 秒未更新（上限 {limit} 秒），需刷新后再选资源"}
    return {"ok": True, "ageSeconds": round(age, 1), "queriedAt": queried, "source": "real"}


def _queue_meta(server_cfg: dict) -> dict:
    meta = {}
    for group in (server_cfg or {}).get("node_groups") or []:
        name = str(group.get("queue") or "").strip()
        if not name:
            continue
        cores = int(group.get("cores_per_node") or 0)
        days = float(group.get("walltime_days") or 0)
        nodes = max(0, int(group.get("end") or 0) - int(group.get("start") or 0) + 1)
        item = meta.setdefault(
            name,
            {"cores_per_node": cores, "walltime_days": days, "paid": False, "risk": "low", "nodes": 0},
        )
        item["cores_per_node"] = min(v for v in (item["cores_per_node"], cores) if v > 0) if cores else item["cores_per_node"]
        item["walltime_days"] = min(v for v in (item["walltime_days"], days) if v > 0) if days else item["walltime_days"]
        item["paid"] = item["paid"] or bool(group.get("paid"))
        if _RISK_SCORE.get(str(group.get("suspend_risk")), 0.0) < _RISK_SCORE.get(item["risk"], 0.0):
            item["risk"] = str(group.get("suspend_risk"))
        item["nodes"] += nodes
    return meta


def _score(meta: dict, live: dict | None, cores: int, nodes: int, walltime: float) -> tuple[float, dict, list]:
    pending = None
    idle = None
    if live:
        pending = (live.get("bqueues") or {}).get("pending")
        idle = live.get("idleCores")
    components = {}
    notes = []
    if isinstance(pending, int):
        components["queue_wait"] = round(-40.0 * min(1.0, pending / 20.0), 2)
    else:
        components["queue_wait"] = 0.0
        notes.append("队列 PEND 数未知，未参与等待评分")
    if isinstance(idle, int):
        components["idle_fit"] = round(25.0 * min(1.0, idle / cores), 2)
    else:
        components["idle_fit"] = 0.0
        notes.append("空闲核数未知")
    components["size"] = round(-8.0 * (nodes - 1), 2)
    components["walltime"] = round(-0.5 * walltime, 2)
    components["core_hours"] = round(-0.02 * cores * walltime, 2)
    components["suspend_risk"] = round(_RISK_SCORE.get(str(meta.get("risk")), 0.0), 2)
    score = round(sum(components.values()), 2)
    return score, components, notes


def _explain(queue: str, meta: dict, live: dict | None, cores: int, ptile: int, nodes: int, walltime: float) -> list:
    parts = [f"队列 {queue}：{nodes} 节点 × {ptile} 核 = {cores} 核，walltime {walltime:g} 小时"]
    pending = (live or {}).get("bqueues", {}).get("pending") if live else None
    if isinstance(pending, int):
        parts.append(f"当前 PEND {pending} 个作业")
    idle = (live or {}).get("idleCores") if live else None
    if isinstance(idle, int):
        parts.append(f"空闲 {idle} 核，{'可覆盖' if idle >= cores else '不足以一次覆盖'}")
    if meta.get("paid"):
        parts.append("付费队列")
    risk = str(meta.get("risk") or "")
    if risk:
        parts.append(f"挂起风险 {risk}")
    return parts


def resource_plan(plan: dict, server_cfg: dict, snapshot, now: datetime | None = None) -> dict:
    """在已授权队列内枚举并评分资源方案（只读；不调用模型、不提交）。"""
    rules = plan.get("resource_rules") or {}
    result = {
        "state": "waiting",
        "reason": "",
        "rules": {
            key: rules.get(key)
            for key in ("queues_allowed", "queues_denied", "paid_allowed", "max_nodes", "max_cores",
                        "cores_per_node", "max_walltime_hours", "max_core_hours", "soft_kill")
        },
        "snapshot": None,
        "candidates": [],
        "filtered": [],
        "heuristic": _HEURISTIC,
    }
    allowed = list(rules.get("queues_allowed") or [])
    denied = set(rules.get("queues_denied") or [])
    if not allowed:
        result["reason"] = "计划未声明可用队列，请先确认这台服务器上允许使用哪些 CPU 队列"
        return result
    health = freshness(snapshot, now)
    result["snapshot"] = health
    if not health.get("ok"):
        result["state"] = "blocked"
        result["reason"] = str(health.get("reason"))
        return result

    meta = _queue_meta(server_cfg)
    live_map = {str(q.get("queue")): q for q in (snapshot.get("queues") or []) if isinstance(q, dict)}
    max_nodes = int(rules.get("max_nodes") or 1)
    max_cores = int(rules.get("max_cores") or 1)
    ptile_cap = int(rules.get("cores_per_node") or 1)
    walltime_cap = float(rules.get("max_walltime_hours") or 1)
    core_hours_cap = float(rules.get("max_core_hours") or 0)

    found = []
    for queue in allowed:
        entry = meta.get(queue)
        if queue in denied:
            result["filtered"].append({"queue": queue, "reason": "用户禁用该队列"})
            continue
        if entry is None:
            result["filtered"].append({"queue": queue, "reason": "服务器节点配置里没有该队列"})
            continue
        if entry.get("paid") and not rules.get("paid_allowed"):
            result["filtered"].append({"queue": queue, "reason": "付费队列，用户要求不使用付费队列"})
            continue
        live = live_map.get(queue)
        if live is not None and int(live.get("nodeCount") or 0) == 0:
            result["filtered"].append({"queue": queue, "reason": "该队列当前没有节点"})
            continue
        ptile = min(ptile_cap, int(entry.get("cores_per_node") or ptile_cap))
        queue_walltime = float(entry.get("walltime_days") or 0) * 24.0
        walltime = min(walltime_cap, queue_walltime) if queue_walltime else walltime_cap
        if walltime <= 0:
            result["filtered"].append({"queue": queue, "reason": "队列 walltime 上限为 0"})
            continue
        queue_nodes = int(entry.get("nodes") or 0)
        if live is not None:
            queue_nodes = min(queue_nodes, int(live.get("nodeCount") or queue_nodes))
        for nodes in range(1, max_nodes + 1):
            cores = nodes * ptile
            if cores > max_cores:
                result["filtered"].append({"queue": queue, "reason": f"{nodes} 节点需要 {cores} 核，超过授权上限 {max_cores} 核"})
                continue
            if int(entry.get("cores_per_node") or 0) and ptile > int(entry["cores_per_node"]):
                result["filtered"].append({"queue": queue, "reason": "每节点核数超过该队列节点上限"})
                continue
            if queue_nodes and nodes > queue_nodes:
                result["filtered"].append({"queue": queue, "reason": f"该队列只有 {queue_nodes} 个节点，无法满足 {nodes} 节点"})
                continue
            core_hours = round(cores * walltime, 3)
            if core_hours_cap and core_hours > core_hours_cap:
                result["filtered"].append({"queue": queue, "reason": f"核时 {core_hours:g} 超过上限 {core_hours_cap:g}"})
                continue
            score, components, notes = _score(entry, live, cores, nodes, walltime)
            found.append(
                {
                    "queue": queue,
                    "paid": bool(entry.get("paid")),
                    "suspend_risk": entry.get("risk"),
                    "cores": cores,
                    "cores_per_node": ptile,
                    "nodes": nodes,
                    "walltime_hours": walltime,
                    "core_hours": core_hours,
                    "score": score,
                    "components": components,
                    "notes": notes,
                    "explain": _explain(queue, entry, live, cores, ptile, nodes, walltime),
                }
            )

    found.sort(key=lambda c: (-c["score"], c["nodes"], c["queue"]))
    result["candidates"] = found[:10]
    if not found:
        result["state"] = "waiting"
        result["reason"] = "按当前规则没有找到可用的资源方案，需要放宽队列/核数/walltime 或等待节点空闲"
    else:
        result["state"] = "ok"
        result["reason"] = f"按当前快照给出 {len(found)} 个候选，推荐第一个"
    return result
