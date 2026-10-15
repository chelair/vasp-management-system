import { request } from './client';
import type {
  ProjectReportDetail,
  ProjectReportGenerateResult,
  ProjectReportMeta,
} from '../types';

/**
 * 项目报告接口（v0.7.0 重构）。
 *
 * 后端按项目生成结构化数据（report.json）+ Markdown（report.md）+ 图表（charts/*.svg），
 * 接口提供：生成 / 列表 / 详情 / 结构化数据 / Markdown / 自包含 HTML 导出 / 删除。
 */

/** 生成项目报告：传 project_id 生成单个，project_ids 或多个 / all=true 批量生成 */
export async function generateProjectReports(payload: {
  project_id?: string;
  project_ids?: string[];
  all?: boolean;
  window_days?: number;
}): Promise<ProjectReportGenerateResult> {
  return request<ProjectReportGenerateResult>('/reports/project/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 报告列表（可按项目 ID / 名称过滤） */
export async function fetchProjectReports(project?: string): Promise<ProjectReportMeta[]> {
  try {
    const data = await request<{ reports: ProjectReportMeta[] }>(
      `/reports/project/list${project ? `?project=${encodeURIComponent(project)}` : ''}`,
    );
    return data.reports;
  } catch (err) {
    console.warn('[api] 读取报告列表失败：', err);
    return [];
  }
}

/** 报告详情（元数据 + 章节 Markdown + 结构化数据） */
export async function fetchProjectReport(reportId: string): Promise<ProjectReportDetail> {
  return request<ProjectReportDetail>(
    `/reports/project/${encodeURIComponent(reportId)}`,
  );
}

/** 仅结构化数据（大模型输入格式） */
export async function fetchProjectReportStructured(
  reportId: string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/reports/project/${encodeURIComponent(reportId)}/structured`,
  );
}

/** 删除报告 */
export async function deleteProjectReport(reportId: string): Promise<void> {
  await request(`/reports/project/${encodeURIComponent(reportId)}`, { method: 'DELETE' });
}

/** Markdown 下载地址 */
export function reportMarkdownUrl(reportId: string): string {
  return `/api/reports/project/${encodeURIComponent(reportId)}/markdown`;
}

/**
 * 自包含 HTML 导出地址。
 * `sections` 传章节 key 数组（空/undefined = 全部章节）；
 * `print=true` 时打开后自动调起浏览器打印（另存为 PDF）。
 */
export function reportHtmlUrl(
  reportId: string,
  sections?: string[],
  print = false,
  hidden?: string[],
  interactive = true,
): string {
  const params = new URLSearchParams();
  if (sections && sections.length) params.set('sections', sections.join(','));
  if (print) params.set('print', '1');
  // 交互版（v0.9.62）：内联 ECharts 运行时 + PDOS 数据，报告里的 PDOS/功函数图可交互；
  // 关掉就是纯静态版（体积小、老浏览器/微信里更稳）。
  if (!interactive) params.set('interactive', '0');
  // 前端隐藏的章节/元素：导出时一并排除（section:x / task:<章节>:<标题> / figure:<章节>:<序号>）
  if (hidden && hidden.length) params.set('hide', hidden.join(','));
  const query = params.toString();
  return `/api/reports/project/${encodeURIComponent(reportId)}/export.html${query ? `?${query}` : ''}`;
}

/** 图表文件地址（SVG） */
export function reportChartUrl(reportId: string, chartPath: string): string {
  const name = chartPath.split('/').pop() ?? chartPath;
  return `/api/reports/project/${encodeURIComponent(reportId)}/files/${encodeURIComponent(name)}`;
}

/** 报告里的结构三视图（VESTA PNG，images/xxx.png）→ 可访问 URL */
export function reportImageUrl(reportId: string, imagePath: string): string {
  const name = imagePath.split('/').pop() ?? imagePath;
  return `/api/reports/project/${encodeURIComponent(reportId)}/images/${encodeURIComponent(name)}`;
}

/** 报告注解（结果分析描述 / 论文写作参考） */
export async function fetchReportNotes(reportId: string): Promise<{
  notes: Record<string, { analysis_note: string; paper_note: string; updated_at?: string }>;
}> {
  return request(`/reports/project/${encodeURIComponent(reportId)}/notes`);
}

/** 写一条报告注解（两条都空 = 删除） */
export async function saveReportNote(
  reportId: string,
  key: string,
  analysisNote: string,
  paperNote: string,
): Promise<{ notes: Record<string, { analysis_note: string; paper_note: string; updated_at?: string }> }> {
  return request(`/reports/project/${encodeURIComponent(reportId)}/notes`, {
    method: 'PUT',
    body: JSON.stringify({ key, analysis_note: analysisNote, paper_note: paperNote }),
  });
}

export interface ReportEdits {
  hidden_sections: string[];
  hidden_elements: string[];
}

/** 报告的隐藏状态（章节 / 元素） */
export async function fetchReportEdits(reportId: string): Promise<ReportEdits> {
  return request(`/reports/project/${encodeURIComponent(reportId)}/edits`);
}

/** 保存报告的隐藏状态（覆盖写） */
export async function saveReportEdits(
  reportId: string,
  hiddenSections: string[],
  hiddenElements: string[],
): Promise<ReportEdits> {
  return request(`/reports/project/${encodeURIComponent(reportId)}/edits`, {
    method: 'PUT',
    body: JSON.stringify({ hidden_sections: hiddenSections, hidden_elements: hiddenElements }),
  });
}

/** 报告 schema 清单（版本 / 枚举 / 单位 / 章节） */
export async function fetchReportSchema(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>('/reports/project/schema');
}
