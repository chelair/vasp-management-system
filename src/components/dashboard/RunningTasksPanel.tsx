import { Card, Empty, Skeleton, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import type { DashboardJob } from '../../types';

interface Props {
  jobs: DashboardJob[];
  loading?: boolean;
  highlight?: boolean;
}

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  RUN: { label: '运行中', color: 'green' },
  PEND: { label: '排队中', color: 'orange' },
  SSUSP: { label: '系统挂起', color: 'red' },
  USUSP: { label: '用户挂起', color: 'red' },
  PSUSP: { label: '排队挂起', color: 'volcano' },
};

export default function RunningTasksPanel({ jobs, loading, highlight }: Props) {
  const navigate = useNavigate();

  const columns: ColumnsType<DashboardJob> = [
    {
      title: '任务名称',
      key: 'task',
      render: (_, row) => (
        <div>
          <div className="cell-strong">{row.task_name}</div>
          {row.job_name && row.job_name !== row.task_name && (
            <div className="dashboard-sub">{row.job_name}</div>
          )}
        </div>
      ),
    },
    {
      title: '所属项目',
      dataIndex: 'project_name',
      key: 'project_name',
      ellipsis: true,
      render: (v: string) => (
        <span className={v === '未登记任务' ? 'dashboard-muted' : undefined}>{v}</span>
      ),
    },
    {
      title: '队列',
      dataIndex: 'queue',
      key: 'queue',
      width: 140,
      render: (v: string) => <span className="path-cell">{v || '—'}</span>,
    },
    {
      title: '核数',
      dataIndex: 'cores',
      key: 'cores',
      width: 92,
      align: 'right',
      render: (v: number, row) => {
        if (!v) return <span className="dashboard-muted">待调度</span>;
        const hosts = row.execHosts.map((h) => `${h.host}×${h.cores}`).join(' + ');
        return (
          <Tooltip title={hosts || undefined}>
            <span className="dashboard-cores">{v}</span>
          </Tooltip>
        );
      },
    },
    {
      title: '作业号',
      dataIndex: 'job_id',
      key: 'job_id',
      width: 100,
      render: (v: string) => <span className="path-cell">{v}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const style = STATUS_STYLE[v] ?? { label: v, color: 'default' };
        return (
          <Tag color={style.color} bordered={false}>
            {style.label}
          </Tag>
        );
      },
    },
  ];

  const running = jobs.filter((j) => j.status === 'RUN').length;
  const pending = jobs.filter((j) => j.status === 'PEND').length;

  return (
    <Card
      id="running-tasks"
      className={`dashboard-card${highlight ? ' dashboard-card--highlight' : ''}`}
      title="运行中的任务"
      extra={
        <span className="dashboard-sub">
          运行 {running} · 排队 {pending}
        </span>
      }
    >
      {loading && jobs.length === 0 ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : jobs.length === 0 ? (
        <Empty description="当前没有作业在运行或排队" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          rowKey="job_id"
          dataSource={jobs}
          columns={columns}
          pagination={false}
          size="small"
          // 固定高度 + 内部滚动：作业变多时模块不再被撑高
          scroll={{ x: 'max-content', y: 320 }}
          onRow={(row) => ({
            onClick: () => {
              if (!row.task_id) return;
              navigate(`/jobs?task=${encodeURIComponent(row.task_id)}`);
            },
            style: { cursor: row.task_id ? 'pointer' : 'default' },
          })}
        />
      )}
      {jobs.length > 0 && (
        <div className="dashboard-note">
          点击任意行跳转到该任务的作业管理详情；核数为 LSF 分配的槽位数（slots）。
        </div>
      )}
    </Card>
  );
}
