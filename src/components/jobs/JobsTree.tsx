import { Dropdown, Tooltip, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import {
  ApartmentOutlined,
  ExperimentOutlined,
  FileOutlined,
  FireOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { GroupMeta, Project, Task } from '../../types';
import { GROUP_ROLE_LABELS, TASK_TYPE_LABELS } from '../../types';
import StatusTag from '../common/StatusTag';
import { sortTasksByStatus } from '../../utils/project';
import { formatStructureLabel } from '../../utils/project';

interface Props {
  projects: Project[];
  selectedProjectId: string | null;
  selectedTaskId: string | null;
  selectedStructureKey: string | null;
  selectedNebGroupKey: string | null;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
  onSelectStructure: (key: string) => void;
  onSelectGroup: (key: string) => void;
  onSelectCategory?: (projectId: string, category: string) => void;
  onNewTask: (projectId: string, type: 'opt' | 'ele') => void;
  onNewGroup: (projectId: string, kind: 'free_energy' | 'neb') => void;
  onAddStructure: (projectId: string, groupId: string) => void;
}

function taskTitle(t: Task) {
  return (
    <Tooltip
      title={`${t.model_name} · ${TASK_TYPE_LABELS[t.task_type] ?? t.task_type}${
        t.subtype ? `（${t.subtype}）` : ''
      }`}
    >
      <span className="job-tree__task">
        <span className="job-tree__task-name">{t.model_name}</span>
        <StatusTag status={t.status} />
      </span>
    </Tooltip>
  );
}

function taskNode(t: Task): DataNode {
  return {
    key: `t:${t.task_id}`,
    icon: <FileOutlined style={{ color: '#9aa7b8' }} />,
    title: taskTitle(t),
    isLeaf: true,
  };
}

function freeEnergyChildren(tasks: Task[]): DataNode[] {
  const byLabel = new Map<string, Task[]>();
  for (const t of tasks) {
    const label = t.group?.structure_label ?? t.model_name;
    const list = byLabel.get(label) ?? [];
    list.push(t);
    byLabel.set(label, list);
  }
  const labels = Array.from(byLabel.keys()).sort();
  return labels.map((label) => {
    const members = sortTasksByStatus(byLabel.get(label) ?? []);
    const first = members[0];
    return {
      key: `s:${first.group?.group_id}:${label}`,
      icon: (
        <span style={{ color: 'var(--color-primary)' }}>
          <ExperimentOutlined />
        </span>
      ),
      title: (
        <span className="job-tree__task">
          <span className="job-tree__task-name">
            {formatStructureLabel(label)}（结构优化 + 频率矫正）
          </span>
          <span className="job-tree__count">{members.length}</span>
        </span>
      ),
      isLeaf: true,
    };
  });
}

function buildProjectChildren(
  p: Project,
  onNewTask: (projectId: string, type: 'opt' | 'ele') => void,
  onNewGroup: (projectId: string, kind: 'free_energy' | 'neb') => void,
  onAddStructure: (projectId: string, groupId: string) => void,
): DataNode[] {
  const groups = new Map<string, Task[]>();
  const byCategory: Record<string, Task[]> = { opt: [], frac: [], neb: [], ele: [] };
  for (const t of p.tasks) {
    if (t.group?.group_id) {
      const list = groups.get(t.group.group_id) ?? [];
      list.push(t);
      groups.set(t.group.group_id, list);
    } else {
      byCategory[t.task_type]?.push(t);
    }
  }
  const children: DataNode[] = [];

  // 结构优化（独立 opt）
  const optNodes = sortTasksByStatus(byCategory.opt).map(taskNode);
  children.push({
    key: `c:${p.id}:opt`,
    icon: <FireOutlined style={{ color: '#d18a2b' }} />,
    title: (
      <span className="job-tree__cat-row">
        <span className="job-tree__category">结构优化</span>
        <span
          className="job-tree__add"
          title="新建结构优化任务"
          onClick={(e) => {
            e.stopPropagation();
            onNewTask(p.id, 'opt');
          }}
        >
          <PlusOutlined />
        </span>
      </span>
    ),
    children: optNodes,
  });

  // 自由能（组 + 独立 frac）
  const feNodes: DataNode[] = [];
  for (const [groupId, tasks] of groups) {
    if (tasks[0].group?.group_type !== 'free_energy') continue;
    feNodes.push({
      key: `g:${p.id}:${groupId}`,
      icon: <ApartmentOutlined style={{ color: 'var(--color-secondary)' }} />,
      title: (
        <span className="job-tree__cat-row">
          <span className="job-tree__group">{tasks[0].group?.name ?? '自由能组'}</span>
          <span
            className="job-tree__add"
            title="添加结构"
            onClick={(e) => {
              e.stopPropagation();
              onAddStructure(p.id, groupId);
            }}
          >
            <PlusOutlined />
          </span>
        </span>
      ),
      children: freeEnergyChildren(tasks),
    });
  }
  feNodes.push(...sortTasksByStatus(byCategory.frac).map(taskNode));
  children.push({
    key: `c:${p.id}:free_energy`,
    icon: <ApartmentOutlined style={{ color: 'var(--color-secondary)' }} />,
    title: (
      <span className="job-tree__cat-row">
        <span className="job-tree__category">自由能</span>
        <span
          className="job-tree__add"
          title="新建自由能组"
          onClick={(e) => {
            e.stopPropagation();
            onNewGroup(p.id, 'free_energy');
          }}
        >
          <PlusOutlined />
        </span>
      </span>
    ),
    children: feNodes,
  });

  // NEB（组 + 独立 neb）
  const nebNodes: DataNode[] = [];
  for (const [groupId, tasks] of groups) {
    if (tasks[0].group?.group_type !== 'neb') continue;
    nebNodes.push({
      key: `g:${p.id}:${groupId}`,
      icon: <ThunderboltOutlined style={{ color: '#7b61d6' }} />,
      title: (
        <span className="job-tree__group">{tasks[0].group?.name ?? 'NEB 组'}</span>
      ),
      children: sortTasksByStatus(tasks).map((t) => ({
        ...taskNode(t),
        title: (
          <span className="job-tree__task">
            <span className="job-tree__task-name">
              {GROUP_ROLE_LABELS[t.group?.group_role as GroupMeta['group_role']] ??
                TASK_TYPE_LABELS[t.task_type]}
            </span>
            <StatusTag status={t.status} />
          </span>
        ),
      })),
    });
  }
  nebNodes.push(...sortTasksByStatus(byCategory.neb).map(taskNode));
  children.push({
    key: `c:${p.id}:neb`,
    icon: <ThunderboltOutlined style={{ color: '#7b61d6' }} />,
    title: (
      <span className="job-tree__cat-row">
        <span className="job-tree__category">NEB</span>
        <span
          className="job-tree__add"
          title="新建 NEB 组"
          onClick={(e) => {
            e.stopPropagation();
            onNewGroup(p.id, 'neb');
          }}
        >
          <PlusOutlined />
        </span>
      </span>
    ),
    children: nebNodes,
  });

  // 电子结构
  children.push({
    key: `c:${p.id}:ele`,
    icon: <ExperimentOutlined style={{ color: '#2c9da8' }} />,
    title: (
      <span className="job-tree__cat-row">
        <span className="job-tree__category">电子结构</span>
        <span
          className="job-tree__add"
          title="新建电子结构任务"
          onClick={(e) => {
            e.stopPropagation();
            onNewTask(p.id, 'ele');
          }}
        >
          <PlusOutlined />
        </span>
      </span>
    ),
    children: sortTasksByStatus(byCategory.ele).map(taskNode),
  });
  return children;
}

export default function JobsTree({
  projects,
  selectedProjectId,
  selectedTaskId,
  selectedStructureKey,
  selectedNebGroupKey,
  onSelectProject,
  onSelectTask,
  onSelectStructure,
  onSelectGroup,
  onSelectCategory,
  onNewTask,
  onNewGroup,
  onAddStructure,
}: Props) {
  // 已关闭项目排到最后（灰色显示、默认折叠子项），与总览 / 巡检中心口径一致
  const orderedProjects = [
    ...projects.filter((p) => !p.closed),
    ...projects.filter((p) => p.closed),
  ];

  const treeData: DataNode[] = orderedProjects.map((p) => ({
    key: `p:${p.id}`,
    icon: (
      <FolderOpenOutlined
        style={{ color: p.closed ? '#9aa7b8' : 'var(--color-primary)' }}
      />
    ),
    title: (
      <span
        className={`job-tree__project-row${p.closed ? ' job-tree__project-row--closed' : ''}`}
      >
        <span className="job-tree__project">
          <span>{p.name}</span>
          <span className="job-tree__count">{p.tasks.length}</span>
          {p.closed && <span className="job-tree__closed">已关闭</span>}
        </span>
        {!p.closed && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              { key: 'opt', label: '新建结构优化' },
              { key: 'fe', label: '新建自由能组' },
              { key: 'neb', label: '新建 NEB 组' },
              { key: 'ele', label: '新建电子结构' },
            ],
            onClick: ({ key, domEvent }) => {
              domEvent.stopPropagation();
              if (key === 'opt' || key === 'ele') onNewTask(p.id, key);
              else onNewGroup(p.id, key as 'free_energy' | 'neb');
            },
          }}
        >
          <span
            className="job-tree__add"
            title="新建任务 / 组"
            onClick={(e) => e.stopPropagation()}
          >
            <PlusOutlined />
          </span>
        </Dropdown>
        )}
      </span>
    ),
    children: buildProjectChildren(p, onNewTask, onNewGroup, onAddStructure),
  }));

  const selectedKeys = selectedTaskId
    ? [`t:${selectedTaskId}`]
    : selectedStructureKey
      ? [selectedStructureKey]
      : selectedNebGroupKey
        ? [selectedNebGroupKey]
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
          else if (key.startsWith('s:')) onSelectStructure(key.slice(2));
          else if (key.startsWith('g:')) onSelectGroup(key.slice(2));
          else if (key.startsWith('c:')) {
            const rest = key.slice(2).split(':');
            onSelectCategory?.(rest[0], rest[1]);
          }
          else if (key.startsWith('p:')) onSelectProject(key.slice(2));
        }}
      />
    </div>
  );
}
