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
  /** 最新输出定位（续算 conN 优先，巡检后回填） */
  current_output?: CurrentOutput | null;
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
  /** 最新输出目录（续算 conN 优先，无则为 null=主目录） */
  latest_dir?: string | null;
  /** 最新输出状态：finished / running / failed / waiting */
  output_status?: 'finished' | 'running' | 'failed' | 'waiting' | null;
}

/** 任务最新输出定位（续算 conN 优先） */
export interface CurrentOutput {
  latest_dir: string | null;
  dir: string;
  contcar_path: string;
  outcar_path: string;
  oszicar_path: string;
  status: 'finished' | 'running' | 'failed' | 'waiting';
  reason: string;
  is_continuation: boolean;
  is_latest_con: boolean;
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
  current_output: CurrentOutput | null;
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

/* ============================================================
   作业管理模块类型
   ============================================================ */

/** INCAR 参数值类型 */
export type IncarValueType = 'bool' | 'enum' | 'number' | 'string';

/** 枚举参数选项 */
export interface IncarOption {
  value: string;
  label: string;
  hint?: string;
}

/** 单个 INCAR 参数定义 */
export interface IncarParamDef {
  key: string;
  label: string;
  type: IncarValueType;
  unit?: string;
  hint?: string;
  options?: IncarOption[];
  placeholder?: string;
  defaultValue: string;
}

/** INCAR 参数分类 */
export interface IncarCategory {
  key: string;
  label: string;
  params: IncarParamDef[];
}

/** 精度档位 */
export type PrecisionMode = 'low' | 'medium' | 'high' | 'custom';

export const PRECISION_LABELS: Record<PrecisionMode, string> = {
  low: '低精度',
  medium: '中精度',
  high: '高精度',
  custom: '自定义',
};

/** INCAR 预设 */
export interface IncarPreset {
  id: string;
  name: string;
  params: Record<string, string>;
  /** 内置模板（不可删除） */
  builtin?: boolean;
  createdAt?: string;
}

/** 提交脚本格式 */
export type ScriptFormat = 'lsf' | 'slurm';

export const SCRIPT_FORMAT_LABELS: Record<ScriptFormat, string> = {
  lsf: 'LSF (bsub)',
  slurm: 'Slurm (sbatch)',
};

export const NODE_STATUS_LABELS: Record<NodeStatus, string> = {
  ok: '正常',
  warning: '较忙',
  busy: '满载',
  closed: '关闭',
  unavail: '不可用',
};

export const SUSPEND_RISK_LABELS: Record<SuspendRisk, string> = {
  low: '低',
  medium: '中',
  high: '高',
};

/** 集群节点运行状态 */
export type NodeStatus = 'ok' | 'warning' | 'busy' | 'closed' | 'unavail';

/** 挂起风险等级 */
export type SuspendRisk = 'low' | 'medium' | 'high';

/** 集群节点（bhost 主数据 + node_groups 映射） */
export interface ClusterNode {
  name: string;
  /** 所属队列（node_groups 映射） */
  queue: string;
  /** 单节点最大核数 */
  maxCores: number;
  /** 运行中核数（bhost RUN） */
  runningCores: number;
  /** 挂起核数（bhost SSUSP） */
  suspendedCores: number;
  /** 不可用核数（bhost UNAVAIL） */
  unavailCores: number;
  /** 空闲核数 = MAX - RUN - SSUSP - UNAVAIL */
  idleCores: number;
  status: NodeStatus;
  cpuModel: string;
  cpuFreq: string;
  walltime: string;
  suspendRisk: SuspendRisk;
  paid: boolean;
  price: number;
}

/** 队列级汇总（node_groups 映射 + bqueues 补充） */
export interface ClusterQueueSummary {
  queue: string;
  walltime: string;
  coresPerNode: number;
  cpuModel: string;
  cpuFreq: string;
  suspendRisk: SuspendRisk;
  paid: boolean;
  price: number;
  nodeCount: number;
  totalCores: number;
  runningCores: number;
  idleCores: number;
  busyPercent: number;
  /** bqueues 补充信息（无数据时为空对象） */
  bqueues?: Record<string, number | string>;
}

/** 集群快照（GET /api/jobs/nodes） */
export interface ClusterSnapshot {
  source: 'real' | 'mock';
  error?: string | null;
  queriedAt: string;
  nodes: ClusterNode[];
  queues: ClusterQueueSummary[];
  bhost_raw?: string;
  bqueues_raw?: string;
}

/** 队列/分区选项 */
export interface QueueOption {
  value: string;
  label: string;
  hint?: string;
}

/** 提交脚本生成参数 */
export interface SubmitScriptOptions {
  format: ScriptFormat;
  jobName: string;
  queue: string;
  cores: number;
  remoteDir: string;
}

/** POSCAR 解析结果（晶格信息） */
export interface PoscarInfo {
  comment: string;
  scale: number;
  lattice: number[][];
  elements: string[];
  counts: number[];
  coordMode: string;
  lengths: { a: number; b: number; c: number };
  angles: { alpha: number; beta: number; gamma: number };
  volume: number;
}

/** VASP 任务文件清单项 */
export interface VaspTaskFile {
  name: string;
  kind: 'input' | 'output' | 'script';
  present: boolean;
  note?: string;
}

/** 单任务的前端工作区（文件内容 / INCAR 参数，后续由后端落盘） */
export interface JobWorkspace {
  incarParams: Record<string, string>;
  precision: PrecisionMode;
  poscarContent: string | null;
  poscarPath: string | null;
  kpointsContent: string | null;
  files: Record<string, boolean>;
  scriptFormat: ScriptFormat;
}

/** 新建子项请求 */
export interface NewTaskPayload {
  modelName: string;
  taskType: TaskType;
  localDir: string;
  remoteDir: string;
}

/** 续算创建结果 */
export interface ContinuationPayload {
  name: string;
  taskType: TaskType;
  localDir: string;
  remoteDir: string;
  ops: string[];
  crossType: boolean;
}

/** 复制参数目标任务引用 */
export interface TaskRef {
  projectId: string;
  projectName: string;
  taskId: string;
  taskName: string;
  taskType: TaskType;
  status: TaskStatus;
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
