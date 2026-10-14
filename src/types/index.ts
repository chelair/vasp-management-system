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
  | 'unconverged'
  | 'zombied'
  | 'archived';

/** 任务类型：固定四种（v0.3.0），流程通过 group 元数据组织 */
export type TaskType = 'opt' | 'frac' | 'neb' | 'ele' | 'ele_diff';

/** ele 类型的后处理子类型 */
export type EleSubtype = 'pdos' | 'bader' | 'diff_charge' | 'work_function';

/** 计算流程组元数据（任务字段 group） */
export interface GroupMeta {
  /** 组名（组根目录名，如 PATH1） */
  name?: string;
  group_id: string;
  group_type: 'free_energy' | 'neb';
  group_role:
    | 'main_structure'
    | 'aux_molecule'
    | 'initial_opt'
    | 'final_opt'
    | 'neb_images';
  structure_label: string;
}

/** 输入来源追踪 */
export interface InputSource {
  poscar_from?: string | null;
  potcar_from?: string | null;
  kpoints_from?: string | null;
}

export type Workload = 'small' | 'medium' | 'large';

/** 最近一次巡检结论（与巡检中心同一口径；未巡检为 null） */
export interface TaskCheckSummary {
  status: Exclude<CheckStatus, 'pending'>;
  message: string;
  checked_at?: string | null;
  energy?: number | null;
  has_inspection?: boolean;
}

