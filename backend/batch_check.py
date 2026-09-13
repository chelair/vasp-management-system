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
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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
# bjobs 结果缓存（同一轮巡检内复用，避免逐任务起子进程）
_BJOBS_DETAIL_CACHE: Dict[str, str] = {}
_BJOBS_CWD_TABLE: Optional[Dict[str, str]] = None
_PRECISION_REQUIREMENTS: Optional[Dict[str, Any]] = None
SUCCESS_MARKERS = (
    "General timing and accounting informations for this job",
    "reached required accuracy",
)
ERROR_KEYWORDS = ("EEEE", "Error", "Segmentation fault", "forrtl: severe")
ENDED_STATUS_TOKENS = ("DONE", "EXIT", "COMPLETED", "FAILED", "CANCELLED")
FORCE_HEADER = "TOTAL-FORCE (eV/Angst)"
CON_DIR_RE = re.compile(r"^con(\d+)$")
MIN_IONIC_STEPS = 5

# 精度检查默认要求（可被 check_registry.json 的 precision 段覆盖）
DEFAULT_PRECISION = {
    "enabled": True,
    "kmesh_min_product": 20.0,  # k 网格密度系数：k × 晶格常数 > 20
    "ediifg_max": -0.02,  # 力收敛精度：EDIFFG ≤ -0.02
    "ediff_max": 1e-5,  # 电子步收敛：EDIFF ≤ 1E-5
    # INCAR 未写 EDIFF/EDIFFG 时按 VASP 默认值（1E-4 / 能量判据）判定为不达标；
    # 设为 false 则视作"无法判定"，不计入不满足
    "treat_missing_as_default": True,
}
VASP_DEFAULT_EDIFF = 1e-4
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


def load_precision_requirements() -> Dict[str, Any]:
    """读取精度检查要求（check_registry.json 的 precision 段，缺省用默认要求）。"""
    candidates = [
        os.environ.get("VASP_CHECK_REGISTRY"),
        str(Path(__file__).resolve().parent / "check_registry.json"),
    ]
    requirements = dict(DEFAULT_PRECISION)
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 配置损坏时回退默认要求
            continue
        section = data.get("precision") or {}
        if isinstance(section, dict):
            for key in DEFAULT_PRECISION:
                if key in section:
                    requirements[key] = section[key]
        break
    return requirements


def _precision_requirements() -> Dict[str, Any]:
    """精度要求（同一轮巡检只读一次配置）。"""
    global _PRECISION_REQUIREMENTS
    if _PRECISION_REQUIREMENTS is None:
        _PRECISION_REQUIREMENTS = load_precision_requirements()
    return _PRECISION_REQUIREMENTS


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
        # 只读尾部 8KB 判正常结束；块数用分块扫描（OUTCAR 常上百 MB，整文件读太贵）
        tail = _read_tail(outcar, 8192)
        if tail is None:
            continue
        # 结构优化已收敛（正常结束标志）：直接采用该目录，无需等待离子步数超过阈值
        if any(marker in tail for marker in SUCCESS_MARKERS):
            return con.name, ""
        # 运行中但已有足够离子步（未收敛时要求步数超过 MIN_IONIC_STEPS）
        if _count_marker(outcar, FORCE_HEADER.encode(), cap=MIN_IONIC_STEPS) > MIN_IONIC_STEPS:
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

def _parse_bjobs_detail(output: str, returncode: int) -> str:
    """把 `bjobs -l`（单个作业，或批量输出里的一段）解析为归一化状态标记。

    标记取值：PEND / RUN / SSUSP（含 PSUSP、USUSP，统一按挂起处理）/
    DONE / EXIT / COMPLETED / FAILED / CANCELLED / NOT_FOUND / UNKNOWN。

    注意：作业名较长时 bjobs -l 会把 "Status <RUN>" 折行成
    "Status <RU\\n                     N>"，因此解析前先把输出压缩为单行，
    再提取 Status <> 字段（避免 \bRUN\b 因折行匹配不到）。
    """
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
    if returncode != 0 or "not found" in output.lower():
        return "NOT_FOUND"
    return "UNKNOWN"


