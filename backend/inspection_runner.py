"""巡检编排：上传 batch_check → 服务器批量解析 → 结果回填 → 归档（对齐参考 check_remote.py）。

Web 化改造：
- 不再生成 HTML 报告（由前端巡检中心页面呈现）；
- batch_check.py / check_registry.json 由本系统上传到服务器（无需手动部署）；
- 支持 VASP_SSH_MOCK 本地模拟，便于离线验证；
- 状态回填复用 storage.update_task_status（与 project_db.py 一致的状态机）。
"""

import base64
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from checks_store import archive_results, record_run
from cif_convert import convert_structure_to_cif
from config import PROJECTS_DIR, load_servers
from continuation import compute_g_correction
from dates import now_iso
from paths import to_remote_rel
from storage import db_transaction, get_project, load_db, update_task_status
from task_paths import task_dir, task_remote_dir

SKIPPED_STATUSES = ("pending", "archived")
STRUCTURE_OPT_TYPE = "opt"
NEB_TYPE = "neb"


def _ionic_steps(result: Dict[str, Any], task_type: str = "") -> int:
    """离子步数（结构分析 25 步一桶的度量）。

    - opt：巡检结果 force_history 的长度（与详情页展示口径一致）；
    - neb：中间映像离子步的最大值（batch_check 回传的 neb_band_steps）。
    """
    if task_type == NEB_TYPE:
        value = result.get("neb_band_steps")
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0
    history = result.get("force_history")
    return len(history) if isinstance(history, list) else 0


