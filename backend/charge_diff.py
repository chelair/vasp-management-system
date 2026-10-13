"""差分电荷链路（2026-10-14 重做）：入口从「归档」搬到**巡检详情**。

用户口径（2026-10-14）：

- 入口在巡检详情的「电子结构分析 → 差分电荷」标签，**不再挂在归档上**；
- 第一次点击依次做四件事：
  ① 远端校验文件完整性（完整结构 `CHGCAR` + 各分块 `N/CHGCAR`，大小差别应 **< 1%**）；
  ② 远端 VTST 算差分（`chgsum.pl` + `chgdiff.pl`）→ `CHGCAR_diff`；
  ③ 回传 `CHGCAR_diff` 到本地；
  ④ 导入 VESTA 导出 a/b/c 三轴图，图片直接呈现在前端详情页。
- 之后每次加载按**阶梯**取值，尽量不打扰远端：
  本地图 → 本地差分文件 → 远端差分文件 → 远端可算；
- 大文件（200MB+）+ VESTA 加载慢：全链路异步 + 阶段上报 + **中断补偿**
  （远端算好就只补回传、本地有文件就只补出图），并且**全局串行**只跑一条链路
  + VESTA 跨进程串行锁，避免拖卡生产机（用户明确要求）。

本地产物（都在 `<ele 任务目录>/diffcharge_files/` 下）：

    chgfiles/CHGCAR_diff.vasp   远端回传的差分电荷（VESTA 能直接开）
    images/chgdiff_{a,b,c}.png  VESTA 导出的三轴图
    meta.json                   最近一次链路运行的状态（跨重启保留失败原因）

异步模型与 `pdos.py` 一致：`start()` 起后台线程返回 `run_id`，`status()` 轮询，
同一任务已有 run 在跑时复用（重复点击不会并发跑两遍）。
"""

from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from dates import now_iso
from ele_diff import (
    CHG_DIFF_NAME,
    CHG_DIR,
    CHG_SUM_NAME,
    IMAGES_DIR,
    LOCAL_CHG_DIFF_NAME,
    DiffChargeError,
    diff_charge_blocks,
    diff_charge_root_local,
    download_charge_diff,
    run_vtst_chgdiff,
    vtst_dir,
)
from storage import db_transaction
from task_paths import task_remote_dir

#: 三个 CHGCAR（完整结构 + 各分块）大小差别阈值：用户口径 **< 1%**
SIZE_TOLERANCE = 0.01
#: 图片文件名（`<image_dir>/<IMAGE_LABEL>_{a,b,c}.png`）
IMAGE_LABEL = "chgdiff"
IMAGE_AXES: Tuple[str, ...] = ("a", "b", "c")
#: 本地元数据文件名
META_JSON = "meta.json"
#: 本地状态（阶梯取值）
STATE_IMAGES = "images"  # 本地已有三视图
STATE_LOCAL_DIFF = "local_diff"  # 本地已有 CHGCAR_diff（可直接出图）
STATE_REMOTE_DIFF = "remote_diff"  # 远端已有 CHGCAR_diff（只需回传）
STATE_REMOTE_READY = "remote_ready"  # 远端分块齐全且完整，可以算
STATE_REMOTE_INCOMPLETE = "remote_incomplete"  # 远端文件缺失/大小不一致
STATE_NO_BLOCKS = "no_blocks"  # 还没划差分电荷分块

#: 阶段名 → 前端展示文案
STAGE_LABELS = {
    "checking": "远端校验文件完整性",
    "computing": "远端 VTST 计算差分电荷（chgsum.pl + chgdiff.pl）",
    "downloading": "回传 CHGCAR_diff",
    "rendering": "VESTA 导入并导出 a/b/c 三轴图",
    "done": "已完成",
}

#: run 状态（进程内）：run_id → {...}
_RUNS: Dict[str, Dict[str, Any]] = {}
#: 任务当前 run：task_id → run_id
_TASK_RUN: Dict[str, str] = {}
#: 全局串行：差分电荷链路一次只跑一条（每条要移动 200MB+ 并起 VESTA）
_JOB_LOCK = threading.Lock()
#: 远端探测缓存：task_id → (时间戳, 探测结果)
_PROBE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PROBE_TTL_SECONDS = 120.0
_LOCK = threading.Lock()