def _split_bjobs_detail(output: str) -> Dict[str, str]:
    """把多个作业的 `bjobs -l` 输出按 `Job <id>` 切成 {job_id: 该作业段落}。"""
    blocks: Dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^Job <(\d+)>", output))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
        blocks[match.group(1)] = output[match.start() : end]
    return blocks


def prefetch_bjobs_details(job_ids: Iterable[str]) -> None:
    """一次性把多个作业的 `bjobs -l` 明细查回来（避免每任务一次子进程）。

    登录节点上每次 `bjobs` 子进程 + 调度器查询 50-500ms，几十个任务就是几十秒。
    这里按批（40 个一组）查询并缓存，`run_bjobs` 优先命中缓存，
    未命中的 job_id 仍走原来的单次查询逻辑，行为不变。
    """
    if os.environ.get("VASP_BATCH_NO_BJOBS"):
        return
    pending: List[str] = []
    for job_id in job_ids:
        text = str(job_id or "")
        if text and text not in _BJOBS_DETAIL_CACHE and text not in pending:
            pending.append(text)
    if not pending:
        return
    for start in range(0, len(pending), 40):
        batch = pending[start : start + 40]
        try:
            proc = subprocess.run(
                ["bjobs", "-l", *batch],
                capture_output=True,
                text=True,
                timeout=BJOB_TIMEOUT * 4,
            )
        except (subprocess.TimeoutExpired, OSError):
            return
        output = (proc.stdout or "") + (proc.stderr or "")
        blocks = _split_bjobs_detail(output)
        if not blocks:
            # 批量查询不可用（命令不存在/输出异常）：留给单次查询兜底
            return
        _BJOBS_DETAIL_CACHE.update(blocks)
        for job_id in batch:
            # 批量输出里没有的 job_id 说明调度器已查不到该作业
            _BJOBS_DETAIL_CACHE.setdefault(job_id, "")


def run_bjobs(job_id: str) -> str:
    """执行 bjobs -l，返回归一化的队列状态标记（优先用预取缓存）。"""
    if os.environ.get("VASP_BATCH_NO_BJOBS"):
        return "UNKNOWN"
    cached = _BJOBS_DETAIL_CACHE.get(str(job_id))
    if cached is not None:
        return _parse_bjobs_detail(cached, 1 if cached == "" else 0)
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
    _BJOBS_DETAIL_CACHE[str(job_id)] = output
    return _parse_bjobs_detail(output, proc.returncode)


def match_job_id_by_cwd(remote_dir: str, work_dir: str) -> Tuple[str, bool]:
    """无 job_id 时，从 bjobs 全量作业中按提交目录（exec_cwd）匹配。

    作业名管理混乱不可靠，故仅按提交目录匹配：仅匹配任务**最新输出目录**
    （conN 或主目录）；该目录无对应作业时不向前追溯（交由 OUTCAR 判定）。

    返回 (job_id, bjobs_ok)：bjobs_ok=False 表示 bjobs 不可用/超时（离线模拟），
    此时无法判断作业是否仍在运行，OUTCAR 已有离子步时维持 running。

    `bjobs -o jobid exec_cwd` 全量列表在同一轮巡检内只查一次（_bjobs_cwd_table），
    原来每个任务都跑一次子进程，几十个任务就是几十秒。
    """
    if os.environ.get("VASP_BATCH_NO_BJOBS"):
        return "", False
    table = _bjobs_cwd_table()
    if table is None:
        return "", False
    job_id = table.get(str(work_dir).rstrip("/"))
    return (job_id or "", True)


