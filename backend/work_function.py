"""功函数链路（2026-10-15 新建）：远端 VASPKIT 426 提平面平均电位 → 回传小数据 → 本地解析 → 前端画图。

用户口径（`待办.md`）：前端选方向（默认 c，支持 a/b）→ 检查 `LOCPOT`/`OUTCAR` 存在非零、
**所选方向是否开了偶极矫正**（`LDIPOL=.TRUE.` 且 `IDIPOL` 与方向匹配；没开就警告但继续）
→ 远端 VASPKIT 426 提取 → 回传解析 → 前端画图（要有真空能级、功函数数值等关键量）。

实测口径（2026-10-15，集群 vaspkit 1.3.5）：

    vaspkit -task 426 -dir z      # **-dir 是笛卡尔方向 x/y/z**（a↔x、b↔y、c↔z，实测 `-dir c` 会报错）

- 写 `PLANAR_AVERAGE.dat`（约 8.7 KB，`#Distance(A) Planar-Average-Potential(eV)` + 两列），
  stdout 汇总 `Vacuum-Level (eV): 4.234` / `Work Function (eV): 5.148`；
- **WF = 真空能级 − E_fermi**（`E-fermi` 从 OUTCAR 读；实测 4.234 − (−0.9138) = 5.148 ✓）；
- **没有 DOSCAR 时** VASPKIT 会在写完 `.dat` 之后报 `The DOSCAR File NOT Exist` 并**跳过汇总** ——
  所以链路**不依赖 VASPKIT 的汇总**：本地从 `.dat` 自己估真空能级（找电位平台）并算 WF，
  再把 VASPKIT 的汇总拿来**交叉校验**（两者差得多时给 warning）。

本地产物（`<任务本地目录>/workfunction/`）：

    PLANAR_AVERAGE.dat   远端回传的平面平均电位曲线
    meta.json            最近一次链路运行的状态与解析结果

远端只做一次 exec（在 `mktemp -d` 的临时目录里软链 LOCPOT/OUTCAR/DOSCAR 后跑 VASPKIT，
跑完删掉临时目录）——**不往任务目录写任何东西**，`.dat` 内容直接 base64 随这次 exec 回传
（几 KB，不需要 SFTP）。异步模型与 pdos/bader 一致：`start()` / `status()` / `load_data()` / `clear()`。
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from dates import now_iso
from paths import to_local_rel
from storage import db_transaction
from task_paths import task_dir, task_remote_dir

#: 界面上的晶轴 → VASPKIT `-dir` 的**笛卡尔**方向
AXIS_TO_CARTESIAN: Dict[str, str] = {"a": "x", "b": "y", "c": "z"}
#: 界面上的晶轴 → "这个方向算不算开了偶极矫正"对应的 IDIPOL（4 = 全方向都算开了）
AXIS_TO_IDIPOL: Dict[str, int] = {"a": 1, "b": 2, "c": 3}
AXIS_LABELS: Dict[str, str] = {"a": "a 轴（x 方向）", "b": "b 轴（y 方向）", "c": "c 轴（z 方向）"}

LOCPOT_NAME = "LOCPOT"
OUTCAR_NAME = "OUTCAR"
DOSCAR_NAME = "DOSCAR"
INCAR_NAME = "INCAR"
RESULT_NAME = "PLANAR_AVERAGE.dat"
DIR_NAME = "workfunction"
META_JSON = "meta.json"
#: 真空平台的取样宽度（相对轴向长度的比例，两端各取这么宽、挑更平的一侧）
PLATEAU_FRACTION = 0.12
_VASPKIT_DEFAULT = "vaspkit"

STAGE_LABELS = {
    "checking": "远端检查 LOCPOT / OUTCAR / 偶极矫正",
    "extracting": "远端 VASPKIT 426 提取平面平均电位",
    "parsing": "解析平面平均电位并估真空能级",
    "done": "已完成",
}

_PROBE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PROBE_TTL_SECONDS = 120.0
_RUNS: Dict[str, Dict[str, Any]] = {}
_TASK_RUN: Dict[str, str] = {}
_LOCK = threading.Lock()
_LOG = Path(__file__).resolve().parent.parent / "data" / "work_function.log"


class WorkFunctionError(RuntimeError):
    """链路错误：`status` = 建议的 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _log_line(message: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


# ------------------------------------------------------------------ 路径


def local_dir(project_name: str, task: Dict[str, Any]) -> Path:
    return task_dir(project_name, task) / DIR_NAME


def data_path(project_name: str, task: Dict[str, Any]) -> Path:
    return local_dir(project_name, task) / RESULT_NAME


def meta_path(project_name: str, task: Dict[str, Any]) -> Path:
    return local_dir(project_name, task) / META_JSON


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_meta(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(meta_path(project_name, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def vaspkit_exe(server: str) -> str:
    """远端 vaspkit：`servers.json: vaspkit_exe` 可覆盖（默认 PATH 里的 `vaspkit`）。"""
    from config import load_servers

    configured = str(load_servers().get(server, {}).get("vaspkit_exe") or "").strip()
    return configured or _VASPKIT_DEFAULT


def has_local(project_name: str, task: Dict[str, Any]) -> bool:
    path = data_path(project_name, task)
    return path.is_file() and path.stat().st_size > 0


# ------------------------------------------------------------------ 解析


def parse_planar_average(text: str) -> List[Tuple[float, float]]:
    """解析 `PLANAR_AVERAGE.dat`：`#Distance(A) Planar-Average-Potential(eV)` + 两列数值。"""
    points: List[Tuple[float, float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            z, value = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        points.append((z, value))
    return points


def _plateau(points: List[Tuple[float, float]]) -> Optional[Dict[str, Any]]:
    """估真空能级：**两端各取一段窗口，挑更平的一侧**取平均（slab 通常只在一端）。

    为什么不用"最高电位"：不同体系里真空平台不一定是最高的；平坦度才是真空的特征。
    VASPKIT 自己的汇总也会给真空能级，两者交叉校验（差 > 0.05 eV 给 warning）。
    """
    if len(points) < 20:
        return None
    z0 = points[0][0]
    z1 = points[-1][0]
    span = z1 - z0
    if span <= 0:
        return None
    width = span * PLATEAU_FRACTION

    def window(side: str) -> Optional[Dict[str, Any]]:
        picked = (
            [(z, v) for z, v in points if z <= z0 + width]
            if side == "start"
            else [(z, v) for z, v in points if z >= z1 - width]
        )
        if len(picked) < 5:
            return None
        values = [v for _, v in picked]
        mean = sum(values) / len(values)
        spread = max(values) - min(values)
        return {
            "side": side,
            "start": picked[0][0],
            "end": picked[-1][0],
            "value": mean,
            "points": len(picked),
            "spread": spread,
        }

    candidates = [w for w in (window("start"), window("end")) if w]
    if not candidates:
        return None
    return min(candidates, key=lambda w: w["spread"])


def parse_vaspkit_summary(text: str) -> Dict[str, Optional[float]]:
    """从 VASPKIT 的 stdout 里抠 `Vacuum-Level (eV)` / `Work Function (eV)`（可能没有）。"""
    out: Dict[str, Optional[float]] = {"vacuum_level": None, "work_function": None}
    vacuum = re.search(r"Vacuum[-\s]?[Ll]evel\s*\(eV\)\s*:\s*([-+\d.]+)", text)
    work = re.search(r"Work\s+Function\s*\(eV\)\s*:\s*([-+\d.]+)", text)
    if vacuum:
        try:
            out["vacuum_level"] = float(vacuum.group(1))
        except ValueError:
            pass
    if work:
        try:
            out["work_function"] = float(work.group(1))
        except ValueError:
            pass
    return out


def parse_fermi(text: str) -> Optional[float]:
    """从 OUTCAR 里读 `E-fermi :  -0.9138`（功函数 = 真空能级 − E_F）。"""
    m = re.search(r"E-fermi\s*:\s*(-?\d+\.?\d*)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_incar_dipole(text: str) -> Dict[str, Any]:
    """读 INCAR 的 `LDIPOL` / `IDIPOL`（判断所选方向有没有开偶极矫正）。"""
    result: Dict[str, Any] = {"ldipol": None, "idipol": None}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(LDIPOL|IDIPOL)\s*=\s*(\S+)", line, re.IGNORECASE)
        if not m:
            continue
        key = m.group(1).upper()
        # VASP 布尔写法很多：`.TRUE.` / `T` / `.T.` / `1` —— 统一去掉两侧的点再判
        value = m.group(2).strip().strip(".").upper()
        if key == "LDIPOL":
            result["ldipol"] = value in ("T", "TRUE", "1", "YES", "ON")
        else:
            try:
                result["idipol"] = int(float(value))
            except ValueError:
                result["idipol"] = None
    return result


def dipole_check(dipole: Dict[str, Any], axis: str) -> Dict[str, Any]:
    """所选方向是否开了偶极矫正：`LDIPOL=.TRUE.` 且 `IDIPOL` 覆盖该方向（4 = 全方向）。"""
    expect = AXIS_TO_IDIPOL.get(axis)
    ldipol = dipole.get("ldipol")
    idipol = dipole.get("idipol")
    label = AXIS_LABELS.get(axis, axis)
    if ldipol is None and idipol is None:
        return {
            "ok": False,
            "reason": "INCAR 里没读到 LDIPOL / IDIPOL（无法确认是否开了偶极矫正）",
        }
    if not ldipol:
        return {"ok": False, "reason": "INCAR 里 LDIPOL 不是 .TRUE.（没开偶极矫正）"}
    if idipol not in (expect, 4):
        return {
            "ok": False,
            "reason": (
                f"偶极矫正方向与所选方向不匹配：IDIPOL={idipol}，"
                f"而 {label} 需要 IDIPOL={expect}（或 4=全方向）"
            ),
        }
    return {"ok": True, "reason": f"LDIPOL=.TRUE. 且 IDIPOL={idipol} 覆盖 {label}"}


# ------------------------------------------------------------------ 远端探测


def _remote_script(remote_dir: str, axis: str, exe: str, *, run: bool) -> str:
    cartesian = AXIS_TO_CARTESIAN.get(axis, "z")
    lines = [
        f'cd "{remote_dir}" 2>/dev/null || {{ echo "@@@NODIR"; exit 3; }}',
        'echo "@@@FILES"',
        f'for f in {LOCPOT_NAME} {OUTCAR_NAME} {DOSCAR_NAME}; do',
        '  if [ -s "$f" ]; then echo "T $f $(stat -c %s "$f" | tr -d \' \')"; '
        'else echo "T $f 0"; fi',
        "done",
        'echo "@@@VASPKIT"',
        f'(command -v "{exe}" >/dev/null 2>&1 || [ -x "{exe}" ]) '
        '&& echo "V ok" || echo "V missing"',
        'echo "@@@INCAR"',
        f'grep -E \'^ *(LDIPOL|IDIPOL|LVHAR|LVTOT)\' {INCAR_NAME} 2>/dev/null | head -n 8',
        'echo "@@@FERMI"',
        f'grep -m1 "E-fermi" {OUTCAR_NAME} 2>/dev/null',
    ]
    if not run:
        lines.append('echo "@@@END"')
        return "\n".join(lines)
    lines += [
        'echo "@@@RUN"',
        "W=$(mktemp -d /tmp/wf_run.XXXXXX) || { echo '@@@NOTMP'; exit 5; }",
        'ln -sf "$PWD/LOCPOT" "$PWD/OUTCAR" "$W"/ 2>/dev/null',
        '[ -s POSCAR ] && ln -sf "$PWD/POSCAR" "$W"/POSCAR',
        '[ -s INCAR ] && ln -sf "$PWD/INCAR" "$W"/INCAR',
        '[ -s DOSCAR ] && ln -sf "$PWD/DOSCAR" "$W"/DOSCAR',
        'cd "$W"',
        # VASPKIT 在缺 DOSCAR 时会在写完 .dat 之后报错退出码仍为 0 → 这里只看 .dat 有没有出来
        f'"{exe}" -task 426 -dir {cartesian} > wf.log 2>&1 || true',
        f'if [ ! -s "{RESULT_NAME}" ]; then echo "@@@NODAT"; tail -n 20 wf.log; '
        'rm -rf "$W"; exit 6; fi',
        'echo "@@@SUMMARY"',
        'grep -E "Vacuum[ -]?Level|Work Function" wf.log | head -n 4',
        'echo "@@@DAT"',
        f'base64 "{RESULT_NAME}" | tr -d \'\\n\'',
        'echo',
        'cd /; rm -rf "$W"',
        'echo "@@@END"',
    ]
    return "\n".join(lines)


def _split_sections(raw: str) -> Dict[str, str]:
    """把带 `@@@XXX` 标记的输出切成段。"""
    sections: Dict[str, str] = {}
    current = "_head"
    buf: List[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if text.startswith("@@@") and text[3:] and re.fullmatch(r"@@@[A-Z_]+", text):
            sections[current] = "\n".join(buf)
            current = text[3:]
            buf = []
            continue
        buf.append(line)
    sections[current] = "\n".join(buf)
    return sections


def probe_remote(
    project: Dict[str, Any], task: Dict[str, Any], *, refresh: bool = False
) -> Dict[str, Any]:
    """远端探测（一次 exec）：LOCPOT/OUTCAR/DOSCAR 大小、vaspkit 是否可用、INCAR 偶极设置、E_F。"""
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        cached = _PROBE_CACHE.get(task_id)
        if cached and not refresh and time.time() - cached[0] < PROBE_TTL_SECONDS:
            return cached[1]

    server = str(project.get("server") or "")
    remote_dir = task_remote_dir(server, task).rstrip("/")
    result: Dict[str, Any] = {
        "remote_dir": remote_dir,
        "checked_at": now_iso(),
        "ok": False,
        "state": "unknown",
        "reason": "",
        "sizes": {},
        "has_vaspkit": False,
        "dipole": {},
        "fermi": None,
        "vaspkit_exe": vaspkit_exe(server),
    }
    if not remote_dir:
        result["reason"] = "任务缺少远程目录"
        return result
    encoded = base64.b64encode(
        _remote_script(remote_dir, "c", result["vaspkit_exe"], run=False).encode("utf-8")
    ).decode("ascii")
    try:
        run = ssh.run_remote(server, f"echo {encoded} | base64 -d | bash", timeout=180)
    except Exception as e:  # noqa: BLE001
        result["reason"] = f"远端探测失败：{type(e).__name__}: {e}"
        return result
    raw = f"{run.get('stdout', '')}\n{run.get('stderr', '')}".strip()
    if "@@@NODIR" in raw:
        result["reason"] = f"远端任务目录不存在：{remote_dir}"
        return result
    sections = _split_sections(raw)

    sizes: Dict[str, int] = {}
    for line in (sections.get("FILES") or "").splitlines():
        parts = line.strip().split()
        if len(parts) == 3 and parts[0] == "T" and parts[2].isdigit():
            sizes[parts[1]] = int(parts[2])
    result["sizes"] = sizes
    result["has_vaspkit"] = "ok" in (sections.get("VASPKIT") or "")
    result["dipole"] = parse_incar_dipole(sections.get("INCAR") or "")
    result["fermi"] = parse_fermi(sections.get("FERMI") or "")

    locpot = sizes.get(LOCPOT_NAME, 0)
    outcar = sizes.get(OUTCAR_NAME, 0)
    if locpot <= 0:
        result.update({
            "state": "no_locpot",
            "reason": "远端没有 LOCPOT（或为空）：需要 INCAR 里 LVHAR=.TRUE. 后重算一轮",
        })
    elif outcar <= 0:
        result.update({"state": "no_outcar", "reason": "远端没有 OUTCAR（或为空）"})
    elif not result["has_vaspkit"]:
        result.update({
            "state": "no_vaspkit",
            "reason": f"远端找不到 vaspkit：{result['vaspkit_exe']}（可用 servers.json: vaspkit_exe 覆盖）",
        })
    else:
        result.update({"ok": True, "state": "ready", "reason": "可计算（远端 LOCPOT/OUTCAR 齐备）"})
    with _LOCK:
        _PROBE_CACHE[task_id] = (time.time(), result)
    return result


# ------------------------------------------------------------------ 状态/结果


def local_status(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    path = data_path(project_name, task)
    has = path.is_file() and path.stat().st_size > 0
    meta = read_meta(project_name, task)
    # 归档大文件回传状态（v0.9.74）：LOCPOT 本地有没有 / ACF.dat 有没有 / 最近一次回传记录
    try:
        import archive_files

        files = archive_files.status(project_name, task)
    except Exception:  # noqa: BLE001 - 状态读不到不影响功函数本身
        files = {}
    return {
        "has_result": has,
        "data_path": str(path) if has else "",
        "bytes": path.stat().st_size if has else 0,
        "mtime": int(path.stat().st_mtime) if has else 0,
        "axis": (meta.get("result") or {}).get("axis"),
        "meta": meta,
        "files": files,
    }


def status(
    project_name: str,
    task: Dict[str, Any],
    run_id: str = "",
    *,
    remote: bool = False,
    project: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    local = local_status(project_name, task)
    with _LOCK:
        rid = run_id or _TASK_RUN.get(task_id, "")
        if not rid:
            latest = [r for r in _RUNS.values() if r.get("task_id") == task_id]
            rid = latest[-1]["run_id"] if latest else ""
        run = dict(_RUNS.get(rid) or {})
    meta = local.get("meta") or {}
    if not run:
        run = {
            "run_id": rid,
            "status": "failed" if meta.get("status") == "failed" else (
                "done" if local["has_result"] else "idle"
            ),
            "error": meta.get("error"),
            "stage": meta.get("stage"),
            "finished_at": meta.get("finished_at"),
        }
    run["stage_label"] = STAGE_LABELS.get(str(run.get("stage") or ""), "")
    run["local"] = {k: v for k, v in local.items() if k != "meta"}
    run["meta"] = meta
    if remote and project is not None:
        run["remote"] = probe_remote(project, task)
    return run


def load_data(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """本地结果（曲线 + 真空能级 + 功函数）；没算过抛 404。纯本地，不连远端。"""
    path = data_path(project_name, task)
    if not (path.is_file() and path.stat().st_size > 0):
        raise WorkFunctionError("本地还没有功函数结果（先在「电子结构分析 → 功函数」里点计算）", 404)
    points = parse_planar_average(path.read_text(encoding="utf-8", errors="replace"))
    if not points:
        raise WorkFunctionError("本地 PLANAR_AVERAGE.dat 解析不出数据点", 500)
    meta = read_meta(project_name, task)
    result = dict(meta.get("result") or {})
    result.update(
        {
            "z": [round(z, 6) for z, _ in points],
            "potential": [round(v, 6) for _, v in points],
            "source": to_local_rel(str(path)),
            "bytes": path.stat().st_size,
            "mtime": int(path.stat().st_mtime),
        }
    )
    return result


# ------------------------------------------------------------------ 异步链路


def start(project: Dict[str, Any], task: Dict[str, Any], *, axis: str = "c") -> Dict[str, Any]:
    axis = str(axis or "c").lower()
    if axis not in AXIS_TO_CARTESIAN:
        raise WorkFunctionError("方向只能是 a / b / c", 400)
    if not task_remote_dir(str(project.get("server") or ""), task):
        raise WorkFunctionError("任务缺少远程目录", 400)
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        current = _TASK_RUN.get(task_id)
        if current and _RUNS.get(current, {}).get("status") == "running":
            return {"run_id": current, "status": "running", "reused": True}
        run_id = f"wf_{int(time.time() * 1000)}"
        _RUNS[run_id] = {
            "run_id": run_id,
            "task_id": task_id,
            "status": "running",
            "stage": "checking",
            "axis": axis,
            "started_at": now_iso(),
        }
        _TASK_RUN[task_id] = run_id
    threading.Thread(
        target=_background,
        args=(dict(project), dict(task), run_id, axis),
        name=f"work-function-{task_id}",
        daemon=True,
    ).start()
    return {"run_id": run_id, "status": "running", "reused": False}


def _set_stage(run_id: str, stage: str, **extra: Any) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update({"stage": stage, **extra})


def _record_task_work_function(
    project_name: str, task_id: str, payload: Optional[Dict[str, Any]]
) -> None:
    """把结果记到 ele 主任务 `task["work_function"]`（巡检详情 / 报告以后读）。"""
    try:
        with db_transaction() as db:
            proj = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = (
                next((t for t in proj.get("tasks", []) if t.get("task_id") == task_id), None)
                if proj
                else None
            )
            if task is not None:
                if payload is None:
                    task.pop("work_function", None)
                else:
                    task["work_function"] = {**payload, "synced_at": now_iso()}
    except Exception as e:  # noqa: BLE001
        _log_line(f"[warn] 写回 work_function 台账失败（{project_name}/{task_id}）：{e}")


def _fail(
    project_name: str, task: Dict[str, Any], run_id: str, stage: str, message: str, started: str
) -> None:
    meta = read_meta(project_name, task)
    meta.update(
        {
            "task_id": str(task.get("task_id") or ""),
            "project_name": project_name,
            "run_id": run_id,
            "status": "failed",
            "stage": stage,
            "error": message,
            "started_at": started,
            "finished_at": now_iso(),
        }
    )
    try:
        _write_json(meta_path(project_name, task), meta)
    except Exception as e:  # noqa: BLE001
        _log_line(f"[warn] 写 meta 失败：{e}")
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update(
                {
                    "status": "failed",
                    "stage": stage,
                    "error": message,
                    "finished_at": meta["finished_at"],
                }
            )
    _log_line(f"[fail] {project_name}/{task.get('task_id')} stage={stage} {message}")


def _background(
    project: Dict[str, Any], task: Dict[str, Any], run_id: str, axis: str
) -> None:
    """后台线程：检查 → VASPKIT 426 → 解析（真空能级/功函数）→ 落盘/台账。"""
    project_name = str(project.get("name") or "")
    server = str(project.get("server") or "")
    task_id = str(task.get("task_id") or "")
    started = now_iso()
    t0 = time.time()
    stage = "checking"
    try:
        remote_dir = task_remote_dir(server, task).rstrip("/")
        if not remote_dir:
            raise WorkFunctionError("任务缺少远程目录", 400)
        _set_stage(run_id, "checking")
        probe = probe_remote(project, task, refresh=True)
        if not probe.get("ok"):
            raise WorkFunctionError(f"远端检查未通过：{probe.get('reason') or '未知原因'}", 400)

        dipole = dipole_check(probe.get("dipole") or {}, axis)
        warnings: List[str] = []
        if not dipole.get("ok"):
            warnings.append(
                f"所选方向没开偶极矫正（{dipole.get('reason')}）：结果可能不可靠，仅作参考"
            )

        stage = "extracting"
        _set_stage(run_id, "extracting")
        encoded = base64.b64encode(
            _remote_script(remote_dir, axis, vaspkit_exe(server), run=True).encode("utf-8")
        ).decode("ascii")
        # VASPKIT 解析 200MB 级 LOCPOT + 写 .dat：默认几分钟够用；走专用连接不占常驻池锁
        run = ssh.run_remote(
            server, f"echo {encoded} | base64 -d | bash", timeout=1800, dedicated=True
        )
        raw = f"{run.get('stdout', '')}\n{run.get('stderr', '')}".strip()
        if int(run.get("exit_code") or 0) != 0 and "@@@END" not in raw:
            tail = " / ".join(line.strip() for line in raw.splitlines() if line.strip())[-400:]
            raise WorkFunctionError(f"远端 VASPKIT 执行失败：{tail or '没有输出'}", 502)
        if "@@@NOTMP" in raw:
            raise WorkFunctionError("远端无法创建临时目录（/tmp 不可写？）", 502)
        if "@@@NODAT" in raw:
            tail = " / ".join(line.strip() for line in raw.splitlines() if line.strip())[-400:]
            raise WorkFunctionError(
                f"VASPKIT 426 没写出 PLANAR_AVERAGE.dat：{tail or '没有输出'}", 502
            )
        sections = _split_sections(raw)
        summary = parse_vaspkit_summary(sections.get("SUMMARY") or "")
        fermi = parse_fermi(sections.get("FERMI") or "") or probe.get("fermi")
        dat_b64 = re.sub(r"\s+", "", sections.get("DAT") or "")
        if not dat_b64:
            raise WorkFunctionError("远端没有回传 PLANAR_AVERAGE.dat 内容", 502)
        try:
            dat_text = base64.b64decode(dat_b64).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            raise WorkFunctionError(f"PLANAR_AVERAGE.dat 回传内容解析失败：{e}", 502) from None
        points = parse_planar_average(dat_text)
        if len(points) < 20:
            raise WorkFunctionError(f"平面平均电位点数太少（{len(points)}）：数据可能不完整", 502)

        stage = "parsing"
        _set_stage(run_id, "parsing")
        plateau = _plateau(points)
        local_vacuum = (plateau or {}).get("value")
        vacuum_vaspkit = summary.get("vacuum_level")
        # **优先用 VASPKIT 的汇总值**（它就是用户要的口径；本地平台估计只做兜底与交叉校验）。
        # 本地估值用"两端各取 12%、挑更平一侧取平均"——真空平台不够平就会偏（实测 model1
        # 平台波动 1.74 eV，估出 4.031 而 VASPKIT 给 4.234），所以只在没有汇总时才用它。
        if vacuum_vaspkit is not None:
            vacuum = float(vacuum_vaspkit)
            vacuum_source = "vaspkit"
            if local_vacuum is not None and abs(local_vacuum - vacuum) > 0.05:
                spread = float((plateau or {}).get("spread") or 0.0)
                warnings.append(
                    f"本地从电位平台估的真空能级 {local_vacuum:.3f} eV 与 VASPKIT 的 "
                    f"{vacuum:.3f} eV 差 {abs(local_vacuum - vacuum):.3f} eV"
                    f"（平台波动 {spread:.2f} eV）：真空可能不够厚/没收敛，"
                    "以 VASPKIT 值为准但建议核对"
                )
        elif local_vacuum is not None:
            vacuum = float(local_vacuum)
            vacuum_source = "local"
            spread = float((plateau or {}).get("spread") or 0.0)
            warnings.append(
                f"没有 DOSCAR，VASPKIT 没给汇总：真空能级是本地从电位平台估的"
                f"（平台波动 {spread:.2f} eV），注意核对"
            )
        else:
            raise WorkFunctionError("无法估出真空能级（曲线太短或全在变化）", 500)
        if fermi is None:
            warnings.append("OUTCAR 里没读到 E-fermi：功函数（= 真空能级 − E_F）无法给出")
            work_function = None
        else:
            work_function = vacuum - fermi
            if summary.get("work_function") is not None and abs(
                summary["work_function"] - work_function
            ) > 0.05:
                warnings.append(
                    f"本地算的功函数 {work_function:.3f} eV 与 VASPKIT 汇总的 "
                    f"{summary['work_function']:.3f} eV 不一致，注意核对"
                )

        target = data_path(project_name, task)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dat_text, encoding="utf-8")

        payload = {
            "ok": True,
            "axis": axis,
            "axis_cartesian": AXIS_TO_CARTESIAN.get(axis),
            "efermi": fermi,
            "vacuum_level": round(vacuum, 4),
            "vacuum_level_vaspkit": summary.get("vacuum_level"),
            "vacuum_level_local": round(local_vacuum, 4) if local_vacuum is not None else None,
            "vacuum_level_source": vacuum_source,
            "work_function": round(work_function, 4) if work_function is not None else None,
            "work_function_vaspkit": summary.get("work_function"),
            "plateau": plateau,
            "points": len(points),
            "dipole": {**dipole, "ldipol": (probe.get("dipole") or {}).get("ldipol"),
                       "idipol": (probe.get("dipole") or {}).get("idipol")},
            "warnings": warnings,
            "local_path": to_local_rel(str(target)),
            "bytes": target.stat().st_size,
            "locpot_bytes": (probe.get("sizes") or {}).get(LOCPOT_NAME, 0),
            "elapsed_seconds": round(time.time() - t0, 1),
            "vaspkit_exe": vaspkit_exe(server),
        }
        meta = {
            "task_id": task_id,
            "project_name": project_name,
            "run_id": run_id,
            "status": "done",
            "stage": "done",
            "started_at": started,
            "finished_at": now_iso(),
            "elapsed_seconds": payload["elapsed_seconds"],
            "remote": {
                "state": probe.get("state"),
                "reason": probe.get("reason"),
                "remote_dir": remote_dir,
            },
            "result": payload,
        }
        _write_json(meta_path(project_name, task), meta)
        _record_task_work_function(project_name, task_id, payload)
        with _LOCK:
            run_state = _RUNS.get(run_id)
            if run_state is not None:
                run_state.update(
                    {
                        "status": "done",
                        "stage": "done",
                        "finished_at": meta["finished_at"],
                        "elapsed_seconds": payload["elapsed_seconds"],
                        "result": payload,
                    }
                )
        _log_line(
            f"[ok] {project_name}/{task_id} axis={axis} WF={payload['work_function']} "
            f"vacuum={payload['vacuum_level']} E_F={fermi} elapsed={payload['elapsed_seconds']}s"
            f"{' warnings=' + str(len(warnings)) if warnings else ''}"
        )
    except WorkFunctionError as exc:
        _fail(project_name, task, run_id, stage, str(exc), started)
    except Exception as exc:  # noqa: BLE001 - 线程里不能抛
        _fail(project_name, task, run_id, stage, f"{type(exc).__name__}: {exc}", started)
    finally:
        with _LOCK:
            if _TASK_RUN.get(task_id) == run_id:
                _TASK_RUN.pop(task_id, None)


def clear(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """清除本地功函数结果（PLANAR_AVERAGE.dat + meta），远端文件不动。"""
    removed: List[str] = []
    for path, label in (
        (data_path(project_name, task), RESULT_NAME),
        (meta_path(project_name, task), META_JSON),
    ):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(label)
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        _PROBE_CACHE.pop(task_id, None)
        rid = _TASK_RUN.pop(task_id, "")
        if rid:
            _RUNS.pop(rid, None)
    _record_task_work_function(project_name, task_id, None)
    return {"removed": removed, "dir": str(local_dir(project_name, task))}
