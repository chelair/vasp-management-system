"""作业管理接口：本地任务目录的统一文件读写。

本地目录约定（v0.3.0，dir_path 为权威字段）：
    独立任务：data/projects/<项目名>/<模型名>/
    自由能组：data/projects/<项目名>/<组根>/<结构标签>/<opt|frac>/
    NEB 组：  data/projects/<项目名>/<组根>/<initial_opt|final_opt|neb_calc>/
每个任务目录下：files/（VASP 文件）、images/、reports/、continuation/
"""

from datetime import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import DATA_DIR, load_servers
from cluster_status import build_snapshot
from continuation import (
    _download_remote_text,
    _remote_latest_con,
    _write_remote_file,
    build_ele_inputs,
    compute_g_correction,
    create_continuation,
    create_frac_files,
    create_neb_files,
    local_continuation_dir,
)
from dates import now_iso
from envelope import fail, ok
from incar import modify_incar
from paths import resolve_local_path, resolve_remote_path, to_local_rel, to_remote_rel
import ssh
from storage import STATUS_ENUM, db_transaction, load_db, save_db, update_task_status
from task_paths import is_continuation_task, task_dir

router = APIRouter(prefix="/jobs", tags=["jobs"])

AUDIT_LOG = DATA_DIR / "audit_submit.log"

#: 允许读取/写入的文本文件白名单（防目录穿越；WAVECAR/CHGCAR 等二进制后续单独处理）
TEXT_FILE_WHITELIST = {
    "INCAR",
    "POSCAR",
    "KPOINTS",
    "POTCAR",
    "CONTCAR",
    "OSZICAR",
    "OUTCAR",
    "DOSCAR",
    "EIGENVAL",
    "vasprun.xml",
    "submit.sh",
    "run.sh",
}


class FileWritePayload(BaseModel):
    content: str


class RenameTaskPayload(BaseModel):
    model_name: str


NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_@]*$")


@router.get("/nodes")
def cluster_nodes(refresh: bool = False):
    """查询集群节点状态：bhost 主数据 + bqueues 补充 + node_groups 映射。

    默认使用 60 秒缓存；传入 ?refresh=1 强制重新查询。
    """
    try:
        servers = load_servers()
        server_name = next(iter(servers.keys()), "server1")
        snapshot = build_snapshot(server_name, use_cache=not refresh)
        return ok("查询成功", snapshot)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=fail(f"查询节点状态失败：{e}"),
        )


def _resolve_task_dir(task_id: str) -> Path:
    """按 task_id 定位任务本地目录（项目库 -> 任务字段）。"""
    db = load_db()
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                return task_dir(str(project.get("name", "")), task)
    raise LookupError(f"任务 {task_id} 不存在")


def _resolve_task(task_id: str):
    """返回 (project, task)，任务不存在时抛 LookupError。"""
    db = load_db()
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                return project, task
    raise LookupError(f"任务 {task_id} 不存在")


def _new_task_id(project: Dict) -> str:
    import time

    ts = int(time.time() * 1000)
    used = {t.get("task_id") for t in project.get("tasks", [])}
    seq = 1
    while f"task_{ts}_{seq}" in used:
        seq += 1
    return f"task_{ts}_{seq}"


def _validate_name(filename: str) -> str:
    if filename not in TEXT_FILE_WHITELIST:
        raise ValueError(f"不支持的文件名：{filename}")
    return filename


def _files_dir(task_dir: Path) -> Path:
    """统一文件目录为 <任务目录>/files/，不存在时退化到任务根目录扫描。"""
    files_dir = task_dir / "files"
    return files_dir if files_dir.is_dir() else task_dir


def _open_in_explorer(path: str) -> None:
    """在服务器所在机器打开文件管理器并定位到目录（Windows 资源管理器优先）。"""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined] - Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _audit_log(project: str, task_id: str, remote_dir: str, command: str, result: str) -> None:
    """提交操作审计日志（操作者、时间、任务、命令、结果）。"""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"[{datetime.now().isoformat(timespec='seconds')}] project={project} "
                f"task={task_id} dir={remote_dir} cmd={command} result={result}\n"
            )
    except Exception:  # noqa: BLE001 - 审计日志失败不影响提交
        pass


