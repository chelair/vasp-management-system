"""风险规则引擎（规则独立于代码，存 data/config/report_rules.json）。

规则是**声明式数据**而非代码：`when` 描述「取哪个事实字段、用什么操作符、比什么值」，
事实由 report_builder 计算成扁平字典后传入。支持 `all` / `any` 组合。

每条规则命中后产出一条风险：
    {risk_id, rule_id, risk_type, severity, scope, target, affected_tasks,
     description, advice, detected_at}
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CONFIG_DIR, DEFAULTS_DIR, ensure_data_dirs

RULES_FILE = CONFIG_DIR / "report_rules.json"
DEFAULT_RULES_FILE = DEFAULTS_DIR / "report_rules.json"
DEFAULT_RULES_VERSION = "1.0.0"

_cache: Dict[str, Any] = {"at": 0.0, "data": None}


def load_rules(force: bool = False) -> Dict[str, Any]:
    """读取规则文件（data/config 优先，缺失时回落到 defaults；60 秒缓存）。"""
    import time

    now = time.time()
    if not force and _cache["data"] and now - _cache["at"] < 60:
        return _cache["data"]
    ensure_data_dirs()
    path = RULES_FILE if RULES_FILE.is_file() else DEFAULT_RULES_FILE
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            raise ValueError("规则文件结构不正确（需要 {rules: [...]}）")
    except Exception:  # noqa: BLE001 - 规则文件损坏时用内置默认，保证报告仍可生成
        data = {"schema_version": DEFAULT_RULES_VERSION, "rules": []}
    data["_source"] = str(path)
    _cache.update({"at": now, "data": data})
    return data


def _compare(fact_value: Any, op: str, target: Any) -> bool:
    if op == "in":
        return fact_value in (target or [])
    if op == "not_in":
        return fact_value not in (target or [])
    if op == "eq":
        return fact_value == target
    if op == "ne":
        return fact_value != target
    if op == "exists":
        return fact_value is not None
    if op == "is_true":
        return fact_value is True
    if op == "is_false":
        return fact_value is False
    if fact_value is None:
        return False
    try:
        left, right = float(fact_value), float(target)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def _match(condition: Dict[str, Any], facts: Dict[str, Any]) -> bool:
    if "all" in condition:
        return all(_match(c, facts) for c in condition["all"])
    if "any" in condition:
        return any(_match(c, facts) for c in condition["any"])
    field = str(condition.get("field") or "")
    return _compare(facts.get(field), str(condition.get("op") or "eq"), condition.get("value"))


def _render(template: str, facts: Dict[str, Any]) -> str:
    """安全格式化：未知占位符原样保留为 '-'，避免抛错。"""
    out = template or ""
    for key, value in facts.items():
        token = "{" + key + "}"
        if token in out:
            shown = "—" if value is None or value == "" else value
            out = out.replace(token, str(shown))
    return out


def evaluate(
    task_facts: List[Dict[str, Any]],
    project_facts: Dict[str, Any],
    *,
    rules: Optional[Dict[str, Any]] = None,
    detected_at: str = "",
) -> List[Dict[str, Any]]:
    """按规则表产出风险列表（已按严重程度排序、按规则上限截断）。"""
    table = rules or load_rules()
    items: List[Dict[str, Any]] = []
    sequence = 0
    for rule in table.get("rules", []):
        scope = str(rule.get("scope") or "task")
        condition = rule.get("when") or {}
        max_items = int(rule.get("max_items") or 10)
        matched: List[Any] = []
        if scope == "task":
            matched = [f for f in task_facts if _match(condition, f)]
        elif scope == "project":
            if _match(condition, project_facts):
                matched = [project_facts]
        for fact in matched[:max_items]:
            sequence += 1
            task_id = str(fact.get("task_id") or "") if scope == "task" else ""
            items.append(
                {
                    "risk_id": f"RK{sequence:03d}",
                    "rule_id": str(rule.get("rule_id") or ""),
                    "risk_type": str(rule.get("risk_type") or "convergence"),
                    "severity": str(rule.get("severity") or "medium"),
                    "scope": scope,
                    "affected_tasks": (
                        [
                            {
                                "task_id": task_id,
                                "task_name": str(fact.get("task_name") or ""),
                                "task_type": str(fact.get("task_type") or ""),
                            }
                        ]
                        if task_id
                        else []
                    ),
                    "target": (
                        str(fact.get("task_name") or "")
                        if scope == "task"
                        else str(project_facts.get("project_name") or "")
                    ),
                    "description": _render(str(rule.get("description") or ""), fact),
                    "advice": _render(str(rule.get("advice") or ""), fact),
                    "detected_at": detected_at,
                }
            )
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda r: (order.get(r["severity"], 9), r["rule_id"]))
    for index, item in enumerate(items, start=1):
        item["risk_id"] = f"RK{index:03d}"
    return items


def rules_meta() -> Dict[str, Any]:
    table = load_rules()
    return {
        "schema_version": table.get("schema_version", DEFAULT_RULES_VERSION),
        "source": table.get("_source"),
        "count": len(table.get("rules", [])),
        "rule_ids": [r.get("rule_id") for r in table.get("rules", [])],
    }


def priority_for(severity: str) -> str:
    return {"high": "P0", "medium": "P1", "low": "P2"}.get(severity, "P2")
