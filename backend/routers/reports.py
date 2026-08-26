"""报告数据接口：按组自动聚合自由能路径（台阶图）与 NEB（能垒图）数据。

解析状态：opt / neb 映像能量已从 OSZICAR 提取（真实）；
frac 的频率矫正（ZPE / 自由能矫正）解析待接入，当前返回 null 占位，
数据结构已定，后续解析器可直接回填。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import PROJECTS_DIR
from aux_molecules import get_aux, list_aux_molecules
from envelope import fail, ok
from storage import load_db
from task_paths import task_files_dir
from task_paths import task_dir

router = APIRouter(prefix="/reports", tags=["reports"])

F_ENERGY_RE = re.compile(r"F=\s*([-+]?\d+\.\d+)")


def last_energy(task_path: Path) -> Optional[float]:
    """从 OSZICAR 末行提取 F= 能量；无则尝试 OUTCAR 的最后一个 TOTEN。"""
    files_dir = task_files_dir("", {"dir_path": str(task_path)})
    oszicar = files_dir / "OSZICAR"
    if oszicar.is_file():
        try:
            lines = [ln for ln in oszicar.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            for line in reversed(lines):
                m = F_ENERGY_RE.search(line)
                if m:
                    return round(float(m.group(1)), 8)
        except OSError:
            pass
    outcar = files_dir / "OUTCAR"
    if outcar.is_file():
        try:
            text = outcar.read_text(encoding="utf-8", errors="replace")
            values = [
                float(m)
                for m in re.findall(r"free\s+energy\s+TOTEN\s*=\s*([-+]?\d+\.\d+)", text)
            ]
            if values:
                return round(values[-1], 8)
        except OSError:
            pass
    return None


def _group_tasks(db: Dict[str, Any], group_id: str):
    rows = []
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            g = task.get("group")
            if isinstance(g, dict) and g.get("group_id") == group_id:
                rows.append((project["name"], task))
    return rows


@router.get("/groups")
def list_groups():
    """列出所有计算流程组（含角色任务数量）。"""
    try:
        db = load_db()
        groups: Dict[str, Dict[str, Any]] = {}
        for project in db.get("projects", []):
            for task in project.get("tasks", []):
                g = task.get("group")
                if not isinstance(g, dict) or not g.get("group_id"):
                    continue
                gid = g["group_id"]
                entry = groups.setdefault(
                    gid,
                    {
                        "group_id": gid,
                        "project": project["name"],
                        "group_type": g.get("group_type"),
                        "root_dir": str(
                            PROJECTS_DIR
                            / project["name"]
                            / (
                                "free_energy"
                                if g.get("group_type") == "free_energy"
                                else "neb"
                            )
                            / str(g.get("name") or "")
                        ),
                        "roles": {},
                        "task_count": 0,
                    },
                )
                role = g.get("group_role", "unknown")
                entry["roles"][role] = entry["roles"].get(role, 0) + 1
                entry["task_count"] += 1
        return ok("查询成功", {"groups": list(groups.values())})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"查询组失败：{e}"))


@router.get("/groups/{group_id}/data")
def group_data(group_id: str):
    """聚合单个组的结构化数据：自由能台阶图 / NEB 能垒图。"""
    try:
        db = load_db()
        rows = _group_tasks(db, group_id)
        if not rows:
            return JSONResponse(status_code=404, content=fail("组不存在"))
        group_type = rows[0][1].get("group", {}).get("group_type")
        project_name = rows[0][0]

        if group_type == "free_energy":
            by_label: Dict[str, Dict[str, Any]] = {}
            aux_refs: List[str] = []
            for pname, task in rows:
                label = task.get("group", {}).get("structure_label", "")
                refs = task.get("group", {}).get("aux_molecules") or []
                if isinstance(refs, list):
                    aux_refs.extend(str(r) for r in refs)
                entry = by_label.setdefault(label, {"label": label, "role": task["group"].get("group_role")})
                if task["group"].get("group_role") != "aux_molecule":
                    entry[task["task_type"]] = {
                        "task_id": task["task_id"],
                        "status": task.get("status"),
                        "dir": task.get("dir_path"),
                        "energy": (
                            last_energy(task_dir(pname, task))
                            if task.get("dir_path")
                            else None
                        ),
                    }
            structures = [
                v for v in by_label.values() if v.get("role") == "main_structure"
            ]
            aux: List[Dict[str, Any]] = [
                v for v in by_label.values() if v.get("role") == "aux_molecule"
            ]
            # 全局辅助分子引用（统一存储，跨项目复用）
            seen_aux = {a.get("label") for a in aux}
            for label in dict.fromkeys(aux_refs):
                if label in seen_aux:
                    continue
                global_m = get_aux(label)
                if global_m is None:
                    continue
                seen_aux.add(label)
                aux.append(
                    {
                        "label": label,
                        "role": "aux_molecule",
                        "opt": {
                            "dir": global_m.get("opt_dir"),
                            "energy": last_energy(Path(global_m.get("opt_dir", "")))
                            if global_m.get("opt_dir")
                            else None,
                        },
                        "frac": {
                            "dir": global_m.get("frac_dir"),
                            "zpe": global_m.get("zpe"),
                            "correction": global_m.get("correction"),
                        },
                        "free_energy": None,
                        "parsing_note": (
                            "频率矫正（ZPE/自由能）解析待接入"
                            if global_m.get("frac_dir")
                            else "缺少 frac 目录"
                        ),
                    }
                )
            structures.sort(key=lambda v: v["label"])
            aux.sort(key=lambda v: v["label"])
            for item in structures + aux:
                frac = item.get("frac") or {}
                item["free_energy"] = None
                item["parsing_note"] = (
                    "频率矫正（ZPE/自由能）解析待接入"
                    if item.get("frac")
                    else "缺少 frac 任务"
                )
            return ok(
                "查询成功",
                {
                    "group_id": group_id,
                    "project": project_name,
                    "group_type": "free_energy",
                    "free_energy": {
                        "structures": structures,
                        "aux_molecules": aux,
                        "parsing_note": "opt 能量已提取（OSZICAR）；frac 矫正待接入",
                    },
                    "neb": None,
                },
            )

        # neb 组
        data: Dict[str, Any] = {"images": []}
        for pname, task in rows:
            role = task.get("group", {}).get("group_role")
            if role == "initial_opt":
                data["initial"] = {
                    "task_id": task["task_id"],
                    "dir": task.get("dir_path"),
                    "energy": (
                        last_energy(task_dir(pname, task)) if task.get("dir_path") else None
                    ),
                }
            elif role == "final_opt":
                data["final"] = {
                    "task_id": task["task_id"],
                    "dir": task.get("dir_path"),
                    "energy": (
                        last_energy(task_dir(pname, task)) if task.get("dir_path") else None
                    ),
                }
            elif role == "neb_images":
                neb_dir = task_dir(pname, task)
                if neb_dir.is_dir():
                    images = sorted(
                        (p for p in neb_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d+", p.name)),
                        key=lambda p: int(p.name),
                    )
                    data["images"] = [
                        {"index": int(p.name), "dir": str(p), "energy": last_energy(p)}
                        for p in images
                    ]
                    data["neb_task_id"] = task["task_id"]
                    data["neb_dir"] = str(neb_dir)
        energies = [img["energy"] for img in data["images"] if img.get("energy") is not None]
        initial = (data.get("initial") or {}).get("energy")
        if energies and initial is not None:
            data["barrier"] = round(max(energies) - initial, 8)
        else:
            data["barrier"] = None
        data["parsing_note"] = "映像能量已提取（OSZICAR）；映像 POSCAR 插值待接入"
        return ok(
            "查询成功",
            {
                "group_id": group_id,
                "project": project_name,
                "group_type": "neb",
                "free_energy": None,
                "neb": data,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取组数据失败：{e}"))