def _bjobs_cwd_table() -> Optional[Dict[str, str]]:
    """`bjobs -o "jobid exec_cwd"` 全量列表 → {exec_cwd: job_id}（只查一次）。

    返回 None 表示 bjobs 不可用/超时（与原来的 bjobs_ok=False 等价）。
    """
    global _BJOBS_CWD_TABLE
    if _BJOBS_CWD_TABLE is not None:
        return _BJOBS_CWD_TABLE or None
    try:
        proc = subprocess.run(
            ["bjobs", "-o", "jobid exec_cwd"],
            capture_output=True,
            text=True,
            timeout=BJOB_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        _BJOBS_CWD_TABLE = {}
        return None
    if proc.returncode != 0:
        _BJOBS_CWD_TABLE = {}
        return None
    table: Dict[str, str] = {}
    for line in (proc.stdout or "").splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        table[parts[1].strip().rstrip("/")] = parts[0].strip()
    _BJOBS_CWD_TABLE = table
    return table


# ---------------------------------------------------------------------------
# OUTCAR 解析
# ---------------------------------------------------------------------------


def parse_incar(path: Path) -> Dict[str, str]:
    """解析 INCAR 为 {KEY: 首个取值}（跳过注释；键统一大写）。

    只做"搬运"：判定规则不放远端。INCAR 就在我们已经在读的最新输出目录里，
    1KB 文本，读它不增加任何 exec / SFTP 往返。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split("!", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        token = value.strip().split()[0] if value.strip() else ""
        if key:
            values[key] = token
    return values


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    token = str(value).strip().strip("'\"").rstrip(".")
    if not token:
        return None
    for candidate in (token, token.replace("D", "E").replace("d", "e")):
        try:
            return float(candidate)
        except ValueError:
            continue
    return None


def parse_kpoints_mesh(path: Path) -> Tuple[Optional[List[int]], str]:
    """从 KPOINTS 读取显式 k 网格；Auto/不可判定时返回 (None, 说明)。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, "KPOINTS 缺失"
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("#", "!"))
    ]
    if len(lines) < 4:
        return None, "KPOINTS 格式不完整"
    mode = lines[2]
    parts = lines[3].split()
    if len(parts) < 3:
        return None, f"KPOINTS 网格行无法解析（{mode}）"
    try:
        mesh = [int(float(p)) for p in parts[:3]]
    except ValueError:
        return None, f"KPOINTS 不是自动网格（{mode}）"
    if all(m > 0 for m in mesh):
        return mesh, mode
    return None, f"KPOINTS 自动网格 0 0 0（{mode}，由 KSPACING 决定，无法直接判定）"


def parse_lattice_abc(path: Path) -> Optional[List[float]]:
    """从 POSCAR 读三个晶格常数（Å，已乘缩放系数）。"""
    try:
        lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return None
    if len(lines) < 5:
        return None
    try:
        scale = float(lines[1].split()[0])
        vectors = [[float(x) for x in lines[2 + i].split()[:3]] for i in range(3)]
    except (ValueError, IndexError):
        return None
    if any(len(v) < 3 for v in vectors):
        return None
    return [round(abs(scale) * math.sqrt(sum(c * c for c in v)), 4) for v in vectors]