_LOG = Path(__file__).resolve().parent.parent / "data" / "charge_diff.log"


class ChargeDiffError(RuntimeError):
    """链路错误：`status` = 建议的 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _log_line(message: str) -> None:
    """链路日志（跨重启排查用，失败不影响主流程）。"""
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


# ------------------------------------------------------------------ 本地路径


def root_dir(project_name: str, task: Dict[str, Any]) -> Path:
    return diff_charge_root_local(project_name, task)


def diff_path(project_name: str, task: Dict[str, Any]) -> Path:
    """本地差分文件：`diffcharge_files/chgfiles/CHGCAR_diff.vasp`。"""
    return root_dir(project_name, task) / CHG_DIR / LOCAL_CHG_DIFF_NAME


def image_dir(project_name: str, task: Dict[str, Any]) -> Path:
    return root_dir(project_name, task) / IMAGES_DIR


def image_paths(project_name: str, task: Dict[str, Any]) -> Dict[str, Path]:
    return {
        axis: image_dir(project_name, task) / f"{IMAGE_LABEL}_{axis}.png"
        for axis in IMAGE_AXES
    }


def meta_path(project_name: str, task: Dict[str, Any]) -> Path:
    return root_dir(project_name, task) / META_JSON


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


def _png_ready(path: Path) -> bool:
    """PNG 完整（有 IEND）才算数 —— 与结构图同一判据（渲染被杀会留截断图）。"""
    try:
        from vesta_render import _output_ready

        return path.is_file() and path.stat().st_size > 0 and _output_ready(path)
    except Exception:  # noqa: BLE001 - 判据失败按"没图"处理
        return False


def local_images(project_name: str, task: Dict[str, Any]) -> Dict[str, Path]:
    """本地**已完整**的三视图（缺一轴就返回缺的那个，调用方自己看数量）。"""
    return {
        axis: path
        for axis, path in image_paths(project_name, task).items()
        if _png_ready(path)
    }


def local_status(
    project_name: str, task: Dict[str, Any], *, block_count: Optional[int] = None
) -> Dict[str, Any]:
    """**只看本地**（零 SSH，详情页可以随便调）：阶梯取值的结果。"""
    images = local_images(project_name, task)
    path = diff_path(project_name, task)
    has_diff = path.is_file() and path.stat().st_size > 0
    if len(images) == len(IMAGE_AXES):
        state = STATE_IMAGES
    elif has_diff:
        state = STATE_LOCAL_DIFF
    else:
        state = ""
    return {
        "state": state,
        "has_images": len(images) == len(IMAGE_AXES),
        "has_partial_images": bool(images) and len(images) != len(IMAGE_AXES),
        "image_axes": sorted(images),
        "has_diff": has_diff,
        "diff_path": str(path) if has_diff else "",
        "diff_bytes": path.stat().st_size if has_diff else 0,
        "diff_mtime": int(path.stat().st_mtime) if has_diff else 0,
        "image_mtime": int(max((p.stat().st_mtime for p in images.values()), default=0)),
        "blocks": int(block_count) if block_count is not None else None,
        "meta": read_meta(project_name, task),
    }


# ------------------------------------------------------------------ 远端探测


def _remote_script(ele_remote: str, block_indexes: List[int], script_dir: str) -> str:
    """一段 bash：列出各 CHGCAR 的字节数 + VTST 脚本是否可执行。"""
    idx = " ".join(str(int(i)) for i in block_indexes)
    return "\n".join(
        [
            f'cd "{ele_remote}" 2>/dev/null || {{ echo "@@@NODIR"; exit 3; }}',
            'echo "@@@FILES"',
            "for f in CHGCAR CHGCAR_diff CHGCAR_sum; do",
            '  [ -e "$f" ] && echo "T $f $(wc -c < "$f" | tr -d \' \')"',
            "done",
            f"for i in {idx}; do",
            '  [ -e "$i/CHGCAR" ] && echo "T $i/CHGCAR $(wc -c < "$i/CHGCAR" | tr -d \' \')"',
            "done",
            'echo "@@@VTST"',
            f'VTST="{script_dir}"',
            "for f in chgsum.pl chgdiff.pl; do",
            '  if [ -x "$VTST/$f" ]; then echo "V $f ok"; else echo "V $f missing"; fi',
            "done",
            'echo "@@@END"',
        ]
    )


def _parse_probe(raw: str) -> Dict[str, Any]:
    sizes: Dict[str, int] = {}
    vtst: Dict[str, bool] = {}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("T "):
            parts = line[2:].split(" ", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                sizes[parts[0]] = int(parts[1].strip())
        elif line.startswith("V "):
            parts = line[2:].split(" ", 1)
            if len(parts) == 2:
                vtst[parts[0]] = parts[1].strip() == "ok"
    return {"sizes": sizes, "vtst": vtst}


def _integrity(sizes: Dict[str, int], block_indexes: List[int]) -> Dict[str, Any]:
    """完整性：完整结构 + 各分块 CHGCAR 都要在，且大小差别 < `SIZE_TOLERANCE`。

    为什么能这样判：分块只改原子（晶胞不变），VASP 的 FFT 网格一样 → CHGCAR 体积应当
    几乎一致（2026-10-14 用户口径：三个文件大小差别应 < 1%）。差得多说明某一块没算完 / 截断。
    """
    wanted = ["CHGCAR", *[f"{int(i)}/CHGCAR" for i in block_indexes]]
    missing = [name for name in wanted if not sizes.get(name)]
    values = [sizes[name] for name in wanted if sizes.get(name)]
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "max": max(values) if values else 0,
            "min": min(values) if values else 0,
            "spread": None,
            "reason": "远端缺少 " + "、".join(missing) + "（或大小为 0）",
        }
    hi, lo = max(values), min(values)
    spread = (hi - lo) / hi if hi else 0.0
    if spread > SIZE_TOLERANCE:
        return {
            "ok": False,
            "missing": [],
            "max": hi,
            "min": lo,
            "spread": round(spread, 4),
            "reason": (
                f"各 CHGCAR 大小差别 {spread * 100:.1f}%（{lo} B ~ {hi} B）"
                f"，超过 {SIZE_TOLERANCE * 100:.0f}% 阈值：可能有分块没算完或文件被截断"
            ),
        }
    return {
        "ok": True,
        "missing": [],
        "max": hi,
        "min": lo,
        "spread": round(spread, 4),
        "reason": f"各 CHGCAR 大小一致（差别 {spread * 100:.2f}%）",
    }


def probe_remote(
    project: Dict[str, Any], task: Dict[str, Any], *, refresh: bool = False
) -> Dict[str, Any]:
    """远端探测（一次 exec，约 0.5–1.5s）：差分类文件在不在 + 分块完整性 + VTST 是否就绪。

    带 120s 缓存（与 `/available-analyses` 同口径），避免前端反复拉详情就反复连远端。
    """
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        cached = _PROBE_CACHE.get(task_id)
        if cached and not refresh and time.time() - cached[0] < PROBE_TTL_SECONDS:
            return cached[1]

    server = str(project.get("server") or "")
    ele_remote = task_remote_dir(server, task).rstrip("/")
    blocks = diff_charge_blocks(project, task)
    result: Dict[str, Any] = {
        "remote_dir": ele_remote,
        "block_count": len(blocks),
        "checked_at": now_iso(),
        "has_diff": False,
        "has_sum": False,
        "integrity": None,
        "vtst": {},
        "state": STATE_NO_BLOCKS,
        "ok": False,
    }
    if not ele_remote:
        result["reason"] = "任务缺少远程目录"
        return result
    if not blocks:
        result["reason"] = "该任务还没有差分电荷分块（先在作业管理里划块创建）"
        result["integrity"] = _integrity({}, [])
        return result

    indexes = [int(b.get("ele_block") or 0) for b in blocks]
    script = _remote_script(ele_remote, indexes, vtst_dir(server))
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    try:
        run = ssh.run_remote(server, f"echo {encoded} | base64 -d | bash", timeout=180)
    except Exception as e:  # noqa: BLE001 - 远端不可达
        result["reason"] = f"远端探测失败：{type(e).__name__}: {e}"
        return result
    raw = f"{run.get('stdout', '')}\n{run.get('stderr', '')}".strip()
    if "@@@NODIR" in raw:
        result["reason"] = f"远端任务目录不存在：{ele_remote}"
        return result
    parsed = _parse_probe(raw)
    sizes = parsed["sizes"]
    result["has_diff"] = bool(sizes.get(CHG_DIFF_NAME))
    result["has_sum"] = bool(sizes.get(CHG_SUM_NAME))
    result["integrity"] = _integrity(sizes, indexes)
    result["vtst"] = {
        "dir": vtst_dir(server),
        "ready": all(parsed["vtst"].values()) if parsed["vtst"] else False,
        "scripts": parsed["vtst"],
    }
    if result["has_diff"]:
        result["state"] = STATE_REMOTE_DIFF
        result["ok"] = True
        result["reason"] = "远端已有 CHGCAR_diff（可直接回传，不必重算）"
    elif result["integrity"]["ok"] and result["vtst"]["ready"]:
        result["state"] = STATE_REMOTE_READY
        result["ok"] = True
        result["reason"] = "远端分块 CHGCAR 齐全且大小一致，可以计算"
    else:
        result["state"] = STATE_REMOTE_INCOMPLETE
        result["reason"] = result["integrity"]["reason"]
        if not result["vtst"]["ready"]:
            result["reason"] += "；远端 VTST 脚本不可用（chgsum.pl / chgdiff.pl）"
    with _LOCK:
        _PROBE_CACHE[task_id] = (time.time(), result)
    return result


# ------------------------------------------------------------------ 状态查询


def status(
    project_name: str,
    task: Dict[str, Any],
    run_id: str = "",
    *,
    remote: bool = False,
    project: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """链路状态：**本地**阶梯 + 当前/最近一次 run（`remote=True` 时附带远端探测）。"""
    task_id = str(task.get("task_id") or "")
    block_count = len(diff_charge_blocks(project, task)) if project else None
    local = local_status(project_name, task, block_count=block_count)
    with _LOCK:
        rid = run_id or _TASK_RUN.get(task_id, "")
        if not rid:
            latest = [r for r in _RUNS.values() if r.get("task_id") == task_id]
            rid = latest[-1]["run_id"] if latest else ""
        run = dict(_RUNS.get(rid) or {})
    meta = local.get("meta") or {}
    if not run:
        failed = meta.get("status") == "failed"
        run = {
            "run_id": rid,
            "status": "failed" if failed else ("done" if local["state"] else "idle"),
            "error": meta.get("error"),
            "stage": meta.get("stage"),
            "finished_at": meta.get("finished_at"),
        }
    run["stage_label"] = STAGE_LABELS.get(str(run.get("stage") or ""), "")
    run["local"] = {k: v for k, v in local.items() if k != "meta"}
    if not run.get("charge_diff"):
        run["charge_diff"] = (meta.get("charge_diff") or None)
    run["meta"] = meta
    if remote and project is not None:
        run["remote"] = probe_remote(project, task)
        if not local["state"]:
            run["state"] = run["remote"].get("state") or ""
    else:
        run["state"] = local["state"]
    return run


# ------------------------------------------------------------------ 异步链路


def start(
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """触发链路：已有在跑的 run 就复用，否则起后台线程。返回 run 信息。"""
    task_id = str(task.get("task_id") or "")
    blocks = diff_charge_blocks(project, task)
    if not blocks:
        raise ChargeDiffError("该任务还没有差分电荷分块（先在作业管理里划块创建）", 400)
    if not task_remote_dir(str(project.get("server") or ""), task):
        raise ChargeDiffError("任务缺少远程目录", 400)
    with _LOCK:
        current = _TASK_RUN.get(task_id)
        if current and _RUNS.get(current, {}).get("status") == "running":
            return {"run_id": current, "status": "running", "reused": True}
        run_id = f"chgdiff_{int(time.time() * 1000)}"
        _RUNS[run_id] = {
            "run_id": run_id,
            "task_id": task_id,
            "status": "running",
            "stage": "checking",
            "started_at": now_iso(),
            "elapsed_seconds": 0.0,
        }
        _TASK_RUN[task_id] = run_id
    threading.Thread(
        target=_background,
        args=(dict(project), dict(task), run_id, bool(force)),
        name=f"charge-diff-{task_id}",
        daemon=True,
    ).start()
    return {"run_id": run_id, "status": "running", "reused": False}


def _set_stage(run_id: str, stage: str, **extra: Any) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update({"stage": stage, **extra})


def _progress_cb_factory(run_id: str) -> Any:
    """下载进度回调：把已传/总字节写进 run 状态（前端轮询展示）。"""
    started = time.time()

    def _cb(done_bytes: int, total_bytes: int) -> None:
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is not None:
                run.update(
                    {
                        "bytes_done": int(done_bytes),
                        "bytes_total": int(total_bytes),
                        "bytes_elapsed_seconds": round(time.time() - started, 1),
                    }
                )

    return _cb


def _record_task_charge_diff(
    project_name: str, task_id: str, payload: Optional[Dict[str, Any]]
) -> None:
    """把结果写回 `task["charge_diff"]`（巡检详情 / 报告都读这个字段）。

    `payload=None` = 清除这个字段（重新计算前先把旧结果抹掉，避免界面显示过期数据）。
    """
    try:
        with db_transaction() as db:
            proj = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = (
                next(
                    (t for t in proj.get("tasks", []) if t.get("task_id") == task_id), None
                )
                if proj
                else None
            )
            if task is not None:
                if payload is None:
                    task.pop("charge_diff", None)
                else:
                    task["charge_diff"] = {**payload, "synced_at": now_iso()}
    except Exception as e:  # noqa: BLE001 - 记台账失败不影响链路结果
        _log_line(f"[warn] 写回 charge_diff 失败（{project_name}/{task_id}）：{e}")


def _fail(
    project_name: str,
    task: Dict[str, Any],
    run_id: str,
    stage: str,
    message: str,
    started: str,
) -> None:
    """失败：写 meta.json（保留上一次成功的字段）+ 记 run 状态 + 写回台账。"""
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
    except Exception as e:  # noqa: BLE001 - 写元数据失败不影响状态上报
        _log_line(f"[warn] 写 meta 失败：{e}")
    _record_task_charge_diff(
        project_name,
        str(task.get("task_id") or ""),
        {"ok": False, "error": message, "stage": stage},
    )
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
    project: Dict[str, Any], task: Dict[str, Any], run_id: str, force: bool
) -> None:
    """后台线程：校验 → （必要才）计算 → （必要才）回传 → 出图 → 写台账。

    每一步都先看"本地/远端是不是已经有了"：抬手中断（服务重启、网络断、用户关页面）
    之后再点一次只补缺的那部分，不重复搬 200MB、不重复跑 VTST。
    """
    project_name = str(project.get("name") or "")
    server = str(project.get("server") or "")
    task_id = str(task.get("task_id") or "")
    started = now_iso()
    t0 = time.time()
    stage = "checking"
    # 全局串行（一次只跑一条链路）：VESTA + 200MB 传输同时来两条最容易把机器拖卡
    with _JOB_LOCK:
        try:
            local = local_status(project_name, task)
            images_needed = force or not local["has_images"]
            diff_needed = force or not local["has_diff"]
            probe: Dict[str, Any] = {"state": STATE_LOCAL_DIFF}

            if images_needed and diff_needed:
                _set_stage(run_id, "checking")
                probe = probe_remote(project, task, refresh=True)
                if not probe.get("ok"):
                    raise ChargeDiffError(
                        f"远端文件校验未通过：{probe.get('reason') or '未知原因'}", 400
                    )
            else:
                # 本地已有差分文件（只缺图）→ 不必探测远端
                probe = {
                    "state": local["state"] or STATE_LOCAL_DIFF,
                    "reason": "本地已有 CHGCAR_diff，只需出图",
                    "has_diff": local["has_diff"],
                }

            run_info: Dict[str, Any] = {
                "skipped": True,
                "remote_path": "",
                "remote_sum": "",
                "elapsed_seconds": 0.0,
            }
            if diff_needed and not probe.get("has_diff"):
                stage = "computing"
                _set_stage(run_id, "computing")
                run_info = run_vtst_chgdiff(server, project, task, remote_diff_exists=False)

            got: Dict[str, Any] = {"bytes": local.get("diff_bytes") or 0}
            if diff_needed:
                stage = "downloading"
                _set_stage(run_id, "downloading", bytes_done=0, bytes_total=0)
                got = download_charge_diff(
                    server,
                    project,
                    task,
                    remote_path=str(run_info.get("remote_path") or ""),
                    progress_cb=_progress_cb_factory(run_id),
                )

            stage = "rendering"
            _set_stage(run_id, "rendering")
            import structure_images

            t_render = time.time()
            target = diff_path(project_name, task)
            render = structure_images.render_volume_now(
                str(target),
                str(image_dir(project_name, task)),
                label=IMAGE_LABEL,
                force=bool(force),
                timeout=1800,
            )
            rendered = (render.get("result") or {}) if render.get("ok") else {}
            images = rendered.get("images") or {}
            if not images:
                reason = (render.get("raw") or "").strip()[-400:] or "未知原因"
                warnings = "；".join(rendered.get("warnings") or [])
                raise ChargeDiffError(
                    f"VESTA 出图失败：{warnings or reason}", 500
                )

            payload = {
                "ok": True,
                "block_count": len(diff_charge_blocks(project, task)),
                "remote_path": str(run_info.get("remote_path") or ""),
                "remote_sum": str(run_info.get("remote_sum") or ""),
                "local_path": str(got.get("local_path") or ""),
                "dir": str(got.get("dir") or ""),
                "bytes": int(got.get("bytes") or 0),
                "elapsed_seconds": round(time.time() - t0, 1),
                "vtst_dir": vtst_dir(server),
                "reused_remote": bool(run_info.get("skipped")),
                "integrity": probe.get("integrity"),
                "images": {axis: str(_rel(path)) for axis, path in sorted(images.items())},
                "render_seconds": round(time.time() - t_render, 1),
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
                "state": STATE_IMAGES,
                "remote": {
                    "state": probe.get("state"),
                    "reason": probe.get("reason"),
                    "remote_dir": probe.get("remote_dir"),
                },
                "charge_diff": payload,
            }
            _write_json(meta_path(project_name, task), meta)
            _record_task_charge_diff(project_name, task_id, payload)
            with _LOCK:
                run = _RUNS.get(run_id)
                if run is not None:
                    run.update(
                        {
                            "status": "done",
                            "stage": "done",
                            "finished_at": meta["finished_at"],
                            "elapsed_seconds": payload["elapsed_seconds"],
                            "charge_diff": payload,
                        }
                    )
            _log_line(
                f"[ok] {project_name}/{task_id} blocks={payload['block_count']} "
                f"bytes={payload['bytes']} reused_remote={payload['reused_remote']} "
                f"elapsed={payload['elapsed_seconds']}s"
            )
        except ChargeDiffError as exc:
            _fail(project_name, task, run_id, stage, str(exc), started)
        except DiffChargeError as exc:
            _fail(project_name, task, run_id, stage, str(exc), started)
        except Exception as exc:  # noqa: BLE001 - 线程里不能抛
            _fail(
                project_name,
                task,
                run_id,
                stage,
                f"{type(exc).__name__}: {exc}",
                started,
            )
        finally:
            with _LOCK:
                if _TASK_RUN.get(task_id) == run_id:
                    _TASK_RUN.pop(task_id, None)


def _rel(path: Path) -> str:
    """相对仓库数据根的可读路径（前端展示/报告引用用）。"""
    from paths import to_local_rel

    return to_local_rel(str(path))


def clear(project_name: str, task: Dict[str, Any], *, images_only: bool = False) -> Dict[str, Any]:
    """清除本地结果（默认连差分文件一起删），便于重新走一遍完整链路。"""
    removed: List[str] = []
    for axis, path in image_paths(project_name, task).items():
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(f"image:{axis}")
    if not images_only:
        path = diff_path(project_name, task)
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append("diff")
        try:
            meta_path(project_name, task).unlink(missing_ok=True)
        except OSError:
            pass
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        _PROBE_CACHE.pop(task_id, None)
        rid = _TASK_RUN.pop(task_id, "")
        if rid:
            _RUNS.pop(rid, None)
    if not images_only:
        _record_task_charge_diff(project_name, task_id, None)
    return {"removed": removed, "dir": str(image_dir(project_name, task))}
