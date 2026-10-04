"""逐原子受力读取（巡检详情页 3D 视图「查看原子受力」，v0.9.41）。

数据来源：远端**结构来源目录**里 OUTCAR 的最后一个 `TOTAL-FORCE` 块，元素与固定原子标志取
同一目录的 POSCAR。解析**直接复用 `batch_check`**（不复制一套）。

**目录口径（关键）**：受力必须与界面显示的 CONTCAR 来自**同一个目录**——所以按巡检同步结构时
记录的 `task.last_structure_dirs.CONTCAR`（如 `con5`；`""` = 任务主目录）取力，而不是"当前最新 conN"。
老数据没有该字段时退回 `last_analysis_dir`。

- opt / frac：取结构来源目录（`last_structure_dirs.CONTCAR`，缺省退回 `last_analysis_dir`）；
- NEB：一次把**所有映像目录**（`00..NN`）的受力全取回来（仍然只发**一次**远端调用），
  每个映像各自落盘，前端切换映像即时可见、不再重复连远端。

远端读取一次 exec（遵守项目"合并远端调用"约定）：定位最新 conN → stat 指纹 + grep -c 离子步数
+ base64 POSCAR + base64 OUTCAR 尾部。OUTCAR 实测 30–57MB，只读尾部 256KB。

缓存落盘到该任务本地镜像 `<任务目录>/reports/atomic_forces[_<映像>].json`（与 files/ 同级）：
任务已结束（status 不在 queued/running）时命中缓存直接返回、不再连远端；任务在跑则重新取并覆盖；
refresh=True 强制重取。
"""

from __future__ import annotations

import base64
import json
import os
import re
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
FORCE_HEADER = "TOTAL-FORCE (eV/Angst)"
#: 只读 OUTCAR 尾部这些字节，足够覆盖最后一个 TOTAL-FORCE 块（大体系也够）
TAIL_BYTES = 262144
RUNNING_STATUSES = ("queued", "running")
DEFAULT_THRESHOLDS = {"max_force_threshold": 0.02, "rms_force_threshold": 0.01}
#: NEB 一次最多取多少个映像（防目录里混入奇怪编号）
MAX_IMAGES = 200
#: 缓存载荷版本：字段口径变化时递增，旧缓存自动作废（不必手动清 data/）
CACHE_SCHEMA = 2


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


def _work_dir_lines(remote_dir: str, analysis_dir: str) -> List[str]:
    """工作目录 = 任务主目录 + 结构来源子目录（`""` 即主目录本身）。"""
    sub = f"/{analysis_dir}" if analysis_dir else ""
    return [
        "set -e",
        f'RD="{remote_dir}"',
        f'WORK="$RD{sub}"',
        '[ -d "$WORK" ] || { echo "@@@NODIR"; exit 3; }',
        'echo "@@@WORK"',
        'echo "$WORK"',
    ]


def _image_probe_lines(prefix: str) -> List[str]:
    """按目录前缀 `prefix`（`"$WORK/"` 或 `"$d/"`）回传指纹 / 离子步 / POSCAR / 尾部 OUTCAR。"""
    return [
        "echo \"@@@META\"",
        f"stat -c '%s %Y' \"{prefix}OUTCAR\"",
        'echo "@@@STEPS"',
        f"grep -c '{FORCE_HEADER}' \"{prefix}OUTCAR\" || true",
        # NEB 判据：真正跑过的 NEB 输出里会回显 INCAR 的 `IMAGES = n`；
        # 建 NEB 时从初/末态 opt 复制过来的端点 OUTCAR 没有这一行（是个普通 opt 结果）。
        'echo "@@@NEB"',
        f"grep -m1 -o 'IMAGES *= *[0-9]*' \"{prefix}OUTCAR\" || true",
        'echo "@@@POSCAR"',
        f"base64 \"{prefix}POSCAR\" | tr -d '\\n'",
        "echo",
        'echo "@@@TAIL"',
        f"tail -c {TAIL_BYTES} \"{prefix}OUTCAR\" | base64 | tr -d '\\n'",
        "echo",
    ]