def precision_check(
    incar: Dict[str, str],
    mesh: Optional[List[int]],
    lattice_abc: Optional[List[float]],
    mesh_note: str,
    requirements: Dict[str, Any],
) -> Dict[str, Any]:
    """按「k 网格密度 / 力收敛精度 / 电子步收敛」三项判精度高低。

    默认要求：k × 晶格常数 > 20、EDIFFG ≤ -0.02、EDIFF ≤ 1E-5；
    任一项不满足即 precision.ok=False（收敛判定降级为「低精度收敛」）。
    无法判定的项（如 Auto k 网格）记入 `undetermined`，不作为不满足处理。
    """
    if not requirements.get("enabled", True):
        return {"ok": True, "level": "ok", "issues": [], "undetermined": [], "values": {}}
    min_product = float(requirements["kmesh_min_product"])
    ediifg_max = float(requirements["ediifg_max"])
    ediff_max = float(requirements["ediff_max"])
    issues: List[str] = []
    undetermined: List[str] = []
    values: Dict[str, Any] = {}

    # ① k 网格密度系数 = k × 晶格常数（三个方向都要满足）
    if mesh and lattice_abc and len(mesh) == 3 and len(lattice_abc) == 3:
        products = [round(k * a, 2) for k, a in zip(mesh, lattice_abc)]
        values["kmesh_product"] = products
        values["kmesh"] = mesh
        values["lattice_abc"] = lattice_abc
        worst = min(products)
        if worst <= min_product:
            issues.append(
                f"k 网格密度系数 {worst:g} ≤ {min_product:g}"
                f"（k×晶格常数 {mesh[0]}×{lattice_abc[0]:g}…，要求 > {min_product:g}）"
            )
    else:
        undetermined.append(f"k 网格密度系数（{mesh_note or 'KPOINTS 未给显式网格'}）")

    # ② 力收敛精度：EDIFFG ≤ -0.02（负值才是力判据）
    treat_missing = bool(requirements.get("treat_missing_as_default", True))
    ediifg = _to_float(incar.get("EDIFFG"))
    values["ediifg"] = ediifg
    if ediifg is None:
        text = f"未设置 EDIFFG（VASP 默认按能量判据），不满足力收敛精度 ≤ {ediifg_max:g}"
        (issues if treat_missing else undetermined).append(text)
    elif ediifg > ediifg_max:
        issues.append(
            f"力收敛精度 EDIFFG={ediifg:g} 未达 {ediifg_max:g}"
            + ("（正值＝按能量判据）" if ediifg > 0 else "")
        )

    # ③ 电子步收敛：EDIFF ≤ 1E-5（未设置时按 VASP 默认 1E-4 计）
    ediff = _to_float(incar.get("EDIFF"))
    values["ediff"] = ediff if ediff is not None else VASP_DEFAULT_EDIFF
    values["ediff_from_default"] = ediff is None
    if values["ediff"] > ediff_max:
        text = (
            f"电子步收敛 EDIFF={values['ediff']:g}"
            + ("（未设置，按 VASP 默认 1E-4）" if ediff is None else "")
            + f" 未达 {ediff_max:g}"
        )
        if ediff is None and not treat_missing:
            undetermined.append(text)
        else:
            issues.append(text)

    return {
        "ok": not issues,
        "level": "ok" if not issues else "low",
        "issues": issues,
        "undetermined": undetermined,
        "values": values,
        "requirements": {
            "kmesh_min_product": min_product,
            "ediifg_max": ediifg_max,
            "ediff_max": ediff_max,
        },
    }


def force_thresholds_from_incar(
    incar: Dict[str, str], base: Dict[str, float]
) -> Tuple[Dict[str, float], str]:
    """结构优化的力收敛阈值来自 INCAR 的 EDIFFG（负值＝力判据，eV/Å）。

    VASP 的判定是「所有力分量 < |EDIFFG|」；本系统还额外看 RMS（历史口径），
    这里取 |EDIFFG|/2 作为 RMS 阈值，与原来 registry(0.02 / 0.01) 的比例一致，
    EDIFFG=-0.02 时与旧行为完全相同。EDIFFG 缺失或为正值（能量判据）时退回 registry。
    """
    ediifg = _to_float(incar.get("EDIFFG"))
    if ediifg is not None and ediifg < 0:
        value = abs(ediifg)
        return (
            {"max_force_threshold": value, "rms_force_threshold": value / 2},
            "incar:EDIFFG",
        )
    return (
        {
            "max_force_threshold": float(base.get("max_force_threshold", 0.02)),
            "rms_force_threshold": float(base.get("rms_force_threshold", 0.01)),
        },
        "registry",
    )

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
        # NEB：中间映像离子步最大值（用于与 opt 相同的 25 步结构分析触发）
        "neb_band_steps": None,
        "error_messages": [],
        "current_output": None,
        # INCAR / K 网格 / 晶格常数快照（思路 A：远端只搬运，不判定业务规则）
        "incar": None,
        "kpoints": None,
        "lattice_abc": None,
        "force_thresholds": None,
        "precision": None,
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


