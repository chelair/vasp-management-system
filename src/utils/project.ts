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