def _single_script(remote_dir: str, analysis_dir: str) -> str:
    """opt / frac 的单目录脚本（结构来源目录）。"""
    lines = _work_dir_lines(remote_dir, analysis_dir)
    lines += [
        'cd "$WORK" 2>/dev/null || { echo "@@@NODIR"; exit 3; }',
        '[ -s OUTCAR ] || { echo "@@@NOOUTCAR"; exit 4; }',
        '[ -s POSCAR ] || { echo "@@@NOPOSCAR"; exit 5; }',
    ]
    lines += _image_probe_lines("")
    lines.append('echo "@@@END"')
    return "\n".join(lines)


def _all_images_script(remote_dir: str, analysis_dir: str) -> str:
    """NEB：一次 exec 遍历所有映像目录（`00..NN`）。"""
    lines = _work_dir_lines(remote_dir, analysis_dir)
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
    """把一段探测输出解析成 `{poscar, tail, size, mtime, steps}`。"""
    meta = _slice(chunk, "@@@META\n", "@@@STEPS").split()
    steps_text = _slice(chunk, "@@@STEPS\n", "@@@NEB").strip()
    neb_text = _slice(chunk, "@@@NEB\n", "@@@POSCAR").strip()
    poscar_b64 = _slice(chunk, "@@@POSCAR\n", "@@@TAIL").strip()
    # 用 _slice 而不是 _after：最后一段后面跟着 "@@@END" 标记，不能混进 base64
    tail_b64 = _slice(chunk, "@@@TAIL\n", "@@@END").strip()
    return {
        "poscar": _decode(poscar_b64),
        "tail": _decode(tail_b64),
        "size": int(meta[0]) if len(meta) > 0 and meta[0].isdigit() else None,
        "mtime": int(meta[1]) if len(meta) > 1 and meta[1].isdigit() else None,
        "steps": int(steps_text) if steps_text.isdigit() else None,
        # 该 OUTCAR 是不是"本 NEB 跑出来的"（含 IMAGES 回显）——opt 结果没有这一行
        "is_neb": bool(neb_text),
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


def _structure_dir(task: Dict[str, Any]) -> str:
    """结构（CONTCAR）实际来源子目录：`""` = 任务主目录。

    优先用巡检同步结构时记录的 `last_structure_dirs.CONTCAR`（含"回退主目录"的真实情况）；
    老数据没有该字段时退回 `last_analysis_dir`。
    """
    dirs = task.get("last_structure_dirs")
    if isinstance(dirs, dict) and "CONTCAR" in dirs:
        return str(dirs.get("CONTCAR") or "")
    return str(task.get("last_analysis_dir") or "")


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
            "ionic_step": probe["steps"],
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
    structure_dir = _structure_dir(task)
    running = str(task.get("status") or "") in RUNNING_STATUSES
    cached = _read_cache(reports_dir, task_id, image)
    # 缓存有效性：结构来源目录必须一致（换过 conN / 重新同步结构就要重取）
    if (
        cached
        and cached.get("source_dir") == structure_dir
        and not running
        and not refresh
    ):
        return {**cached, "cached": True}

    if task_type == "neb":
        if not image:
            raise AtomicForceError(400, "NEB 请指定映像编号（image），或直接切换映像后重试")
        payloads = _fetch_all_images(
            server, remote_dir, structure_dir, task_id, reports_dir
        )
        if image not in payloads:
            raise AtomicForceError(
                404,
                f"映像 {image} 没有可用的 OUTCAR（可能尚未计算），本次共取到 {len(payloads)} 个映像",
            )
        payload = payloads[image]
        others = sorted(k for k in payloads if k != image)
        payload["cached"] = False
        payload["sibling_images"] = others
        return payload

    thresholds = _thresholds(task_id)
    script = base64.b64encode(
        _single_script(remote_dir, structure_dir).encode("utf-8")
    ).decode("ascii")
    out = _run(server, script)
    _raise_for_flags(
        out, f"{remote_dir}/{structure_dir}" if structure_dir else remote_dir
    )
    work_dir = _after(out, "@@@WORK\n").split("\n", 1)[0].strip()
    probe = _probe_of(out)
    payload, warnings = _build_payload(
        task_id=task_id,
        task_type=task_type,
        image=None,
        work_dir=work_dir,
        probe=probe,
        thresholds=thresholds,
    )
    payload["source_dir"] = structure_dir
    payload["cache_path"] = _write_cache(reports_dir, task_id, None, payload)
    if warnings:
        payload["warnings"] = warnings
    payload["cached"] = False
    return payload


def _run(server: str, script_b64: str) -> str:
    # base64 传输（避免引号转义；本地模拟模式也认这个形式），整段一次 exec
    result = ssh.run_remote(server, f"echo {script_b64} | base64 -d | bash", timeout=300)
    out = str(result.get("stdout") or "")
    # 脚本主动打标记（@@@NODIR 等）退出属于"可解释失败"，交给调用方映射成 404/409
    flagged = any(flag in out for flag in ("@@@NODIR", "@@@NOOUTCAR", "@@@NOPOSCAR"))
    if result.get("exit_code") != 0 and "@@@END" not in out and not flagged:
        raise AtomicForceError(
            502, f"读取远端受力失败：{(result.get('stderr') or out).strip()[:200]}"
        )
    return out


def _raise_for_flags(out: str, remote_dir: str) -> None:
    if "@@@NODIR" in out:
        raise AtomicForceError(
            404, f"远端结构目录不存在：{remote_dir}（与界面显示的 CONTCAR 来源不一致时会这样）"
        )
    if "@@@NOOUTCAR" in out:
        raise AtomicForceError(404, "该目录还没有 OUTCAR（作业可能尚未开始或尚未产生输出）")
    if "@@@NOPOSCAR" in out:
        raise AtomicForceError(404, "该目录缺少 POSCAR，无法对应原子序号")


def _fetch_all_images(
    server: str,
    remote_dir: str,
    structure_dir: str,
    task_id: str,
    reports_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    """NEB：一次 exec 取回所有映像的受力，逐个落盘，返回 `{映像: payload}`。"""
    script = base64.b64encode(
        _all_images_script(remote_dir, structure_dir).encode("utf-8")
    ).decode("ascii")
    out = _run(server, script)
    if "@@@NODIR" in out:
        raise AtomicForceError(
            404,
            f"远端结构目录不存在：{remote_dir}"
            + (f"/{structure_dir}" if structure_dir else ""),
        )

    work_base = _after(out, "@@@WORK\n").split("\n", 1)[0].strip()
    # 目录清单（含被跳过的）：用于判断"这个 NEB 到底跑没跑"
    found = re.findall(r"@@@(IMG|SKIP) ([^\s]+)", out)
    all_labels = [label for _, label in found]
    skipped = {label for kind, label in found if kind == "SKIP"}
    # 端点 OUTCAR 可能是建 NEB 时从初/末态 opt 复制来的伪结果，不代表本 NEB 运行过
    # （与 batch_check._analyze_neb_status 同一判据）：中间映像有 OUTCAR 才说明跑过第一步
    if len(all_labels) >= 3:
        middles = all_labels[1:-1]
        if middles and not any(label not in skipped for label in middles):
            raise AtomicForceError(
                409,
                "该 NEB 还没有跑出第一个离子步（中间映像还没有 OUTCAR），暂时没有逐原子受力",
            )
    elif skipped and all_labels and len(skipped) == len(all_labels):
        raise AtomicForceError(
            409, "该 NEB 还没有跑出第一个离子步（所有映像都还没有 OUTCAR）"
        )

    thresholds = _thresholds(task_id)
    payloads: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for chunk in _after(out, "@@@IMG ").split("@@@IMG "):
        label, _, rest = chunk.partition("\n")
        label = label.strip()
        if not label:
            continue
        probe = _probe_of(rest)
        if not probe["is_neb"]:
            # 端点 OUTCAR 来自创建 NEB 时的拷贝（普通 opt 结果）→ 不作为本 NEB 的受力
            warnings.append(f"映像 {label} 的 OUTCAR 不是本 NEB 的输出（建 NEB 时的拷贝），已跳过")
            continue
        try:
            payload, block_warnings = _build_payload(
                task_id=task_id,
                task_type="neb",
                image=label,
                work_dir=f"{work_base}/{label}",
                probe=probe,
                thresholds=thresholds,
            )
        except AtomicForceError as e:
            warnings.append(f"映像 {label}：{e.message}")
            continue
        payload["warnings"] = block_warnings
        payload["source_dir"] = structure_dir
        payload["cache_path"] = _write_cache(reports_dir, task_id, label, payload)
        payloads[label] = payload
    if not payloads:
        raise AtomicForceError(
            409, "没有取到任何映像的逐原子受力（" + ("；".join(warnings) or "映像还没有跑出离子步") + "）",
            extra={"warnings": warnings},
        )
    return payloads
