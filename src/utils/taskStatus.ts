import type { Task } from '../types';

/** Archiving does not discard the convergence status of an optimization. */
export function isCompletedOptimization(task: Pick<Task, 'task_type' | 'status' | 'archived_from'>): boolean {
  return task.task_type === 'opt' && (task.status === 'completed' ||
    (task.status === 'archived' && task.archived_from === 'completed'));
}
