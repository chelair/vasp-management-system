"""作业管理接口：本地任务目录的统一文件读写。

本地目录约定（与前端一致）：
    data/projects/<项目名>/<任务类型>/<子项名>/
        files/          VASP 输入/输出文件（INCAR、POSCAR、KPOINTS、POTCAR、CONTCAR…）
        images/         VESTA 结构渲染图
        reports/        生成报告
        continuation/   续算目录
"""

from datetime import datetime
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import PROJECTS_DIR, load_servers
from cluster_status import build_snapshot
from envelope import fail, ok
from storage import load_db

router = APIRouter(prefix="/jobs", tags=["jobs"])

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
                return (
                    PROJECTS_DIR
                    / str(project.get("name", ""))
                    / str(task.get("task_type", ""))
                    / str(task.get("model_name", ""))
                )
    raise LookupError(f"任务 {task_id} 不存在")


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
