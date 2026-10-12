/**
 * 总览页「项目管理」面板（2026-10-12）：
 * 列出项目名称 / 交付日期 / 优先级（只读，算出来的）/ 归属，点「编辑」打开原生 <dialog>。
 * 空状态显示"暂无项目"。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, Empty, Table, Tag } from 'antd';

import ProjectEditDialog from './ProjectEditDialog';
import { fetchProjects } from '../../api/projects';
import type { Project } from '../../types';

interface Props {
  /** 外部（总览页）刷新信号：变化时重新拉一次项目列表 */
  refreshToken?: number;
  onSaved?: (project: Project) => void;
}

export default function ProjectManagePanel({ refreshToken = 0, onSaved }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Project | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 自己拉一次完整项目（总览的 projectProgress 是聚合视图，缺 calc_description 等字段）
      setProjects(await fetchProjects());
    } catch {
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const rows = useMemo(
    () => [...projects].sort((a, b) => (a.deadline || '9999').localeCompare(b.deadline || '9999')),
    [projects],
  );

  const columns = [
    {
      title: '项目',
      dataIndex: 'name',
      render: (name: string, row: Project) => (
        <span>
          {name}
          {row.closed ? <Tag style={{ marginLeft: 8 }}>已关闭</Tag> : null}
        </span>
      ),
    },
    {
      title: '交付日期',
      dataIndex: 'deadline',
      render: (deadline: string) => deadline || '—',
    },
    {
      title: '优先级（只读）',
      dataIndex: 'priority_quadrant',
      render: (_: string, row: Project) => (
        <span className="project-priority">
          {row.urgency === 'urgent' ? '紧急' : '不紧急'} ·{' '}
          {row.workload === 'large' ? '大工作量' : '小工作量'}
        </span>
      ),
    },
    {
      title: '归属',
      dataIndex: 'owner',
      render: (owner: string | null | undefined) => owner || '—',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, row: Project) => (
        <Button size="small" onClick={() => setEditing(row)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <Card
      className="dashboard-card mt-16"
      title="项目管理"
      extra={<span className="dashboard-sub">基础信息 + 计算内容描述 / 预期结果（会写进报告）</span>}
    >
      {rows.length === 0 ? (
        <Empty description={loading ? '加载中…' : '暂无项目'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table
          rowKey="id"
          dataSource={rows}
          columns={columns}
          pagination={false}
          size="middle"
        />
      )}
      <ProjectEditDialog
        open={editing !== null}
        project={editing}
        onClose={() => setEditing(null)}
        onSaved={(project) => {
          setEditing(null);
          setProjects((prev) => prev.map((p) => (p.id === project.id ? project : p)));
          onSaved?.(project);
        }}
      />
    </Card>
  );
}