@router.get("/tasks/{task_id}/files")
def list_task_files(task_id: str):
    try:
        task_dir = _resolve_task_dir(task_id)
        scan_dir = _files_dir(task_dir)
        entries = []
        if scan_dir.is_dir():
            for f in sorted(scan_dir.iterdir(), key=lambda p: p.name.lower()):
                if not f.is_file():
                    continue
                st = f.stat()
                entries.append(
                    {
                        "name": f.name,
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
        return ok(
            "查询成功",
            {"task_id": task_id, "dir": str(scan_dir), "files": entries},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取任务目录失败：{e}"))


@router.get("/tasks/{task_id}/files/{filename}")
def read_task_file(task_id: str, filename: str):
    try:
        name = _validate_name(filename)
        task_dir = _resolve_task_dir(task_id)
        path = _files_dir(task_dir) / name
        if not path.is_file():
            return JSONResponse(
                status_code=404,
                content=fail(f"{name} 不存在于任务目录 {task_dir}"),
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        return ok("读取成功", {"name": name, "path": str(path), "content": content})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取 {filename} 失败：{e}"))


@router.put("/tasks/{task_id}/files/{filename}")
def write_task_file(task_id: str, filename: str, payload: FileWritePayload):
    try:
        name = _validate_name(filename)
        task_dir = _resolve_task_dir(task_id)
        files_dir = task_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        path = files_dir / name
        path.write_text(payload.content, encoding="utf-8")
        return ok(
            "保存成功",
            {"name": name, "path": str(path), "size": path.stat().st_size},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"写入 {filename} 失败：{e}"))


@router.post("/tasks/{task_id}/open-folder")
def open_task_folder(task_id: str):
    """在服务器本机打开任务本地目录（定位到 files/），便于直接查看/编辑文件。"""
    try:
        task_dir = _resolve_task_dir(task_id)
        files_dir = task_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        target = files_dir if files_dir.is_dir() else task_dir
        _open_in_explorer(str(target))
        return ok("已打开文件夹", {"path": str(target)})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"打开文件夹失败：{e}"))


@router.post("/tasks/{task_id}/continuation")
def create_same_type_continuation(task_id: str):
    """同类型续算：全部在远程服务器完成，创建 conN 目录并登记续算子任务。"""
    try:
        project, task = _resolve_task(task_id)
        if is_continuation_task(task):
            return JSONResponse(
                status_code=400,
                content=fail("续算子任务不支持再续算，请对原始任务操作"),
            )
        if task.get("task_type") not in ("opt", "neb"):
            return JSONResponse(
                status_code=400,
                content=fail("仅结构优化（opt）与 NEB 任务支持同类型续算"),
            )
        # 状态不做前置拦截：由续算分流逻辑按最新目录 OUTCAR/CONTCAR 判断
        # （未运行/异常任务将返回 input_incomplete / input_complete_but_not_finished）
        result = create_continuation(project.get("server"), project, task)
        if result.get("action") != "created":
            _audit_log(
                project["name"],
                task_id,
                str(result.get("current_dir", "")),
                "continuation",
                f"action={result.get('action')} missing={result.get('missing_files') or []}",
            )
            return ok(result.get("message", "续算检查完成"), result)
        # 非 NEB 续算必须得到 POSCAR（来自最新 CONTCAR）
        if task.get("task_type") != "neb" and "POSCAR" not in result.get("copied_files", []):
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"源目录缺少 CONTCAR，无法生成续算 POSCAR（源：{result.get('source_dir')}）"
                ),
            )

        # 登记续算子任务（本地镜像目录仅建空结构，文件不经过本地）
        con = result["con"]
        local_dir = local_continuation_dir(str(task.get("dir_path", "")), con)
        for sub in ("files", "images", "reports", "continuation"):
            (resolve_local_path(local_dir) / sub).mkdir(parents=True, exist_ok=True)
        now = now_iso()
        rel_remote = to_remote_rel(project.get("server"), result["remote_dir"])
        sub_task = {
            "task_id": _new_task_id(project),
            "task_type": task.get("task_type"),
            "subtype": task.get("subtype"),
            "model_name": f"{task.get('model_name', 'task')}_{con}",
            "status": "pending",
            "last_energy": None,
            "last_check_time": None,
            "job_id": None,
            "notes": f"由 {task.get('model_name')} 同类型续算创建（{con}）",
            "continuation_ready": False,
            "continuation_dir": None,
            "dir_path": local_dir,
            "remote_dir": rel_remote,
            "group": None,
            "parent_task_id": task_id,
            "input_source": {
                "poscar_from": to_remote_rel(
                    project.get("server"), f"{result['source_dir']}/CONTCAR"
                ),
                "potcar_from": None,
                "kpoints_from": None,
            },
            "created_at": now,
            "updated_at": now,
        }
        from storage import save_db

        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        if any(t.get("dir_path") == local_dir for t in proj["tasks"]):
            return JSONResponse(
                status_code=409,
                content=fail(f"续算目录 {con} 已登记，请勿重复创建"),
            )
        proj["tasks"].append(sub_task)
        save_db(db)

        return ok(
            "续算目录已创建",
            {
                **result,
                "task_id": sub_task["task_id"],
                "local_dir": local_dir,
                "remote_dir": rel_remote,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建续算失败：{e}"))


@router.post("/tasks/{task_id}/create-frac")
def create_frac(task_id: str, payload: dict = Body(default={})):
    """为结构优化任务构建频率矫正（frac）输入文件（自由能流程）。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "opt":
            return JSONResponse(status_code=400, content=fail("仅结构优化任务可创建频率矫正"))
        frac_task = next(
            (
                t
                for t in project["tasks"]
                if t.get("dir_path") == f"{task.get('dir_path', '')}/frac"
            ),
            None,
        )
        if frac_task is None:
            return JSONResponse(
                status_code=404,
                content=fail("未找到对应的频率矫正子任务（frac），请先在自由能组中创建"),
            )
        result = create_frac_files(
            project["server"],
            project,
            task,
            frac_task,
            params=payload.get("params") or {},
        )
        frac_task["input_source"] = {
            "poscar_from": f"{result['source_dir']}/CONTCAR",
            "potcar_from": f"{result['source_dir']}/POTCAR",
            "kpoints_from": f"{result['source_dir']}/KPOINTS",
        }
        frac_task["notes"] = f"频率矫正输入由 {task.get('model_name')} 生成（{result['latest_dir'] or '主目录'}）"
        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == frac_task["task_id"]:
                t.update(frac_task)
        save_db(db)
        _audit_log(
            project["name"], task_id, result["frac_dir"],
            "create-frac", f"OK src={result['source_dir']}",
        )
        return ok("频率矫正输入文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建频率矫正失败：{e}"))


@router.post("/tasks/{task_id}/build-ele-inputs")
def build_ele(task_id: str, payload: dict = Body(default={})):
    """为电子结构任务构建输入文件（从 opt 导入或外部结构）。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "ele":
            return JSONResponse(status_code=400, content=fail("仅电子结构任务可构建输入文件"))
        source_type = str(payload.get("source_type", "opt"))
        source_task_id = payload.get("source_task_id")
        ele_types = payload.get("ele_types") or payload.get("ele_type") or []
        if isinstance(ele_types, str):
            ele_types = [ele_types]
        ele_types = [str(t) for t in ele_types if t]
        params = payload.get("params") or {}
        result = build_ele_inputs(
            project["server"],
            project,
            task,
            source_type,
            source_task_id,
            ele_types,
            params,
        )
        task["input_source"] = {
            "poscar_from": (
                f"{result['source_dir']}/CONTCAR" if result.get("source_dir") else "external/POSCAR"
            ),
            "potcar_from": (
                f"{result['source_dir']}/POTCAR" if result.get("source_dir") else None
            ),
            "kpoints_from": (
                f"{result['source_dir']}/KPOINTS" if result.get("source_dir") else None
            ),
        }
        task["subtype"] = ",".join(ele_types) if ele_types else None
        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == task_id:
                t.update(task)
        save_db(db)
        _audit_log(
            project["name"], task_id, result["ele_dir"],
            f"build-ele-inputs type={ele_type}", "OK",
        )
        return ok("电子结构输入文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"构建电子结构输入失败：{e}"))


@router.post("/tasks/{task_id}/create-neb-files")
def create_neb(task_id: str, payload: dict = Body(default={})):
    """根据初末态 opt 任务创建 NEB 计算文件（nebmake.pl 插值）。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "neb":
            return JSONResponse(status_code=400, content=fail("仅 NEB 任务可创建计算文件"))
        initial_id = payload.get("initial_opt_task_id")
        final_id = payload.get("final_opt_task_id")
        num_images = int(payload.get("num_images", 3))
        if not initial_id or not final_id:
            return JSONResponse(status_code=400, content=fail("缺少初态/末态优化任务 ID"))
        initial_task = next(
            (t for t in project["tasks"] if t.get("task_id") == initial_id), None
        )
        final_task = next(
            (t for t in project["tasks"] if t.get("task_id") == final_id), None
        )
        if initial_task is None or final_task is None:
            return JSONResponse(status_code=404, content=fail("初态/末态优化任务不存在"))
        if initial_task.get("task_type") != "opt" or final_task.get("task_type") != "opt":
            return JSONResponse(status_code=400, content=fail("初态/末态必须是结构优化任务"))
        # 通过项目数据库校验初末态是否收敛
        if initial_task.get("status") != "completed":
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"初态优化未收敛（当前状态：{initial_task.get('status')}），请先完成结构优化"
                ),
            )
        if final_task.get("status") != "completed":
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"末态优化未收敛（当前状态：{final_task.get('status')}），请先完成结构优化"
                ),
            )
        result = create_neb_files(
            project["server"],
            project,
            task,
            initial_task,
            final_task,
            num_images,
            params=payload.get("params") or {},
        )
        task["input_source"] = {
            "poscar_from": f"{result['source_is']}/CONTCAR",
            "potcar_from": f"{result['source_is']}/POTCAR",
            "kpoints_from": f"{result['source_is']}/KPOINTS",
        }
        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == task_id:
                t.update(task)
        save_db(db)
        _audit_log(
            project["name"], task_id, result["neb_dir"],
            f"create-neb images={num_images}", "OK",
        )
        return ok("NEB 计算文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建 NEB 计算文件失败：{e}"))


@router.patch("/tasks/{task_id}")
def rename_task(task_id: str, payload: RenameTaskPayload):
    """重命名独立任务：同步更新本地/远端目录与数据库。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("group"):
            return JSONResponse(
                status_code=400,
                content=fail("组内任务请通过结构管理调整，不支持直接重命名"),
            )
        new_name = payload.model_name.strip()
        if not NAME_PATTERN.fullmatch(new_name):
            return JSONResponse(
                status_code=400,
                content=fail("名称仅支持字母、数字、下划线、@，且不能以数字开头"),
            )
        if any(t.get("model_name") == new_name for t in project["tasks"]):
            return JSONResponse(status_code=400, content=fail("项目中已存在同名任务"))
        old_name = task.get("model_name", "")
        old_local = resolve_local_path(task.get("dir_path", ""))
        new_local = old_local.parent / new_name
        if old_local.is_dir() and old_local != new_local and not new_local.exists():
            shutil.move(str(old_local), str(new_local))
        old_remote = resolve_remote_path(project.get("server"), task.get("remote_dir", ""))
        new_remote = ""
        if old_remote and old_name:
            new_remote = old_remote.rsplit("/", 1)[0] + f"/{new_name}"
            from ssh import run_remote

            r = run_remote(
                project.get("server"),
                f'bash -c \'[ -d "{old_remote}" ] && [ ! -e "{new_remote}" ] '
                f'&& mv "{old_remote}" "{new_remote}" || true\'',
                timeout=60,
            )
            if r["exit_code"] != 0:
                return JSONResponse(
                    status_code=500,
                    content=fail(f"远程目录重命名失败：{(r['stderr'] or r['stdout']).strip()}"),
                )
        task["model_name"] = new_name
        from paths import to_local_rel

        task["dir_path"] = to_local_rel(str(new_local))
        if new_remote:
            task["remote_dir"] = to_remote_rel(project.get("server"), new_remote)
        from storage import save_db

        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == task_id:
                t.update(task)
        save_db(db)
        return ok(
            "任务已重命名",
            {
                "task_id": task_id,
                "model_name": new_name,
                "dir_path": task["dir_path"],
                "remote_dir": task["remote_dir"],
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"重命名失败：{e}"))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    """删除最末端子项：本地目录移入回收站，记录从数据库移除（远端目录不自动删除）。"""
    try:
        project, task = _resolve_task(task_id)
        children = [
            t for t in project["tasks"]
            if t.get("parent_task_id") == task_id
        ]
        if children:
            return JSONResponse(
                status_code=400,
                content=fail("该任务存在续算子任务，请先删除子任务"),
            )
        trash_path = None
        old_local = resolve_local_path(task.get("dir_path", ""))
        if old_local.is_dir():
            trash_dir = DATA_DIR / "trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            trash_path = trash_dir / f"{task_id}_{int(datetime.now().timestamp())}"
            shutil.move(str(old_local), str(trash_path))
        from storage import save_db

        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        proj["tasks"] = [t for t in proj["tasks"] if t.get("task_id") != task_id]
        save_db(db)
        return ok(
            "任务已删除",
            {
                "task_id": task_id,
                "model_name": task.get("model_name"),
                "local_trash": str(trash_path) if trash_path else None,
                "remote_dir": task.get("remote_dir"),
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"删除任务失败：{e}"))


@router.post("/tasks/{task_id}/submit")
def submit_task(task_id: str):
    """提交作业：远程目录内执行 bsub < vasp.lsf，登记 job_id 并将状态更新为 queued。"""
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))

    status = task.get("status")
    job_id = task.get("job_id")
    if job_id and status in ("queued", "running"):
        return JSONResponse(status_code=409, content=fail("作业已提交/运行中，请勿重复操作"))

    server = project.get("server")
    remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
    if not remote_dir:
        return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))

    # 定位最新续算目录（conN，即使尚无输出），在该目录内提交；
    # 无续算目录则用任务主目录
    servers = load_servers()
    batch_path = servers.get(server, {}).get("batch_check_path")
    latest = ""
    if batch_path:
        try:
            latest = _remote_latest_con(server, remote_dir, batch_path)
        except Exception:  # noqa: BLE001 - 定位失败回退主目录
            latest = ""
    work_dir = f"{remote_dir}/{latest}" if latest else remote_dir

    submit_script = "vasp.lsf"
    command = (
        f"bash -c 'cd \"{work_dir}\" && "
        f"[ -f \"{submit_script}\" ] && bsub < \"{submit_script}\"'"
    )
    try:
        # 先确认远程目录与提交脚本存在
        check = ssh.run_remote(
            server,
            f'bash -c \'[ -d "{work_dir}" ] && [ -f "{work_dir}/vasp.lsf" ] && echo YES || echo NO\'',
            timeout=30,
        )
        if "YES" not in check["stdout"]:
            detail = ssh.run_remote(
                server,
                f'bash -c \'[ -d "{work_dir}" ] && echo DIR_OK || echo NO_DIR\'',
                timeout=30,
            )["stdout"].strip()
            if detail == "NO_DIR":
                return JSONResponse(
                    status_code=404,
                    content=fail(f"远程目录不存在：{work_dir}"),
                )
            return JSONResponse(
                status_code=404,
                content=fail("提交脚本 vasp.lsf 不存在，请先创建提交脚本"),
            )

        # 加载 LSF profile 后提交（复用节点查询的 profile 路径）
        profile = str(
            servers.get(server, {}).get(
                "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
            )
        )
        result = ssh.run_remote(
            server,
            f'bash -c "source {profile} >/dev/null 2>&1; cd \"{work_dir}\" && bsub < vasp.lsf"',
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001 - SSH 连接类错误统一返回 502
        return JSONResponse(
            status_code=502,
            content=fail(f"无法连接远程服务器，请检查 SSH 配置：{e}"),
        )

    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    # 以 bsub 明确输出 "Job <id> is submitted" 作为成功标志；
    # stderr 中的 bashrc/conda 等环境噪音（含 Error 字样）不判定为提交失败
    submit_match = re.search(r"Job <(\d+)> is submitted", raw)
    if not submit_match and result.get("exit_code") != 0:
        _audit_log(project["name"], task_id, remote_dir, command, f"FAILED: {raw}")
        return JSONResponse(
            status_code=500,
            content=fail(f"bsub 提交失败：{raw or '未知错误'}"),
        )

    if not submit_match:
        match = re.search(r"Job <(\d+)>", raw)
    else:
        match = submit_match
    if not match:
        _audit_log(project["name"], task_id, remote_dir, command, f"UNPARSED: {raw}")
        return JSONResponse(
            status_code=500,
            content=fail(f"未能从 bsub 输出解析作业 ID：{raw}"),
        )
    new_job_id = match.group(1)

    # 登记 job_id 并将状态更新为 queued（走串行事务，避免与巡检回填互相覆盖）
    try:
        with db_transaction() as db:
            update_task_status(
                db,
                project["name"],
                task_id,
                "queued",
                {"job_id": new_job_id},
            )
    except Exception as e:  # noqa: BLE001 - 状态落库失败不影响已提交事实
        _audit_log(project["name"], task_id, remote_dir, command, f"DB_WARN: {e}")

    _audit_log(project["name"], task_id, remote_dir, command, f"OK job={new_job_id}")
    return ok(
        f"作业 {new_job_id} 已提交到队列",
        {
            "job_id": new_job_id,
            "new_status": "queued",
            "raw_output": raw,
        },
    )


@router.post("/tasks/{task_id}/archive")
def archive_task(task_id: str):
    """关闭（归档）任务：只改状态，本地/远端文件都不动。

    前端在任务未正常结束（状态不是 completed）时会弹窗提醒，后端不做硬性拦截。
    """
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    previous = str(task.get("status") or "")
    if previous == "archived":
        return JSONResponse(status_code=409, content=fail("任务已经处于关闭（归档）状态"))
    try:
        with db_transaction() as db:
            update_task_status(
                db,
                project["name"],
                task_id,
                "archived",
                {"archived_at": now_iso(), "archived_from": previous},
            )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"关闭任务失败：{e}"))
    return ok(
        "任务已关闭（归档）",
        {
            "task_id": task_id,
            "project_name": project["name"],
            "new_status": "archived",
            "previous_status": previous,
            "was_completed": previous == "completed",
        },
    )


