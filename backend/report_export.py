"""报告导出：把结构化报告渲染成自包含 HTML（供下载 / 浏览器打印成 PDF）。

要点：
- **可选范围**：按 `sections` 只导出指定章节（如取消勾选风险分析）；
- **自包含**：图表以**内联 SVG** 写入，CSS 内联，单文件即可离线打开；
- **打印友好**：A4 页边距、表格/图表不跨页断开，供「打印为 PDF」直接使用；
- Markdown → HTML 使用内置轻量转换器（只覆盖本项目生成的语法子集），
  保证 HTML 与 Markdown 内容完全一致，不引入第三方依赖。
"""

import html as html_lib
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
@page { size: A4; margin: 14mm; }
@media print {
  body { padding: 0; font-size: 12px; }
  h2 { page-break-before: auto; }
  .no-print { display: none !important; }
}
"""


def _inline(text: str) -> str:
    """行内语法：**加粗**、`代码`、_斜体_、[文字](链接)。"""
    out = html_lib.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])", r"<em>\1</em>", out)

    def link(m: "re.Match[str]") -> str:
        label, href = m.group(1), m.group(2)
        safe = href if not href.lower().startswith(("javascript:", "data:")) else "#"
        return f'<a href="{safe}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, out)


def markdown_to_html(
    markdown: str,
    *,
    chart_loader: Optional[Callable[[str], Optional[str]]] = None,
    inline_charts: bool = True,
) -> str:
    """把报告 Markdown 子集转为 HTML（表格 / 列表 / 图片 / 加粗 / 代码）。"""
    lines = (markdown or "").split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
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
                    out.extend(f"<td>{_inline(c)}</td>" for c in row)
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

        # 图片
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if m:
            alt, src = m.group(1), m.group(2)
            svg = None
            if inline_charts and chart_loader is not None and src.startswith("charts/"):
                svg = chart_loader(src.split("/", 1)[1])
            if svg:
                out.append(f"<figure>{svg}<figcaption>{_inline(alt)}</figcaption></figure>")
            else:
                out.append(
                    f'<figure><img src="{html_lib.escape(src)}" alt="{html_lib.escape(alt)}"/>'
                    f"<figcaption>{_inline(alt)}</figcaption></figure>"
                )
            i += 1
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


def render_html(
    doc: Dict[str, Any],
    markdown_sections: List[Dict[str, str]],
    *,
    sections: Optional[List[str]] = None,
    chart_loader: Optional[Callable[[str], Optional[str]]] = None,
    auto_print: bool = False,
) -> str:
    """生成自包含 HTML。`sections` 为空表示导出全部章节。"""
    meta = doc.get("metadata") or {}
    chosen = set(sections) if sections else {s["key"] for s in markdown_sections}
    body_parts: List[str] = []
    for section in markdown_sections:
        if section["key"] not in chosen:
            continue
        title = SECTION_TITLES.get(section["key"], section["title"])
        body_parts.append(f"<h2>{html_lib.escape(title)}</h2>")
        body_parts.append(
            markdown_to_html(
                section.get("markdown", ""),
                chart_loader=chart_loader,
                inline_charts=True,
            )
        )
    risk_summary = (doc.get("risks") or {}).get("summary") or {}
    footer = (
        f"报告 ID：{meta.get('report_id', '')} · 项目：{meta.get('project_name', '')} · "
        f"生成时间：{meta.get('generated_at', '')} · schema {doc.get('schema_version', '')} · "
        f"风险：高 {risk_summary.get('high', 0)} / 中 {risk_summary.get('medium', 0)} / "
        f"低 {risk_summary.get('low', 0)} · 导出章节 {len(chosen)}/{len(markdown_sections)}"
    )
    auto = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),600));</script>" if auto_print else ""
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
        + auto
        + "</body></html>"
    )
