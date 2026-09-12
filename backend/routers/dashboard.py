"""总览页接口：聚合总览 / 核数占用 / 集群健康 / 风险预警 / 趋势。

集群查询走 `dashboard.cluster_snapshot`（单次 SSH + 5 分钟缓存），
`?refresh=1` 强制重新查询；本地归档聚合另有 60 秒缓存。
"""

from fastapi import APIRouter, Query
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
    server: str | None = Query(default=None, description="服务器名，默认取第一个"),
    refresh: bool = Query(default=False, description="true 时忽略缓存强制查询"),
):
    try:
        return ok("查询成功", cached_overview(_server(server), refresh=refresh))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"总览数据获取失败：{e}"))


@router.get("/dashboard/cores-usage")
def cores_usage(
    server: str | None = Query(default=None),
    refresh: bool = Query(default=False),
):
    try:
        name = _server(server)
        snapshot = cluster_snapshot(name, refresh=refresh)
        return ok(
            "查询成功",
            {
                **build_cores_usage(load_db(), snapshot),
                "queriedAt": snapshot.get("queriedAt"),
                "source": snapshot.get("source"),
                "error": snapshot.get("error"),
            },
        )
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
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"集群状态获取失败：{e}"))


@router.get("/dashboard/risk-alerts")
def risk_alerts():
    try:
        return ok("查询成功", local_bundle()["riskAlerts"])
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"风险任务获取失败：{e}"))


@router.get("/dashboard/trend")
def trend(days: int = Query(default=7, ge=2, le=30)):
    try:
        data = dict(local_bundle()["trend"])
        data["points"] = (data.get("points") or [])[-days:]
        data["days"] = days
        return ok("查询成功", data)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"趋势数据获取失败：{e}"))
