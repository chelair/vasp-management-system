/**
 * 规则的「作用对象 → 具体对象 → 附加条件」映射（v0.9.9）。
 *
 * 用户配置规则时是三级交互，不让用户猜条件字段：
 * 1. 作用对象：项目 / opt 任务 / 自由能组
 * 2. 具体对象：勾选具体的项目 / 任务 / 组（可搜索、可多选）
 * 3. 附加条件：从下拉里选字段与取值（字段带中文名、说明与可选值）
 *
 * 本文件是纯函数（可单测），字段口径与后端 `automation/rules.build_context()` 对齐。
 */

export type RuleTargetType = 'project' | 'opt' | 'neb' | 'free_energy';

export interface RuleTargetOption {
  value: RuleTargetType;
  label: string;
  hint: string;
}

export const RULE_TARGET_OPTIONS: RuleTargetOption[] = [
  { value: 'project', label: '项目', hint: '项目下的所有任务' },
  { value: 'opt', label: 'opt 任务（结构优化）', hint: '只看结构优化任务，可挑具体任务' },
  { value: 'neb', label: 'NEB 任务（路径计算）', hint: '只看 NEB 路径计算任务（neb），可挑具体任务' },
  { value: 'free_energy', label: '自由能组', hint: '只看自由能路径，可挑具体路径组' },
];

/** 项目里的任务（由页面从 /api/projects 摊平后传入） */
export interface TaskRefLite {
  task_id: string;
  model_name: string;
  task_type: string;
  project: string;
  group_id?: string | null;
  group_name?: string | null;
  group_type?: string | null;
}

export interface RuleSelection {
  target: RuleTargetType;
  /** 具体项目（作用对象=项目，可多选） */
  projects: string[];
  /** 具体任务（作用对象=opt 任务） */
  tasks: string[];
  /** 具体组（作用对象=自由能组） */
  groups: string[];
  extra: Record<string, unknown>;
  isSchedule: boolean;
}

/** 单个值原样、多个值给列表（后端两处都支持） */
function oneOrMany(values: string[]): string | string[] | undefined {
  const list = values.filter(Boolean);
  if (list.length === 0) return undefined;
  return list.length === 1 ? list[0] : list;
}

/** 把选择结果转成后端的 condition / scope */
export function selectionToCondition(
  selection: RuleSelection,
  refs: TaskRefLite[] = [],
): { condition: Record<string, unknown>; scope?: string } {
  const { target, projects, tasks, groups, extra, isSchedule } = selection;
  const condition: Record<string, unknown> = {};
  let scopeProjects: string[] = [];

  if (target === 'opt') {
    condition.task_type = 'opt';
    const picked = oneOrMany(tasks);
    if (picked !== undefined) condition.task_id = picked;
    scopeProjects = refs.filter((t) => tasks.includes(t.task_id)).map((t) => t.project);
  } else if (target === 'neb') {
    condition.task_type = 'neb';
    const picked = oneOrMany(tasks);
    if (picked !== undefined) condition.task_id = picked;
    scopeProjects = refs.filter((t) => tasks.includes(t.task_id)).map((t) => t.project);
  } else if (target === 'free_energy') {
    condition.group_type = 'free_energy';
    const picked = oneOrMany(groups);
    if (picked !== undefined) condition.group_id = picked;
    scopeProjects = refs
      .filter((t) => t.group_id && groups.includes(t.group_id))
      .map((t) => t.project);
  } else {
    const picked = oneOrMany(projects);
    if (picked !== undefined) condition.project = picked;
    scopeProjects = projects;
  }

  for (const [key, value] of Object.entries(extra ?? {})) {
    if (value === '' || value === null || value === undefined) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    condition[key] = value;
  }

  if (!isSchedule) return { condition };
  const uniqueProjects = Array.from(new Set(scopeProjects.filter(Boolean)));
  if (uniqueProjects.length === 1 && !condition.project) {
    // 定时 + 只涉及一个项目：用 scope 更直观（列表里能看到项目名）
    return { condition, scope: `project:${uniqueProjects[0]}` };
  }
  return { condition, scope: 'all' };
}