export interface Task {
  task_id: string;
  task_type: TaskType;
  subtype?: EleSubtype | null;
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
  /** 任务本地目录绝对路径（dir_path 权威字段） */
  dir_path?: string;
  /** 归档（关闭）：归档时间与归档前状态，重新打开时恢复 */
  archived_at?: string | null;
  archived_from?: string | null;
  /** 自由能组主任务对应的频率矫正子任务（归档时会一并归档） */
  frac_sibling?: {
    task_id: string;
    model_name: string;
    status: TaskStatus;
  } | null;
  /**
   * 最近一次巡检结论：`低精度收敛`、`计算完成但力未收敛` 这类提示只存在于巡检结果里
   * （数据库状态可能仍是 completed），作业管理页据此显示与巡检中心一致的告警。
   */
  check?: TaskCheckSummary | null;
  /** 所属计算流程组（独立任务为 null） */
  group?: GroupMeta | null;
  parent_task_id?: string | null;
  input_source?: InputSource | null;
  /** 差分电荷分块计算（`task_type=ele_diff`）：块序号 / 块名 / 该块原子（POSCAR 序号 1 起） */
  ele_block?: number | null;
  ele_block_label?: string | null;
  ele_block_atoms?: number[];
  diff_charge_group?: string | null;
  /** 本地文件布局：`flat` = 文件直接放任务目录（差分电荷分块），缺省 `<任务>/files/` */
  local_layout?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface Project {
  id: string;
  name: string;
  /** 项目归属用户名（第 3 步：新建项目自动记当前登录用户；过滤留待第 4 步） */
  owner?: string | null;
  description: string;
  deadline: string;
  /** 项目计算内容描述（报告"基本信息"章节用；可空） */
  calc_description?: string;
  /** 预期结果（报告"基本信息"章节用；可空） */
  expected_results?: string;
  workload: Workload;
  /** 优先级：算出来的（紧急度 × 工作量），只读 */
  urgency?: string;
  priority_quadrant?: string;
  server: string;
  remote_base?: string;
  progress: number;
  remainingHours: number;
  /** 项目已关闭（全部可见任务归档后可关闭）：展示上排到最后并折叠 */
  closed?: boolean;
  closedAt?: string | null;
  createdAt: string;
  updatedAt: string;
  tasks: Task[];
}

export type CheckStatus = 'normal' | 'warning' | 'error' | 'pending' | 'archived';

export type CheckCategory = 'convergence' | 'resource' | 'file' | 'ssh' | 'queue';

export interface InspectionResult {
  id: string;
  check_time: string;
  project_name: string;
  task_id: string;
  task_name: string;
  /** 自由能路径组名称（如 PATH1），非自由能任务为空 */
  group_name?: string;
  /** 组 ID（自由能/NEB），用于路径看板等聚合 */
  group_id?: string;
  /** 组内结构标签（如 1、2），自由能行用于排序 */
  structure_label?: string;
  category: CheckCategory;
  status: CheckStatus;
  message: string;
  detail: string;
  /** 是否在结构分析范围内（巡检前后状态有变化或运行中） */
  analysis_needed?: boolean;
  has_force_history?: boolean;
  /** 是否已有过至少一次巡检记录（false 时操作列显示“单独巡检”） */
  has_inspection?: boolean;
  /** 本次巡检相对上次状态有变化（前端用于详情红点提醒） */
  status_changed?: boolean;
  /** 最新输出目录（续算 conN 优先，无则为 null=主目录） */
  latest_dir?: string | null;
  /** 最新输出状态：finished / running / failed / waiting */
  output_status?: 'finished' | 'running' | 'failed' | 'waiting' | null;
  /** 任务类型分类（结构优化 / 自由能 / NEB / 电子结构） */
  task_category?: string;
  /** 任务在 projects.json 中的真实状态（归档判断用：archived = 已关闭） */
  task_status?: TaskStatus;
  /** 所属项目是否已关闭（关闭项目在列表中排最后并默认折叠） */
  project_closed?: boolean;
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

/** 自由能组结构优化详情中合并展示的频率矫正子任务数据 */
export interface InspectionFracDetail {
  task_id: string;
  task_name: string;
  status: string;
  has_inspection: boolean;
  check_time: string | null;
  last_energy: number | null;
  errors: string[];
  notes: string;
  queue_status: string | null;
  current_output: CurrentOutput | null;
  /** 自由能矫正项（vaspkit 501 计算，eV） */
  correction?: number | null;
}

/** 差分电荷分块：巡检详情里挂在 ele 主任务后面的表格（2026-10-13） */
export interface InspectionDiffChargeBlock {
  task_id: string;
  task_name: string;
  /** 分块序号（1 起，对应远端目录 / 本地 diffcharge_files/<N>/） */
  block: number;
  block_label: string | null;
  atoms_count: number;
  status: string;
  has_inspection: boolean;
  check_time: string | null;
  last_energy: number | null;
  force_max: number | null;
  queue_status: string | null;
  errors: string[];
  notes: string;
  current_output: CurrentOutput | null;
}

export interface InspectionDiffChargeDetail {
  group_id: string | null;
  block_count: number;
  /**
   * 差分电荷结果（2026-10-14 口径）：远端用 VTST chgsum.pl + chgdiff.pl 算好后
   * 只回传一个 `CHGCAR_diff`，本地落 `diffcharge_files/chgfiles/CHGCAR_diff.vasp`。
   * 未归档 / 未计算时为 null；计算失败时 `ok=false` 且带 `error`。
   */
  charge_diff: {
    ok: boolean;
    block_count?: number;
    remote_path?: string;
    remote_sum?: string;
    local_path?: string;
    dir?: string;
    bytes?: number;
    elapsed_seconds?: number;
    vtst_dir?: string;
    error?: string;
    synced_at?: string;
  } | null;
  blocks: InspectionDiffChargeBlock[];
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
  /** vasp2cif 生成的结构 CIF 文本（3Dmol 结构视图用），未生成时为 null */
  poscar_cif?: string | null;
  contcar_cif?: string | null;
  /** NEB 映像分析（v0.6.9）：优化后的 IS → 中间态 → FS 结构（各映像一张 CIF） */
  neb_images?: {
    label: string;
    /** is = 初态、fs = 末态、middle = 中间态 */
    role: 'is' | 'fs' | 'middle';
    cif: string;
    energy: number | null;
    relative: number | null;
    max_force: number | null;
  }[];
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
  /** 力收敛阈值（结构优化取自 INCAR 的 EDIFFG；缺失/正值时退回 registry 默认 0.02/0.01） */
  force_thresholds?: {
    max_force_threshold: number;
    rms_force_threshold: number;
    /** `incar:EDIFFG` = 按 INCAR 判；`registry` = 用默认阈值 */
    source: string;
  } | null;
  force_history: ForceHistoryPoint[];
  errors: string[];
  /** OUTCAR 报错诊断（巡检知识库）：命中条目含名称/分类/解释/解决方法/原文证据 */
  check_errors?: {
    id: string;
    name: string;
    kind?: string;
    severity?: string;
    category?: string;
    message?: string;
    advice?: string[];
    matched?: string;
    evidence?: string;
    /** NEB：报错来自哪个映像 */
    image?: string;
  }[];
  /** 知识库未收录时报错原文（兜底提取） */
  error_text?: string | null;
  notes: string;
  current_output: CurrentOutput | null;
  /** 自由能组 opt 任务关联的频率矫正子任务数据（无则为 null） */
  frac?: InspectionFracDetail | null;
  /** 电子结构任务：差分电荷分块（列表不单独展示，详情里用表格呈现） */
  diff_charge?: InspectionDiffChargeDetail | null;
  /** 电子结构任务可分析内容识别（对应输出文件存在且非空） */
  available_analyses?: {
    pdos: boolean;
    bader: boolean;
    cohp: boolean;
    work_function: boolean;
    diff_charge: boolean;
  } | null;
  /** NEB 过渡态：nebef.pl 输出（受力/能量/相对能垒） */
  neb_barrier?: {
    images: {
      label: string;
      max_force: number | null;
      energy: number | null;
      relative: number | null;
    }[];
  } | null;
  analysis: StructureAnalysis | null;
}

export type ReportStatus = 'completed' | 'generating' | 'failed';

/* ---------------- 项目报告（v0.7.0 重构） ---------------- */

/** 报告列表项（后端 index.json 的一条） */
export interface ProjectReportMeta {
  report_id: string;
  project_id: string;
  project_name: string;
  generated_at: string;
  time_window: { start?: string; end?: string; label?: string };
  schema_version: string;
  project_status: 'normal' | 'warning' | 'critical';
  summary: string;
  risk_summary: { high?: number; medium?: number; low?: number; total?: number };
  completion_percent: number | null;
  chart_count: number;
  json_path: string;
  markdown_path: string;
  directory: string;
}

/** 报告章节（key + 标题 + 该章 Markdown） */
export interface ProjectReportSection {
  key: string;
  title: string;
  markdown: string;
}

export interface ProjectReportDetail {
  meta: ProjectReportMeta;
  schema_version: string;
  markdown: string;
  markdown_sections: ProjectReportSection[];
  /** 结构三视图弹窗（点「结构 N / 映像 N」打开；图片按报告目录解析） */
  dialogs: ProjectReportDialog[];
  /** 报告注解：key = task_id 或 section_<章节key> */
  notes: Record<string, ReportNote>;
  /** 按任务块聚合的注解：label（= markdown 里 #### 标题）→ 若干条目 */
  note_blocks: Record<string, ReportNoteEntry[]>;
  /** 前端隐藏状态（章节/元素），持久化在 data/reports/edits/<report_id>.json */
  edits?: { hidden_sections: string[]; hidden_elements: string[] };
  sections: { key: string; title: string }[];
  charts: { name?: string; path: string }[] | string[];
  /** 结构化数据（字段随 schema 版本演进，前端按需读取） */
  structured: Record<string, unknown>;
}

export interface ReportNote {
  analysis_note: string;
  paper_note: string;
  updated_at?: string;
}

export interface ReportNoteEntry extends ReportNote {
  /** 多条目时的子标签（如「结构 1」）；单任务块为空串 */
  label: string;
}

export interface ProjectReportDialogRow {
  /** 行标签，如「优化后（CONTCAR）」 */
  label: string;
  /** a/b/c → 报告目录下的相对路径（images/xxx.png） */
  views: Record<string, string>;
}

export interface ProjectReportDialog {
  id: string;
  title: string;
  rows: ProjectReportDialogRow[];
}

export interface ProjectReportGenerateResult {
  reports: ProjectReportMeta[];
  failed: { project: string; error: string }[];
}

export interface RiskItem {
  level: 'high' | 'medium' | 'low';
  content: string;
}


/* ---------------- 总览（Dashboard 重构版） ---------------- */

/** LSF 作业行：bjobs 实时查询结果 + 本地任务元数据映射 */
export interface DashboardJob {
  job_id: string;
  /** 集群上的作业名（LSF JOB_NAME） */
  job_name: string;
  /** 匹配到的本地任务（未登记时为 null） */
  task_id: string | null;
  task_name: string;
  task_type: TaskType | null;
  project_name: string;
  queue: string;
  cores: number;
  /** RUN / PEND / SSUSP / USUSP / PSUSP */
  status: string;
  execHosts: { cores: number; host: string }[];
}

/** 核数占用（blimits 配额 + bjobs 汇总，按项目分组） */
export interface DashboardCoresUsage {
  usedCores: number;
  totalCores: number | null;
  remainingCores: number | null;
  usedPercent: number | null;
  level: 'normal' | 'warning' | 'critical';
  limitSource: string;
  runningJobs: number;
  summedJobCores: number;
  queues: string[];
  byProject: { project_name: string; cores: number }[];
  queriedAt?: string | null;
  source?: string;
  error?: string | null;
}

export interface DashboardNodeStats {
  total: number;
  ok: number;
  full: number;
  closed: number;
  down: number;
  totalCores: number;
  runningCores: number;
  idleCores: number;
}

export interface DashboardQueueRow {
  queue: string;
  pending: number;
  running: number;
  suspended: number;
  status: string;
}

export interface DashboardStorage {
  filesystem: string;
  size: string;
  used: string;
  available: string;
  usedPercent: number;
  mountedOn: string;
  warning: boolean;
}

export interface DashboardClusterHealth {
  nodes: DashboardNodeStats | null;
  queues: DashboardQueueRow[];
  queueTotals: { pending: number; running: number; queues: number };
  storage: DashboardStorage | null;
  queriedAt?: string | null;
  source?: string;
  error?: string | null;
  cached?: boolean;
  cacheAgeSeconds?: number;
  stale?: boolean;
}

export interface DashboardRiskAlert {
  task_id: string;
  task_name: string;
  task_type: string;
  project_name: string;
  status: string;
  kind: string;
  severity: 'error' | 'warning';
  title: string;
  reason: string;
  action: string;
  last_check_time?: string | null;
  remote_dir?: string | null;
}

export interface DashboardRiskSummary {
  alerts: DashboardRiskAlert[];
  errorCount: number;
  warningCount: number;
  lastInspectionAt: string | null;
  lastInspectionInspected?: number;
  lastInspectionUpdated?: number;
}

export interface DashboardProjectProgress {
  project_id: string;
  project_name: string;
  deadline: string;
  daysLeft: number | null;
  overdue: boolean;
  totalTasks: number;
  visibleTasks: number;
  continuationTasks: number;
  completed: number;
  /** 已关闭（归档）任务数 */
  archived: number;
  /** 全部可见任务都已归档 → 可以关闭项目 */
  closable: boolean;
  /** 项目是否已关闭 */
  closed: boolean;
  running: number;
  queued: number;
  anomalies: number;
  progress: number;
  timeRatio: number | null;
  workload: string;
}

export interface DashboardTrendPoint {
  date: string;
  label: string;
  usedCores: number | null;
  runningTasks: number | null;
  submissions: number;
}

export interface DashboardTrend {
  points: DashboardTrendPoint[];
  since: string | null;
  sampleCount: number;
  note: string;
  days?: number;
}

export interface DashboardStats {
  projects: number;
  projectsThisMonth: number;
  running: number;
  queued: number;
  /** 集群查询未返回时为 null（前端显示"—"，不要显示成 0） */
  runningJobs: number | null;
  pendingJobs: number | null;
  todayCompleted: number;
  yesterdayCompleted: number;
  completedDelta: number;
  anomalies: number;
  errorCount: number;
  warningCount: number;
  totalTasks: number;
}

export interface DashboardClusterMeta {
  /** true = 这一次响应没有查集群（前端据此显示"加载中/查询失败"，不要假装 0） */
  pending?: boolean;
  source: string;
  error: string | null;
  queriedAt: string | null;
  cached?: boolean;
  cacheAgeSeconds?: number;
  stale?: boolean;
}

export interface DashboardOverview {
  generatedAt: string;
  server: string;
  stats: DashboardStats;
  runningTasks: DashboardJob[];
  /** `cluster=0`（只取本地聚合）时为 null —— 集群部分单独加载 */
  coresUsage: DashboardCoresUsage | null;
  clusterHealth: DashboardClusterHealth | null;
  riskAlerts: DashboardRiskSummary;
  projectProgress: DashboardProjectProgress[];
  recentTasks: DashboardRecentTask[];
  trend: DashboardTrend;
  cluster: DashboardClusterMeta;
}

/** 最近更新的任务（总览明细表） */
export interface DashboardRecentTask {
  task_id: string;
  task_name: string;
  task_type: TaskType;
  project_name: string;
  status: TaskStatus;
  last_energy: number | null;
  job_id: string | null;
  last_check_time: string | null;
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
  /** 仅频率矫正（frac）任务显示与使用；其他任务类型不展示、不进默认参数 */
  fracOnly?: boolean;
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
  bhostRaw?: string;
  bqueuesRaw?: string;
  /** 采集元信息（v0.8.7：与总览页共用同一份采集缓存） */
  cached?: boolean;
  /** 采集失败但有旧数据时为 true（数据仍是真实采集，只是过期） */
  stale?: boolean;
  /** 距上次成功采集的秒数 */
  cacheAgeSeconds?: number;
  /** 采集缓存 TTL（秒），前端据此显示「缓存 N 分钟」 */
  cacheTtlSeconds?: number;
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
  /** 本次计算（远端同步）实际使用的参数，用于"已修改"对比与取消回滚 */
  snapshotParams?: Record<string, string>;
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
  subtype?: EleSubtype | null;
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
  /** 所属项目是否已关闭（已关闭项目的作业在选择列表里折叠到最后） */
  projectClosed?: boolean;
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
  subtypes?: string[];
  subtype_labels?: Record<string, string>;
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
  unconverged: '未收敛',
  zombied: '异常',
  archived: '已归档',
};

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  opt: '结构优化',
  frac: '频率矫正',
  neb: 'NEB 过渡态',
  ele: '电子结构',
  ele_diff: '差分电荷分块',
};

export const ELE_SUBTYPE_LABELS: Record<EleSubtype, string> = {
  pdos: 'PDOS',
  bader: 'Bader 分析',
  diff_charge: '差分电荷',
  work_function: '功函数',
};

export const GROUP_ROLE_LABELS: Record<GroupMeta['group_role'], string> = {
  main_structure: '主结构',
  aux_molecule: '辅助分子',
  initial_opt: '初态优化',
  final_opt: '末态优化',
  neb_images: 'NEB 映像',
};

export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = {
  normal: '正常',
  warning: '警告',
  error: '错误',
  pending: '待提交',
  archived: '关闭',
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

/* ---------------- PDOS 分析（2026-10-13 重建链路） ---------------- */

/** 曲线：id → 数值（`grid` 指向 energy.total / energy.partial 两条能量轴） */
export interface PdosSeries {
  grid: 'total' | 'partial';
  values: number[];
}

/** 菜单树里的曲线描述（自旋极化时 up/down 各一条） */
export interface PdosCurve {
  id: string;
  spin: 'up' | 'down' | 'total';
  label: string;
  color: string;
}

/** 轨道选择菜单节点：一级总态密度 / 二级元素×轨道 / 三级 p、d 方向 */
export interface PdosTreeNode {
  key: string;
  label: string;
  level: 1 | 2 | 3;
  /** false = 只做分组，不给勾选框（元素节点） */
  checkable?: boolean;
  color?: string;
  curves?: PdosCurve[];
  children?: PdosTreeNode[];
}

export interface PdosMeta {
  task_id?: string | null;
  run_id?: string | null;
  generated_at?: string;
  efermi?: number | null;
  spin_polarized?: boolean;
  elements?: string[];
  points?: number;
  partial_points?: number;
  has_projection?: boolean;
  has_fine_orbitals?: boolean;
  notes?: string[];
  source?: string;
  status?: string;
  error?: string | null;
  finished_at?: string | null;
}

/** `GET /api/jobs/tasks/{id}/pdos` 的返回 */
export interface PdosView {
  meta: PdosMeta;
  energy: { total: number[]; partial: number[] };
  tree: PdosTreeNode[];
  series: Record<string, PdosSeries>;
}

/**
 * Bader 电荷链路（2026-10-14）：入口在巡检详情的「电子结构分析 → Bader」标签。
 * 远端算（chgsum.pl AECCAR0+AECCAR2 → CHGCAR_sum，再 bader CHGCAR -ref CHGCAR_sum）
 * → 回传 ACF.dat → 本地解析。净电荷（要 POTCAR ZVAL）/ 分组 / 图表属于下一轮分析链路。
 */
export interface BaderAtom {
  index: number;
  x: number;
  y: number;
  z: number;
  /** Bader 体积内的电荷（电子数） */
  charge: number;
  /** 到最近 Bader 表面的距离（Å） */
  min_dist?: number | null;
  /** 原子体积（Å³，新版权才写这一列） */
  atomic_vol?: number | null;
  /** 元素（由本地 POSCAR 的元素行展开而来；算不出净电荷时可能没有） */
  element?: string;
  /** 该元素的价电子数 ZVAL（POTCAR TITEL/ZVAL 两行解析） */
  zval?: number;
  /** 净电荷 Δq = ZVAL − charge（正=失电子；没有 ZVAL 时为 null） */
  net_charge?: number | null;
}

/** 逐原子净电荷的整体统计（后端算好，报告/面板都能用） */
export interface BaderStats {
  n_atoms: number;
  charge_total: number;
  zval_total: number;
  net_total: number;
  net_mean: number;
  net_max: { value: number; index: number; element: string };
  net_min: { value: number; index: number; element: string };
}

/** `GET /api/jobs/tasks/{id}/bader` 的返回（ACF.dat 解析结果） */
export interface BaderData {
  n_atoms: number;
  atoms: BaderAtom[];
  total_charge: number;
  n_electrons?: number | null;
  vacuum_charge?: number | null;
  vacuum_volume?: number | null;
  has_atomic_vol: boolean;
  has_min_dist: boolean;
  /** 逐原子元素序列（长度 = n_atoms） */
  elements?: string[];
  /** 元素 → ZVAL */
  zval?: Record<string, number>;
  /** 能不能算净电荷（缺本地 POSCAR / 远端 POTCAR 时为 false） */
  net_charge_available?: boolean;
  net_charge_reason?: string;
  stats?: BaderStats;
  source: string;
  bytes: number;
  mtime: number;
  meta?: {
    elapsed_seconds?: number;
    result?: {
      sum_reused?: boolean;
      bader_exe?: string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}

/** 远端探测（`status?remote=1`） */
export interface BaderRemote {
  state?: string;
  reason?: string;
  remote_dir?: string;
  ok?: boolean;
  sizes?: Record<string, number>;
  integrity?: ChargeDiffIntegrity | null;
  tools?: Record<string, boolean>;
  has_sum?: boolean;
  has_remote_acf?: boolean;
  bader_exe?: string;
  checked_at?: string;
}

/** `GET /api/jobs/tasks/{id}/bader/status` 的返回 */
export interface BaderStatus {
  run_id?: string;
  status: 'idle' | 'running' | 'done' | 'failed';
  stage?: string;
  stage_label?: string;
  error?: string | null;
  elapsed_seconds?: number;
  finished_at?: string | null;
  local: {
    has_acf: boolean;
    acf_path?: string;
    acf_bytes?: number;
    acf_mtime?: number;
  };
  remote?: BaderRemote;
  result?: Record<string, unknown>;
  meta?: Record<string, unknown>;
}

/**
 * 差分电荷链路（2026-10-14）：入口在巡检详情的「电子结构分析 → 差分电荷」标签。
 * 状态取值阶梯：本地图 → 本地差分文件 → 远端差分文件 → 远端可算（见 backend/charge_diff.py）。
 */
export interface ChargeDiffIntegrity {
  ok: boolean;
  missing?: string[];
  max?: number;
  min?: number;
  spread?: number | null;
  reason?: string;
}

/** 远端探测结果（`status?remote=1`） */
export interface ChargeDiffRemote {
  state?: string;
  reason?: string;
  remote_dir?: string;
  block_count?: number;
  has_diff?: boolean;
  has_sum?: boolean;
  integrity?: ChargeDiffIntegrity | null;
  vtst?: { dir?: string; ready?: boolean; scripts?: Record<string, boolean> };
  checked_at?: string;
}

/** 本地阶梯（零 SSH：图 / 差分文件都在不在） */
export interface ChargeDiffLocal {
  state?: string;
  has_images: boolean;
  has_partial_images?: boolean;
  image_axes?: string[];
  has_diff: boolean;
  diff_path?: string;
  diff_bytes?: number;
  diff_mtime?: number;
  image_mtime?: number;
  blocks?: number | null;
}

/** 写回 `task.charge_diff` 的链路结果（报告 / 巡检详情共用） */
export interface ChargeDiffRecord {
  ok: boolean;
  block_count?: number;
  bytes?: number;
  elapsed_seconds?: number;
  render_seconds?: number;
  remote_path?: string;
  remote_sum?: string;
  local_path?: string;
  dir?: string;
  images?: Record<string, string>;
  reused_remote?: boolean;
  stage?: string;
  error?: string;
  synced_at?: string;
}

/** `GET /api/jobs/tasks/{id}/charge-diff/status` 的返回 */
export interface ChargeDiffStatus {
  run_id?: string;
  status: 'idle' | 'running' | 'done' | 'failed';
  stage?: string;
  stage_label?: string;
  error?: string | null;
  elapsed_seconds?: number;
  bytes_done?: number;
  bytes_total?: number;
  finished_at?: string | null;
  /** 阶梯取值（没传 remote=1 时只按本地；传了就是"本地 → 远端"的结果） */
  state?: string;
  local: ChargeDiffLocal;
  remote?: ChargeDiffRemote;
  charge_diff?: ChargeDiffRecord | null;
  meta?: Record<string, unknown>;
}

/** `GET .../pdos/status` 的返回 */
export interface PdosStatus {
  run_id?: string;
  status: 'idle' | 'running' | 'done' | 'failed';
  error?: string | null;
  finished_at?: string | null;
  has_data?: boolean;
  meta?: PdosMeta;
}
