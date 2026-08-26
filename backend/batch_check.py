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
    """在任务目录下定位最新有效输出目录（续算 conN）。

    返回 (latest_subdir, status)；latest_subdir 为空串表示主目录。
    从最大编号 con* 开始，第一个 OUTCAR 末尾含正常结束标志的即为最新输出。
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
        if not outcar.is_file():
            continue
        try:
            tail = outcar.read_text(encoding="utf-8", errors="replace")[-8192:]
        except Exception:  # noqa: BLE001 - 单个目录读取失败继续检查
            continue
        if any(marker in tail for marker in SUCCESS_MARKERS):
            return con.name, "finished"
    return "", ""


# ---------------------------------------------------------------------------
# 队列查询
# ---------------------------------------------------------------------------

def run_bjobs(job_id: str) -> str:
    """执行 bjobs -l，返回归一化的队列状态标记。

    标记取值：PEND / RUN / SSUSP（含 PSUSP、USUSP，统一按挂起处理）/
    DONE / EXIT / COMPLETED / FAILED / CANCELLED / NOT_FOUND / UNKNOWN。
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
    if "Status <PEND>" in output or re.search(r"\bPEND\b", output):
        return "PEND"
    if "Status <RUN>" in output or re.search(r"\bRUN\b", output):
        return "RUN"
    # 挂起：SSUSP（系统挂起）/ PSUSP（排队挂起）/ USUSP（用户挂起）
    if (
        "Status <SSUSP>" in output
        or "Status <PSUSP>" in output
        or "Status <USUSP>" in output
        or re.search(r"\b(SSUSP|PSUSP|USUSP)\b", output)
    ):
        return "SSUSP"
    for token in ENDED_STATUS_TOKENS:
        if token in output:
            return token
    if proc.returncode != 0 or "not found" in output.lower():
        return "NOT_FOUND"
    return "UNKNOWN"


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
        "job_id": task.get("job_id") or "",
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


def check_task(task: Dict[str, Any], thresholds: Dict[str, float]) -> Dict[str, Any]:
    """检查单个任务，任何异常只写入 error_messages，不影响其他任务。"""
    result = _new_result(task)
    try:
        job_id = task.get("job_id") or ""
        remote_dir = _local_remote_dir(str(task.get("remote_dir", "")))
        task_type = str(task.get("task_type", ""))
        # 定位最新输出目录（续算 conN 优先），OUTCAR/OSZICAR/CONTCAR 从该目录读取
        latest_dir, _ = resolve_latest_output(remote_dir)
        work_dir = str(Path(remote_dir) / latest_dir) if latest_dir else remote_dir
        result["current_output"] = {
            "latest_dir": latest_dir or None,
            "dir": work_dir,
            "contcar_path": f"{work_dir}/CONTCAR",
            "outcar_path": f"{work_dir}/OUTCAR",
            "oszicar_path": f"{work_dir}/OSZICAR",
        }
        outcar_path = Path(work_dir) / "OUTCAR"

        if not job_id:
            if outcar_path.is_file():
                _analyze_outcar(
                    # 固定原子标志必须取自最新输出目录（conN）自身的 POSCAR：
                    # 主目录 POSCAR 可能缺少 Selective dynamics，会把固定原子算进活动原子
                    result, work_dir, task_type, thresholds, poscar_dir=work_dir
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
            elif queue_status == "SSUSP":
                # 作业被挂起：仍在 LSF 中存活，按运行中处理（队列状态显示“挂起”）
                result["status"] = "running"
            else:
                _analyze_outcar(
                    result, work_dir, task_type, thresholds, poscar_dir=work_dir
                )
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