/** 编辑既有规则时，从 condition / trigger 反推三级选择 */
export function conditionToSelection(
  condition: Record<string, unknown> | undefined,
  isSchedule: boolean,
  scope?: string,
): RuleSelection {
  const source = { ...(condition ?? {}) };
  const asList = (value: unknown): string[] => {
    if (Array.isArray(value)) return value.map(String);
    if (value === undefined || value === null || value === '') return [];
    return [String(value)];
  };

  let target: RuleTargetType = 'project';
  let projects: string[] = [];
  let tasks: string[] = [];
  let groups: string[] = [];

  if (source.group_type === 'free_energy') {
    target = 'free_energy';
    delete source.group_type;
  } else if (source.task_type === 'opt') {
    target = 'opt';
    delete source.task_type;
  } else if (source.task_type === 'neb') {
    target = 'neb';
    delete source.task_type;
  }

  if (target === 'free_energy') {
    groups = asList(source.group_id);
    delete source.group_id;
  } else if (target === 'opt' || target === 'neb') {
    tasks = asList(source.task_id);
    delete source.task_id;
  }

  const projectValue = asList(source.project);
  delete source.project;
  if (target === 'project') {
    projects = projectValue;
  } else if (projectValue.length > 0) {
    // 非项目作用对象上的 project 条件放回附加条件（历史规则可能出现）
    source.project = oneOrMany(projectValue);
  }

  if (isSchedule && projects.length === 0 && String(scope || '').startsWith('project:')) {
    projects = [String(scope).slice('project:'.length)];
  }

  return { target, projects, tasks, groups, extra: source, isSchedule };
}

/* ------------------------------------------------------------------ 附加条件字段目录 */

export type ConditionFieldType = 'bool' | 'enum-multi' | 'text';

export interface ConditionField {
  key: string;
  label: string;
  type: ConditionFieldType;
  hint: string;
  options?: { value: string; label: string }[];
}

function boolField(key: string, label: string, hint: string): ConditionField {
  return { key, label, type: 'bool', hint };
}

/** 附加条件可选字段（带中文名与说明；作用对象已覆盖的字段不再重复列出） */
export const CONDITION_FIELDS: ConditionField[] = [
  {
    key: 'status',
    label: '任务状态',
    type: 'enum-multi',
    hint: '只对处于所选状态的任务触发',
    options: [
      { value: 'pending', label: '待提交' },
      { value: 'queued', label: '排队中' },
      { value: 'running', label: '运行中' },
      { value: 'completed', label: '已完成' },
      { value: 'unconverged', label: '未收敛' },
      { value: 'zombied', label: '异常（僵尸）' },
      { value: 'archived', label: '已归档' },
    ],
  },
  {
    key: 'group_role',
    label: '在组里的角色',
    type: 'enum-multi',
    hint: '自由能 / NEB 组内成员的角色',
    options: [
      { value: 'opt', label: '自由能结构优化' },
      { value: 'frac', label: '频率矫正' },
      { value: 'initial_opt', label: 'NEB 初态优化' },
      { value: 'final_opt', label: 'NEB 末态优化' },
      { value: 'neb_images', label: 'NEB 映像计算' },
    ],
  },
  boolField('converged', '是否已收敛', '任务状态为「已完成」时算已收敛'),
  boolField('frac_missing', '缺频率矫正输入', '自由能结构已收敛、frac 还没开始时为「是」'),
  boolField('initial_converged', 'NEB 初态已收敛', '仅 NEB 组任务有值'),
  boolField('final_converged', 'NEB 末态已收敛', '仅 NEB 组任务有值'),
  boolField('images_created', 'NEB 映像文件已创建', '仅 NEB 任务有值'),
  boolField('is_continuation', '是续算子任务', 'conN 目录登记的隐藏子任务'),
  boolField('archived', '已归档', '任务被关闭（归档）'),
  { key: 'model_name', label: '任务名（完全匹配）', type: 'text', hint: '例如 ProjA_opt' },
];

export function findConditionField(key: string): ConditionField | undefined {
  return CONDITION_FIELDS.find((f) => f.key === key);
}

/** 表单值 → 条件值（多选列表、布尔原样、文本去空格） */
export function normalizeConditionValue(key: string, value: unknown): unknown {
  const field = findConditionField(key);
  if (field?.type === 'bool') return value === true || value === 'true';
  if (field?.type === 'enum-multi') {
    const list = Array.isArray(value) ? value.map(String) : value ? [String(value)] : [];
    if (list.length === 0) return undefined;
    return list.length === 1 ? list[0] : list;
  }
  const text = String(value ?? '').trim();
  return text === '' ? undefined : text;
}

