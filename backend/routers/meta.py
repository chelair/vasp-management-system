"""元信息接口：健康检查 / 服务器列表 / 任务类型 / 依赖检查。"""

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import load_servers, load_task_registry
from dependencies import INSTALL_HINT, check_dependencies
from envelope import fail, ok

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return ok("ok", {"uptime": time.monotonic()})


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
