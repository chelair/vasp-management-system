"""CIF → POSCAR 转换（零依赖，只用标准库）。

用途：「导入 POSCAR」支持 .cif（Materials Project / ICSD / VESTA / OQMD 等导出的
结构文件），前端把 CIF 文本发过来，这里转成 VASP POSCAR 文本再走原有导入流程。

覆盖常见写法：

- 晶胞参数带不确定度：`_cell_length_a  5.430(2)`；
- 分数坐标 `_atom_site_fract_x/y/z`，或笛卡尔坐标 `_atom_site_Cartn_x/y/z`（自动换算）；
- 只给不对称单元 + 对称操作（`_symmetry_equiv_pos_as_xyz` 或
  `_space_group_symop_operation_xyz`，支持 `1/2+x` 这类平移）→ 按对称操作展开；
- 元素列优先 `_atom_site_type_symbol`，没有就从标签推（`O1` → O，`Fe2+` → Fe）；
- 占据数不是 1 的原子照留但给 warning（POSCAR 表达不了部分占据）；
- 数字写成 `1/2`、`0.5` 两种都认。

输出保持**原胞**（不做标准化/去对称），元素按首次出现顺序分组——VASP 要求同元素连续，
计数行与元素行严格对应。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple


class CifError(ValueError):
    """CIF 解析/转换失败（消息直接面向用户）。"""


_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TERM_RE = re.compile(r"([+-]?)\s*(\d+/\d+|\d*\.\d+|\d+)?\s*([xyzXYZ])?")
_XYZ_INDEX = {"x": 0, "y": 1, "z": 2}


def _number(token: Any) -> Optional[float]:
    """CIF 数值 → float：支持 `5.430(2)`、`1/2`、`?`/`.` 缺省写法。"""
    if token is None:
        return None
    text = str(token).strip().strip("'\"")
    if text in ("", ".", "?", "-"):
        return None
    text = re.sub(r"\(.*?\)", "", text)  # 去 esd
    if "/" in text:
        parts = text.split("/")
        if len(parts) == 2:
            try:
                return float(parts[0]) / float(parts[1])
            except (ValueError, ZeroDivisionError):
                pass
    match = _NUMBER_RE.match(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _tokenize(text: str) -> List[str]:
    """CIF 词法：按行处理，跳过 `#` 注释与 `;` 文本块，尊重引号。"""
    tokens: List[str] = []
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.lstrip().startswith(";"):  # 多行文本字段，用不到，整块跳过
            idx += 1
            while idx < len(lines) and not lines[idx].lstrip().startswith(";"):
                idx += 1
            idx += 1
            continue
        pos = line.find("#")
        if pos >= 0:
            line = line[:pos]
        idx += 1
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if ch.isspace():
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                i += 1
                start = i
                while i < n and line[i] != quote:
                    i += 1
                tokens.append(line[start:i])
                i += 1
                continue
            start = i
            while i < n and not line[i].isspace():
                i += 1
            tokens.append(line[start:i])
    return tokens


def _parse_cif(text: str) -> Tuple[Dict[str, str], List[Tuple[List[str], List[List[str]]]]]:
    """返回 (标量键值, [(loop 标签, 行数据), ...])；键统一小写。"""
    tokens = _tokenize(text)
    scalars: Dict[str, str] = {}
    loops: List[Tuple[List[str], List[List[str]]]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        low = token.lower()
        if low.startswith("data_"):
            # 数据块名（多个块时取第一个）：CIF 里常拿它当结构名
            scalars.setdefault("_data_block_name", token[5:])
            i += 1
            continue
        if low == "loop_":
            i += 1
            tags: List[str] = []
            while i < len(tokens) and tokens[i].startswith("_"):
                tags.append(tokens[i].lower())
                i += 1
            rows: List[List[str]] = []
            width = len(tags)
            if width:
                while i < len(tokens):
                    nxt = tokens[i]
                    nxt_low = nxt.lower()
                    if nxt.startswith("_") or nxt_low == "loop_" or nxt_low.startswith("data_") or nxt_low == "stop_":
                        break
                    row = tokens[i : i + width]
                    if len(row) < width:
                        break
                    rows.append(row)
                    i += width
            loops.append((tags, rows))
            continue
        if token.startswith("_"):
            if i + 1 < len(tokens):
                scalars.setdefault(low, tokens[i + 1])
            i += 2
            continue
        i += 1
    return scalars, loops


def _parse_symop(expr: str) -> Tuple[List[List[float]], List[float]]:
    """`1/2+x,-y,z` → (旋转矩阵 3x3, 平移向量)。"""
    parts = [p.strip() for p in str(expr).strip().strip("'\"").split(",")]
    if len(parts) != 3:
        raise CifError(f"对称操作写得不认识：{expr}")
    rotation = [[0.0, 0.0, 0.0] for _ in range(3)]
    translation = [0.0, 0.0, 0.0]
    for row, part in enumerate(parts):
        compact = part.replace(" ", "")
        found = False
        for sign, number, var in _TERM_RE.findall(compact):
            if not (sign or number or var):
                continue
            found = True
            value = _number(number) if number else 1.0
            if value is None:
                value = 1.0
            if sign == "-":
                value = -value
            if var:
                rotation[row][_XYZ_INDEX[var.lower()]] += value
            else:
                translation[row] += value
        if not found:
            raise CifError(f"对称操作写得不认识：{expr}")
    return rotation, translation


def _element_from_label(label: str) -> str:
    """`O1` → O；`Fe2+` → Fe；`Si_2` → Si。"""
    text = re.sub(r"[^A-Za-z]", "", str(label or ""))
    if not text:
        return ""
    if len(text) >= 2 and text[0].isupper() and text[1].islower():
        return text[:2].capitalize()
    return text[0].upper()


def _lattice_matrix(a: float, b: float, c: float, alpha: float, beta: float, gamma: float) -> List[List[float]]:
    """晶胞参数 → 晶格矢量（行 = a/b/c 矢量，VASP POSCAR 约定，a 沿 x）。"""
    alpha_r, beta_r, gamma_r = (math.radians(x) for x in (alpha, beta, gamma))
    sin_gamma = math.sin(gamma_r)
    if abs(sin_gamma) < 1e-12:
        raise CifError("晶胞角 gamma 为 0/180 度，无法建立晶格矢量")
    cos_alpha, cos_beta, cos_gamma = math.cos(alpha_r), math.cos(beta_r), math.cos(gamma_r)
    cx = cos_beta
    cy = (cos_alpha - cos_beta * cos_gamma) / sin_gamma
    cz_sq = 1.0 - cx * cx - cy * cy
    if cz_sq < -1e-9:
        raise CifError("晶胞参数不自洽（无法换算成正交矢量的组合）")
    cz = math.sqrt(max(0.0, cz_sq))
    return [
        [a, 0.0, 0.0],
        [b * cos_gamma, b * sin_gamma, 0.0],
        [c * cx, c * cy, c * cz],
    ]


def _invert(matrix: List[List[float]]) -> List[List[float]]:
    (a, b, c), (d, e, f), (g, h, i2) = matrix
    det = a * (e * i2 - f * h) - b * (d * i2 - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise CifError("晶格矩阵不可逆（晶胞参数有问题）")
    return [
        [(e * i2 - f * h) / det, (c * h - b * i2) / det, (b * f - c * e) / det],
        [(f * g - d * i2) / det, (a * i2 - c * g) / det, (c * d - a * f) / det],
        [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
    ]


def parse_cif(text: str) -> Dict[str, Any]:
    """解析 CIF：返回晶胞、原子（分数坐标，已按对称操作展开）与 warnings。"""
    scalars, loops = _parse_cif(text)
    a = _number(scalars.get("_cell_length_a"))
    b = _number(scalars.get("_cell_length_b"))
    c = _number(scalars.get("_cell_length_c"))
    alpha = _number(scalars.get("_cell_angle_alpha")) or 90.0
    beta = _number(scalars.get("_cell_angle_beta")) or 90.0
    gamma = _number(scalars.get("_cell_angle_gamma")) or 90.0
    if not (a and b and c):
        raise CifError("没有找到完整的晶胞参数（_cell_length_a/b/c）")
    lattice = _lattice_matrix(a, b, c, alpha, beta, gamma)

    warnings: List[str] = []
    sites: List[Dict[str, Any]] = []
    for tags, rows in loops:
        if not any(tag.startswith("_atom_site_") for tag in tags):
            continue
        col = {tag: idx for idx, tag in enumerate(tags)}
        for row in rows:
            def cell(key: str) -> Optional[str]:
                index = col.get(key)
                return row[index] if index is not None and index < len(row) else None

            label = (cell("_atom_site_label") or cell("_atom_site_type_symbol") or "").strip()
            element = (cell("_atom_site_type_symbol") or "").strip() or _element_from_label(label)
            element = _element_from_label(element) or element
            if not element:
                continue
            occupancy = _number(cell("_atom_site_occupancy"))
            if occupancy is None:
                occupancy = 1.0
            if occupancy <= 0:
                warnings.append(f"跳过占据数为 {occupancy:g} 的原子 {label or element}")
                continue
            if abs(occupancy - 1.0) > 1e-6:
                warnings.append(
                    f"原子 {label or element} 的占据数是 {occupancy:g}，POSCAR 表达不了部分占据（按整占据写入）"
                )
            frac: Optional[List[float]] = None
            fx, fy, fz = (cell("_atom_site_fract_x"), cell("_atom_site_fract_y"), cell("_atom_site_fract_z"))
            if fx is not None and fy is not None and fz is not None:
                values = [_number(fx), _number(fy), _number(fz)]
                if all(v is not None for v in values):
                    frac = [float(v) for v in values]  # type: ignore[arg-type]
            if frac is None:
                cx, cy, cz = (cell("_atom_site_cartn_x"), cell("_atom_site_cartn_y"), cell("_atom_site_cartn_z"))
                if cx is not None and cy is not None and cz is not None:
                    values = [_number(cx), _number(cy), _number(cz)]
                    if all(v is not None for v in values):
                        cart = [float(v) for v in values]  # type: ignore[arg-type]
                        inverse = _invert(lattice)
                        frac = [sum(inverse[r][k] * cart[k] for k in range(3)) for r in range(3)]
            if frac is None:
                continue
            sites.append({"label": label, "element": element, "frac": frac, "occupancy": occupancy})
    if not sites:
        # 少见写法：单个原子直接写成标量标签（没有 loop_）
        fx, fy, fz = (
            scalars.get("_atom_site_fract_x"),
            scalars.get("_atom_site_fract_y"),
            scalars.get("_atom_site_fract_z"),
        )
        values = [_number(fx), _number(fy), _number(fz)]
        if all(value is not None for value in values):
            label = (scalars.get("_atom_site_label") or scalars.get("_atom_site_type_symbol") or "").strip()
            element = (scalars.get("_atom_site_type_symbol") or "").strip() or _element_from_label(label)
            element = _element_from_label(element) or element
            if element:
                sites.append(
                    {
                        "label": label,
                        "element": element,
                        "frac": [float(value) for value in values],  # type: ignore[arg-type]
                        "occupancy": _number(scalars.get("_atom_site_occupancy")) or 1.0,
                    }
                )
    if not sites:
        raise CifError("没有找到原子坐标（_atom_site_fract_* 或 _atom_site_Cartn_*）")

    ops: List[Tuple[List[List[float]], List[float]]] = []
    for tags, rows in loops:
        col = {tag: idx for idx, tag in enumerate(tags)}
        index = col.get("_symmetry_equiv_pos_as_xyz")
        if index is None:
            index = col.get("_space_group_symop_operation_xyz")
        if index is None:
            continue
        for row in rows:
            if index < len(row) and row[index].strip():
                ops.append(_parse_symop(row[index]))
    if not ops:
        single = scalars.get("_symmetry_equiv_pos_as_xyz") or scalars.get("_space_group_symop_operation_xyz")
        if single:
            ops.append(_parse_symop(single))
    if not ops:
        ops = [([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0, 0.0, 0.0])]
        group = (
            scalars.get("_symmetry_space_group_name_h-m")
            or scalars.get("_space_group_name_h-m_alt")
            or ""
        ).strip()
        if group and group.upper().replace(" ", "") not in ("P1", "P 1"):
            warnings.append(
                f"CIF 声明了空间群 {group}，但文件里没有对称操作列表，只能按列出的原子（P1）处理"
            )

    expanded: List[Dict[str, Any]] = []
    seen = set()
    for site in sites:
        source = site["frac"]
        for rotation, translation in ops:
            frac = [
                sum(rotation[r][k] * source[k] for k in range(3)) + translation[r]
                for r in range(3)
            ]
            frac = [v - math.floor(v) for v in frac]
            key = (
                site["element"],
                round(frac[0] % 1.0, 4) % 1.0,
                round(frac[1] % 1.0, 4) % 1.0,
                round(frac[2] % 1.0, 4) % 1.0,
            )
            if key in seen:
                continue
            seen.add(key)
            expanded.append({**site, "frac": frac})

    return {
        "cell": {"a": a, "b": b, "c": c, "alpha": alpha, "beta": beta, "gamma": gamma},
        "lattice": lattice,
        "sites": expanded,
        "formula": (scalars.get("_chemical_formula_sum") or "").strip(),
        "name": (scalars.get("_data_block_name") or "").strip(),
        "warnings": warnings,
    }


def cif_to_poscar(text: str, comment: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """CIF 文本 → (POSCAR 文本, 摘要信息)。失败抛 `CifError`。"""
    data = parse_cif(text)
    order: List[str] = []
    for site in data["sites"]:
        if site["element"] not in order:
            order.append(site["element"])
    counts = {element: 0 for element in order}
    grouped: Dict[str, List[List[float]]] = {element: [] for element in order}
    for site in data["sites"]:
        counts[site["element"]] += 1
        grouped[site["element"]].append(site["frac"])

    title = (comment or data["formula"] or data["name"] or "converted from CIF").strip() or "converted from CIF"
    lines = [title, "1.0"]
    for vector in data["lattice"]:
        lines.append("  " + "  ".join(f"{value:20.12f}" for value in vector))
    lines.append("  " + "  ".join(order))
    lines.append("  " + "  ".join(str(counts[element]) for element in order))
    lines.append("Direct")
    for element in order:
        for frac in grouped[element]:
            values = [0.0 if abs(v) < 1e-12 else v for v in frac]
            lines.append("  " + "  ".join(f"{value:19.12f}" for value in values))
    poscar = "\n".join(lines) + "\n"
    info = {
        "elements": order,
        "counts": [counts[element] for element in order],
        "atoms": len(data["sites"]),
        "cell": data["cell"],
        "formula": data["formula"],
        "name": data["name"],
        "warnings": data["warnings"],
    }
    return poscar, info
