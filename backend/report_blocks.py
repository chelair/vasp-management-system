"""R2-A：报告元素候选目录 + Evidence 稳定 ID / 来源与状态适配。

设计合同见 `agent-upgrade/R2-report-blocks.md` §3。这里的四条硬边界：

1. **只读本地数据**：巡检归档（`checks_store.merged_results`）+ 本地镜像文件是否存在。
   不调用完整 `build_report()`（它会取集群快照/SSH）、不连远端、不改任务库与巡检数据。
2. **科学数据只在 Evidence 里存一份**；Block 只保存 `source_refs = [{evidence_id, version}]`。
3. **ID 稳定**：由（项目, 类型, 任务/组, variant）确定性生成，不含标题、图序号、能量值、conN 编号；
   文本块由用户创建，才用随机 ID。
4. **状态不合并**：`availability`（有没有/是否解析）、`validation`（科学校验）、`freshness`（时效）、
   `full_report_visibility`（完整报告是否展示）四件事分开记，UNKNOWN 一律保留。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from checks_store import merged_results
from cif_convert import read_or_convert_cif
from dates import now_iso
from task_paths import is_auxiliary_task, task_files_dir

# 复用报告构建器的事实提取与分类口径（同一份数据，避免两套口径）
from report_builder import (
    MAX_STRUCTURE_TASKS,
    STATUS_DONE,
    SUBTYPE_LABELS,
    TASK_TYPE_LABELS,
    STATUS_LABELS,
    _label,
    _parse_time,
    _submit_times,
    _task_category,
    _task_facts,
)

SCHEMA_VERSION = "r2.1.0"

#: 单份组合最多多少个展示元素（防止把整本报告塞进一个组合）
MAX_BLOCKS = 40
#: 文本元素最大字符数
MAX_TEXT_CHARS = 4000
#: 标题最大字符数
MAX_TITLE_CHARS = 200
#: 超过多少小时算 stale
FRESH_HOURS = 24
#: 力收敛阈值（现有曲线图口径；未从 INCAR 反推时按默认 EDIFFG 0.02 eV/Å）
DEFAULT_FORCE_THRESHOLD = 0.02

#: Block 类型 → (renderer, evidence_kind, scope, 中文名, 是否已接入解析器)
#: scope: task / group / project / text
BLOCK_TYPES: Dict[str, Dict[str, Any]] = {
    "task.summary": {"renderer": "facts", "evidence": "task.fact", "scope": "task",
                     "label": "任务基本信息", "resolvable": True},
    "task.params": {"renderer": "param_table", "evidence": "task.params", "scope": "task",
                    "label": "关键参数", "resolvable": True},
    "task.energy_force": {"renderer": "metric", "evidence": "task.energy", "scope": "task",
                          "label": "最终能量 / 最大力", "resolvable": True},
    "task.convergence_curve": {"renderer": "curve", "evidence": "task.energy", "scope": "task",
                               "label": "收敛曲线", "resolvable": True},
    "task.structure": {"renderer": "structure", "evidence": "task.structure", "scope": "task",
                       "label": "结构可视化", "resolvable": True},
    "group.free_energy": {"renderer": "path_panel", "evidence": "group.path", "scope": "group",
                          "label": "自由能路径", "resolvable": False},
    "group.neb": {"renderer": "neb_panel", "evidence": "group.neb", "scope": "group",
                  "label": "NEB 能垒", "resolvable": False},
    "ele.pdos": {"renderer": "pdos_panel", "evidence": "ele.pdos", "scope": "task",
                 "label": "PDOS", "resolvable": False},
    "ele.bader": {"renderer": "bader_table", "evidence": "ele.bader", "scope": "task",
                  "label": "Bader 电荷", "resolvable": False},
    "ele.work_function": {"renderer": "work_function_panel", "evidence": "ele.work_function",
                          "scope": "task", "label": "功函数", "resolvable": False},
    "ele.charge_diff": {"renderer": "image_panel", "evidence": "ele.charge_diff", "scope": "task",
                        "label": "差分电荷图", "resolvable": False},
    "project.comparison": {"renderer": "comparison_table", "evidence": "project.comparison",
                           "scope": "project", "label": "对照表", "resolvable": True},
    "method.source": {"renderer": "method_table", "evidence": "project.method", "scope": "project",
                      "label": "方法与来源", "resolvable": True},
    "text.analysis": {"renderer": "text", "evidence": "", "scope": "text",
                      "label": "分析文本", "resolvable": True},
}

BLOCK_TYPE_NAMES = tuple(BLOCK_TYPES)

#: 元素展示选项白名单（键 → 允许的取值类型）
OPTION_KEYS: Dict[str, Tuple[type, ...]] = {
    "compact": (bool,),
    "show_units": (bool,),
    "digits": (int,),
    "note": (str,),
    "caption": (str,),
}

_UNITS = {
    "final_energy_ev": "eV",
    "force_max_ev_per_a": "eV/Å",
    "force_rms_ev_per_a": "eV/Å",
    "runtime_hours": "h",
    "cores": "核",
    "ionic_steps": "步",
}


# ------------------------------------------------------------------ 稳定 ID


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def block_id(
    project_id: str,
    block_type: str,
    *,
    task_id: str = "",
    group_id: str = "",
    variant: str = "",
) -> str:
    """数据块确定性 ID：同一（项目, 类型, 任务/组, variant）永远同一个 ID。"""
    return "blk_" + _digest(
        "|".join(["block", str(project_id), str(block_type), str(task_id), str(group_id), str(variant)])
    )


def evidence_id(
    project_id: str,
    kind: str,
    *,
    task_id: str = "",
    group_id: str = "",
) -> str:
    return "ev_" + _digest(
        "|".join(["evidence", str(project_id), str(kind), str(task_id), str(group_id)])
    )


def new_text_block_id() -> str:
    """文本块没有科学来源，用随机 ID（不参与确定性推导，避免改标题就换身份）。"""
    return "blk_txt_" + uuid.uuid4().hex


def is_text_block(block_type: str) -> bool:
    return str(block_type) == "text.analysis"


# ------------------------------------------------------------------ 版本


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_version(kind: str, payload: Any, provenance: Iterable[Dict[str, Any]]) -> str:
    """Evidence 版本 = 种类 + 实际 payload + 来源身份的内容摘要。

    刻意**不含** `observed_at` / `parsed_at`：同一份数据重复读取必须得到同一版本；
    报告生成时间更不能冒充数据版本。
    """
    source = [
        {key: item.get(key) for key in ("task_id", "directory", "attempt", "archive", "local_files")}
        for item in (provenance or [])
    ]
    basis = {"kind": str(kind), "payload": payload, "provenance": source}
    return "sha256:" + hashlib.sha256(_canonical(basis).encode("utf-8")).hexdigest()[:32]


# ------------------------------------------------------------------ 状态判定


def _freshness(checked_at: Any, now: datetime) -> Dict[str, Any]:
    parsed = _parse_time(checked_at)
    if parsed is None:
        return {"state": "unknown", "basis": "没有可用的巡检时间"}
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    age_hours = (now - parsed).total_seconds() / 3600.0
    state = "fresh" if age_hours <= FRESH_HOURS else "stale"
    return {
        "state": state,
        "basis": f"最近巡检 {checked_at}（{age_hours:.1f} 小时前，阈值 {FRESH_HOURS}h）",
    }


def _validation(kind: str, fact: Optional[Dict[str, Any]], *, available: bool = True) -> Dict[str, Any]:
    """科学校验状态。没有规则可判时返回 NOT_TESTED，有数据但不收敛返回 FAIL，绝不默认 PASS。"""
    items: List[Dict[str, Any]] = []
    if not available:
        return {"status": "UNKNOWN", "items": [{"rule": "data", "status": "UNKNOWN",
                                                "detail": "没有可用数据"}]}
    if kind == "task.energy":
        converged = fact.get("converged") if fact else None
        if converged is True:
            items.append({"rule": "force_converged", "status": "PASS", "detail": "巡检判定力已收敛"})
            return {"status": "PASS", "items": items}
        if converged is False:
            items.append({"rule": "force_converged", "status": "FAIL", "detail": "巡检判定力未收敛"})
            return {"status": "FAIL", "items": items}
        items.append({"rule": "force_converged", "status": "NOT_TESTED",
                      "detail": "巡检结果没有力收敛结论"})
        return {"status": "NOT_TESTED", "items": items}
    if kind == "task.params":
        precision = (fact or {}).get("precision") or {}
        sources = ((fact or {}).get("parameter_sources") or {}).get("mismatch")
        if sources:
            items.append({"rule": "parameter_source", "status": "WARNING",
                          "detail": f"参数来源与计算目录不一致：{sources}"})
            return {"status": "WARNING", "items": items}
        if not (fact or {}).get("incar_snapshot"):
            items.append({"rule": "incar", "status": "NOT_TESTED", "detail": "没有 INCAR 快照"})
            return {"status": "NOT_TESTED", "items": items}
        items.append({"rule": "incar", "status": "PASS", "detail": "存在 INCAR 快照"})
        if precision.get("ok") is False:
            items.append({"rule": "precision", "status": "WARNING", "detail": "精度检查未通过"})
            return {"status": "WARNING", "items": items}
        return {"status": "PASS", "items": items}
    # 其余类型：数据存在但没有本阶段的科学规则 → NOT_TESTED
    items.append({"rule": "science", "status": "NOT_TESTED", "detail": "R2-A 未接入该类型的科学校验规则"})
    return {"status": "NOT_TESTED", "items": items}


def _visibility(fact: Dict[str, Any], opt_index: Optional[int], converged: bool) -> str:
    """完整报告是否展示这个元素（与"有没有数据"是两件事）。"""
    if fact.get("task_type") == "opt" and _task_category(fact) == "结构优化":
        if fact.get("status") == "archived":
            return "shown"
        if not converged:
            return "omitted_unconverged"
        if opt_index is not None and opt_index >= MAX_STRUCTURE_TASKS:
            return "omitted_limit"
    return "shown"


def _local_files(project: Dict[str, Any], task: Dict[str, Any]) -> List[str]:
    try:
        directory = task_files_dir(str(project.get("name") or ""), task)
        if not directory.is_dir():
            return []
        return sorted(item.name for item in directory.iterdir() if item.is_file())
    except OSError:
        return []


def _availability(
    block_type: str,
    fact: Optional[Dict[str, Any]],
    files: List[str],
) -> str:
    spec = BLOCK_TYPES[block_type]
    kind = spec["evidence"]
    if block_type == "task.summary":
        return "available"
    if kind == "task.params":
        if (fact or {}).get("incar_snapshot"):
            return "available"
        return "unparsed" if "INCAR" in files else "missing"
    if kind == "task.energy":
        if (fact or {}).get("last_energy") is not None or (fact or {}).get("force_history"):
            return "available"
        return "unparsed" if "OUTCAR" in files else "missing"
    if kind == "task.structure":
        if any(name in files for name in ("CONTCAR", "POSCAR")):
            return "available"
        return "missing"
    if kind == "project.comparison":
        return "available" if (fact or {}).get("_comparison_count", 0) >= 2 else "missing"
    if kind == "project.method":
        return "available"
    # 组 / 电子结构：R2-A 还没接入解析器，有文件就标 unparsed，不冒充可用
    return "unparsed" if files else "missing"


# ------------------------------------------------------------------ 候选目录


def _task_by_id(project: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(task.get("task_id") or ""): task for task in project.get("tasks", [])}


def _opt_indices(facts: List[Dict[str, Any]]) -> Dict[str, int]:
    """独立结构优化任务在完整报告里的展示序号（只有前 MAX_STRUCTURE_TASKS 个进正文）。"""
    indices: Dict[str, int] = {}
    counter = 0
    for fact in facts:
        if fact.get("task_type") != "opt" or _task_category(fact) != "结构优化":
            continue
        indices[str(fact.get("task_id"))] = counter
        counter += 1
    return indices


def _task_title(fact: Dict[str, Any]) -> str:
    return f"{fact.get('task_name') or fact.get('task_id')} · {fact.get('task_type_label') or ''}".strip(" ·")


def _candidate(
    project: Dict[str, Any],
    block_type: str,
    *,
    fact: Optional[Dict[str, Any]] = None,
    task: Optional[Dict[str, Any]] = None,
    group_id: str = "",
    title: str = "",
    visibility: str = "shown",
    now: datetime,
) -> Dict[str, Any]:
    spec = BLOCK_TYPES[block_type]
    project_id = str(project.get("project_id") or project.get("name") or "")
    task_id = str((fact or {}).get("task_id") or (task or {}).get("task_id") or "")
    files = _local_files(project, task) if task else []
    availability = _availability(block_type, fact, files)
    checked_at = (fact or {}).get("inspection_checked_at") or (fact or {}).get("last_check_time")
    return {
        "block_id": block_id(project_id, block_type, task_id=task_id, group_id=group_id),
        "type": block_type,
        "type_label": spec["label"],
        "title": title or (fact.get("task_name") if fact else "") or group_id or spec["label"],
        "project_id": project_id,
        "task_id": task_id,
        "group_id": group_id,
        "variant": "",
        "evidence_id": evidence_id(project_id, spec["evidence"], task_id=task_id, group_id=group_id)
        if spec["evidence"]
        else "",
        "evidence_kind": spec["evidence"],
        "renderer": spec["renderer"],
        "resolvable": bool(spec["resolvable"]),
        "availability": availability,
        "validation": _validation(spec["evidence"], fact, available=availability == "available"),
        "freshness": _freshness(checked_at, now),
        "full_report_visibility": visibility,
        "summary": _summary(block_type, fact, availability),
        "detail": "" if availability == "available" else _availability_note(block_type, availability),
    }


def _availability_note(block_type: str, availability: str) -> str:
    if availability == "missing":
        return "本地没有该类型的原始数据或归档"
    if availability == "unparsed":
        if not BLOCK_TYPES[block_type]["resolvable"]:
            return "R2-A 尚未接入该类型的解析器（数据可能存在，不能宣称没有）"
        return "存在原始文件但尚未解析"
    return ""


def _summary(block_type: str, fact: Optional[Dict[str, Any]], availability: str) -> str:
    if fact is None:
        return ""
    if block_type in ("task.energy_force", "task.convergence_curve"):
        energy = fact.get("last_energy")
        force = fact.get("force_max")
        if energy is None and force is None:
            return "没有能量/力结果"
        return f"E = {energy if energy is not None else '—'} eV · Fmax = {force if force is not None else '—'} eV/Å"
    if block_type == "task.params":
        incar = fact.get("incar_snapshot") or {}
        return f"{len(incar)} 个 INCAR 参数" if incar else "没有参数快照"
    if block_type == "task.summary":
        return f"{fact.get('status_label') or fact.get('status')} · {fact.get('task_type_label')}"
    if block_type == "task.structure":
        return availability == "available" and "存在本地结构文件" or "没有本地结构文件"
    return ""


def list_candidates(
    project: Dict[str, Any],
    *,
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
    submit_times: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """**全部授权任务**的候选目录（不受完整报告 6 条上限影响），轻量、不解析图像/DOS。"""
    project_id = str(project.get("project_id") or project.get("name") or "")
    moment = now or datetime.now().astimezone()
    tasks = [t for t in project.get("tasks", []) if not is_auxiliary_task(t)]
    facts = _task_facts(
        project,
        tasks,
        merged if merged is not None else merged_results(force=force),
        submit_times if submit_times is not None else _submit_times(),
        {},
    )
    by_id = _task_by_id(project)
    opt_index = _opt_indices(facts)

    energy_rows = [f for f in facts if f.get("last_energy") is not None]

    candidates: List[Dict[str, Any]] = []
    for fact in facts:
        task = by_id.get(str(fact.get("task_id"))) or {}
        converged = bool(fact["converged"]) if fact.get("converged") is not None else fact["status"] in STATUS_DONE
        visibility = _visibility(fact, opt_index.get(str(fact.get("task_id"))), converged)
        task_type = str(fact.get("task_type") or "")
        types = ["task.summary"]
        if task_type in ("opt", "frac", "neb", "ele"):
            types.append("task.params")
        if task_type in ("opt", "frac", "neb"):
            types += ["task.energy_force", "task.convergence_curve"]
        if task_type in ("opt", "neb"):
            types.append("task.structure")
        if task_type == "ele":
            subtype = str(fact.get("subtype") or "")
            types += ["ele.pdos"] if subtype in ("", "pdos") else []
            types += ["ele.bader"] if subtype == "bader" else []
            types += ["ele.work_function"] if subtype == "work_function" else []
            types += ["ele.charge_diff"] if subtype in ("diff_charge", "charge_diff") else []
        for block_type in types:
            candidates.append(
                _candidate(project, block_type, fact=fact, task=task, visibility=visibility, now=moment)
            )

    # 组级候选（自由能路径 / NEB）
    group_seen: Dict[str, Dict[str, Any]] = {}
    for fact in facts:
        group = fact.get("group") or {}
        group_id = str(group.get("group_id") or "")
        gtype = str(group.get("group_type") or "")
        if not group_id:
            continue
        entry = group_seen.setdefault(group_id, {"type": gtype, "members": []})
        entry["members"].append(fact)
    for group_id, entry in group_seen.items():
        block_type = "group.free_energy" if entry["type"] == "free_energy" else (
            "group.neb" if entry["type"] == "neb" else ""
        )
        if not block_type:
            continue
        members = entry["members"]
        member_visible = []
        for member in members:
            member_converged = (
                bool(member["converged"])
                if member.get("converged") is not None
                else member["status"] in STATUS_DONE
            )
            member_visible.append(
                _visibility(member, opt_index.get(str(member.get("task_id"))), member_converged)
            )
        visibility = "shown" if any(v == "shown" for v in member_visible) else "omitted_limit"
        candidates.append(
            _candidate(
                project,
                block_type,
                fact=members[0],
                task=by_id.get(str(members[0].get("task_id"))) or {},
                group_id=group_id,
                title=f"{group_id} · {BLOCK_TYPES[block_type]['label']}",
                visibility=visibility,
                now=moment,
            )
        )

    # 项目级候选
    comparison_fact = {"_comparison_count": len(energy_rows)}
    candidates.append(
        _candidate(project, "project.comparison", fact=comparison_fact, title="模型 / 能量对照表", now=moment)
    )
    candidates.append(
        _candidate(project, "method.source", fact={"task_id": ""}, title="方法与来源", now=moment)
    )

    counts: Dict[str, int] = {}
    for item in candidates:
        counts[item["type"]] = counts.get(item["type"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "project_name": str(project.get("name") or ""),
        "generated_at": now_iso(),
        "task_count": len(tasks),
        "evidence_task_limit": MAX_STRUCTURE_TASKS,
        "filters": {
            "include_archived": True,
            "note": "候选来自全部授权任务；辅助任务（conN / 差分分块）跟随主任务，不单独成为元素",
        },
        "counts": counts,
        "types": [
            {
                "type": name,
                "label": spec["label"],
                "renderer": spec["renderer"],
                "scope": spec["scope"],
                "resolvable": spec["resolvable"],
            }
            for name, spec in BLOCK_TYPES.items()
        ],
        "candidates": candidates,
    }


# ------------------------------------------------------------------ Evidence 解析


class UnsupportedEvidence(Exception):
    """该类型在 R2-A 还没接入解析器（不是"没有数据"）。"""


def _provenance(
    fact: Dict[str, Any],
    task: Dict[str, Any],
    files: List[str],
    parsed_at: str,
) -> List[Dict[str, Any]]:
    latest = fact.get("latest_output_dir") or ""
    return [
        {
            "task_id": fact.get("task_id"),
            "directory": latest or str(task.get("remote_dir") or ""),
            "attempt": (latest.rsplit("/", 1)[-1] if latest else "main"),
            "archive": "data/checks（巡检归档合并结果）",
            "observed_at": fact.get("inspection_checked_at") or fact.get("last_check_time"),
            "parsed_at": parsed_at,
            "hash": None,
            "hash_scope": "payload_only",
            "local_files": list(files),
        }
    ]


def _payload_task_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": fact.get("task_id"),
        "task_name": fact.get("task_name"),
        "task_type": fact.get("task_type"),
        "task_type_label": fact.get("task_type_label"),
        "subtype": fact.get("subtype") or None,
        "subtype_label": SUBTYPE_LABELS.get(str(fact.get("subtype") or ""), None),
        "status": fact.get("status"),
        "status_label": fact.get("status_label"),
        "group": fact.get("group"),
        "job_id": fact.get("job_id"),
        "queue": fact.get("queue"),
        "cores": fact.get("cores"),
        "runtime_hours": fact.get("runtime_hours"),
        "remote_dir": fact.get("remote_dir"),
        "latest_output_dir": fact.get("latest_output_dir"),
        "continuation_count": fact.get("continuation_count"),
        "ionic_steps": fact.get("steps"),
        "errors": fact.get("errors") or [],
        "inspection_checked_at": fact.get("inspection_checked_at"),
        "units": {"runtime_hours": "h", "cores": "核", "ionic_steps": "步"},
    }


def _payload_params(fact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incar": fact.get("incar_snapshot") or {},
        "kpoints": fact.get("kpoints_snapshot") or {},
        "parameter_sources": fact.get("parameter_sources") or {},
        "precision": fact.get("precision") or {},
        "units": {},
        "note": "来源与格式沿用报告快照；缺失值保持缺失，不用当前输入补造",
    }


def _payload_energy(fact: Dict[str, Any]) -> Dict[str, Any]:
    series = [
        {
            "step": point.get("step"),
            "energy": point.get("energy"),
            "max_force": point.get("max_force"),
        }
        for point in (fact.get("force_history") or [])
        if isinstance(point, dict)
    ]
    return {
        "final_energy_ev": fact.get("last_energy"),
        "force_max_ev_per_a": fact.get("force_max"),
        "force_rms_ev_per_a": fact.get("force_rms"),
        "converged": fact.get("converged"),
        "ionic_steps": fact.get("steps"),
        "series": series,
        "force_threshold_ev_per_a": DEFAULT_FORCE_THRESHOLD,
        "units": dict(_UNITS),
        "note": "曲线点为巡检归档的离子步记录；阈值取默认 EDIFFG 口径",
    }


def _payload_structure(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    poscar = contcar = None
    errors: List[str] = []
    for name, key in (("POSCAR", "poscar_cif"), ("CONTCAR", "contcar_cif")):
        try:
            value = read_or_convert_cif(project, task, name)
        except Exception as exc:  # noqa: BLE001 - 单个结构失败不影响另一份
            value = None
            errors.append(f"{name}: {exc}")
        if key == "poscar_cif":
            poscar = value
        else:
            contcar = value
    return {
        "poscar_cif": poscar,
        "contcar_cif": contcar,
        "structure_source": "local_mirror",
        "errors": errors,
        "note": "只读本地镜像；本地没有结构文件时不生成假图",
    }


def _comparison_payload(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for fact in facts:
        if fact.get("last_energy") is None:
            continue
        rows.append(
            {
                "task_id": fact.get("task_id"),
                "task_name": fact.get("task_name"),
                "task_type": fact.get("task_type"),
                "status": fact.get("status"),
                "final_energy_ev": fact.get("last_energy"),
                "force_max_ev_per_a": fact.get("force_max"),
                "force_converged": fact.get("converged"),
                "latest_output_dir": fact.get("latest_output_dir"),
            }
        )
    return {
        "rows": rows,
        "units": {"final_energy_ev": "eV", "force_max_ev_per_a": "eV/Å"},
        "note": "只并列已有能量结果，不做参考态换算，也不推测缺失模型",
    }


def _method_payload(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for fact in facts:
        incar = fact.get("incar_snapshot") or {}
        rows.append(
            {
                "task_id": fact.get("task_id"),
                "task_name": fact.get("task_name"),
                "task_type": fact.get("task_type"),
                "status": fact.get("status"),
                "encut": incar.get("ENCUT") or incar.get("encut"),
                "kpoints": fact.get("kpoints_snapshot") or {},
                "parameter_sources": fact.get("parameter_sources") or {},
                "latest_output_dir": fact.get("latest_output_dir"),
            }
        )
    return {
        "rows": rows,
        "note": "方法口径来自报告快照中的 INCAR/KPOINTS 与参数来源，不反解析 Markdown",
    }


def _facts_for(project: Dict[str, Any], merged, submit_times) -> List[Dict[str, Any]]:
    tasks = [t for t in project.get("tasks", []) if not is_auxiliary_task(t)]
    return _task_facts(project, tasks, merged, submit_times, {})


def resolve_evidence(
    project: Dict[str, Any],
    block_type: str,
    *,
    task_id: str = "",
    group_id: str = "",
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
    submit_times: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """按（类型, 任务/组）解析一条 Evidence：payload 只在这里生成一次。"""
    spec = BLOCK_TYPES.get(str(block_type))
    if spec is None:
        raise KeyError(f"未知元素类型：{block_type}")
    if not spec["resolvable"]:
        raise UnsupportedEvidence(
            f"{spec['label']} 在 R2-A 尚未接入解析器（候选里已标 unparsed），不能伪造证据"
        )

    project_id = str(project.get("project_id") or project.get("name") or "")
    moment = now or datetime.now().astimezone()
    facts = _facts_for(
        project,
        merged if merged is not None else merged_results(force=force),
        submit_times if submit_times is not None else _submit_times(),
    )
    by_id = _task_by_id(project)
    kind = spec["evidence"]

    if spec["scope"] == "task":
        fact = next((f for f in facts if str(f.get("task_id")) == str(task_id)), None)
        if fact is None:
            raise LookupError(f"任务不存在或不属于该项目：{task_id}")
        task = by_id.get(str(task_id)) or {}
        files = _local_files(project, task)
        availability = _availability(block_type, fact, files)
        if kind == "task.fact":
            payload = _payload_task_fact(fact)
        elif kind == "task.params":
            payload = _payload_params(fact)
        elif kind == "task.energy":
            payload = _payload_energy(fact)
        elif kind == "task.structure":
            payload = _payload_structure(project, task)
        else:  # pragma: no cover - 新增类型必须在这里显式接入
            raise UnsupportedEvidence(f"证据种类 {kind} 没有解析实现")
        title = _task_title(fact)
    elif spec["scope"] == "group":
        members = [
            f for f in facts
            if str((f.get("group") or {}).get("group_id") or "") == str(group_id)
        ]
        if not members:
            raise LookupError(f"组不存在或没有成员：{group_id}")
        fact = members[0]
        payload = {
            "group_id": group_id,
            "members": [
                {
                    "task_id": m.get("task_id"),
                    "task_name": m.get("task_name"),
                    "status": m.get("status"),
                    "final_energy_ev": m.get("last_energy"),
                    "force_max_ev_per_a": m.get("force_max"),
                }
                for m in members
            ],
            "note": "组级证据在 R2-A 只给成员清单，路径/能垒面板 R2-D 接入",
        }
        files = []
        availability = "unparsed"
        title = group_id
    else:  # project
        if block_type == "project.comparison":
            payload = _comparison_payload(facts)
            availability = "available" if len(payload["rows"]) >= 2 else "missing"
            title = "模型 / 能量对照表"
        elif block_type == "method.source":
            payload = _method_payload(facts)
            availability = "available"
            title = "方法与来源"
        else:  # pragma: no cover
            raise UnsupportedEvidence(f"项目级类型没有解析实现：{block_type}")
        fact = {"task_id": "", "inspection_checked_at": None}
        files = []
        by_id = {}

    task_obj = by_id.get(str(fact.get("task_id") or ""), {}) if spec["scope"] == "task" else {}
    provenance = _provenance(fact, task_obj, files, now_iso())
    version = payload_version(kind, payload, provenance)

    return {
        "evidence_id": evidence_id(project_id, kind, task_id=str(task_id or ""), group_id=str(group_id or "")),
        "version": version,
        "kind": kind,
        "block_type": block_type,
        "project_id": project_id,
        "task_id": str(task_id or ""),
        "group_id": str(group_id or ""),
        "title": title,
        "payload": payload,
        "provenance": provenance,
        "availability": availability,
        "validation": _validation(kind, fact, available=availability == "available"),
        "freshness": _freshness(fact.get("inspection_checked_at") or fact.get("last_check_time"), moment),
        "observed_at": fact.get("inspection_checked_at") or fact.get("last_check_time"),
        "parsed_at": provenance[0]["parsed_at"],
    }


# ------------------------------------------------------------------ 组合校验公共件


def normalize_options(options: Any) -> Dict[str, Any]:
    """展示选项白名单：未知键直接拒绝，避免把命令/路径/科学值塞进 options。"""
    if options in (None, {}):
        return {}
    if not isinstance(options, dict):
        raise ValueError("options 必须是对象")
    clean: Dict[str, Any] = {}
    for key, value in options.items():
        if key not in OPTION_KEYS:
            raise ValueError(f"不支持的展示选项：{key}")
        if not isinstance(value, OPTION_KEYS[key]):
            raise ValueError(f"展示选项 {key} 类型不合法")
        clean[key] = value
    return clean


def check_title(title: Any) -> str:
    text = str(title or "").strip()
    if not text:
        raise ValueError("标题不能为空")
    if len(text) > MAX_TITLE_CHARS:
        raise ValueError(f"标题过长（>{MAX_TITLE_CHARS} 字）")
    return text


def check_text(value: Any) -> str:
    text = str(value or "")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"文本过长（>{MAX_TEXT_CHARS} 字）")
    return text
