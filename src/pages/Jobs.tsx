import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { FileTextOutlined, FolderOpenOutlined, RedoOutlined } from '@ant-design/icons';
import { fetchProjects } from '../api/projects';
import { buildInputFiles } from '../data/mock/vaspFiles';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import ProgressBar from '../components/common/ProgressBar';
import StatusTag from '../components/common/StatusTag';
import type { Project, Task, TaskStatus } from '../types';
import { TASK_TYPE_LABELS } from '../types';
import { projectStatus } from '../utils/project';

export default function Jobs() {
  const { message } = App.useApp();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [generateTarget, setGenerateTarget] = useState<Task | null>(null);
  const [previewTab, setPreviewTab] = useState('INCAR');

  useEffect(() => {
    fetchProjects().then((p) => {
      setProjects(p);
      setSelectedProjectId(p[0]?.id ?? null);
    }).finally(() => setLoading(false));
  }, []);

  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;

  useEffect(() => {
    setSelectedTaskId(selectedProject?.tasks[0]?.task_id ?? null);
  }, [selectedProjectId, selectedProject]);

  const selectedTask = selectedProject?.tasks.find((t) => t.task_id === selectedTaskId) ?? null;
  const previewFiles = useMemo(
    () => (selectedTask ? buildInputFiles(selectedTask.model_name) : null),
    [selectedTask],
  );

  const handleResume = (task: Task) => {
    message.info(
      `已提交续算：${task.model_name}（演示）。正式版将从上次中断的 WAVECAR / CONTCAR 继续计算`,
    );
  };

  const columns: ColumnsType<Task> = [
    {
      title: '任务',
      key: 'task',
      render: (_, row) => (
        <div>
          <div className="cell-strong">{row.model_name}</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            {TASK_TYPE_LABELS[row.task_type]} · {row.task_id}
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s: TaskStatus) => <StatusTag status={s} />,
    },
    {
      title: '作业号',
      dataIndex: 'job_id',
      key: 'job_id',
      width: 100,
      render: (v: string | null) =>
        v ? <span className="path-cell">{v}</span> : <span style={{ color: 'var(--color-text-muted)' }}>—</span>,
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
      title: '远程路径',
      dataIndex: 'remote_dir',
      key: 'remote_dir',
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}>
          <span className="path-cell">{v}</span>
        </Tooltip>
      ),
    },
    {
      title: '本地路径',
      dataIndex: 'local_dir',
      key: 'local_dir',
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v}>
          <span className="path-cell">{v}</span>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 170,
      fixed: 'right',
      render: (_, row) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => setGenerateTarget(row)}
          >
            输入文件
          </Button>
          <Popconfirm
            title="确认提交续算？"
            description={`${row.model_name} 将从上次中断处继续（演示）`}
            onConfirm={() => handleResume(row)}
            okText="确认续算"
            cancelText="取消"
          >
            <Button size="small" icon={<RedoOutlined />}>
              续算
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const previewTabs = previewFiles
    ? (Object.entries(previewFiles) as [string, string][]).map(([name, content]) => ({
        key: name,
        label: name,
        children: <pre className="file-preview">{content}</pre>,
      }))
    : [];

  return (
    <PageTransition>
      <PageHeader
        title="作业管理"
        subtitle="管理项目子任务、本地/远程目录同步与 VASP 输入文件生成、续算"
      />

      <div className="jobs-grid">
        <Card title="项目列表" loading={loading}>
          <div className="project-list">
            {projects.map((p) => (
              <div
                key={p.id}
                className={`project-item${p.id === selectedProjectId ? ' active' : ''}`}
                onClick={() => setSelectedProjectId(p.id)}
              >
                <div className="project-item__head">
                  <span className="project-item__name">{p.name}</span>
                  <StatusTag status={projectStatus(p)} />
                </div>
                <ProgressBar value={p.progress} showText />
                <div className="project-item__meta">
                  {p.tasks.length} 个子任务 · 剩余约 {p.remainingHours}h · 截止 {p.deadline}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div>
          <Card title={`子任务 · ${selectedProject?.name ?? ''}`} loading={loading}>
            {selectedProject ? (
              <Table
                rowKey="task_id"
                dataSource={selectedProject.tasks}
                columns={columns}
                pagination={false}
                size="middle"
                scroll={{ x: 860 }}
              />
            ) : (
              <Empty description="请选择一个项目" />
            )}
          </Card>

          <Card
            className="mt-16"
            title="输入文件预览（占位）"
            extra={<span className="preview-note">演示内容 · 后续从远程服务器读取真实文件</span>}
          >
            {selectedTask && previewFiles ? (
              <>
                <div className="preview-paths">
                  <span>本地：{selectedTask.local_dir}</span>
                  <span>远程：{selectedTask.remote_dir}</span>
                </div>
                <Tabs activeKey={previewTab} onChange={setPreviewTab} items={previewTabs} />
              </>
            ) : (
              <Empty description="请选择左侧项目中的子任务" />
            )}
          </Card>
        </div>
      </div>

      <Modal
        title={`生成输入文件 · ${generateTarget?.model_name ?? ''}`}
        open={!!generateTarget}
        onCancel={() => setGenerateTarget(null)}
        onOk={() => {
          message.success(`输入文件已生成：${generateTarget?.model_name}（演示）`);
          setGenerateTarget(null);
        }}
        okText="生成"
        cancelText="取消"
      >
        <Alert
          type="info"
          showIcon
          message="演示模式"
          description="不会写入实际文件。正式版将自动生成 INCAR / POSCAR / KPOINTS / POTCAR，并同步到本地与远程目录。"
          style={{ marginTop: 8 }}
        />
        <div className="file-gen-list">
          {['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR'].map((f) => (
            <div key={f} className="file-gen-item">
              <FolderOpenOutlined style={{ color: 'var(--color-primary)' }} />
              {f}
              <span>→ {generateTarget?.remote_dir}/{f}</span>
            </div>
          ))}
        </div>
      </Modal>
    </PageTransition>
  );
}
