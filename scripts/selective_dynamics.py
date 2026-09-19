#!/usr/bin/env python3
"""POSCAR 选择性动力学（Selective Dynamics）生成器 —— 只固定指定原子。

做什么：
    1. 读取 `POSCAR`（默认当前目录，可用 --poscar 指定）；
    2. 在**元素数量行之后、坐标行之前**插入 `Selective Dynamics`；
    3. 按第 6 行元素符号 + 第 7 行元素数量，给每个原子生成 `元素+序号` 标签
       （默认元素内序号 `Fe1…Fe24 S1…S32`，可切换全局序号 `Fe1…S56`）；
    4. 每个坐标行输出：原坐标(3 个浮点数) + 三个 T/F + 标签，
       例如 `0.333333 0.416667 0.129380 T T F O1`；
    5. 固定原子写 `F F F`、其余写 `T T T`；
    6. 原 `POSCAR` 备份成 `old_POSCAR`，新内容写回 `POSCAR`。

支持重复运行（幂等）：**已固定过的 POSCAR**（已有 Selective Dynamics / T-F 标志 /
末尾标签）会重新解析、按本次配置覆盖，不会越写越乱。

固定规则（FIX_MODE）：
    manual    —— 按原子序号固定（`--fixed-atoms 1,5,7`，也接受 `Fe1, O33` 这种标签）
    elements  —— 按元素固定（`--fixed-elements Fe,S`）
    z_range   —— 按高度固定：分数坐标 z 在 [zmin, zmax] 内的原子（vaspkit 常用）
    indices   —— 同 manual，语义上表示"按全局序号"
    from_json —— 读 POSCAR 页面导出的选中原子（支持
                 `{"atoms":[{"element":"Fe","poscarIndex":1}]}`、`[1,5,7]`、`["Fe1"]`）

用法示例：
    python selective_dynamics.py                          # 用下面配置区
    python selective_dynamics.py --fixed-atoms 1,2,3
    python selective_dynamics.py --mode elements --fixed-elements Fe
    python selective_dynamics.py --mode z_range --z-range 0 0.25
    python selective_dynamics.py --mode from_json --fixed-json selected.json
    python selective_dynamics.py --numbering global --no-labels
    python selective_dynamics.py --dry-run                # 只打印结果，不落盘
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

# ============================================================================
#                               配 置 区
# 直接改这里就能用；命令行参数会覆盖这些值
# ============================================================================

POSCAR = "POSCAR"  # 输入文件（运行目录下的 POSCAR）
BACKUP_NAME = "old_POSCAR"  # 原文件备份名
BACKUP_MODE = "overwrite"  # overwrite=每次覆盖备份；keep_first=只保留最初那份原始文件

FIX_MODE = "manual"  # manual / elements / z_range / indices / from_json
FIXED_ATOMS: List[str] = []  # manual / indices：原子序号（1 起）或标签，如 [1, 5, "O33"]
FIXED_ELEMENTS: List[str] = []  # elements：元素符号，如 ["Fe", "S"]
Z_RANGE: Tuple[float, float] = (0.0, 0.2)  # z_range：分数坐标 z 的 [下限, 上限]
FIXED_JSON = ""  # from_json：POSCAR 页导出的选中原子文件

NUMBERING = "element"  # element=元素内序号（Fe1…Fe24, S1…S32）；global=全局序号（Fe1…S56）
LABEL_ATOMS = True  # 坐标行末尾是否附 "元素+序号" 标签
FLAG_FIXED = ("F", "F", "F")  # 固定原子的三个标志
FLAG_FREE = ("T", "T", "T")  # 自由原子的三个标志

DRY_RUN = False  # True=只打印结果，不改动任何文件
# ============================================================================


COORD_SEP = "   "  # 坐标之间的分隔（保持原文件的 3-4 空格风格）
FLAG_SEP = "  "  # 标志之间的分隔
LABEL_GAP = "   "  # 标志与标签之间的分隔

#: 坐标行尾部（已存在的 T/F 标志 + 可选标签），用于"原地替换"而不是重排整行
_TAIL_RE = re.compile(
    r"^(?P<gap1>\s+)(?P<f1>[TFtf])(?P<sep1>\s+)(?P<f2>[TFtf])"
    r"(?P<sep2>\s+)(?P<f3>[TFtf])(?P<gap2>\s*)(?P<label>\S*)\s*$"
)


def split_coord_line(line: str) -> Tuple[str, str]:
    """把坐标行切成 `(前缀, 尾部)`。

    前缀 = 行首空白 + 3 个坐标 token（**连同它们之间的原始空白**），
    尾部 = 之后的所有内容（可能已有 T/F 标志与标签）。
    这样重写时能保留原文件的缩进与列宽，diff 只显示真正变化的部分。
    """
    spans = [m.end() for m in re.finditer(r"\S+", line)]
    if len(spans) < 3:
        return line, ""
    return line[: spans[2]], line[spans[2] :]


def rebuild_coord_line(
    line: str,
    flags: Sequence[str],
    label: str,
    label_atoms: bool,
    coord_sep: str,
) -> str:
    """在**不重排**原坐标行的前提下写入 T/F（与可选标签）。

    - 原行已有标志（如 test/1 这种已固定过的文件）：只把标志字母换掉，
      `F  F  F` 之间的空格、标签前后的对齐空格全部保持原样；
    - 原行没有标志：在坐标尾部按原文件坐标列宽追加标志（+ 标签）；
    - `label_atoms=False` 时丢掉标签（连同标签前的对齐空格）。
    """
    prefix, tail = split_coord_line(line)
    if not tail.strip():
        gap = coord_sep or COORD_SEP
        out = prefix + gap + FLAG_SEP.join(flags)
        if label_atoms:
            out += LABEL_GAP + label
        return out.rstrip()
    m = _TAIL_RE.match(tail)
    if not m:
        # 尾部不是标志（异常内容）：保守起见原样保留
        return line.rstrip()
    out = prefix + m.group("gap1") + flags[0] + m.group("sep1") + flags[1]
    out += m.group("sep2") + flags[2]
    if label_atoms:
        out += (m.group("gap2") or LABEL_GAP) + label
    return out.rstrip()


class PoscarError(RuntimeError):
    """POSCAR 解析/校验错误。"""


def _is_int(token: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+", token or ""))


def _as_float(token: str) -> float:
    try:
        return float(token)
    except (TypeError, ValueError):
        raise PoscarError(f"无法解析为浮点数：{token!r}")


class Poscar(NamedTuple):
    """解析结果：保留每一行的**原文与原始行尾**（`\\n` / `\\r\\n`），重写时最小化 diff。

    行内容通过下面的属性按索引取，未改动的行写回时逐字节一致（含 CRLF）。
    """

    lines: List[str]  # 每行文本（已去掉行尾换行符）
    endings: List[str]  # 每行的原始行尾（"" / "\n" / "\r\n"）
    header_idx: List[int]  # 前 5 行（标题/缩放/3 条晶格）
    element_idx: Optional[int]  # 元素符号行（VASP4 为 None）
    count_idx: int  # 元素数量行
    sd_idx: Optional[int]  # 原有 "Selective Dynamics" 行（没有则 None）
    mode_idx: int  # 坐标模式行（Direct / Cartesian）
    coord_idx: List[int]  # 坐标行
    trailer_idx: List[int]  # 坐标块之后的附加内容（空行 + 速度块等）
    elements: List[str]  # 元素符号（VASP4 为空列表）
    counts: List[int]  # 各元素原子数
    coords: List[List[str]]  # 每行前 3 个坐标 token

    # ---- 便捷视图（按索引取原文）----
    @property
    def header(self) -> List[str]:
        return [self.lines[i] for i in self.header_idx]

    @property
    def element_line(self) -> str:
        return self.lines[self.element_idx] if self.element_idx is not None else ""

    @property
    def count_line(self) -> str:
        return self.lines[self.count_idx]

    @property
    def sd_line(self) -> str:
        return self.lines[self.sd_idx] if self.sd_idx is not None else ""

    @property
    def mode_line(self) -> str:
        return self.lines[self.mode_idx]

    @property
    def coord_lines(self) -> List[str]:
        return [self.lines[i] for i in self.coord_idx]

    @property
    def trailer(self) -> List[str]:
        return [self.lines[i] for i in self.trailer_idx]


def read_poscar(path: Path) -> Poscar:
    """解析 POSCAR（保留原始格式细节）。

    已固定过的文件（含 Selective Dynamics / T F 标志 / 标签）同样能正确解析 ——
    旧标志与标签会被**原地替换**（保留列宽与缩进），而不是把整行重排。

    **附加内容会被原样保留**：VASP 的 CONTCAR 常在坐标块后面再跟一段（空行 +
    速度块 / predictor-corrector 块，用于 MD 续跑），插入 `Selective Dynamics`
    只应影响坐标块，后面的内容不能丢。
    """
    if not path.is_file():
        raise PoscarError(f"找不到 POSCAR 文件：{path}")
    # 按字节读取再解码：read_text() 的通用换行会把 \r\n 提前转成 \n，丢失原始行尾
    raw = path.read_bytes().decode("utf-8", errors="replace")
    # 逐行保留原始行尾：CRLF 文件写回仍是 CRLF，未改动的行逐字节一致
    lines: List[str] = []
    endings: List[str] = []
    for chunk in raw.splitlines(keepends=True):
        for suffix in ("\r\n", "\n", "\r"):
            if chunk.endswith(suffix):
                lines.append(chunk[: -len(suffix)])
                endings.append(suffix)
                break
        else:
            lines.append(chunk)
            endings.append("")
    if not lines:
        raise PoscarError(f"文件为空：{path}")
    lines[0] = lines[0].lstrip("\ufeff")  # 去掉可能的 BOM
    while lines and not lines[-1].strip():
        lines.pop()
        endings.pop()
    if len(lines) < 7:
        raise PoscarError("POSCAR 至少需要 7 行（标题/缩放/3 条晶格/元素/数量）")

    header_idx = [0, 1, 2, 3, 4]
    idx = 5
    tokens = lines[idx].split()
    if tokens and all(_is_int(t) for t in tokens):
        # VASP4 格式：没有元素符号行，第 6 行直接是数量
        elements: List[str] = []
        counts = [int(t) for t in tokens]
        element_idx: Optional[int] = None
        count_idx = idx
        idx += 1
    else:
        elements = tokens
        counts = [int(t) for t in lines[idx + 1].split()]
        element_idx = idx
        count_idx = idx + 1
        idx += 2
    if not counts or any(c < 0 for c in counts):
        raise PoscarError(f"元素数量行非法：{lines[5]!r}")
    if elements and len(elements) != len(counts):
        raise PoscarError(
            f"元素符号数（{len(elements)}）与元素数量数（{len(counts)}）不一致"
        )

    sd_idx: Optional[int] = None
    if idx < len(lines) and lines[idx].strip()[:1].lower() == "s":
        sd_idx = idx
        idx += 1
    if idx >= len(lines):
        raise PoscarError("缺少坐标模式行（Direct / Cartesian）")
    mode_idx = idx
    mode = lines[idx].strip()
    if mode[:1].lower() not in ("d", "c", "k"):
        raise PoscarError(f"坐标模式行无法识别：{mode!r}（应为 Direct 或 Cartesian）")
    idx += 1

    natoms = sum(counts)
    # 取前 natoms 个非空行作为坐标行（空行只可能在坐标块之后）
    coord_idx: List[int] = []
    consumed = idx - 1
    cursor = idx
    while cursor < len(lines) and len(coord_idx) < natoms:
        if lines[cursor].strip():
            coord_idx.append(cursor)
            consumed = cursor
        cursor += 1
    if len(coord_idx) < natoms:
        raise PoscarError(f"坐标行数不足：需要 {natoms} 行，实际只有 {len(coord_idx)} 行")
    coords: List[List[str]] = []
    for i in coord_idx:
        ln = lines[i]
        parts = ln.split()
        if len(parts) < 3:
            raise PoscarError(f"坐标行非法：{ln!r}")
        coords.append(parts[:3])  # 只保留 3 个浮点数（丢掉旧的 T/F 与标签）
    trailer_idx = list(range(consumed + 1, len(lines)))
    return Poscar(
        lines=lines,
        endings=endings,
        header_idx=header_idx,
        element_idx=element_idx,
        count_idx=count_idx,
        sd_idx=sd_idx,
        mode_idx=mode_idx,
        coord_idx=coord_idx,
        trailer_idx=trailer_idx,
        elements=elements,
        counts=counts,
        coords=coords,
    )


def build_labels(elements: Sequence[str], counts: Sequence[int], numbering: str) -> List[str]:
    """按元素顺序生成 `元素+序号` 标签。

    element：元素内序号（Fe1…Fe24, S1…S32）
    global ：全局序号（Fe1…Fe24, S25…S56），与 POSCAR 坐标行序号一致
    """
    labels: List[str] = []
    counter: Dict[str, int] = {}
    # VASP4（没有元素符号行）没有真实元素可用，统一用占位符 X，保证标签是 X1…Xn
    symbols = list(elements) if elements else ["X"] * len(counts)
    total = 0
    for symbol, number in zip(symbols, counts):
        for _ in range(int(number)):
            total += 1
            counter[symbol] = counter.get(symbol, 0) + 1
            labels.append(f"{symbol}{total}" if numbering == "global" else f"{symbol}{counter[symbol]}")
    return labels


def atoms_fractional_z(
    coords: Sequence[Sequence[str]], header: Sequence[str], mode: str
) -> List[float]:
    """取每个原子的**分数坐标 z**（用于按高度固定）。

    Direct 直接用第 3 个坐标；Cartesian 需要用晶格矩阵求逆换算
    （POSCAR：真实坐标 = scale × 晶格矩阵 × 分数坐标）。
    """
    if mode[:1].lower() == "d":
        return [_as_float(atom[2]) for atom in coords]

    scale = _as_float(header[1].split()[0]) if header[1].split() else 1.0
    m = [[_as_float(x) for x in header[2 + i].split()[:3]] for i in range(3)]
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    if abs(det) < 1e-12:
        raise PoscarError("晶格矩阵不可逆，无法把 Cartesian 坐标换算成分数坐标")
    inv = [
        [
            (m[1][1] * m[2][2] - m[1][2] * m[2][1]) / det,
            (m[0][2] * m[2][1] - m[0][1] * m[2][2]) / det,
            (m[0][1] * m[1][2] - m[0][2] * m[1][1]) / det,
        ],
        [
            (m[1][2] * m[2][0] - m[1][0] * m[2][2]) / det,
            (m[0][0] * m[2][2] - m[0][2] * m[2][0]) / det,
            (m[0][2] * m[1][0] - m[0][0] * m[1][2]) / det,
        ],
        [
            (m[1][0] * m[2][1] - m[1][1] * m[2][0]) / det,
            (m[0][1] * m[2][0] - m[0][0] * m[2][1]) / det,
            (m[0][0] * m[1][1] - m[0][1] * m[1][0]) / det,
        ],
    ]
    zs: List[float] = []
    for atom in coords:
        r = [_as_float(atom[i]) / (scale if scale else 1.0) for i in range(3)]
        zs.append(inv[2][0] * r[0] + inv[2][1] * r[1] + inv[2][2] * r[2])
    return zs


def load_fixed_from_json(path: Path) -> List[str]:
    """读 POSCAR 页导出的选中原子（支持多种写法，返回标签或序号字符串列表）。"""
    if not path.is_file():
        raise PoscarError(f"找不到选中原子文件：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("atoms") or data.get("selected") or []
    if not isinstance(data, list):
        raise PoscarError("选中原子 JSON 应为列表，或 {\"atoms\": [...]}")
    result: List[str] = []
    for item in data:
        if isinstance(item, dict):
            if item.get("poscarIndex") is not None:
                result.append(str(int(item["poscarIndex"])))
            elif item.get("index") is not None:
                result.append(str(int(item["index"]) + 1))  # 页面下标 0 起
            elif item.get("element"):
                result.append(str(item["element"]))
        else:
            result.append(str(item))
    return result


def resolve_fixed_atoms(
    spec: Sequence[str], labels: Sequence[str], elements: Sequence[str]
) -> set:
    """把配置里的原子（序号 / 标签）解析成 1 起的原子下标集合。"""
    fixed: set = set()
    label_to_index = {label: i + 1 for i, label in enumerate(labels)}
    element_seq: List[str] = []
    for i, label in enumerate(labels):
        symbol = re.sub(r"\d+$", "", label)
        element_seq.append(symbol)
    for raw in spec:
        token = str(raw).strip()
        if not token:
            continue
        if _is_int(token):
            index = int(token)
            if not 1 <= index <= len(labels):
                raise PoscarError(f"原子序号越界：{index}（本结构共 {len(labels)} 个原子）")
            fixed.add(index)
            continue
        if token in label_to_index:
            fixed.add(label_to_index[token])
            continue
        # 允许只写元素符号（等价于该元素全部固定）
        if token in elements:
            fixed.update(i + 1 for i, sym in enumerate(element_seq) if sym == token)
            continue
        raise PoscarError(f"无法识别的原子标识：{token!r}（可用序号、Fe3 这样的标签或元素符号）")
    return fixed


def decide_fixed(
    mode: str,
    labels: Sequence[str],
    elements: Sequence[str],
    fractional_z: Sequence[float],
    fixed_spec: Sequence[str],
    fixed_elements: Sequence[str],
    z_range: Tuple[float, float],
) -> Tuple[set, str]:
    """按配置算出"要固定的原子（1 起下标集合）"，并返回一句说明。"""
    if mode in ("manual", "indices"):
        fixed = resolve_fixed_atoms(fixed_spec, labels, elements)
        return fixed, f"manual：按给定 {len(fixed)} 个原子固定"
    if mode == "elements":
        wanted = {str(e) for e in fixed_elements if str(e).strip()}
        if not wanted:
            raise PoscarError("elements 模式需要 --fixed-elements（如 Fe,S）")
        fixed = {
            i + 1
            for i, label in enumerate(labels)
            if re.sub(r"\d+$", "", label) in wanted
        }
        missing = wanted - {re.sub(r"\d+$", "", label) for label in labels}
        if missing:
            raise PoscarError(f"结构里没有这些元素：{', '.join(sorted(missing))}")
        return fixed, f"elements：固定 {', '.join(sorted(wanted))}"
    if mode == "z_range":
        zmin, zmax = float(z_range[0]), float(z_range[1])
        fixed = {i + 1 for i, z in enumerate(fractional_z) if zmin <= z <= zmax}
        return fixed, f"z_range：固定分数坐标 z ∈ [{zmin:g}, {zmax:g}] 的原子"
    if mode == "from_json":
        fixed = resolve_fixed_atoms(fixed_spec, labels, elements)
        return fixed, f"from_json：固定选中的 {len(fixed)} 个原子"
    raise PoscarError(f"未知 FIX_MODE：{mode!r}")


def render_poscar(
    poscar: Poscar,
    labels: Sequence[str],
    fixed: set,
    label_atoms: bool,
    flag_fixed: Sequence[str],
    flag_free: Sequence[str],
) -> str:
    """拼出新的 POSCAR 文本（只做必要改动，其余保持原样）。

    - 前 5 行 / 元素行 / 数量行 / 坐标模式行 / 坐标块之后的附加内容：原样保留；
    - `Selective Dynamics`：原来有就沿用原行原文（大小写不变），没有才插入；
    - 坐标行：调用 `rebuild_coord_line()` **原地**替换/追加 T/F（与可选标签），
      保留原缩进与列宽 —— 这样 `diff old_POSCAR POSCAR` 只显示真正变化的地方；
    - 每行连同它**自己的原始行尾**写回（CRLF 文件保持 CRLF，末行没换行就不加）。
    """
    parts: List[Tuple[str, str]] = []  # (行文本, 该行的原始行尾)

    def emit(index: int, text: Optional[str] = None) -> None:
        parts.append((poscar.lines[index] if text is None else text, poscar.endings[index]))

    for i in poscar.header_idx:
        emit(i)
    if poscar.element_idx is not None:
        emit(poscar.element_idx)
    emit(poscar.count_idx)
    if poscar.sd_idx is not None:
        emit(poscar.sd_idx)  # 已有 SD 行：沿用原文（大小写/缩进不变）
    else:
        parts.append(("Selective Dynamics", poscar.endings[poscar.count_idx]))
    emit(poscar.mode_idx)

    # 坐标列宽：沿用原文件第 2、3 个坐标之间的空白；取不到就用 3 空格
    coord_sep = COORD_SEP
    for line in poscar.coord_lines:
        spans = [m.span() for m in re.finditer(r"\S+", line)]
        if len(spans) >= 3:
            coord_sep = line[spans[1][1] : spans[2][0]] or COORD_SEP
            break

    for n, index in enumerate(poscar.coord_idx):
        flags = flag_fixed if (n + 1) in fixed else flag_free
        emit(
            index,
            rebuild_coord_line(
                poscar.lines[index], flags, labels[n], label_atoms, coord_sep
            ),
        )
    # VASP 的 CONTCAR 常在坐标块后跟"空行 + 速度块"，原样保留（MD 续跑要用）
    for i in poscar.trailer_idx:
        emit(i)
    return "".join(text + ending for text, ending in parts)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="给 POSCAR 加 Selective Dynamics 并固定指定原子（原文件备份为 old_POSCAR）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--poscar", default=POSCAR, help="输入 POSCAR 路径")
    parser.add_argument(
        "--mode",
        default=FIX_MODE,
        choices=["manual", "elements", "z_range", "indices", "from_json"],
        help="固定规则",
    )
    parser.add_argument("--fixed-atoms", default="", help="manual/indices：原子序号或标签，逗号分隔（1,5,O33）")
    parser.add_argument("--fixed-elements", default="", help="elements：元素符号，逗号分隔（Fe,S）")
    parser.add_argument("--z-range", nargs=2, type=float, default=list(Z_RANGE), help="z_range：分数坐标 z 下限 上限")
    parser.add_argument("--fixed-json", default=FIXED_JSON, help="from_json：选中原子 JSON 路径")
    parser.add_argument("--numbering", default=NUMBERING, choices=["element", "global"], help="标签编号方式")
    parser.add_argument("--no-labels", action="store_true", help="坐标行末尾不写元素+序号标签")
    parser.add_argument("--backup-name", default=BACKUP_NAME, help="备份文件名")
    parser.add_argument(
        "--backup-mode",
        default=BACKUP_MODE,
        choices=["overwrite", "keep_first"],
        help="overwrite=覆盖旧备份；keep_first=只保留第一次的原始文件",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = parser.parse_args(argv)

    poscar_path = Path(args.poscar)
    label_atoms = LABEL_ATOMS and not args.no_labels

    try:
        poscar = read_poscar(poscar_path)
        labels = build_labels(poscar.elements, poscar.counts, args.numbering)
        # 只有按高度固定时才需要分数坐标（避免无谓的晶格求逆）
        fractional_z = (
            atoms_fractional_z(poscar.coords, poscar.header, poscar.mode_line)
            if args.mode == "z_range"
            else []
        )

        if args.mode == "from_json":
            spec = load_fixed_from_json(Path(args.fixed_json)) if args.fixed_json else []
            if not spec:
                raise PoscarError("from_json 模式需要 --fixed-json，且文件里要有选中的原子")
        else:
            spec = [t for t in str(args.fixed_atoms).replace(";", ",").split(",") if t.strip()]
        fixed_elements = [t.strip() for t in str(args.fixed_elements).split(",") if t.strip()]

        fixed, note = decide_fixed(
            args.mode,
            labels,
            poscar.elements,
            fractional_z,
            spec,
            fixed_elements or FIXED_ELEMENTS,
            (args.z_range[0], args.z_range[1]),
        )
        text = render_poscar(
            poscar,
            labels,
            fixed,
            label_atoms,
            FLAG_FIXED,
            FLAG_FREE,
        )
    except (PoscarError, json.JSONDecodeError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    # ---------------- 输出 ----------------
    by_element: Dict[str, int] = {}
    for i in sorted(fixed):
        symbol = re.sub(r"\d+$", "", labels[i - 1])
        by_element[symbol] = by_element.get(symbol, 0) + 1
    summary = "、".join(f"{k} {v}" for k, v in by_element.items()) or "无"
    print(
        f"结构：{len(labels)} 个原子"
        f"（{', '.join(poscar.elements) if poscar.elements else 'VASP4'}）"
    )
    if poscar.sd_line:
        print("检测到原文件已含 Selective Dynamics —— 本次按新配置重新覆盖固定原子")
    print(f"规则：{note}")
    print(f"固定：{len(fixed)} 个原子（{summary}）· 其余 {len(labels) - len(fixed)} 个为自由")
    if poscar.trailer:
        print(
            f"注意：坐标块之后还有 {len(poscar.trailer)} 行附加内容"
            "（空行/速度块等，常见于 CONTCAR）—— 已原样保留"
        )

    if args.dry_run:
        print("---- 结果预览（--dry-run，不写文件）----")
        print(text, end="")
        return 0

    backup = poscar_path.with_name(args.backup_name)
    if args.backup_mode == "keep_first" and backup.exists():
        backup_done = False
    else:
        backup_done = True
        shutil.move(str(poscar_path), str(backup))
    # newline="" 表示不做换行转换：文本里已经是原文的换行风格
    poscar_path.write_text(text, encoding="utf-8", newline="")
    print(f"✓ 已写入 {poscar_path}")
    if backup_done:
        print(f"✓ 原文件备份为 {backup}")
    else:
        print(f"· 保留第一次的备份 {backup}（backup-mode=keep_first）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