/** 条件值 → 表单值（编辑回填） */
export function toFormValue(key: string, value: unknown): unknown {
  const field = findConditionField(key);
  if (field?.type === 'bool') return value === true || value === 'true';
  if (field?.type === 'enum-multi') {
    return Array.isArray(value) ? value.map(String) : value ? [String(value)] : [];
  }
  return value === undefined || value === null ? '' : String(value);
}

/* ------------------------------------------------------------------ 树状结构（具体对象选择用） */

export interface PickerTreeNode {
  value: string;
  title: string;
  selectable: boolean;
  children?: PickerTreeNode[];
}

function sortBy<T>(items: T[], key: (item: T) => string): T[] {
  return [...items].sort((a, b) => key(a).localeCompare(key(b), 'zh-Hans-CN'));
}

/** 按「项目 → 组 或 独立任务 → 任务」组织任务叶子（opt / NEB 共用） */
function buildTaskTree(refs: TaskRefLite[], taskType: string): PickerTreeNode[] {
  const byProject = new Map<string, TaskRefLite[]>();
  for (const ref of refs) {
    if (ref.task_type !== taskType) continue;
    const list = byProject.get(ref.project) ?? [];
    list.push(ref);
    byProject.set(ref.project, list);
  }
  const tree: PickerTreeNode[] = [];
  for (const [project, tasks] of sortBy(Array.from(byProject.entries()), ([name]) => name)) {
    const byGroup = new Map<string, { title: string; tasks: TaskRefLite[] }>();
    for (const task of tasks) {
      const key = task.group_id || `__solo__:${project}`;
      const title = task.group_id ? task.group_name || task.group_id : '独立任务';
      const bucket = byGroup.get(key) ?? { title, tasks: [] };
      bucket.tasks.push(task);
      byGroup.set(key, bucket);
    }
    tree.push({
      value: `p:${project}`,
      title: project,
      selectable: false,
      children: sortBy(Array.from(byGroup.entries()), ([, bucket]) => bucket.title).map(([key, bucket]) => ({
        value: `g:${project}:${key}`,
        title: `${bucket.title}（${bucket.tasks.length}）`,
        selectable: false,
        children: sortBy(bucket.tasks, (task) => task.model_name).map((task) => ({
          value: task.task_id,
          title: task.model_name,
          selectable: true,
        })),
      })),
    });
  }
  return tree;
}

/**
 * opt 任务的树：项目 → （自由能/NEB 组 或 独立任务）→ 任务叶子。
 * 任务多的时候用 TreeSelect + 搜索就不会乱。
 */
export function buildOptTaskTree(refs: TaskRefLite[]): PickerTreeNode[] {
  return buildTaskTree(refs, 'opt');
}

/** NEB 路径计算任务的树：项目 → NEB 组 → NEB 任务叶子（v0.9.15） */
export function buildNebTaskTree(refs: TaskRefLite[]): PickerTreeNode[] {
  return buildTaskTree(refs, 'neb');
}

/** 自由能组的树：项目 → 路径组（叶子） */
export function buildFreeEnergyGroupTree(refs: TaskRefLite[]): PickerTreeNode[] {
  const byProject = new Map<string, Map<string, { name: string; count: number }>>();
  for (const ref of refs) {
    if (ref.group_type !== 'free_energy' || !ref.group_id) continue;
    const groups = byProject.get(ref.project) ?? new Map();
    const entry = groups.get(ref.group_id) ?? { name: ref.group_name || ref.group_id, count: 0 };
    entry.count += ref.task_type === 'opt' ? 1 : 0;
    groups.set(ref.group_id, entry);
    byProject.set(ref.project, groups);
  }
  const tree: PickerTreeNode[] = [];
  for (const [project, groups] of sortBy(Array.from(byProject.entries()), ([name]) => name)) {
    tree.push({
      value: `p:${project}`,
      title: project,
      selectable: false,
      children: sortBy(Array.from(groups.entries()), ([, entry]) => entry.name).map(([groupId, entry]) => ({
        value: groupId,
        title: entry.count > 0 ? `${entry.name}（${entry.count} 个结构）` : entry.name,
        selectable: true,
      })),
    });
  }
  return tree;
}
