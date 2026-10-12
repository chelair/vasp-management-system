"""AI 消费视图（规范化）：把报告结构化数据整理成**字段/枚举/单位/时间都统一**的一份视图。

背景（2026-10-12 审查结论）：
- 同一个 `status` 在不同 payload 里有四种含义（任务 / 巡检行 / 归档 / 最新输出目录）；
- `created_at` 与 `createdAt` 并存；能量在不同面叫 `last_energy` / `last_energy_ev`；
- 时间有无偏移不明确（历史数据是本地时间）。

本模块**只做加法**：既有字段一个不动（前端/既有消费方零影响），
只在报告里多挂一份 `ai_view`，供 AI / 大模型读取。规则见 `report_schema.schema_manifest()`。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from report_schema import (
    FIELD_ALIASES,
    LOW_PRECISION_POLICY,
    SCHEMA_VERSION,
    STATUS_FAMILIES,
    TIME_FORMAT,
    UNITS,
)

#: 本地时区（Asia/Shanghai = UTC+8，无夏令时）
LOCAL_TZ = timezone(timedelta(hours=8))


def iso_local(value: Any) -> Optional[str]:
    """把历史时间字符串规范成 `YYYY-MM-DDTHH:mm:ss+08:00`（纯日期原样返回）。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=LOCAL_TZ).isoformat()
        except ValueError:
            continue
    if len(text) == 10 and text[4] == "-":  # 纯日期
        return text
    return text  # 认不出来就原样保留，别猜


def normalize_task_status(status: Any) -> Dict[str, Any]:
    """任务状态规范化：`low_precision` → `completed` + 精度问题（用户确认口径）。"""
    text = str(status or "").strip()
    if text == "low_precision":
        return {"task_status": "completed", "precision_ok": False, "raw_status": text}
    return {
        "task_status": text or "pending",
        "precision_ok": True,
        "raw_status": text or None,
    }


def _project_block(doc: Dict[str, Any]) -> Dict[str, Any]:
    info = doc.get("basic_info") or {}
    meta = doc.get("metadata") or {}
    return {
        "project_id": info.get("project_id") or meta.get("project_id") or "",
        "name": info.get("project_name") or meta.get("project_name") or "",
        "delivery_date": info.get("deadline") or "",  # 纯日期 YYYY-MM-DD
        "calc_description": info.get("calc_description") or "",
        "expected_results": info.get("expected_results") or "",
        "project_status": info.get("project_status") or "normal",
        "progress_percent": info.get("progress_percent"),
        "weighted_progress_percent": info.get("weighted_progress_percent"),
        "generated_at": iso_local(info.get("generated_at")),
    }


def _task_block(row: Dict[str, Any]) -> Dict[str, Any]:
    norm = normalize_task_status(row.get("status"))
    return {
        "task_id": row.get("task_id"),
        "task_name": row.get("task_name") or row.get("model_name") or "",
        "task_type": row.get("task_type"),
        "task_status": norm["task_status"],
        "precision_ok": norm["precision_ok"],
        "raw_status": norm["raw_status"],
        "latest_output_dir": row.get("latest_output_dir") or "",
        "last_energy_ev": row.get("last_energy_ev", row.get("last_energy")),
        "force_max_ev_per_a": row.get("force_max_ev_per_a", row.get("force_max")),
        "force_rms_ev_per_a": row.get("force_rms_ev_per_a", row.get("force_rms")),
        "ionic_steps": row.get("ionic_steps"),
        "force_converged": row.get("force_converged"),
        "continuation_count": row.get("continuation_count"),
        "job_id": row.get("job_id"),
        "remote_dir": row.get("remote_dir") or "",
    }


