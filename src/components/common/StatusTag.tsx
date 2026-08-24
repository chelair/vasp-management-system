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

export default function StatusTag({ status }: { status: Status }) {
  return (
    <span className={`status-tag status-tag--${status}`}>
      <span className="status-tag__dot" />
      {LABELS[status] ?? status}
    </span>
  );
}