@router.post("/tasks/{task_id}/unarchive")
def unarchive_task(task_id: str):
    """重新打开已归档任务：恢复到归档前的状态（默认 pending）。"""
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    if str(task.get("status") or "") != "archived":
        return JSONResponse(status_code=409, content=fail("任务未处于关闭（归档）状态"))
    restore = str(task.get("archived_from") or "")
    if restore not in STATUS_ENUM or restore == "archived":
        restore = "pending"
    try:
        with db_transaction() as db:
            update_task_status(
                db,
                project["name"],
                task_id,
                restore,
                {"reopened_at": now_iso()},
            )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"重新打开任务失败：{e}"))
    return ok(
        "任务已重新打开",
        {"task_id": task_id, "project_name": project["name"], "new_status": restore},
    )


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str):
    """停止作业：远程 bkill 终止运行中的作业，任务状态回退为待提交。"""
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))

    job_id = task.get("job_id")
    if not job_id or task.get("status") not in ("queued", "running"):
        return JSONResponse(
            status_code=409,
            content=fail("作业未在排队/运行中，无法停止"),
        )

    server = project.get("server")
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    try:
        result = ssh.run_remote(
            server,
            f'bash -c "source {profile} >/dev/null 2>&1; bkill {job_id}"',
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001 - SSH 连接类错误
        return JSONResponse(
            status_code=502,
            content=fail(f"无法连接远程服务器，请检查 SSH 配置：{e}"),
        )
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    # LSF：对已结束/不存在的作业执行 bkill 会输出 "Job <id>: Job has already
    # finished" 且退出码非 0 —— 作业实际上已停止，按停止成功处理（归档为待提交）
    already_finished = bool(re.search(r"already finished", raw, re.IGNORECASE))
    if result.get("exit_code") != 0 and not already_finished:
        _audit_log(project["name"], task_id, str(job_id), "bkill", f"FAILED: {raw}")
        return JSONResponse(status_code=500, content=fail(f"停止作业失败：{raw or '未知错误'}"))

    # 作业已终止：状态回退为待提交（可重新提交或续算）
    try:
        with db_transaction() as db:
            update_task_status(db, project["name"], task_id, "pending")
    except Exception as e:  # noqa: BLE001 - 状态落库失败不影响停止事实
        _audit_log(project["name"], task_id, str(job_id), "bkill", f"DB_WARN: {e}")
    _audit_log(
        project["name"],
        task_id,
        str(job_id),
        "bkill",
        "OK (already finished)" if already_finished else "OK",
    )
    return ok(
        "作业已停止（作业此前已结束）" if already_finished else "作业已停止",
        {
            "job_id": job_id,
            "new_status": "pending",
            "already_finished": already_finished,
        },
    )


@router.post("/tasks/{task_id}/upload-incar")
def upload_incar(task_id: str, payload: dict = Body(default={})):
    """本地生成 INCAR 并上传到远端最新目录；旧文件备份为 old_INCAR。"""
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        # 最新目录：最大编号 conN（存在即算），无则主目录；不创建新目录
        servers = load_servers()
        batch_path = servers.get(server, {}).get("batch_check_path")
        latest = ""
        if batch_path:
            try:
                latest = _remote_latest_con(server, remote_dir, batch_path)
            except Exception:  # noqa: BLE001 - 定位失败回退主目录
                latest = ""
        work_dir = f"{remote_dir}/{latest}" if latest else remote_dir

        content = payload.get("content")
        params = payload.get("params")
        old = _download_remote_text(server, f"{work_dir}/INCAR") or ""
        if content:
            new_text = str(content)
            warnings = []
        elif params:
            new_text, warnings = modify_incar(old, params)
        else:
            return JSONResponse(
                status_code=400,
                content=fail("请提供 content（完整文本）或 params（参数字典）"),
            )

        # 备份旧文件（存在则 mv 为 old_INCAR，old_INCAR 已存在则覆盖）
        ssh.run_remote(
            server,
            f'bash -c \'[ -f "{work_dir}/INCAR" ] && mv -f "{work_dir}/INCAR" "{work_dir}/old_INCAR" || true\'',
            timeout=30,
        )
        _write_remote_file(server, f"{work_dir}/INCAR", new_text)
        _audit_log(
            project["name"],
            task_id,
            work_dir,
            "upload-incar",
            f"OK backup={'old_INCAR' if old else 'none'}",
        )
        return ok(
            "INCAR 已上传到远端",
            {
                "dir": work_dir,
                "backup_file": "old_INCAR" if old else None,
                "warnings": warnings,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"上传 INCAR 失败：{e}"))


@router.post("/tasks/{task_id}/upload-kpoints")
def upload_kpoints(task_id: str, payload: dict = Body(default={})):
    """上传 KPOINTS 到远端最新目录；旧文件备份为 old_KPOINTS（逻辑同 INCAR）。"""
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        servers = load_servers()
        batch_path = servers.get(server, {}).get("batch_check_path")
        latest = ""
        if batch_path:
            try:
                latest = _remote_latest_con(server, remote_dir, batch_path)
            except Exception:  # noqa: BLE001 - 定位失败回退主目录
                latest = ""
        work_dir = f"{remote_dir}/{latest}" if latest else remote_dir

        content = payload.get("content")
        if not content:
            return JSONResponse(status_code=400, content=fail("请提供 KPOINTS 内容（content）"))
        old = _download_remote_text(server, f"{work_dir}/KPOINTS") or ""
        ssh.run_remote(
            server,
            f'bash -c \'[ -f "{work_dir}/KPOINTS" ] && mv -f "{work_dir}/KPOINTS" "{work_dir}/old_KPOINTS" || true\'',
            timeout=30,
        )
        _write_remote_file(server, f"{work_dir}/KPOINTS", str(content))
        _audit_log(
            project["name"],
            task_id,
            work_dir,
            "upload-kpoints",
            f"OK backup={'old_KPOINTS' if old else 'none'}",
        )
        return ok(
            "KPOINTS 已上传到远端",
            {"dir": work_dir, "backup_file": "old_KPOINTS" if old else None},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"上传 KPOINTS 失败：{e}"))


