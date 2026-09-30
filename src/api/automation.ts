/** 自动化与统一动作接口（v0.9.6，全部接口仅 admin 可用）。 */
import { request } from './client';

export interface AutomationSettings {
  enabled: boolean;
  dry_run: boolean;
  schedules_enabled: boolean;
  disabled_rules?: string[];
  failure_threshold?: number;
}

export interface AutomationRule {
  id: string;
  enabled: boolean;
  description?: string;
  trigger: {
    type: string;
    /** 定时子类型：cron 周期 / after（N 秒后执行一次） */
    mode?: 'cron' | 'after' | string;
    cron?: string;
    after_seconds?: number;
    scope?: string;
  };
  condition: Record<string, unknown>;
  action: string;
  guard: { cooldown_seconds?: number; max_runs_per_task?: number };
  /** 主动作成功后接着执行的动作（例如续算成功后自动提交作业） */
  follow_up_action?: string | null;
  failures?: number;
  /** 已运行次数 / 单任务执行上限（计数口径与调度层一致） */
  progress?: RuleProgress;
}

/** 单个目标任务在这条规则下的累计执行次数 */
export interface RuleProgressTarget {
  task_id: string;
  /** 项目 · 任务名（前端 tooltip 用） */
  label: string;
  count: number;
  /** 接力动作（如 task.submit）在该任务上的累计次数 */
  follow_up_count?: number;
  /** 当前是否满足完整条件（含 status 等）；false 只表示"现在不会跑"，计数照样算 */
  matched: boolean;
  /** 未命中原因（仅 matched=false 时返回） */
  reason?: string;
}

/**
 * 规则当前进度：目标任务里"用得最多"的已运行次数 + 上限。
 *
 * 「单任务执行上限」是**累计值**、按 `任务|动作` 分开计，接力动作各算一份，
 * 所以这里既有主动作的 max_count，也有接力的 max_follow_up_count。
 */
export interface RuleProgress {
  action: string;
  follow_up_action?: string | null;
  /** 0 = 不限制（界面显示成 ∞） */
  limit: number;
  max_count: number;
  max_follow_up_count?: number | null;
  /** 当前命中条件的目标任务数（targets 只回传前 20 个） */
  target_count: number;
  targets: RuleProgressTarget[];
}

export interface AutomationSchedule {
  id: string;
  enabled: boolean;
  /** cron = 按表达式周期；after = N 秒后执行一次（一次性） */
  mode?: 'cron' | 'after' | string;
  cron: string;
  after_seconds?: number | null;
  last_fired_at?: string | null;
  scope: string;
  action: string;
  description?: string;
  guard?: Record<string, unknown>;
  next_run_at?: string | null;
  progress?: RuleProgress;
}

export interface AutomationDecision {
  at: string;
  status: 'success' | 'failed' | 'skipped' | 'blocked' | 'dry_run' | string;
  action: string;
  task_id?: string;
  project?: string;
  trigger?: string;
  trigger_id?: string;
  rule_id?: string;
  reason?: string;
  elapsed_ms?: number;
}

export interface AutomationRun {
  run_id: string;
  action: string;
  task_id?: string;
  status: string;
  started_at?: string;
  finished_at?: string | null;
  reason?: string;
  result?: unknown;
}

export interface ActionCatalogItem {
  name: string;
  label: string;
  description: string;
  long_running: boolean;
  params_help?: Record<string, string>;
}

export function fetchAutomationStatus(): Promise<{
  settings: AutomationSettings;
  schedules: AutomationSchedule[];
  rules: AutomationRule[];
  counts: Record<string, number>;
  last_results: Record<string, unknown>;
}> {
  return request('/automation/status');
}

export function saveAutomationSettings(
  patch: Partial<AutomationSettings>,
): Promise<AutomationSettings> {
  return request('/automation/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export function setAutomationRuleEnabled(id: string, enabled: boolean): Promise<AutomationRule> {
  return request(`/automation/rules/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}

/** 新建规则（写 data/config/rules/<id>.json，立即生效） */
export function createAutomationRule(rule: Partial<AutomationRule>): Promise<AutomationRule> {
  return request('/automation/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rule),
  });
}

/** 修改规则（可改 description/trigger/condition/action/guard/enabled/follow_up_action） */
export function updateAutomationRule(
  id: string,
  patch: Partial<AutomationRule>,
): Promise<AutomationRule> {
  return request(`/automation/rules/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

/** 删除规则 */
export function deleteAutomationRule(id: string): Promise<{ id: string }> {
  return request(`/automation/rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/**
 * 重置这条规则**目标任务的执行次数与冷却**（「单任务执行上限」撑满后用它放行）。
 * 同时清掉该规则的连续失败计数与熔断标记。
 */
export function resetAutomationRuleRuns(id: string): Promise<{
  rule_id: string;
  action: string;
  /** 被清零的动作（主动作 + 接力动作） */
  actions: string[];
  task_count: number;
  tasks: string[];
  cleared: { counts: number; cooldowns: number; last_results: number };
  /** 重置后的「已运行 / 上限」（前端直接用来刷新徽标） */
  progress?: RuleProgress;
}> {
  return request(`/automation/rules/${encodeURIComponent(id)}/reset-runs`, { method: 'POST' });
}

export function runAutomationRule(id: string): Promise<{ rule_id: string }> {
  return request(`/automation/rules/${encodeURIComponent(id)}/run`, { method: 'POST' });
}

export function reloadAutomation(): Promise<{ rules: number }> {
  return request('/automation/reload', { method: 'POST' });
}

export function fetchAutomationDecisions(limit = 100): Promise<{ decisions: AutomationDecision[] }> {
  return request(`/automation/decisions?limit=${limit}`);
}

export function fetchAutomationRuns(limit = 50): Promise<{ runs: AutomationRun[] }> {
  return request(`/automation/runs?limit=${limit}`);
}

export function fetchActionCatalog(): Promise<{ actions: ActionCatalogItem[] }> {
  return request('/actions');
}

export interface ActionResult {
  status: string;
  result?: unknown;
  run_id?: string;
  reason?: string;
  audit_id?: string;
  preflight?: unknown;
  preflight_ok?: boolean;
  will_do?: string | null;
}

/** 统一动作入口（dry_run=true 只跑 preflight） */
export function runAction(
  name: string,
  payload: {
    task_id?: string;
    params?: Record<string, unknown>;
    dry_run?: boolean;
    idempotency_key?: string;
    wait?: boolean;
  },
): Promise<ActionResult> {
  return request(`/actions/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function fetchActionRun(runId: string): Promise<AutomationRun> {
  return request(`/actions/runs/${encodeURIComponent(runId)}`);
}
