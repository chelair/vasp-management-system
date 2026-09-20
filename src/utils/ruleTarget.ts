/**
 * 规则的「作用对象」↔ condition / scope 映射（v0.9.8）。
 *
 * 用户配置规则时先选"针对什么"，而不是直接填条件字段；这里做纯函数转换，
 * 供弹窗使用、也便于单测。字段含义与后端 `automation/rules.build_context()` 对齐：
 * - 项目：不额外限定任务类型（可选再用"指定项目"锁定某个项目）
 * - opt 任务：`condition.task_type = "opt"`
 * - 自由能组：`condition.group_type = "free_energy"`
 */

export type RuleTargetType = 'project' | 'opt' | 'free_energy';

export interface RuleTargetOption {
  value: RuleTargetType;
  label: string;
  hint: string;
}

export const RULE_TARGET_OPTIONS: RuleTargetOption[] = [
  { value: 'project', label: '项目', hint: '项目下的所有任务' },
  { value: 'opt', label: 'opt 任务（结构优化）', hint: '只看结构优化任务' },
  { value: 'free_energy', label: '自由能组', hint: '只看自由能路径里的任务（含 frac 子任务）' },
];

/** 作用对象 → 条件里的固定字段（其余条件放在"附加条件"里） */
export function targetCondition(target: RuleTargetType): Record<string, unknown> {
  if (target === 'opt') return { task_type: 'opt' };
  if (target === 'free_energy') return { group_type: 'free_energy' };
  return {};
}

/**
 * 组装最终 condition / scope。
 *
 * @param target      作用对象
 * @param projectName 指定项目（空 = 全部项目）
 * @param extra       附加条件（高级）
 * @param isSchedule  定时规则：指定项目走 `scope=project:<名>`；条件规则走 `condition.project`
 */
export function buildRuleCondition(
  target: RuleTargetType,
  projectName: string | undefined,
  extra: Record<string, unknown>,
  isSchedule: boolean,
): { condition: Record<string, unknown>; scope?: string } {
  const condition: Record<string, unknown> = { ...targetCondition(target) };
  if (projectName && !isSchedule) {
    condition.project = projectName;
  }
  for (const [key, value] of Object.entries(extra ?? {})) {
    if (value === '' || value === null || value === undefined) continue;
    condition[key] = value;
  }
  if (!isSchedule) return { condition };
  return { condition, scope: projectName ? `project:${projectName}` : 'all' };
}

/** 从已有规则的 condition 反推"作用对象"与附加条件（编辑时回填） */
export function inferRuleTarget(condition: Record<string, unknown> | undefined): {
  target: RuleTargetType;
  project?: string;
  extra: Record<string, unknown>;
} {
  const source = { ...(condition ?? {}) };
  let target: RuleTargetType = 'project';
  if (source.group_type === 'free_energy') {
    target = 'free_energy';
    delete source.group_type;
  } else if (source.task_type === 'opt') {
    target = 'opt';
    delete source.task_type;
  }
  const project = typeof source.project === 'string' ? source.project : undefined;
  delete source.project;
  return { target, project, extra: source };
}
