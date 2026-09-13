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


def step_chart(
    structures: Sequence[Dict[str, Any]],
    *,
    title: str = "自由能路径台阶图",
    width: int = 760,
    height: int = 280,
) -> str:
    """自由能台阶图（相对第一个有数据的中间体；数值数组同时写入结构化数据）。"""
    margin = {"left": 74, "right": 24, "top": 34, "bottom": 46}
    valid = [s for s in structures if s.get("free_energy") is not None]
    body: List[str] = [
        f'<text x="{margin["left"]}" y="20" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    if not valid:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无可用能量数据</text>'
        )
        return _svg(width, height, "".join(body), title)

    ref = float(valid[0]["free_energy"])
    rels = [float(s["free_energy"]) - ref for s in structures if s.get("free_energy") is not None]
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    y_max = max(max(rels), 0.0) + 0.4
    y_min = min(min(rels), 0.0) - 0.4

    def py(y: float) -> float:
        return margin["top"] + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    n = len(structures)
    unit = plot_w / max(2 * n - 1, 1)

    def px(k: float) -> float:
        return margin["left"] + k * unit

    for value in _nice_ticks(y_min, y_max):
        y = py(value)
        body.append(
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width - margin["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="3 5"/>'
        )
        body.append(
            f'<text x="{margin["left"] - 8}" y="{y + 4:.1f}" font-size="10" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{value:+.2f}</text>'
        )
    zero_y = py(0.0)
    body.append(
        f'<line x1="{margin["left"]}" y1="{zero_y:.1f}" x2="{width - margin["right"]}" '
        f'y2="{zero_y:.1f}" stroke="{COLOR_AXIS}"/>'
    )
    for i, item in enumerate(structures):
        if item.get("free_energy") is None:
            continue
        rel = float(item["free_energy"]) - ref
        y = py(rel)
        x1, x2 = px(2 * i), px(2 * i + 1)
        warn = not item.get("converged", False) or not item.get("corrected", False)
        color = COLOR_WARN if warn else COLOR_SECONDARY
        body.append(
            f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{color}" '
            f'stroke-width="3" stroke-linecap="round"/>'
        )
        body.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{y - 7:.1f}" font-size="10" fill="{color}" '
            f'text-anchor="middle" {FONT}>{rel:+.3f}</text>'
        )
        body.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{height - 20}" font-size="10" fill="{COLOR_TEXT}" '
            f'text-anchor="middle" {FONT}>结构 {_escape(item.get("structure_label", i + 1))}</text>'
        )
        if i < n - 1 and structures[i + 1].get("free_energy") is not None:
            nx = px(2 * i + 2)
            ny = py(float(structures[i + 1]["free_energy"]) - ref)
            body.append(
                f'<line x1="{x2:.1f}" y1="{y:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
                f'stroke="{COLOR_MUTED}" stroke-dasharray="4 4"/>'
            )
    body.append(
        f'<text x="{width / 2}" y="{height - 4}" font-size="10" fill="{COLOR_MUTED}" '
        f'text-anchor="middle" {FONT}>相对自由能 ΔE (eV，参考：结构 '
        f'{_escape(valid[0].get("structure_label", 1))}）</text>'
    )
    return _svg(width, height, "".join(body), title)


def neb_barrier_chart(
    images: Sequence[Dict[str, Any]],
    *,
    title: str = "NEB 能垒曲线",
    width: int = 760,
    height: int = 280,
) -> str:
    """NEB 相对能垒曲线（直线连接各映像，不做插值）。"""
    margin = {"left": 74, "right": 24, "top": 34, "bottom": 46}
    pts = [
        (i, float(img["relative"]))
        for i, img in enumerate(images)
        if img.get("relative") is not None
    ]
    body: List[str] = [
        f'<text x="{margin["left"]}" y="20" font-size="13" fill="#374151" {FONT}>{_escape(title)}</text>'
    ]
    if not pts:
        body.append(
            f'<text x="{width / 2}" y="{height / 2}" font-size="12" fill="{COLOR_MUTED}" '
            f'text-anchor="middle" {FONT}>暂无 NEB 映像能量数据</text>'
        )
        return _svg(width, height, "".join(body), title)

    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    ys = [p[1] for p in pts]
    y_max = max(max(ys), 0.0) + 0.2
    y_min = min(min(ys), 0.0) - 0.2
    saddle_idx = max(range(len(ys)), key=lambda i: ys[i])

    def px(i: int) -> float:
        return margin["left"] + (i / max(len(images) - 1, 1)) * plot_w

    def py(y: float) -> float:
        return margin["top"] + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    for value in _nice_ticks(y_min, y_max):
        y = py(value)
        body.append(
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width - margin["right"]}" y2="{y:.1f}" '
            f'stroke="{COLOR_GRID}" stroke-dasharray="3 5"/>'
        )
        body.append(
            f'<text x="{margin["left"] - 8}" y="{y + 4:.1f}" font-size="10" fill="{COLOR_MUTED}" '
            f'text-anchor="end" {FONT}>{value:+.2f}</text>'
        )
    path = " ".join(
        f'{"M" if k == 0 else "L"}{px(i):.1f},{py(y):.1f}' for k, (i, y) in enumerate(pts)
    )
    body.append(f'<path d="{path}" fill="none" stroke="{COLOR_PRIMARY}" stroke-width="2.4"/>')
    for i, y in pts:
        is_saddle = i == saddle_idx
        body.append(
            f'<circle cx="{px(i):.1f}" cy="{py(y):.1f}" r="{5 if is_saddle else 3.5}" fill="#fff" '
            f'stroke="{COLOR_DANGER if is_saddle else COLOR_PRIMARY}" stroke-width="2.4"/>'
        )
        label = images[i].get("label", i)
        body.append(
            f'<text x="{px(i):.1f}" y="{height - 20}" font-size="10" fill="{COLOR_TEXT}" '
            f'text-anchor="middle" {FONT}>{_escape(label)}</text>'
        )
    ea = ys[saddle_idx]
    body.append(
        f'<text x="{px(pts[saddle_idx][0]):.1f}" y="{py(ea) - 10:.1f}" font-size="11" '
        f'fill="{COLOR_DANGER}" text-anchor="middle" {FONT}>Ea = {ea:+.3f} eV</text>'
    )
    body.append(
        f'<text x="{width / 2}" y="{height - 4}" font-size="10" fill="{COLOR_MUTED}" '
        f'text-anchor="middle" {FONT}>NEB 映像（相对初态，eV）</text>'
    )
    return _svg(width, height, "".join(body), title)


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
