"""总览页接口：聚合总览 / 核数占用 / 集群健康 / 风险预警 / 趋势。

集群查询走 `dashboard.cluster_snapshot`（单次 SSH + 5 分钟缓存），
`?refresh=1` 强制重新查询；本地归档聚合另有 60 秒缓存。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from config import load_servers
from dashboard import (
    build_cluster_health,
    build_cores_usage,
    cached_overview,
    cluster_snapshot,
    local_bundle,
)
from envelope import fail, ok
import permissions
from storage import load_db

router = APIRouter(tags=["dashboard"])


def _server(name: str | None) -> str:
    servers = load_servers()
    if name and name in servers:
        return name
    if servers:
        return next(iter(servers))
    raise ValueError("未配置任何服务器")


@router.get("/dashboard/overview")
def overview(
    request: Request,
    server: str | None = Query(default=None, description="服务器名，默认取第一个"),
    refresh: bool = Query(default=False, description="true 时忽略缓存强制查询"),
):
    """总览聚合：项目相关统计按可见项目过滤（第 4 步），集群信息保持全局。"""
    try:
        names = permissions.visible_project_names(load_db(), getattr(request.state, "user", None))
        return ok(
            "查询成功",
            cached_overview(_server(server), refresh=refresh, project_names=names),
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"总览数据获取失败：{e}"))


@router.get("/dashboard/cores-usage")
def cores_usage(
    request: Request,
    server: str | None = Query(default=None),
    refresh: bool = Query(default=False),
):
    """核数占用：项目维度的分配按可见项目过滤；集群总量（blimits）仍是全局真实值。"""
    try:
        name = _server(server)
        snapshot = cluster_snapshot(name, refresh=refresh)
        db = load_db()
        names = permissions.visible_project_names(db, getattr(request.state, "user", None))
        visible_db = {
            **db,
            "projects": [p for p in db.get("projects", []) if str(p.get("name") or "") in names],
        }
        return ok(
            "查询成功",
            {
                **build_cores_usage(visible_db, snapshot),
                "queriedAt": snapshot.get("queriedAt"),
                "source": snapshot.get("source"),
                "error": snapshot.get("error"),
            },
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"核数占用获取失败：{e}"))


@router.get("/dashboard/cluster-health")
def cluster_health(
    server: str | None = Query(default=None),
    refresh: bool = Query(default=False),
):
    try:
        name = _server(server)
        snapshot = cluster_snapshot(name, refresh=refresh)
        return ok(
            "查询成功",
            {
                **build_cluster_health(snapshot),
                "queriedAt": snapshot.get("queriedAt"),
                "source": snapshot.get("source"),
                "error": snapshot.get("error"),
                "cached": snapshot.get("cached"),
                "cacheAgeSeconds": snapshot.get("cacheAgeSeconds"),
                "stale": snapshot.get("stale", False),
            },
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"集群状态获取失败：{e}"))


@router.get("/dashboard/risk-alerts")
def risk_alerts(request: Request):
    try:
        names = permissions.visible_project_names(load_db(), getattr(request.state, "user", None))
        return ok("查询成功", local_bundle(project_names=names)["riskAlerts"])
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"风险任务获取失败：{e}"))


@router.get("/dashboard/trend")
def trend(request: Request, days: int = Query(default=7, ge=2, le=30)):
    """趋势：集群采样与提交数都是全局量（不按项目拆分），保持全局可见。"""
    try:
        names = permissions.visible_project_names(load_db(), getattr(request.state, "user", None))
        data = dict(local_bundle(project_names=names)["trend"])
        data["points"] = (data.get("points") or [])[-days:]
        data["days"] = days
        return ok("查询成功", data)
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"趋势数据获取失败：{e}"))
