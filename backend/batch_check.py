#!/usr/bin/env python3
"""服务器端批量检查脚本（在 VASP 计算服务器本地运行）。

用法：python3 batch_check.py <输入JSON路径> <输出JSON路径>

输入 JSON：任务清单数组，每项含 task_id / remote_dir / job_id / task_type /
project_name（project_name 仅透传，供巡检结果归档使用）。
输出 JSON：每项含 queue_status / status / last_energy / force_max /
force_rms / force_converged / force_history / error_messages。

规则要点：
- job_id 为空 -> OUTCAR 存在则按 OUTCAR 分析，否则 status=pending；
- job_id 非空 -> bjobs -l（5 秒超时），PEND->queued、RUN->running（不读 OUTCAR）；
  DONE/EXIT/COMPLETED/FAILED/CANCELLED/作业不存在/超时(UNKNOWN) -> 进入 OUTCAR 分析；
- OUTCAR 成功标记 -> completed；错误关键词 -> zombied；无标记且作业已结束 -> zombied；
- 能量：取所有 "free energy TOTEN =" 的最后一个值；
- 结构优化：解析 POSCAR Selective dynamics，统计每个 TOTAL-FORCE 块（离子步）的
  最大力，生成力收敛历史；最后一步计算 force_max / force_rms / force_converged；
- 单任务异常只写入该任务 error_messages，不影响其他任务。

环境变量：
- VASP_CHECK_REGISTRY：力收敛阈值配置文件路径（缺省读脚本同目录 check_registry.json）
- VASP_BATCH_NO_BJOBS=1：跳过 bjobs 查询（本地模拟/离线测试用），统一按 OUTCAR 分析
- VASP_BATCH_LOCAL_ROOT：把 remote_dir 映射到本地根目录（本地模拟用），
  仅影响文件读取，结果中的 remote_dir 仍保留原始远程路径
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _force_utf8_stdio() -> None:
    """强制 stdout/stderr 使用 UTF-8 编码（服务器 locale 可能非 UTF-8）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


_force_utf8_stdio()

BJOB_TIMEOUT = 5  # 秒
DEFAULT_THRESHOLDS = {
    "max_force_threshold": 0.02,
    "rms_force_threshold": 0.01,
}
SUCCESS_MARKERS = (
    "General timing and accounting informations for this job",
    "reached required accuracy",
)
ERROR_KEYWORDS = ("EEEE", "Error", "Segmentation fault", "forrtl: severe")
ENDED_STATUS_TOKENS = ("DONE", "EXIT", "COMPLETED", "FAILED", "CANCELLED")
FORCE_HEADER = "TOTAL-FORCE (eV/Angst)"
CON_DIR_RE = re.compile(r"^con(\d+)$")
MIN_IONIC_STEPS = 5
NEBEF_PL = "/data/gpfs03/mdye/VTST/vtstscripts/nebef.pl"


# ---------------------------------------------------------------------------
# 阈值配置
# ---------------------------------------------------------------------------

