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

/** 逐原子受力（巡检详情页 3D 视图「查看原子受力」） */
export interface AtomicForceAtom {
  /** CIF / POSCAR 原子下标（0 起，与 3D 视图里的原子一一对应） */
  index: number;
  element?: string;
  fx: number;
  fy: number;
  fz: number;
  /** max(|fx|,|fy|,|fz|) —— 与 VASP 力判据（EDIFFG）同口径 */
  fmax: number;
  /** Selective dynamics 固定的原子（不参与收敛判据） */
  fixed: boolean;
}

export interface AtomicForces {
  task_id: string;
  task_type: string;
  /** NEB 才有：映像编号 */
  image: string | null;
  /** 受力取自哪个远端工作目录 */
  work_dir: string;
  /** 结构来源子目录（`""` = 任务主目录）——与界面显示的 CONTCAR 同一个目录 */
  source_dir?: string;
  structure: string;
  /** 第几个离子步（OUTCAR 里 TOTAL-FORCE 块序号） */
  ionic_step: number | null;
  energy: number | null;
  force_max: number | null;
  force_rms: number | null;
  threshold: {
    max_force_threshold: number;
    rms_force_threshold: number;
    source: string;
  } | null;
  atom_count: number;
  fixed_count: number;
  /** POSCAR 展开后的逐原子元素（VASP4 无元素名时为 null） */
  elements: string[] | null;
  atoms: AtomicForceAtom[];
  warnings: string[];
  /** 命中本地缓存（任务已结束，未连远端） */
  cached: boolean;
  /** NEB：同一次调用里一并取回的其它映像编号（都已在本地落盘，切换即时可见） */
  sibling_images?: string[];
  fetched_at: string;
  /** 落盘位置（任务本地镜像 reports/atomic_forces*.json，与 files/ 同级） */
  cache_path?: string;
}

/**
 * 读取逐原子受力。结果落在任务本地镜像 `reports/atomic_forces*.json`（与 `files/` 同级）：
 * 任务已结束时直接读本地缓存，任务在跑时会重新取远端并覆盖。
 */
export async function fetchAtomicForces(
  taskId: string,
  options: { image?: string | null; refresh?: boolean } = {},
): Promise<AtomicForces> {
  const query = new URLSearchParams();
  if (options.image) query.set('image', options.image);
  if (options.refresh) query.set('refresh', '1');
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return request<AtomicForces>(
    `/inspections/${encodeURIComponent(taskId)}/atomic-forces${suffix}`,
  );
}
