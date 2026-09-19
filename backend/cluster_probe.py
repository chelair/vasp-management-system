"""集群原始采集 + 共享缓存（v0.8.7）。

**总览页与作业管理页共用同一份集群采集**：

- 一次 SSH exec 拿 5 段原始输出（bjobs / blimits / df / bhosts / bqueues），
  用 `@@@NAME` 标记分段；
- 原始文本按 TTL 缓存（`settings.cluster_cache_seconds`，兼容旧的
  `dashboard_cache_seconds`，默认 300s = 5 分钟）——两个页面在 TTL 内打开都**直接读缓存**，
  不再各自发 SSH；
- 任一页面手动刷新（`refresh=1`）强制重采一次，两边看到的数据同时更新；
- 采集失败但有上一份数据时返回**旧数据 + stale 标记**（不伪造数据），
  完全没有数据时由调用方决定回退（作业管理回退模拟负载）。

调用方：
- `dashboard.cluster_snapshot()` → 解析 jobs / coreLimit / storage / nodes / queues
- `cluster_status.build_snapshot()` → 解析 nodes（node_groups 映射）+ queues
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import load_servers, load_settings
from ssh import run_remote

DEFAULT_TTL_SECONDS = 300

DEFAULT_COMMANDS = {
    "node_status_cmd": "bhosts",
    "queue_status_cmd": "bqueues",
    "user_used_cores_cmd": (
        'bjobs -u $USER -o "jobid stat queue job_name slots exec_host" -noheader'
    ),
    "user_total_cores_cmd": "blimits",
    "storage_check_cmd": "df -h {storage_path}",
}

_cache: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def cache_ttl_seconds() -> int:
    """采集缓存时长（秒）：cluster_cache_seconds > dashboard_cache_seconds > 300。"""
    settings = load_settings()
    raw = settings.get("cluster_cache_seconds")
    if raw in (None, ""):
        raw = settings.get("dashboard_cache_seconds", DEFAULT_TTL_SECONDS)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS


def resolve_command(server_cfg: Dict[str, Any], key: str) -> str:
    """取远端命令：servers.json（按服务器）> settings.json（全局）> 内置默认。"""
    val = str(server_cfg.get(key, "") or "").strip()
    if val:
        return val
    val = str(load_settings().get(key, "") or "").strip()
    if val:
        return val
    # 兼容 cluster_status 时代的旧键名（bhost_cmd / bqueues_cmd）
    legacy = {
        "node_status_cmd": "bhost_cmd",
        "queue_status_cmd": "bqueues_cmd",
    }.get(key)
    if legacy:
        val = str(server_cfg.get(legacy, "") or "").strip()
        if val:
            return val
    return DEFAULT_COMMANDS[key]


def cluster_script(server_name: str) -> str:
    cfg = load_servers().get(server_name, {}) or {}
    profile = str(cfg.get("lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"))
    storage_path = str(cfg.get("remote_base", "") or "").rstrip("/") or "."
    commands = {
        key: resolve_command(cfg, key).replace("{storage_path}", storage_path)
        for key in DEFAULT_COMMANDS
    }
    return "\n".join(
        [
            f"source {profile} >/dev/null 2>&1 || true",
            "echo @@@BJOBS",
            commands["user_used_cores_cmd"],
            "echo @@@BLIMITS",
            commands["user_total_cores_cmd"],
            "echo @@@DF",
            commands["storage_check_cmd"],
            "echo @@@BHOSTS",
            commands["node_status_cmd"],
            "echo @@@BQUEUES",
            commands["queue_status_cmd"],
            "echo @@@END",
        ]
    )


def split_sections(output: str) -> Dict[str, str]:
    """按 `@@@NAME` 标记切分远端输出。"""
    result: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in output.splitlines():
        m = re.match(r"^@@@([A-Z]+)\s*$", line.strip())
        if m:
            if current:
                result[current] = "\n".join(buf).strip("\n")
            current = m.group(1)
            buf = []
            continue
        if current:
            buf.append(line)
    if current:
        result[current] = "\n".join(buf).strip("\n")
    return result


def _payload(entry: Dict[str, Any], now: float, ttl: int) -> Dict[str, Any]:
    return {
        "server": entry.get("server"),
        "sections": entry.get("sections") or {},
        "queriedAt": entry.get("queriedAt"),
        "cacheAgeSeconds": round(now - float(entry.get("at") or now), 1),
        "cacheTtlSeconds": ttl,
    }


def probe(server_name: str, refresh: bool = False) -> Dict[str, Any]:
    """取集群原始采集（按 TTL 缓存）。

    返回 `{server, sections, queriedAt, cached, cacheAgeSeconds, cacheTtlSeconds, stale, error}`；
    `error` 非空表示这次采集失败（`stale=True` 时 sections 是上一次的可用数据）。
    """
    global _cache
    ttl = cache_ttl_seconds()
    now = time.time()
    with _lock:
        entry = _cache.get(server_name)
        if (
            entry
            and entry.get("sections")
            and not refresh
            and now - float(entry.get("at") or 0) < ttl
        ):
            return {**_payload(entry, now, ttl), "cached": True, "stale": False, "error": None}
        try:
            result = run_remote(server_name, cluster_script(server_name), timeout=90)
            if result.get("exit_code") != 0:
                raise RuntimeError(
                    (
                        result.get("stderr")
                        or result.get("stdout")
                        or "集群查询失败"
                    ).strip()[:300]
                )
            sections = split_sections(str(result.get("stdout") or ""))
            if not sections:
                raise RuntimeError("集群查询返回为空（检查 LSF profile 与命令配置）")
            _cache[server_name] = {
                "at": now,
                "server": server_name,
                "sections": sections,
                "queriedAt": datetime.now().isoformat(timespec="seconds"),
            }
            entry = _cache[server_name]
            return {**_payload(entry, now, ttl), "cached": False, "stale": False, "error": None}
        except Exception as e:  # noqa: BLE001 - 采集失败：有旧数据就用旧数据
            if entry and entry.get("sections"):
                return {
                    **_payload(entry, now, ttl),
                    "cached": True,
                    "stale": True,
                    "error": str(e),
                }
            return {
                "server": server_name,
                "sections": {},
                "queriedAt": datetime.now().isoformat(timespec="seconds"),
                "cached": False,
                "cacheAgeSeconds": 0.0,
                "cacheTtlSeconds": ttl,
                "stale": True,
                "error": str(e),
            }


def invalidate(servers: Optional[List[str]] = None) -> List[str]:
    """作废采集缓存（巡检结束后调用），返回被作废的服务器名。"""
    global _cache
    with _lock:
        targets = [s for s in (servers or list(_cache.keys())) if s]
        for name in targets:
            _cache.pop(name, None)
        return targets


def status() -> Dict[str, Any]:
    """调试/状态查询：当前缓存到的服务器与采集时间。"""
    now = time.time()
    ttl = cache_ttl_seconds()
    return {
        "cacheTtlSeconds": ttl,
        "servers": [
            {
                "server": name,
                "queriedAt": entry.get("queriedAt"),
                "cacheAgeSeconds": round(now - float(entry.get("at") or now), 1),
                "sections": sorted((entry.get("sections") or {}).keys()),
            }
            for name, entry in _cache.items()
        ],
    }
