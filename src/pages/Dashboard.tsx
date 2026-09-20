import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Card, Skeleton, Table, Tooltip } from 'antd';
import { useAuth } from '../context/AuthContext';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  CloudSyncOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { closeProject, deleteProject, reopenProject } from '../api/projects';
import { fetchDashboardOverview } from '../api/dashboard';
import { runInspection } from '../api/inspections';
import AddProjectModal from '../components/projects/AddProjectModal';
import ClusterHealthPanel from '../components/dashboard/ClusterHealthPanel';
import CoresUsagePanel from '../components/dashboard/CoresUsagePanel';
import ProjectProgressPanel from '../components/dashboard/ProjectProgressPanel';
import RiskAlertsPanel from '../components/dashboard/RiskAlertsPanel';
import RunningTasksPanel from '../components/dashboard/RunningTasksPanel';
import TrendPanel from '../components/dashboard/TrendPanel';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatCard from '../components/common/StatCard';
import StatusTag from '../components/common/StatusTag';
import useCountUp from '../hooks/useCountUp';
import type {
  DashboardOverview,
  DashboardProjectProgress,
  DashboardRecentTask,
} from '../types';
import { TASK_TYPE_LABELS } from '../types';
import '../components/dashboard/dashboard.css';

/** 自动刷新间隔：30 分钟（集群查询在服务端还有 5 分钟缓存） */
const AUTO_REFRESH_MS = 30 * 60 * 1000;