@router.post("/tasks/{task_id}/analysis/pdos")
def analyze_pdos(task_id: str, payload: dict = Body(default={})):
    """PDOS 分析：远端执行 vaspkit 111/113/115，生成文件下载回本地 files/analysis/。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "ele":
            return JSONResponse(status_code=400, content=fail("仅电子结构任务支持 PDOS 分析"))
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        mode = int(payload.get("mode", 111))
        if mode not in (111, 113, 115):
            return JSONResponse(status_code=400, content=fail("mode 仅支持 111 / 113 / 115"))
        groups = payload.get("groups") or []
        if mode == 115 and not groups:
            return JSONResponse(status_code=400, content=fail("自定义分析需提供至少一组元素与轨道"))

        lines = [str(mode)]
        if mode == 115:
            for g in groups:
                elem = str(g.get("elements", "")).strip()
                orb = str(g.get("orbitals", "")).strip()
                if elem:
                    lines.append(f"{elem} {orb}".strip())
            lines.append("")
        else:
            lines.append("")
        input_text = "\n".join(lines) + "\n"
        escaped = input_text.replace("\\", "\\\\").replace('"', '\\"')
        result = ssh.run_remote(
            server,
            f'bash -c \'cd "{remote_dir}" && printf "{escaped}" | vaspkit\'',
            timeout=180,
        )
        raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
        if result.get("exit_code") != 0:
            return JSONResponse(
                status_code=500,
                content=fail(f"vaspkit 执行失败：{raw or '未知错误'}"),
            )

        # 收集远端 *.dat 文件下载到本地 files/analysis/
        from task_paths import task_dir

        local_analysis = task_dir(project.get("name", ""), task) / "files" / "analysis"
        local_analysis.mkdir(parents=True, exist_ok=True)
        ls = ssh.run_remote(
            server,
            f'bash -c \'ls -1 "{remote_dir}"/*.dat 2>/dev/null\'',
            timeout=30,
        )
        downloaded = []
        for name in (ls.get("stdout") or "").splitlines():
            name = name.strip()
            if not name:
                continue
            local = local_analysis / Path(name).split("/")[-1]
            if ssh.download_file(server, f"{remote_dir}/{name}", str(local)):
                downloaded.append(str(local))
        _audit_log(
            project["name"],
            task_id,
            remote_dir,
            f"pdos mode={mode}",
            f"OK files={len(downloaded)}",
        )
        return ok(
            "PDOS 分析完成",
            {
                "mode": mode,
                "files": downloaded,
                "raw": raw[:800],
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"PDOS 分析失败：{e}"))


@router.post("/tasks/{task_id}/calculate-correction")
def calculate_correction(task_id: str, payload: dict = Body(default={"temperature": 298.15})):
    """自由能矫正项：远端 frac 目录执行 vaspkit 501，解析 Thermal correction to G(T)。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "frac":
            return JSONResponse(status_code=400, content=fail("仅频率矫正任务可计算矫正项"))
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        temperature = float(payload.get("temperature", 298.15))
        try:
            correction = compute_g_correction(server, remote_dir, temperature)
        except Exception as e:  # noqa: BLE001 - 计算失败返回明确错误
            return JSONResponse(status_code=500, content=fail(str(e)))
        with db_transaction() as db:
            proj = next(p for p in db["projects"] if p["name"] == project["name"])
            for t in proj["tasks"]:
                if t.get("task_id") == task_id:
                    t["correction"] = correction
                    t["correction_temp"] = temperature
                    t["correction_at"] = now_iso()
        _audit_log(
            project["name"],
            task_id,
            remote_dir,
            f"vaspkit501 T={temperature}",
            f"OK correction={correction}",
        )
        return ok(
            "矫正项计算完成",
            {"correction": correction, "temperature": temperature},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"计算矫正项失败：{e}"))