def _count_marker(path: Path, marker: bytes = b"TOTAL-FORCE", cap: Optional[int] = None) -> int:
    """分块统计文件中标记出现次数（OUTCAR 可能上百 MB，避免整体读入内存）。

    `cap` 给定时，超过该值立即返回（用于"是否达到 N 步"这类只关心阈值的判断，
    避免为一个大文件做完整扫描）；跨块边界用尾部重叠保证不漏计。
    """
    total = 0
    overlap = max(len(marker) - 1, 0)
    try:
        with path.open("rb") as fh:
            carry = b""
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                data = carry + chunk
                total += data.count(marker)
                if cap is not None and total > cap:
                    return total
                carry = data[-overlap:] if overlap else b""
    except OSError:
        return 0
    return total


def _read_tail(path: Path, size: int = 8192) -> Optional[str]:
    """只读文件尾部 `size` 字节（判正常结束标志用）；失败返回 None。"""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            length = fh.tell()
            fh.seek(max(0, length - size))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def _scan_outcar(path: Path) -> Optional[Tuple[int, bool]]:
    """单次分块扫描 OUTCAR：返回 (TOTAL-FORCE 块数, 是否含正常结束标志)。

    NEB 判定原来对每个映像"整文件读一次判结束 + 再扫一次数块"，这里合并成一遍，
    语义不变（结束标志仍是全文匹配，只是改为按块匹配）；读取失败返回 None。
    """
    marker = FORCE_HEADER.encode()
    overlap = max(len(marker), max(len(m) for m in SUCCESS_MARKERS)) - 1
    count = 0
    success = False
    try:
        with path.open("rb") as fh:
            carry = b""
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                data = carry + chunk
                count += data.count(marker)
                if not success:
                    success = any(m.encode() in data for m in SUCCESS_MARKERS)
                carry = data[-overlap:]
    except OSError:
        return None
    return count, success


