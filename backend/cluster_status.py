"""集群节点状态：解析共享采集 + 节点-队列映射。

节点-队列映射固化在 servers.json 的 node_groups 中（b001-b014 → normal_2week 等）。
**v0.8.7 起不再自己发 SSH**：原始 bhosts / bqueues 来自 `cluster_probe` 的共享采集
（与总览页同一份、同一 TTL 缓存），这里只做解析与映射；
模拟模式（VASP_SSH_MOCK=1）或采集失败且无旧数据时，按映射生成模拟负载供界面预览。
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import cluster_probe
from config import load_servers


def format_walltime(days: Optional[int]) -> str:
    if days is None:
        return "无限制"
    if days >= 7 and days % 7 == 0:
        return f"{days // 7}周"
    return f"{days}天"


def expand_node_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 node_groups 的区间展开为具体节点列表。"""
    nodes: List[Dict[str, Any]] = []
    for group in groups or []:
        prefix = str(group.get("prefix", "n"))
        start = int(group.get("start", 1))
        end = int(group.get("end", start))
        width = max(3, len(prefix) + 3)
        for i in range(start, end + 1):
            nodes.append(
                {
                    "name": f"{prefix}{i:03d}",
                    "queue": str(group.get("queue", "")),
                    "max_cores": int(group.get("cores_per_node", 1)),
                    "walltime": format_walltime(group.get("walltime_days")),
                    "cpu_model": str(group.get("cpu_model", "")),
                    "cpu_freq": str(group.get("cpu_freq", "")),
                    "suspend_risk": str(group.get("suspend_risk", "low")),
                    "paid": bool(group.get("paid", False)),
                    "price": float(group.get("price_per_core_hour", 0) or 0),
                }
            )
    return nodes


def _hash_ratio(name: str, salt: str) -> float:
    """按节点名生成稳定的模拟负载比例（0.15 ~ 0.95）。"""
    digest = hashlib.md5(f"{name}:{salt}".encode("utf-8")).hexdigest()
    return 0.15 + (int(digest[:8], 16) % 8000) / 10000


def simulate_nodes(nodes: List[Dict[str, Any]], salt: str = "vasp") -> List[Dict[str, Any]]:
    """按映射生成模拟节点占用（状态分布：多数 ok，少量 busy/unavail）。"""
    result: List[Dict[str, Any]] = []
    for idx, node in enumerate(nodes):
        ratio = _hash_ratio(node["name"], salt)
        if idx % 9 == 3:
            status = "unavail"
            running = 0
            suspended = 0
            unavail = node["max_cores"]
        else:
            status = "ok"
            running = round(node["max_cores"] * ratio)
            if idx % 7 == 4:
                running = node["max_cores"]
                status = "busy"
            suspended = round(node["max_cores"] * 0.04) if idx % 5 == 2 else 0
            unavail = 0
        idle = max(0, node["max_cores"] - running - suspended - unavail)
        if status == "ok" and idle == 0:
            status = "busy"
        result.append({**node, "status": status, "running_cores": running,
                       "suspended_cores": suspended, "unavail_cores": unavail,
                       "idle_cores": idle})
    return result


def parse_bhost(output: str) -> Dict[str, Dict[str, Any]]:
    """按表头解析 bhost / bhosts 输出（兼容列顺序差异）。

    经典 bhost：HOST_NAME STATUS JL/U MAX NJOBS RUN SSUSP UNAVAIL
    IBM bhosts：HOST_NAME STATUS JL/U MAX NJOBS RUN SSUSP USUSP RSV
    """
    parsed: Dict[str, Dict[str, Any]] = {}
    header: Dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].upper() == "HOST_NAME":
            header = {name.upper(): i for i, name in enumerate(parts)}
            continue
        if not header:
            continue
        name = parts[0]

        def col(key: str) -> int:
            idx = header.get(key)
            return int(parts[idx]) if idx is not None and idx < len(parts) else 0

        try:
            parsed[name] = {
                "status": parts[1],
                "max_cores": col("MAX"),
                "running_cores": col("RUN"),
                "suspended_cores": col("SSUSP") + col("USUSP"),
                "unavail_cores": col("UNAVAIL"),
            }
        except ValueError:
            continue
    return parsed


def parse_bqueues(output: str) -> Dict[str, Dict[str, Any]]:
    """解析 bqueues 输出（补充信息）：QUEUE_NAME PRIO STATUS ... NJOBS PEND RUN SSUSP ..."""
    parsed: Dict[str, Dict[str, Any]] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 8 or parts[0].upper() == "QUEUE_NAME":
            continue
        queue = parts[0]
        try:
            parsed[queue] = {
                "status": parts[2],
                "pending": int(parts[8]),
                "running": int(parts[9]),
                "suspended": int(parts[10]),
            }
        except (ValueError, IndexError):
            continue
    return parsed


def _map_status(bhost_status: str, idle: int, running: int) -> str:
    low = bhost_status.lower()
    if low in ("closed", "closedadm", "closemig"):
        return "closed"
    if low in ("unavail", "unknow", "new"):
        return "unavail"
    if idle == 0 and running > 0:
        return "busy"
    if running > 0 and idle < running:
        return "warning"
    return "ok"


