/**
 * 全局类型定义。
 * 字段命名与现有 Python 后端（project_db.json / schemas.py）对齐，
 * 后续接入真实 API 时只需替换 src/api/ 下的数据来源。
 */

/** 任务状态：与 scripts/project_db.py 的 STATUS_ENUM 一致 */
export type TaskStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'completed'
  | 'zombied'
  | 'archived';

/** 任务类型：与 config/task_registry.json 一致 */
export type TaskType =
  | 'structure_opt'
  | 'electronic_structure'
  | 'free_energy'
  | 'frequency'
  | 'neb';

export type Workload = 'small' | 'medium' | 'large';

export interface Task {
  task_id: string;
  task_type: TaskType;
  model_name: string;
  status: TaskStatus;
  last_energy: number | null;
  last_check_time: string | null;
  job_id: string | null;
  notes: string;
  continuation_ready: boolean;
  continuation_dir: string | null;
  remote_dir: string;
  /** 前端展示用本地目录，后端接入后由配置/接口提供 */
  local_dir: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  deadline: string;
  workload: Workload;
  server: string;
  progress: number;
  remainingHours: number;
  createdAt: string;
  updatedAt: string;
  tasks: Task[];
}

export type CheckStatus = 'normal' | 'warning' | 'error';

export type CheckCategory = 'convergence' | 'resource' | 'file' | 'ssh' | 'queue';

export interface InspectionResult {
  id: string;
  check_time: string;
  project_name: string;
  task_id: string;
  task_name: string;
  category: CheckCategory;
  status: CheckStatus;
  message: string;
  detail: string;
  /** 是否在结构分析范围内（巡检前后状态有变化或运行中） */
  analysis_needed?: boolean;
  has_force_history?: boolean;
}

export interface ForceHistoryPoint {
  step: number;
  energy: number | null;
  max_force: number | null;
}

export interface LatticeParams {
  a: number;
  b: number;
  c: number;
  alpha: number;
  beta: number;
  gamma: number;
  volume: number;
}

export interface StructureAnalysis {
  in_scope: boolean;
  steps: number | null;
  files: { poscar: boolean; contcar: boolean };
  /** 优化模式：ISIF 值（本地 INCAR 缺失时按 VASP 默认 2） */
  isif: number | null;
  isif_source: 'incar' | 'default' | null;
  /** ISIF 0/1/2：晶格固定，仅离子弛豫 */
  cell_fixed: boolean;
  poscar: LatticeParams | null;
  contcar: LatticeParams | null;
  deltas: {
    a_pct: number | null;
    b_pct: number | null;
    c_pct: number | null;
    volume_pct: number | null;
  } | null;
  /** 原子位移（ISIF=2 晶格固定时替代晶格对比） */
  displacements: {
    count: number;
    max: number;
    rms: number;
    mean: number;
  } | null;
  images: {
    poscar: Record<string, string>;
    contcar: Record<string, string>;
  };
  skipped: string | null;
  warnings: string[];
}

export interface InspectionDetail {
  task_id: string;
  project_name: string;
  model_name: string;
  task_type: string;
  status: string;
  check_time: string | null;
  queue_status: string | null;
  last_energy: number | null;
  force_max: number | null;
  force_rms: number | null;
  force_converged: boolean | null;
  force_history: ForceHistoryPoint[];
  errors: string[];
  notes: string;
  analysis: StructureAnalysis | null;
}

export type ReportStatus = 'completed' | 'generating' | 'failed';

export interface RiskItem {
  level: 'high' | 'medium' | 'low';
  content: string;
}

export interface ReportRecord {
  id: string;
  title: string;
  generated_at: string;
  status: ReportStatus;
  summary: string;
  risks: RiskItem[];
  suggestions: string[];
}

export interface DashboardMeta {
  todayCompleted: number;
  anomalyCount: number;
}

export interface TrendPoint {
  date: string;
  value: number;
}

/** SSH 服务器认证方式 */
export type AuthType = 'password' | 'key';

/** 队列系统 */
export type QueueSystem = 'lsf' | 'slurm' | 'pbs' | 'other';

/**
 * SSH 服务器配置。
 * 字段对齐现有后端 config/servers.json 的 server1 配置，
 * 并补充前端展示所需字段（connected / latencyMs / lastTestAt）。
 */
export interface ServerConfig {
  id: string;
  name: string;
  host: string;
  port: number;
  user: string;
  authType: AuthType;
  /** 私钥路径（authType=key 时使用） */
  keyPath?: string;
  /** 密码（authType=password 时使用；仅演示，正式版由后端保管） */
  password?: string;
  /** 用户主目录 */
  home?: string;
  queueSystem: QueueSystem | string;
  /** 远程项目基础目录 */
  remoteBase?: string;
  /** 当前是否已连接（同一时间仅一个服务器处于连接状态） */
  connected: boolean;
  latencyMs?: number | null;
  lastTestAt?: string | null;
}

export interface ConnectionTestResult {
  ok: boolean;
  latencyMs: number;
  message: string;
}

/** 后端 /api/servers 返回的服务器选项 */
export interface ServerOption {
  name: string;
  host: string;
  port: number;
  user: string;
  queue_system: string;
  home: string | null;
  remote_base: string | null;
}

/** 后端 /api/task-types 返回的任务类型选项 */
export interface TaskTypeOption {
  type: TaskType;
  description: string;
  workload_weight: number;
}

/** 新增项目请求体（字段与后端 add_project 规则对齐） */
export interface CreateProjectPayload {
  name: string;
  deadline: string;
  server: string;
  tasks: { task_type: TaskType; model_name: string }[];
  description?: string;
  estimated_hours?: number | null;
}

export interface CreateProjectResult {
  project_id: string;
  priority_quadrant: string;
  urgency: string;
  workload: string;
  remote_base: string;
}

/** 状态/类别中文文案映射（集中维护，页面复用） */
export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  pending: '待提交',
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  zombied: '异常',
  archived: '已归档',
};

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  structure_opt: '结构优化',
  electronic_structure: '电子结构',
  free_energy: '自由能',
  frequency: '频率计算',
  neb: 'NEB 过渡态',
};

export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = {
  normal: '正常',
  warning: '警告',
  error: '错误',
};

export const CHECK_CATEGORY_LABELS: Record<CheckCategory, string> = {
  convergence: '收敛性',
  resource: '资源',
  file: '文件',
  ssh: 'SSH 连接',
  queue: '队列',
};

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  completed: '已完成',
  generating: '生成中',
  failed: '失败',
};
