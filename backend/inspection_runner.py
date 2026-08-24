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
from storage import load_db, save_db, update_task_status

SKIPPED_STATUSES = ("pending", "archived")
STRUCTURE_OPT_TYPE = "structure_opt"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _filter_tasks(
    db: Dict[str, Any],
    project_name: Optional[str],
    task_id: Optional[str],
) -> Tuple[Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]], List[str]]:
    """筛选待巡检任务并按服务器分组；返回 (by_server, skipped_projects)。"""
    by_server: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    skipped: List[str] = []
    for project in db.get("projects", []):
        if project_name is not None and project.get("name") != project_name:
            continue
        targets = [
            t for t in project.get("tasks", []) if t.get("status") not in SKIPPED_STATUSES
        ]
        if task_id is not None:
            targets = [t for t in targets if t.get("task_id") == task_id]
        if not targets:
            skipped.append(project.get("name"))
            continue
        by_server.setdefault(project.get("server"), []).extend(
            (project, task) for task in targets
        )
    return by_server, skipped


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
    script_dir = str(Path(batch_path).parent)
    remote_input = f"/tmp/vasp_tasks_{timestamp}.json"
    remote_output = f"/tmp/vasp_results_{timestamp}.json"

    # 上传脚本与阈值配置（自动部署，无需手动同步）
    ssh.mkdir_remote(server, script_dir)
    ssh.upload_file(server, str(script_local), batch_path)
    ssh.upload_file(server, str(registry_local), f"{script_dir}/check_registry.json")

    manifest = [
        {
            "task_id": task["task_id"],
            "remote_dir": task.get("remote_dir", ""),
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
    project: Dict[str, Any], task: Dict[str, Any]
) -> List[str]:
    """下载 POSCAR/CONTCAR 到本地 files/ 并校验非空，返回缺失标记。"""
    markers: List[str] = []
    local_files = (
        PROJECTS_DIR
        / project["name"]
        / task["task_type"]
        / task["model_name"]
        / "files"
    )
    local_files.mkdir(parents=True, exist_ok=True)
    remote_dir = str(task.get("remote_dir", "")).rstrip("/")
    for filename in ("POSCAR", "CONTCAR"):
        remote_path = f"{remote_dir}/{filename}"
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
    notes_markers: List[str] = [str(m) for m in result.get("error_messages", []) or []]
    if not task.get("job_id") and new_status != "completed":
        notes_markers.append("未见有效完成日志")

    markers: List[str] = []
    # 仅当两次巡检之间状态发生变化（如 running→completed / running→zombied）
    # 且任务为结构优化、到达终态时，才下载并校验 POSCAR/CONTCAR
    if (
        task.get("task_type") == STRUCTURE_OPT_TYPE
        and observed_changed
        and new_status in ("completed", "zombied")
    ):
        try:
            markers = _sync_and_validate_structure(project, task)
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
    if task.get("job_id") is not None:
        extra_fields["job_id"] = task["job_id"]
    if notes:
        extra_fields["notes"] = notes
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
        "server_status": server_status,
        "rejected": rejected,
    }


def run_inspection(
    project_name: Optional[str] = None, task_id: Optional[str] = None
) -> Dict[str, Any]:
    """执行一轮巡检并返回摘要（前端「立即巡检」调用）。"""
    db = load_db()

    # 预检：指定任务必须存在且处于待巡检状态
    if task_id is not None:
        found = any(
            t.get("task_id") == task_id and t.get("status") not in SKIPPED_STATUSES
            for p in db.get("projects", [])
            if project_name is None or p.get("name") == project_name
            for t in p.get("tasks", [])
        )
        if not found:
            raise ValueError(f"任务 '{task_id}' 不存在或无需巡检")

    by_server, skipped_projects = _filter_tasks(db, project_name, task_id)
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
                # 结构分析范围：结构优化 + 两次巡检状态有变化 + 到达终态
                enriched_entry["analysis_needed"] = (
                    row["task_type"] == STRUCTURE_OPT_TYPE
                    and row["observed_changed"]
                    and row["new_status"] in ("completed", "zombied")
                )
                enriched_entry["checked_at"] = now_iso()
                enriched_entry["project_name"] = row["project"]
                enriched_entry["notes"] = "；".join(row["notes"]) if row["notes"] else ""
                enriched_entry["markers"] = row["markers"]
            enriched.append(enriched_entry)
        archived_files.append(archive_results(enriched, server, ts))

    # 状态/备注/巡检时间落库（含备份）
    save_db(db)

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