def _count_neb_band_steps(remote_dir: str) -> int:
    """NEB 带推进步数：中间映像 OUTCAR 中 TOTAL-FORCE 块数的最大值。

    VTST 各映像同步推进，因此中间映像步数一致，取最大值即可代表整条带。
    端点是 IS/FS 的伪结果（复制自各自 opt），不计入。
    运行中的作业也会统计（结构分析要按 25 步桶定期抓映像结构）。
    """
    neb_dir = _neb_latest_output_dir(remote_dir)
    if not neb_dir:
        return 0
    base = Path(neb_dir)
    names = sorted(
        (p.name for p in base.iterdir() if p.is_dir() and p.name.isdigit()),
        key=int,
    )
    if len(names) < 3:
        return 0
    best = 0
    for img in names[1:-1]:
        outcar = base / img / "OUTCAR"
        if outcar.is_file() and outcar.stat().st_size > 0:
            best = max(best, _count_marker(outcar))
    return best


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
    # 中间映像的离子步：取各映像 OUTCAR 的 TOTAL-FORCE 块数最大值，
    # 作为「NEB 带推进了多少步」的度量（端点 OUTCAR 是 IS/FS 的伪结果，不计入）
    band_steps = 0
    for img in middle:
        outcar = base / img / "OUTCAR"
        if not outcar.is_file() or outcar.stat().st_size == 0:
            missing.append(img)
            continue
        # 一次分块扫描同时拿到「块数」与「是否有正常结束标志」，不再整文件读入
        scanned = _scan_outcar(outcar)
        if scanned is None:
            missing.append(img)
            continue
        blocks, finished = scanned
        band_steps = max(band_steps, blocks)
        if not finished:
            unfinished.append(img)
    result["neb_band_steps"] = band_steps
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

        # INCAR / KPOINTS / POSCAR 本来就在最新输出目录里（1KB 级文本），顺手读：
        # ① 结构优化的力收敛阈值改由 INCAR 的 EDIFFG 决定；
        # ② 做精度检查（k 网格密度 / EDIFFG / EDIFF）。
        # 全部复用同一次 exec，不新增任何 SSH 往返。
        incar = parse_incar(Path(work_dir) / "INCAR") or parse_incar(Path(remote_dir) / "INCAR")
        result["incar"] = incar or None
        used_thresholds = thresholds
        if task_type == "opt":
            used_thresholds, threshold_source = force_thresholds_from_incar(incar, thresholds)
            result["force_thresholds"] = {**used_thresholds, "source": threshold_source}
            mesh, mesh_note = parse_kpoints_mesh(Path(work_dir) / "KPOINTS")
            if mesh is None:
                mesh, mesh_note = parse_kpoints_mesh(Path(remote_dir) / "KPOINTS")
            lattice_abc = parse_lattice_abc(Path(work_dir) / "POSCAR") or parse_lattice_abc(
                Path(remote_dir) / "POSCAR"
            )
            result["kpoints"] = {"mesh": mesh, "note": mesh_note}
            result["lattice_abc"] = lattice_abc
            result["precision"] = precision_check(
                incar, mesh, lattice_abc, mesh_note, _precision_requirements()
            )
        else:
            # 其他任务类型只留 INCAR 快照，不改判定逻辑
            result["force_thresholds"] = {**thresholds, "source": "registry"}

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
                        used_thresholds,
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
                    _parse_forces(result, work_dir, text, used_thresholds)
            elif queue_status == "SSUSP":
                # 作业被挂起：仍在 LSF 中存活，按运行中处理（队列状态显示“挂起”）
                result["status"] = "running"
                if outcar_path.is_file() and outcar_path.stat().st_size > 0:
                    try:
                        text = outcar_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        text = ""
                    result["last_energy"] = extract_toten(text)
                    _parse_forces(result, work_dir, text, used_thresholds)
            else:
                if task_type == "neb":
                    # NEB：作业已结束，按映像 OUTCAR 判定完成状态
                    _analyze_neb_status(result, remote_dir)
                else:
                    _analyze_outcar(
                        result,
                        work_dir,
                        task_type,
                        used_thresholds,
                        poscar_dir=work_dir,
                        allow_running=False,
                    )

        # NEB 过渡态：运行 nebef.pl 解析各映像受力/能量/相对能垒
        if task_type == "neb":
            # 无论作业是否在跑都统计「带推进步数」：巡检据此按 25 步桶同步映像结构
            if result.get("neb_band_steps") is None:
                result["neb_band_steps"] = _count_neb_band_steps(remote_dir)
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

    # 精度检查：结构优化已（按 INCAR 的 EDIFFG）收敛，但精度不达标 -> 低精度收敛
    if result.get("task_type") == "opt" and result.get("status") == "completed":
        precision = result.get("precision") or {}
        if precision and precision.get("ok") is False:
            result["status"] = "low_precision"
            result["convergence"] = "low_precision"
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
    # 预取作业信息：先拿一次「cwd → job_id」全量表，再把库里的 job_id 与该表的
    # job_id 一起批量查明细（`bjobs -l id1 id2 ...`），避免每个任务各起一个子进程
    cwd_table = _bjobs_cwd_table() or {}
    prefetch_bjobs_details(
        [str(task.get("job_id") or "") for task in tasks if isinstance(task, dict)]
        + list(cwd_table.values())
    )
    results = [check_task(task, thresholds) for task in tasks]
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"checked {len(results)} tasks -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
