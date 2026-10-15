"""逐原子受力读取（巡检详情页 3D 视图「查看原子受力」，v0.9.41）。

数据来源：远端**结构来源目录**里 OUTCAR 的最后一个 `TOTAL-FORCE` 块，元素与固定原子标志取
同一目录的 POSCAR。解析**直接复用 `batch_check`**（不复制一套）。

**目录口径（关键）**：受力必须与界面显示的 CONTCAR 来自**同一个目录**——所以按巡检同步结构时
记录的 `task.last_structure_dirs.CONTCAR`（如 `con5`；`""` = 任务主目录）取力，而不是"当前最新 conN"。
老数据没有该字段时退回 `last_analysis_dir`。

- opt / frac：取结构来源目录（`last_structure_dirs.CONTCAR`，缺省退回 `last_analysis_dir`）；
- NEB：一次把**所有映像目录**（`00..NN`）的受力全取回来（仍然只发**一次**远端调用），
  每个映像各自落盘，前端切换映像即时可见、不再重复连远端。

远端读取一次 exec（遵守项目"合并远端调用"约定）：进入结构来源目录 → stat 指纹 + base64 POSCAR
  + base64 OUTCAR 尾部 128KB。OUTCAR 实测 30–57MB，只读尾部（**不做全文件扫描**，否则每张要读几十 MB）。
尾部窗口里没有完整的 `TOTAL-FORCE` 块时（有的映像在最后一个离子步之后又写了大块内容，把力块挤出窗口），
再发一次**定点**调用：远端 grep 出最后一个 `TOTAL-FORCE` 行号、算出字节偏移，只把那一段取回来
（`_deep_block_script`，上限 512KB；2026-10-13 Ag24@Al2O3_neb 映像 01 就是这么取到的）。

首/末映像也照常着色：端点的 OUTCAR 是建 NEB 时从初/末态 opt 复制来的，与它显示的初/末态结构
来自同一目录，属于有效结果；中间映像要等 NEB 真跑出离子步才会有 OUTCAR（没有就不显示受力）。

缓存落盘到该任务本地镜像 `<任务目录>/reports/atomic_forces[_<映像>].json`（与 files/ 同级）：
任务已结束（status 不在 queued/running）时命中缓存直接返回、不再连远端；任务在跑则重新取并覆盖；
refresh=True 强制重取。
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from batch_check import (
    compute_force_stats,
    parse_poscar_layout,
    parse_total_force_blocks,
)
from checks_store import merged_results
from config import DATA_DIR
from dates import now_iso
import ssh
from task_paths import task_dir, task_remote_dir

#: 任务目录写不进去时（权限异常）退回这里，保证功能不至于直接报错
FALLBACK_DIR = DATA_DIR / "forces"
#: 只读 OUTCAR 尾部这些字节，足够覆盖最后一个 TOTAL-FORCE 块（140 原子一块约 10KB，留足余量）
TAIL_BYTES = 131072
RUNNING_STATUSES = ("queued", "running")
DEFAULT_THRESHOLDS = {"max_force_threshold": 0.02, "rms_force_threshold": 0.01}
#: NEB 一次最多取多少个映像（防目录里混入奇怪编号）
MAX_IMAGES = 200
#: 缓存载荷版本：字段口径变化时递增，旧缓存自动作废（不必手动清 data/）
CACHE_SCHEMA = 4  # v4：受力来源改成"候选目录列表 + 实际命中目录"（见 _structure_dirs）
#: 远端单次调用超时（秒）：只读尾部 + 两个 grep，正常 2–5s 内
REMOTE_TIMEOUT = 120


class AtomicForceError(Exception):
    """受力读取失败（带 HTTP 状态码）。"""

    def __init__(self, status_code: int, message: str, *, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.extra = extra or {}


# ---------------------------------------------------------------- 缓存


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_@" else "_" for ch in str(name))


def _forces_dir(project_name: str, task: Dict[str, Any]) -> Path:
    """受力缓存落到该任务本地镜像的 reports/ 里（与 files/ 同级，不混进 VASP 输入文件）。"""
    try:
        reports_dir = task_dir(project_name, task) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir
    except OSError:
        FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        return FALLBACK_DIR


def _cache_path(base_dir: Path, task_id: str, image: Optional[str]) -> Path:
    # 落在任务自己的 reports/ 时用固定名；退回 FALLBACK_DIR 时带 task_id 防撞
    suffix = f"_{_safe(image)}" if image else ""
    if base_dir == FALLBACK_DIR:
        return base_dir / f"{_safe(task_id)}{suffix}.json"
    return base_dir / f"atomic_forces{suffix}.json"


def _read_cache(
    base_dir: Path, task_id: str, image: Optional[str]
) -> Optional[Dict[str, Any]]:
    path = _cache_path(base_dir, task_id, image)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA:
            return None  # 口径变化后的旧缓存直接作废（例如端点伪结果那版）
        return data
    except Exception:  # noqa: BLE001 - 缓存损坏当作没有
        return None


def _write_cache(
    base_dir: Path, task_id: str, image: Optional[str], payload: Dict[str, Any]
) -> str:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(base_dir, task_id, image)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


# ---------------------------------------------------------------- 远端脚本


def _work_dir_lines(remote_dir: str, analysis_dirs: List[str]) -> List[str]:
    """挑出**真正存在且有结果**的工作目录。

    候选子目录按优先级排列（`""` = 任务主目录本身）。顺序试：谁的 OUTCAR 非空（opt）
    或谁的映像子目录里有非空 OUTCAR（NEB）就用谁 —— 这样"记录里的 conN 已经被删/换过"
    时不会取到空目录（2026-10-08 用户：PAYH3_TS2 记录里还是 con8，但远端只剩 con1–con6）。

    **失败原因要说清楚**（2026-10-15 修）：以前"所有候选都没有可用 OUTCAR"和"任务主目录不存在"
    都打同一个 `@@@NODIR`，本地一律翻译成"远端结构目录不存在：<主目录>"→ 明明目录在、
    只是 OUTCAR 正在重写（作业刚重启）时，报错把人引偏（用户 FS-1opt 反馈）。
    现在分三种标记，并且**逐个候选上报状态**（`@@@CAND=<子目录或主目录>:<字节数|MISSING>`），
    本地据此给出"试过哪些目录、各自什么状态"。
    """
    subs = " ".join(f'"{d}"' for d in analysis_dirs)
    return [
        "set -e",
        f'RD="{remote_dir}"',
        'WORK=""',
        '[ -d "$RD" ] || { echo "@@@NODIR"; exit 3; }',
        f"for SUB in {subs}; do",
        '  CAND="$RD/$SUB"',
        '  if [ -d "$CAND" ]; then',
        '    SZ=$(stat -c %s "$CAND/OUTCAR" 2>/dev/null || echo 0)',
        '    echo "@@@CAND=$SUB:$SZ"',
        '    if [ "$SZ" -gt 0 ]; then WORK="$CAND"; break; fi',
        '    for f in "$CAND"/[0-9]*/OUTCAR; do',
        '      if [ -s "$f" ]; then WORK="$CAND"; break 2; fi',
        "    done",
        "  else",
        '    echo "@@@CAND=$SUB:MISSING"',
        "  fi",
        "done",
        '[ -n "$WORK" ] || { echo "@@@NODATA"; exit 3; }',
        'echo "@@@WORK"',
        'echo "$WORK"',
    ]


def _image_probe_lines(prefix: str) -> List[str]:
    """按目录前缀 `prefix`（`"$WORK/"` 或 `"$d/"`）回传指纹 / POSCAR / 尾部 OUTCAR。

    不在这里做 `grep -c TOTAL-FORCE`（要整读 30–57MB 的 OUTCAR，NEB 一张一张读会明显变慢）；
    只 `grep -m1` 取尾部…也不需要——尾部里就有完整块，交给本地解析。
    """
    return [
        "echo \"@@@META\"",
        f"stat -c '%s %Y' \"{prefix}OUTCAR\"",
        'echo "@@@POSCAR"',
        f"base64 \"{prefix}POSCAR\" | tr -d '\\n'",
        "echo",
        'echo "@@@TAIL"',
        f"tail -c {TAIL_BYTES} \"{prefix}OUTCAR\" | base64 | tr -d '\\n'",
        "echo",
        # 每个映像的探测块显式收尾：后面的 "@@@SKIP xx" 等标记必须落在块外，
        # 否则会被当成 base64 内容拼进去（曾导致首个映像解析失败）
        'echo "@@@IMGDONE"',
    ]


#: 深度兜底：尾部窗口里没有 TOTAL-FORCE 时，远端定位最后一个块起点后最多取这么多字节
DEEP_BLOCK_BYTES = 512 * 1024


def _deep_block_script(image_dir: str) -> str:
    """远端定位 `OUTCAR` 里**最后一个** `TOTAL-FORCE` 行，从该行起取回文本。

    为什么需要它：只读尾部 128KB 是为了省流量，但某些映像的 OUTCAR 在最后一个离子步之后
    又写了大块内容（实测 Ag24@Al2O3_neb 的映像 01：546KB 文件、TOTAL-FORCE 只有 1 次、
    被挤出了尾部窗口），于是"看起来还没有离子步"。这里回远端 grep 出行号、算出字节偏移，
    只把那一块（到 EOF 或上限）取回来，代价是远端一次全文件顺序读，网络传输仍然很小。
    """
    return "\n".join(
        [
            f'D="{image_dir}"',
            'LINE=$(grep -n "TOTAL-FORCE" "$D/OUTCAR" 2>/dev/null | tail -1 | cut -d: -f1)',
            '[ -n "$LINE" ] || { echo "@@@NOBLOCK"; exit 0; }',
            'OFF=$(head -n "$((LINE - 1))" "$D/OUTCAR" | wc -c)',
            f'tail -c +"$((OFF + 1))" "$D/OUTCAR" | head -c {DEEP_BLOCK_BYTES} | base64 | tr -d "\\n"',
        ]
    )


def _deep_block(server: str, image_dir: str) -> str:
    """取回最后一个 TOTAL-FORCE 块（没有则返回空串）。"""
    script = base64.b64encode(_deep_block_script(image_dir).encode("utf-8")).decode("ascii")
    out = _run(server, script)
    if "@@@NOBLOCK" in out:
        return ""
    return _decode(out.strip())


def _single_script(remote_dir: str, analysis_dirs: List[str]) -> str:
    """opt / frac 的单目录脚本（结构来源目录）。"""
    lines = _work_dir_lines(remote_dir, analysis_dirs)
    lines += [
        'cd "$WORK" 2>/dev/null || { echo "@@@NODIR"; exit 3; }',
        '[ -s OUTCAR ] || { echo "@@@NOOUTCAR"; exit 4; }',
        '[ -s POSCAR ] || { echo "@@@NOPOSCAR"; exit 5; }',
    ]
    lines += _image_probe_lines("")
    lines.append('echo "@@@END"')
    return "\n".join(lines)


def _all_images_script(remote_dir: str, analysis_dirs: List[str]) -> str:
    """NEB：一次 exec 遍历所有映像目录（`00..NN`）。"""
    lines = _work_dir_lines(remote_dir, analysis_dirs)
    lines += [
        "COUNT=0",
        'for d in "$WORK"/[0-9]*; do',
        '  [ -d "$d" ] || continue',
        "  img=$(basename \"$d\")",
        "  COUNT=$((COUNT + 1))",
        f"  [ $COUNT -le {MAX_IMAGES} ] || break",
        '  if [ ! -s "$d/OUTCAR" ] || [ ! -s "$d/POSCAR" ]; then',
        '    echo "@@@SKIP $img"',
        "    continue",
        "  fi",
        '  echo "@@@IMG $img"',
    ]
    lines += [f"  {line}" for line in _image_probe_lines('$d/')]
    lines += [
        "done",
        'echo "@@@END"',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 输出解析


def _after(text: str, marker: str) -> str:
    idx = text.find(marker)
    return text[idx + len(marker) :] if idx >= 0 else ""


def _slice(text: str, start: str, end: str) -> str:
    rest = _after(text, start)
    if not rest:
        return ""
    idx = rest.find(end)
    return rest[:idx] if idx >= 0 else rest


def _decode(text: str) -> str:
    try:
        return base64.b64decode(text).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise AtomicForceError(502, f"远端返回内容解码失败：{e}") from None


def _probe_of(chunk: str) -> Dict[str, Any]:
    """把一段探测输出解析成 `{poscar, tail, size, mtime}`。"""
    meta = _slice(chunk, "@@@META\n", "@@@POSCAR").split()
    poscar_b64 = _slice(chunk, "@@@POSCAR\n", "@@@TAIL").strip()
    # 用 _slice 而不是 _after：最后一段后面跟着 "@@@END" 标记，不能混进 base64
    tail_b64 = _slice(chunk, "@@@TAIL\n", "@@@IMGDONE").strip()
    return {
        "poscar": _decode(poscar_b64),
        "tail": _decode(tail_b64),
        "size": int(meta[0]) if len(meta) > 0 and meta[0].isdigit() else None,
        "mtime": int(meta[1]) if len(meta) > 1 and meta[1].isdigit() else None,
    }


# ---------------------------------------------------------------- 组装载荷


def _elements_of(layout: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """把 POSCAR 的「元素名 + 计数」摊平成逐原子元素表；VASP4（无元素名）返回 None。"""
    if not layout:
        return None
    species = layout.get("species")
    counts = layout.get("counts") or []
    if not species or len(species) != len(counts):
        return None
    out: List[str] = []
    for name, count in zip(species, counts):
        out.extend([str(name)] * int(count))
    return out


def _thresholds(task_id: str) -> Dict[str, Any]:
    """阈值口径与巡检判定一致：优先用巡检归档里那条（可能来自 INCAR 的 EDIFFG）。"""
    entry = (merged_results() or {}).get(task_id) or {}
    got = entry.get("force_thresholds")
    if isinstance(got, dict) and got.get("max_force_threshold") is not None:
        return dict(got)
    return {**DEFAULT_THRESHOLDS, "source": "registry"}


def _structure_dirs(task: Dict[str, Any]) -> List[str]:
    """受力该读哪个子目录：按优先级给一串候选（`""` = 任务主目录），远端会挑第一个真有结果的。

    用户口径："**CONTCAR 来自哪个文件夹，受力就来自哪里**"。候选顺序：
      1. `last_structure_dirs`（巡检同步结构时记的真实来源，含"回退主目录"的情况）；
      2. `input_state.source.con` —— **本地镜像（files/ 里的 CONTCAR/POSCAR）是从哪个 conN 同步来的**，
         也就是界面/文件里看到的那份 CONTCAR 的实际来源；
      3. `last_analysis_dir`（老数据只有这个字段）；
      4. `""` 任务主目录。
    为什么要给一串：记录里的 conN 可能已经被清理/换名（2026-10-08 PAYH3_TS2 记录还是 con8、
    远端只剩 con1–con6），只认死一个就会取到空目录、白屏或报"没有 OUTCAR"。
    """
    candidates: List[str] = []

    def _add(value: Any) -> None:
        text = str(value or "").strip().strip("/")
        if text and text not in candidates:
            candidates.append(text)

    dirs = task.get("last_structure_dirs")
    if isinstance(dirs, dict):
        for key in ("CONTCAR", "POSCAR", "OUTCAR"):
            if key in dirs:
                _add(dirs.get(key))
    source = (task.get("input_state") or {}).get("source") or {}
    _add(source.get("con"))
    _add(task.get("last_analysis_dir"))
    # 兜底：**任务主目录本身**（`""`）。
    # 2026-10-15 修 bug：以前这里写的是 `_add("")`，而 `_add` 里有 `if text` 过滤 ——
    # 空串被判为假，于是"回退主目录"这个候选**从来没进过列表**。后果：记录里的 conN
    # 一旦不可用（被清理 / OUTCAR 正在重写），就一个候选都没有 → 远端打 `@@@NODIR`
    # → 本地报"远端结构目录不存在：<主目录>"，而主目录里其实躺着一份好好的 OUTCAR
    # （用户 FS-1opt 反馈的就是这个）。现在显式追加，且**放在最后**当兜底。
    if "" not in candidates:
        candidates.append("")
    return candidates


def _relative_dir(remote_dir: str, work_dir: str) -> str:
    """远端返回的工作目录（绝对路径）→ 相对任务目录的子目录（主目录本身 = ""）。"""
    base = str(remote_dir or "").rstrip("/")
    work = str(work_dir or "").rstrip("/")
    if not base or not work.startswith(base):
        return ""
    return work[len(base) :].lstrip("/")


def _build_payload(
    *,
    task_id: str,
    task_type: str,
    image: Optional[str],
    work_dir: str,
    probe: Dict[str, Any],
    thresholds: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """由一个目录的探测结果组装逐原子受力载荷；返回 `(payload, warnings)`。"""
    blocks = parse_total_force_blocks(probe["tail"])
    if not blocks:
        raise AtomicForceError(
            409, "OUTCAR 里还没有完整的离子步（TOTAL-FORCE）块，暂时没有逐原子受力"
        )
    last = blocks[-1]
    forces: List[Any] = last.get("forces") or []
    if not forces:
        raise AtomicForceError(409, "最后一个 TOTAL-FORCE 块没有原子行")

    layout = parse_poscar_layout(probe["poscar"])
    fixed: List[bool] = list((layout or {}).get("fixed") or [])
    elements = _elements_of(layout)
    warnings: List[str] = []
    if layout is None:
        warnings.append("POSCAR 解析失败，无法确定固定原子与元素名")
    elif layout.get("n_atoms") != len(forces):
        warnings.append(
            f"POSCAR 原子数（{layout.get('n_atoms')}）与 OUTCAR 受力行数（{len(forces)}）不一致"
        )

    atoms: List[Dict[str, Any]] = []
    for index, (fx, fy, fz) in enumerate(forces):
        atom: Dict[str, Any] = {
            "index": index,
            "fx": round(float(fx), 6),
            "fy": round(float(fy), 6),
            "fz": round(float(fz), 6),
            "fmax": round(max(abs(float(fx)), abs(float(fy)), abs(float(fz))), 6),
            "fixed": bool(fixed[index]) if index < len(fixed) else False,
        }
        if elements and index < len(elements):
            atom["element"] = elements[index]
        atoms.append(atom)

    stats = compute_force_stats(forces, fixed or None)
    return (
        {
            "task_id": task_id,
            "schema": CACHE_SCHEMA,
            "task_type": task_type,
            "image": image,
            "work_dir": work_dir,
            "structure": "CONTCAR",
            "energy": last.get("energy"),
            "force_max": stats[0] if stats else None,
            "force_rms": stats[1] if stats else None,
            "threshold": thresholds,
            "atom_count": len(atoms),
            "fixed_count": sum(1 for a in atoms if a["fixed"]),
            "elements": elements,
            "atoms": atoms,
            "warnings": warnings,
            "outcar": {"size": probe["size"], "mtime": probe["mtime"]},
            "fetched_at": now_iso(),
        },
        warnings,
    )


# ---------------------------------------------------------------- 主入口


def build_atomic_forces(
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    image: Optional[str] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """读取逐原子受力（带本地缓存）。失败抛 `AtomicForceError`。

    - opt / frac：取最新 conN 的 OUTCAR；
    - NEB：一次 exec 取回**全部映像**并各自落盘，返回所请求的那个映像。
    """
    task_id = str(task.get("task_id") or "")
    task_type = str(task.get("task_type") or "")
    if task_type not in ("opt", "frac", "neb"):
        raise AtomicForceError(400, "仅结构优化 / 频率矫正 / NEB 任务支持查看原子受力")
    image = (str(image).strip() or None) if image else None
    if task_type != "neb":
        image = None  # 只有 NEB 分映像

    server = project.get("server")
    remote_dir = task_remote_dir(server, task).rstrip("/")
    if not remote_dir:
        raise AtomicForceError(404, "任务缺少远程目录")

    reports_dir = _forces_dir(str(project.get("name") or ""), task)
    structure_dirs = _structure_dirs(task)
    structure_key = ",".join(structure_dirs)  # 候选变了（换过 conN / 重新同步结构）就要重取
    running = str(task.get("status") or "") in RUNNING_STATUSES
    cached = _read_cache(reports_dir, task_id, image)
    if (
        cached
        and cached.get("source_dirs") == structure_key
        and not running
        and not refresh
    ):
        return {**cached, "cached": True}

    if task_type == "neb":
        if not image:
            raise AtomicForceError(400, "NEB 请指定映像编号（image），或直接切换映像后重试")
        payloads, fetch_warnings = _fetch_all_images(
            server, remote_dir, structure_dirs, task_id, reports_dir
        )
        if image not in payloads:
            got = "、".join(sorted(payloads)) or "无"
            detail = next(
                (w.split("：", 1)[1] for w in fetch_warnings if w.startswith(f"映像 {image}：")),
                "该映像还没开始或还没算完",
            )
            raise AtomicForceError(
                404,
                f"映像 {image} 暂时没有受力（{detail}）；本次已取到映像 {got}",
                extra={"warnings": fetch_warnings},
            )
        payload = payloads[image]
        others = sorted(k for k in payloads if k != image)
        payload["cached"] = False
        payload["sibling_images"] = others
        return payload

    thresholds = _thresholds(task_id)
    script = base64.b64encode(
        _single_script(remote_dir, structure_dirs).encode("utf-8")
    ).decode("ascii")
    out = _run(server, script)
    _raise_for_flags(out, remote_dir)
    work_dir = _after(out, "@@@WORK\n").split("\n", 1)[0].strip()
    probe = _probe_of(out)
    try:
        payload, warnings = _build_payload(
            task_id=task_id,
            task_type=task_type,
            image=None,
            work_dir=work_dir,
            probe=probe,
            thresholds=thresholds,
        )
    except AtomicForceError:
        # 同上：尾部窗口里没有力块时回远端定位最后一个 TOTAL-FORCE
        try:
            deep = _deep_block(server, work_dir)
        except Exception:  # noqa: BLE001 - 深度兜底失败就按原始错误报告
            raise
        if not (deep and "TOTAL-FORCE" in deep):
            raise
        payload, warnings = _build_payload(
            task_id=task_id,
            task_type=task_type,
            image=None,
            work_dir=work_dir,
            probe={**probe, "tail": deep},
            thresholds=thresholds,
        )
        warnings = [*warnings, "受力来自深度兜底（尾部窗口里没有力块）"]
    payload["source_dir"] = _relative_dir(remote_dir, work_dir)
    payload["source_dirs"] = structure_key
    # 2026-10-15：受力来源与"记录里的结构来源"不一致时**明确提示**（用户 FS-1opt 反馈：
    # 界面显示的是某个 conN 的 CONTCAR，受力却因为那份 conN 失效而回退到别处 →
    # 两者可能不是同一份结构，不能再默默返回）。
    recorded_source = structure_dirs[0] if structure_dirs else ""
    if recorded_source and payload["source_dir"] != recorded_source:
        actual = payload["source_dir"] or "主目录"
        warnings = [
            *warnings,
            f"受力来源与记录的结构来源不一致（记录 {recorded_source} → 实际 {actual}）："
            "可能与界面显示的 CONTCAR 不同源，确认后再用这组受力",
        ]
    payload["cache_path"] = _write_cache(reports_dir, task_id, None, payload)
    if warnings:
        payload["warnings"] = warnings
    payload["cached"] = False
    return payload


def _run(server: str, script_b64: str) -> str:
    # base64 传输（避免引号转义；本地模拟模式也认这个形式），整段一次 exec
    result = ssh.run_remote(
        server, f"echo {script_b64} | base64 -d | bash", timeout=REMOTE_TIMEOUT
    )
    out = str(result.get("stdout") or "")
    # 脚本主动打标记（@@@NODIR / @@@NODATA 等）退出属于"可解释失败"，交给调用方映射成 404/409
    # （@@@NODATA 是 2026-10-15 新增：目录在、但没有可用的 OUTCAR —— 漏了它就会掉进 502 兜底，
    #   把"试过哪些候选目录"的诊断全丢掉）
    flagged = any(
        flag in out for flag in ("@@@NODIR", "@@@NODATA", "@@@NOOUTCAR", "@@@NOPOSCAR")
    )
    if result.get("exit_code") != 0 and "@@@END" not in out and not flagged:
        raise AtomicForceError(
            502, f"读取远端受力失败：{(result.get('stderr') or out).strip()[:200]}"
        )
    return out


def _raise_for_flags(out: str, remote_dir: str) -> None:
    """把远端标记翻译成人话（`@@@NODIR` = 任务主目录不存在 / `@@@NODATA` = 目录在但没有可用 OUTCAR）。"""
    if "@@@NODIR" in out:
        raise AtomicForceError(404, f"远端任务目录不存在：{remote_dir}")
    if "@@@NODATA" in out:
        raise AtomicForceError(
            409,
            "候选目录里没有可用的 OUTCAR（作业可能刚刚重启、OUTCAR 正在重写；"
            "等一会儿再点「查看原子受力」）"
            + _candidate_note(out),
        )
    if "@@@NOOUTCAR" in out:
        raise AtomicForceError(404, "该目录还没有 OUTCAR（作业可能尚未开始或尚未产生输出）")
    if "@@@NOPOSCAR" in out:
        raise AtomicForceError(404, "该目录缺少 POSCAR，无法对应原子序号")


def _candidate_note(out: str) -> str:
    """把脚本上报的候选目录状态拼成一句诊断：`· 试过：con1（OUTCAR 4.4 MB）、主目录（不存在）`。"""
    items: List[str] = []
    for line in out.splitlines():
        text = line.strip()
        if not text.startswith("@@@CAND="):
            continue
        payload = text[len("@@@CAND=") :]
        sub, _, size = payload.rpartition(":")
        label = f"{sub}" if sub else "主目录"
        if size == "MISSING":
            items.append(f"{label}（目录不存在）")
        else:
            try:
                size_int = int(size)
            except ValueError:
                size_int = 0
            shown = (
                f"{size_int / 1024 / 1024:.1f} MB"
                if size_int >= 1024 * 1024
                else f"{size_int} B"
            )
            items.append(f"{label}（OUTCAR {shown}）")
    if not items:
        return ""
    return " · 试过：" + "、".join(items)


def _fetch_all_images(
    server: str,
    remote_dir: str,
    structure_dirs: List[str],
    task_id: str,
    reports_dir: Path,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """NEB：一次 exec 取回所有映像的受力，逐个落盘；返回 `({映像: payload}, 警告)`。"""
    script = base64.b64encode(
        _all_images_script(remote_dir, structure_dirs).encode("utf-8")
    ).decode("ascii")
    out = _run(server, script)
    if "@@@NODIR" in out:
        tried = "、".join(d or "任务主目录" for d in structure_dirs)
        raise AtomicForceError(404, f"远端没有可用的结构目录（试过：{tried}）")

    work_base = _after(out, "@@@WORK\n").split("\n", 1)[0].strip()
    thresholds = _thresholds(task_id)
    payloads: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for chunk in _after(out, "@@@IMG ").split("@@@IMG "):
        label, _, rest = chunk.partition("\n")
        label = label.strip()
        if not label:
            continue
        image_dir = f"{work_base}/{label}"
        probe = _probe_of(rest)
        try:
            payload, block_warnings = _build_payload(
                task_id=task_id,
                task_type="neb",
                image=label,
                work_dir=image_dir,
                probe=probe,
                thresholds=thresholds,
            )
        except AtomicForceError as e:
            # 尾部窗口里没有力块 → 回远端定位最后一个 TOTAL-FORCE 再取一次（见 _deep_block_script）
            deep = ""
            try:
                deep = _deep_block(server, image_dir)
            except Exception as exc:  # noqa: BLE001 - 深度兜底失败就按原错误报告
                warnings.append(f"映像 {label}：深度取受力失败：{exc}")
            if not (deep and "TOTAL-FORCE" in deep):
                warnings.append(f"映像 {label}：{e.message}")
                continue
            try:
                payload, block_warnings = _build_payload(
                    task_id=task_id,
                    task_type="neb",
                    image=label,
                    work_dir=image_dir,
                    probe={**probe, "tail": deep},
                    thresholds=thresholds,
                )
                block_warnings = [*block_warnings, "受力来自深度兜底（尾部窗口里没有力块）"]
            except AtomicForceError as e2:
                warnings.append(f"映像 {label}：{e2.message}")
                continue
        payload["warnings"] = block_warnings
        payload["source_dir"] = _relative_dir(remote_dir, work_base)
        payload["source_dirs"] = ",".join(structure_dirs)
        payload["cache_path"] = _write_cache(reports_dir, task_id, label, payload)
        payloads[label] = payload
    if not payloads:
        raise AtomicForceError(
            409, "没有取到任何映像的逐原子受力（" + ("；".join(warnings) or "映像还没有跑出离子步") + "）",
            extra={"warnings": warnings},
        )
    return payloads, warnings
