"""模型按需查询巡检证据：只读原始观测，限定当前项目，不读页面、不发SSH。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

from checks_store import collect_task_observations, observation_directory
from config import load_settings
from dates import now_iso
from permissions import PermissionDenied
from task_paths import is_auxiliary_task

FRESHNESS_SECONDS = 4 * 3600


def participation(project, task):
    reasons = []
    if project.get('closed'):
        reasons.append('project_closed')
    if task.get('status') in ('pending','archived'):
        reasons.append('task_' + task['status'])
    if not project.get('server'):
        reasons.append('server_not_configured')
    try:
        if not load_settings().get('auto_inspection_enabled',True):
            reasons.append('auto_inspection_disabled')
    except (OSError,ValueError,TypeError):
        reasons.append('inspection_settings_unknown')
    return {'included':not reasons, 'excluded_reasons':reasons}


def parameter_diff(newer, older):
    def canonical(value):
        if isinstance(value,str):
            value = ' '.join(value.split())
            if value.lower() in ('.true.','true','t'): return True
            if value.lower() in ('.false.','false','f'): return False
            try:
                number = float(value.replace('D','E').replace('d','e'))
                if math.isfinite(number): return number
            except ValueError:
                pass
        return value
    new, old = newer.get('incar'), older.get('incar')
    changes = []
    if isinstance(new,dict) and isinstance(old,dict):
        for key in sorted(set(new) | set(old)):
            if canonical(new.get(key)) != canonical(old.get(key)):
                changes.append({'key':key,'before':old.get(key),'after':new.get(key)})
    kp_new, kp_old = newer.get('kpoints'), older.get('kpoints')
    return {'from_directory':_output(older),'to_directory':_output(newer),'incar_changes':changes,
            'incar_available':isinstance(new,dict) and isinstance(old,dict),
            'full_values_verified':newer.get('incar_value_format') == older.get('incar_value_format') == 'full_values_v1'
                and not newer.get('parameter_source_mismatch') and not older.get('parameter_source_mismatch'),
            'kpoints_available':kp_new is not None and kp_old is not None,
            'kpoints_change':{'before':kp_old,'after':kp_new} if kp_old is not None and kp_new is not None and kp_old != kp_new else None,
            'note':'逐项比较所选观测的参数；旧归档可能仅保存首个取值，多值参数需已提交记录或远端补证'}


def task_for(project: dict, task_id: str) -> dict:
    for task in project.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    raise PermissionDenied("任务不属于当前会话项目或不存在")


def find_tasks(project: dict, query: str) -> dict:
    query = query.strip().casefold()
    if not query or len(query) > 200:
        raise ValueError("请输入任务名称、ID或目录片段，最多200字符")
    matches = []
    for task in project.get("tasks", []):
        values = [str(task.get(k) or "").casefold() for k in ("task_id", "model_name", "dir_path", "remote_dir")]
        if any(query in value for value in values):
            matches.append((query not in values[:2], is_auxiliary_task(task), task))
    matches.sort(key=lambda item: (item[0], item[1], item[2].get("model_name") or "", item[2]["task_id"]))
    return {"project_id": project["project_id"], "matches": [
        {"task_id": t["task_id"], "name": t.get("model_name"), "type": t.get("task_type"),
         "status": t.get("status"), "dir_path": t.get("dir_path"), "auxiliary": is_auxiliary_task(t)}
        for _, _, t in matches[:20]], "total": len(matches), "truncated": len(matches) > 20,
        "note": "有多个匹配时按类型和目录确认目标，不凭名称自动合并任务。"}


def _output(row: dict):
    value = (row.get("current_output") or {}).get("latest_dir")
    return "" if value in ("MAIN", "main", ".") else value


def _parameters(row: dict):
    if not row.get("incar") or not row.get("kpoints"):
        return None
    data = json.dumps({"incar": row["incar"], "kpoints": row["kpoints"]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _age(checked_at):
    try:
        date = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        return round((datetime.now().astimezone() - date.astimezone()).total_seconds())
    except (ValueError, OverflowError):
        return None


def _strings(values, count=3):
    return [str(value)[:500] for value in values[:count]] if isinstance(values, list) else []


def _summary(observation: dict) -> dict:
    row = observation["data"]
    curve = row.get("force_history") or []
    precision = row.get("precision") or {}
    images = (row.get("neb_barrier") or {}).get("images") or []
    return {"observation_id": observation["observation_id"], "archive": observation["archive"],
            "directory": observation.get("directory") or observation_directory(row),
            "checked_at": row.get("checked_at"), "age_seconds": _age(row.get("checked_at")),
            "status": row.get("status"), "previous_status": row.get("prev_status"),
            "queue_status": row.get("queue_status"), "job_id": row.get("job_id") or None,
            "remote_dir": row.get("remote_dir"), "output_dir": _output(row),
            "parameters_sha256": _parameters(row), "energy_ev": _number(row.get("last_energy")),
            "energy_correction": row.get("energy_correction"),
            "incar_value_format":row.get('incar_value_format','legacy_first_token_or_unknown'),
            'parameter_sources':row.get('parameter_sources'), 'parameter_source_mismatch':bool(row.get('parameter_source_mismatch')),
            "force_max_ev_per_a": _number(row.get("force_max")), "force_rms_ev_per_a": _number(row.get("force_rms")),
            "force_converged": row.get("force_converged"), "force_thresholds": row.get("force_thresholds"),
            "ionic_steps": row.get("neb_band_steps") if row.get("task_type") == "neb" else len(curve) if curve else None,
            "curve_points": len(curve), "neb_image_count": len(images),
            "precision": {"ok": precision.get("ok"), "issues": _strings(precision.get("issues"), 5)},
            "errors": _strings(row.get("error_messages")), "markers": _strings(row.get("markers")),
            "notes": str(row.get("notes") or "")[:500],
            "missing": [key for key in ("checked_at", "last_energy", "force_max", "incar", "kpoints") if row.get(key) is None]
                + (['kpoints_mesh'] if isinstance(row.get('kpoints'),dict) and row['kpoints'].get('mesh') is None else [])}


def query_inspections(project: dict, task_id: str, limit: int = 3) -> dict:
    task = task_for(project, task_id)
    observations = collect_task_observations(task_id, limit=5)
    rows = [_summary(row) for row in observations[:limit]]
    comparisons = []
    for index, (newer, older) in enumerate(zip(rows, rows[1:])):
        identity = ("remote_dir", "output_dir", "job_id", "parameters_sha256")
        changed = [key for key in identity if newer[key] is not None and older[key] is not None and newer[key] != older[key]]
        unknown = [key for key in identity if newer[key] is None or older[key] is None]
        comparable = not changed and not unknown
        comparisons.append({"newer": newer["observation_id"], "older": older["observation_id"],
            "same_observed_stage": comparable, "changed_identity_fields": changed, "unknown_identity_fields": unknown,
            "energy_delta_ev": newer["energy_ev"]-older["energy_ev"] if comparable and newer["energy_ev"] is not None and older["energy_ev"] is not None else None,
            "force_delta_ev_per_a": newer["force_max_ev_per_a"]-older["force_max_ev_per_a"] if comparable and newer["force_max_ev_per_a"] is not None and older["force_max_ev_per_a"] is not None else None,
            "parameter_diff":parameter_diff(observations[index]['data'], observations[index+1]['data']),
            "note": "仅比较已观测到的作业、目录与参数身份；不保证结构输入一致" if comparable else "阶段有变化或证据不足，不直接拼接曲线或判定趋势"})
    warnings = []
    if len(rows) < limit:
        warnings.append(f"只找到{len(rows)}个目录的最新结果，不补造缺失目录或同目录旧记录")
    if comparisons and any(not c["same_observed_stage"] for c in comparisons):
        warnings.append("最近巡检跨作业/目录/参数阶段或身份缺失，请分段分析")
    from parameter_history import records, summaries
    applied_records = records(project,task)
    inputs_newer = bool(rows and applied_records and _age(applied_records[0].get('at')) is not None
                        and (rows[0]['age_seconds'] is None or _age(applied_records[0]['at']) < rows[0]['age_seconds']))
    mismatch = bool(rows and (_output(task) is not None and rows[0]["output_dir"] != _output(task)
                 or task.get("job_id") and rows[0]["job_id"] != task["job_id"]))
    if inputs_newer:
        mismatch = True
        warnings.append('巡检之后有实际输入上传/续算/提交记录；需区分已写入输入与运行时采用参数')
    if rows and rows[0]['parameter_source_mismatch']:
        mismatch = True
        warnings.append('巡检参数回退读取了任务根目录，不能冒充当前con目录的输入')
    if mismatch:
        warnings.append("最近巡检与当前任务目录或作业不一致，不能作为当前状态确认")
    age = rows[0]["age_seconds"] if rows else None
    scope = participation(project,task)
    stale = bool(scope['included'] and (age is None or age > FRESHNESS_SECONDS or age < -300))
    if stale:
        warnings.append("参与巡检任务的最新观测缺失、时间异常或超过4小时；先按需读取远端只读证据并核对状态，再判断是否需要干预")
    token = hashlib.sha256(json.dumps([project.get('project_id'),task_id,[o['observation_id'] for o in observations],
                                      task.get('job_id'),task.get('current_output'),task.get('status'),
                                      applied_records[0]['id'] if applied_records else None],sort_keys=True).encode()).hexdigest()
    return {"schema_version": 2, "generated_at": now_iso(), "project_id": project["project_id"],
            "task": {"task_id": task_id, "name": task.get("model_name"), "type": task.get("task_type"),
                     "current_status": task.get("status"), "current_job_id": task.get("job_id"), "current_output_dir": _output(task)},
            "requested": limit, "returned": len(rows), "available": len(observations), "retention_limit": 5,
            "retention_unit": "calculation_directory", "observation_semantics": "latest_result_per_directory",
            "observations": rows, "comparisons": comparisons, "warnings": warnings,
            "applied_parameter_records":summaries(applied_records),
            "evidence_token":token,
            "freshness": {"stale_for_live_decision": stale, "threshold_seconds": FRESHNESS_SECONDS, "remote_verified": False,
                          'age_seconds':age,'inspection_participation':scope,'source_mismatch':mismatch,
                          'input_records_after_observation':inputs_newer,
                          'needs_remote_evidence':bool(scope['included'] and (stale or mismatch)),
                          'next_step':'get_remote_task_evidence' if scope['included'] and (stale or mismatch) else 'analyze_local_evidence',
                          'excluded_note':'不参与自动巡检的任务不按4小时自动判旧；历史事实不等于当前远端状态'},
            "units": {"energy": "eV", "force": "eV/Å", "age": "seconds"},
            "evidence": {"kind": "raw_inspection_archives", "inherited_fields": False,
                         "energy_policy": "总能可按同次保存的OUTCAR离子步段与OSZICAR F重解析；更正时energy_correction保留原记录值，不改归档或观测标识。",
                         "history_policy": "每目录仅保留最新结果；同目录后续巡检更新覆盖。这里不是同目录的巡检时间序列，目录内收敛趋势请读取离子步曲线。",
                         "parameters_hash_scope": "归档的INCAR与KPOINTS，不包含完整原子结构",
                         "historical_structures": "未保证每次观测保存结构；当前本地结构不能冒充历史结构",
                         "more": "get_inspection_evidence(task_id, observation_id, kind)，可读曲线、参数和NEB数值；需要坐标或日志再调用文件工具"}}


def query_evidence(project: dict, task_id: str, observation_id: str, kind: str, offset: int = 0) -> dict:
    task_for(project, task_id)
    observations = collect_task_observations(task_id, limit=5)
    observation = next((row for row in observations if row["observation_id"] == observation_id), None)
    if observation is None:
        raise ValueError("该目录结果已更新或超出保留范围，请重新查询各目录最新结果")
    row = observation["data"]
    if kind == "curves":
        values = row.get("force_history") or []
    elif kind == "neb":
        values = (row.get("neb_barrier") or {}).get("images") or []
    elif kind == "parameters":
        values = [{"field": key, "value": row.get(key)} for key in ("incar", "kpoints", "lattice_abc", "force_thresholds", "precision")]
    else:
        raise ValueError("只支持curves、neb或parameters证据")
    # 返回完整JSON页，避免通用文件字节分片将三次观测或单个数值截断。
    selected, used = [], 0
    for value in values[offset:offset+60]:
        size = len(json.dumps(value, ensure_ascii=False))
        if used+size > 16000:
            if not selected:
                raise ValueError("该字段超过单页预算，请读取对应任务文件的文本片段")
            break
        selected.append(value)
        used += size
    return {"task_id": task_id, "observation_id": observation_id, "archive": observation["archive"],
            "checked_at": row.get("checked_at"), "kind": kind, "total": len(values), "offset": offset,
            "items": selected, "next_offset": offset+len(selected) if offset+len(selected) < len(values) else None,
            "missing": not values or kind == "parameters" and all(item["value"] is None for item in values),
            "source": "raw_inspection_archive", "remote_verified": False,
            "units": {"energy": "eV", "force": "eV/Å", "length": "Å"},
            "note": "这是所选观测保存的数值，不混入当前结构、实时远端结果或其他轮次"}
