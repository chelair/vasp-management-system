import { Button, Card, Empty, Skeleton, Tooltip } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { DashboardRiskAlert, DashboardRiskSummary } from '../../types';

interface Props {
  summary: DashboardRiskSummary | null;
  loading?: boolean;
  onInspect?: () => void;
  inspecting?: boolean;
}

const TYPE_LABELS: Record<string, string> = {
  opt: '结构优化',
  frac: '频率矫正',
  neb: 'NEB',
  ele: '电子结构',
};

export default function RiskAlertsPanel({
  summary,
  loading,
  onInspect,
  inspecting,
}: Props) {
  const navigate = useNavigate();
  const alerts = summary?.alerts ?? [];
  const visible = alerts.slice(0, 6);

  const open = (alert: DashboardRiskAlert) => {
    if (alert.kind === 'inspection') {
      navigate('/inspection');
      return;
    }
    navigate(`/jobs?task=${encodeURIComponent(alert.task_id)}`);
  };

  return (
    <Card
      className="dashboard-card"
      title="任务健康与风险预警"
      extra={
        <div className="risk-head">
          {summary?.lastInspectionAt && (
            <Tooltip title={`上次巡检：${summary.lastInspectionAt}`}>
              <span className="dashboard-sub">
                上次巡检 {summary.lastInspectionAt.replace('T', ' ').slice(5, 16)}
              </span>
            </Tooltip>
          )}
          <Button size="small" onClick={() => navigate('/inspection')}>
            巡检中心
          </Button>
        </div>
      }
    >
      {loading && !summary ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : alerts.length === 0 ? (
        <Empty description="没有需要干预的任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div className="risk-summary">
            <span className="dashboard-badge dashboard-badge--error">
              严重 {summary?.errorCount ?? 0}
            </span>
            <span className="dashboard-badge dashboard-badge--warning">
              警告 {summary?.warningCount ?? 0}
            </span>
            {onInspect && (
              <Button
                size="small"
                type="primary"
                ghost
                loading={inspecting}
                onClick={onInspect}
              >
                立即巡检
              </Button>
            )}
          </div>
          <div className="risk-list">
            {visible.map((alert) => (
              <button
                key={`${alert.task_id}-${alert.kind}`}
                type="button"
                className={`risk-item risk-item--${alert.severity}`}
                onClick={() => open(alert)}
              >
                <span className={`risk-item__dot risk-item__dot--${alert.severity}`} />
                <span className="risk-item__main">
                  <span className="risk-item__title">{alert.title}</span>
                  <span className="risk-item__meta">
                    {alert.project_name} · {alert.task_name}
                    {alert.task_type ? ` · ${TYPE_LABELS[alert.task_type] ?? alert.task_type}` : ''}
                  </span>
                  <span className="risk-item__reason">{alert.reason}</span>
                </span>
                <span className="risk-item__action">{alert.action} ›</span>
              </button>
            ))}
          </div>
          {alerts.length > visible.length && (
            <div className="dashboard-note">
              还有 {alerts.length - visible.length} 条未展示，点击「巡检中心」查看完整列表。
            </div>
          )}
        </>
      )}
    </Card>
  );
}
