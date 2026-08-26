"""结构分析：读取本地 INCAR/POSCAR/CONTCAR 进行晶格或原子位移分析。

- ISIF=2（VASP 默认，多数结构优化场景）：晶格固定、仅离子弛豫，
  晶格参数对比无意义 -> 改为计算 POSCAR -> CONTCAR 的原子位移
  （最大 / RMS / 平均位移）；
- ISIF 为其他值（如 3）：晶格可变化 -> 显示晶格参数与体积对比。
- ISIF 从本地 files/INCAR 读取；本地未同步 INCAR 时按 VASP 默认 2。
"""

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from task_paths import task_files_dir


# ---------------------------------------------------------------------------
# 晶格
# ---------------------------------------------------------------------------

def _scaled_matrix(text: str) -> Optional[List[List[float]]]:
    """解析 POSCAR/CONTCAR 的缩放后晶格矩阵；失败返回 None。"""
    lines = text.splitlines()
    if len(lines) < 5:
        return None
    try:
        scale = float(lines[1].split()[0])
        matrix = [[float(x) for x in lines[i].split()[:3]] for i in (2, 3, 4)]
        if scale < 0:
            scale = abs(scale) / abs(_det3(matrix)) ** (1.0 / 3.0)
        return [[scale * c for c in row] for row in matrix]
    except (ValueError, IndexError, ZeroDivisionError):
        return None