export default function Dashboard() {
  const { isAdmin } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [highlightRunning, setHighlightRunning] = useState(false);
  const runningRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(
    async (refreshCluster = false, silent = false) => {
      if (refreshCluster) setRefreshing(true);
      else if (!silent) setLoading(true);
      try {
        const data = await fetchDashboardOverview(refreshCluster);
        setOverview(data);
      } catch (err) {
        if (!silent) {
          message.error(err instanceof Error ? err.message : '总览数据加载失败');
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [message],
  );

  useEffect(() => {
    load();
  }, [load]);

  // 每 30 分钟自动刷新（静默刷新，不打扰用户）
  useEffect(() => {
    const timer = window.setInterval(() => load(false, true), AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const stats = overview?.stats;
  const projectCount = useCountUp(stats?.projects ?? 0);
  const anomalyCount = useCountUp(stats?.anomalies ?? 0);
  const todayCompleted = useCountUp(stats?.todayCompleted ?? 0);
  const runningJobs = useCountUp(stats?.runningJobs ?? 0);

  const trendText = useMemo(() => {
    if (!stats) return '';
    if (stats.projectsThisMonth > 0) return `本月新增 ${stats.projectsThisMonth} 个`;
    return `共 ${stats.totalTasks} 个任务`;
  }, [stats]);

  const completedTrend = useMemo(() => {
    const delta = stats?.completedDelta ?? 0;
    if (delta > 0) return `较昨日 +${delta}`;
    if (delta < 0) return `较昨日 ${delta}`;
    return '与昨日持平';
  }, [stats]);

  const focusRunning = () => {
    setHighlightRunning(true);
    runningRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => setHighlightRunning(false), 1600);
  };

  const handleInspect = async () => {
    setInspecting(true);
    try {
      const result = await runInspection({});
      message.success(
        `巡检完成：检查 ${result.inspected} 项，更新 ${result.updated} 项` +
          (result.warnings ? `，警告 ${result.warnings} 项` : ''),
      );
      await load(true, true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '触发巡检失败');
    } finally {
      setInspecting(false);
    }
  };

  const handleProjectCreated = async () => {
    await load(true, true);
  };

  const handleProjectDeleted = async (project: DashboardProjectProgress) => {
    try {
      const result = await deleteProject(project.project_id);
      message.success(
        `项目 ${result.project_name} 已删除` +
          (result.local_trash ? '（本地目录已移入回收站）' : ''),
      );
      await load(false, true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除项目失败');
    }
  };

  const handleProjectClose = async (project: DashboardProjectProgress) => {
    try {
      await closeProject(project.project_id);
      message.success(`项目 ${project.project_name} 已关闭（可在「已关闭项目」里重新打开）`);
      await load(false, true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '关闭项目失败');
    }
  };

  const handleProjectReopen = async (project: DashboardProjectProgress) => {
    try {
      await reopenProject(project.project_id);
      message.success(`项目 ${project.project_name} 已重新打开`);
      await load(false, true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重新打开项目失败');
    }
  };

  const recentColumns: ColumnsType<DashboardRecentTask> = [
    {
      title: '任务',
      key: 'task',
      render: (_, row) => (
        <div>
          <div className="cell-strong">{row.task_name}</div>
          <div className="dashboard-sub">
            {TASK_TYPE_LABELS[row.task_type] ?? row.task_type}
          </div>
        </div>
      ),
    },
    { title: '所属项目', dataIndex: 'project_name', key: 'project_name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: DashboardRecentTask['status']) => <StatusTag status={s} />,
    },
    {
      title: '最近能量 (eV)',
      dataIndex: 'last_energy',
      key: 'last_energy',
      width: 130,
      render: (v: number | null) =>
        v == null ? <span className="dashboard-muted">—</span> : v.toFixed(4),
    },
    {
      title: '作业号',
      dataIndex: 'job_id',
      key: 'job_id',
      width: 110,
      render: (v: string | null) =>
        v ? <span className="path-cell">{v}</span> : <span className="dashboard-muted">—</span>,
    },
    {
      title: '最近巡检',
      dataIndex: 'last_check_time',
      key: 'last_check_time',
      width: 160,
      render: (v: string | null) => (v ? v.replace('T', ' ').slice(5, 16) : '—'),
    },
  ];

  return (
    <PageTransition>
      <PageHeader
        title="总览"
        subtitle="状态 → 资源 → 趋势 → 明细：项目、作业与集群的一屏视图"
        extra={
          <div className="quick-actions">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
              新建项目
            </Button>
            {isAdmin && (
              <Button
                icon={<ThunderboltOutlined />}
                loading={inspecting}
                onClick={handleInspect}
              >
                触发全局巡检
              </Button>
            )}
            <Tooltip title="重新执行 bjobs / bhosts / bqueues / df（约 2-4 秒）">
              <Button
                icon={<ReloadOutlined />}
                loading={refreshing}
                onClick={() => load(true)}
              >
                刷新集群状态
              </Button>
            </Tooltip>
          </div>
        }
      />

      {loading && !overview ? (
        <Card>
          <Skeleton active paragraph={{ rows: 10 }} />
        </Card>
      ) : !overview ? (
        <Card>
          <div className="dashboard-muted">暂无数据：请确认后端服务（端口 3001）已启动。</div>
        </Card>
      ) : (
        <>
          {/* ① 顶部全局状态栏 */}
          <div className="stats-grid">
            <StatCard
              label="项目总数"
              value={projectCount}
              icon={<FolderOpenOutlined />}
              accent="blue"
              trend={trendText}
              delay={0}
            />
            <StatCard
              label="异常 / 警告项"
              value={anomalyCount}
              icon={<WarningOutlined />}
              accent="orange"
              trend={
                stats && stats.errorCount > 0
                  ? `严重 ${stats.errorCount} · 警告 ${stats.warningCount}`
                  : '需人工关注'
              }
              delay={0.06}
              onClick={() => navigate('/inspection')}
            />
            <StatCard
              label="今日完成"
              value={todayCompleted}
              icon={<CheckCircleOutlined />}
              accent="green"
              trend={completedTrend}
              delay={0.12}
            />
            <StatCard
              label="运行中任务"
              value={runningJobs}
              icon={<ThunderboltOutlined />}
              accent="teal"
              trend={`另有 ${stats?.pendingJobs ?? 0} 个排队中`}
              delay={0.18}
              onClick={focusRunning}
              active={highlightRunning}
            />
          </div>

          {/* ② 资源运行区 + 趋势健康区 */}
          <div className="dashboard-grid dashboard-grid--main">
            <div ref={runningRef}>
              <RunningTasksPanel
                jobs={overview.runningTasks}
                loading={loading}
                highlight={highlightRunning}
              />
            </div>
            <CoresUsagePanel usage={overview.coresUsage} loading={loading} />
          </div>

          <div className="dashboard-grid dashboard-grid--main">
            <TrendPanel trend={overview.trend} loading={loading} />
            <ClusterHealthPanel health={overview.clusterHealth} loading={loading} />
          </div>

          {/* ③ 风险 + 项目进度 */}
          <div className="dashboard-grid dashboard-grid--main">
            <RiskAlertsPanel
              summary={overview.riskAlerts}
              loading={loading}
              onInspect={isAdmin ? handleInspect : undefined}
              inspecting={inspecting}
            />
            <ProjectProgressPanel
              projects={overview.projectProgress}
              loading={loading}
              onDelete={handleProjectDeleted}
              onClose={handleProjectClose}
              onReopen={handleProjectReopen}
            />
          </div>

          {/* ④ 底部明细区 */}
          <Card
            className="dashboard-card mt-16"
            title="最近更新的任务"
            extra={
              <span className="dashboard-sub">
                集群数据 {overview.cluster.queriedAt?.replace('T', ' ') ?? '—'}
                {overview.cluster.cached ? '（缓存）' : ''}
              </span>
            }
          >
            <Table
              rowKey="task_id"
              dataSource={overview.recentTasks}
              columns={recentColumns}
              pagination={false}
              size="middle"
              onRow={(row) => ({
                onClick: () => navigate(`/jobs?task=${encodeURIComponent(row.task_id)}`),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>

          <div className="dashboard-note dashboard-note--footer">
            <CloudSyncOutlined /> 数据每次打开页面加载一次，之后每 30 分钟自动刷新；
            集群查询（bjobs / bhosts / bqueues / df）在服务端缓存 5 分钟，点「刷新集群状态」可强制更新。
            {overview.cluster.error && (
              <span className="dashboard-note--danger"> 集群查询异常：{overview.cluster.error}</span>
            )}
          </div>
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
