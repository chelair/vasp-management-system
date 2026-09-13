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


# ------------------------------------------------------------ 结构三视图


def _parse_cif_atoms(cif_text: str) -> Optional[Dict[str, Any]]:
    """从 CIF 提取晶胞与原子坐标（与前端 structure3d.ts 同口径，纯 Python）。

    返回 {"lattice": [[...]], "atoms": [(element, x, y, z)]}，解析失败返回 None。
    """
    import math
    import re

    if not cif_text:
        return None
    lines = cif_text.splitlines()

    def number(key: str) -> Optional[float]:
        for line in lines:
            m = re.match(rf"^{key}\s+([\d.]+)", line.strip())
            if m:
                return float(m.group(1))
        return None

    a, b, c = number("_cell_length_a"), number("_cell_length_b"), number("_cell_length_c")
    if not (a and b and c):
        return None
    alpha = number("_cell_angle_alpha") or 90.0
    beta = number("_cell_angle_beta") or 90.0
    gamma = number("_cell_angle_gamma") or 90.0
    rad = math.pi / 180
    ca, cb, cg = math.cos(alpha * rad), math.cos(beta * rad), math.cos(gamma * rad)
    sg = math.sin(gamma * rad) or 1e-9
    cx = c * cb
    cy = c * (ca - cb * cg) / sg
    cz = math.sqrt(max(0.0, c * c - cx * cx - cy * cy))
    lattice = [[a, 0.0, 0.0], [b * cg, b * sg, 0.0], [cx, cy, cz]]

    cols: Dict[str, int] = {}
    start = -1
    for i, line in enumerate(lines):
        if line.strip() != "loop_":
            continue
        names: List[str] = []
        j = i + 1
        while j < len(lines) and lines[j].strip().startswith("_"):
            names.append(lines[j].strip())
            j += 1
        if "_atom_site_fract_x" in names:
            cols = {name: k for k, name in enumerate(names)}
            start = j
            break
    if start < 0:
        return None
    atoms: List[tuple] = []
    for line in lines[start:]:
        if not line.strip():
            break
        parts = line.split()
        try:
            fx = float(parts[cols["_atom_site_fract_x"]])
            fy = float(parts[cols["_atom_site_fract_y"]])
            fz = float(parts[cols["_atom_site_fract_z"]])
        except (KeyError, IndexError, ValueError):
            break
        element = parts[cols.get("_atom_site_type_symbol", 0)].strip()
        x = lattice[0][0] * fx + lattice[1][0] * fy + lattice[2][0] * fz
        y = lattice[0][1] * fx + lattice[1][1] * fy + lattice[2][1] * fz
        z = lattice[0][2] * fx + lattice[1][2] * fy + lattice[2][2] * fz
        atoms.append((element, x, y, z))
    if not atoms:
        return None
    return {"lattice": lattice, "atoms": atoms}


_ELEMENT_COLORS = {
    "H": "#ffffff",
    "C": "#909090",
    "N": "#3050f8",
    "O": "#ff0d0d",
    "S": "#ffff30",
    "P": "#ff8000",
    "Al": "#bfa6a6",
    "Ti": "#bfc2c7",
    "Fe": "#e06633",
    "Co": "#a0a0ff",
    "Ni": "#50d050",
    "Cu": "#c88033",
    "Zn": "#7d80b0",
    "Ag": "#c0c0c0",
    "Au": "#ffd123",
    "Pt": "#d0d0e0",
    "Pd": "#006985",
    "Li": "#cc80ff",
    "Na": "#ab5cf2",
}


def structure_views(
    cif_text: str,
    *,
    views: Sequence[str] = ("ab", "bc", "ac"),
    panel: int = 150,
    title: str = "",
    labels: Optional[Sequence[str]] = None,
) -> str:
    """结构三视图（a-b / b-c / a-c 正交投影），元素着色 + 晶胞边框。

    纯 Python 正交投影 SVG：前端展示与导出 HTML/PDF 用的是同一张图（v0.7.2 起报告页不再有交互式 3D）。
    后端没有 3Dmol（浏览器端 JS 库），需要真实静态 3D 渲染得引入 headless 浏览器。
    """
    parsed = _parse_cif_atoms(cif_text)
    labels = list(labels or views)
    if parsed is None:
        return _svg(
            panel * len(views),
            panel + 18,
            f'<text x="8" y="{panel / 2}" font-size="11" fill="{COLOR_MUTED}" {FONT}>'
            f"结构文件缺失或无法解析</text>",
            title or "结构视图",
        )
    width = panel * len(views)
    height = panel + 18
    body: List[str] = []
    axis = {"ab": (0, 1), "bc": (1, 2), "ac": (0, 2)}
    lattice = parsed["lattice"]
    corners = [
        [
            sa * lattice[0][k] + sb * lattice[1][k] + sc * lattice[2][k]
            for k in range(3)
        ]
        for sa in (0, 1)
        for sb in (0, 1)
        for sc in (0, 1)
    ]
    for index, view in enumerate(views):
        i, j = axis.get(view, (0, 1))
        ox = index * panel
        pts = [(atom[i + 1], atom[j + 1], atom[0]) for atom in parsed["atoms"]]
        pts.extend((corner[i], corner[j], "cell") for corner in corners)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        span_x = max(xs) - min(xs) or 1.0
        span_y = max(ys) - min(ys) or 1.0
        scale = (panel - 26) / max(span_x, span_y)

        def sx(x: float) -> float:
            return ox + 13 + (x - min(xs)) * scale

        def sy(y: float) -> float:
            return 13 + (max(ys) - y) * scale

        # 晶胞投影外框（8 个角点的投影包围盒）
        cell_x = [sx(c[i]) for c in corners]
        cell_y = [sy(c[j]) for c in corners]
        body.append(
            f'<rect x="{min(cell_x):.1f}" y="{min(cell_y):.1f}" '
            f'width="{max(cell_x) - min(cell_x):.1f}" height="{max(cell_y) - min(cell_y):.1f}" '
            f'fill="none" stroke="{COLOR_AXIS}" stroke-dasharray="4 3"/>'
        )
        radius = max(2.6, min(4.4, scale * 1.1))
        for atom in parsed["atoms"]:
            element = atom[0]
            color = _ELEMENT_COLORS.get(element, "#9aa7b8")
            body.append(
                f'<circle cx="{sx(atom[i + 1]):.1f}" cy="{sy(atom[j + 1]):.1f}" r="{radius:.1f}" '
                f'fill="{color}" stroke="#5A6A80" stroke-width="0.6" opacity="0.92"/>'
            )
        body.append(
            f'<text x="{ox + panel / 2:.1f}" y="{height - 4}" font-size="10.5" '
            f'fill="{COLOR_TEXT}" text-anchor="middle" {FONT}>{_escape(labels[index])}</text>'
        )
        body.append(
            f'<line x1="{ox}" y1="0" x2="{ox}" y2="{height}" stroke="{COLOR_GRID}"/>'
        )
    return _svg(width, height, "".join(body), title or "结构三视图")


