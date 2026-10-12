"""任务上下文 `task_context`（2026-10-13）：把散落各处的素材聚合成**一份只读快照**。

AI 决策时只读这一份。素材来源全部在本地，按需计算、可选落盘缓存：
- 任务元数据 → `data/projects.json`（tasks[]，含 group / input_state / current_output / 归档痕迹）
- 最近 N 轮巡检 → `data/checks/check_results_*.json`（`checks_store.collect_task_history`）
- 最近 N 次动作 → `data/audit/actions.jsonl`（把 `username` 规范成 `actor` + `actor_kind`）
- 文件摘要 → `<任务>/files/`（清单、INCAR 关键参数）+ `<任务>/reports/*_tail.txt`（归档时切好的 OUTCAR/result 尾部）
- 人工痕迹 → `input_state.changes`（带 applied_at/in）、`archived_at/from`、`reopened_at`、巡检 notes
- 项目级 `calc_description` / `expected_results`（AI 生成报告分析的**输入**）

命名/单位/时间沿用 2026-10-12 定的契约：snake_case、状态带族名、能量 eV、时间本地 `+08:00`。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_view import iso_local
from checks_store import CHECKS_DIR, collect_task_history
from config import DATA_DIR
from report_schema import SCHEMA_VERSION, STATUS_FAMILIES, UNITS
from task_files_summary import read_task_file_summaries
from task_paths import task_dir

#: 动作历史来源
AUDIT_FILE = DATA_DIR / "audit" / "actions.jsonl"


def _actor_kind(username: Any) -> str:
    """审计里的 `username` → 角色类别：真人 / 自动化 / 系统（后台线程写 `-`）。"""
    text = str(username or "").strip()
    if text in ("", "-"):
        return "system"
    if text == "automation":
        return "automation"
    return "user"


def _actions_for(task_id: str, limit: int) -> List[Dict[str, Any]]:
    """最近 N 条动作（新 → 旧）。审计是 JSONL，按行倒着找。"""
    if not AUDIT_FILE.is_file() or limit <= 0:
        return []
    found: List[Dict[str, Any]] = []
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        if f'"{task_id}"' not in line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001 - 单行损坏跳过
            continue
        if rec.get("task_id") != task_id:
            continue
        found.append(
            {
                "at": iso_local(rec.get("at")),
                "actor": str(rec.get("username") or "-"),
                "actor_kind": _actor_kind(rec.get("username")),
                "command": rec.get("command"),
                "result": str(rec.get("result") or "")[:400],
                "remote_dir": rec.get("remote_dir") or "",
            }
        )
        if len(found) >= limit:
            break
    return found


def _check_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """把一轮巡检原始条目压成上下文要的最小字段（单位/命名统一）。"""
    precision = entry.get("precision") or {}
    status = str(entry.get("status") or "")
    return {
        "checked_at": iso_local(entry.get("checked_at")),
        "task_status": "completed" if status == "low_precision" else status,
        "raw_status": status or None,
        "energy_ev": entry.get("last_energy"),
        "force_max_ev_per_a": entry.get("force_max"),
        "force_rms_ev_per_a": entry.get("force_rms"),
        "converged": entry.get("force_converged"),
        "precision_ok": precision.get("ok"),
        "precision_issues": precision.get("issues") or [],
        "queue_state": entry.get("queue_status"),
        "output_state": (entry.get("current_output") or {}).get("status"),
        "output_dir": (entry.get("current_output") or {}).get("latest_dir"),
        "error_messages": (entry.get("error_messages") or [])[:5],
        "markers": (entry.get("markers") or [])[:5],
    }


def _fingerprint(project_name: str, task: Dict[str, Any]) -> str:
    """输入指纹：任务更新时间、镜像来源、最近巡检、审计文件、关键本地文件任一变化就变。"""
    parts: List[str] = [
        str(task.get("status") or ""),
        str(task.get("archived_at") or ""),
        str((task.get("input_state") or {}).get("source", {}).get("synced_at") or ""),
        str(task.get("last_check_time") or ""),
    ]
    try:
        newest_check = max(
            (p.stat().st_mtime for p in CHECKS_DIR.glob("check_results_*.json")),
            default=0.0,
        )
    except OSError:
        newest_check = 0.0
    parts.append(f"checks:{newest_check:.0f}")
    try:
        st = AUDIT_FILE.stat()
        parts.append(f"audit:{st.st_size}:{int(st.st_mtime)}")
    except OSError:
        parts.append("audit:0")
    root = task_dir(project_name, task)
    for rel in ("files/INCAR", "files/OUTCAR", "files/result", "reports/outcar_tail.txt"):
        path = root / rel
        try:
            parts.append(f"{rel}:{path.stat().st_mtime:.0f}")
        except OSError:
            parts.append(f"{rel}:0")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def build_task_context(
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    n_checks: int = 5,
    n_actions: int = 10,
) -> Dict[str, Any]:
    """构建任务上下文（纯本地、不发 SSH）。"""
    project_name = str(project.get("name") or "")
    task_id = str(task.get("task_id") or "")
    state = task.get("input_state") or {}
    files_meta = state.get("files") or {}
    incar_params = (files_meta.get("INCAR") or {}).get("params") or {}
    key_params = {
        k: incar_params[k]
        for k in (
            "SYSTEM", "PREC", "ENCUT", "EDIFF", "EDIFFG", "ISMEAR", "SIGMA", "NELM",
            "NSW", "IBRION", "ISIF", "ISYM", "LREAL", "ALGO", "NCORE", "KPAR",
            "LORBIT", "NEDOS", "LWAVE", "LCHARG", "LVHAR", "LVTOT", "LDAU", "MAGMOM",
        )
        if k in incar_params
    }
    summaries = read_task_file_summaries(project_name, task) if task_id else {}
    history = [_check_entry(e) for e in collect_task_history(task_id, limit=n_checks)]
    actions = _actions_for(task_id, n_actions)

    missing: List[str] = []
    present = set(summaries.get("present") or [])
    if not present:
        missing.append("本地没有任务文件（还没同步/归档过）")
    else:
        if "OUTCAR" in present and not summaries.get("outcar_tail"):
            missing.append("OUTCAR 尾部未生成（归档同步后自动生成，或在作业管理里点一次「同步」）")
        elif "OUTCAR" not in present:
            missing.append("本地没有 OUTCAR（先同步/归档）")
        if "result" in present and not summaries.get("result_tail"):
            missing.append("result 尾部未生成（归档同步后自动生成）")
        elif "result" not in present:
            missing.append("本地没有 result 文件（归档会拉取；老数据需重新归档或同步）")
    if not history:
        missing.append("最近归档里没有该任务的巡检记录")
    if not actions:
        missing.append("审计日志里没有该任务的动作记录")

    return {
        "contract": {
            "schema_version": SCHEMA_VERSION,
            "units": UNITS,
            "status_families": STATUS_FAMILIES,
            "note": "AI 只读本上下文即可决策；键名 snake_case、能量 eV、力 eV/Å、时间本地 +08:00",
        },
        "generated_at": iso_local(
            __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        ),
        "project": {
            "project_id": project.get("project_id"),
            "name": project_name,
            "owner": project.get("owner"),
            "server": project.get("server"),
            "deadline": project.get("deadline"),
            "project_status": (project.get("priority_quadrant") or "") or None,
            "calc_description": project.get("calc_description") or "",
            "expected_results": project.get("expected_results") or "",
        },
        "task": {
            "task_id": task_id,
            "task_name": task.get("model_name") or "",
            "task_type": task.get("task_type"),
            "subtype": task.get("subtype"),
            "task_status": task.get("status"),
            "status_label": None,
            "owner": project.get("owner"),
            "group": task.get("group"),
            "parent_task_id": task.get("parent_task_id"),
            "dir_path": task.get("dir_path"),
            "remote_dir": task.get("remote_dir"),
            "job_id": task.get("job_id"),
            "created_at": iso_local(task.get("created_at")),
            "archived_at": iso_local(task.get("archived_at")),
            "archived_from": task.get("archived_from"),
            "reopened_at": iso_local(task.get("reopened_at")),
            "last_check_time": iso_local(task.get("last_check_time")),
            "last_energy_ev": task.get("last_energy"),
            "continuation_ready": task.get("continuation_ready"),
            "continuation_dir": task.get("continuation_dir"),
            "current_output": task.get("current_output"),
            "structure_source_dir": task.get("last_analysis_dir"),
            "structure_analysis_bucket": task.get("last_analysis_bucket"),
        },
        "input": {
            "source": state.get("source") or {},
            "incar_key_params": key_params,
            "incar_param_count": len(incar_params),
            "kpoints_mesh": (files_meta.get("KPOINTS") or {}).get("mesh"),
            "lattice_abc": (files_meta.get("POSCAR") or {}).get("lattice_abc")
            or (files_meta.get("CONTCAR") or {}).get("lattice_abc"),
            "draft": state.get("draft") or {},
            "pending_changes": [c for c in (state.get("changes") or []) if not c.get("applied_at")],
        },
        "checks": {"history_count": len(history), "recent": history},
        "actions": {"recent": actions},
        "files": {
            "present": summaries.get("present") or [],
            "outcar_tail": summaries.get("outcar_tail"),
            "result_tail": summaries.get("result_tail"),
            "image_tails": summaries.get("image_tails") or {},
        },
        "manual": {
            "param_changes": (state.get("changes") or [])[:20],
            "archived": {
                "at": iso_local(task.get("archived_at")),
                "from": task.get("archived_from"),
            },
            "reopened_at": iso_local(task.get("reopened_at")),
            "notes": task.get("notes") or "",
        },
        "hints": {"missing": missing},
    }


def task_context_path(project_name: str, task: Dict[str, Any]) -> Path:
    return task_dir(project_name, task) / "reports" / "task_context.json"


def load_task_context(
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    n_checks: int = 5,
    n_actions: int = 10,
    refresh: bool = False,
) -> Dict[str, Any]:
    """带缓存的上下文：指纹一致就直接用落盘的那份（`<任务>/reports/task_context.json`）。"""
    project_name = str(project.get("name") or "")
    fingerprint = _fingerprint(project_name, task)
    path = task_context_path(project_name, task)
    if not refresh and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
                return {**cached, "cached": True}
        except Exception:  # noqa: BLE001 - 缓存坏了就重算
            pass
    context = build_task_context(project, task, n_checks=n_checks, n_actions=n_actions)
    context["fingerprint"] = fingerprint
    context["cached"] = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(context, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    return context
