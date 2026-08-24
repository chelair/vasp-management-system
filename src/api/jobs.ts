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
