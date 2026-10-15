"""PDOS 分析链路（2026-10-13 重建）：远端 vaspkit 提取 → 整合 JSON 回传 → 本地解析 → 前端画图。

职责划分（用户口径）：

- **远端**：只跑提取脚本（复用 `scripts/dos_extract.py`，核心逻辑不动），生成**一个整合数据文件**
  （`dos.json`）；vaspkit 的原始 `.dat` **不传回来**；
- **本地后端**：接收整合数据 → 存 `<任务>/pdos/dos.json` → 解析成"菜单树 + 曲线"（内存缓存）→
  暴露 触发/状态/数据/清除 四个接口；
- **本地前端**：只消费接口数据（三级轨道菜单 + ECharts 折线）。

存储（`<任务本地目录>/pdos/`）：

    dos.json    远端回传的整合数据（唯一的大文件；元数据/曲线都从它解析）
    meta.json   轻量元数据：分析时间、run_id、费米能级、自旋、元素、脚本与文件指纹、失败原因

异步执行：`start(task)` 起后台线程并返回 `run_id`；`status()` 轮询；
同一任务已有 run 在跑时直接复用那个 run_id（重复点分析不会并发跑两遍）。
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from dates import now_iso
from paths import resolve_remote_path
from task_paths import task_dir

#: 复用仓库里的提取脚本（远端每次上传一份，避免依赖集群上的绝对路径）
EXTRACT_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dos_extract.py"
#: 远端放在任务目录下的脚本名与产物名
REMOTE_SCRIPT_NAME = "dos_extract.py"
REMOTE_JSON_NAME = "dos.json"
#: 本地产物目录
PDOS_DIR = "pdos"
DOS_JSON = "dos.json"
META_JSON = "meta.json"

#: 解析结果缓存：task_id → {"stamp": 文件指纹, "view": 解析结果}
_VIEW_CACHE: Dict[str, Dict[str, Any]] = {}
#: run 状态：run_id → {...}
_RUNS: Dict[str, Dict[str, Any]] = {}
#: 任务当前 run：task_id → run_id
_TASK_RUN: Dict[str, str] = {}
_LOCK = threading.Lock()

#: 方向投影（用户口径：目前只支持 p、d 分方向）
DIRECTIONS = {
    "p": [("px", "px"), ("py", "py"), ("pz", "pz")],
    "d": [("dxy", "dxy"), ("dyz", "dyz"), ("dz2", "dz2"), ("dxz", "dxz"), ("dx2", "dx²−y²")],
}
#: 二级轨道固定顺序
ORBITALS = ("s", "p", "d")


class PdosError(RuntimeError):
    """PDOS 链路错误：`status` = 建议的 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ 本地路径


def pdos_dir(project_name: str, task: Dict[str, Any]) -> Path:
    return task_dir(project_name, task) / PDOS_DIR


def data_path(project_name: str, task: Dict[str, Any]) -> Path:
    return pdos_dir(project_name, task) / DOS_JSON