def _det3(m: List[List[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _norm(v: List[float]) -> float:
    return math.sqrt(sum(c * c for c in v))


def _angle_deg(v1: List[float], v2: List[float]) -> float:
    cos = sum(a * b for a, b in zip(v1, v2)) / (_norm(v1) * _norm(v2) or 1.0)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def parse_lattice(text: str) -> Optional[Dict[str, float]]:
    """解析晶格向量，返回 a/b/c、α/β/γ、体积。"""
    m = _scaled_matrix(text)
    if m is None:
        return None
    try:
        a, b, c = _norm(m[0]), _norm(m[1]), _norm(m[2])
        return {
            "a": round(a, 4),
            "b": round(b, 4),
            "c": round(c, 4),
            "alpha": round(_angle_deg(m[1], m[2]), 3),
            "beta": round(_angle_deg(m[0], m[2]), 3),
            "gamma": round(_angle_deg(m[0], m[1]), 3),
            "volume": round(abs(_det3(m)), 3),
        }
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# 原子坐标 / 位移
# ---------------------------------------------------------------------------

def _strip_comment(raw: str) -> str:
    for marker in ("#", "!"):
        position = raw.find(marker)
        if position != -1:
            raw = raw[:position]
    return raw


def _atom_count(lines: List[str]) -> Optional[Tuple[int, int]]:
    """返回 (原子总数, 计数行索引)。"""
    for index in range(5, min(len(lines), 12)):
        parts = _strip_comment(lines[index]).split()
        if parts and all(p.lstrip("+-").isdigit() for p in parts):
            return sum(int(p) for p in parts), index
    return None


def parse_positions(text: str, matrix: List[List[float]]) -> Optional[List[List[float]]]:
    """解析原子笛卡尔坐标（Direct 坐标经晶格矩阵转换）。"""
    lines = text.splitlines()
    count = _atom_count(lines)
    if count is None:
        return None
    n_atoms, counts_index = count

    coord_index = None
    for index in range(counts_index + 1, len(lines)):
        tokens = lines[index].lower().split()
        if tokens and tokens[0] in ("direct", "cartesian", "d", "c"):
            coord_index = index
            mode = tokens[0]
            break
    if coord_index is None:
        return None

    positions: List[List[float]] = []
    for line in lines[coord_index + 1 :]:
        if not line.strip():
            continue
        parts = line.split()
        try:
            coords = [float(x) for x in parts[:3]]
        except (ValueError, IndexError):
            break
        if mode in ("direct", "d"):
            cart = [
                matrix[0][0] * coords[0] + matrix[0][1] * coords[1] + matrix[0][2] * coords[2],
                matrix[1][0] * coords[0] + matrix[1][1] * coords[1] + matrix[1][2] * coords[2],
                matrix[2][0] * coords[0] + matrix[2][1] * coords[1] + matrix[2][2] * coords[2],
            ]
            positions.append(cart)
        else:
            positions.append(coords)
        if len(positions) >= n_atoms:
            break
    return positions if len(positions) == n_atoms else None


def compute_displacements(
    poscar_text: str, contcar_text: str, matrix: List[List[float]]
) -> Optional[Dict[str, Any]]:
    """计算 POSCAR -> CONTCAR 每个原子的位移，返回最大/RMS/平均。"""
    p1 = parse_positions(poscar_text, matrix)
    p2 = parse_positions(contcar_text, matrix)
    if p1 is None or p2 is None or len(p1) != len(p2):
        return None
    distances = [_norm([b - a for a, b in zip(p1[i], p2[i])]) for i in range(len(p1))]
    if not distances:
        return None
    mean = sum(distances) / len(distances)
    rms = math.sqrt(sum(d * d for d in distances) / len(distances))
    return {
        "count": len(distances),
        "max": round(max(distances), 4),
        "rms": round(rms, 4),
        "mean": round(mean, 4),
    }


# ---------------------------------------------------------------------------
# ISIF
# ---------------------------------------------------------------------------

def read_isif(project: Dict[str, Any], task: Dict[str, Any]) -> Tuple[int, str]:
    """读取本地 files/INCAR 的 ISIF；本地未同步时按 VASP 默认 2。"""
    incar = task_files_dir(project["name"], task) / "INCAR"
    if incar.is_file():
        match = re.search(
            r"^\s*ISIF\s*=\s*(\d+)",
            incar.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        if match:
            return int(match.group(1)), "incar"
    return 2, "default"


def _pct(new_value: Optional[float], old_value: Optional[float]) -> Optional[float]:
    if new_value is None or old_value in (None, 0):
        return None
    return round((new_value - old_value) / abs(old_value) * 100, 3)


def analyze(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """结构分析：ISIF=2 时原子位移，其余情况晶格参数对比。"""
    files_dir = task_files_dir(project["name"], task)
    poscar_path = files_dir / "POSCAR"
    contcar_path = files_dir / "CONTCAR"
    warnings: List[str] = []

    isif, isif_source = read_isif(project, task)
    cell_fixed = isif in (0, 1, 2)

    poscar_text = contcar_text = None
    poscar = contcar = None
    if poscar_path.is_file():
        poscar_text = poscar_path.read_text(encoding="utf-8", errors="replace")
        poscar = parse_lattice(poscar_text)
        if poscar is None:
            warnings.append("POSCAR 晶格解析失败")
    if contcar_path.is_file():
        contcar_text = contcar_path.read_text(encoding="utf-8", errors="replace")
        contcar = parse_lattice(contcar_text)
        if contcar is None:
            warnings.append("CONTCAR 晶格解析失败")

    deltas = None
    displacements = None
    if poscar and contcar:
        if cell_fixed:
            matrix = _scaled_matrix(poscar_text or "")
            displacements = (
                compute_displacements(poscar_text or "", contcar_text or "", matrix)
                if matrix
                else None
            )
            if displacements is None:
                warnings.append("原子数不一致或坐标解析失败，无法计算位移")
        else:
            deltas = {
                "a_pct": _pct(contcar["a"], poscar["a"]),
                "b_pct": _pct(contcar["b"], poscar["b"]),
                "c_pct": _pct(contcar["c"], poscar["c"]),
                "volume_pct": _pct(contcar["volume"], poscar["volume"]),
            }

    skipped = None
    if not poscar_path.is_file() and not contcar_path.is_file():
        skipped = "结构文件缺失（POSCAR/CONTCAR 未同步）"

    return {
        "files": {
            "poscar": poscar_path.is_file(),
            "contcar": contcar_path.is_file(),
        },
        "isif": isif,
        "isif_source": isif_source,
        "cell_fixed": cell_fixed,
        "poscar": poscar,
        "contcar": contcar,
        "deltas": deltas,
        "displacements": displacements,
        "skipped": skipped,
        "warnings": warnings,
    }