def _analysis_bucket(steps: int) -> int:
    """每 25 个离子步一个分析桶：0-24→0，25-49→1，50-74→2…"""
    return steps // 25 if steps > 0 else 0


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _manifest_entry(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """远端 batch_check 的任务清单条目。"""
    return {
        "task_id": task["task_id"],
        "remote_dir": task_remote_dir(project["server"], task),
        "job_id": task.get("job_id") or "",
        "task_type": task.get("task_type", ""),
        "project_name": project["name"],
    }


def _plan_batches(
    db: Dict[str, Any],
    project_name: Optional[str],
    task_id: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """规划巡检批次：**每个项目一个批次**（同一服务器可多个批次）。

    - 全局巡检：跳过 pending / archived 任务与已关闭项目；无待巡检任务的项目记入 skipped。
    - 单任务巡检：不做状态筛选；自由能组的 opt 任务会带上同目录的 frac 子任务一起检查。
    返回 (batches, skipped_projects)，batch 结构：
      {server, project_name, task_ids, manifest}
    """
    batches: List[Dict[str, Any]] = []
    skipped: List[str] = []

    if task_id is not None:
        pair = _find_task(db, project_name, task_id)
        if pair is None:
            raise ValueError(f"任务 '{task_id}' 不存在")
        project, task = pair
        # 已关闭（归档）的任务不允许再巡检：否则观测状态会把 archived 覆盖回去
        if str(task.get("status") or "") == "archived":
            raise ValueError(
                f"任务「{task.get('model_name') or task_id}」已关闭（归档），"
                "请先「重新打开」再巡检"
            )
        server = project.get("server") or ""
        if not server:
            raise ValueError(f"任务 '{task_id}' 未配置服务器，无法巡检")
        targets = [task]
        # 自由能 opt 单任务巡检：顺带检查其 frac 频率矫正子任务
        # （frac 目录有输出才产生数据，未收敛/未生成时结果为空，不影响主任务）
        if (
            task.get("task_type") == STRUCTURE_OPT_TYPE
            and (task.get("group") or {}).get("group_type") == "free_energy"
        ):
            frac_task = next(
                (
                    t
                    for t in project.get("tasks", [])
                    if t.get("dir_path") == f"{task.get('dir_path', '')}/frac"
                ),
                None,
            )
            if frac_task is not None:
                targets.append(frac_task)
        return (
            [
                {
                    "server": server,
                    "project_name": str(project.get("name") or ""),
                    "task_ids": [t["task_id"] for t in targets],
                    "manifest": [_manifest_entry(project, t) for t in targets],
                }
            ],
            [],
        )

    for project in db.get("projects", []):
        if project_name is not None and project.get("name") != project_name:
            continue
        name = str(project.get("name") or "")
        # 已关闭的项目不再巡检（关闭前提是全部任务已归档，正常情况下也不会命中）
        if project.get("closed"):
            skipped.append(name)
            continue
        targets = [
            t
            for t in project.get("tasks", [])
            if t.get("status") not in SKIPPED_STATUSES
        ]
        if not targets or not project.get("server"):
            skipped.append(name)
            continue
        batches.append(
            {
                "server": project.get("server"),
                "project_name": name,
                "task_ids": [t["task_id"] for t in targets],
                "manifest": [_manifest_entry(project, t) for t in targets],
            }
        )
    return batches, skipped


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


def _ensure_scripts(server: str) -> None:
    """把 batch_check.py 与 check_registry.json 上传到服务器（每个服务器每轮一次）。"""
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
    ssh.mkdir_remote(server, script_dir)
    ssh.upload_file(server, str(script_local), batch_path)
    ssh.upload_file(server, str(registry_local), f"{script_dir}/check_registry.json")


def _run_server_batch(
    server: str,
    manifest: List[Dict[str, Any]],
    timestamp: str,
) -> List[Dict[str, Any]]:
    """上传任务清单 → 远端运行 batch_check → 下载结果（脚本/阈值由 _ensure_scripts 预置）。"""
    servers = load_servers()
    cfg = servers.get(server)
    if cfg is None:
        raise ValueError(f"服务器 '{server}' 未在 servers.json 中配置")
    batch_path = cfg.get("batch_check_path")
    if not batch_path:
        raise ValueError(f"服务器 '{server}' 未配置 batch_check_path")
    remote_input = f"/tmp/vasp_tasks_{timestamp}.json"
    remote_output = f"/tmp/vasp_results_{timestamp}.json"

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


def _sync_and_convert_structure(
    project: Dict[str, Any],
    task: Dict[str, Any],
    latest_dir: str = "",
) -> List[str]:
    """下载 POSCAR（主目录）与最新 CONTCAR（续算目录优先），并用 vasp2cif 转为 CIF。"""
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

    # 用 vasp2cif 脚本把下载的结构转为 CIF（触发=新结果，覆盖旧 CIF；失败保留旧文件）
    report_dir = local_files.parent / "reports" / "structure"
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in ("POSCAR", "CONTCAR"):
        src = local_files / name
        out = report_dir / f"{name}.cif"
        if not src.is_file() or src.stat().st_size == 0:
            markers.append(f"{name} 缺失或为空，跳过 CIF 转换")
            continue
        if not convert_structure_to_cif(src, out, overwrite=True):
            markers.append(f"{name}.cif 转换失败（保留上一次结果）")
    return markers


def _merge_notes(existing: Optional[str], markers: List[str]) -> str:
    parts: List[str] = []
    if existing:
        parts.append(existing)
    for marker in markers:
        if marker not in (existing or "") and marker not in parts:
            parts.append(marker)
    return "；".join(parts)


NEB_IMAGE_DIR = "images"


def _sync_neb_image_structures(
    project: Dict[str, Any],
    task: Dict[str, Any],
    latest_dir: str = "",
) -> List[str]:
    """同步 NEB 各映像的**优化后结构**（IS → 中间态 → FS），生成 CIF。

    - 每个数字映像目录取 CONTCAR（优化后几何），没有 CONTCAR 时退回 POSCAR；
    - 用**单次远端 bash 脚本**把各映像结构 base64 回传（避免 N 次 SSH 往返）；
    - 原始结构写入 <任务>/files/neb_images/<label>，CIF 写入
      <任务>/reports/structure/images/<label>.cif（覆盖旧结果，失败保留旧文件）。
    """
    markers: List[str] = []
    server = project["server"]
    remote_dir = task_remote_dir(server, task).rstrip("/")
    con_dir = f"{remote_dir}/{latest_dir}" if latest_dir else remote_dir
    if latest_dir:
        markers.append(f"NEB 映像结构取自续算输出 {latest_dir}/")

    script = "\n".join(
        [
            "set -e",
            f'BASE="{con_dir}"',
            'for d in "$BASE"/[0-9]*; do',
            '  [ -d "$d" ] || continue',
            '  img=$(basename "$d")',
            # 只取 CONTCAR（优化后的结构）；缺 CONTCAR 的映像直接跳过，
            # 不再回退 POSCAR —— 映像的 POSCAR 是 nebmake 插值出来的初始结构，
            # 当成"优化后结构"展示会误导（2026-09-15 用户要求）
            '  f="$d/CONTCAR"',
            '  [ -s "$f" ] || continue',
            '  echo "@@@IMG:$img:CONTCAR"',
            '  base64 "$f" | tr -d "\\n"',
            '  echo',
            "done",
        ]
    )
    result = ssh.run_remote(server, script, timeout=120)
    if result.get("exit_code") != 0 or not result.get("stdout"):
        raise RuntimeError(
            (result.get("stderr") or result.get("stdout") or "远端读取映像结构失败").strip()[:200]
        )

    task_root = task_dir(project["name"], task)
    raw_dir = task_root / "files" / "neb_images"
    cif_dir = task_root / "reports" / "structure" / NEB_IMAGE_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    cif_dir.mkdir(parents=True, exist_ok=True)

    labels: List[str] = []
    current: Optional[str] = None
    buffer: List[str] = []
    sections: List[tuple] = []
    for line in result["stdout"].splitlines():
        if line.startswith("@@@IMG:"):
            if current:
                sections.append((current, "".join(buffer)))
            parts = line.split(":")
            current = parts[1] if len(parts) > 1 else ""
            buffer = []
            continue
        if current:
            buffer.append(line.strip())
    if current:
        sections.append((current, "".join(buffer)))

    for label, payload in sections:
        if not payload:
            continue
        try:
            data = base64.b64decode(payload)
        except Exception as e:  # noqa: BLE001 - 单个映像解码失败不影响其他映像
            markers.append(f"映像 {label} 结构解码失败：{e}")
            continue
        raw_path = raw_dir / label
        tmp_path = raw_dir / f"{label}.tmp"
        tmp_path.write_bytes(data)
        tmp_path.replace(raw_path)
        out = cif_dir / f"{label}.cif"
        if convert_structure_to_cif(raw_path, out, overwrite=True):
            labels.append(label)
        else:
            markers.append(f"映像 {label} CIF 转换失败（保留上一次结果）")

    if labels:
        labels.sort(key=lambda x: int(x) if x.isdigit() else 999)
        markers.append(
            f"NEB 映像结构已同步：{labels[0]}–{labels[-1]}（共 {len(labels)} 个，只取 CONTCAR）"
        )
    else:
        markers.append("未取到任何 NEB 映像结构（目录为空，或映像还没有 CONTCAR）")
    return markers


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
    # 「低精度收敛」是巡检判定的细分结论：数据库里仍按 completed 记
    # （进度/看板口径不变），但归档结果与巡检列表保留这个更细的状态
    db_status = "completed" if new_status == "low_precision" else new_status
    # 未读红点/状态变化用落库口径比较：低精度收敛每轮都会重新判定，
    # 但数据库状态仍是 completed，不该每轮都算"状态变化"
    server_status = db_status
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
    if not (task.get("job_id") or result.get("job_id")) and db_status != "completed":
        notes_markers.append("未见有效完成日志")

    # 结构分析触发条件（替换原“状态变化或最新输出目录变化”）：
    # - 每 25 个离子步一个桶（0-24→0，25-49→1，50-74→2…），桶 ≥ 1 才可能触发；
    # - 同一目录：仅当离子步桶比上次触发时更大才再次触发（25-49 触发后，
    #   再次巡检仍在 25-49 不触发，直到 50-74 及以后）；
    # - 目录变化：视为新目录重新计数（有效上桶重置为 -1），重复上述规则；
    # - 其余筛选（opt 类型等）保持不变。
    task_type = str(task.get("task_type") or "")
    steps = _ionic_steps(result, task_type)
    bucket = _analysis_bucket(steps)
    prev_bucket = int(task.get("last_analysis_bucket") or -1)
    prev_dir = str(task.get("last_analysis_dir") or "")
    dir_changed = (latest_dir or "") != prev_dir
    effective_prev_bucket = -1 if dir_changed else prev_bucket
    # 结构分析触发条件（opt 与 neb 相同）：25 步一桶、桶号推进才触发、目录变化重置
    should_analyze = task_type in (STRUCTURE_OPT_TYPE, NEB_TYPE) and bucket >= 1 and bucket > effective_prev_bucket

    markers: List[str] = []
    structure_synced = False
    extra_fields: Dict[str, Any] = {}
    if should_analyze:
        structure_synced = True
        try:
            if task_type == NEB_TYPE:
                markers = _sync_neb_image_structures(project, task, latest_dir)
            else:
                markers = _sync_and_convert_structure(project, task, latest_dir)
        except Exception as e:  # noqa: BLE001 - 结构同步异常不阻塞巡检
            markers.append(f"结构文件同步异常：{e}")
        extra_fields["last_analysis_bucket"] = bucket
        extra_fields["last_analysis_dir"] = latest_dir or ""
    notes_markers.extend(markers)

    notes = _merge_notes(task.get("notes"), notes_markers)
    status_changed = False
    rejected: Optional[str] = None
    warnings: List[str] = []
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
            db, project["name"], task_id, db_status, extra_fields or None
        )
        status_changed = db_status != old_status
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
        "structure_synced": structure_synced,
        "steps": steps,
        "bucket": bucket,
        "server_status": server_status,
        "rejected": rejected,
    }


