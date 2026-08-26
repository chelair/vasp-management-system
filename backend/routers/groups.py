"""计算流程组管理：自由能组 / NEB 组 / 独立任务创建。

v0.4.1 目录规范（目录一律 ASCII，前端树显示中文）：
    结构优化：<项目>/opt/<独立任务>
    电子结构：<项目>/ele/<独立任务>
    自由能组：<项目>/free_energy/<组名>/<struct_NN>/<opt|frac>
    NEB 组：  <项目>/neb/<组名>/opt/<IS|FS>、<组名>/neb/<00..n+1>
组元数据 group{group_id, group_type, group_role, structure_label} 仍为识别依据。
"""

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import PROJECTS_DIR, load_settings, load_task_registry
from aux_molecules import add_aux_molecule, get_aux
from dates import now_iso
from envelope import fail, ok
from paths import to_local_rel, to_remote_rel
from storage import load_db, save_db
from task_paths import CATEGORY_DIRS

router = APIRouter(prefix="/groups", tags=["groups"])

TASK_SUBDIRS = ("files", "images", "reports", "continuation")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_@]*$")
GROUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_@]*$")


class FreeEnergyGroupPayload(BaseModel):
    project: str = Field(min_length=1)
    group_type: str = "free_energy"
    name: Optional[str] = None
    structures: int = Field(default=1, ge=1, le=50)
    aux_molecules: List[str] = Field(default_factory=list)


class NebGroupPayload(BaseModel):
    project: str = Field(min_length=1)
    group_type: str = "neb"
    name: Optional[str] = None
    images: int = Field(default=6, ge=1, le=50)


class IndependentTaskPayload(BaseModel):
    project: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    subtype: Optional[str] = None


class AddStructuresPayload(BaseModel):
    count: int = Field(default=1, ge=1, le=50)


def _task_id(project: Dict[str, Any]) -> str:
    """生成不重复 task_id。"""
    ts = int(time.time() * 1000)
    used = {t.get("task_id") for t in project.get("tasks", [])}
    seq = 1
    while f"task_{ts}_{seq}" in used:
        seq += 1
    return f"task_{ts}_{seq}"


