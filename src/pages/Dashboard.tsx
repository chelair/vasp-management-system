import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  App,
  Popconfirm,
  Skeleton,
  Table,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  deleteProject,
  fetchDashboardMeta,
  fetchProjects,
  fetchWeeklyTrend,
} from '../api/projects';
import AddProjectModal from '../components/projects/AddProjectModal';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import ProgressBar from '../components/common/ProgressBar';
import StatCard from '../components/common/StatCard';
import StatusTag from '../components/common/StatusTag';
import TrendChart from '../components/common/TrendChart';
import type {
  DashboardMeta,
  Project,
  Task,
  TaskStatus,
  TrendPoint,
} from '../types';
import { TASK_TYPE_LABELS } from '../types';
import { projectStatus } from '../utils/project';

interface RecentRow extends Task {
  projectName: string;
}

export default function Dashboard() {
  const { message } = App.useApp();
  const [projects, setProjects] = useState<Project[]>([]);
  const [meta, setMeta] = useState<DashboardMeta | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    Promise.all([
      fetchProjects(),
      fetchDashboardMeta(),
      fetchWeeklyTrend(),
    ])
      .then(([p, m, t]) => {
        setProjects(p);
        setMeta(m);
        setTrend(t);
      })
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const allTasks = projects.flatMap((p) => p.tasks);
    const running = allTasks.filter((t) => t.status === 'running').length;
    const queued = allTasks.filter((t) => t.status === 'queued').length;
    return {
      projects: projects.length,
      running,
      queued,
      todayCompleted: meta?.todayCompleted ?? 0,
      anomalies: meta?.anomalyCount ?? 0,
    };
  }, [projects, meta]);

  const recentTasks = useMemo<RecentRow[]>(() => {
    const rows = projects.flatMap((p) =>
      p.tasks.map((t) => ({ ...t, projectName: p.name })),
    );
    return rows
      .sort((a, b) => {
        const ta = a.last_check_time ?? '';
        const tb = b.last_check_time ?? '';
        return tb.localeCompare(ta);
      })
      .slice(0, 6);
  }, [projects]);

  const recentColumns: ColumnsType<RecentRow> = [
    {
      title: '任务',
      key: 'task',
      render: (_, row) => (
        <div>
          <div className="cell-strong">{row.model_name}</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            {TASK_TYPE_LABELS[row.task_type]}
          </div>
        </div>
      ),
    },
    { title: '所属项目', dataIndex: 'projectName', key: 'projectName', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: TaskStatus) => <StatusTag status={s} />,
    },
    {
      title: '最近能量 (eV)',
      dataIndex: 'last_energy',
      key: 'last_energy',
      width: 130,
      render: (v: number | null) =>
        v == null ? <span style={{ color: 'var(--color-text-muted)' }}>—</span> : v.toFixed(4),
    },
    {
      title: '作业号',
      dataIndex: 'job_id',
      key: 'job_id',
      width: 110,
      render: (v: string | null) =>
        v ? <span className="path-cell">{v}</span> : <span style={{ color: 'var(--color-text-muted)' }}>—</span>,
    },
    {
      title: '最近巡检',
      dataIndex: 'last_check_time',
      key: 'last_check_time',
      width: 150,
      render: (v: string | null) => v ?? '—',
    },
  ];

  const openAdd = () => setAddOpen(true);

  const handleProjectCreated = async () => {
    const fresh = await fetchProjects();
    setProjects(fresh);
  };

  const handleProjectDeleted = async (p: Project) => {
    try {
      const result = await deleteProject(p.id);
      message.success(
        `项目 ${result.project_name} 已删除` +
          (result.local_trash ? `（本地目录已移入回收站）` : ''),
      );
      const fresh = await fetchProjects();
      setProjects(fresh);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除项目失败');
    }
  };

  return (
    <PageTransition>
      <PageHeader
        title="总览"
        subtitle="查看所有项目进度与计算资源概况"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={openAdd}
          >
            新增项目
          </Button>
        }
      />

      {loading ? (
        <Card>
          <Skeleton active paragraph={{ rows: 8 }} />
        </Card>
      ) : (
        <>
          <div className="stats-grid">
            <StatCard
              label="项目总数"
              value={stats.projects}
              icon={<FolderOpenOutlined />}
              accent="blue"
              trend="本月新增 2 个"
              delay={0}
            />
            <StatCard
              label="运行中任务"
              value={stats.running}
              icon={<ThunderboltOutlined />}
              accent="teal"
              trend={`另有 ${stats.queued} 个排队中`}
              delay={0.06}
            />
            <StatCard
              label="今日完成"
              value={stats.todayCompleted}
              icon={<CheckCircleOutlined />}
              accent="green"
              trend="较昨日 +3"
              delay={0.12}
            />
            <StatCard
              label="异常 / 警告项"
              value={stats.anomalies}
              icon={<WarningOutlined />}
              accent="orange"
              trend="需人工关注"
              delay={0.18}
            />
          </div>

          <div className="dashboard-grid">
            <Card title="项目进度总览" styles={{ body: { paddingTop: 6, paddingBottom: 6 } }}>
              <div className="project-progress-list">
                {projects.map((p) => (
                  <div key={p.id} className="project-progress-row">
                    <div className="project-progress-row__name" title={p.name}>
                      {p.name}
                    </div>
                    <StatusTag status={projectStatus(p)} />
                    <ProgressBar value={p.progress} showText />
                    <div className="project-progress-row__time">
                      {p.remainingHours > 0 ? `剩余约 ${p.remainingHours}h` : '已完成'}
                    </div>
                    <Popconfirm
                      title={`删除项目 ${p.name}？`}
                      description="本地目录将移入回收站，远端文件不受影响"
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      cancelText="取消"
                      onConfirm={() => handleProjectDeleted(p)}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={`删除项目 ${p.name}`}
                      />
                    </Popconfirm>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="运行中任务趋势（近 7 天）">
              <TrendChart data={trend} />
            </Card>
          </div>

          <Card className="mt-16" title="最近更新的任务">
            <Table
              rowKey="task_id"
              dataSource={recentTasks}
              columns={recentColumns}
              pagination={false}
              size="middle"
            />
          </Card>
        </>
      )}

      <AddProjectModal
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onCreated={handleProjectCreated}
      />
    </PageTransition>
  );
}
