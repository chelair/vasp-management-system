import { request, wait } from './client';
import {
  QUEUE_OPTIONS,
  buildSubmitScript,
  recommendCores,
  simulateFallbackSnapshot,
} from '../data/mock/cluster';
import type {
  ClusterSnapshot,
  IncarPreset,
  QueueOption,
  ScriptFormat,
  SubmitScriptOptions,
} from '../types';

/**
 * 作业管理数据层（框架阶段）。
 * - INCAR 预设：localStorage 持久化，刷新后仍可用
 * - 节点状态 / 提交脚本：Mock 数据，后续替换为后端 SSH 接口
 */

const PRESET_STORAGE_KEY = 'vasp.incar.presets.v1';

export function loadIncarPresets(): IncarPreset[] {
  try {
    const raw = localStorage.getItem(PRESET_STORAGE_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as IncarPreset[];
    return Array.isArray(list) ? list.filter((p) => p && p.name && p.params) : [];
  } catch {
    return [];
  }
}

export function saveIncarPreset(name: string, params: Record<string, string>): IncarPreset {
  const preset: IncarPreset = {
    id: `user:${Date.now()}`,
    name,
    params: { ...params },
    createdAt: new Date().toISOString(),
  };
  const all = [...loadIncarPresets(), preset];
  localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(all));
  return preset;
}

export function deleteIncarPreset(id: string): IncarPreset[] {
  const rest = loadIncarPresets().filter((p) => p.id !== id);
  localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(rest));
  return rest;
}

/** 获取集群节点状态快照：优先后端（bhost + bqueues + node_groups），后端不可用回退本地模拟 */
export async function fetchClusterSnapshot(refresh = false): Promise<ClusterSnapshot> {
  try {
    return await request<ClusterSnapshot>(`/jobs/nodes${refresh ? '?refresh=1' : ''}`);
  } catch {
    await wait(200);
    return simulateFallbackSnapshot();
  }
}

export function fetchQueueOptions(format: ScriptFormat): QueueOption[] {
  return QUEUE_OPTIONS[format];
}

export function getRecommendedCores(nodes: ClusterSnapshot['nodes']): number {
  return recommendCores(nodes);
}

/** 生成提交脚本内容 */
export function generateSubmitScript(opts: SubmitScriptOptions): string {
  return buildSubmitScript(opts);
}

/* ============================================================
   本地任务目录文件读写（后端 /api/jobs，统一管理 data/projects/...）
   ============================================================ */

export interface TaskFileEntry {
  name: string;
  size: number;
  modified: string;
}

/** 读取任务本地目录文件清单（第一次打开/刷新时扫描） */
export async function fetchTaskFiles(taskId: string): Promise<TaskFileEntry[]> {
  const data = await request<{ task_id: string; dir: string; files: TaskFileEntry[] }>(
    `/jobs/tasks/${encodeURIComponent(taskId)}/files`,
  );
  return data.files;
}

/** 读取任务本地目录中的单个文本文件内容 */
export async function fetchTaskFile(
  taskId: string,
  filename: string,
): Promise<{ name: string; path: string; content: string }> {
  return request(
    `/jobs/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(filename)}`,
  );
}

/** 写入任务本地目录中的文本文件（如导入 POSCAR） */
export async function saveTaskFile(
  taskId: string,
  filename: string,
  content: string,
): Promise<{ name: string; path: string; size: number }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/files/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

/** 在服务器本机打开任务本地目录（定位到 files/） */
export async function openTaskFolder(
  taskId: string,
): Promise<{ path: string }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/open-folder`, {
    method: 'POST',
  });
}

/** 同类型续算（全部在远程服务器端完成）：创建 conN 并登记续算子任务 */
export async function createContinuation(
  taskId: string,
): Promise<
  {
    action:
      | 'created'
      | 'running'
      | 'input_complete_but_not_finished'
      | 'input_incomplete';
    message: string;
    current_dir?: string;
    job_id?: string;
    missing_files?: string[];
    warnings: string[];
  } & Partial<{
  task_id: string;
  con: string;
  remote_dir: string;
  source_dir: string;
  incar_changes: Record<string, string>;
  copied_files: string[];
  images?: string[];
  local_dir: string;
}>
> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/continuation`, {
    method: 'POST',
  });
}

/** 提交作业：远程目录执行 bsub < vasp.lsf，返回作业 ID 并更新任务状态为 queued */
export async function submitTask(taskId: string): Promise<{
  job_id: string;
  new_status: string;
  raw_output: string;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/submit`, {
    method: 'POST',
  });
}

/** 停止作业：远程 bkill 终止运行中的作业，任务状态回退为待提交 */
export async function stopTask(taskId: string): Promise<{
  job_id: string;
  new_status: string;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/stop`, {
    method: 'POST',
  });
}

/** 为结构优化任务构建频率矫正（frac）输入文件（自由能流程） */
export async function createFracFiles(
  taskId: string,
  ibration = 5,
): Promise<{
  frac_dir: string;
  source_dir: string;
  latest_dir: string | null;
  incar_changes: Record<string, string>;
  copied_files: string[];
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/create-frac`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ibration }),
  });
}

/** 为电子结构任务构建输入文件（从 opt 导入或外部结构） */
export async function buildEleInputs(
  taskId: string,
  payload: {
    source_type: 'opt' | 'external';
    source_task_id?: string;
    ele_type: string;
    params?: Record<string, string | number | boolean>;
  },
): Promise<{
  ele_dir: string;
  source_type: string;
  source_dir: string | null;
  ele_type: string;
  incar_changes: Record<string, string>;
  copied_files: string[];
  warnings: string[];
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/build-ele-inputs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 根据初末态 opt 任务创建 NEB 计算文件（nebmake.pl 插值） */
export async function createNebFiles(
  taskId: string,
  payload: {
    initial_opt_task_id: string;
    final_opt_task_id: string;
    num_images: number;
  },
): Promise<{
  neb_dir: string;
  source_is: string;
  source_fs: string;
  num_images: number;
  images: string[];
  incar_changes: Record<string, string | number>;
  copied_files: string[];
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/create-neb-files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 重命名独立任务（同步本地/远端目录与数据库） */
export async function renameTask(
  taskId: string,
  modelName: string,
): Promise<{ task_id: string; model_name: string; dir_path: string; remote_dir: string }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_name: modelName }),
  });
}

/** 删除最末端子项（本地目录移入回收站，远端目录不自动删除） */
export async function deleteTask(
  taskId: string,
): Promise<{ task_id: string; model_name: string; local_trash: string | null; remote_dir: string }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  });
}
