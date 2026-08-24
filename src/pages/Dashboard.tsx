import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
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
  createProject,
  fetchDashboardMeta,
  fetchProjects,
  fetchServers,
  fetchTaskTypes,
  fetchWeeklyTrend,
} from '../api/projects';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import ProgressBar from '../components/common/ProgressBar';
import StatCard from '../components/common/StatCard';
import StatusTag from '../components/common/StatusTag';
import TrendChart from '../components/common/TrendChart';
import type {
  CreateProjectPayload,
  DashboardMeta,
  Project,
  ServerOption,
  Task,
  TaskStatus,
  TaskType,
  TaskTypeOption,
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
  const [submitting, setSubmitting] = useState(false);
  const [serverOptions, setServerOptions] = useState<ServerOption[]>([]);
  const [taskTypeOptions, setTaskTypeOptions] = useState<TaskTypeOption[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    Promise.all([
      fetchProjects(),
      fetchDashboardMeta(),
      fetchWeeklyTrend(),
      fetchServers(),
      fetchTaskTypes(),
    ])
      .then(([p, m, t, servers, taskTypes]) => {
        setProjects(p);
        setMeta(m);
        setTrend(t);
        setServerOptions(servers);
        setTaskTypeOptions(taskTypes);
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

  const openAdd = () => {
    form.resetFields();
    form.setFieldsValue({
      server: serverOptions[0]?.name ?? 'server1',
      tasks: [{ task_type: 'structure_opt', model_name: '' }],
    });
    setAddOpen(true);
  };

  const handleAddProject = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload: CreateProjectPayload = {
        name: values.name,
        deadline: values.deadline,
        server: values.server,
        tasks: values.tasks.map((t: { task_type: TaskType; model_name: string }) => ({
          task_type: t.task_type,
          model_name: t.model_name,
        })),
        description: values.description || '',
        estimated_hours: values.estimated_hours ?? null,
      };
      const result = await createProject(payload);
      setAddOpen(false);
      form.resetFields();
      message.success(
        `项目「${values.name}」创建成功：${result.project_id}（${result.priority_quadrant}）`,
      );
      // 刷新项目列表（后端已就绪，将返回真实数据）
      const fresh = await fetchProjects();
      setProjects(fresh);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setSubmitting(false);
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

      <Modal
        title="新增项目"
        open={addOpen}
        onOk={handleAddProject}
        onCancel={() => {
          setAddOpen(false);
          form.resetFields();
        }}
        confirmLoading={submitting}
        okText="创建"
        cancelText="取消"
        forceRender
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            label="项目名称"
            name="name"
            rules={[
              { required: true, message: '请输入项目名称' },
              {
                pattern: /^[A-Za-z0-9][A-Za-z0-9_]*$/,
                message: '与后端一致：以字母/数字开头，仅含字母、数字、下划线',
              },
            ]}
          >
            <Input placeholder="如 Ag_20260830" />
          </Form.Item>
          <Form.Item
            label="截止日期"
            name="deadline"
            rules={[
              { required: true, message: '请输入截止日期' },
              {
                pattern: /^\d{4}-\d{2}-\d{2}$/,
                message: '格式须为 YYYY-MM-DD，如 2026-09-30',
              },
            ]}
          >
            <Input placeholder="2026-09-30" />
          </Form.Item>
          <Form.Item
            label="计算服务器"
            name="server"
            rules={[{ required: true, message: '请选择计算服务器' }]}
          >
            <Select
              placeholder="选择服务器"
              options={serverOptions.map((s) => ({
                value: s.name,
                label: `${s.name} (${s.user}@${s.host})`,
              }))}
            />
          </Form.Item>

          <Form.Item label="子任务（至少 1 个）" required style={{ marginBottom: 8 }}>
            <Form.List name="tasks">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <div key={key} className="task-form-row">
                      <Form.Item
                        {...restField}
                        name={[name, 'task_type']}
                        rules={[{ required: true, message: '请选择任务类型' }]}
                        style={{ width: 190, marginBottom: 8 }}
                      >
                        <Select
                          placeholder="任务类型"
                          options={taskTypeOptions
                            .filter((t) => t.type !== 'frequency')
                            .map((t) => ({
                              value: t.type,
                              label: `${t.description}（权重 ${t.workload_weight}）`,
                            }))}
                        />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'model_name']}
                        rules={[
                          { required: true, message: '请输入模型名称' },
                          {
                            pattern: /^[A-Za-z0-9][A-Za-z0-9_]*$/,
                            message: '以字母/数字开头，仅含字母、数字、下划线',
                          },
                        ]}
                        style={{ flex: 1, marginBottom: 8 }}
                      >
                        <Input placeholder="模型名称，如 Al2O3_Ag" />
                      </Form.Item>
                      {fields.length > 1 && (
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => remove(name)}
                          style={{ marginBottom: 8 }}
                          aria-label="删除该子任务"
                        />
                      )}
                    </div>
                  ))}
                  <Button
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    onClick={() => add({ task_type: 'structure_opt', model_name: '' })}
                    style={{ marginBottom: 12 }}
                  >
                    添加子任务
                  </Button>
                </>
              )}
            </Form.List>
          </Form.Item>

          <Form.Item label="预计耗时（小时，可选）" name="estimated_hours">
            <InputNumber min={1} max={2000} style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item label="项目描述（可选）" name="description">
            <Input.TextArea rows={2} placeholder="研究内容简述" />
          </Form.Item>
        </Form>
      </Modal>
    </PageTransition>
  );
}
