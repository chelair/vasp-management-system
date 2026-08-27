"""巡检编排：上传 batch_check → 服务器批量解析 → 结果回填 → 归档（对齐参考 check_remote.py）。

Web 化改造：
- 不再生成 HTML 报告（由前端巡检中心页面呈现）；
- batch_check.py / check_registry.json 由本系统上传到服务器（无需手动部署）；
- 支持 VASP_SSH_MOCK 本地模拟，便于离线验证；
- 状态回填复用 storage.update_task_status（与 project_db.py 一致的状态机）。
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from checks_store import archive_results, record_run
from config import PROJECTS_DIR, load_servers
from dates import now_iso
from paths import to_remote_rel
from storage import db_transaction, update_task_status
from task_paths import task_dir, task_remote_dir

SKIPPED_STATUSES = ("pending", "archived")
STRUCTURE_OPT_TYPE = "opt"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _filter_tasks(
    db: Dict[str, Any],
    project_name: Optional[str],
) -> Tuple[Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]], List[str]]:
    """全局巡检：按状态筛选待巡检任务并按服务器分组；返回 (by_server, skipped_projects)。"""
    by_server: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    skipped: List[str] = []
    for project in db.get("projects", []):
        if project_name is not None and project.get("name") != project_name:
            continue
        targets = [
            t for t in project.get("tasks", []) if t.get("status") not in SKIPPED_STATUSES
        ]
        if not targets:
            skipped.append(project.get("name"))
            continue
        by_server.setdefault(project.get("server"), []).extend(
            (project, task) for task in targets
        )
    return by_server, skipped


def _find_task(
    db: Dict[str, Any],
    project_name: Optional[str],
    task_id: str,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """直接定位任务（单任务巡检用，不做任何状态筛选）。"""
    for project in db.get("projects", []):
        if project_name is not None and project.get("name") != project_name:
            continue
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                return project, task
    return None


def _run_server_batch(
    server: str,
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    timestamp: str,
) -> List[Dict[str, Any]]:
    """上传任务清单与 batch_check 脚本，在服务器运行并下载结果。"""
    servers = load_servers()
    cfg = servers.get(server)
    if cfg is None:
        raise ValueError(f"服务器 '{server}' 未在 servers.json 中配置")
    batch_path = cfg.get("batch_check_path")
    if not batch_path:
        raise ValueError(f"服务器 '{server}' 未配置 batch_check_path")

    script_local = Path(__file__).resolve().parent / "batch_check.py"
    registry_local = Path(__file__).resolve().parent / "check_registry.json"
    # Windows 上 Path.__str__ 会把正斜杠转成反斜杠，远程路径必须统一为正斜杠
    script_dir = str(Path(batch_path).parent).replace("\\", "/")
    remote_input = f"/tmp/vasp_tasks_{timestamp}.json"
    remote_output = f"/tmp/vasp_results_{timestamp}.json"

    # 上传脚本与阈值配置（自动部署，无需手动同步）
    ssh.mkdir_remote(server, script_dir)
    ssh.upload_file(server, str(script_local), batch_path)
    ssh.upload_file(server, str(registry_local), f"{script_dir}/check_registry.json")

    manifest = [
        {
            "task_id": task["task_id"],
            "remote_dir": task_remote_dir(project["server"], task),
            "job_id": task.get("job_id") or "",
            "task_type": task.get("task_type", ""),
            "project_name": project["name"],
        }
        for project, task in pairs
    ]

    with tempfile.TemporaryDirectory() as tmp:
        local_input = Path(tmp) / "tasks_to_check.json"
        local_output = Path(tmp) / "check_results.json"
        local_input.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        ssh.upload_file(server, str(local_input), remote_input)
        result = ssh.run_remote(
            server,
            f"python3 {batch_path} {remote_input} {remote_output}",
            timeout=120,
        )
        if result["exit_code"] != 0:
            raise RuntimeError(
                f"服务器批量检查失败：{(result['stderr'] or result['stdout']).strip()}"
            )
        ok = ssh.download_file(server, remote_output, str(local_output))
        if not ok:
            raise RuntimeError("下载批量检查结果失败")
        return json.loads(local_output.read_text(encoding="utf-8"))


def _sync_and_validate_structure(
    project: Dict[str, Any],
    task: Dict[str, Any],
    latest_dir: str = "",
) -> List[str]:
    """下载 POSCAR（主目录）与最新 CONTCAR（续算目录优先）到本地 files/。"""
    markers: List[str] = []
    local_files = task_dir(project["name"], task) / "files"
    local_files.mkdir(parents=True, exist_ok=True)
    remote_dir = task_remote_dir(project["server"], task).rstrip("/")
    pairs = [("POSCAR", f"{remote_dir}/POSCAR")]
    contcar_remote = (
        f"{remote_dir}/{latest_dir}/CONTCAR" if latest_dir else f"{remote_dir}/CONTCAR"
    )
    pairs.append(("CONTCAR", contcar_remote))
    if latest_dir:
        markers.append(f"结构对比使用续算输出 {latest_dir}/CONTCAR")
    for filename, remote_path in pairs:
        local_path = local_files / filename
        ok = False
        try:
            ok = ssh.download_file(project["server"], remote_path, str(local_path))
        except Exception as e:  # noqa: BLE001 - 下载失败仅记录标记
            markers.append(f"{filename} 下载失败：{e}")
        if not ok:
            markers.append(
                "POSCAR缺失或内容为空" if filename == "POSCAR" else "CONTCAR未生成或内容为空"
            )
    return markers


def _merge_notes(existing: Optional[str], markers: List[str]) -> str:
    parts: List[str] = []
    if existing:
        parts.append(existing)
    for marker in markers:
        if marker not in (existing or "") and marker not in parts:
            parts.append(marker)
    return "；".join(parts)


def _apply_result(
    db: Dict[str, Any],
    project: Dict[str, Any],
    task: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """将单个任务结果按状态机回填数据库，非法流转保持原状态并记录警告。"""
    task_id = task["task_id"]
    old_status = task.get("status")
    new_status = result.get("status", old_status)
    server_status = new_status
    observed_changed = server_status != old_status
    energy = result.get("last_energy")
    queue_status = result.get("queue_status")
    current_output = result.get("current_output")
    latest_dir = ""
    if isinstance(current_output, dict):
        latest_dir = str(current_output.get("latest_dir") or "")
        server = project.get("server")
        for key in ("dir", "contcar_path", "outcar_path", "oszicar_path"):
            if current_output.get(key):
                current_output[key] = to_remote_rel(server, str(current_output[key]))
    old_output = task.get("current_output")
    old_latest = (
        old_output.get("latest_dir") if isinstance(old_output, dict) else None
    )
    latest_changed = (old_latest or "") != (latest_dir or "")
    notes_markers: List[str] = [str(m) for m in result.get("error_messages", []) or []]
    if not (task.get("job_id") or result.get("job_id")) and new_status != "completed":
        notes_markers.append("未见有效完成日志")

    markers: List[str] = []
    # 结构优化任务：最新有效输出目录变化（续算推进到新 conN）或任务状态变化时，
    # 下载并校验 POSCAR/CONTCAR；其余情况保留上一次结果
    if (
        task.get("task_type") == STRUCTURE_OPT_TYPE
        and (observed_changed or latest_changed)
    ):
        try:
            markers = _sync_and_validate_structure(project, task, latest_dir)
        except Exception as e:  # noqa: BLE001 - 结构校验异常不阻塞巡检
            markers.append(f"结构文件同步异常：{e}")
    notes_markers.extend(markers)

    notes = _merge_notes(task.get("notes"), notes_markers)
    status_changed = False
    rejected: Optional[str] = None
    warnings: List[str] = []
    extra_fields: Dict[str, Any] = {}
    if energy is not None:
        extra_fields["last_energy"] = round(float(energy), 8)
    # job_id：本次巡检按最新输出目录匹配，匹配到则回填（用于 bjobs 判定）；
    # 匹配不到时**保留**已有 job_id（提交过的作业号是历史记录，不被巡检清除）
    if result.get("job_id"):
        extra_fields["job_id"] = str(result["job_id"])
    if notes:
        extra_fields["notes"] = notes
    if current_output:
        extra_fields["current_output"] = current_output
    try:
        update_task_status(
            db, project["name"], task_id, new_status, extra_fields or None
        )
        status_changed = new_status != old_status
    except ValueError as e:
        rejected = str(e)
        new_status = old_status
        warnings.append(f"状态更新被拒绝：{e}")

    return {
        "project": project["name"],
        "task_id": task_id,
        "model_name": task.get("model_name"),
        "task_type": task.get("task_type"),
        "old_status": old_status,
        "new_status": new_status,
        "energy": energy,
        "queue_status": queue_status,
        "notes": notes_markers,
        "markers": markers,
        "warnings": warnings,
        "status_changed": status_changed,
        "observed_changed": observed_changed,
        "latest_changed": latest_changed,
        "server_status": server_status,
        "rejected": rejected,
    }


def run_inspection(
    project_name: Optional[str] = None, task_id: Optional[str] = None
) -> Dict[str, Any]:
    """执行一轮巡检并返回摘要（前端「立即巡检」调用）。"""
    # 串行事务：并发巡检（多个单任务）不会互相覆盖数据库回填
    with db_transaction() as db:
        return _run_inspection_locked(db, project_name, task_id)


def _run_inspection_locked(
    db: Dict[str, Any],
    project_name: Optional[str],
    task_id: Optional[str],
) -> Dict[str, Any]:
    """数据库锁内的巡检主体（读取、SSH 检查、回填、归档、保存）。"""

    if task_id is not None:
        # 单任务巡检：跳过状态筛选，直接定位任务（任意状态均可巡检）
        pair = _find_task(db, project_name, task_id)
        if pair is None:
            raise ValueError(f"任务 '{task_id}' 不存在")
        server = pair[0].get("server") or ""
        if not server:
            raise ValueError(f"任务 '{task_id}' 未配置服务器，无法巡检")
        by_server = {server: [pair]}
        skipped_projects: List[str] = []
    else:
        by_server, skipped_projects = _filter_tasks(db, project_name)
    rows: List[Dict[str, Any]] = []
    inspected = updated = unchanged = warnings_count = 0
    rejected: List[Dict[str, str]] = []
    archived_files: List[str] = []

    for server, pairs in by_server.items():
        ts = _timestamp()
        results = _run_server_batch(server, pairs, ts)
        results_by_id = {r.get("task_id"): r for r in results}
        server_rows = []
        for project, task in pairs:
            row = _apply_result(db, project, task, results_by_id.get(task["task_id"], {}))
            server_rows.append(row)
            rows.append(row)
            inspected += 1
            if row["status_changed"]:
                updated += 1
            elif not row["rejected"]:
                unchanged += 1
            if row["rejected"]:
                rejected.append({"task_id": row["task_id"], "message": row["rejected"]})
            warnings_count += len(row["warnings"])

        # 富化（prev_status / observed_changed / analysis_needed）并归档
        row_by_id = {r["task_id"]: r for r in server_rows}
        enriched = []
        for entry in results:
            enriched_entry = dict(entry)
            row = row_by_id.get(entry.get("task_id"))
            if row is not None:
                enriched_entry["prev_status"] = row["old_status"]
                enriched_entry["observed_changed"] = row["observed_changed"]
                # 结构分析范围：结构优化 + 最新输出目录变化 或 任务状态变化
                enriched_entry["analysis_needed"] = (
                    row["task_type"] == STRUCTURE_OPT_TYPE
                    and (row["observed_changed"] or row["latest_changed"])
                )
                enriched_entry["checked_at"] = now_iso()
                enriched_entry["project_name"] = row["project"]
                enriched_entry["notes"] = "；".join(row["notes"]) if row["notes"] else ""
                enriched_entry["markers"] = row["markers"]
            enriched.append(enriched_entry)
        archived_files.append(archive_results(enriched, server, ts))

    # 状态/备注/巡检时间落库由 db_transaction 统一保存（含备份）

    run_id = f"run_{_timestamp()}"
    summary = {
        "run_id": run_id,
        "checked_at": now_iso(),
        "inspected": inspected,
        "updated": updated,
        "unchanged": unchanged,
        "warnings": warnings_count,
        "rejected": rejected,
        "skipped_projects": skipped_projects,
        "archived_files": archived_files,
    }
    record_run(summary)
    return summary
