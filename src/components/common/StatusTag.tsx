import type { CheckStatus, ReportStatus, TaskStatus } from '../../types';
import {
  CHECK_STATUS_LABELS,
  REPORT_STATUS_LABELS,
  TASK_STATUS_LABELS,
} from '../../types';

type Status = TaskStatus | CheckStatus | ReportStatus;

const LABELS: Record<Status, string> = {
  ...TASK_STATUS_LABELS,
  ...CHECK_STATUS_LABELS,
  ...REPORT_STATUS_LABELS,
};

type Kind = 'task' | 'check' | 'report';

/** 按上下文取标签：任务状态（待提交）与巡检状态（未巡检）的 pending 语义不同 */
function labelsFor(kind: Kind): Record<Status, string> {
  if (kind === 'task') return TASK_STATUS_LABELS as Record<Status, string>;
  if (kind === 'check') return CHECK_STATUS_LABELS as Record<Status, string>;
  if (kind === 'report') return REPORT_STATUS_LABELS as Record<Status, string>;
  return LABELS;
}

export default function StatusTag({
  status,
  kind = 'task',
}: {
  status: Status;
  kind?: Kind;
}) {
  const labels = labelsFor(kind);
  return (
    <span className={`status-tag status-tag--${status}`}>
      <span className="status-tag__dot" />
      {labels[status] ?? status}
    </span>
  );
}
