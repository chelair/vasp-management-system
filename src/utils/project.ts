import type { Project, TaskStatus } from '../types';

/** 由子任务状态推导项目级状态（展示用） */
export function projectStatus(p: Project): TaskStatus {
  if (p.tasks.some((t) => t.status === 'zombied')) return 'zombied';
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
  completed: 2,
  queued: 3,
  pending: 4,
  archived: 5,
};

export function sortTasksByStatus<T extends { status: TaskStatus }>(tasks: T[]): T[] {
  return [...tasks].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  );
}
