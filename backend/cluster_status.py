"""集群节点状态查询：bhost（主）+ bqueues（补充）+ 节点-队列映射。

节点-队列映射固化在 servers.json 的 node_groups 中（b001-b014 → normal_2week 等），
真实模式下通过 Paramiko 执行 bhost / bqueues 并解析；
模拟模式（VASP_SSH_MOCK=1）或真实查询失败时，按映射生成模拟负载，保证界面可预览。
"""

import hashlib
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import load_servers
from ssh import run_remote

# 节点状态缓存（秒）：避免页面反复打开时重复 SSH 查询
CACHE_TTL_SECONDS = 60
_snapshot_cache: Dict[str, Any] = {"at": 0.0, "data": None}


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
    """查询服务器节点状态：bhost 主数据 + bqueues 补充 + node_groups 映射。"""
    global _snapshot_cache
    now = time.time()
    if use_cache and _snapshot_cache["data"] and now - _snapshot_cache["at"] < CACHE_TTL_SECONDS:
        return _snapshot_cache["data"]

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

    source = "real"
    error = ""
    bhost_raw = ""
    bqueues_raw = ""
    nodes_query_cmd = str(cfg.get("nodes_query_cmd", "")).strip()
    bhost_cmd = str(cfg.get("bhost_cmd", 'bash -c "bhosts"'))
    bqueues_cmd = str(cfg.get("bqueues_cmd", 'bash -c "bqueues"'))
    try:
        if nodes_query_cmd:
            # 单次 SSH 连接同时查询 bhosts + bqueues，避免登录 shell 开销
            query = run_remote(server_name, nodes_query_cmd, timeout=35)
            if query["exit_code"] != 0:
                raise RuntimeError(
                    query["stderr"].strip()
                    or query["stdout"].strip()
                    or "节点状态查询失败"
                )
            out = query["stdout"]
            if "===BQUEUES===" in out:
                head, bqueues_raw = out.split("===BQUEUES===", 1)
            else:
                head, bqueues_raw = out, ""
            bhost_raw = head.split("===BHOST===", 1)[1] if "===BHOST===" in head else head
        else:
            bhost = run_remote(server_name, bhost_cmd, timeout=25)
            bqueues = run_remote(server_name, bqueues_cmd, timeout=25)
            if bhost["exit_code"] != 0:
                raise RuntimeError(
                    bhost["stderr"].strip() or bhost["stdout"].strip() or "bhost 执行失败"
                )
            bhost_raw = bhost["stdout"]
            bqueues_raw = bqueues.get("stdout", "")
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
        "queriedAt": datetime.now().isoformat(timespec="seconds"),
        "nodes": nodes,
        "queues": queues,
        "bhostRaw": bhost_raw,
        "bqueuesRaw": bqueues_raw,
    }
    if source == "real" or not error:
        _snapshot_cache = {"at": now, "data": result}
    return result
