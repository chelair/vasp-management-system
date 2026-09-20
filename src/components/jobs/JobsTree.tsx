import { Dropdown, Tooltip, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useEffect, useMemo, useState } from 'react';
import {
  ApartmentOutlined,
  CloseCircleFilled,
  ExperimentOutlined,
  FileOutlined,
  FireOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  WarningFilled,
} from '@ant-design/icons';
import type { GroupMeta, Project, Task } from '../../types';
import { GROUP_ROLE_LABELS, TASK_TYPE_LABELS } from '../../types';
import StatusTag from '../common/StatusTag';
import {
  checkNeedsAttention,
  pickGroupCheck,
  pickGroupStatus,
  sortTasksByStatus,
} from '../../utils/project';
import type { TaskCheckSummary } from '../../types';
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

/** 巡检告警图标：低精度收敛 / 力未收敛 / 异常等（与巡检中心同一文案，悬停可看） */
function checkIcon(check?: TaskCheckSummary | null) {
  if (!checkNeedsAttention(check)) return null;
  const error = check?.status === 'error';
  return (
    <Tooltip title={check?.message || '巡检异常'}>
      <span className={`job-tree__check${error ? ' is-error' : ''}`}>
        {error ? <CloseCircleFilled /> : <WarningFilled />}
      </span>
    </Tooltip>
  );
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
        {/* 巡检结论只在指向告警图标时显示（行本身不展开巡检文案，避免误触/刷屏） */}
        {checkIcon(t.check)}
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
    const groupStatus = pickGroupStatus(members);
    const groupCheck = pickGroupCheck(members);
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
          {/* 结构节点 = opt + frac 两个任务，显示两者里优先级最高的状态（红>黄>灰>归档） */}
          {checkIcon(groupCheck)}
          {groupStatus && <StatusTag status={groupStatus} />}
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
    const groupStatus = pickGroupStatus(tasks);
    const groupCheck = pickGroupCheck(tasks);
    feNodes.push({
      key: `g:${p.id}:${groupId}`,
      icon: <ApartmentOutlined style={{ color: 'var(--color-secondary)' }} />,
      title: (
        <span className="job-tree__cat-row">
          <span className="job-tree__group">{tasks[0].group?.name ?? '自由能组'}</span>
          {checkIcon(groupCheck)}
          {groupStatus && <StatusTag status={groupStatus} />}
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
    const groupStatus = pickGroupStatus(tasks);
    const groupCheck = pickGroupCheck(tasks);
    nebNodes.push({
      key: `g:${p.id}:${groupId}`,
      icon: <ThunderboltOutlined style={{ color: '#7b61d6' }} />,
      title: (
        <span className="job-tree__cat-row">
          <span className="job-tree__group">{tasks[0].group?.name ?? 'NEB 组'}</span>
          {checkIcon(groupCheck)}
          {groupStatus && <StatusTag status={groupStatus} />}
        </span>
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

  // 已关闭项目默认折叠（不展开其子树），其余项目保持展开
  const closedProjectKeys = new Set(
    orderedProjects.filter((p) => p.closed).map((p) => `p:${p.id}`),
  );
  const collectKeys = (nodes: DataNode[], underClosed = false): string[] =>
    nodes.flatMap((node) => {
      const key = String(node.key);
      const closedHere = underClosed || closedProjectKeys.has(key);
      const own = closedHere ? [] : [key];
      const children = (node.children as DataNode[] | undefined) ?? [];
      return [...own, ...collectKeys(children, closedHere)];
    });
  const allExpandableKeys = useMemo(
    () => collectKeys(treeData),
    // treeData 由 projects 派生，随 projects 变化重算即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projects],
  );
  const [expandedKeys, setExpandedKeys] = useState<string[]>(allExpandableKeys);
  // 项目列表变化时（新建/归档/关闭）重置为「关闭项目折叠、其余展开」
  useEffect(() => {
    setExpandedKeys(allExpandableKeys);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  return (
    <div className="job-tree">
      <Tree
        showIcon
        blockNode
        treeData={treeData}
        selectedKeys={selectedKeys}
        expandedKeys={expandedKeys}
        onExpand={(keys) => setExpandedKeys(keys.map(String))}
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