def run_inspection(
    project_name: Optional[str] = None, task_id: Optional[str] = None
) -> Dict[str, Any]:
    """执行一轮巡检并返回摘要（前端「立即巡检」/「单独巡检」调用）。

    批次划分：**每个项目一批**（见 `_plan_batches`）。远端检查在事务外加锁执行，
    只有"回填 + 归档"这一小段进入 `db_transaction`，因此：
    - 单个批次失败只影响该项目，其余项目照常回填（不再整轮回滚）；
    - 数据库写锁只持有回填的短暂时间，不会因一个 90 秒的远端调用锁住整个库。
    """
    db = load_db()
    batches, skipped_projects = _plan_batches(db, project_name, task_id)

    rows: List[Dict[str, Any]] = []
    archived_files: List[str] = []
    failures: List[Dict[str, str]] = []
    inspected = updated = unchanged = warnings_count = 0
    rejected: List[Dict[str, str]] = []
    ensured_servers: set = set()

    for batch in batches:
        server = str(batch["server"])
        try:
            if server not in ensured_servers:
                _ensure_scripts(server)
                ensured_servers.add(server)
            ts = _timestamp()
            # 远端检查在事务外：任务清单已在规划阶段生成，不需要持有数据库写锁
            results = _run_server_batch(server, batch["manifest"], ts)
            batch_rows, archived = _apply_batch(
                server, batch["project_name"], batch["task_ids"], results, ts
            )
        except Exception as e:  # noqa: BLE001 - 单批次失败不影响其他项目
            failures.append(
                {
                    "server": server,
                    "project_name": str(batch["project_name"]),
                    "error": str(e),
                }
            )
            continue

        rows.extend(batch_rows)
        archived_files.append(archived)
        for row in batch_rows:
            inspected += 1
            if row["status_changed"]:
                updated += 1
            elif not row["rejected"]:
                unchanged += 1
            if row["rejected"]:
                rejected.append({"task_id": row["task_id"], "message": row["rejected"]})
            warnings_count += len(row["warnings"])

    summary = {
        "run_id": f"run_{_timestamp()}",
        "checked_at": now_iso(),
        "inspected": inspected,
        "updated": updated,
        "unchanged": unchanged,
        "warnings": warnings_count,
        "rejected": rejected,
        "skipped_projects": skipped_projects,
        "failed_batches": failures,
        "archived_files": archived_files,
        "scope": "single" if task_id is not None else "global",
    }
    record_run(summary)

    # 全局巡检后静默刷新集群状态：作废快照缓存并后台预热（不阻塞返回）
    if task_id is None and not failures:
        try:
            from dashboard import invalidate_cluster_cache

            invalidate_cluster_cache(
                sorted({str(b["server"]) for b in batches if b.get("server")}),
                prewarm=True,
            )
        except Exception:  # noqa: BLE001 - 刷新集群状态失败不影响巡检结果
            pass
    return summary


