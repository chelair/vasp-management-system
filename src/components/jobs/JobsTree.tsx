import { Tooltip, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { FolderOpenOutlined, FileOutlined, PlusOutlined } from '@ant-design/icons';
import type { Project, TaskStatus } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import StatusTag from '../common/StatusTag';
import { sortTasksByStatus } from '../../utils/project';

interface Props {
  projects: Project[];
  selectedProjectId: string | null;
  selectedTaskId: string | null;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
  onNewTask: (projectId: string) => void;
}

function taskTitle(t: { task_id: string; model_name: string; task_type: string; status: TaskStatus }) {
  return (
    <Tooltip
      title={`${t.model_name} · ${TASK_TYPE_LABELS[t.task_type as keyof typeof TASK_TYPE_LABELS] ?? t.task_type}`}
    >
      <span className="job-tree__task">
        <span className="job-tree__task-name">{t.model_name}</span>
        <StatusTag status={t.status} />
      </span>
    </Tooltip>
  );
}

export default function JobsTree({
  projects,
  selectedProjectId,
  selectedTaskId,
  onSelectProject,
  onSelectTask,
  onNewTask,
}: Props) {
  const treeData: DataNode[] = projects.map((p) => ({
    key: `p:${p.id}`,
    icon: <FolderOpenOutlined style={{ color: 'var(--color-primary)' }} />,
    title: (
      <span className="job-tree__project-row">
        <span className="job-tree__project">
          <span>{p.name}</span>
          <span className="job-tree__count">{p.tasks.length}</span>
        </span>
        <span
          className="job-tree__add"
          title="新建子项"
          onClick={(e) => {
            e.stopPropagation();
            onNewTask(p.id);
          }}
        >
          <PlusOutlined />
        </span>
      </span>
    ),
    children: sortTasksByStatus(p.tasks).map((t) => ({
      key: `t:${t.task_id}`,
      icon: <FileOutlined style={{ color: '#9aa7b8' }} />,
      title: taskTitle(t),
      isLeaf: true,
    })),
  }));

  const selectedKeys = selectedTaskId
    ? [`t:${selectedTaskId}`]
    : selectedProjectId
      ? [`p:${selectedProjectId}`]
      : [];

  return (
    <div className="job-tree">
      <Tree
        showIcon
        blockNode
        treeData={treeData}
        selectedKeys={selectedKeys}
        defaultExpandAll
        onSelect={(_keys, info) => {
          const key = String(info.node.key);
          if (key.startsWith('t:')) onSelectTask(key.slice(2));
          else onSelectProject(key.slice(2));
        }}
      />
    </div>
  );
}