def build_snapshot(server_name: str, use_cache: bool = True) -> Dict[str, Any]:
    """节点状态：读 `cluster_probe` 的**共享采集**（与总览页同一份）+ node_groups 映射。

    v0.8.7 起不再单独发 SSH：采集（bhosts / bqueues / bjobs / blimits / df 一次 exec）
    由 `cluster_probe.probe()` 统一做并按 TTL（默认 300s）缓存，`use_cache=False`
    等价于 `refresh=1`（强制重采，总览页看到的也会一起更新）。
    """
    servers = load_servers()
    cfg = servers.get(server_name)
    groups = (cfg or {}).get("node_groups", [])
    mapped = expand_node_groups(groups)
    if not mapped:
        return {
            "source": "mock",
            "error": "服务器配置中未定义 node_groups 节点映射",
            "queriedAt": datetime.now().isoformat(timespec="seconds"),
            "nodes": [],
            "queues": [],
            "bhostRaw": "",
            "bqueuesRaw": "",
        }

    probe = cluster_probe.probe(server_name, refresh=not use_cache)
    sections = probe.get("sections") or {}
    bhost_raw = sections.get("BHOSTS", "")
    bqueues_raw = sections.get("BQUEUES", "")
    source = "real"
    error = str(probe.get("error") or "")
    if not bhost_raw:
        # 采集失败且没有可用旧数据 → 回退模拟负载（界面明确标"模拟数据"）
        source = "mock"
        error = error or "未取到节点状态数据（检查 SSH / LSF profile）"
    try:
        host_map = parse_bhost(bhost_raw)
        queue_map = parse_bqueues(bqueues_raw)
    except Exception as e:  # noqa: BLE001 - SSH 不可用/未连接时回退模拟
        source = "mock"
        error = str(e)
        host_map = {}
        queue_map = {}

    if source == "mock":
        raw_nodes = simulate_nodes(mapped)
    else:
        raw_nodes = []
        for node in mapped:
            live = host_map.get(node["name"])
            if live is None:
                raw_nodes.append(
                    {
                        **node,
                        "status": "closed",
                        "running_cores": 0,
                        "suspended_cores": 0,
                        "unavail_cores": node["max_cores"],
                        "idle_cores": 0,
                    }
                )
                continue
            idle = max(
                0,
                live["max_cores"]
                - live["running_cores"]
                - live["suspended_cores"]
                - live["unavail_cores"],
            )
            raw_nodes.append(
                {
                    **node,
                    "status": _map_status(live["status"], idle, live["running_cores"]),
                    "running_cores": live["running_cores"],
                    "suspended_cores": live["suspended_cores"],
                    "unavail_cores": live["unavail_cores"],
                    "idle_cores": idle,
                }
            )

    # 输出字段统一为 camelCase（与前端类型对齐）
    nodes = [
        {
            "name": n["name"],
            "queue": n["queue"],
            "maxCores": n["max_cores"],
            "runningCores": n["running_cores"],
            "suspendedCores": n["suspended_cores"],
            "unavailCores": n["unavail_cores"],
            "idleCores": n["idle_cores"],
            "status": n["status"],
            "cpuModel": n["cpu_model"],
            "cpuFreq": n["cpu_freq"],
            "walltime": n["walltime"],
            "suspendRisk": n["suspend_risk"],
            "paid": n["paid"],
            "price": n["price"],
        }
        for n in raw_nodes
    ]

    # 按队列汇总（bqueues 作为补充信息）
    queues: List[Dict[str, Any]] = []
    by_queue: Dict[str, List[Dict[str, Any]]] = {}
    for node in raw_nodes:
        by_queue.setdefault(node["queue"], []).append(node)
    for queue, members in by_queue.items():
        total = sum(m["max_cores"] for m in members)
        running = sum(m["running_cores"] for m in members)
        idle = sum(m["idle_cores"] for m in members)
        first = members[0]
        queues.append(
            {
                "queue": queue,
                "walltime": first["walltime"],
                "coresPerNode": first["max_cores"],
                "cpuModel": first["cpu_model"],
                "cpuFreq": first["cpu_freq"],
                "suspendRisk": first["suspend_risk"],
                "paid": first["paid"],
                "price": first["price"],
                "nodeCount": len(members),
                "totalCores": total,
                "runningCores": running,
                "idleCores": idle,
                "busyPercent": round(running / total * 100, 1) if total else 0,
                "bqueues": queue_map.get(queue, {}),
            }
        )
    result = {
        "source": source,
        "error": error or None,
        "queriedAt": probe.get("queriedAt") or datetime.now().isoformat(timespec="seconds"),
        "nodes": nodes,
        "queues": queues,
        "bhostRaw": bhost_raw,
        "bqueuesRaw": bqueues_raw,
        # 采集元信息：前端据此显示「缓存 X 分钟 · N 分钟前采集」（v0.8.7）
        "cached": bool(probe.get("cached")),
        "stale": bool(probe.get("stale")),
        "cacheAgeSeconds": probe.get("cacheAgeSeconds"),
        "cacheTtlSeconds": probe.get("cacheTtlSeconds"),
    }
    return result