def load_thresholds() -> Dict[str, float]:
    """读取力收敛阈值，优先 VASP_CHECK_REGISTRY，缺省 0.02 / 0.01。"""
    candidates = [
        os.environ.get("VASP_CHECK_REGISTRY"),
        str(Path(__file__).resolve().parent / "check_registry.json"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 配置损坏时回退默认阈值
            continue
        section = data.get("force_convergence", data)
        thresholds = section.get("thresholds", section)
        max_force = thresholds.get(
            "max_force_threshold",
            thresholds.get("max_force", DEFAULT_THRESHOLDS["max_force_threshold"]),
        )
        rms_force = thresholds.get(
            "rms_force_threshold",
            thresholds.get("rms_force", DEFAULT_THRESHOLDS["rms_force_threshold"]),
        )
        return {
            "max_force_threshold": float(max_force),
            "rms_force_threshold": float(rms_force),
        }
    return dict(DEFAULT_THRESHOLDS)


def resolve_latest_output(remote_dir: str):
    """定位最新**有运行结果**的输出目录（续算 conN）。

    返回 (latest_subdir, status)；latest_subdir 为空串表示主目录。
    从最大编号 con* 开始，取第一个 OUTCAR 存在非空且离子步数大于
    MIN_IONIC_STEPS 的目录；con* 均无结果时回退主目录。
    """
    base = Path(remote_dir)
    if not base.is_dir():
        return "", ""
    cons = sorted(
        (
            p
            for p in base.iterdir()
            if p.is_dir() and CON_DIR_RE.fullmatch(p.name)
        ),
        key=lambda p: int(CON_DIR_RE.fullmatch(p.name).group(1)),
    )
    for con in reversed(cons):
        outcar = con / "OUTCAR"
        if not outcar.is_file() or outcar.stat().st_size == 0:
            continue
        try:
            text = outcar.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 单个目录读取失败继续检查
            continue
        # 结构优化已收敛（正常结束标志）：直接采用该目录，无需等待离子步数超过阈值
        if any(marker in text[-8192:] for marker in SUCCESS_MARKERS):
            return con.name, ""
        # 运行中但已有足够离子步（未收敛时要求步数超过 MIN_IONIC_STEPS）
        if text.count(FORCE_HEADER) > MIN_IONIC_STEPS:
            return con.name, ""
    return "", ""


def resolve_latest_con(remote_dir: str) -> str:
    """定位最新**续算目录**（最大编号 con*，存在即算，不要求输出）。

    用于作业提交等需要"最新目录"的场景（即使尚未运行）。
    无 con* 时返回空串（表示主目录）。
    """
    base = Path(remote_dir)
    if not base.is_dir():
        return ""
    cons = sorted(
        (
            p
            for p in base.iterdir()
            if p.is_dir() and CON_DIR_RE.fullmatch(p.name)
        ),
        key=lambda p: int(CON_DIR_RE.fullmatch(p.name).group(1)),
    )
    return cons[-1].name if cons else ""


def _neb_latest_output_dir(remote_dir: str) -> str:
    """NEB 最新**有结果**目录（逐级回退）。

    判定标准：目录内存在**中间映像**（编号 0 < img < max）的 OUTCAR——
    端点 OUTCAR 可能是创建 NEB 文件时从 IS/FS 复制来的伪结果，不代表 NEB 运行过。
    从最大编号 conN 向前回退，直到主目录；均无结果返回空串。
    """
    base = Path(remote_dir)
    if not base.is_dir():
        return ""

    def _has_result(directory: Path) -> bool:
        nums = sorted(
            int(p.name)
            for p in directory.iterdir()
            if p.is_dir() and p.name.isdigit()
        )
        if len(nums) < 3:
            return False
        lo, hi = nums[0], nums[-1]
        for p in directory.iterdir():
            if p.is_dir() and p.name.isdigit() and lo < int(p.name) < hi:
                if (p / "OUTCAR").is_file():
                    return True
        return False

    cons = sorted(
        (
            p
            for p in base.iterdir()
            if p.is_dir() and CON_DIR_RE.fullmatch(p.name)
        ),
        key=lambda p: int(CON_DIR_RE.fullmatch(p.name).group(1)),
    )
    for con in reversed(cons):
        if _has_result(con):
            return str(con)
    if _has_result(base):
        return str(base)
    return ""


# ---------------------------------------------------------------------------
# 队列查询
# ---------------------------------------------------------------------------

def run_bjobs(job_id: str) -> str:
    """执行 bjobs -l，返回归一化的队列状态标记。

    标记取值：PEND / RUN / SSUSP（含 PSUSP、USUSP，统一按挂起处理）/
    DONE / EXIT / COMPLETED / FAILED / CANCELLED / NOT_FOUND / UNKNOWN。

    注意：作业名较长时 bjobs -l 会把 "Status <RUN>" 折行成
    "Status <RU\\n                     N>"，因此解析前先把输出压缩为单行，
    再提取 Status <> 字段（避免 \bRUN\b 因折行匹配不到）。
    """
    if os.environ.get("VASP_BATCH_NO_BJOBS"):
        return "UNKNOWN"
    try:
        proc = subprocess.run(
            ["bjobs", "-l", job_id],
            capture_output=True,
            text=True,
            timeout=BJOB_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "UNKNOWN"
    output = proc.stdout + proc.stderr
    compact = re.sub(r"\s+", " ", output)
    m = re.search(r"Status\s*<\s*([^>]+?)\s*>", compact)
    if m:
        status = re.sub(r"\s+", "", m.group(1)).upper()
        if status == "PEND":
            return "PEND"
        if status == "RUN":
            return "RUN"
        if status in ("SSUSP", "PSUSP", "USUSP"):
            return "SSUSP"
        if status in ENDED_STATUS_TOKENS:
            return status
    # 兜底：压缩文本中的关键字匹配（兼容无 Status<> 字段的输出）
    if re.search(r"\bPEND\b", compact):
        return "PEND"
    if re.search(r"\bRUN\b", compact):
        return "RUN"
    if re.search(r"\b(SSUSP|PSUSP|USUSP)\b", compact):
        return "SSUSP"
    for token in ENDED_STATUS_TOKENS:
        if token in compact:
            return token
    if proc.returncode != 0 or "not found" in output.lower():
        return "NOT_FOUND"
    return "UNKNOWN"


def match_job_id_by_cwd(remote_dir: str, work_dir: str) -> Tuple[str, bool]:
    """无 job_id 时，从 bjobs 全量作业中按提交目录（exec_cwd）匹配。

    作业名管理混乱不可靠，故仅按提交目录匹配：仅匹配任务**最新输出目录**
    （conN 或主目录）；该目录无对应作业时不向前追溯（交由 OUTCAR 判定）。

    返回 (job_id, bjobs_ok)：bjobs_ok=False 表示 bjobs 不可用/超时（离线模拟），
    此时无法判断作业是否仍在运行，OUTCAR 已有离子步时维持 running。
    """
    if os.environ.get("VASP_BATCH_NO_BJOBS"):
        return "", False
    candidates = {str(work_dir).rstrip("/")}
    try:
        proc = subprocess.run(
            ["bjobs", "-o", "jobid exec_cwd"],
            capture_output=True,
            text=True,
            timeout=BJOB_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "", False
    if proc.returncode != 0:
        return "", False
    lines = (proc.stdout or "").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        cwd = parts[1].strip().rstrip("/")
        if cwd in candidates:
            return parts[0].strip(), True
    return "", True


# ---------------------------------------------------------------------------
# OUTCAR 解析
# ---------------------------------------------------------------------------

def extract_toten(text: str) -> Optional[float]:
    """提取所有 TOTEN 能量行中的最后一个值。"""
    last_value: Optional[float] = None
    for line in text.splitlines():
        if "free" not in line or "TOTEN" not in line or "=" not in line:
            continue
        parts = line.split()
        for index, part in enumerate(parts):
            if part == "=" and index + 1 < len(parts):
                try:
                    last_value = float(parts[index + 1])
                except ValueError:
                    pass
                break
    return round(last_value, 8) if last_value is not None else None


def parse_total_force_blocks(text: str) -> List[Dict[str, Any]]:
    """解析 OUTCAR 中所有 TOTAL-FORCE 块，返回 [{energy, forces: [...]}]。

    VASP OUTCAR 中每个离子步先输出力块，随后才输出该步的 TOTEN 能量行，
    因此力块能量采用向后扫描：取力块之后、下一个力块之前的第一个 TOTEN 行。
    """
    blocks: List[Dict[str, Any]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if FORCE_HEADER in line:
            index += 2  # 跳过列标题行（x y z fx fy fz）
            forces: List[Tuple[float, float, float]] = []
            while index < len(lines):
                parts = lines[index].split()
                if len(parts) < 6:
                    break
                try:
                    forces.append((float(parts[3]), float(parts[4]), float(parts[5])))
                except ValueError:
                    break
                index += 1
            energy: Optional[float] = None
            scan = index
            while scan < len(lines):
                candidate = lines[scan]
                if FORCE_HEADER in candidate:
                    break
                if "free" in candidate and "TOTEN" in candidate and "=" in candidate:
                    energy = extract_toten(candidate)
                    break
                scan += 1
            blocks.append({"energy": energy, "forces": forces})
            continue
        index += 1
    return blocks


def parse_poscar_fixed(poscar_path: Path) -> Optional[List[bool]]:
    """解析 POSCAR，返回每个原子是否固定（任一方向标记为 F 即固定）。"""
    if not poscar_path.is_file():
        return None
    lines = [line.strip() for line in poscar_path.read_text(encoding="utf-8").splitlines()]

    def _strip_comment(raw: str) -> str:
        for marker in ("#", "!"):
            position = raw.find(marker)
            if position != -1:
                raw = raw[:position]
        return raw

    n_atoms: Optional[int] = None
    counts_index: Optional[int] = None
    for index in range(5, min(len(lines), 12)):
        parts = _strip_comment(lines[index]).split()
        if parts and all(p.lstrip("+-").isdigit() for p in parts):
            counts_index = index
            n_atoms = sum(int(p) for p in parts)
            break
    if n_atoms is None:
        return None

    coord_index: Optional[int] = None
    for index in range(counts_index + 1, len(lines)):
        tokens = lines[index].lower().split()
        if tokens and tokens[0] in ("direct", "cartesian", "d", "c"):
            coord_index = index
            break
    if coord_index is None:
        return None

    has_selective = any(
        lines[index].lower().startswith("selective")
        for index in range(counts_index + 1, coord_index)
    )

    fixed: List[bool] = []
    for line in lines[coord_index + 1 :]:
        if not line:
            continue
        parts = line.split()
        try:
            float(parts[0])
        except (ValueError, IndexError):
            break
        if has_selective:
            flags = [part.upper() for part in parts[3:6] if part.upper() in ("T", "F")]
            fixed.append(any(flag == "F" for flag in flags))
        else:
            fixed.append(False)
        if len(fixed) >= n_atoms:
            break
    return fixed


def compute_force_stats(
    forces: List[Tuple[float, float, float]],
    fixed_flags: Optional[List[bool]],
) -> Optional[Tuple[float, float]]:
    """计算活动原子的最大力与 RMS 力；无活动原子返回 None。"""
    active = []
    for index, force in enumerate(forces):
        if fixed_flags and index < len(fixed_flags) and fixed_flags[index]:
            continue
        active.append(force)
    if not active:
        return None
    components = [abs(c) for force in active for c in force]
    max_force = max(components)
    rms_force = (sum(c * c for c in components) / len(components)) ** 0.5
    return round(max_force, 6), round(rms_force, 6)


# ---------------------------------------------------------------------------
# 单任务检查
# ---------------------------------------------------------------------------

def _new_result(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "remote_dir": str(task.get("remote_dir", "")),
        # job_id 由本任务检查按最新输出目录匹配得到，不沿用数据库旧值
        "job_id": "",
        "task_type": str(task.get("task_type", "")),
        "model_name": str(task.get("model_name", "")),
        "project_name": str(task.get("project_name", "")),
        "queue_status": "UNKNOWN",
        "status": "pending",
        "last_energy": None,
        "force_max": None,
        "force_rms": None,
        "force_converged": None,
        "force_history": None,
        "error_messages": [],
        "current_output": None,
    }


def _local_remote_dir(remote_dir: str) -> str:
    """本地模拟时把远程目录映射到 VASP_BATCH_LOCAL_ROOT 下的本地路径。"""
    root = os.environ.get("VASP_BATCH_LOCAL_ROOT")
    if root:
        return str(Path(root) / str(remote_dir).lstrip("/"))
    return remote_dir


def _analyze_outcar(
    result: Dict[str, Any],
    remote_dir: str,
    task_type: str,
    thresholds: Dict[str, float],
    poscar_dir: str = "",
    allow_running: bool = False,
) -> None:
    outcar_path = Path(remote_dir) / "OUTCAR"
    if not outcar_path.is_file() or not os.access(outcar_path, os.R_OK):
        result["status"] = "zombied"
        result["error_messages"].append("OUTCAR not found or unreadable")
        return
    try:
        text = outcar_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        result["status"] = "zombied"
        result["error_messages"].append(f"OUTCAR read error: {e}")
        return

    result["last_energy"] = extract_toten(text)
    if any(marker in text for marker in SUCCESS_MARKERS):
        result["status"] = "completed"
    elif any(keyword in text for keyword in ERROR_KEYWORDS):
        result["status"] = "zombied"
        matched = [k for k in ERROR_KEYWORDS if k in text]
        result["error_messages"].append(f"matched error keyword(s): {', '.join(matched)}")
    else:
        # 仅无 job_id（无法查询 bjobs）时，OUTCAR 已有离子步视为运行中；
        # 有 job_id 且 bjobs 已查不到作业（已结束）时，无正常结束标志即判定异常
        if allow_running and parse_total_force_blocks(text):
            result["status"] = "running"
        else:
            result["status"] = "zombied"
            result["error_messages"].append("Job ended without normal termination")

    if task_type == "opt":
        _parse_forces(result, poscar_dir or remote_dir, text, thresholds)
    # 已完成但力未收敛 -> 未收敛
    if (
        task_type == "opt"
        and result.get("status") == "completed"
        and result.get("force_converged") is False
    ):
        result["status"] = "unconverged"
        result["error_messages"].append(
            "calculation finished but forces not converged"
        )


def _parse_forces(
    result: Dict[str, Any],
    remote_dir: str,
    outcar_text: str,
    thresholds: Dict[str, float],
) -> None:
    blocks = parse_total_force_blocks(outcar_text)
    if not blocks:
        result["force_history"] = []
        return

    fixed_flags: Optional[List[bool]] = []
    poscar_path = Path(remote_dir) / "POSCAR"
    if poscar_path.is_file():
        try:
            fixed_flags = parse_poscar_fixed(poscar_path)
        except Exception as e:  # noqa: BLE001
            fixed_flags = None
            result["error_messages"].append(f"POSCAR parse error: {e}")
    else:
        fixed_flags = None
        result["error_messages"].append("POSCAR not found or unreadable")

    history = []
    for index, block in enumerate(blocks, start=1):
        stats = compute_force_stats(block["forces"], fixed_flags)
        history.append(
            {
                "step": index,
                "energy": block["energy"],
                "max_force": stats[0] if stats else None,
            }
        )
    result["force_history"] = history

    if fixed_flags is None:
        return
    final_stats = compute_force_stats(blocks[-1]["forces"], fixed_flags)
    if final_stats is None:
        result["error_messages"].append("No active atoms for force calculation")
        return
    max_force, rms_force = final_stats
    result["force_max"] = max_force
    result["force_rms"] = rms_force
    result["force_converged"] = (
        max_force < thresholds["max_force_threshold"]
        and rms_force < thresholds["rms_force_threshold"]
    )


def _analyze_neb_status(result: Dict[str, Any], remote_dir: str) -> None:
    """NEB 任务结束后的状态判定：按映像 OUTCAR 判断，而不是主目录 OUTCAR。

    规则（与结构优化一致的前提：bjobs 已无活跃作业）：
    - 中间映像（非端点）没有任何 OUTCAR -> pending（待提交，任务还没开始运行）；
    - 所有中间映像 OUTCAR 均正常结束（含成功标志）-> completed；
    - 有结果但存在缺失/无结束标志的映像 -> zombied，并列出具体映像。
    端点（00/NN）的 OUTCAR 是创建 NEB 文件时从 IS/FS 复制的伪结果，不参与判定。
    """
    neb_dir = _neb_latest_output_dir(remote_dir)
    if not neb_dir:
        result["status"] = "pending"
        return
    base = Path(neb_dir)
    names = sorted(
        (p.name for p in base.iterdir() if p.is_dir() and p.name.isdigit()),
        key=int,
    )
    if len(names) < 3:
        result["status"] = "zombied"
        result["error_messages"].append("NEB 映像目录不足（少于 3 个），无法判定完成状态")
        return
    lo, hi = names[0], names[-1]
    middle = [n for n in names if lo < n < hi]
    missing: List[str] = []
    unfinished: List[str] = []
    for img in middle:
        outcar = base / img / "OUTCAR"
        if not outcar.is_file() or outcar.stat().st_size == 0:
            missing.append(img)
            continue
        try:
            text = outcar.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 单个映像读取失败按缺失处理
            missing.append(img)
            continue
        if not any(marker in text for marker in SUCCESS_MARKERS):
            unfinished.append(img)
    if not missing and not unfinished:
        result["status"] = "completed"
        try:
            text = (base / lo / "OUTCAR").read_text(
                encoding="utf-8", errors="replace"
            )
            result["last_energy"] = extract_toten(text)
        except Exception:  # noqa: BLE001 - 能量读取失败不影响状态
            pass
    else:
        result["status"] = "zombied"
        if missing:
            result["error_messages"].append(
                f"NEB 中间映像 OUTCAR 缺失或为空：{', '.join(missing)}"
            )
        if unfinished:
            result["error_messages"].append(
                f"NEB 中间映像无正常结束标志：{', '.join(unfinished)}"
            )


def check_task(task: Dict[str, Any], thresholds: Dict[str, float]) -> Dict[str, Any]:
    """检查单个任务，任何异常只写入 error_messages，不影响其他任务。"""
    result = _new_result(task)
    try:
        remote_dir = _local_remote_dir(str(task.get("remote_dir", "")))
        task_type = str(task.get("task_type", ""))
        # 定位最新输出目录（续算 conN 优先），OUTCAR/OSZICAR/CONTCAR 从该目录读取
        latest_dir, _ = resolve_latest_output(remote_dir)
        # 最新续算目录（最大编号 conN，存在即算）：作业匹配与状态判定以此为准
        latest_con = resolve_latest_con(remote_dir)
        con_dir = str(Path(remote_dir) / latest_con) if latest_con else remote_dir
        work_dir = str(Path(remote_dir) / latest_dir) if latest_dir else remote_dir
        result["current_output"] = {
            "latest_dir": latest_dir or None,
            "dir": work_dir,
            "contcar_path": f"{work_dir}/CONTCAR",
            "outcar_path": f"{work_dir}/OUTCAR",
            "oszicar_path": f"{work_dir}/OSZICAR",
        }
        # NEB 任务：最新输出目录用"含中间映像 OUTCAR"的有结果目录（逐级回退），
        # 而不是主目录（端点 OUTCAR 可能来自 IS/FS 复制）
        if task_type == "neb":
            neb_out_dir = _neb_latest_output_dir(remote_dir)
            if neb_out_dir:
                neb_rel = (
                    Path(neb_out_dir).name
                    if Path(neb_out_dir) != Path(remote_dir)
                    else None
                )
                result["current_output"] = {
                    "latest_dir": neb_rel,
                    "dir": neb_out_dir,
                    "contcar_path": f"{neb_out_dir}/CONTCAR",
                    "outcar_path": f"{neb_out_dir}/OUTCAR",
                    "oszicar_path": f"{neb_out_dir}/OSZICAR",
                }
        outcar_path = Path(work_dir) / "OUTCAR"

        # 以最新续算目录为准匹配作业（续算推进到新 conN 后，作业在新目录提交）
        job_id, bjobs_ok = match_job_id_by_cwd(remote_dir, con_dir)
        if job_id:
            result["job_id"] = job_id
        else:
            # exec_cwd 匹配不到（如手动提交、LSF 无 cwd 信息）时，
            # 回退检查数据库已有作业号是否仍活跃（PEND/RUN/SSUSP）
            db_job = str(task.get("job_id") or "")
            if db_job:
                db_status = run_bjobs(db_job)
                result["queue_status"] = db_status
                if db_status in ("PEND", "RUN", "SSUSP"):
                    job_id = db_job
                    result["job_id"] = db_job
                elif db_status != "UNKNOWN":
                    # bjobs 可查询且该作业已结束（DONE/EXIT/...）：确认无活跃作业
                    bjobs_ok = True

        if not job_id:
            # 最新续算目录无对应作业：OUTCAR 为空/不存在 -> 待提交；
            # OUTCAR 非空 -> 不关联 job_id，按该目录 OUTCAR 分析。
            # allow_running 仅当 bjobs 不可用（离线/超时）时为 True：
            # bjobs 可查询且查不到活跃作业说明作业已结束/停止，按结束态分析
            # （无正常结束标志 -> zombied），不能再维持 running。
            if task_type == "neb":
                # NEB：OUTCAR 在映像子目录，按映像判定（无结果 -> 待提交）
                _analyze_neb_status(result, remote_dir)
            else:
                con_outcar = Path(con_dir) / "OUTCAR"
                if con_outcar.is_file() and con_outcar.stat().st_size > 0:
                    _analyze_outcar(
                        # 固定原子标志必须取自最新输出目录（conN）自身的 POSCAR：
                        # 主目录 POSCAR 可能缺少 Selective dynamics，会把固定原子算进活动原子
                        result,
                        con_dir,
                        task_type,
                        thresholds,
                        poscar_dir=con_dir,
                        allow_running=not bjobs_ok,
                    )
                else:
                    result["status"] = "pending"
        else:
            queue_status = run_bjobs(job_id)
            result["queue_status"] = queue_status
            if queue_status == "PEND":
                result["status"] = "queued"
            elif queue_status == "RUN":
                result["status"] = "running"
                # 运行中也解析 OUTCAR：回传最近能量 + 力历史（供详情能量/力曲线）
                if outcar_path.is_file() and outcar_path.stat().st_size > 0:
                    try:
                        text = outcar_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:  # noqa: BLE001 - 解析失败不影响状态
                        text = ""
                    result["last_energy"] = extract_toten(text)
                    _parse_forces(result, work_dir, text, thresholds)
            elif queue_status == "SSUSP":
                # 作业被挂起：仍在 LSF 中存活，按运行中处理（队列状态显示“挂起”）
                result["status"] = "running"
                if outcar_path.is_file() and outcar_path.stat().st_size > 0:
                    try:
                        text = outcar_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        text = ""
                    result["last_energy"] = extract_toten(text)
                    _parse_forces(result, work_dir, text, thresholds)
            else:
                if task_type == "neb":
                    # NEB：作业已结束，按映像 OUTCAR 判定完成状态
                    _analyze_neb_status(result, remote_dir)
                else:
                    _analyze_outcar(
                        result,
                        work_dir,
                        task_type,
                        thresholds,
                        poscar_dir=work_dir,
                        allow_running=False,
                    )

        # NEB 过渡态：运行 nebef.pl 解析各映像受力/能量/相对能垒
        if task_type == "neb":
            nebef_dir = _neb_latest_output_dir(remote_dir)
            if nebef_dir:
                try:
                    proc = subprocess.run(
                        ["perl", NEBEF_PL],
                        # 最新**有结果**目录（含中间映像 OUTCAR 的 conN 或主目录）
                        cwd=nebef_dir,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=120,
                    )
                    images = []
                    for line in (proc.stdout + proc.stderr).splitlines():
                        m = re.match(
                            r"^\s*(\d+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)",
                            line,
                        )
                        if m:
                            images.append(
                                {
                                    "label": m.group(1),
                                    "max_force": float(m.group(2)),
                                    "energy": float(m.group(3)),
                                    "relative": float(m.group(4)),
                                }
                            )
                    result["neb_barrier"] = {"images": images} if images else None
                except Exception:  # noqa: BLE001 - nebef.pl 运行失败不影响状态
                    result["neb_barrier"] = None
            else:
                result["neb_barrier"] = None
    except Exception as e:  # noqa: BLE001 - 单任务容错
        result["error_messages"].append(f"unexpected error: {e}")
        if result["status"] in ("pending",) and result["queue_status"] == "UNKNOWN":
            result["status"] = "zombied"
    return result


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) != 3:
        print(
            f"Usage: python3 {Path(sys.argv[0]).name} <input.json> <output.json>",
            file=sys.stderr,
        )
        return 2
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    try:
        tasks = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"Failed to read input file: {e}", file=sys.stderr)
        return 1
    if not isinstance(tasks, list):
        print("Input file must be a JSON array", file=sys.stderr)
        return 1

    thresholds = load_thresholds()
    results = [check_task(task, thresholds) for task in tasks]
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"checked {len(results)} tasks -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