def meta_path(project_name: str, task: Dict[str, Any]) -> Path:
    return pdos_dir(project_name, task) / META_JSON


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_meta(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    path = meta_path(project_name, task)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 坏了当空
        return {}


# ------------------------------------------------------------------ 解析成视图


def _curve_id(*parts: str) -> str:
    return "|".join(parts)


def build_view(payload: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """把提取脚本的整合数据解析成前端要的「菜单树 + 曲线」。

    树是**三级**（用户口径：一级总态密度、二级元素×轨道、三级只对 p / d 分方向）：

        total 总态密度
        el:<元素>            （元素节点本身不画线，只做分组）
          el:<元素>:s
          el:<元素>:p  →  el:<元素>:p:px / py / pz
          el:<元素>:d  →  el:<元素>:d:dxy / dyz / dz2 / dxz / dx2

    每个"能画线的节点"带 `curves`（自旋时 up/down 两条，非自旋一条），
    曲线数值放在顶层 `series` 里（id → {grid, values}），避免在树里重复大数组。
    """
    energy = payload.get("metadata") or {}
    total_dos = payload.get("total_dos") or {}
    orbital_dos = payload.get("orbital_dos") or {}
    element_dos = payload.get("element_dos") or {}

    spin = bool(energy.get("spin_polarized"))
    total_values = total_dos.get("total") or total_dos.get("up") or []
    if not energy.get("energy_grid") or not total_values:
        raise PdosError("整合数据缺少总态密度或能量网格，无法出图", 422)

    series: Dict[str, Dict[str, Any]] = {}

    #: 曲线配色计数：按遍历顺序从调色板轮转取色（同一次分析里顺序固定 → 颜色稳定，
    #: 勾掉/勾上别的曲线不会让已显示的曲线换色）。up/down 相邻 → 必然不同色。
    curve_seq = itertools.count()

    def add_curves(
        node: Dict[str, Any],
        prefix: Tuple[str, ...],
        buckets: Dict[str, List[float]],
        grid: str,
    ) -> None:
        """把 up/down/total 三条（有几条加几条）挂到节点上；**每条曲线一个颜色**。"""
        curves: List[Dict[str, Any]] = []
        order = [("up", "自旋向上"), ("down", "自旋向下")] if spin else [("total", "合计")]
        for key, label in order:
            values = buckets.get(key)
            if not values:
                continue
            cid = _curve_id(*prefix, key)
            series[cid] = {"grid": grid, "values": values}
            color = _CURVE_PALETTE[next(curve_seq) % len(_CURVE_PALETTE)]
            curves.append({"id": cid, "spin": key, "label": label, "color": color})
        if curves:
            node["curves"] = curves

    # 一级：总态密度
    total_node: Dict[str, Any] = {"key": "total", "label": "总态密度", "level": 1, "children": []}
    # 总态密度固定用蓝色族（它是参考曲线，跟投影曲线的调色板区分开）：
    # up = 主蓝、down = 浅一档的蓝 —— 自旋两条也不重复颜色。
    add_curves(total_node, ("total",), total_dos, "total")
    for curve in total_node.get("curves") or []:
        curve["color"] = "#8AB4F8" if curve.get("spin") == "down" else "#5B8DEF"
    tree: List[Dict[str, Any]] = [total_node]

    # 二级 / 三级：元素 → 轨道 →（p/d）方向
    partial_grid = "partial" if energy.get("partial_energy_grid") else "total"
    def has_signal(buckets: Optional[Dict[str, List[float]]]) -> bool:
        """这个轨道/方向有没有真实数据：**全零就不建节点**。

        VASPKIT 的投影 DOS 对每个元素都给满 s/py/pz/px/dxy… 全部列，
        没有 d 电子的元素（例如 S）d 列全 0 —— 用户口径：这种不要出现在菜单里
        （2026-10-13 反馈："S 没有 d 轨道还是导出了 d 轨道"）。
        """
        if not buckets:
            return False
        for values in buckets.values():
            if any(abs(float(v)) > 1e-6 for v in values or []):
                return True
        return False

    for element in sorted(orbital_dos.keys()):
        buckets_by_orbital = orbital_dos[element]
        element_node: Dict[str, Any] = {
            "key": f"el:{element}",
            "label": element,
            "level": 2,
            "color": _element_color(element),
            # 元素节点只是分组（元素总量没有单独曲线）：**不给勾选框**
            # —— 2026-10-13 用户口径："元素前面的勾可以去掉了"、"勾 Fe 无作用"
            "checkable": False,
            "children": [],
        }
        for orbital in ORBITALS:
            orbital_buckets = buckets_by_orbital.get(orbital)
            if not has_signal(orbital_buckets):
                continue
            orbital_node: Dict[str, Any] = {
                "key": f"el:{element}:{orbital}",
                "label": orbital,
                "level": 2,
                "children": [],
            }
            add_curves(
                orbital_node,
                ("el", element, orbital),
                orbital_buckets,
                partial_grid,
            )
            # 三级：只有 p / d 分方向
            for direction, label in DIRECTIONS.get(orbital, []):
                direction_buckets = buckets_by_orbital.get(direction)
                if not has_signal(direction_buckets):
                    continue
                direction_node: Dict[str, Any] = {
                    "key": f"el:{element}:{orbital}:{direction}",
                    "label": label,
                    "level": 3,
                    "children": [],
                }
                add_curves(
                    direction_node,
                    ("el", element, orbital, direction),
                    direction_buckets,
                    partial_grid,
                )
                if direction_node.get("curves"):
                    orbital_node["children"].append(direction_node)
            if orbital_node.get("curves") or orbital_node["children"]:
                element_node["children"].append(orbital_node)
        if element_node["children"]:
            tree.append(element_node)

    # 元素列表与"有没有投影"都按**过滤后**的菜单树算（全零的轨道/元素不进树）
    tree_elements = [node["label"] for node in tree if str(node.get("key", "")).startswith("el:")]
    has_projection = bool(tree_elements)
    has_fine = bool(
        any(
            has_signal(buckets_by_orbital.get(direction))
            for buckets_by_orbital in orbital_dos.values()
            for orbital in DIRECTIONS
            for direction, _ in DIRECTIONS[orbital]
        )
    )
    return {
        "meta": {
            **{k: v for k, v in meta.items() if k != "view"},
            "task_id": meta.get("task_id"),
            "generated_at": meta.get("generated_at") or now_iso(),
            "efermi": energy.get("efermi"),
            "spin_polarized": spin,
            "elements": tree_elements or sorted(element_dos.keys()),
            "nedos": energy.get("nedos"),
            "points": len(energy.get("energy_grid") or []),
            "partial_points": len(energy.get("partial_energy_grid") or []),
            "has_projection": has_projection,
            "has_fine_orbitals": has_fine,
            "notes": energy.get("notes") or [],
            "source": energy.get("source"),
        },
        "energy": {
            "total": energy.get("energy_grid") or [],
            "partial": energy.get("partial_energy_grid") or (energy.get("energy_grid") or []),
        },
        "tree": tree,
        "series": series,
    }


_ELEMENT_COLORS = {
    "H": "#8ab4f8",
    "C": "#9aa7b8",
    "N": "#5B8DEF",
    "O": "#EB6F8A",
    "S": "#F0A020",
    "P": "#d18a2b",
    "Fe": "#67C6B0",
    "Co": "#7b61d6",
    "Ni": "#2c9da8",
    "Al": "#B37FEB",
    "Si": "#4EA1D3",
    "Li": "#EB6F8A",
    "In": "#67C6B0",
    "Cl": "#F0A020",
}
_FALLBACK_COLORS = ["#5B8DEF", "#67C6B0", "#F0A020", "#B37FEB", "#EB6F8A", "#4EA1D3", "#7b61d6"]


#: **逐曲线**调色板（v0.9.56）。为什么要单独一套：
#: 以前同一元素的所有曲线共用一个颜色（`add_curves(color=_element_color(element))`），
#: 于是 Fe 的 dxy/dyz/dz2/dxz/dx2 五条、以及自旋 up/down 全是同一个颜色 ——
#: 用户 2026-10-15 反馈"不同曲线颜色都一样、带中心的 up/down 不好区分"。
#: 这套调色板**刻意冷暖交替**：相邻两个颜色对比强烈，而曲线的遍历顺序里
#: up/down 紧挨着（同一轨道先 up 后 down）→ 自旋一定不同色；不同方向也依次换色。
#: 23 个颜色足够把常见一屏（几组轨道 + 全部方向）都染成互不相同的颜色。
_CURVE_PALETTE = (
    "#E4572E",  # 橙红
    "#2E86DE",  # 蓝
    "#F2B134",  # 琥珀
    "#12A594",  # 青绿
    "#9B5DE5",  # 紫
    "#4CAF50",  # 绿
    "#E1467C",  # 玫红
    "#3D9BE9",  # 亮蓝
    "#C77D02",  # 棕黄
    "#0FA3A3",  # 蓝绿
    "#7B61D6",  # 蓝紫
    "#D9535B",  # 红
    "#67C6B0",  # 薄荷
    "#B37FEB",  # 淡紫
    "#EB6F8A",  # 粉红
    "#4EA1D3",  # 天蓝
    "#F0A020",  # 橙
    "#A0C814",  # 黄绿
    "#E86A33",  # 橘
    "#00A6A6",  # 深青
    "#8E6BBF",  # 藕紫
    "#D14E86",  # 洋红
    "#2C9DA8",  # 青
)


def _element_color(element: str) -> str:
    if element in _ELEMENT_COLORS:
        return _ELEMENT_COLORS[element]
    index = sum(ord(ch) for ch in element) % len(_FALLBACK_COLORS)
    return _FALLBACK_COLORS[index]


def load_view(project_name: str, task: Dict[str, Any], *, refresh: bool = False) -> Dict[str, Any]:
    """读本地整合数据并解析（带内存缓存：同一文件指纹不重复解析）。"""
    path = data_path(project_name, task)
    if not path.is_file():
        raise PdosError("该任务还没有 PDOS 分析结果（先点「PDOS · 开始分析」）", 404)
    stat = path.stat()
    stamp = f"{int(stat.st_mtime)}:{stat.st_size}"
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        cached = _VIEW_CACHE.get(task_id)
    if cached and cached.get("stamp") == stamp and not refresh:
        return cached["view"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PdosError(f"整合数据解析失败：{exc}", 422)
    meta = read_meta(project_name, task)
    view = build_view(payload, meta)
    with _LOCK:
        _VIEW_CACHE[task_id] = {"stamp": stamp, "view": view}
    return view


def clear(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """清除本地分析结果（数据 + 元数据 + 内存缓存/运行状态），便于重新分析。"""
    directory = pdos_dir(project_name, task)
    removed: List[str] = []
    if directory.is_dir():
        for name in (DOS_JSON, META_JSON):
            path = directory / name
            if path.is_file():
                path.unlink()
                removed.append(name)
        try:
            directory.rmdir()
        except OSError:
            pass
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        _VIEW_CACHE.pop(task_id, None)
        run_id = _TASK_RUN.pop(task_id, "")
        if run_id:
            _RUNS.pop(run_id, None)
    return {"removed": removed, "dir": str(directory)}


# ------------------------------------------------------------------ 远端执行


def _run_script(server: str, remote_dir: str) -> Dict[str, Any]:
    """把提取脚本上传到远端任务目录并执行（--quiet，最后一行给 @@@DONE）。"""
    if not EXTRACT_SCRIPT.is_file():
        raise PdosError(f"提取脚本不存在：{EXTRACT_SCRIPT}", 500)
    remote_script = f"{remote_dir}/{REMOTE_SCRIPT_NAME}"
    ssh.upload_file(server, str(EXTRACT_SCRIPT), remote_script)
    cmd = (
        f'cd "{remote_dir}" && python3 "{REMOTE_SCRIPT_NAME}" '
        f'--dir . --out "{REMOTE_JSON_NAME}" --quiet'
    )
    started = time.time()
    result = ssh.run_remote(server, cmd, timeout=1800)
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    done = next((line for line in raw.splitlines() if line.startswith("@@@DONE")), "")
    ok = bool(done) and int(result.get("exit_code") or 0) == 0
    return {"ok": ok, "raw": raw[-4000:], "done": done, "elapsed": round(time.time() - started, 1)}


def _background(project: Dict[str, Any], task: Dict[str, Any], run_id: str) -> None:
    """后台线程：上传脚本 → 执行 → 下载整合 JSON → 写元数据 → 解析缓存。"""
    task_id = str(task.get("task_id") or "")
    project_name = str(project.get("name") or "")
    server = str(project.get("server") or "")
    started = now_iso()
    try:
        remote_dir = resolve_remote_path(server, str(task.get("remote_dir") or "")).rstrip("/")
        if not remote_dir:
            raise PdosError("任务缺少远程目录", 400)
        run = _run_script(server, remote_dir)
        if not run["ok"]:
            tail = " / ".join(line.strip() for line in run["raw"].splitlines() if line.strip())[-600:]
            raise PdosError(f"远端提取失败：{tail or '没有输出'}", 500)
        local = data_path(project_name, task)
        local.parent.mkdir(parents=True, exist_ok=True)
        if not ssh.download_file(server, f"{remote_dir}/{REMOTE_JSON_NAME}", str(local)):
            raise PdosError("整合数据回传失败（远端 dos.json 下载不到）", 502)
        meta = {
            "task_id": task_id,
            "run_id": run_id,
            "project_name": project_name,
            "remote_dir": remote_dir,
            "started_at": started,
            "finished_at": now_iso(),
            "elapsed_seconds": run["elapsed"],
            "status": "done",
            "script": EXTRACT_SCRIPT.name,
            "bytes": local.stat().st_size,
            "done_line": run["done"],
        }
        view = load_view(project_name, task, refresh=True)
        meta.update(
            {
                "efermi": view["meta"].get("efermi"),
                "spin_polarized": view["meta"].get("spin_polarized"),
                "elements": view["meta"].get("elements"),
                "has_projection": view["meta"].get("has_projection"),
                "has_fine_orbitals": view["meta"].get("has_fine_orbitals"),
                "points": view["meta"].get("points"),
            }
        )
        _write_json(meta_path(project_name, task), meta)
        with _LOCK:
            _RUNS[run_id].update({"status": "done", "finished_at": meta["finished_at"], "meta": meta})
    except PdosError as exc:
        _fail(project_name, task, run_id, str(exc), started)
    except Exception as exc:  # noqa: BLE001 - 线程里不能抛
        _fail(project_name, task, run_id, f"{type(exc).__name__}: {exc}", started)
    finally:
        with _LOCK:
            if _TASK_RUN.get(task_id) == run_id:
                _TASK_RUN.pop(task_id, None)


def _fail(project_name: str, task: Dict[str, Any], run_id: str, message: str, started: str) -> None:
    """失败：写进元数据（保留上一次的成功数据/元信息里的其它字段）并更新 run 状态。"""
    meta = read_meta(project_name, task)
    meta.update(
        {
            "task_id": str(task.get("task_id") or ""),
            "run_id": run_id,
            "started_at": started,
            "finished_at": now_iso(),
            "status": "failed",
            "error": message,
        }
    )
    try:
        _write_json(meta_path(project_name, task), meta)
    except Exception:  # noqa: BLE001 - 写元数据失败不影响状态上报
        pass
    with _LOCK:
        _RUNS[run_id].update({"status": "failed", "error": message, "finished_at": meta["finished_at"]})


def start(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """触发分析：已有在跑的 run 就复用，否则起后台线程。返回 run 信息。"""
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        current = _TASK_RUN.get(task_id)
        if current and _RUNS.get(current, {}).get("status") == "running":
            return {"run_id": current, "status": "running", "reused": True}
        run_id = f"pdos_{int(time.time() * 1000)}"
        _RUNS[run_id] = {
            "run_id": run_id,
            "task_id": task_id,
            "status": "running",
            "started_at": now_iso(),
        }
        _TASK_RUN[task_id] = run_id
    thread = threading.Thread(
        target=_background, args=(dict(project), dict(task), run_id), daemon=True
    )
    thread.start()
    return {"run_id": run_id, "status": "running", "reused": False}


def status(project_name: str, task: Dict[str, Any], run_id: str = "") -> Dict[str, Any]:
    """查询 run 状态；不传 run_id 时看该任务当前/最近一次 run，并带上本地元数据。"""
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        rid = run_id or _TASK_RUN.get(task_id, "")
        if not rid:
            latest = [
                r for r in _RUNS.values() if r.get("task_id") == task_id
            ]
            rid = latest[-1]["run_id"] if latest else ""
        run = dict(_RUNS.get(rid) or {})
    meta = read_meta(project_name, task)
    has_data = data_path(project_name, task).is_file()
    if not run:
        run = {
            "run_id": rid,
            "status": "done" if has_data else ("failed" if meta.get("status") == "failed" else "idle"),
            "error": meta.get("error"),
            "finished_at": meta.get("finished_at"),
        }
    run["has_data"] = has_data
    run["meta"] = meta
    return run
