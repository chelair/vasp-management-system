import type { InspectionDetail, InspectionResult } from '../types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new Error('无法连接后端服务：请先运行 npm run server（端口 3001）');
  }
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || body.success === false) {
    throw new Error(body?.message ?? `请求失败（HTTP ${res.status}）`);
  }
  return body.data as T;
}

export interface InspectionRejected {
  task_id: string;
  message: string;
}

export interface InspectionRunSummary {
  run_id: string;
  checked_at: string;
  inspected: number;
  updated: number;
  unchanged: number;
  warnings: number;
  rejected: InspectionRejected[];
  skipped_projects: string[];
  archived_files: string[];
}

export interface InspectionMeta {
  enabled: boolean;
  interval_hours: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_run_summary: InspectionRunSummary | null;
}

export interface InspectionRunScope {
  project_name?: string | null;
  task_id?: string | null;
}

/** 巡检结果列表（数据以真实后端为准；后端不可用时返回空列表） */
export async function fetchInspectionResults(): Promise<InspectionResult[]> {
  try {
    const data = await request<{ results: InspectionResult[] }>('/inspections');
    return data.results;
  } catch (err) {
    console.warn('[api] 后端不可用，巡检结果为空：', err);
    return [];
  }
}

/** 自动巡检调度信息（后端不可用时返回 null，页面用本地估算兜底） */
export async function fetchInspectionMeta(): Promise<InspectionMeta | null> {
  try {
    return await request<InspectionMeta>('/inspections/meta');
  } catch {
    return null;
  }
}

/** 立即巡检（需要后端；返回本轮摘要） */
export async function runInspection(
  scope: InspectionRunScope = {},
): Promise<InspectionRunSummary> {
  return request<InspectionRunSummary>('/inspections/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scope),
  });
}

/** 单任务巡检详情（能量/力曲线 + 结构分析） */
export async function fetchInspectionDetail(
  taskId: string,
): Promise<InspectionDetail> {
  return request<InspectionDetail>(`/inspections/${encodeURIComponent(taskId)}`);
}
