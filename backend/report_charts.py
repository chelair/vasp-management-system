"""报告图表生成（纯 Python 输出 SVG，零第三方依赖）。

为什么不用 matplotlib：本机与部署环境都没有装，且报告只需要几张折线 / 台阶 /
能垒 / 圆环 / 进度条图；手写 SVG 无依赖、体积小、Markdown 与 HTML 都能直接引用，
还能在 HTML 导出时内联成自包含文件。

所有函数返回 SVG 文本；由 report_builder 写入 reports/<项目>/<报告>/charts/。
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

COLOR_PRIMARY = "#5B8DEF"
COLOR_SECONDARY = "#2C9DA8"
COLOR_WARN = "#E8A33D"
COLOR_DANGER = "#D9535B"
COLOR_GRID = "#EDF1F7"
COLOR_AXIS = "#DCE3EC"
COLOR_TEXT = "#5A6A80"
COLOR_MUTED = "#8A98AC"
FONT = "font-family=\"Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif\""


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _svg(width: int, height: int, body: str, title: str = "") -> str:
    label = f'<title>{_escape(title)}</title>' if title else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">{label}'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>{body}</svg>'
    )


def _nice_ticks(low: float, high: float, count: int = 4) -> List[float]:
    if high <= low:
        high = low + 1
    return [low + (high - low) * i / count for i in range(count + 1)]


def line_chart(
    points: Sequence[Dict[str, Any]],
    *,
    title: str,
    y_label: str,
    x_key: str = "step",
    y_key: str = "energy",
    threshold: Optional[float] = None,
    width: int = 720,
    height: int = 260,
    color: str = COLOR_PRIMARY,
) -> str:
    """折线图（离子步-能量 / 离子步-力），支持阈值基准线。"""
    margin = {"left": 72, "right": 24, "top": 34, "bottom": 40}
    data = [
        (float(p[x_key]), float(p[y_key]))
        for p in points
        if p.get(x_key) is not None and p.get(y_key) is not None
    ]
    body: List[str] = [
        f'<text x="{margin["left"]}" y="20" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    if not data:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无数据</text>'
        )
        return _svg(width, height, "".join(body), title)

    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    xs = [d[0] for d in data]
    ys = [d[1] for d in data]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if threshold is not None:
        y_min = min(y_min, threshold)
        y_max = max(y_max, threshold)
    pad = (y_max - y_min) * 0.12 or 0.1
    y_min -= pad
    y_max += pad
    if x_max <= x_min:
        x_max = x_min + 1

    def px(x: float) -> float:
        return margin["left"] + (x - x_min) / (x_max - x_min) * plot_w

    def py(y: float) -> float:
        return margin["top"] + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    for value in _nice_ticks(y_min, y_max):
        y = py(value)
        body.append(
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width - margin["right"]}" '
            f'y2="{y:.1f}" stroke="{COLOR_GRID}" stroke-dasharray="3 5"/>'
        )
        body.append(
            f'<text x="{margin["left"] - 8}" y="{y + 4:.1f}" font-size="10" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{value:.4g}</text>'
        )
    if threshold is not None:
        y = py(threshold)
        body.append(
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width - margin["right"]}" '
            f'y2="{y:.1f}" stroke="{COLOR_DANGER}" stroke-width="1.4" stroke-dasharray="6 4"/>'
        )
        body.append(
            f'<text x="{width - margin["right"] - 4}" y="{y - 5:.1f}" font-size="10" '
            f'fill="{COLOR_DANGER}" text-anchor="end" {FONT}>阈值 {threshold}</text>'
        )
    path = " ".join(
        f'{"M" if i == 0 else "L"}{px(x):.1f},{py(y):.1f}' for i, (x, y) in enumerate(data)
    )
    body.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
    # 只标首/中/末三个点，避免密集点糊在一起
    for idx in {0, len(data) // 2, len(data) - 1}:
        x, y = data[idx]
        body.append(
            f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="#fff" stroke="{color}" stroke-width="2"/>'
        )
    body.append(
        f'<text x="{width / 2}" y="{height - 6}" font-size="11" fill="{COLOR_MUTED}" '
        f'text-anchor="middle" {FONT}>离子步</text>'
    )
    body.append(
        f'<text x="14" y="{margin["top"] + plot_h / 2}" font-size="11" fill="{COLOR_MUTED}" '
        f'text-anchor="middle" transform="rotate(-90 14 {margin["top"] + plot_h / 2})" {FONT}>'
        f"{_escape(y_label)}</text>"
    )
    return _svg(width, height, "".join(body), title)


# 自由能台阶图 / NEB 能垒图已迁到 `report_panels.py`——那里是**与巡检详情页同版式**的
# 「看板」（统计卡 + 图例 + 图），避免报告和详情页各画一套。这里只保留通用的
# 折线 / 圆环 / 进度条 / 结构三视图等基础图表。


def donut_chart(
    used: Optional[float],
    total: Optional[float],
    *,
    title: str = "核数占用",
    width: int = 360,
    height: int = 260,
) -> str:
    """核数占用圆环图（≥90% 橙色、≥100% 红色）。"""
    import math

    body: List[str] = [
        f'<text x="{width / 2}" y="22" font-size="13" fill="#374151" text-anchor="middle" {FONT}>{_escape(title)}</text>'
    ]
    if not used or not total:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无核数配额数据</text>'
        )
        return _svg(width, height, "".join(body), title)

    cx, cy, r_out, r_in = width / 2, height / 2 + 6, 84, 58
    ratio = min(float(used) / float(total), 1.0)
    color = COLOR_DANGER if ratio >= 1 else COLOR_WARN if ratio >= 0.9 else COLOR_PRIMARY
    body.append(
        f'<circle cx="{cx}" cy="{cy}" r="{(r_out + r_in) / 2}" fill="none" stroke="#EEF2F8" '
        f'stroke-width="{r_out - r_in}"/>'
    )
    large = 1 if ratio > 0.5 else 0
    end_x = cx + math.cos(-math.pi / 2 + ratio * 2 * math.pi) * (r_out + r_in) / 2
    end_y = cy + math.sin(-math.pi / 2 + ratio * 2 * math.pi) * (r_out + r_in) / 2
    start_x, start_y = cx, cy - (r_out + r_in) / 2
    body.append(
        f'<path d="M{start_x:.1f},{start_y:.1f} A{(r_out + r_in) / 2:.1f},{(r_out + r_in) / 2:.1f} '
        f'0 {large} 1 {end_x:.1f},{end_y:.1f}" fill="none" stroke="{color}" '
        f'stroke-width="{r_out - r_in}" stroke-linecap="round"/>'
    )
    body.append(
        f'<text x="{cx}" y="{cy + 2}" font-size="20" font-weight="700" fill="#233043" '
        f'text-anchor="middle" {FONT}>{int(used)} / {int(total)}</text>'
    )
    body.append(
        f'<text x="{cx}" y="{cy + 22}" font-size="11" fill="{COLOR_MUTED}" text-anchor="middle" {FONT}>'
        f'使用率 {ratio * 100:.0f}%</text>'
    )
    return _svg(width, height, "".join(body), title)


def progress_bar(
    percent: Optional[float],
    *,
    title: str = "存储使用",
    detail: str = "",
    warn_at: float = 85.0,
    width: int = 420,
    height: int = 120,
) -> str:
    """水平进度条（存储使用率，超过阈值变红）。"""
    body: List[str] = [
        f'<text x="16" y="26" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    if percent is None:
        body.append(
            f'<text x="16" y="64" font-size="12" fill="{COLOR_MUTED}" {FONT}>暂无存储数据</text>'
        )
        return _svg(width, height, "".join(body), title)
    value = max(0.0, min(float(percent), 100.0))
    color = COLOR_DANGER if value >= warn_at else COLOR_PRIMARY
    bar_x, bar_y, bar_w, bar_h = 16, 44, width - 32, 16
    body.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="8" fill="#EEF2F8"/>'
    )
    body.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w * value / 100:.1f}" height="{bar_h}" rx="8" fill="{color}"/>'
    )
    body.append(
        f'<text x="{bar_x}" y="{bar_y + bar_h + 22}" font-size="11" fill="{COLOR_TEXT}" {FONT}>'
        f"{value:.0f}%{(' · ' + _escape(detail)) if detail else ''}</text>"
    )
    return _svg(width, height, "".join(body), title)


# ------------------------------------------------------- 能量 + 力（双纵轴）


def energy_force_chart(
    points: Sequence[Dict[str, Any]],
    *,
    title: str = "能量 / 最大力 - 离子步",
    force_threshold: float = 0.02,
    width: int = 620,
    height: int = 260,
) -> str:
    """能量与最大力合并在**同一张图**（双纵轴），风格与巡检详情里的 LineChart 一致：
    相同的边距 / 网格 / 刻度 / 字体与蓝色（能量）、橙色（力）配色，另加力收敛阈值虚线。
    """
    M = {"left": 66, "right": 62, "top": 24, "bottom": 34}
    plot_w = width - M["left"] - M["right"]
    plot_h = height - M["top"] - M["bottom"]
    body: List[str] = [
        f'<text x="{M["left"]}" y="16" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    data = [
        (
            float(p["step"]),
            float(p["energy"]) if p.get("energy") is not None else None,
            float(p["max_force"]) if p.get("max_force") is not None else None,
        )
        for p in points
        if p.get("step") is not None
    ]
    if not data:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无数据</text>'
        )
        return _svg(width, height, "".join(body), title)

    steps = [d[0] for d in data]
    energies = [d[1] for d in data if d[1] is not None]
    forces = [d[2] for d in data if d[2] is not None]
    x_min, x_max = min(steps), max(steps)
    if x_max <= x_min:
        x_max = x_min + 1
    if energies:
        e_lo, e_hi = min(energies), max(energies)
        if e_hi - e_lo < 1e-9:
            e_hi = e_lo + 1.0
    else:
        e_lo, e_hi = 0.0, 1.0
    f_hi = (max(forces + [force_threshold]) if forces else force_threshold) * 1.15

    def px(x: float) -> float:
        return M["left"] + (x - x_min) / (x_max - x_min) * plot_w

    def py_e(y: float) -> float:
        return M["top"] + (1 - (y - e_lo) / (e_hi - e_lo)) * plot_h

    def py_f(y: float) -> float:
        return M["top"] + (1 - y / f_hi) * plot_h

    # 左侧能量刻度（与巡检折线图同款：4 档 + 浅灰网格）
    for k in range(4):
        value = e_lo + (e_hi - e_lo) * k / 3
        y = py_e(value)
        body.append(
            f'<line x1="{M["left"]}" y1="{y:.1f}" x2="{width - M["right"]}" y2="{y:.1f}" '
            f'stroke="#E7ECF3" stroke-width="1"/>'
        )
        body.append(
            f'<text x="{M["left"] - 6}" y="{y + 4:.1f}" font-size="10" fill="#6B7A90" '
            f'text-anchor="end" {FONT}>{_tick(value)}</text>'
        )
    # 右侧力刻度
    for k in range(4):
        value = f_hi * k / 3
        y = py_f(value)
        body.append(
            f'<text x="{width - M["right"] + 8}" y="{y + 4:.1f}" font-size="10" '
            f'fill="{COLOR_WARN}" text-anchor="start" {FONT}>{_tick(value)}</text>'
        )
    # 坐标轴
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"]}" x2="{M["left"]}" y2="{M["top"] + plot_h}" '
        f'stroke="#9CA3AF"/>'
    )
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"] + plot_h}" x2="{width - M["right"]}" '
        f'y2="{M["top"] + plot_h}" stroke="#9CA3AF"/>'
    )
    # 力阈值（与巡检一致的红虚线 + 标注）
    ty = py_f(force_threshold)
    body.append(
        f'<line x1="{M["left"]}" y1="{ty:.1f}" x2="{width - M["right"]}" y2="{ty:.1f}" '
        f'stroke="#D9535B" stroke-width="1.5" stroke-dasharray="6,4"/>'
    )
    body.append(
        f'<text x="{width - M["right"] - 4}" y="{ty - 5:.1f}" font-size="10" fill="#D9535B" '
        f'text-anchor="end" {FONT}>阈值 {force_threshold:.3f}</text>'
    )

    def path_for(index: int, mapper) -> str:
        chunks: List[str] = []
        pen = False
        for point in data:
            value = point[index]
            if value is None:
                pen = False
                continue
            chunks.append(f'{"L" if pen else "M"}{px(point[0]):.1f},{mapper(value):.1f}')
            pen = True
        return " ".join(chunks)

    if forces:
        body.append(
            f'<path d="{path_for(2, py_f)}" fill="none" stroke="{COLOR_WARN}" stroke-width="2" '
            f'stroke-linejoin="round"/>'
        )
    if energies:
        body.append(
            f'<path d="{path_for(1, py_e)}" fill="none" stroke="{COLOR_PRIMARY}" stroke-width="2" '
            f'stroke-linejoin="round"/>'
        )
    # x 轴：首 / 中 / 末离子步
    for idx in {0, len(data) // 2, len(data) - 1}:
        body.append(
            f'<text x="{px(data[idx][0]):.1f}" y="{height - 14}" font-size="10" fill="#6B7A90" '
            f'text-anchor="middle" {FONT}>{int(data[idx][0])}</text>'
        )
    # 纵轴单位与横轴说明（与巡检图一致）
    body.append(
        f'<text x="14" y="{M["top"] + plot_h / 2}" font-size="11" fill="#6B7A90" '
        f'text-anchor="middle" transform="rotate(-90 14 {M["top"] + plot_h / 2})" {FONT}>能量 (eV)</text>'
    )
    body.append(
        f'<text x="{width - 12}" y="{M["top"] + plot_h / 2}" font-size="11" fill="{COLOR_WARN}" '
        f'text-anchor="middle" transform="rotate(90 {width - 12} {M["top"] + plot_h / 2})" {FONT}>最大力 (eV/A)</text>'
    )
    body.append(
        f'<text x="{M["left"] + plot_w / 2}" y="{height - 2}" font-size="11" fill="#6B7A90" '
        f'text-anchor="middle" {FONT}>离子步</text>'
    )
    # 图内一行结论（最终能量 / 最终力 / 是否收敛）
    if energies:
        body.append(
            f'<text x="{M["left"]}" y="{height - 20}" font-size="10.5" fill="#5A6A80" {FONT}>'
            f"最终能量 {energies[-1]:.4f} eV</text>"
        )
    if forces:
        body.append(
            f'<text x="{M["left"] + 150}" y="{height - 20}" font-size="10.5" '
            f'fill="{COLOR_WARN}" {FONT}>最终最大力 {forces[-1]:.4f} eV/A</text>'
        )
    return _svg(width, height, "".join(body), title)


def _tick(value: float) -> str:
    return f"{value:.4g}"


# ------------------------------------------------------- 电子结构（PDOS / 功函数）


def _fmt_label(value: float, digits: int = 3) -> str:
    text = f"{value:.{digits}f}"
    return "0.000" if text in ("-0.000", "0.000") else text


def clip_polyline(
    points: Sequence[Tuple[float, float]], lo: float, hi: float
) -> List[Tuple[float, float]]:
    """把折线按 x ∈ [lo, hi] 裁剪（边界处线性插值补点）。

    态密度的能量网格比展示窗口宽（例如 -21 ~ +8 eV 而窗口取 -10 ~ 10），
    不裁剪会把线画到坐标框外面（2026-10-15 实测踩到）。
    """
    out: List[Tuple[float, float]] = []
    for index in range(1, len(points)):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        if x1 == x0:
            continue
        left = max(min(x0, x1), lo)
        right = min(max(x0, x1), hi)
        if right < left:
            continue

        def y_at(x: float) -> float:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

        if not out:
            out.append((left, y_at(left)))
        out.append((right, y_at(right)))
    return out


def dos_lines_chart(
    lines: Sequence[Dict[str, Any]],
    *,
    title: str,
    x_min: float,
    x_max: float,
    width: int = 760,
    height: int = 320,
    x_label: str = "E − E_F (eV)",
    y_label: str = "Intensity",
    show_fermi: bool = True,
    bands: Sequence[Dict[str, Any]] = (),
    legend_max: int = 8,
) -> str:
    """态密度折线图（PDOS 静态图，2026-10-15）。

    用于报告正文的单文件导出与打印：**交互版**（报告页 / 导出内嵌 ECharts）用
    `interactive/pdosWidget.ts`；这里是同一份数据渲染出的静态兜底，
    老浏览器 / 关闭 JS / 打印成 PDF 时看这张。

    `lines` = `[{name, color, points: [(x, y), ...], dashed}]`（x 已相对 E_F）；
    `bands` = 竖直虚线 `[{x, color, label, dashed}]`（带中心）。
    """
    M = {"left": 70, "right": 22, "top": 52, "bottom": 44}
    plot_w = width - M["left"] - M["right"]
    plot_h = height - M["top"] - M["bottom"]
    body: List[str] = [
        f'<text x="{M["left"]}" y="18" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    if x_max <= x_min:
        x_max = x_min + 1
    ys = [y for line in lines for _, y in line.get("points") or []]
    if not ys:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无数据</text>'
        )
        return _svg(width, height, "".join(body), title)
    y_lo, y_hi = min(ys), max(ys)
    if y_hi - y_lo < 1e-9:
        y_hi = y_lo + 1.0
    pad = (y_hi - y_lo) * 0.06
    y_lo -= pad
    y_hi += pad

    def px(x: float) -> float:
        return M["left"] + (x - x_min) / (x_max - x_min) * plot_w

    def py(y: float) -> float:
        return M["top"] + (1 - (y - y_lo) / (y_hi - y_lo)) * plot_h

    # 网格 + 刻度（横向 4 档、纵向 5 档，与其它报告图同款浅灰）
    for k in range(5):
        y = M["top"] + plot_h * k / 4
        body.append(
            f'<line x1="{M["left"]}" y1="{y:.1f}" x2="{width - M["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-width="1"/>'
        )
        value = y_hi - (y_hi - y_lo) * k / 4
        body.append(
            f'<text x="{M["left"] - 8}" y="{y + 3:.1f}" font-size="10.5" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{_tick(value)}</text>'
        )
    for k in range(5):
        x = M["left"] + plot_w * k / 4
        value = x_min + (x_max - x_min) * k / 4
        body.append(
            f'<text x="{x:.1f}" y="{height - 24}" font-size="10.5" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>{_tick(value)}</text>'
        )
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"]}" x2="{M["left"]}" y2="{M["top"] + plot_h}" '
        f'stroke="{COLOR_AXIS}" stroke-width="1"/>'
    )
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"] + plot_h}" x2="{width - M["right"]}" '
        f'y2="{M["top"] + plot_h}" stroke="{COLOR_AXIS}" stroke-width="1"/>'
    )
    body.append(
        f'<text x="{M["left"] + plot_w / 2:.1f}" y="{height - 8}" font-size="11" '
        f'fill="{COLOR_TEXT}" text-anchor="middle" {FONT}>{_escape(x_label)}</text>'
    )
    body.append(
        f'<text x="14" y="{M["top"] + plot_h / 2:.1f}" font-size="11" fill="{COLOR_TEXT}" '
        f'text-anchor="middle" transform="rotate(-90 14 {M["top"] + plot_h / 2:.1f})" {FONT}>'
        f"{_escape(y_label)}</text>"
    )

    # 纵轴 0 基线（镜像布局的正负分界）
    if y_lo < 0 < y_hi:
        y0 = py(0)
        body.append(
            f'<line x1="{M["left"]}" y1="{y0:.1f}" x2="{width - M["right"]}" y2="{y0:.1f}" '
            f'stroke="#c8d2e0" stroke-width="1"/>'
        )
    # 费米能级（x=0）
    if show_fermi and x_min < 0 < x_max:
        x0 = px(0)
        body.append(
            f'<line x1="{x0:.1f}" y1="{M["top"]}" x2="{x0:.1f}" y2="{M["top"] + plot_h}" '
            f'stroke="#98a6bd" stroke-width="1" stroke-dasharray="5 4"/>'
        )
    # 带中心（同色竖直虚线 + 数值）
    for band in bands:
        bx = float(band.get("x") or 0)
        if not (x_min <= bx <= x_max):
            continue
        xb = px(bx)
        band_color = _escape(band.get("color") or COLOR_PRIMARY)
        band_dash = "2 3" if band.get("dashed") else "7 4"
        body.append(
            f'<line x1="{xb:.1f}" y1="{M["top"]}" x2="{xb:.1f}" y2="{M["top"] + plot_h}" '
            f'stroke="{band_color}" stroke-width="1.2" '
            f'stroke-dasharray="{band_dash}"/>'
        )
        if band.get("label"):
            body.append(
                f'<text x="{xb + 3:.1f}" y="{M["top"] + 11}" font-size="10" '
                f'fill="{band_color}" {FONT}>'
                f"{_escape(band['label'])}</text>"
            )

    for line in lines:
        # 再裁一次（调用方可能已经把整条曲线递进来；越界的线段会画到坐标框外）
        points = clip_polyline(line.get("points") or [], x_min, x_max)
        if not points:
            continue
        path = " ".join(
            f'{"M" if index == 0 else "L"}{px(x):.2f},{py(y):.2f}'
            for index, (x, y) in enumerate(points)
        )
        dash = ' stroke-dasharray="4 3"' if line.get("dashed") else ""
        body.append(
            f'<path d="{path}" fill="none" stroke="{_escape(line.get("color") or COLOR_PRIMARY)}" '
            f'stroke-width="{line.get("width") or 1.4}" stroke-linejoin="round"{dash}/>'
        )

    # 图例：标题下方一行芯片（曲线多时只列前几条 + "等 N 条"）
    lx = M["left"]
    shown = 0
    for line in lines:
        if shown >= legend_max:
            break
        name = str(line.get("name") or "")
        text_w = 10 + 7 * len(name)
        if lx + text_w > width - M["right"]:
            break
        color = _escape(line.get("color") or COLOR_PRIMARY)
        legend_dash = ' stroke-dasharray="4 3"' if line.get("dashed") else ""
        body.append(
            f'<line x1="{lx}" y1="33" x2="{lx + 12}" y2="33" stroke="{color}" '
            f'stroke-width="2.4"{legend_dash}/>'
        )
        body.append(
            f'<text x="{lx + 16}" y="36.5" font-size="10.5" fill="{COLOR_TEXT}" {FONT}>'
            f"{_escape(name)}</text>"
        )
        lx += text_w + 12
        shown += 1
    if len(lines) > shown:
        body.append(
            f'<text x="{lx}" y="36.5" font-size="10.5" fill="{COLOR_MUTED}" {FONT}>'
            f"等 {len(lines)} 条</text>"
        )
    return _svg(width, height, "".join(body), title)


def planar_average_chart(
    points: Sequence[Tuple[float, float]],
    *,
    title: str,
    vacuum: Optional[float] = None,
    fermi: Optional[float] = None,
    width: int = 760,
    height: int = 300,
    x_label: str = "z (Å)",
    y_label: str = "静电势 (eV)",
) -> str:
    """平面平均静电势（功函数静态图，2026-10-15）：曲线 + 真空能级 / E_F 两条水平虚线。"""
    M = {"left": 70, "right": 78, "top": 46, "bottom": 44}
    plot_w = width - M["left"] - M["right"]
    plot_h = height - M["top"] - M["bottom"]
    body: List[str] = [
        f'<text x="{M["left"]}" y="18" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    data = [(float(z), float(v)) for z, v in points]
    if len(data) < 2:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无数据</text>'
        )
        return _svg(width, height, "".join(body), title)
    z_min, z_max = data[0][0], data[-1][0]
    if z_max <= z_min:
        z_max = z_min + 1
    values = [v for _, v in data]
    marks = [v for v in (vacuum, fermi) if v is not None]
    y_lo, y_hi = min(values + marks), max(values + marks)
    if y_hi - y_lo < 1e-9:
        y_hi = y_lo + 1.0
    pad = (y_hi - y_lo) * 0.08
    y_lo -= pad
    y_hi += pad

    def px(z: float) -> float:
        return M["left"] + (z - z_min) / (z_max - z_min) * plot_w

    def py(v: float) -> float:
        return M["top"] + (1 - (v - y_lo) / (y_hi - y_lo)) * plot_h

    for k in range(5):
        y = M["top"] + plot_h * k / 4
        body.append(
            f'<line x1="{M["left"]}" y1="{y:.1f}" x2="{width - M["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-width="1"/>'
        )
        body.append(
            f'<text x="{M["left"] - 8}" y="{y + 3:.1f}" font-size="10.5" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{_tick(y_hi - (y_hi - y_lo) * k / 4)}</text>'
        )
    for k in range(5):
        z = z_min + (z_max - z_min) * k / 4
        body.append(
            f'<text x="{px(z):.1f}" y="{height - 24}" font-size="10.5" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>{_tick(z)}</text>'
        )
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"]}" x2="{M["left"]}" y2="{M["top"] + plot_h}" '
        f'stroke="{COLOR_AXIS}" stroke-width="1"/>'
    )
    body.append(
        f'<line x1="{M["left"]}" y1="{M["top"] + plot_h}" x2="{width - M["right"]}" '
        f'y2="{M["top"] + plot_h}" stroke="{COLOR_AXIS}" stroke-width="1"/>'
    )
    body.append(
        f'<text x="{M["left"] + plot_w / 2:.1f}" y="{height - 8}" font-size="11" '
        f'fill="{COLOR_TEXT}" text-anchor="middle" {FONT}>{_escape(x_label)}</text>'
    )
    body.append(
        f'<text x="14" y="{M["top"] + plot_h / 2:.1f}" font-size="11" fill="{COLOR_TEXT}" '
        f'text-anchor="middle" transform="rotate(-90 14 {M["top"] + plot_h / 2:.1f})" {FONT}>'
        f"{_escape(y_label)}</text>"
    )
    for value, color, label in (
        (vacuum, COLOR_SECONDARY, "真空能级"),
        (fermi, COLOR_WARN, "E_F"),
    ):
        if value is None:
            continue
        y = py(float(value))
        body.append(
            f'<line x1="{M["left"]}" y1="{y:.1f}" x2="{width - M["right"]}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="1.2" stroke-dasharray="6 4"/>'
        )
        body.append(
            f'<text x="{width - M["right"] + 4}" y="{y + 3.5:.1f}" font-size="10.5" '
            f'fill="{color}" {FONT}>{_escape(f"{label} {_fmt_label(float(value))}")}</text>'
        )
    path = " ".join(f'{"M" if i == 0 else "L"}{px(z):.2f},{py(v):.2f}' for i, (z, v) in enumerate(data))
    body.append(f'<path d="{path}" fill="none" stroke="{COLOR_PRIMARY}" stroke-width="1.6"/>')
    return _svg(width, height, "".join(body), title)


# ------------------------------------------------------------ 结构三视图


# ---------------------------------------------------------------------------
# 注：原来的 Python 正交投影三视图/映像矩阵（structure_views / structure_matrix /
# task_panel / _parse_cif_atoms）已在 2026-10-07 废除 —— 结构图统一由 VESTA 渲染成
# PNG（见 backend/structure_images.py、backend/vesta_render.py），报告里 base64 内联。
# ---------------------------------------------------------------------------
