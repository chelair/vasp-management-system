import type { Project, TaskCheckSummary, TaskStatus } from '../types';

/** 由子任务状态推导项目级状态（展示用） */
export function projectStatus(p: Project): TaskStatus {
  if (p.tasks.some((t) => t.status === 'zombied')) return 'zombied';
  if (p.tasks.some((t) => t.status === 'unconverged')) return 'unconverged';
  if (p.tasks.every((t) => t.status === 'completed' || t.status === 'archived')) {
    return 'completed';
  }
  if (p.tasks.some((t) => t.status === 'running')) return 'running';
  if (p.tasks.some((t) => t.status === 'queued')) return 'queued';
  return 'pending';
}

/** 子项展示排序：running → zombied → completed → queued → pending → archived */
const STATUS_ORDER: Record<TaskStatus, number> = {
  running: 0,
  zombied: 1,
  unconverged: 2,
  completed: 3,
  queued: 4,
  pending: 5,
  archived: 6,
};

export function sortTasksByStatus<T extends { status: TaskStatus }>(tasks: T[]): T[] {
  return [...tasks].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  );
}

/**
 * 任务状态的"关注度"（数字越小越需要先看）：
 * 出错(红) > 未收敛(黄) > 运行中(蓝) > 排队(青) > 待提交(灰) > 已完成(绿) > 已归档。
 */
export const TASK_STATUS_SEVERITY: Record<TaskStatus, number> = {
  zombied: 0,
  unconverged: 1,
  running: 2,
  queued: 3,
  pending: 4,
  completed: 5,
  archived: 6,
};

/**
 * 组状态：自由能结构是「结构优化 + 频率矫正」两个任务、NEB 组是多个映像任务，
 * 展示时取成员里**优先级最高**（最需要关注）的那个状态 —— 红 > 黄 > 灰 > 归档。
 */
export function pickGroupStatus<T extends { status: TaskStatus }>(
  tasks: T[],
): TaskStatus | null {
  if (!tasks.length) return null;
  return [...tasks].sort(
    (a, b) =>
      (TASK_STATUS_SEVERITY[a.status] ?? 9) - (TASK_STATUS_SEVERITY[b.status] ?? 9),
  )[0].status;
}

/**
 * 组内"最需要关注的巡检结论"：错误 > 警告 > 其它（未巡检/正常）。
 * 用于任务树/作业概览显示与巡检中心一致的提示（低精度收敛、力未收敛等）。
 */
export function pickGroupCheck<T extends { check?: TaskCheckSummary | null }>(
  tasks: T[],
): TaskCheckSummary | null {
  const rank = (c?: TaskCheckSummary | null) =>
    !c || !c.has_inspection ? 3 : c.status === 'error' ? 0 : c.status === 'warning' ? 1 : 2;
  const withCheck = tasks.filter((t) => t.check?.has_inspection);
  if (!withCheck.length) return null;
  return [...withCheck].sort((a, b) => rank(a.check) - rank(b.check))[0].check ?? null;
}

/** 巡检结论是否需要提醒（警告/错误） */
export function checkNeedsAttention(check?: TaskCheckSummary | null): boolean {
  return !!check && (check.status === 'warning' || check.status === 'error');
}

/** 结构标签显示：struct_01 → 结构1（目录为 ASCII，界面显示中文） */
export function formatStructureLabel(label: string): string {
  const m = /^struct_(\d+)$/.exec(label);
  return m ? `结构${parseInt(m[1], 10)}` : label;
}

/** 任务类型 → 顶层分类目录（ASCII） */
export const CATEGORY_DIR_LABELS: Record<string, string> = {
  opt: 'opt',
  frac: 'free_energy',
  neb: 'neb',
  ele: 'ele',
};
