/**
 * 轻量 Markdown 渲染（无第三方依赖）。
 *
 * 只覆盖本项目后端生成的语法子集：标题、表格、无序列表、加粗、行内代码、
 * 斜体、链接、图片、分隔线与段落。HTML 特殊字符会转义，链接/图片做协议白名单，
 * 因此可以安全地配合 dangerouslySetInnerHTML 使用。
 */

const ESCAPE: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ESCAPE[c]);
}

function safeUrl(url: string): string {
  const value = url.trim();
  if (/^(https?:|mailto:|#|\/)/i.test(value)) return escapeHtml(value);
  return '#';
}

/** 行内语法 */
function inline(text: string, chartResolver?: (path: string) => string): string {
  let out = escapeHtml(text);
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])/g, '<em>$1</em>');
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label: string, href: string) => {
    const url = chartResolver && !/^(https?:|mailto:|#|\/)/i.test(href) && href.startsWith('charts/')
      ? chartResolver(href)
      : href;
    return `<a href="${safeUrl(url)}" target="_blank" rel="noreferrer">${label}</a>`;
  });
  return out;
}

interface Options {
  /** 把 Markdown 里的相对图表路径（charts/xxx.svg）解析为可访问 URL */
  chartResolver?: (path: string) => string;
  /** 图片包装 class（默认 report-figure） */
  figureClass?: string;
}

export function renderMarkdown(markdown: string, options: Options = {}): string {
  const { chartResolver, figureClass = 'report-figure' } = options;
  const lines = (markdown || '').split('\n');
  const html: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line) {
      i += 1;
      continue;
    }

    // 表格
    if (line.startsWith('|')) {
      const block: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        block.push(lines[i].trim());
        i += 1;
      }
      const rows = block
        .filter((row) => !/^\|[\s\-:|]+\|$/.test(row))
        .map((row) => row.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
      if (rows.length) {
        const [head, ...body] = rows;
        html.push('<table class="report-table"><thead><tr>');
        head.forEach((c) => html.push(`<th>${inline(c, chartResolver)}</th>`));
        html.push('</tr></thead><tbody>');
        body.forEach((row) => {
          html.push('<tr>');
          row.forEach((c) => html.push(`<td>${inline(c, chartResolver)}</td>`));
          html.push('</tr>');
        });
        html.push('</tbody></table>');
      }
      continue;
    }

    // 列表
    if (/^[-*]\s+/.test(line)) {
      html.push('<ul class="report-list">');
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        let item = lines[i].trim().replace(/^[-*]\s+/, '');
        i += 1;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i])) {
          item += ` ${lines[i].trim()}`;
          i += 1;
        }
        html.push(`<li>${inline(item, chartResolver)}</li>`);
      }
      html.push('</ul>');
      continue;
    }

    // 图片
    const img = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line);
    if (img) {
      const alt = img[1];
      const src = img[2].startsWith('charts/') && chartResolver
        ? chartResolver(img[2])
        : img[2];
      html.push(
      // 报告页一屏内会挂十几张图，用 eager + async 解码：既不会出现"滚到才加载"的空白，
      // 也不会阻塞正文渲染（lazy 在部分内嵌浏览器里会一直不加载）
      `<figure class="${figureClass}"><img src="${safeUrl(src)}" alt="${escapeHtml(alt)}" loading="eager" decoding="async"/><figcaption>${escapeHtml(alt)}</figcaption></figure>`,
      );
      i += 1;
      continue;
    }

    // 标题（h1/h2 由页面自己渲染，这里从 h3 起，保持层级合理）
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      html.push(`<h${level} class="report-md-h${level}">${inline(heading[2], chartResolver)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^-{3,}$/.test(line)) {
      html.push('<hr/>');
      i += 1;
      continue;
    }

    // 段落（合并连续行）
    const paragraph = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^([-*]\s|\||!\[|#{1,6}\s|-{3,}$)/.test(lines[i].trim())
    ) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    html.push(`<p>${inline(paragraph.join(' '), chartResolver)}</p>`);
  }

  return html.join('\n');
}