def _apply_batch(
    server: str,
    project_name: str,
    task_ids: List[str],
    results: List[Dict[str, Any]],
    ts: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """在**独立事务**内回填一个项目的巡检结果并归档（锁只在本地写入期间持有）。"""
    with db_transaction() as db:
        project = get_project(db, project_name)
        if project is None:
            raise ValueError(f"项目 '{project_name}' 不存在（可能已被删除）")
        pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for tid in task_ids:
            task = next(
                (t for t in project.get("tasks", []) if t.get("task_id") == tid), None
            )
            if task is not None:
                pairs.append((project, task))
        if not pairs:
            return [], ""

        results_by_id = {r.get("task_id"): r for r in results}
        server_rows: List[Dict[str, Any]] = []
        for project, task in pairs:
            row = _apply_result(db, project, task, results_by_id.get(task["task_id"], {}))
            server_rows.append(row)
            # 自由能 frac 巡检完成（completed）且尚无矫正项：自动尝试计算矫正项
            if (
                task.get("task_type") == "frac"
                and row["new_status"] == "completed"
                and task.get("correction") is None
            ):
                try:
                    remote_dir = task_remote_dir(project.get("server"), task).rstrip("/")
                    task["correction"] = compute_g_correction(
                        project.get("server"), remote_dir
                    )
                    task["correction_at"] = now_iso()
                except Exception as e:  # noqa: BLE001 - 自动计算失败不阻塞巡检
                    row["warnings"].append(f"自动计算矫正项失败：{e}")

        # 富化（prev_status / observed_changed / analysis_needed）并归档
        row_by_id = {r["task_id"]: r for r in server_rows}
        enriched = []
        for entry in results:
            enriched_entry = dict(entry)
            row = row_by_id.get(entry.get("task_id"))
            if row is not None:
                enriched_entry["prev_status"] = row["old_status"]
                enriched_entry["observed_changed"] = row["observed_changed"]
                # 结构分析范围：本轮是否触发了结构同步（离子步桶推进或目录变化）
                enriched_entry["analysis_needed"] = bool(
                    row.get("structure_synced", False)
                )
                enriched_entry["checked_at"] = now_iso()
                enriched_entry["project_name"] = row["project"]
                enriched_entry["notes"] = "；".join(row["notes"]) if row["notes"] else ""
                enriched_entry["markers"] = row["markers"]
            enriched.append(enriched_entry)
        archived = archive_results(enriched, server, ts)
    return server_rows, archived
