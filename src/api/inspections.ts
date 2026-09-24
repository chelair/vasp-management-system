import { request } from './client';
import type { InspectionDetail, InspectionResult } from '../types';

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
  /** 调度器实际运行状态（v0.6.2 起接入后台线程） */
  scheduler?: {
    enabled: boolean;
    interval_hours: number;
    scheduler_started: boolean;
    running: boolean;
    /** 最近一次**自动**巡检（手动点「立即巡检」不计入，倒计时按它算） */
    last_run_at: string | null;
    /** 最近一次巡检（含手动），仅用于展示 */
    last_any_run_at?: string | null;
    next_run_at: string | null;
    last_triggered_at: string | null;
    last_finished_at: string | null;
    last_error: string | null;
  };
}

/** 开关自动巡检 / 调整间隔（写入 settings.json） */
export async function updateAutoInspection(payload: {
  enabled?: boolean;
  interval_hours?: number;
}): Promise<InspectionMeta['scheduler']> {
  return request('/inspections/auto', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
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

/** 单任务巡检（任意状态任务均可触发；完成后归档新增/更新该任务记录） */
export async function runSingleInspection(taskId: string): Promise<InspectionRunSummary> {
  return request<InspectionRunSummary>(
    `/inspections/run-single/${encodeURIComponent(taskId)}`,
    { method: 'POST' },
  );
}

/** 单任务巡检详情（能量/力曲线 + 结构分析） */
export async function fetchInspectionDetail(
  taskId: string,
): Promise<InspectionDetail> {
  return request<InspectionDetail>(`/inspections/${encodeURIComponent(taskId)}`);
}

/** 自由能路径汇总（各中间体 DFT 能量、矫正项、自由能） */
export interface FreeEnergyStructure {
  task_id: string;
  structure_label: string;
  dft_energy: number | null;
  correction: number | null;
  free_energy: number | null;
  converged: boolean;
  corrected: boolean;
}

export async function fetchFreeEnergySummary(
  groupId: string,
): Promise<{ group_id: string; name: string; structures: FreeEnergyStructure[] }> {
  return request(`/free-energy/${encodeURIComponent(groupId)}/summary`);
}
