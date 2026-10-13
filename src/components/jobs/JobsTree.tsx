import { Dropdown, Tooltip, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useEffect, useMemo, useRef, useState } from 'react';
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

/**
 * 树节点（在 antd `DataNode` 上多带一个标记）：
 * `allArchived` = 该节点及其所有子任务**全部已归档** → 默认折叠（用户仍可手动展开，
 * 2026-10-13 用户要求："一个组或该类型任务全部归档，则默认折叠"）。
 */
type JobNode = DataNode & { allArchived?: boolean };

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

function taskNode(t: Task): JobNode {
  return {
    key: `t:${t.task_id}`,
    icon: <FileOutlined style={{ color: '#9aa7b8' }} />,
    title: taskTitle(t),
    isLeaf: true,
    allArchived: t.status === 'archived',
  };
}

function freeEnergyChildren(tasks: Task[]): JobNode[] {
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
      // 结构节点 = opt + frac 两个任务：两个都归档才算"全归档"
      allArchived: members.every((t) => t.status === 'archived'),
    };
  });
}

function buildProjectChildren(
  p: Project,
  onNewTask: (projectId: string, type: 'opt' | 'ele') => void,
  onNewGroup: (projectId: string, kind: 'free_energy' | 'neb') => void,
  onAddStructure: (projectId: string, groupId: string) => void,
): JobNode[] {
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
  const children: JobNode[] = [];
  /** 子节点全部归档（且非空）→ 这一层默认折叠 */
  const allArchived = (nodes: JobNode[]) =>
    nodes.length > 0 && nodes.every((node) => node.allArchived === true);

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
    allArchived: allArchived(optNodes),
  });

  // 自由能（组 + 独立 frac）
  const feNodes: JobNode[] = [];
  for (const [groupId, tasks] of groups) {
    if (tasks[0].group?.group_type !== 'free_energy') continue;
    const groupStatus = pickGroupStatus(tasks);
    const groupCheck = pickGroupCheck(tasks);
    const structureNodes = freeEnergyChildren(tasks);
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
      children: structureNodes,
      // 组内结构（opt + frac）全部归档 → 该组默认折叠
      allArchived: structureNodes.length > 0 && structureNodes.every((n) => n.allArchived === true),
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
    allArchived: allArchived(feNodes),
  });

  // NEB（组 + 独立 neb）
  const nebNodes: JobNode[] = [];
  for (const [groupId, tasks] of groups) {
    if (tasks[0].group?.group_type !== 'neb') continue;
    const groupStatus = pickGroupStatus(tasks);
    const groupCheck = pickGroupCheck(tasks);
    const memberNodes = sortTasksByStatus(tasks).map((t) => ({
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
    }));
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
      children: memberNodes,
      allArchived: allArchived(memberNodes),
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
    allArchived: allArchived(nebNodes),
  });

  // 电子结构
  const eleNodes = sortTasksByStatus(byCategory.ele).map(taskNode);
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
    children: eleNodes,
    allArchived: allArchived(eleNodes),
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
          {p.owner && (
            <Tooltip title={`项目归属：${p.owner}`}>
              <span className="job-tree__owner">{p.owner}</span>
            </Tooltip>
          )}
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

  /**
   * 选中项对应的树节点 key。
   *
   * 注意**自由能组内的任务在树里不是独立节点**（opt + frac 合并成一个 `s:<组>:<结构>` 结构节点），
   * 所以外部（总览点任务 / 巡检跳转）选中组内任务时要把任务 id 映射回结构节点，
   * 否则既不高亮、也定位不到（2026-10-13 用户反馈）。
   */
  const focusKey = useMemo(() => {
    if (selectedTaskId) {
      const task = orderedProjects
        .flatMap((p) => p.tasks)
        .find((t) => t.task_id === selectedTaskId);
      if (task?.group?.group_type === 'free_energy') {
        const label = task.group.structure_label ?? task.model_name;
        return `s:${task.group.group_id}:${label}`;
      }
      return `t:${selectedTaskId}`;
    }
    if (selectedStructureKey) return selectedStructureKey;
    if (selectedNebGroupKey) return selectedNebGroupKey;
    if (selectedProjectId) return `p:${selectedProjectId}`;
    return '';
  }, [selectedTaskId, selectedStructureKey, selectedNebGroupKey, selectedProjectId, orderedProjects]);
  const selectedKeys = focusKey ? [focusKey] : [];

  // 已关闭项目默认折叠（不展开其子树），其余项目保持展开
  const closedProjectKeys = new Set(
    orderedProjects.filter((p) => p.closed).map((p) => `p:${p.id}`),
  );
  /**
   * 收集"默认展开"的节点 key：跳过已关闭项目的子树，以及**全部已归档**的组/类型
   * （用户可以手动展开，但默认折叠 —— 2026-10-13 用户要求）。
   */
  const collectKeys = (nodes: JobNode[], underCollapsed = false): string[] =>
    nodes.flatMap((node) => {
      const key = String(node.key);
      const collapsedHere =
        underCollapsed || closedProjectKeys.has(key) || node.allArchived === true;
      const own = collapsedHere ? [] : [key];
      const children = (node.children as JobNode[] | undefined) ?? [];
      return [...own, ...collectKeys(children, collapsedHere)];
    });
  /** 树里**存在**的所有 key（用于刷新时判断"这个 key 还在不在"） */
  const collectExistingKeys = (nodes: JobNode[]): string[] =>
    nodes.flatMap((node) => [
      String(node.key),
      ...collectExistingKeys((node.children as JobNode[] | undefined) ?? []),
    ]);
  const allExpandableKeys = useMemo(
    () => collectKeys(treeData),
    // treeData 由 projects 派生，随 projects 变化重算即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projects],
  );
  /** 树上存在的全部 key：刷新时只按它剔除"已经不存在"的 key（见下面的展开状态处理） */
  const existingKeys = useMemo(
    () => new Set(collectExistingKeys(treeData)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projects],
  );
  const [expandedKeys, setExpandedKeys] = useState<string[]>(allExpandableKeys);
  /**
   * 项目列表刷新时的展开状态处理（v0.9.26）。
   *
   * 原来的写法是"只要 projects 变了就 setExpandedKeys(allExpandableKeys)"——
   * 结果每次提交作业 / 归档 / 新建之后的列表刷新，都会把用户手动折叠/展开的状态冲掉、
   * 整个树回到"全部展开 + 滚动到顶端"的观感。现在改成：
   * - **保留**用户当前的展开状态（只丢掉已经不存在的 key，比如被删掉的任务/组）；
   * - 只把**这次新出现**的节点自动展开（新建项目/组/任务时体验不变）；
   * - 已关闭项目的子树仍然自动折叠（allExpandableKeys 里本来就不含它们的子键）。
   */
  const knownKeysRef = useRef<Set<string>>(new Set(allExpandableKeys));
  useEffect(() => {
    const known = knownKeysRef.current;
    const fresh = allExpandableKeys.filter((key) => !known.has(key));
    // 有效性按"节点是否还在树上"判断 —— 不能只用默认展开集合：
    // 用户手动展开了"全归档"的组、或从总览跳进来时自动展开了某条路径，
    // 这些 key 不在默认集合里，但必须保留（否则一次刷新就把它们折回去）。
    const valid = existingKeys;
    knownKeysRef.current = valid;
    setExpandedKeys((prev) => {
      const kept = prev.filter((key) => valid.has(key));
      const next = Array.from(new Set([...kept, ...fresh]));
      // 内容没变就不要 setState，避免多余渲染把滚动位置晃掉
      const same = next.length === prev.length && next.every((key, i) => key === prev[i]);
      return same ? prev : next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allExpandableKeys]);

  /** 从总览/巡检点任务跳进来时：展开这个节点所在路径，并把它滚到视野中间。 */
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const focusedKeyRef = useRef<string>('');
  const skipScrollRef = useRef(false);

  const ancestorKeysOf = useMemo(() => {
    const build = (target: string): string[] => {
      const walk = (nodes: JobNode[], trail: string[]): string[] | null => {
        for (const node of nodes) {
          const key = String(node.key);
          if (key === target) return trail;
          const children = (node.children as JobNode[] | undefined) ?? [];
          if (!children.length) continue;
          const found = walk(children, [...trail, key]);
          if (found) return found;
        }
        return null;
      };
      return walk(treeData, []) ?? [];
    };
    return build;
  }, [treeData]);

  useEffect(() => {
    if (!focusKey || focusedKeyRef.current === focusKey) return;
    focusedKeyRef.current = focusKey;
    const fromTree = skipScrollRef.current; // 用户自己在树上点选的：已在视野里，不滚
    skipScrollRef.current = false;
    // 找到这条路径上的可展开节点：
    // - 归属"全归档"的组/类型 → 平时折叠着，这里临时展开（点了任务就该看得到）
    // - 归属已关闭项目 → 同理（原来一律折叠，跳进来就会"找不到任务"）
    const ancestors = ancestorKeysOf(focusKey);
    if (ancestors.length) {
      setExpandedKeys((prev) => {
        const next = Array.from(new Set([...prev, ...ancestors]));
        return next.length === prev.length ? prev : next;
      });
    }
    if (fromTree) return;
    // 等展开后的 DOM 落地再滚动（antd 树没有虚拟滚动，直接查选中的那一行）
    const timer = window.setTimeout(() => {
      const node = wrapRef.current?.querySelector('.ant-tree-treenode-selected');
      node?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 80);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, ancestorKeysOf]);

  return (
    <div className="job-tree" ref={wrapRef}>
      <Tree
        showIcon
        blockNode
        treeData={treeData}
        selectedKeys={selectedKeys}
        expandedKeys={expandedKeys}
        onExpand={(keys) => setExpandedKeys(keys.map(String))}
        onSelect={(_keys, info) => {
          const key = String(info.node.key);
          skipScrollRef.current = true;
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
