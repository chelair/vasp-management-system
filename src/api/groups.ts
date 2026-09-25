import { request } from './client';
import type { EleSubtype, TaskType } from '../types';

/**
 * 计算流程组与任务创建 API（后端 /api/groups）。
 * 后端负责目录创建、元数据与默认输入文件生成。
 */

export interface CreateGroupResult {
  group_id: string;
  group_root: string;
  task_count: number;
  tasks: string[];
  warnings: string[];
}

/** 全局辅助分子（跨项目统一调用） */
export interface AuxMolecule {
  label: string;
  dir: string;
  opt_dir: string;
  frac_dir: string;
  energy?: number | null;
  zpe?: number | null;
  correction?: number | null;
  status: string;
}

/** 创建自由能路径组：N 个主结构 × (opt+frac) + 辅助分子 × (opt+frac) */
export function createFreeEnergyGroup(payload: {
  project: string;
  name?: string;
  structures: number;
  aux_molecules: string[];
}): Promise<CreateGroupResult> {
  return request('/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_type: 'free_energy', ...payload }),
  });
}

/** 创建 NEB 流程组：initial_opt / final_opt / neb_calc(映像目录按系统默认生成) */
export function createNebGroup(payload: {
  project: string;
  name?: string;
  images?: number;
}): Promise<CreateGroupResult> {
  return request('/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_type: 'neb', ...payload }),
  });
}

/** 新增全局辅助分子（固定存放于本地 aux_molecules/） */
export function addAuxMolecule(label: string): Promise<AuxMolecule> {
  return request('/aux-molecules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label }),
  });
}

/** 查询全局辅助分子列表 */
export async function fetchAuxMolecules(): Promise<AuxMolecule[]> {
  const data = await request<{ molecules: AuxMolecule[] }>('/aux-molecules');
  return data.molecules;
}

/** 创建独立任务（group=None，落库 + 建目录） */
export function createIndependentTask(payload: {
  project: string;
  model_name: string;
  task_type: TaskType;
  subtype?: EleSubtype | null;
}): Promise<{ task_id: string; dir_path: string; remote_warning?: string | null }> {
  return request('/groups/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/* ============================================================
   报告组数据
   ============================================================ */

export interface ReportGroupSummary {
  group_id: string;
  project: string;
  group_type: 'free_energy' | 'neb';
  root_dir: string | null;
  roles: Record<string, number>;
  task_count: number;
}

export interface GroupTaskEnergy {
  task_id?: string;
  status?: string;
  dir?: string;
  energy?: number | null;
  zpe?: number | null;
  correction?: number | null;
}

export interface FreeEnergyGroupData {
  structures: {
    label: string;
    role: string;
    opt?: GroupTaskEnergy;
    frac?: GroupTaskEnergy;
    free_energy?: number | null;
    parsing_note?: string;
  }[];
  aux_molecules: {
    label: string;
    role: string;
    opt?: GroupTaskEnergy;
    frac?: GroupTaskEnergy;
    free_energy?: number | null;
    parsing_note?: string;
  }[];
  parsing_note?: string;
}

export interface NebGroupData {
  initial?: GroupTaskEnergy;
  final?: GroupTaskEnergy;
  images: { index: number; dir: string; energy?: number | null }[];
  barrier?: number | null;
  neb_task_id?: string;
  neb_dir?: string;
  parsing_note?: string;
}

export interface GroupReportData {
  group_id: string;
  project: string;
  group_type: 'free_energy' | 'neb';
  free_energy: FreeEnergyGroupData | null;
  neb: NebGroupData | null;
}

export async function fetchReportGroups(): Promise<ReportGroupSummary[]> {
  const data = await request<{ groups: ReportGroupSummary[] }>('/reports/groups');
  return data.groups;
}

export async function fetchGroupReportData(groupId: string): Promise<GroupReportData> {
  return request(`/reports/groups/${encodeURIComponent(groupId)}/data`);
}

/** 为自由能组添加结构（自动生成 结构N+1 的 opt+frac） */
export async function addGroupStructures(
  groupId: string,
  count: number,
): Promise<{ group_id: string; labels: string[]; task_ids: string[] }> {
  return request(`/groups/${encodeURIComponent(groupId)}/structures`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count }),
  });
}
