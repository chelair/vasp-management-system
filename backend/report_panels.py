"""报告看板图表（纯 Python SVG）——与巡检详情页**同款视觉**。

为什么单独一个模块：报告里的「自由能路径看板 / NEB 能垒看板 / 项目进度」要和前端
巡检详情页（`PathStepChart` / `NebBarrierPanel` / `.fe-*` 版式）看起来一致，
因此几何、配色、字号都按前端同一套常量抄写。**改详情页视觉时同步改这里**，
否则报告与详情页又会「各画一套」。

所有函数返回 SVG 文本；由 report_builder 写入 reports/<项目>/<报告>/charts/。
纯 Python，无第三方依赖（本机与部署环境都没有 matplotlib）。
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple
import zlib

FONT = "font-family=\"Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif\""

# 与前端巡检详情页 global.css 的 .fe-* 变量对齐
COLOR_PRIMARY = "#5B8DEF"
COLOR_PRIMARY_STRONG = "#3F6FE0"
COLOR_TEXT = "#5A6A80"
COLOR_MUTED = "#8A98AC"
COLOR_MUTED_SOFT = "#9AA7B8"
COLOR_GRID = "#EDF1F7"
COLOR_AXIS = "#DCE3EC"
CARD_BORDER = "#EDF1F7"

FE_OK = "#2C9DA8"
FE_OK_SOFT = "#3FB3BD"
FE_WARN = "#E8A33D"
FE_WARN_SOFT = "#F5BE68"
FE_EMPTY = "#C3CEDA"

NEB_LINE = "#7B61D6"
NEB_LINE_SOFT = "#A78BFA"
NEB_SADDLE = "#D9535B"

# 任务类型配色（与项目进度分段一致）
SEGMENT_COLORS = {
    "结构优化": "#5B8DEF",
    "自由能路径": "#2C9DA8",
    "NEB 过渡态": "#7B61D6",
    "电子结构": "#E8A33D",
}


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _svg(width: int, height: int, body: str, title: str = "") -> str:
    label = f"<title>{_escape(title)}</title>" if title else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">{label}'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>{body}</svg>'
    )


def _inner(svg: str) -> str:
    start = svg.find(">", svg.find("<svg"))
    end = svg.rfind("</svg>")
    return svg[start + 1 : end] if start >= 0 and end > start else ""


def _uid(seed: str) -> str:
    """渐变 id 命名空间：同一份 HTML 会内联多张图，id 不能重复。"""
    return f"g{zlib.crc32(seed.encode('utf-8')) & 0xFFFFFF:06x}"


def _text_w(text: str, size: float = 11.0) -> float:
    """粗略文本宽度（SVG 里没法量文字，用中文 1.0em / 西文 0.55em 估算）。"""
    total = 0.0
    for ch in str(text):
        total += size if ord(ch) > 0x2E7F else size * 0.55
    return total


def _signed(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}"


def _fmt(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


# --------------------------------------------------------------- 统计卡 / 图例


def stat_cards(cards: Sequence[Dict[str, str]], *, width: int, uid: str) -> str:
    """一排统计卡（对齐巡检详情页 .fe-stat：浅渐变底 + 圆角 12 + 三行文字）。"""
    count = max(len(cards), 1)
    gap = 10
    card_w = (width - gap * (count - 1)) / count
    card_h = 68
    body: List[str] = [
        "<defs>"
        f'<linearGradient id="{uid}card" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#FBFDFF"/>'
        '<stop offset="100%" stop-color="#F3F8FD"/>'
        "</linearGradient>"
        "</defs>"
    ]
    for index, card in enumerate(cards):
        x = index * (card_w + gap)
        body.append(
            f'<rect x="{x:.1f}" y="0" width="{card_w:.1f}" height="{card_h}" rx="12" '
            f'fill="url(#{uid}card)" stroke="{CARD_BORDER}"/>'
        )
        body.append(
            f'<text x="{x + 14:.1f}" y="22" font-size="12" fill="{COLOR_MUTED_SOFT}" '
            f"{FONT}>{_escape(card.get('label', ''))}</text>"
        )
        body.append(
            f'<text x="{x + 14:.1f}" y="46" font-size="19" font-weight="700" '
            f'fill="{COLOR_PRIMARY_STRONG}" {FONT}>{_escape(card.get("value", "—"))}</text>'
        )
        sub = card.get("sub", "")
        if sub:
            body.append(
                f'<text x="{x + 14:.1f}" y="62" font-size="11" fill="{COLOR_MUTED_SOFT}" '
                f"{FONT}>{_escape(sub)}</text>"
            )
    return _svg(int(width), card_h, "".join(body), "统计卡")


def legend_row(
    items: Sequence[Tuple[str, str, bool]], *, width: int, ref: str = "", top: int = 0
) -> str:
    """图例行：`(颜色, 文案, 是否虚线空心点)` + 右侧灰字说明。"""
    height = 20
    body: List[str] = []
    x = 4.0
    cy = top + height / 2
    for color, label, dashed in items:
        if dashed:
            body.append(
                f'<circle cx="{x + 4:.1f}" cy="{cy:.1f}" r="3.4" fill="#fff" '
                f'stroke="{color}" stroke-dasharray="2 2"/>'
            )
        else:
            body.append(f'<circle cx="{x + 4:.1f}" cy="{cy:.1f}" r="4" fill="{color}"/>')
        body.append(
            f'<text x="{x + 13:.1f}" y="{cy + 4:.1f}" font-size="11" fill="{COLOR_MUTED}" '
            f"{FONT}>{_escape(label)}</text>"
        )
        x += 13 + _text_w(label, 11) + 16
    if ref:
        body.append(
            f'<text x="{width - 4:.1f}" y="{cy + 4:.1f}" font-size="11" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{_escape(ref)}</text>'
        )
    return f'<g transform="translate(0,{top})">{"".join(body)}</g>'


# ------------------------------------------------------------------ 自由能台阶

STEP_W = 968
STEP_H = 320
STEP_M = {"left": 72, "right": 28, "top": 36, "bottom": 62}
STEP_GAP_RATIO = 0.45


def step_chart(
    structures: Sequence[Dict[str, Any]], *, title: str = "自由能路径台阶图"
) -> str:
    """自由能台阶图（几何 / 配色 / 字号与前端 `PathStepChart` 一致）。

    纵轴为相对自由能（以第一个有数据的中间体为参考）；台阶柱体青/琥珀区分
    「收敛且已矫正」与「存在未收敛 / 未矫正」，两台阶之间虚线连接。
    """
    uid = _uid("step" + title)
    m = STEP_M
    plot_w = STEP_W - m["left"] - m["right"]
    plot_h = STEP_H - m["top"] - m["bottom"]
    n = len(structures)
    valid = [s for s in structures if s.get("free_energy") is not None]
    if not valid or n == 0:
        return _svg(
            STEP_W,
            STEP_H,
            f'<text x="{STEP_W / 2}" y="{STEP_H / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无可用能量数据</text>',
            title,
        )

    ref = float(valid[0]["free_energy"])
    rels = [float(s["free_energy"]) - ref for s in valid]
    hi_raw = max([0.0] + rels)
    lo_raw = min([0.0] + rels)
    pad = max((hi_raw - lo_raw) * 0.18, 0.2)
    hi, lo = hi_raw + pad, lo_raw - pad
    step_w = plot_w / (n + max(0, n - 1) * STEP_GAP_RATIO)
    gap = step_w * STEP_GAP_RATIO

    def px(index: int) -> float:
        return m["left"] + index * (step_w + gap)

    def rel_of(item: Dict[str, Any]) -> Optional[float]:
        value = item.get("free_energy")
        return None if value is None else float(value) - ref

    def py(value: float) -> float:
        return m["top"] + plot_h * (1 - (value - lo) / (hi - lo))

    y0 = py(0.0)
    body: List[str] = [
        "<defs>"
        f'<linearGradient id="{uid}areaOk" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{FE_OK}" stop-opacity="0.26"/>'
        f'<stop offset="100%" stop-color="{FE_OK}" stop-opacity="0.02"/></linearGradient>'
        f'<linearGradient id="{uid}areaWarn" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{FE_WARN}" stop-opacity="0.26"/>'
        f'<stop offset="100%" stop-color="{FE_WARN}" stop-opacity="0.02"/></linearGradient>'
        f'<linearGradient id="{uid}barOk" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{FE_OK_SOFT}"/>'
        f'<stop offset="100%" stop-color="{FE_OK}"/></linearGradient>'
        f'<linearGradient id="{uid}barWarn" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{FE_WARN_SOFT}"/>'
        f'<stop offset="100%" stop-color="{FE_WARN}"/></linearGradient>'
        "</defs>"
    ]
    # 网格 + 刻度
    for k in range(5):
        value = lo + (hi - lo) * k / 4
        y = py(value)
        body.append(
            f'<line x1="{m["left"]}" y1="{y:.1f}" x2="{STEP_W - m["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="3 5"/>'
        )
        body.append(
            f'<text x="{m["left"] - 8}" y="{y + 4:.1f}" font-size="10" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{value:+.2f}</text>'
        )
    # 参考线（ΔE = 0）与坐标轴
    body.append(
        f'<line x1="{m["left"]}" y1="{y0:.1f}" x2="{STEP_W - m["right"]}" y2="{y0:.1f}" '
        f'stroke="{FE_EMPTY}"/>'
    )
    body.append(
        f'<text x="{m["left"] - 8}" y="{y0 + 4:.1f}" font-size="10" fill="{COLOR_TEXT}" '
        f'font-weight="600" text-anchor="end" {FONT}>0.00</text>'
    )
    body.append(
        f'<line x1="{m["left"]}" y1="{m["top"]}" x2="{m["left"]}" y2="{m["top"] + plot_h}" '
        f'stroke="{COLOR_AXIS}"/>'
    )
    body.append(
        f'<line x1="{m["left"]}" y1="{m["top"] + plot_h}" x2="{STEP_W - m["right"]}" '
        f'y2="{m["top"] + plot_h}" stroke="{COLOR_AXIS}"/>'
    )
    # 台阶之间的虚线连接
    for index, item in enumerate(structures):
        if index >= n - 1:
            break
        rel, nxt = rel_of(item), rel_of(structures[index + 1])
        if rel is None or nxt is None:
            continue
        body.append(
            f'<line x1="{px(index) + step_w:.1f}" y1="{py(rel):.1f}" '
            f'x2="{px(index + 1):.1f}" y2="{py(nxt):.1f}" stroke="{FE_EMPTY}" '
            f'stroke-width="1.2" stroke-dasharray="5 5"/>'
        )
    # 台阶
    for index, item in enumerate(structures):
        rel = rel_of(item)
        x1 = px(index)
        x2 = x1 + step_w
        warn = not item.get("converged", False) or not item.get("corrected", False)
        y = y0 if rel is None else py(rel)
        if rel is not None:
            body.append(
                f'<path d="M{x1:.1f},{y0:.1f} L{x1:.1f},{y:.1f} L{x2:.1f},{y:.1f} '
                f'L{x2:.1f},{y0:.1f} Z" fill="url(#{uid}{"areaWarn" if warn else "areaOk"})"/>'
            )
        stroke = (
            FE_EMPTY
            if rel is None
            else f"url(#{uid}{'barWarn' if warn else 'barOk'})"
        )
        dash = ' stroke-dasharray="6 6"' if rel is None else ""
        body.append(
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{stroke}" '
            f'stroke-width="4" stroke-linecap="round"{dash}/>'
        )
        body.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{y - 10:.1f}" font-size="11" font-weight="600" '
            f'fill="{(COLOR_MUTED_SOFT if rel is None else (FE_WARN if warn else "#1F7C86"))}" '
            f'text-anchor="middle" {FONT}>{"无数据" if rel is None else _signed(rel)}</text>'
        )
        label = str(item.get("structure_label") or index + 1)
        chip_w = max(68.0, _text_w(f"结构 {label}", 11) + 18)
        body.append(
            f'<rect x="{(x1 + x2) / 2 - chip_w / 2:.1f}" y="{m["top"] + plot_h + 14}" '
            f'width="{chip_w:.1f}" height="22" rx="11" fill="#F4F7FB" stroke="#E3E9F2"/>'
        )
        body.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{m["top"] + plot_h + 29}" font-size="11" '
            f'fill="{COLOR_TEXT}" text-anchor="middle" {FONT}>结构 {_escape(label)}</text>'
        )
        if warn and rel is not None:
            body.append(
                f'<circle cx="{x2 - 4:.1f}" cy="{y - 16:.1f}" r="3.2" fill="{FE_WARN}"/>'
            )
    body.append(
        f'<text x="{m["left"] + plot_w / 2:.1f}" y="{STEP_H - 6}" font-size="11" '
        f'fill="{COLOR_MUTED}" text-anchor="middle" {FONT}>'
        f"中间体顺序（ΔE = E − E参考）</text>"
    )
    return _svg(STEP_W, STEP_H, "".join(body), title)


# -------------------------------------------------------------------- NEB 能垒

NEB_W = 968
NEB_H = 340
NEB_M = {"left": 72, "right": 30, "top": 40, "bottom": 56}


def neb_barrier_chart(
    images: Sequence[Dict[str, Any]], *, title: str = "NEB 能垒曲线"
) -> str:
    """NEB 能垒曲线（几何 / 配色与前端 `NebBarrierPanel` 一致，直线连接不插值）。"""
    uid = _uid("neb" + title)
    m = NEB_M
    plot_w = NEB_W - m["left"] - m["right"]
    plot_h = NEB_H - m["top"] - m["bottom"]
    n = len(images)
    rels = [float(i["relative"]) for i in images if i.get("relative") is not None]
    if not rels or n == 0:
        return _svg(
            NEB_W,
            NEB_H,
            f'<text x="{NEB_W / 2}" y="{NEB_H / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无 NEB 映像能量数据</text>',
            title,
        )
    hi_raw, lo_raw = max([0.0] + rels), min([0.0] + rels)
    pad = max((hi_raw - lo_raw) * 0.16, 0.05)
    hi, lo = hi_raw + pad, lo_raw - pad
    saddle = max(
        (i for i, x in enumerate(images) if x.get("relative") is not None),
        key=lambda i: float(images[i]["relative"]),
    )
    saddle_rel = float(images[saddle]["relative"])

    def px(index: int) -> float:
        return m["left"] + (index * plot_w / (n - 1) if n > 1 else plot_w / 2)

    def py(value: float) -> float:
        return m["top"] + plot_h * (1 - (value - lo) / (hi - lo))

    y0 = py(0.0)
    body: List[str] = [
        "<defs>"
        f'<linearGradient id="{uid}area" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{NEB_LINE}" stop-opacity="0.26"/>'
        f'<stop offset="100%" stop-color="{NEB_LINE}" stop-opacity="0.02"/></linearGradient>'
        f'<linearGradient id="{uid}stroke" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{NEB_LINE_SOFT}"/>'
        f'<stop offset="100%" stop-color="{NEB_LINE}"/></linearGradient>'
        "</defs>"
    ]
    for k in range(5):
        value = lo + (hi - lo) * k / 4
        y = py(value)
        body.append(
            f'<line x1="{m["left"]}" y1="{y:.1f}" x2="{NEB_W - m["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="3 5"/>'
        )
        body.append(
            f'<text x="{m["left"] - 8}" y="{y + 4:.1f}" font-size="10" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{value:+.2f}</text>'
        )
    body.append(
        f'<line x1="{m["left"]}" y1="{y0:.1f}" x2="{NEB_W - m["right"]}" y2="{y0:.1f}" '
        f'stroke="{FE_EMPTY}"/>'
    )
    body.append(
        f'<text x="{m["left"] - 8}" y="{y0 + 4:.1f}" font-size="10" fill="{COLOR_TEXT}" '
        f'font-weight="600" text-anchor="end" {FONT}>0.00</text>'
    )
    body.append(
        f'<line x1="{m["left"]}" y1="{m["top"]}" x2="{m["left"]}" y2="{m["top"] + plot_h}" '
        f'stroke="{COLOR_AXIS}"/>'
    )
    body.append(
        f'<line x1="{m["left"]}" y1="{m["top"] + plot_h}" x2="{NEB_W - m["right"]}" '
        f'y2="{m["top"] + plot_h}" stroke="{COLOR_AXIS}"/>'
    )
    # 渐变面积 + 折线（跳过缺失点，不做插值）
    pts: List[Tuple[float, float]] = []
    path: List[str] = []
    pen = False
    for index, item in enumerate(images):
        value = item.get("relative")
        if value is None:
            pen = False
            continue
        x, y = px(index), py(float(value))
        pts.append((x, y))
        path.append(f'{"L" if pen else "M"}{x:.1f},{y:.1f}')
        pen = True
    if len(pts) >= 2:
        area = (
            f"M{pts[0][0]:.1f},{y0:.1f} "
            + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts)
            + f" L{pts[-1][0]:.1f},{y0:.1f} Z"
        )
        body.append(f'<path d="{area}" fill="url(#{uid}area)"/>')
    body.append(
        f'<path d="{" ".join(path)}" fill="none" stroke="url(#{uid}stroke)" stroke-width="2.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    # 鞍点竖线 + 标注药丸
    saddle_x, saddle_y = px(saddle), py(saddle_rel)
    body.append(
        f'<line x1="{saddle_x:.1f}" y1="{saddle_y:.1f}" x2="{saddle_x:.1f}" y2="{y0:.1f}" '
        f'stroke="{NEB_SADDLE}" stroke-width="1.2" stroke-dasharray="4 4"/>'
    )
    pill_y = max(saddle_y - 30, 12)
    body.append(
        f'<g transform="translate({saddle_x:.1f}, {pill_y:.1f})">'
        f'<rect x="-52" y="-16" width="104" height="22" rx="11" fill="#FDECED" stroke="#F3C3C7"/>'
        f'<text x="0" y="-1" font-size="11" fill="#C8434B" text-anchor="middle" '
        f'font-weight="600" {FONT}>Ea = {_signed(saddle_rel)} eV</text></g>'
    )
    # 数据点（端点大一点、鞍点红色）
    for index, item in enumerate(images):
        value = item.get("relative")
        if value is None:
            continue
        is_end = index in (0, n - 1)
        is_saddle = index == saddle
        body.append(
            f'<circle cx="{px(index):.1f}" cy="{py(float(value)):.1f}" '
            f'r="{6 if is_saddle else (5 if is_end else 4)}" fill="#fff" '
            f'stroke="{NEB_SADDLE if is_saddle else NEB_LINE}" '
            f'stroke-width="{3 if is_saddle else 2.4}"/>'
        )
    # 横轴映像标签
    label_step = max(1, -(-n // 12))
    for index, item in enumerate(images):
        if index % label_step and index != n - 1:
            continue
        is_end = index in (0, n - 1)
        body.append(
            f'<text x="{px(index):.1f}" y="{m["top"] + plot_h + 20}" font-size="10" '
            f'fill="{COLOR_TEXT if is_end else COLOR_MUTED}" '
            f'font-weight="{600 if is_end else 400}" text-anchor="middle" {FONT}>'
            f'{_escape(item.get("label", index))}</text>'
        )
    body.append(
        f'<text x="{m["left"] - 8}" y="{m["top"] + plot_h + 20}" font-size="10" '
        f'fill="{COLOR_MUTED}" text-anchor="end" {FONT}>映像</text>'
    )
    return _svg(NEB_W, NEB_H, "".join(body), title)


# ------------------------------------------------------------------ 看板拼接


def _stack(parts: Sequence[str], *, width: int, gap: int = 8, padding: int = 16, title: str) -> str:
    """把若干张 SVG 竖向叠成一张（左右居中对齐，同一基线）。"""
    body: List[str] = []
    y = padding
    for part in parts:
        inner_start = part.find(">", part.find("<svg"))
        inner_end = part.rfind("</svg>")
        inner = part[inner_start + 1 : inner_end]
        height = int(part.split('height="', 1)[1].split('"', 1)[0])
        body.append(f'<g transform="translate({padding},{y})">{inner}</g>')
        y += height + gap
    height = int(y - gap + padding)
    return _svg(width, height, "".join(body), title)


def _panel_head(title: str, subtitle: str, *, width: int, height: int = 28) -> str:
    body = [
        f'<text x="16" y="18" font-size="14" font-weight="600" fill="#374151" {FONT}>'
        f"{_escape(title)}</text>"
    ]
    if subtitle:
        body.append(
            f'<text x="{width - 16}" y="18" font-size="11" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{_escape(subtitle)}</text>'
        )
    return _svg(width, height, "".join(body), title)


def free_energy_panel(path: Dict[str, Any], *, title: str = "自由能路径看板") -> str:
    """自由能路径看板：统计卡 + 台阶图（与巡检详情页 PathSummaryModal 同版式）。"""
    structures = list(path.get("structures") or [])
    with_energy = [s for s in structures if s.get("free_energy_ev") is not None]
    ref = float(with_energy[0]["free_energy_ev"]) if with_energy else None
    rels = [
        (float(s["free_energy_ev"]) - ref, s)
        for s in with_energy
        if ref is not None
    ]
    max_rel, max_item = (max(rels, key=lambda x: x[0]) if rels else (None, None))
    corrected = sum(1 for s in structures if s.get("corrected"))
    converged = sum(1 for s in structures if s.get("converged"))
    cards = [
        {
            "label": "中间体数量",
            "value": str(len(structures)),
            "sub": f"结构 1 – {len(structures)}" if structures else "—",
        },
        {
            "label": "矫正项完成度",
            "value": f"{corrected} / {len(structures)}",
            "sub": "全部已矫正" if corrected == len(structures) and structures else "部分中间体待矫正",
        },
        {
            "label": "结构优化收敛",
            "value": f"{converged} / {len(structures)}",
            "sub": "全部已收敛" if converged == len(structures) and structures else "存在未收敛中间体",
        },
        {
            "label": "最高相对能",
            "value": _signed(max_rel),
            "sub": f"结构 {max_item.get('structure_label')}" if max_item else "暂无对比数据",
        },
    ]
    chart_width = STEP_W
    head = _panel_head(
        title, f"{path.get('group_name') or path.get('group_id') or ''} · 相对能台阶图 + 中间体明细",
        width=chart_width + 32,
    )
    cards_svg = stat_cards(cards, width=chart_width, uid=_uid("fe" + title))
    legend = _svg(
        chart_width,
        20,
        legend_row(
            [
                (FE_OK, "收敛且已矫正", False),
                (FE_WARN, "未收敛 / 未矫正", False),
                (FE_EMPTY, "无数据", True),
            ],
            width=chart_width,
            ref=f"相对能以结构 {with_energy[0].get('structure_label') if with_energy else '1'} 为参考",
            top=0,
        ),
        "图例",
    )
    step = step_chart(
        [
            {
                "structure_label": s.get("structure_label"),
                "free_energy": s.get("free_energy_ev"),
                "converged": s.get("converged"),
                "corrected": s.get("corrected"),
            }
            for s in structures
        ],
        title=title,
    )
    return _stack([head, cards_svg, legend, step], width=chart_width + 32, gap=6, title=title)


def neb_panel(item: Dict[str, Any], *, title: str = "NEB 能垒看板") -> str:
    """NEB 能垒看板：统计卡 + 能垒曲线（与巡检详情页 NebBarrierPanel 同版式）。"""
    images = list(item.get("images") or [])
    rels = [float(i["relative_energy_ev"]) for i in images if i.get("relative_energy_ev") is not None]
    saddle_index = (
        max((i for i, x in enumerate(images) if x.get("relative_energy_ev") is not None),
            key=lambda i: float(images[i]["relative_energy_ev"]))
        if rels
        else -1
    )
    saddle_rel = rels and float(images[saddle_index]["relative_energy_ev"])
    force_index = (
        max((i for i, x in enumerate(images) if x.get("max_force_ev_per_a") is not None),
            key=lambda i: float(images[i]["max_force_ev_per_a"]))
        if any(x.get("max_force_ev_per_a") is not None for x in images)
        else -1
    )
    corner_rel = images[-1].get("relative_energy_ev") if images else None
    count = len(images)
    cards = [
        {
            "label": "映像数量",
            "value": str(count),
            "sub": f"端点 2 + 中间 {count - 2}" if count >= 2 else "含端点",
        },
        {
            "label": "能垒 Ea",
            "value": _signed(saddle_rel),
            "sub": f"最高点：映像 {images[saddle_index].get('label')}" if saddle_index >= 0 else "暂无数据",
        },
        {
            "label": "最大受力",
            "value": _fmt(
                float(images[force_index]["max_force_ev_per_a"]) if force_index >= 0 else None, 3
            ),
            "sub": f"映像 {images[force_index].get('label')}（eV/Å）" if force_index >= 0 else "暂无数据",
        },
        {
            "label": "末态相对能",
            "value": _signed(float(corner_rel) if corner_rel is not None else None),
            "sub": "与初态基本一致"
            if corner_rel is not None and abs(float(corner_rel)) < 0.01
            else "相对初态（映像 00）",
        },
    ]
    chart_width = NEB_W
    last_label = images[-1].get("label") if images else ""
    head = _panel_head(
        title, f"{item.get('task_name') or ''} · 相对能垒曲线 + 映像明细", width=chart_width + 32
    )
    cards_svg = stat_cards(cards, width=chart_width, uid=_uid("neb" + title))
    legend = _svg(
        chart_width,
        20,
        legend_row(
            [
                (NEB_LINE, "相对能垒（nebef.pl）", False),
                (NEB_SADDLE, "鞍点（能垒最高）", False),
            ],
            width=chart_width,
            ref=f"横轴为 NEB 映像（{images[0].get('label') if images else '00'} = 初态，"
            f"{last_label} = 末态）",
            top=0,
        ),
        "图例",
    )
    chart = neb_barrier_chart(
        [
            {
                "label": i.get("label"),
                "relative": i.get("relative_energy_ev"),
                "energy": i.get("energy_ev"),
                "max_force": i.get("max_force_ev_per_a"),
            }
            for i in images
        ],
        title=title,
    )
    return _stack([head, cards_svg, legend, chart], width=chart_width + 32, gap=6, title=title)


# ------------------------------------------------------------------ 项目进度


def segmented_progress_chart(
    segments: Sequence[Dict[str, Any]],
    *,
    main_percent: float,
    main_detail: str = "",
    notes: Sequence[str] = (),
    title: str = "项目进度",
    width: int = 1000,
) -> str:
    """项目进度：**按任务类型分成数块**（块宽 = 该类型任务当量占比）＋一条主进度。

    每块内部按该类型自身的完成比例填充；块下方给出该类型的完成数、百分比与当量占比。
    `notes` 用来放工作量（当量→核时）与工期估算这类补充说明。
    """
    uid = _uid("progress" + title)
    pad = 26
    bar_w = width - pad * 2
    main_y, main_h = 62, 12
    seg_y, seg_h = 96, 24
    body: List[str] = [
        "<defs>"
        f'<linearGradient id="{uid}main" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="#7FA7F7"/><stop offset="100%" stop-color="{COLOR_PRIMARY}"/>'
        "</linearGradient>"
        f'<linearGradient id="{uid}seg" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="#7FA7F7"/><stop offset="100%" stop-color="{COLOR_PRIMARY_STRONG}"/>'
        "</linearGradient>"
        "</defs>"
    ]
    body.append(
        f'<text x="{pad}" y="28" font-size="15" font-weight="600" fill="#374151" {FONT}>'
        f"{_escape(title)}</text>"
    )
    body.append(
        f'<text x="{width - pad}" y="30" font-size="22" font-weight="700" '
        f'fill="{COLOR_PRIMARY_STRONG}" text-anchor="end" {FONT}>{main_percent:.1f}%</text>'
    )
    if main_detail:
        body.append(
            f'<text x="{pad}" y="48" font-size="11" fill="{COLOR_MUTED}" {FONT}>'
            f"{_escape(main_detail)}</text>"
        )
    # 主进度条
    body.append(
        f'<rect x="{pad}" y="{main_y}" width="{bar_w}" height="{main_h}" rx="6" fill="#EEF2F8"/>'
    )
    main_w = bar_w * max(0.0, min(main_percent, 100.0)) / 100
    if main_w > 0:
        body.append(
            f'<rect x="{pad}" y="{main_y}" width="{main_w:.1f}" height="{main_h}" rx="6" '
            f'fill="url(#{uid}main)"/>'
        )
    # 分段条：块宽 = 当量占比
    total_share = sum(float(s.get("share") or 0) for s in segments) or 1.0
    gap = 6
    usable = bar_w - gap * max(0, len(segments) - 1)
    x = float(pad)
    for seg in segments:
        seg_w = usable * float(seg.get("share") or 0) / total_share
        color = seg.get("color") or SEGMENT_COLORS.get(str(seg.get("label")), COLOR_PRIMARY)
        body.append(
            f'<rect x="{x:.1f}" y="{seg_y}" width="{seg_w:.1f}" height="{seg_h}" rx="7" '
            f'fill="{color}" fill-opacity="0.16"/>'
        )
        inner = seg_w * max(0.0, min(float(seg.get("percent") or 0), 100.0)) / 100
        if inner > 0:
            body.append(
                f'<rect x="{x:.1f}" y="{seg_y}" width="{max(inner, 4):.1f}" height="{seg_h}" '
                f'rx="7" fill="{color}"/>'
            )
        x += seg_w + gap
    # 分段说明（自动换行）
    line_y = seg_y + seg_h + 18
    cursor = float(pad)
    lines = 1
    for seg in segments:
        color = seg.get("color") or SEGMENT_COLORS.get(str(seg.get("label")), COLOR_PRIMARY)
        label = str(seg.get("label") or "")
        text = (
            f"{label} {seg.get('done', 0)}/{seg.get('count', 0)} · "
            f"{float(seg.get('percent') or 0):.0f}% · 当量 {float(seg.get('weight') or 0):.1f}"
            f"（占 {float(seg.get('share') or 0):.0f}%）"
        )
        item_w = 13 + _text_w(text, 11) + 18
        if cursor + item_w > width - pad and cursor > pad:
            cursor = float(pad)
            line_y += 18
            lines += 1
        body.append(f'<circle cx="{cursor + 4:.1f}" cy="{line_y - 4:.1f}" r="4" fill="{color}"/>')
        body.append(
            f'<text x="{cursor + 13:.1f}" y="{line_y}" font-size="11" fill="{COLOR_TEXT}" '
            f"{FONT}>{_escape(text)}</text>"
        )
        cursor += item_w
    note_y = line_y + 20
    for text in notes:
        body.append(
            f'<text x="{pad}" y="{note_y}" font-size="11.5" fill="{COLOR_TEXT}" {FONT}>'
            f"{_escape(text)}</text>"
        )
        note_y += 17
    foot_y = note_y + 4
    body.append(
        f'<text x="{pad}" y="{foot_y}" font-size="11" fill="{COLOR_MUTED}" {FONT}>'
        "块宽 = 该类型的任务当量占比；当量按任务类型权重折算"
        "（结构优化 1 · 频率矫正 1 · NEB 5 · 电子结构 0.4）</text>"
    )
    height = int(foot_y + 14)
    return _svg(width, height, "".join(body), title)
