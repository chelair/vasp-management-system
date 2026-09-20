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

/** 关闭（归档）任务：只改状态，本地/远端文件都不动 */
export async function archiveTask(taskId: string): Promise<{
  task_id: string;
  project_name: string;
  new_status: string;
  previous_status: string;
  was_completed: boolean;
  /** 归档前的频率矫正状态（自由能主任务才有） */
  frac_status: string | null;
  /** 连带归档的频率矫正子任务 */
  archived_siblings: {
    task_id: string;
    model_name: string;
    previous_status: string;
    was_completed: boolean;
  }[];
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/archive`, {
    method: 'POST',
  });
}

/** 重新打开已归档任务（恢复到归档前状态） */
export async function unarchiveTask(taskId: string): Promise<{
  task_id: string;
  project_name: string;
  new_status: string;
  /** 连带恢复的频率矫正子任务 */
  reopened_siblings: { task_id: string; model_name: string; new_status: string }[];
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/unarchive`, {
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

/** 上传 INCAR 到远端最新目录（旧文件备份为 old_INCAR） */
export async function uploadIncar(
  taskId: string,
  payload: { content?: string; params?: Record<string, string | number | boolean> },
): Promise<{
  dir: string;
  backup_file: string | null;
  warnings: string[];
  /** 本次同步顺带生效的台账 key（同步到远端 = 立即应用这些修改） */
  applied: string[];
  state: TaskInputState;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/upload-incar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 上传 KPOINTS 到远端最新目录（旧文件备份为 old_KPOINTS） */
export async function uploadKpoints(
  taskId: string,
  payload: { content: string },
): Promise<{
  dir: string;
  backup_file: string | null;
  applied: string[];
  state: TaskInputState;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/upload-kpoints`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * 写入提交脚本到远端最新目录（v0.8.7）：
 * 旧 `vasp.lsf` 自动备份为 `old_vasp.lsf`，同时同步一份到本地镜像 `files/vasp.lsf`。
 */
export async function uploadSubmitScript(
  taskId: string,
  payload: { content: string },
): Promise<{
  dir: string;
  remote_path: string;
  backup_file: string | null;
  size: number;
  local_path: string | null;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/upload-submit-script`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * 上传 POSCAR 到远端最新目录（v0.8.8）：
 * 旧文件备份为 `old_POSCAR`，同时同步一份到本地镜像 `files/POSCAR`。
 */
export async function uploadPoscar(
  taskId: string,
  payload: { content: string },
): Promise<{
  dir: string;
  remote_path: string;
  backup_file: string | null;
  size: number;
  local_path: string | null;
  applied: string[];
  state: TaskInputState;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/upload-poscar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * 在远端「当前目录」（最新 conN，无则主目录）运行 `pos2pot` 生成 POTCAR（v0.8.8）。
 * 单次 exec 完成：命令输出 + POTCAR 大小/行数/元素都在这一个响应里。
 */
export async function generatePotcar(taskId: string): Promise<{
  dir: string;
  command: string;
  exit_code: number;
  output: string;
  generated: boolean;
  potcar: {
    exists: boolean;
    size: number;
    lines: number;
    elements: string[];
    elements_count: number;
  };
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/generate-potcar`, {
    method: 'POST',
  });
}

export interface SelectiveDynamicsPayload {
  /** 用页面当前的 POSCAR 文本；不传则后端读本地镜像 files/POSCAR */
  content?: string;
  mode: 'manual' | 'elements' | 'z_range';
  /** manual：选中的原子（poscarIndex 为 1 起的 POSCAR 坐标行序号） */
  atoms?: { element?: string; poscarIndex?: number; index?: number }[];
  /** elements：要固定的元素符号 */
  elements?: string[];
  /** z_range：分数坐标 z 区间 */
  zRange?: [number, number];
  numbering?: 'element' | 'global';
  labels?: boolean;
  /** 生成后是否同时写入远端最新目录（旧文件备份 old_POSCAR） */
  syncRemote?: boolean;
}

/**
 * 生成带 `Selective Dynamics` 的 POSCAR（固定选中原子）——v0.8.7。
 * 本地写回 `files/POSCAR`（旧文件备份 `files/old_POSCAR`）并刷新元数据；
 * `syncRemote=true` 时同时写入远端最新目录。
 */
export async function applySelectiveDynamics(
  taskId: string,
  payload: SelectiveDynamicsPayload,
): Promise<{
  text: string;
  mode: string;
  numbering: string;
  labels: boolean;
  summary: string;
  local_backup: string | null;
  remote_dir: string | null;
  remote_backup: string | null;
  synced_remote: boolean;
  state: TaskInputState;
}> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/selective-dynamics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/* ============================================================
   输入文件状态（v0.8.2）：远端快照 / 草稿 / 变更台账
   ============================================================ */

export interface TaskInputFileMeta {
  hash?: string | null;
  size?: number;
  /** INCAR：解析出的参数 */
  params?: Record<string, string>;
  /** KPOINTS：k 网格与模式说明 */
  mesh?: number[] | null;
  mesh_note?: string;
  /** POSCAR/CONTCAR：结构摘要 */
  elements?: string[];
  counts?: number[];
  n_atoms?: number;
  lengths?: { a: number; b: number; c: number };
  /** 该文件来自本地 files/（尚未同步过远端） */
  local?: boolean;
}

export interface TaskInputChange {
  file: 'INCAR' | 'KPOINTS';
  key: string;
  from: string;
  to: string;
  at: string;
  applied_at?: string | null;
  applied_in?: string | null;
}

export interface TaskInputSource {
  remote_dir?: string;
  con?: string;
  job_id?: string | null;
  synced_at?: string;
  kind?: string;
}

export interface TaskInputState {
  task_id: string;
  source: TaskInputSource | null;
  synced: boolean;
  files: Record<string, TaskInputFileMeta & { text: string }>;
  draft: {
    INCAR?: Record<string, string>;
    KPOINTS?: { mesh: number[] };
  };
  changes: TaskInputChange[];
  last_applied?: { con: string; at: string; items: TaskInputChange[] } | null;
  pending: boolean;
  poscar_cif: string | null;
  contcar_cif: string | null;
}

/** 读取任务的输入文件状态（快照 + 草稿 + 变更台账） */
export function fetchTaskInput(taskId: string): Promise<TaskInputState> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/input`);
}

/** 同步远端最新计算目录的输入文件（1 次 exec + 4 次小文件下载） */
export function syncTaskInput(taskId: string, kind = 'manual'): Promise<TaskInputState> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/input/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  });
}

/** 保存参数草稿（INCAR 参数 / KPOINTS 网格），下次续算时应用 */
export function saveTaskInputDraft(
  taskId: string,
  payload:
    | { file: 'INCAR'; params: Record<string, string> }
    | { file: 'KPOINTS'; mesh: number[] },
): Promise<TaskInputState> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/input/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 撤销某个文件的参数草稿 */
export function revertTaskInputDraft(taskId: string, file: 'INCAR' | 'KPOINTS'): Promise<TaskInputState> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/input/draft/${file}`, {
    method: 'DELETE',
  });
}

/**
 * 把同一套 INCAR 参数写入多个任务的待生效草稿（「复制到其他作业」）。
 *
 * 逐个任务调用草稿接口（后端按任务各自与「本次计算值」比对生成台账），
 * 单个失败不影响其它任务：返回项里 `state === null` 表示该任务写入失败。
 */
export async function copyIncarParamsToTasks(
  taskIds: string[],
  params: Record<string, string>,
): Promise<{ taskId: string; state: TaskInputState | null }[]> {
  return Promise.all(
    taskIds.map(async (taskId) => {
      try {
        const state = await saveTaskInputDraft(taskId, { file: 'INCAR', params });
        return { taskId, state };
      } catch {
        return { taskId, state: null };
      }
    }),
  );
}

/** PDOS 分析：远端 vaspkit 111/113/115 生成文件并回传本地 */
export async function analyzePdos(
  taskId: string,
  payload: {
    mode: number;
    groups?: { elements: string; orbitals: string }[];
  },
): Promise<{ mode: number; files: string[]; raw: string }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/analysis/pdos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 自由能矫正项：远端 vaspkit 501 计算 Thermal correction to G(T) */
export async function calculateCorrection(
  taskId: string,
  temperature = 298.15,
): Promise<{ correction: number; temperature: number }> {
  return request(`/jobs/tasks/${encodeURIComponent(taskId)}/calculate-correction`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ temperature }),
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
    ele_types: string[];
    params?: Record<string, string | number | boolean>;
  },
): Promise<{
  ele_dir: string;
  source_type: string;
  source_dir: string | null;
  ele_types: string[];
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
    params?: Record<string, string | number | boolean>;
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
