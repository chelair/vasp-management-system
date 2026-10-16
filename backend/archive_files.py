"""归档时**后台回传**原始大文件（2026-10-16 用户口径）。

> "bader 和功函数要回传 ACF.dat 和 LOCPOT，LOCPOT 比较大，可以放在归档时后台回传"

两个文件：

- **`ACF.dat`**（几十 KB）：Bader 分析链路本来就会回传（`<任务>/bader/ACF.dat`）；
  这里做**兜底**：本地还没有、而远端任务目录（或 `.bader_sum/`）里已经有 `ACF.dat` 时，
  归档时顺手拉回来（历史任务 / 用户自己跑过 bader 的情况）。
- **`LOCPOT`**（**可能几百 MB**）：功函数链路以前只回传 8 KB 的 `PLANAR_AVERAGE.dat`，
  LOCPOT 一直留在集群上；现在归档时在后台线程里把它回传一份到本地镜像
  **`<任务>/files/LOCPOT`**（与 POSCAR/CONTCAR/OUTCAR 同一个本地镜像目录）。

设计要点：

- **不阻塞归档**：归档接口只起线程，接口立刻返回（几百 MB 传几分钟很正常）；
- **串行**：同一任务只跑一个（内存 run 表），全局同时只下载一个文件（链路别打满）；
- **幂等**：本地已有且大小与远端一致 → 跳过；大小不一致（远端重算过）→ 覆盖；
- **原子落盘**：先下到 `.tmp` 再 `os.replace`，失败保留旧文件、原因写进记录；
- **状态可读**：`task["archive_files"]` = `{locpot: {...}, acf: {...}, updated_at: ...}`，
  每个文件带 `state`（pending / downloading / done / skipped / failed）、`bytes`、
  `elapsed_seconds`、`error`、`at`；功函数面板与巡检详情读它显示进度。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict

import ssh
from dates import now_iso
from storage import db_transaction
from task_paths import task_dir, task_remote_dir

LOGGER = logging.getLogger(__name__)

LOCPOT_NAME = "LOCPOT"
ACF_NAME = "ACF.dat"
#: bader 中间产物目录（`chgsum.pl` + `bader` 在里面跑，ACF.dat 可能只在这里）
ACF_SUM_DIR = ".bader_sum"

#: 全局串行：同时只回传一个大文件（避免把 SSH 链路打满）
_DOWNLOAD_LOCK = threading.Lock()
#: run 状态：run_id → {...}
_RUNS: Dict[str, Dict[str, Any]] = {}
#: 任务当前 run：task_id → run_id
_TASK_RUN: Dict[str, str] = {}
_LOCK = threading.Lock()


def local_paths(project_name: str, task: Dict[str, Any]) -> Dict[str, Path]:
    """两个文件的本地落点（与既有约定一致）：LOCPOT 进 `files/`，ACF.dat 进 `bader/`。"""
    base = task_dir(project_name, task)
    return {
        "locpot": base / "files" / LOCPOT_NAME,
        "acf": base / "bader" / ACF_NAME,
    }


def status(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """本地状态（纯本地读，不连远端）：两个文件在不在、多大 + 最近一次回传记录。"""
    paths = local_paths(project_name, task)
    out: Dict[str, Any] = {}
    for key, path in paths.items():
        try:
            exists = path.is_file() and path.stat().st_size > 0
            out[key] = {
                "path": str(path),
                "present": exists,
                "bytes": path.stat().st_size if exists else 0,
                "mtime": int(path.stat().st_mtime) if exists else 0,
            }
        except OSError:
            out[key] = {"path": str(path), "present": False, "bytes": 0, "mtime": 0}
    out["record"] = dict(task.get("archive_files") or {})
    run_id = _TASK_RUN.get(str(task.get("task_id") or ""), "")
    run = dict(_RUNS.get(run_id) or {})
    out["running"] = bool(run) and run.get("status") == "running"
    if run:
        out["run"] = {
            k: run.get(k)
            for k in ("run_id", "status", "file", "bytes_done", "bytes_total", "started_at", "error")
            if run.get(k) is not None
        }
    return out


# ------------------------------------------------------------------ 远端探测


def _remote_probe_script(remote_dir: str) -> str:
    """一次 exec 拿两个文件（含 `.bader_sum/ACF.dat`）的大小。"""
    return (
        f'cd "{remote_dir}" 2>/dev/null || {{ echo "@@@NODIR"; exit 3; }}\n'
        f'for f in {LOCPOT_NAME} {ACF_NAME} {ACF_SUM_DIR}/{ACF_NAME}; do\n'
        '  if [ -s "$f" ]; then echo "@@@FILE $f $(stat -c %s "$f")"; fi\n'
        "done\n"
        'echo "@@@DONE"\n'
    )


def probe(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """远端有哪些文件（一次 exec）：`{"LOCPOT": 197000000, "ACF.dat": 8321, ...}`。"""
    server = str(project.get("server") or "")
    remote_dir = task_remote_dir(server, task)
    if not remote_dir:
        return {"ok": False, "reason": "任务缺少远程目录", "sizes": {}}
    try:
        result = ssh.run_remote(server, _remote_probe_script(remote_dir), timeout=60)
    except Exception as exc:  # noqa: BLE001 - 探测失败不致命
        return {"ok": False, "reason": f"远端探测失败：{exc}", "sizes": {}}
    text = str(result.get("stdout") or "")
    if "@@@NODIR" in text:
        return {"ok": False, "reason": f"远端目录不存在：{remote_dir}", "sizes": {}}
    sizes: Dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "@@@FILE":
            try:
                sizes[parts[1]] = int(parts[2])
            except ValueError:
                continue
    return {"ok": True, "sizes": sizes, "remote_dir": remote_dir}


# ------------------------------------------------------------------ 后台回传


def _set_stage(run_id: str, stage: str, **extra: Any) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update({"stage": stage, **extra})


def _write_record(project_name: str, task_id: str, payload: Dict[str, Any]) -> None:
    """把回传记录写进任务（`task["archive_files"]`）—— 面板 / 巡检详情都读它。"""
    try:
        with db_transaction() as db:
            project = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = (
                next(
                    (t for t in project.get("tasks", []) if str(t.get("task_id")) == task_id),
                    None,
                )
                if project
                else None
            )
            if task is not None:
                current = dict(task.get("archive_files") or {})
                current.update(payload)
                current["updated_at"] = now_iso()
                task["archive_files"] = current
    except Exception as exc:  # noqa: BLE001 - 记台账失败不影响回传结果
        LOGGER.warning("写 archive_files 记录失败（%s/%s）：%s", project_name, task_id, exc)


def _download_one(
    run_id: str,
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    key: str,
    remote_rel: str,
    remote_bytes: int,
    target: Path,
) -> Dict[str, Any]:
    """下载一个文件（原子落盘 + 大小校验），返回该文件的记录。"""
    server = str(project.get("server") or "")
    remote_dir = task_remote_dir(server, task)
    remote_path = f"{remote_dir}/{remote_rel}"
    started = time.time()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    _set_stage(run_id, "downloading", file=key, bytes_done=0, bytes_total=remote_bytes)

    def progress(done: int, total: int) -> None:
        _set_stage(run_id, "downloading", file=key, bytes_done=done, bytes_total=total)

    try:
        with _DOWNLOAD_LOCK:  # 全局串行：一次只传一个大文件
            ok = ssh.download_file(
                server, remote_path, str(tmp), timeout=3600, progress_cb=progress
            )
        if not ok or not tmp.is_file() or tmp.stat().st_size <= 0:
            raise RuntimeError("下载失败或文件为空")
        size = tmp.stat().st_size
        if remote_bytes and size != remote_bytes:
            LOGGER.warning(
                "%s 大小不一致（远端 %s / 本地 %s），以本地为准", key, remote_bytes, size
            )
        tmp.replace(target)  # 同目录 rename → 原子替换
        return {
            "state": "done",
            "bytes": size,
            "remote_bytes": remote_bytes,
            "elapsed_seconds": round(time.time() - started, 1),
            "at": now_iso(),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响另一个
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "state": "failed",
            "bytes": 0,
            "remote_bytes": remote_bytes,
            "elapsed_seconds": round(time.time() - started, 1),
            "at": now_iso(),
            "error": str(exc),
        }


def _background(project: Dict[str, Any], task: Dict[str, Any], run_id: str) -> None:
    """后台线程：探测 → 逐个回传（已一致就跳过）→ 写记录。"""
    project_name = str(project.get("name") or "")
    task_id = str(task.get("task_id") or "")
    paths = local_paths(project_name, task)
    try:
        result = probe(project, task)
        if not result.get("ok"):
            reason = str(result.get("reason") or "远端探测失败")
            _set_stage(run_id, "failed", error=reason)
            _write_record(project_name, task_id, {"state": "failed", "error": reason})
            return
        sizes = result.get("sizes") or {}
        # ACF.dat 可能在任务目录，也可能只在 `.bader_sum/`
        acf_rel = None
        for candidate in (ACF_NAME, f"{ACF_SUM_DIR}/{ACF_NAME}"):
            if sizes.get(candidate):
                acf_rel = candidate
                break
        wanted: list[tuple[str, str | None, int, Path]] = [
            ("locpot", LOCPOT_NAME, int(sizes.get(LOCPOT_NAME, 0)), paths["locpot"]),
            ("acf", acf_rel, int(sizes.get(acf_rel or "", 0)), paths["acf"]),
        ]
        record: Dict[str, Any] = {}
        for key, remote_rel, remote_bytes, target in wanted:
            if not remote_rel or not remote_bytes:
                record[key] = {
                    "state": "skipped",
                    "bytes": 0,
                    "at": now_iso(),
                    "error": None,
                    "note": "远端没有该文件",
                }
                _write_record(project_name, task_id, record)
                continue
            try:
                local_size = target.stat().st_size if target.is_file() else 0
            except OSError:
                local_size = 0
            if local_size == remote_bytes:
                record[key] = {
                    "state": "skipped",
                    "bytes": local_size,
                    "at": now_iso(),
                    "error": None,
                    "note": "本地已有同大小文件",
                }
                _write_record(project_name, task_id, record)
                continue
            record[key] = _download_one(
                run_id,
                project,
                task,
                key=key,
                remote_rel=remote_rel,
                remote_bytes=remote_bytes,
                target=target,
            )
            _write_record(project_name, task_id, record)  # 每传完一个落一次台账
        _set_stage(run_id, "done")
        _write_record(project_name, task_id, {**record, "state": "done", "at": now_iso(), "error": None})
        LOGGER.info("归档回传完成：%s/%s %s", project_name, task_id, record)
    except Exception as exc:  # noqa: BLE001 - 后台线程不能把异常抛出去
        LOGGER.exception("归档回传失败：%s/%s", project_name, task_id)
        _set_stage(run_id, "failed", error=str(exc))
        _write_record(project_name, task_id, {"state": "failed", "error": str(exc)})
    finally:
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is not None:
                run.update({"status": "done", "finished_at": now_iso()})


def start(project: Dict[str, Any], task: Dict[str, Any], *, force: bool = True) -> Dict[str, Any]:
    """起一个后台回传任务（不阻塞调用方）。已有在跑的直接复用那个 run。"""
    project_name = str(project.get("name") or "")
    task_id = str(task.get("task_id") or "")
    if not task_remote_dir(str(project.get("server") or ""), task):
        return {"started": False, "reason": "任务缺少远程目录"}
    with _LOCK:
        current = _TASK_RUN.get(task_id)
        if current and _RUNS.get(current, {}).get("status") == "running":
            return {"started": False, "reused": True, "run_id": current, "reason": "已有回传在跑"}
        run_id = f"af_{int(time.time() * 1000)}"
        _RUNS[run_id] = {
            "run_id": run_id,
            "task_id": task_id,
            "status": "running",
            "stage": "probing",
            "started_at": now_iso(),
        }
        _TASK_RUN[task_id] = run_id
    _write_record(
        project_name,
        task_id,
        {"state": "running", "force": bool(force), "at": now_iso(), "error": None},
    )
    threading.Thread(
        target=_background,
        args=(dict(project), dict(task), run_id),
        name=f"archive-files-{task_id}",
        daemon=True,
    ).start()
    return {"started": True, "run_id": run_id}