def build_ai_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """把报告结构化数据 → 规范化 AI 视图（**不修改入参**）。"""
    science = doc.get("science") or {}
    appendix = doc.get("appendix") or {}
    # 任务清单：报告附录里的 all_tasks（含最新能量/力，单位已在键名里）
    tasks = [_task_block(t) for t in (appendix.get("all_tasks") or [])]

    opt = [
        {
            "task_id": item.get("task_id"),
            "task_name": item.get("task_name"),
            "task_status": normalize_task_status(item.get("status"))["task_status"],
            "converged": bool(item.get("converged")),
            "ionic_steps": item.get("ionic_steps"),
            "final_energy_ev": item.get("final_energy_ev"),
            "force_max_ev_per_a": item.get("force_max_ev_per_a"),
            "energy_force_series": [
                {
                    "step": p.get("step"),
                    "energy_ev": p.get("energy"),
                    "force_max_ev_per_a": p.get("max_force"),
                }
                for p in (item.get("energy_force_series") or [])
            ],
            "analysis_note": item.get("analysis_note") or "",
            "paper_note": item.get("paper_note") or "",
        }
        for item in (science.get("opt") or [])
    ]
    free_energy = [
        {
            "path": path.get("group_name"),
            "chart": path.get("chart"),
            "steps": [
                {
                    "label": s.get("structure_label"),
                    "task_status": normalize_task_status(s.get("opt_status"))["task_status"],
                    "dft_energy_ev": s.get("dft_energy_ev"),
                    "correction_ev": s.get("correction_ev"),
                    "free_energy_ev": s.get("free_energy_ev"),
                    "converged": bool(s.get("converged")),
                    "corrected": bool(s.get("corrected")),
                }
                for s in (path.get("structures") or [])
            ],
        }
        for path in (science.get("free_energy") or [])
    ]
    neb = [
        {
            "task_id": item.get("task_id"),
            "task_name": item.get("task_name"),
            "barrier_ev": item.get("barrier_ev"),
            "transition_state_image": item.get("transition_state_image"),
            "images": [
                {
                    "label": img.get("label"),
                    "relative_energy_ev": img.get("relative_energy_ev"),
                    "energy_ev": img.get("energy_ev"),
                    "force_max_ev_per_a": img.get("max_force_ev_per_a"),
                }
                for img in (item.get("images") or [])
            ],
        }
        for item in (science.get("neb") or [])
    ]

    risks = [
        {
            "risk_id": item.get("risk_id"),
            "rule_id": item.get("rule_id"),
            "risk_type": item.get("risk_type"),
            "severity": item.get("severity"),
            "scope": item.get("scope"),
            "target": item.get("target"),
            "description": item.get("description"),
            "advice": item.get("advice"),
            "affected_tasks": [
                t.get("task_id") for t in (item.get("affected_tasks") or [])
            ],
        }
        for item in ((doc.get("risks") or {}).get("items") or [])
    ]
    actions = [
        {
            "action_id": item.get("action_id"),
            "priority": item.get("priority"),
            "task_id": item.get("task_id"),
            "task_name": item.get("task_name"),
            "action": item.get("action"),
            "reason": item.get("reason"),
            "estimated_hours": item.get("estimated_hours"),
            "risk_id": item.get("risk_id"),
        }
        for item in ((doc.get("actions") or {}).get("items") or [])
    ]

    return {
        "contract": {
            "schema_version": SCHEMA_VERSION,
            "units": UNITS,
            "time_format": TIME_FORMAT,
            "status_families": STATUS_FAMILIES,
            "field_aliases": FIELD_ALIASES,
            "low_precision_policy": LOW_PRECISION_POLICY,
            "note": "本视图键名统一 snake_case；能量 eV、力 eV/Å、时间本地带 +08:00；"
            "状态字段带族名，别再用裸 `status`",
        },
        "generated_at": iso_local((doc.get("basic_info") or {}).get("generated_at")),
        "project": _project_block(doc),
        "summary": {
            "task_stats": (doc.get("executive_summary") or {}).get("task_stats") or {},
            "summary_text": (doc.get("executive_summary") or {}).get("summary_text") or "",
            "key_findings": ((doc.get("llm_context") or {}).get("key_findings") or []),
            "open_questions": ((doc.get("llm_context") or {}).get("open_questions") or []),
        },
        "tasks": tasks,
        "science": {"opt": opt, "free_energy": free_energy, "neb": neb},
        "risks": risks,
        "actions": actions,
        "notes": doc.get("notes") or {},
    }
