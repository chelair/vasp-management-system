"""SSH 服务器配置接口（配置文件：data/config/servers.json）。

前端 SSH 连接页编辑的服务器配置（含“项目远程根目录”）通过本接口持久化，
新增项目时后端直接读取该文件中的 remote_base 作为远程根目录。
"""

import json
import os
import re
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import CONFIG_DIR, load_servers
from envelope import fail, ok
from ssh import get_pool_status

router = APIRouter(prefix="/ssh", tags=["ssh"])

SERVERS_PATH = CONFIG_DIR / "servers.json"
SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

CONFIG_KEYS = (
    "host",
    "port",
    "user",
    "key_path",
    "password",
    "home",
    "queue_system",
    "remote_base",
)


@router.get("/status")
def ssh_status():
    """常驻 SSH 连接池状态（顶栏真实连接指示）。"""
    try:
        return ok("查询成功", get_pool_status())
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"查询 SSH 状态失败：{e}"))


def _atomic_write_servers(servers: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(CONFIG_DIR), prefix=".servers_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(servers, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, SERVERS_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _to_public(name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": name,
        "host": cfg.get("host"),
        "port": cfg.get("port", 22),
        "user": cfg.get("user"),
        "auth_type": "key" if cfg.get("key_path") else "password",
        "key_path": cfg.get("key_path"),
        "password": cfg.get("password"),
        "home": cfg.get("home"),
        "queue_system": cfg.get("queue_system", "lsf"),
        "remote_base": cfg.get("remote_base"),
    }


@router.get("/config")
def get_config():
    try:
        servers = load_servers()
        return ok(
            "查询成功",
            {"servers": [_to_public(name, cfg) for name, cfg in servers.items()]},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取 SSH 配置失败：{e}"))


@router.put("/config")
def put_config(payload: dict):
    if not isinstance(payload, dict) or not isinstance(payload.get("servers"), list):
        return JSONResponse(
            status_code=400, content=fail("请求体必须包含 servers 列表")
        )
    items: List[Dict[str, Any]] = payload["servers"]

    # 校验
    names = set()
    for item in items:
        if not isinstance(item, dict):
            return JSONResponse(
                status_code=400, content=fail("servers 元素必须是对象")
            )
        name = item.get("name")
        if not isinstance(name, str) or not SERVER_NAME_PATTERN.fullmatch(name):
            return JSONResponse(
                status_code=400,
                content=fail("服务器名称（name）仅允许字母、数字、下划线、连字符"),
            )
        if name in names:
            return JSONResponse(
                status_code=400, content=fail(f"服务器名称重复：{name}")
            )
        names.add(name)
        if not isinstance(item.get("host"), str) or not item["host"].strip():
            return JSONResponse(
                status_code=400, content=fail(f"服务器 '{name}' 缺少 host")
            )
        if not isinstance(item.get("user"), str) or not item["user"].strip():
            return JSONResponse(
                status_code=400, content=fail(f"服务器 '{name}' 缺少 user")
            )
        if "port" in item and item["port"] is not None:
            if not isinstance(item["port"], int) or not 1 <= item["port"] <= 65535:
                return JSONResponse(
                    status_code=400,
                    content=fail(f"服务器 '{name}' 的 port 必须是 1-65535 的整数"),
                )

    # 合并写回：保留未提交的原有字段（如 bjobs_cmd / submit_cmd）
    existing = load_servers()
    new_servers: Dict[str, Any] = {}
    for item in items:
        name = item["name"]
        merged = dict(existing.get(name, {}))
        for key in CONFIG_KEYS:
            if key in item and item[key] is not None:
                merged[key] = item[key]
        # 认证方式互斥
        if item.get("password"):
            merged.pop("key_path", None)
        if item.get("key_path"):
            merged.pop("password", None)
        new_servers[name] = merged

    try:
        _atomic_write_servers(new_servers)
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"写入 SSH 配置失败：{e}"))
    return ok(
        "SSH 配置已保存",
        {"servers": [_to_public(name, cfg) for name, cfg in new_servers.items()]},
    )
