"""报告导出：把结构化报告渲染成自包含 HTML（供下载 / 浏览器打印成 PDF）。

要点：
- **可选范围**：按 `sections` 只导出指定章节（如取消勾选风险分析）；
- **自包含**：图表以**内联 SVG** 写入，CSS 内联，单文件即可离线打开；
- **打印友好**：A4 页边距、表格/图表不跨页断开，供「打印为 PDF」直接使用；
- Markdown → HTML 使用内置轻量转换器（只覆盖本项目生成的语法子集），
  保证 HTML 与 Markdown 内容完全一致，不引入第三方依赖。
"""

import html as html_lib
import json
import re
from typing import Any, Callable, Dict, List, Optional

from report_schema import REPORT_SECTIONS

SECTION_TITLES = dict(REPORT_SECTIONS)

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 40px 48px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", Helvetica, Arial, sans-serif;
  color: #233043; background: #fff; line-height: 1.7; font-size: 14px;
}
h1 { font-size: 24px; margin: 0 0 6px; }
h2 {
  font-size: 17px; margin: 26px 0 10px; padding: 0 0 6px 11px; position: relative;
  border-bottom: 2px solid #EEF3FA; page-break-after: avoid;
}
h2::before {
  content: ''; position: absolute; left: 0; top: 3px;
  width: 4px; height: 16px; border-radius: 3px; background: #3F6FE0;
}
h3, h4 { font-size: 14px; margin: 20px 0 6px; color: #233043; page-break-after: avoid; }
/* 任务标题（#### → h5）：左侧竖条，把每个任务切成一块 */
h5 {
  font-size: 15px; margin: 26px 0 4px; padding-left: 10px; line-height: 1.4;
  border-left: 3px solid #5B8DEF; color: #233043; page-break-after: avoid;
}
h5 + p { margin: 0 0 10px; padding-left: 13px; font-size: 12.5px; color: #8A98AC; }
.report-meta { color: #8A98AC; font-size: 12px; margin-bottom: 18px; }
table {
  border-collapse: collapse; width: 100%; margin: 8px 0 14px;
  font-size: 12.5px; page-break-inside: avoid;
}
th, td { border: 1px solid #E3E9F2; padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: #F4F7FB; font-weight: 600; }
th:not(:first-child):not(:last-child), td:not(:first-child):not(:last-child) {
  text-align: right; font-variant-numeric: tabular-nums;
}
tbody tr:nth-child(even) td, tr:nth-child(even) td { background: #FBFCFE; }
td:first-child { color: #3F68B8; font-weight: 500; }
code {
  background: #F4F7FB; border-radius: 4px; padding: 1px 5px;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: 12px;
}
ul { margin: 6px 0 14px; padding-left: 20px; }
li { margin: 3px 0; }
figure { margin: 8px 0 4px; page-break-inside: avoid; text-align: center; }
figure svg { max-width: 100%; height: auto; }
figcaption { font-size: 11.5px; color: #8A98AC; margin-top: 4px; }
hr { border: none; border-top: 1px dashed #DCE3EC; margin: 22px 0 0; }
img { max-width: 100%; }
a { color: #3F68B8; text-decoration: none; }
.footer { margin-top: 28px; padding-top: 10px; border-top: 1px dashed #E3E9F2;
  color: #8A98AC; font-size: 11.5px; }

/* ---------------- 电子结构挂点（Bader 完整表 / PDOS · 功函数交互组件） ---------------- */
.bader-table {
  border: 1px solid #E9EEF6; border-radius: 10px; padding: 12px 14px 14px; margin: 8px 0 16px;
  background: #fff;
}
.bader-table__head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.bader-table__title { font-size: 13px; font-weight: 600; color: #374151; }
.bader-table__meta { font-size: 11.5px; color: #8A98AC; }
/* 可滑动容器：整张表在容器内滚动，表头固定；窄屏横向可滑动 */
.bader-table__scroll { max-height: 420px; overflow: auto; border: 1px solid #F0F3F8; border-radius: 8px; }
.bader-table__scroll table { margin: 0; font-size: 12px; }
.bader-table__scroll thead th { position: sticky; top: 0; z-index: 1; }
.report-widget { margin: 10px 0 16px; }
/* 结构 3D 视图（v0.9.72）：正文里取代三视图 PNG，PNG 转"仅打印" */
.report-widget--3d { margin: 10px 0 14px; }
/* Bader：3D 结构视图 + 完整表 左右一行（窄屏自动上下） */
.report-bader-row { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; margin: 8px 0 16px; }
.report-bader-row__view { flex: 1 1 420px; min-width: 320px; }
.report-bader-row__table { flex: 1 1 380px; min-width: 300px; }
.report-bader-row__table .bader-table { margin: 0; }

.report-widget__loading, .report-widget__error {
  border: 1px dashed #DCE3EC; border-radius: 8px; padding: 12px 14px;
  color: #8A98AC; font-size: 12.5px; text-align: center;
}
.report-widget__error { color: #C0392B; border-color: #F0C4C0; }
.report-widget button { font: inherit; }
@page { size: A4; margin: 14mm; }
@media print {
  body { padding: 0; font-size: 12px; }
  h2 { page-break-before: auto; }
  .no-print { display: none !important; }
  /* 打印 / PDF 走**静态图**兜底（用户口径 2026-10-15：HTML 只给可交互的，静态图留给 PDF）：
     屏幕上的交互组件（ECharts canvas）不打印，被运行时收起来的静态图在打印时恢复显示。
     这样 PDF 不会既出现交互图又出现静态图。 */
  .report-widget { display: none !important; }
  .report-static-taken-over { display: block !important; }
  /* 3D 视图不打印（canvas 打印不可靠），用三视图 PNG 兜底 */
  .report-widget--3d,
  .report-bader-row__view { display: none !important; }
  .img-row { page-break-inside: avoid; }
}

/* ---------------- 结构三视图（VESTA PNG，横向紧凑、等宽等高） ---------------- */
.img-row {
  display: flex; gap: 8px; align-items: stretch; justify-content: center;
  margin: 10px 0 14px; page-break-inside: avoid;
}
.img-row figure { flex: 1 1 0; min-width: 0; margin: 0; }
.img-row img { width: 100%; height: auto; display: block; border-radius: 6px; }
.img-row figcaption { font-size: 11px; }
.row-label { margin: 14px 0 2px; font-size: 12.5px; color: #5A6B85; font-weight: 600; }

/* ---------------- 可点击标签（点开结构三视图弹窗） ---------------- */
button.chip {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: 28px; padding: 2px 10px; border: 1px solid #CFE0FF; border-radius: 999px;
  background: #F2F7FF; color: #2D5FCC; font: inherit; font-size: 12px; font-weight: 500;
  cursor: pointer; touch-action: manipulation; -webkit-tap-highlight-color: transparent;
}
button.chip:hover { background: #E7F0FF; }
button.chip:active { background: #DCE9FF; }

/* ---------------- 弹窗（原生 <dialog>） ---------------- */
dialog.viewer {
  width: min(1100px, 92vw); max-height: 90vh; padding: 0; border: none; border-radius: 14px;
  box-shadow: 0 24px 60px rgba(20, 40, 80, .28); color: #233043;
}
dialog.viewer::backdrop { background: rgba(16, 26, 44, .55); }
dialog.viewer header {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 14px; border-bottom: 1px solid #E7EDF6;
}
dialog.viewer h3 { margin: 0; font-size: 15px; }
dialog.viewer .close {
  min-width: 44px; min-height: 44px; border: none; background: transparent; color: #7A89A0;
  font-size: 24px; line-height: 1; cursor: pointer; border-radius: 8px;
}
dialog.viewer .close:hover { background: #F2F5FA; }
dialog.viewer .body { padding: 10px 14px 16px; overflow: auto; max-height: calc(90vh - 62px); }

/* ---------------- 手机（≤720px）：表格变卡片、三视图竖排、弹窗全屏 ---------------- */
@media (max-width: 720px) {
  body { padding: 16px 13px 28px; font-size: 13.5px; }
  h1 { font-size: 20px; }
  table, thead, tbody, tr, th, td { display: block; width: 100%; }
  thead { display: none; }
  table { border: none; }
  tbody tr {
    border: 1px solid #E3E9F2; border-radius: 10px; margin: 8px 0; padding: 4px 0;
    background: #fff;
  }
  tbody tr:nth-child(even) td { background: transparent; }
  td {
    border: none; display: flex; align-items: baseline; justify-content: space-between;
    gap: 12px; padding: 5px 12px; text-align: right;
  }
  td::before {
    content: attr(data-label); color: #8A98AC; font-weight: 500; text-align: left;
    flex: 0 0 auto;
  }
  td:first-child { color: #233043; font-weight: 600; }
  .img-row { flex-direction: column; gap: 10px; }
  button.chip { min-height: 44px; padding: 6px 14px; }
  dialog.viewer {
    width: 100vw; height: 100vh; max-width: none; max-height: none; border-radius: 0; margin: 0;
  }
  dialog.viewer .body { max-height: calc(100vh - 60px); }
}
/* ---- 图片查看器：点任意结构图/图表看原图，可缩放（2026-10-13，桌面 + 手机） ---- */
figure img { cursor: zoom-in; }
.img-lightbox {
  position: fixed; inset: 0; z-index: 2000; display: none;
  background: rgba(15, 23, 42, 0.94); color: #e2e8f0;
}
.img-lightbox[data-open="1"] { display: flex; flex-direction: column; }
.img-lightbox__bar {
  display: flex; align-items: center; gap: 10px; padding: 6px 12px;
  min-height: 48px; border-bottom: 1px solid #1e293b;
}
.img-lightbox__caption {
  font-size: 13px; color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.img-lightbox__tools { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.img-lightbox__tools button {
  min-width: 38px; min-height: 34px; border-radius: 8px; border: 1px solid #334155;
  background: #1e293b; color: #e2e8f0; font-size: 14px; cursor: pointer; touch-action: manipulation;
}
.img-lightbox__tools button:active { background: #263449; }
.img-lightbox__percent { min-width: 48px; text-align: center; font-size: 12px; color: #94a3b8; }
.img-lightbox__stage {
  position: relative; flex: 1; display: flex; align-items: center; justify-content: center;
  overflow: hidden; touch-action: none; cursor: grab;
}
.img-lightbox__stage:active { cursor: grabbing; }
.img-lightbox__stage img {
  max-width: 100%; max-height: 100%; transform-origin: center center;
  user-select: none; -webkit-user-drag: none; will-change: transform;
}
.img-lightbox__tip { padding: 6px 12px 10px; text-align: center; font-size: 12px; color: #64748b; }
@media (max-width: 720px) {
  .img-lightbox__tip { display: none; }
  .img-lightbox__tools button { min-width: 44px; min-height: 40px; }
}
"""


def _inline(text: str) -> str:
    """行内语法：**加粗**、`代码`、_斜体_、[文字](链接)。

    `[结构 1](#dlg_xxx)` 这种"指向弹窗"的链接会渲染成可点击的 chip（原生 <dialog> 打开），
    Markdown 本身还是普通链接，`.md` 读起来不受影响。
    """
    out = html_lib.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])", r"<em>\1</em>", out)

    def link(m: "re.Match[str]") -> str:
        label, href = m.group(1), m.group(2)
        if href.startswith("#dlg_"):
            return (
                f'<button type="button" class="chip" data-dialog="{html_lib.escape(href[1:])}">'
                f"{label}</button>"
            )
        safe = href if not href.lower().startswith(("javascript:", "data:")) else "#"
        return f'<a href="{safe}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, out)


def markdown_to_html(
    markdown: str,
    *,
    chart_loader: Optional[Callable[[str], Optional[str]]] = None,
    image_loader: Optional[Callable[[str], Optional[str]]] = None,
    inline_charts: bool = True,
    widget_renderer: Optional[Callable[[str, str], Optional[str]]] = None,
) -> str:
    """把报告 Markdown 子集转为 HTML（表格 / 列表 / 图片 / 加粗 / 代码）。

    - `charts/xxx.svg` → 内联 SVG（原行为）；
    - `images/xxx.png` → `image_loader` 给的 base64 data URI（结构三视图，**拿不到就整块跳过**）；
    - 连续的图片行（a/b/c 三视图）合并成一行 `.img-row`，等宽紧凑。

    **挂点行**（2026-10-15，电子结构接报告）：`@[kind:task_id]` 交给 `widget_renderer` ——
    Bader 完整表渲染成原生 `<details>`（折叠报表）；PDOS / 功函数的交互组件渲染成宿主
    `<div>`，由注入的 ECharts 运行时接管（拿不到运行时就看前面的静态 SVG 兜底）。
    """
    lines = (markdown or "").split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 挂点行：@[bader-table:xxx] / @[pdos-chart:xxx] / @[work-function-chart:xxx]
        hook = re.fullmatch(r"@\[([a-z0-9-]+):([^\]\s]+)\]", stripped)
        if hook and widget_renderer is not None:
            rendered = widget_renderer(hook.group(1), hook.group(2))
            if rendered:
                out.append(rendered)
            i += 1
            continue

        # 表格：连续的以 | 开头的行
        if stripped.startswith("|"):
            block: List[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            cells = [
                [c.strip() for c in row.strip("|").split("|")]
                for row in block
                if not re.fullmatch(r"\|[\s\-:|]+\|", row)
            ]
            if cells:
                head, *body = cells
                out.append("<table><thead><tr>")
                out.extend(f"<th>{_inline(c)}</th>" for c in head)
                out.append("</tr></thead><tbody>")
                for row in body:
                    out.append("<tr>")
                    for idx, cell in enumerate(row):
                        label = head[idx] if idx < len(head) else ""
                        out.append(
                            f'<td data-label="{html_lib.escape(label, quote=True)}">'
                            f"{_inline(cell)}</td>"
                        )
                    out.append("</tr>")
                out.append("</tbody></table>")
            continue

        # 列表
        if re.match(r"^[-*]\s+", stripped):
            out.append("<ul>")
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                item = re.sub(r"^[-*]\s+", "", lines[i].strip())
                # 列表项后续的缩进行合并进来
                i += 1
                while i < len(lines) and lines[i].startswith(("  ", "\t")) and lines[i].strip():
                    item += " " + lines[i].strip()
                    i += 1
                out.append(f"<li>{_inline(item)}</li>")
            out.append("</ul>")
            continue

        # 图片（连续多张合并成一行）
        if re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped):
            figures: List[str] = []
            while i < len(lines):
                mm = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", lines[i].strip())
                if not mm:
                    break
                alt, src = mm.group(1), mm.group(2)
                svg = None
                data_uri = None
                if inline_charts and chart_loader is not None and src.startswith("charts/"):
                    svg = chart_loader(src.split("/", 1)[1])
                elif image_loader is not None and src.startswith("images/"):
                    data_uri = image_loader(src)
                if svg:
                    figures.append(f"<figure>{svg}<figcaption>{_inline(alt)}</figcaption></figure>")
                elif data_uri:
                    figures.append(
                        f'<figure><img src="{data_uri}" alt="{html_lib.escape(alt)}"/>'
                        f"<figcaption>{_inline(alt)}</figcaption></figure>"
                    )
                elif src.startswith("images/"):
                    pass  # 结构图缺失：跳过（用户口径：没有就跳过）
                else:
                    figures.append(
                        f'<figure><img src="{html_lib.escape(src)}" alt="{html_lib.escape(alt)}"/>'
                        f"<figcaption>{_inline(alt)}</figcaption></figure>"
                    )
                i += 1
            if len(figures) > 1:
                out.append('<div class="img-row">' + "".join(figures) + "</div>")
            else:
                out.extend(figures)
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = min(len(m.group(1)) + 1, 6)  # 文档内章节从 h2 起
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if re.fullmatch(r"-{3,}", stripped):
            out.append("<hr/>")
            i += 1
            continue

        # 段落（合并连续行）
        paragraph = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^([-*]\s|\||!\[|#{1,6}\s|-{3,}$)", lines[i].strip()
        ):
            paragraph.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------- 电子结构挂点

#: 单张 Bader 完整表最多渲染多少行（正常算例 100~300 个原子；异常大算例给个上限）
BADER_TABLE_MAX_ROWS = 2000


def _ele_tasks_by_id(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    tasks = ((doc.get("science") or {}).get("ele") or {}).get("tasks") or []
    return {str(item.get("task_id")): item for item in tasks}


def _bader_table_html(item: Dict[str, Any]) -> Optional[str]:
    """Bader 完整表（**直接展示 + 可滑动容器**）。

    用户口径（2026-10-15）："Bader 直接展示完整表格，但是放在一个容器中可滑动查看" ——
    所以不再用 `<details>` 折叠，改成"标题 + 固定高度的滚动容器（表头 sticky）+ 全部行"，
    页面版（`components/reports/ReportScienceWidgets.tsx::BaderFullTable`）同口径。
    """
    summary = item.get("bader_summary") or {}
    atoms = summary.get("atoms") or []
    if not atoms:
        return None
    rows = atoms[:BADER_TABLE_MAX_ROWS]
    head = (
        "<table><thead><tr>"
        "<th>原子</th><th>元素</th><th>Bader 电荷 (e)</th>"
        "<th>ZVAL (e)</th><th>净电荷 Δq (e)</th></tr></thead><tbody>"
    )
    body = []
    for atom in rows:
        label = f"{atom.get('element') or ''}{atom.get('index')}"
        net = atom.get("net_charge")
        charge = atom.get("charge")
        zval = atom.get("zval")
        charge_text = "—" if charge is None else f"{float(charge):.4f}"
        zval_text = "—" if zval is None else f"{float(zval):.2f}"
        net_text = "—" if net is None else f"{float(net):+.4f}"
        body.append(
            "<tr>"
            f"<td>{html_lib.escape(label)}</td>"
            f"<td>{html_lib.escape(str(atom.get('element') or '—'))}</td>"
            f"<td>{charge_text}</td><td>{zval_text}</td><td>{net_text}</td>"
            "</tr>"
        )
    meta = (
        f"共 {len(atoms)} 个原子"
        + (f"，表中只列前 {len(rows)} 个" if len(atoms) > len(rows) else "")
        + "（按原子序号排列）"
    )
    return (
        '<div class="bader-table">'
        '<div class="bader-table__head"><span class="bader-table__title">逐原子 Bader 电荷（完整表）</span>'
        f'<span class="bader-table__meta">{html_lib.escape(meta)}</span></div>'
        '<div class="bader-table__scroll">'
        + head
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def widget_renderer_for(doc: Dict[str, Any]) -> Callable[[str, str], Optional[str]]:
    """把 Markdown 里的挂点行渲染成 HTML。

    - `structure-3d` → 结构 3D 视图宿主（v0.9.72，正文里直接挂，不在弹窗里）；
    - `bader-table` → **3D 结构视图 + 完整表**左右一行（表服务端直出，3D 由运行时挂）；
    - `pdos-chart` / `work-function-chart` → 只给宿主 `<div>`，由注入的 ECharts 运行时接管；
      运行时不可用（老浏览器 / 关闭 JS / 打印）时，前面的静态 SVG / 三视图 PNG 就是它的兜底。
    """
    by_id = _ele_tasks_by_id(doc)

    def render(kind: str, task_id: str) -> Optional[str]:
        item = by_id.get(str(task_id)) or {}
        if kind in ("pdos-chart", "work-function-chart"):
            return (
                f'<div class="report-widget" data-report-widget="{html_lib.escape(kind)}" '
                f'data-task-id="{html_lib.escape(str(task_id))}"></div>'
            )
        if kind == "structure-3d":
            # 结构 3D 视图（v0.9.72）：正文里**直接**挂；后面那几行三视图 PNG 由运行时
            # 标成"仅打印"（屏幕看 3D、打印/PDF 用 PNG）
            return (
                f'<div class="report-widget report-widget--3d" '
                f'data-report-widget="structure-3d" data-task-id="{html_lib.escape(str(task_id))}"></div>'
            )
        if kind == "bader-table":
            # Bader：3D 结构视图 + 完整表 左右一行
            table = _bader_table_html(item)
            if not table:
                return None
            return (
                '<div class="report-bader-row">'
                f'<div class="report-bader-row__view">'
                f'<div class="report-widget report-widget--3d" data-report-widget="structure-3d" '
                f'data-task-id="{html_lib.escape(str(task_id))}" data-source="bader"></div>'
                f"</div>"
                f'<div class="report-bader-row__table">{table}</div>'
                "</div>"
            )
        return None

    return render


VIEWER_SCRIPT = """
(function () {
  var lastOpen = 0;
  /* ---------------- 图片查看器：点报告里任意一张图 → 看原图（可缩放/平移，桌面+手机） ---------------- */
  var box = null, stage = null, imgEl = null, capEl = null, pctEl = null, tipEl = null;
  var scale = 1, offX = 0, offY = 0;
  var pointers = {}, pinch = null, drag = null;
  var MIN = 0.2, MAX = 10;

  function clamp(v) { return Math.min(MAX, Math.max(MIN, v)); }

  function apply() {
    if (!imgEl) return;
    imgEl.style.transform = 'translate(' + offX + 'px,' + offY + 'px) scale(' + scale + ')';
    if (pctEl) pctEl.textContent = Math.round(scale * 100) + '%';
  }

  function close() {
    if (!box) return;
    box.setAttribute('data-open', '0');
    imgEl.removeAttribute('src');
    pointers = {}; pinch = null; drag = null;
  }

  function open(src, caption) {
    if (!box) build();
    scale = 1; offX = 0; offY = 0;
    imgEl.src = src;
    capEl.textContent = caption || '结构图';
    apply();
    box.setAttribute('data-open', '1');
  }

  function build() {
    box = document.createElement('div');
    box.className = 'img-lightbox';
    box.setAttribute('data-open', '0');
    box.innerHTML =
      '<div class="img-lightbox__bar">' +
        '<span class="img-lightbox__caption"></span>' +
        '<span class="img-lightbox__tools">' +
          '<button type="button" data-zoom="out" title="缩小">−</button>' +
          '<span class="img-lightbox__percent">100%</span>' +
          '<button type="button" data-zoom="in" title="放大">＋</button>' +
          '<button type="button" data-zoom="fit" title="适应窗口">⤢</button>' +
          '<button type="button" data-zoom="one" title="原始大小 100%">1:1</button>' +
          '<button type="button" data-zoom="close" title="关闭">×</button>' +
        '</span>' +
      '</div>' +
      '<div class="img-lightbox__stage"><img alt=""/></div>' +
      '<div class="img-lightbox__tip">滚轮 / 双指捏合缩放 · 拖拽平移 · 双击切换 1:1 · ESC 关闭</div>';
    document.body.appendChild(box);
    stage = box.querySelector('.img-lightbox__stage');
    imgEl = stage.querySelector('img');
    capEl = box.querySelector('.img-lightbox__caption');
    pctEl = box.querySelector('.img-lightbox__percent');

    box.addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-zoom]') : null;
      if (btn) {
        var kind = btn.getAttribute('data-zoom');
        if (kind === 'in') scale = clamp(scale * 1.25);
        else if (kind === 'out') scale = clamp(scale / 1.25);
        else if (kind === 'fit' || kind === 'one') { scale = 1; offX = 0; offY = 0; }
        else if (kind === 'close') { close(); return; }
        apply();
        return;
      }
      if (ev.target === box) close();
    });
    box.addEventListener('wheel', function (ev) {
      if (box.getAttribute('data-open') !== '1') return;
      ev.preventDefault();
      scale = clamp(scale * (ev.deltaY < 0 ? 1.12 : 1 / 1.12));
      apply();
    }, { passive: false });
    box.addEventListener('dblclick', function (ev) {
      if (box.getAttribute('data-open') !== '1') return;
      if (ev.target.closest && ev.target.closest('.img-lightbox__tools')) return;
      scale = scale > 1.2 ? 1 : 2; offX = 0; offY = 0; apply();
    });
    stage.addEventListener('pointerdown', function (ev) {
      stage.setPointerCapture && stage.setPointerCapture(ev.pointerId);
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      var ids = Object.keys(pointers);
      if (ids.length === 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: scale };
        drag = null;
      } else {
        drag = { x: ev.clientX, y: ev.clientY };
      }
    });
    stage.addEventListener('pointermove', function (ev) {
      if (!pointers[ev.pointerId]) return;
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      var ids = Object.keys(pointers);
      if (ids.length >= 2 && pinch) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        scale = clamp(pinch.s * ((Math.hypot(a.x - b.x, a.y - b.y) || 1) / pinch.d));
        apply();
        return;
      }
      if (!drag) return;
      offX += ev.clientX - drag.x; offY += ev.clientY - drag.y;
      drag = { x: ev.clientX, y: ev.clientY };
      apply();
    });
    function up(ev) {
      delete pointers[ev.pointerId];
      stage.releasePointerCapture && stage.releasePointerCapture(ev.pointerId);
      if (Object.keys(pointers).length < 2) pinch = null;
      if (Object.keys(pointers).length === 0) drag = null;
    }
    stage.addEventListener('pointerup', up);
    stage.addEventListener('pointercancel', up);
  }

  function openImage(target) {
    if (!target || !target.closest) return false;
    var img = target.closest('figure img, .img-row img');
    if (img) {
      var fig = img.closest('figure');
      var cap = fig && fig.querySelector('figcaption');
      open(img.getAttribute('src'), (cap && cap.textContent) || img.getAttribute('alt') || '');
      return true;
    }
    // 报告里内联的看板图（原始 <svg>）：现场序列化成 data URI，一样能缩放看清
    var svg = target.closest('svg');
    if (svg && svg.closest('.report-body, body')) {
      try {
        var text = new XMLSerializer().serializeToString(svg);
        open('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(text), '看板图');
        return true;
      } catch (e) { return false; }
    }
    return false;
  }

  function openDialog(target) {
    if (!target || !target.closest) return false;
    var btn = target.closest('[data-dialog]');
    if (!btn) return false;
    var dlg = document.getElementById(btn.getAttribute('data-dialog'));
    if (!dlg || typeof dlg.showModal !== 'function') return false;
    if (!dlg.open) dlg.showModal();
    return true;
  }
  // 触摸：pointerup 立即响应（手机上不用等 click 的 300ms）
  document.addEventListener('pointerup', function (ev) {
    if (ev.pointerType !== 'touch') return;
    if (openImage(ev.target) || openDialog(ev.target)) lastOpen = Date.now();
  });
  document.addEventListener('click', function (ev) {
    if (Date.now() - lastOpen < 600) return;
    if (box && box.getAttribute('data-open') === '1') return;   // 查看器打开时吞掉页面点击
    if (openImage(ev.target)) return;
    if (openDialog(ev.target)) return;
    var closeBtn = ev.target.closest && ev.target.closest('dialog.viewer [data-close]');
    if (closeBtn) { closeBtn.closest('dialog').close(); return; }
    // 点弹窗外的遮罩关闭
    var dlg = ev.target.closest && ev.target.closest('dialog.viewer');
    if (dlg && ev.target === dlg) dlg.close();
  });
  // 原生 <dialog> 自带 Esc 关闭与焦点管理；这里只补键盘可达性
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') {
      if (box && box.getAttribute('data-open') === '1') { close(); return; }
      document.querySelectorAll('dialog.viewer[open]').forEach(function (d) { d.close(); });
    }
  });
})();
"""


def render_dialogs(
    dialogs: List[Dict[str, Any]],
    *,
    image_loader: Optional[Callable[[str], Optional[str]]] = None,
    chart_loader: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """弹窗（原生 `<dialog>`）：两种形态 ——

    - **三视图弹窗**：每行 a/b/c 三视图（base64 内联）；
    - **图表弹窗**（`chart: charts/xxx.svg`，2026-10-15 起的「收敛历史」）：内联那张 SVG，
      报告页里同一张图会被换成可交互 ECharts（见 Report.tsx）。
    """
    parts: List[str] = []
    for dialog in dialogs or []:
        dialog_id = html_lib.escape(str(dialog.get("id") or ""), quote=True)
        if not dialog_id:
            continue
        rows_html: List[str] = []
        # 图表弹窗（收敛历史）：chart 走 chart_loader 内联 SVG
        chart = str(dialog.get("chart") or "")
        if chart and chart_loader is not None:
            svg = chart_loader(chart.split("/", 1)[1]) if chart.startswith("charts/") else None
            if svg:
                if dialog.get("note"):
                    rows_html.append(f'<p class="row-label">{_inline(str(dialog["note"]))}</p>')
                rows_html.append(f"<figure>{svg}</figure>")
        for row in dialog.get("rows") or []:
            views = row.get("views") or {}
            figures: List[str] = []
            for axis in ("a", "b", "c"):
                src = views.get(axis)
                if not src:
                    continue
                data_uri = image_loader(src) if image_loader else None
                if not data_uri:
                    continue  # 缺图就跳过这一张（不挂图）
                figures.append(
                    f'<figure><img src="{data_uri}" alt="{axis} 视图" loading="lazy" '
                    f'decoding="async"/><figcaption>{axis} 视图</figcaption></figure>'
                )
            if not figures:
                continue
            rows_html.append(f'<p class="row-label">{_inline(str(row.get("label") or ""))}</p>')
            rows_html.append('<div class="img-row">' + "".join(figures) + "</div>")
        if not rows_html:
            continue  # 一张图都没有 → 不输出空弹窗
        parts.append(
            f'<dialog class="viewer" id="{dialog_id}">'
            f"<header><h3>{_inline(str(dialog.get('title') or '结构三视图'))}</h3>"
            f'<button type="button" class="close" data-close aria-label="关闭">×</button></header>'
            f'<div class="body">{"".join(rows_html)}</div></dialog>'
        )
    return "".join(parts)


def _notes_body(text: str) -> str:
    """注解正文：支持**加粗**、`代码`、- 列表（与报告 Markdown 同一套轻量语法）。"""
    out: List[str] = []
    bullets: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            bullets.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if bullets:
            out.append("<ul>" + "".join(bullets) + "</ul>")
            bullets = []
        out.append(f"<p>{_inline(line)}</p>")
    if bullets:
        out.append("<ul>" + "".join(bullets) + "</ul>")
    return "".join(out)


def notes_panel(entries: List[Dict[str, Any]], *, title: str = "结果分析与论文参考") -> str:
    """可折叠的注解面板（原生 `<details>`）：结果分析描述 + 论文写作参考。

    `entries` 每项 `{label, analysis_note, paper_note}`；全空则返回空串（不产生空壳）。
    """
    filled = [
        e for e in (entries or [])
        if (e.get("analysis_note") or "").strip() or (e.get("paper_note") or "").strip()
    ]
    if not filled:
        return ""
    blocks: List[str] = []
    for entry in filled:
        label = str(entry.get("label") or "")
        head = f"<h4>{_inline(label)}</h4>" if label else ""
        analysis = (entry.get("analysis_note") or "").strip()
        paper = (entry.get("paper_note") or "").strip()
        blocks.append(
            head
            + (
                f'<p class="notes-label">结果分析描述</p>{_notes_body(analysis)}'
                if analysis
                else ""
            )
            + (
                f'<p class="notes-label">论文写作参考</p>{_notes_body(paper)}' if paper else ""
            )
        )
    return (
        f'<details class="notes-panel"><summary>{html_lib.escape(title)}</summary>'
        f'<div class="notes-body">{"".join(blocks)}</div></details>'
    )


def _inject_task_notes(body_html: str, note_blocks: Dict[str, Any]) -> str:
    """把每个任务块（`<h5>任务名</h5>` 开始、到下一个 h5 之前）的注解插到块尾。

    Markdown 里任务标题统一是 `#### 名称` → 导出后是 `<h5>`；按标签取 `note_blocks`。
    """
    if not note_blocks or "<h5>" not in body_html:
        return body_html
    parts = re.split(r"(?=<h5>)", body_html)
    out: List[str] = []
    for part in parts:
        m = re.match(r"<h5>(.*?)</h5>", part)
        if m:
            label = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            panel = notes_panel(note_blocks.get(label) or [])
            out.append(part + panel)
        else:
            out.append(part)
    return "".join(out)


#: 类型级注解（用户 2026-10-13 口径）：markdown `### 标题` → 导出后 `<h4>`；只在科学结果分析章节内
_TYPE_NOTE_KEYS = {
    "结构优化": "type_opt",
    "自由能路径": "type_free_energy",
    "NEB 过渡态": "type_neb",
    "电子结构": "type_ele",
}


def _inject_type_notes(body_html: str, notes: Dict[str, Any]) -> str:
    """把「类型级」（该类型一条总的）注解插到类型标题正下方（`<h4>` 之后）。

    四个类型都有类型级落点（电子结构是占位区块，只有类型级、没有子项级）；
    空注解不产生空壳（`notes_panel` 会返回空串）。
    """
    if not notes or "<h4>" not in body_html:
        return body_html
    out: List[str] = []
    for part in re.split(r"(?=<h4>)", body_html):
        m = re.match(r"<h4>(.*?)</h4>", part)
        if not m:
            out.append(part)
            continue
        label = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        key = _TYPE_NOTE_KEYS.get(label)
        if not key:
            out.append(part)
            continue
        panel = notes_panel(
            [notes.get(key) or {}], title=f"{label} · 结果分析与论文参考"
        )
        out.append(part[: m.end()] + panel + part[m.end() :])
    return "".join(out)


def _apply_hidden(section_key: str, body_html: str, hidden: set) -> str:
    """按隐藏 key 过滤章节内的元素（与前端 `utils/reportHidden.ts` 同一套 key/粒度）。

    - `type:<章节>:<类型标题>` → 整个类型块（导出 HTML 里是 `<h4>` 块；**兼容旧 key**
      `task:<章节>:<类型标题>`，早期版本把类型块存成了 task）；
    - `task:<章节>:<任务标题>` → **单个任务块**（导出里是 `<h5>` 块：一个结构优化任务 /
      一组 NEB / 一条自由能路径 / 电子结构的一个子块）；
    - `etask:<章节>:<任务名>` → 电子结构里**一个任务的全部子块**（`<任务> · 差分电荷` /
      `· Bader 电荷` / `· 态密度` / `· 功函数` 一起藏）；
    - `figure:<章节>:<序号>` → 单张图（序号 = 章节内 `<figure>` 顺序，与页面一致）。
    """
    if not hidden:
        return body_html

    def _label(chunk: str, tag: str) -> str:
        m = re.match(rf"<{tag}>(.*?)</{tag}>", chunk, flags=re.S)
        if not m:
            return ""
        return html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()

    # 1) 类型块（<h4> 起 → 下一个 h4 前）
    kept: List[str] = []
    for part in re.split(r"(?=<h4>)", body_html):
        label = _label(part, "h4")
        if label and (
            f"type:{section_key}:{label}" in hidden or f"task:{section_key}:{label}" in hidden
        ):
            continue
        kept.append(part)
    body_html = "".join(kept)

    # 2) 任务块（<h5> 起 → 下一个 h5/h4 前）+ 电子结构"整任务"
    kept = []
    for part in re.split(r"(?=<h5>)", body_html):
        label = _label(part, "h5")
        if label:
            if f"task:{section_key}:{label}" in hidden:
                continue
            name = label.split(" · ")[0].strip()
            if name and f"etask:{section_key}:{name}" in hidden:
                continue
        kept.append(part)
    body_html = "".join(kept)

    # 3) 单张图（按章节内 figure 出现顺序编号，与前端一致）
    index = 0
    out: List[str] = []
    for chunk in re.split(r"(<figure>.*?</figure>)", body_html, flags=re.S):
        if chunk.startswith("<figure>"):
            if f"figure:{section_key}:{index}" in hidden:
                index += 1
                continue
            index += 1
        out.append(chunk)
    return "".join(out)


def render_html(
    doc: Dict[str, Any],
    markdown_sections: List[Dict[str, str]],
    *,
    sections: Optional[List[str]] = None,
    chart_loader: Optional[Callable[[str], Optional[str]]] = None,
    image_loader: Optional[Callable[[str], Optional[str]]] = None,
    auto_print: bool = False,
    hidden: Optional[set] = None,
    interactive_js: str = "",
    interactive_data: Optional[Dict[str, Any]] = None,
    mol_js: str = "",
) -> str:
    """生成自包含 HTML（单文件：CSS/JS 内联、SVG 内联、PNG 走 base64）。

    `sections` 为空表示导出全部章节；`image_loader("images/x.png")` 返回 data URI。

    **交互版**（2026-10-15）：`interactive_js` = 前端打包的运行时（含 ECharts），
    `interactive_data` = `{pdos: {...}, work_function: {...}}`；两者都给了才会注入，
    页面加载后由运行时接管 `@[...]` 挂点（静态 SVG 保留作兜底）。
    """
    meta = doc.get("metadata") or {}
    chosen = set(sections) if sections else {s["key"] for s in markdown_sections}
    body_parts: List[str] = []
    hidden = hidden or set()
    for section in markdown_sections:
        if section["key"] not in chosen:
            continue
        if f"section:{section['key']}" in hidden:
            continue  # 章节级隐藏：整章不导出
        title = SECTION_TITLES.get(section["key"], section["title"])
        body_parts.append(f"<h2>{html_lib.escape(title)}</h2>")
        section_html = markdown_to_html(
            section.get("markdown", ""),
            chart_loader=chart_loader,
            image_loader=image_loader,
            inline_charts=True,
            widget_renderer=widget_renderer_for(doc),
        )
        # 任务级注解：插在每个任务块尾（标签 = markdown 里的 #### 标题）
        section_html = _apply_hidden(section["key"], section_html, hidden)
        section_html = _inject_task_notes(section_html, doc.get("note_blocks") or {})
        # 类型级注解（只在本章节 = 重点科学结果分析）：插在每个类型标题正下方
        if section["key"] == "science":
            section_html = _inject_type_notes(section_html, doc.get("notes") or {})
        body_parts.append(section_html)
    dialogs_html = render_dialogs(
        doc.get("dialogs") or [], image_loader=image_loader, chart_loader=chart_loader
    )
    # 页脚**只留对外信息**（报告是给客户看的，2026-10-15 用户："报告不出现警告和提示"）：
    # 报告 ID / schema 版本 / 风险高中低计数 / 导出章节数都是内部口径，页眉已有项目名与时间。
    footer = (
        f"项目：{meta.get('project_name', '')} · "
        f"数据窗口：{((meta.get('time_window') or {}).get('label')) or '—'} · "
        f"生成时间：{meta.get('generated_at', '')}"
    )
    auto = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),600));</script>" if auto_print else ""
    # 交互版：数据脚本 + 运行时（都在 `</body>` 前，跑的时候 DOM 已经就绪）
    interactive = ""
    if interactive_js and interactive_data:
        payload = json.dumps(interactive_data, ensure_ascii=False, separators=(",", ":")).replace(
            "<", "\\u003c"
        )
        # 3Dmol 先加载（全局 `$3Dmol`），再跑运行时 —— 与站内 index.html 同一顺序
        mol = f"<script>{mol_js}</script>" if mol_js else ""
        interactive = (
            f"<script>window.__VASP_REPORT_DATA__={payload};</script>"
            f"{mol}"
            f"<script>{interactive_js}</script>"
        )
    return (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"/>"
        f'<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f"<title>{html_lib.escape(str(meta.get('project_name', '')))} · 项目报告</title>"
        f"<style>{CSS}</style></head><body>"
        f"<h1>{html_lib.escape(str(meta.get('project_name', '')))} · 项目报告</h1>"
        f'<div class="report-meta">{html_lib.escape(str((meta.get("time_window") or {}).get("label", "")))}'
        f" · 生成于 {html_lib.escape(str(meta.get('generated_at', '')))}</div>"
        + "".join(body_parts)
        + f'<div class="footer">{html_lib.escape(footer)}</div>'
        + dialogs_html
        + f"<script>{VIEWER_SCRIPT}</script>"
        + interactive
        + auto
        + "</body></html>"
    )
