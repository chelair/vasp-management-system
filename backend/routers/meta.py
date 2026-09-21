"""元信息接口：健康检查 / 服务器列表 / 任务类型 / 依赖检查 / 结构文件转换。"""

import time

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

import cif_reader
from config import load_servers, load_task_registry
from dates import now_iso
from dependencies import INSTALL_HINT, check_dependencies
from envelope import fail, ok

router = APIRouter(tags=["meta"])

# 进程启动时刻：Windows 上 time.monotonic() 是系统开机时长而非进程运行时长，
# 早期实现直接返回它，排查问题时会误判后端是否为新进程。
_STARTED_AT = time.time()
_STARTED_AT_ISO = now_iso()


@router.get("/health")
def health():
    return ok(
        "ok",
        {
            "uptime": round(time.time() - _STARTED_AT, 1),
            "startedAt": _STARTED_AT_ISO,
        },
    )


@router.get("/servers")
def servers():
    try:
        items = [
            {
                "name": name,
                "host": cfg.get("host"),
                "port": cfg.get("port", 22),
                "user": cfg.get("user"),
                "queue_system": cfg.get("queue_system", "lsf"),
                "home": cfg.get("home"),
                "remote_base": cfg.get("remote_base"),
            }
            for name, cfg in load_servers().items()
        ]
        return ok("查询成功", {"servers": items})
    except Exception as e:
        return JSONResponse(
            status_code=500, content=fail(f"读取服务器配置失败：{e}")
        )


@router.get("/task-types")
def task_types():
    try:
        items = [
            {
                "type": name,
                "description": cfg.get("description", name),
                "workload_weight": cfg.get("workload_weight", 1),
                "subtypes": cfg.get("subtypes", []),
                "subtype_labels": cfg.get("subtype_labels", {}),
            }
            for name, cfg in load_task_registry().items()
        ]
        return ok("查询成功", {"task_types": items})
    except Exception as e:
        return JSONResponse(
            status_code=500, content=fail(f"读取任务类型配置失败：{e}")
        )


@router.get("/deps")
def deps():
    return ok(
        "依赖检查完成",
        {"dependencies": check_dependencies(), "install_hint": INSTALL_HINT},
    )


@router.post("/tools/cif-to-poscar")
def cif_to_poscar(payload: dict = Body(default={})):
    """CIF → POSCAR（「导入 POSCAR」支持 .cif 文件时用）。

    body：`{content, filename?}`；返回 `{poscar, elements, counts, atoms, cell, formula, warnings}`。
    纯文本转换，不写任何文件；失败返回 400 并给出面向用户的说明。
    """
    try:
        content = str((payload or {}).get("content") or "")
        if not content.strip():
            return JSONResponse(status_code=400, content=fail("请提供 CIF 文件内容（content）"))
        poscar, info = cif_reader.cif_to_poscar(content)
        return ok(f"CIF 已转换为 POSCAR（{info['atoms']} 个原子）", {"poscar": poscar, **info})
    except cif_reader.CifError as e:
        return JSONResponse(status_code=400, content=fail(f"CIF 转换失败：{e}"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"CIF 转换失败：{e}"))
