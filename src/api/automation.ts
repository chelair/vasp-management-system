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
  trigger: { type: string; cron?: string; scope?: string };
  condition: Record<string, unknown>;
  action: string;
  guard: { cooldown_seconds?: number; max_runs_per_task?: number };
  failures?: number;
}

export interface AutomationSchedule {
  id: string;
  enabled: boolean;
  cron: string;
  scope: string;
  action: string;
  description?: string;
  guard?: Record<string, unknown>;
  next_run_at?: string | null;
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
