/**
 * 图表数据导出（2026-10-15，用户："html 中态密度、功函数要支持导出 txt/csv 格式数据"）。
 *
 * 设计：**造表（纯函数）** 与 **下载（副作用）** 分开 ——
 * 前者好测（jsdom 里直接断言表头与数值），后者只有几行 Blob + `<a>` 点击。
 *
 * - CSV：只有表头 + 数据（Excel / Origin 直接认，不带注释行）；
 * - TXT：`#` 注释块（数据来源、费米能级、自旋、范围等）+ 表头 + 空格分隔数据
 *   （gnuplot / xmgrace / VASP 社区一眼能读）。
 *
 * 下载用 Blob + `URL.createObjectURL`：**完全在前端完成**，导出的单文件 HTML 离线也能用。
 */

/** 一张待导出的表：表头 + 行（行内空值用 null，导出时写空） */
export interface ExportTable {
  header: string[];
  rows: (number | string | null)[][];
}

/** 数字转文本：保留有效位但去掉浮点尾巴（`-0.25` / `1.0e-5`） */
export function num(value: number | null | undefined, digits = 6): string {
  if (value == null || !Number.isFinite(Number(value))) return '';
  const rounded = Number(value).toFixed(digits);
  // 去掉多余的小数 0（`0.250000` → `0.25`，`3.000000` → `3`）
  return rounded.includes('.') ? rounded.replace(/0+$/, '').replace(/\.$/, '') : rounded;
}

function csvCell(value: number | string | null): string {
  if (value == null) return '';
  const text = typeof value === 'number' ? num(value) : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** CSV 文本（表头 + 数据；行尾统一 \n，Excel 也认） */
export function tableToCsv(table: ExportTable): string {
  const lines = [table.header.map((h) => csvCell(h)).join(',')];
  for (const row of table.rows) lines.push(row.map((cell) => csvCell(cell)).join(','));
  return lines.join('\n') + '\n';
}

/** TXT 文本：`#` 注释块 + 表头 + 空格分隔（空值写 `NaN`，gnuplot 会断开） */
export function tableToTxt(table: ExportTable, comments: string[] = []): string {
  const lines: string[] = [];
  for (const line of comments) lines.push(line.startsWith('#') ? line : `# ${line}`);
  lines.push(`# ${table.header.join(' ')}`);
  for (const row of table.rows) {
    lines.push(row.map((cell) => (typeof cell === 'number' ? num(cell) : cell ?? 'NaN')).join(' '));
  }
  return lines.join('\n') + '\n';
}

/** 文件名字段清洗：去掉路径分隔与空白（任务名里可能有 `/`、空格） */
export function safeName(text: string): string {
  return String(text || 'data').replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 60);
}

/** 时间戳（`20261015-2210`），用于文件名去重 */
export function stamp(date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}`
  );
}

/** 触发浏览器下载（BOM 前置，Excel 打开 UTF-8 中文不乱码） */
export function downloadTextFile(
  filename: string,
  text: string,
  mime = 'text/csv;charset=utf-8',
): void {
  const doc = typeof document !== 'undefined' ? document : null;
  if (!doc) return;
  const blob = new Blob(['\ufeff' + text], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = doc.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  doc.body.appendChild(link);
  link.click();
  link.remove();
  // 立刻回收会让部分浏览器下载中断，延后释放
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