def _base_record(
    project: Dict[str, Any],
    task_type: str,
    model_name: str,
    dir_path: Path,
    remote_dir: str,
    group: Optional[Dict[str, Any]],
    parent_task_id: Optional[str] = None,
    input_source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = now_iso()
    return {
        "task_id": _task_id(project),
        "task_type": task_type,
        "subtype": None,
        "model_name": model_name,
        "status": "pending",
        "last_energy": None,
        "last_check_time": None,
        "job_id": None,
        "notes": "",
        "continuation_ready": False,
        "continuation_dir": None,
        "dir_path": to_local_rel(str(dir_path)),
        "remote_dir": to_remote_rel(project.get("server"), remote_dir),
        "group": group,
        "parent_task_id": parent_task_id,
        "input_source": input_source,
        "created_at": now,
        "updated_at": now,
    }


def _make_task_dirs(task_path: Path) -> None:
    for sub in TASK_SUBDIRS:
        (task_path / sub).mkdir(parents=True, exist_ok=True)


def _incar_text(params: Dict[str, Any]) -> str:
    if not params:
        return ""
    width = max(len(str(k)) for k in params)
    return "\n".join(f"{str(k).ljust(width + 2)}= {v}" for k, v in params.items())


def _write_default_inputs(task_path: Path, task_type: str, images: Optional[int] = None) -> None:
    """写入默认 INCAR（按注册表模板）与 KPOINTS；POTCAR 由后续伪势模块生成。"""
    registry = load_task_registry()
    cfg = registry.get(task_type, {})
    params = dict(cfg.get("default_incar", {}))
    if task_type == "neb" and images is not None:
        params["IMAGES"] = images
    incar = _incar_text(params)
    if incar:
        (task_path / "INCAR").write_text(incar + "\n", encoding="utf-8")
    kpoints = "Automatic mesh\n0\nGamma\n4 4 4\n0 0 0\n"
    (task_path / "KPOINTS").write_text(kpoints, encoding="utf-8")


def _register_tasks(db: Dict[str, Any], project_name: str, tasks: List[Dict[str, Any]]) -> None:
    project = next(p for p in db["projects"] if p["name"] == project_name)
    project["tasks"].extend(tasks)


def _try_remote_mkdir(server: str, remote_dir: str) -> Optional[str]:
    try:
        import ssh

        ssh.mkdir_remote(server, remote_dir)
        return None
    except Exception as e:  # noqa: BLE001 - 远程失败不阻塞本地创建
        return f"远程目录创建失败：{e}"


@router.post("")
def create_group(payload: dict):
    """创建自由能组或 NEB 组，自动生成组内任务、目录与默认输入文件。"""
    try:
        db = load_db()
        project = next(
            (p for p in db["projects"] if p["name"] == payload.get("project")),
            None,
        )
        if project is None:
            return JSONResponse(status_code=400, content=fail("项目不存在"))
        group_type = payload.get("group_type")
        if group_type not in ("free_energy", "neb"):
            return JSONResponse(status_code=400, content=fail("group_type 仅支持 free_energy / neb"))

        existing = {
            t.get("group", {}).get("group_id")
            for t in project["tasks"]
            if isinstance(t.get("group"), dict)
        }
        group_id = f"{group_type}_{int(time.time() * 1000)}"
        while group_id in existing:
            group_id = f"{group_type}_{int(time.time() * 1000) + 1}"

        group_ids = {
            t["group"]["group_id"]
            for t in project["tasks"]
            if isinstance(t.get("group"), dict)
            and t["group"].get("group_type") == group_type
        }
        seq = len(group_ids) + 1
        default_name = f"PATH{seq}"
        root_name = payload.get("name") or default_name
        if not GROUP_NAME_PATTERN.fullmatch(root_name):
            return JSONResponse(
                status_code=400,
                content=fail("组名仅支持字母、数字、下划线、@（目录名不使用中文）"),
            )

        category = "free_energy" if group_type == "free_energy" else "neb"
        project_root = PROJECTS_DIR / project["name"] / category / root_name
        remote_base = project.get("remote_base", "")
        remote_category_base = f"{remote_base}/{category}"
        tasks: List[Dict[str, Any]] = []
        warnings: List[str] = []

        if group_type == "free_energy":
            n_structures = int(payload.get("structures", 1))
            aux = [str(a) for a in payload.get("aux_molecules", []) or []]
            aux_labels = []
            for a in aux:
                if not NAME_PATTERN.fullmatch(a):
                    return JSONResponse(
                        status_code=400,
                        content=fail(f"辅助分子标签不合法：{a}"),
                    )
                if get_aux(a) is None:
                    add_aux_molecule(a)
                    warnings.append(f"已自动创建全局辅助分子：{a}")
                aux_labels.append(a)
            for i in range(1, n_structures + 1):
                label = str(i)
                # opt 任务目录 = 结构目录本身（结构优化直接位于 1/ 下）
                opt_path = project_root / label
                _make_task_dirs(opt_path)
                _write_default_inputs(opt_path, "opt")
                remote_opt = f"{remote_category_base}/{root_name}/{label}"
                opt_task = _base_record(
                    project,
                    "opt",
                    f"{label}_opt",
                    opt_path,
                    remote_opt,
                    {
                        "name": root_name,
                        "group_id": group_id,
                        "group_type": "free_energy",
                        "group_role": "main_structure",
                        "structure_label": label,
                        "aux_molecules": aux_labels or None,
                    },
                )
                tasks.append(opt_task)
                # frac 任务目录 = 1/frac（与续算目录 conN 同级）
                frac_path = project_root / label / "frac"
                _make_task_dirs(frac_path)
                _write_default_inputs(frac_path, "frac")
                frac_remote = f"{remote_category_base}/{root_name}/{label}/frac"
                frac_task = _base_record(
                    project,
                    "frac",
                    f"{label}_frac",
                    frac_path,
                    frac_remote,
                    {
                        "name": root_name,
                        "group_id": group_id,
                        "group_type": "free_energy",
                        "group_role": "main_structure",
                        "structure_label": label,
                        "aux_molecules": aux_labels or None,
                    },
                )
                tasks.append(frac_task)
                # frac 的父任务 = 同结构的 opt；输入来源 = opt/CONTCAR
                frac_task["parent_task_id"] = opt_task["task_id"]
                frac_task["input_source"] = {
                    "poscar_from": f"{opt_task['dir_path']}/CONTCAR",
                    "potcar_from": None,
                    "kpoints_from": None,
                }
                warn = _try_remote_mkdir(
                    project["server"], f"{remote_category_base}/{root_name}/{label}"
                )
                if warn:
                    warnings.append(warn)
        else:
            images = int(payload.get("images", 6))
            plan = (
                ("IS", "opt", "initial_opt"),
                ("FS", "opt", "final_opt"),
                ("neb", "neb", "neb_images"),
            )
            for sub_dir, task_type, role in plan:
                task_path = (
                    project_root / "opt" / sub_dir
                    if task_type == "opt"
                    else project_root / "neb"
                )
                _make_task_dirs(task_path)
                _write_default_inputs(task_path, task_type, images if task_type == "neb" else None)
                remote_dir = (
                    f"{remote_category_base}/{root_name}/opt/{sub_dir}"
                    if task_type == "opt"
                    else f"{remote_category_base}/{root_name}/neb"
                )
                # 每个任务目录都要在远端创建（与 free_energy 分支一致）
                warn = _try_remote_mkdir(project["server"], remote_dir)
                if warn:
                    warnings.append(warn)
                task = _base_record(
                    project,
                    task_type,
                    f"{root_name}_{sub_dir}",
                    task_path,
                    remote_dir,
                    {
                        "name": root_name,
                        "group_id": group_id,
                        "group_type": "neb",
                        "group_role": role,
                        "structure_label": sub_dir,
                    },
                )
                tasks.append(task)
            warn = _try_remote_mkdir(
                project["server"], f"{remote_category_base}/{root_name}"
            )
            if warn:
                warnings.append(warn)

        _register_tasks(db, project["name"], tasks)
        save_db(db)
        return ok(
            "组创建成功",
            {
                "group_id": group_id,
                "group_root": str(project_root),
                "task_count": len(tasks),
                "tasks": [t["task_id"] for t in tasks],
                "warnings": warnings,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建组失败：{e}"))


@router.post("/{group_id}/structures")
def add_group_structures(group_id: str, payload: AddStructuresPayload):
    """为自由能组添加结构（自动生成 struct_N+1 的 opt+frac）。"""
    try:
        db = load_db()
        group_tasks = [
            t
            for p in db["projects"]
            for t in p["tasks"]
            if (t.get("group") or {}).get("group_id") == group_id
        ]
        if not group_tasks:
            return JSONResponse(status_code=404, content=fail("组不存在"))
        project = next(
            p for p in db["projects"]
            if any(t in p["tasks"] for t in group_tasks)
        )
        gtype = group_tasks[0]["group"].get("group_type")
        if gtype != "free_energy":
            return JSONResponse(status_code=400, content=fail("仅自由能组支持添加结构"))
        root_name = group_tasks[0]["group"].get("name", "")
        existing = {
            int(t["group"]["structure_label"])
            for t in group_tasks
            if t["group"].get("structure_label", "").isdigit()
        }
        next_num = max(existing, default=0) + 1
        category = "free_energy"
        project_root = PROJECTS_DIR / project["name"] / category / root_name
        remote_base = project.get("remote_base", "")
        remote_category_base = f"{remote_base}/{category}"
        new_tasks: List[Dict[str, Any]] = []
        for i in range(next_num, next_num + payload.count):
            label = str(i)
            opt_path = project_root / label
            _make_task_dirs(opt_path)
            _write_default_inputs(opt_path, "opt")
            remote_opt = f"{remote_category_base}/{root_name}/{label}"
            opt_task = _base_record(
                project,
                "opt",
                f"{label}_opt",
                opt_path,
                remote_opt,
                {
                    "name": root_name,
                    "group_id": group_id,
                    "group_type": "free_energy",
                    "group_role": "main_structure",
                    "structure_label": label,
                },
            )
            new_tasks.append(opt_task)
            frac_path = project_root / label / "frac"
            _make_task_dirs(frac_path)
            _write_default_inputs(frac_path, "frac")
            frac_task = _base_record(
                project,
                "frac",
                f"{label}_frac",
                frac_path,
                f"{remote_category_base}/{root_name}/{label}/frac",
                {
                    "name": root_name,
                    "group_id": group_id,
                    "group_type": "free_energy",
                    "group_role": "main_structure",
                    "structure_label": label,
                },
                parent_task_id=opt_task["task_id"],
                input_source={"poscar_from": f"{opt_path}/CONTCAR"},
            )
            new_tasks.append(frac_task)
        project["tasks"].extend(new_tasks)
        save_db(db)
        return ok(
            "结构已添加",
            {
                "group_id": group_id,
                "labels": [str(i) for i in range(next_num, next_num + payload.count)],
                "task_ids": [t["task_id"] for t in new_tasks],
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"添加结构失败：{e}"))


@router.post("/tasks")
def create_independent_task(payload: IndependentTaskPayload):
    """创建独立任务（group=None），目录位于 <项目>/<模型名>。"""
    try:
        registry = load_task_registry()
        if payload.task_type not in registry:
            return JSONResponse(status_code=400, content=fail(f"未知任务类型：{payload.task_type}"))
        if payload.subtype and payload.task_type != "ele":
            return JSONResponse(status_code=400, content=fail("subtype 仅 ele 类型可填"))
        if payload.subtype and payload.subtype not in registry["ele"].get("subtypes", []):
            return JSONResponse(status_code=400, content=fail(f"未知 ele subtype：{payload.subtype}"))
        if not NAME_PATTERN.fullmatch(payload.model_name):
            return JSONResponse(status_code=400, content=fail("模型名仅支持字母、数字、下划线、@"))

        db = load_db()
        project = next((p for p in db["projects"] if p["name"] == payload.project), None)
        if project is None:
            return JSONResponse(status_code=400, content=fail("项目不存在"))
        if any(t.get("model_name") == payload.model_name for t in project["tasks"]):
            return JSONResponse(status_code=400, content=fail("项目中已存在同名任务"))

        category = CATEGORY_DIRS.get(payload.task_type, "结构优化")
        task_path = PROJECTS_DIR / project["name"] / category / payload.model_name
        _make_task_dirs(task_path)
        _write_default_inputs(task_path, payload.task_type)
        remote_dir = (
            f"{project.get('remote_base', '')}/{category}/{payload.model_name}"
        )
        task = _base_record(
            project,
            payload.task_type,
            payload.model_name,
            task_path,
            remote_dir,
            None,
        )
        task["subtype"] = payload.subtype
        _register_tasks(db, project["name"], [task])
        save_db(db)
        return ok("独立任务已创建", {"task_id": task["task_id"], "dir_path": task["dir_path"]})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建独立任务失败：{e}"))
