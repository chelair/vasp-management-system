/** 项目托管计划数据访问层：只读写计划/优先级/资源规则，不触发提交。 */
import { request } from './client';

export interface ManagedGoal {
  text: string;
  summary?: string;
}

export interface ManagedStage {
  stage_id: string;
  title: string;
  task_ids: string[];
  due?: string;
  timezone?: string;
  priority: number;
  source_quote?: string;
  reason?: string;
}

export interface ManagedTaskOverride {
  priority: number;
  locked: boolean;
  reason?: string;
  source?: 'human' | 'ai';
  updated_at?: string;
}

export interface ManagedResourceRules {
  queues_allowed: string[];
  queues_denied: string[];
  paid_allowed: boolean;
  max_nodes: number;
  max_cores: number;
  cores_per_node: number;
  max_walltime_hours: number;
  max_core_hours: number;
  max_submissions: number;
  soft_kill: boolean;
}

export interface ManagedPlan {
  id: string;
  project: string;
  server: string;
  owner: string;
  status: 'active' | 'paused' | 'ended';
  goal: ManagedGoal;
  stages: ManagedStage[];
  task_overrides: Record<string, ManagedTaskOverride>;
  resource_rules: ManagedResourceRules;
  revision: number;
  history?: Array<{ at: string; by: string; source: string; action: string; detail: string }>;
  created_at: string;
  updated_at: string;
}

export interface ManagedCandidate {
  task_id: string;
  task_name: string;
  task_type: string;
  status: string;
  intent: 'first_submit' | 'continuation' | 'in_flight' | 'waiting_upstream';
  action: 'task.submit' | 'task.continuation' | null;
  priority: number;
  priority_source: 'override' | 'stage' | 'default';
  locked: boolean;
  stage_id?: string;
  stage_title?: string;
  due?: string;
  due_epoch?: number | null;
  order: number;
  reason: string;
}

export interface ManagedSummary {
  plan_id?: string;
  project?: string;
  status?: string;
  revision?: number;
  goal?: ManagedGoal;
  counts?: Record<string, number>;
  next?: ManagedCandidate | null;
  waiting?: ManagedCandidate[];
  needs_user?: string[];
  candidates?: ManagedCandidate[];
  error?: string;
}

export interface ManagedPlanItem {
  plan: ManagedPlan;
  summary: ManagedSummary;
}

export interface ResourceCandidate {
  queue: string;
  paid: boolean;
  suspend_risk?: string;
  cores: number;
  cores_per_node: number;
  nodes: number;
  walltime_hours: number;
  core_hours: number;
  score: number;
  components: Record<string, number>;
  notes: string[];
  explain: string[];
}

export interface ServerQueue {
  queue: string;
  cores_per_node: number;
  walltime_hours: number;
  paid: boolean;
  suspend_risk?: string;
  nodes: number;
}

export interface ResourcePlanResult {
  state: 'ok' | 'waiting' | 'blocked';
  reason: string;
  rules?: Partial<ManagedResourceRules>;
  server_queues?: ServerQueue[];
  snapshot?: { ok?: boolean; reason?: string; ageSeconds?: number; queriedAt?: string };
  candidates: ResourceCandidate[];
  filtered?: Array<{ queue: string; reason: string }>;
  heuristic?: string;
  notes?: string[];
}

export interface ScriptPreview {
  state?: string;
  reason?: string;
  script?: string;
  candidate?: ResourceCandidate;
  issues?: string[];
  written: boolean;
}

export async function fetchManagedPlans() {
  return request<{ plans: ManagedPlanItem[]; execution_enabled: boolean }>('/managed');
}

export async function createManagedPlan(payload: {
  project: string;
  goal: ManagedGoal;
  stages?: Omit<ManagedStage, 'stage_id' | 'timezone'>[];
  resource_rules?: Partial<ManagedResourceRules>;
}) {
  return request<ManagedPlanItem>('/managed/plans', { method: 'POST', body: JSON.stringify(payload) });
}

export async function patchManagedPlan(
  planId: string,
  revision: number,
  changes: Record<string, unknown>,
) {
  return request<ManagedPlanItem>(`/managed/plans/${planId}`, {
    method: 'PATCH',
    body: JSON.stringify({ revision, ...changes }),
  });
}

export async function setManagedStatus(planId: string, status: 'active' | 'paused' | 'ended') {
  return request<ManagedPlanItem>(`/managed/plans/${planId}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
}

export async function fetchResourcePlan(planId: string) {
  return request<ResourcePlanResult>(`/managed/plans/${planId}/resource-plan`);
}

export async function fetchScriptPreview(planId: string, index = 0) {
  return request<ScriptPreview>(`/managed/plans/${planId}/script-preview?index=${index}`);
}
