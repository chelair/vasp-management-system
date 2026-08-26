import type { Project, TaskStatus } from '../types';

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