def structure_matrix(
    items: Sequence[Dict[str, Any]],
    *,
    views: Sequence[str] = ("ab", "bc", "ac"),
    panel: int = 120,
    title: str = "NEB 映像结构对比",
) -> str:
    """NEB 结构对比矩阵：行 = 视图（a-b / b-c / a-c），列 = 映像（IS → FS）。"""
    columns = [i for i in items if i.get("cif")]
    if not columns:
        return structure_views("", views=views, panel=panel, title=title)
    width = panel * len(columns)
    height = panel * len(views) + 20
    body: List[str] = []
    axis = {"ab": (0, 1), "bc": (1, 2), "ac": (0, 2)}
    for col, item in enumerate(columns):
        parsed = _parse_cif_atoms(item["cif"])
        for row, view in enumerate(views):
            ox, oy = col * panel, row * panel
            if parsed is None:
                body.append(
                    f'<text x="{ox + panel / 2}" y="{oy + panel / 2}" font-size="10" '
                    f'fill="{COLOR_MUTED}" text-anchor="middle" {FONT}>无结构</text>'
                )
                continue
            i, j = axis.get(view, (0, 1))
            pts = [(a[i + 1], a[j + 1]) for a in parsed["atoms"]]
            xs = [p[0] for p in pts] or [0.0]
            ys = [p[1] for p in pts] or [0.0]
            span_x = max(xs) - min(xs) or 1.0
            span_y = max(ys) - min(ys) or 1.0
            scale = (panel - 22) / max(span_x, span_y)
            for atom in parsed["atoms"]:
                color = _ELEMENT_COLORS.get(atom[0], "#9aa7b8")
                cx = ox + 11 + (atom[i + 1] - min(xs)) * scale
                cy = oy + 11 + (max(ys) - atom[j + 1]) * scale
                body.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(2.0, min(3.4, scale)):.1f}" '
                    f'fill="{color}" stroke="#5A6A80" stroke-width="0.5" opacity="0.92"/>'
                )
            body.append(
                f'<rect x="{ox}" y="{oy}" width="{panel}" height="{panel}" fill="none" '
                f'stroke="{COLOR_GRID}"/>'
            )
        body.append(
            f'<text x="{col * panel + panel / 2:.1f}" y="{height - 6}" font-size="10" '
            f'fill="{COLOR_TEXT}" text-anchor="middle" {FONT}>'
            f"{_escape(str(item.get('label', col)))}</text>"
        )
    for row, view in enumerate(views):
        body.append(
            f'<text x="4" y="{row * panel + 12}" font-size="9.5" fill="{COLOR_MUTED}" {FONT}>'
            f"{_escape(view)}</text>"
        )
    return _svg(width, height, "".join(body), title)


def progress_bar_percent(
    percent: float, *, title: str = "项目进度", detail: str = "", width: int = 420
) -> str:
    """项目进度条（基本信息模块用，静态 SVG）。"""
    return progress_bar(percent, title=title, detail=detail, warn_at=101.0, width=width, height=104)


def _inner(svg: str) -> str:
    """取出 <svg ...> 内部内容（用于把多张图拼成一张）。"""
    start = svg.find(">", svg.find("<svg"))
    end = svg.rfind("</svg>")
    return svg[start + 1 : end] if start >= 0 and end > start else ""


def _size(svg: str) -> Tuple[int, int]:
    import re

    w = re.search(r'width="(\d+)"', svg)
    h = re.search(r'height="(\d+)"', svg)
    return (int(w.group(1)) if w else 400, int(h.group(1)) if h else 200)


def task_panel(views_svg: str, curve_svg: str, *, gap: int = 22, padding: int = 4) -> str:
    """结构优化任务面板：**左侧结构三视图 + 右侧能量/力曲线横向排列**（一张图内对齐）。

    拼成单张 SVG 的好处：Markdown、前端与导出的 HTML/PDF 完全一致（所见即所得），
    且两栏在同一基线上对齐。
    """
    vw, vh = _size(views_svg)
    cw, ch = _size(curve_svg)
    width = padding * 2 + vw + gap + cw
    height = padding * 2 + max(vh, ch)
    body = (
        f'<g transform="translate({padding},{padding})">{_inner(views_svg)}</g>'
        f'<g transform="translate({padding + vw + gap},{padding})">{_inner(curve_svg)}</g>'
    )
    return _svg(width, height, body, "结构优化任务面板")
