import { useMemo, useState } from 'react';
import { Checkbox, Empty, Input, Radio } from 'antd';
import { DownOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import type { TaskRef, TaskType } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  targets: TaskRef[];
  /** 单选（复制一个结构）或多选（批量同步参数） */
  mode: 'single' | 'multiple';
  selectedIds: string[];
  /** 选中/取消选中一个任务；additive=true 表示并入（多选时由父组件决定） */
  onToggle: (taskId: string, additive: boolean) => void;
  /** 多选：整组全选 / 取消全选 */
  onToggleGroup?: (taskIds: string[], checked: boolean) => void;
  /** 默认展开的项目（一般传当前任务所在项目，其余默认折叠） */
  defaultExpandedIds?: string[];
  emptyText?: string;
}

export interface ProjectGroup {
  projectId: string;
  projectName: string;
  closed: boolean;
  tasks: TaskRef[];
}

/** 按项目分组，并把已关闭项目单独拆出来（列表里折叠到最后） */
export function groupTargets(targets: TaskRef[]): {
  active: ProjectGroup[];
  closed: ProjectGroup[];
} {
  const map = new Map<string, ProjectGroup>();
  for (const target of targets) {
    const group = map.get(target.projectId) ?? {
      projectId: target.projectId,
      projectName: target.projectName,
      closed: !!target.projectClosed,
      tasks: [],
    };
    group.tasks.push(target);
    map.set(target.projectId, group);
  }
  const all = Array.from(map.values());
  return { active: all.filter((g) => !g.closed), closed: all.filter((g) => g.closed) };
}

/** 关键字过滤：项目名 / 任务名 / 任务类型都参与匹配；空关键字原样返回 */
export function filterGroups(groups: ProjectGroup[], keyword: string): ProjectGroup[] {
  const kw = keyword.trim().toLowerCase();
  if (!kw) return groups;
  return groups
    .map((group) => ({
      ...group,
      tasks: group.tasks.filter((t) =>
        `${group.projectName} ${t.taskName} ${
          TASK_TYPE_LABELS[t.taskType as TaskType] ?? t.taskType
        }`
          .toLowerCase()
          .includes(kw),
      ),
    }))
    .filter((group) => group.tasks.length > 0);
}

/**
 * 任务选择列表（v0.8.9）。
 *
 * 作业一多，平铺列表会越来越长，所以统一按**项目分组 + 可折叠**呈现：
 * 默认只展开当前任务所在项目，带搜索框，**已关闭项目排到最后、折成一块**
 * （与总览 / 报告 / 巡检中心的「已关闭项目」口径一致）。
 */
export default function TaskPickerList({
  targets,
  mode,
  selectedIds,
  onToggle,
  onToggleGroup,
  defaultExpandedIds = [],
  emptyText = '没有可选的作业',
}: Props) {
  const [keyword, setKeyword] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(defaultExpandedIds));
  const [closedOpen, setClosedOpen] = useState(false);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const kw = keyword.trim().toLowerCase();

  const { active, closed } = useMemo(() => groupTargets(targets), [targets]);
  const visibleActive = useMemo(() => filterGroups(active, keyword), [active, keyword]);
  const visibleClosed = useMemo(() => filterGroups(closed, keyword), [closed, keyword]);

  // 搜索时全部展开，否则结果会藏在折叠里看不见
  const showClosedList = kw ? visibleClosed.length > 0 : closedOpen;
  /**
   * 是否展开项目成员：搜索时全展开；已关闭项目在折叠块打开时**直接展开**
   * （否则要点两层才看得到内容）；其余项目按用户的手动折叠状态。
   */
  const isExpanded = (group: ProjectGroup) =>
    kw || (group.closed && showClosedList) || expanded.has(group.projectId);

  const toggleGroupExpanded = (projectId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  };

  const renderGroup = (group: ProjectGroup) => {
    const ids = group.tasks.map((t) => t.taskId);
    const picked = ids.filter((id) => selectedSet.has(id)).length;
    const open = isExpanded(group);
    return (
      <div key={group.projectId} className="task-picker__group">
        <div
          className="task-picker__group-head"
          role="button"
          tabIndex={0}
          onClick={() => toggleGroupExpanded(group.projectId)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') toggleGroupExpanded(group.projectId);
          }}
        >
          {open ? <DownOutlined /> : <RightOutlined />}
          <span className="task-picker__group-name">{group.projectName}</span>
          <span className="task-picker__group-count">
            {picked > 0 ? `已选 ${picked} / ${group.tasks.length}` : `${group.tasks.length} 个作业`}
          </span>
          {mode === 'multiple' && onToggleGroup && !kw && (
            <Checkbox
              checked={picked > 0 && picked === ids.length}
              indeterminate={picked > 0 && picked < ids.length}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onToggleGroup(ids, e.target.checked)}
            >
              全选本项目
            </Checkbox>
          )}
        </div>
        {open && (
          <div className="task-picker__group-items">
            {group.tasks.map((task) => (
              <label key={task.taskId} className="task-picker__item">
                {mode === 'multiple' ? (
                  <Checkbox
                    checked={selectedSet.has(task.taskId)}
                    onChange={() => onToggle(task.taskId, false)}
                  />
                ) : (
                  <Radio
                    checked={selectedSet.has(task.taskId)}
                    onChange={() => onToggle(task.taskId, false)}
                  />
                )}
                <span className="task-picker__name">{task.taskName}</span>
                <span className="preview-note">
                  {TASK_TYPE_LABELS[task.taskType as TaskType] ?? task.taskType}
                </span>
                <StatusTag status={task.status} />
              </label>
            ))}
          </div>
        )}
      </div>
    );
  };

  if (targets.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />;
  }

  return (
    <div className="task-picker">
      <Input
        allowClear
        size="small"
        className="task-picker__search"
        prefix={<SearchOutlined />}
        placeholder="搜索项目 / 作业名 / 任务类型"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <div className="task-picker__list">
        {visibleActive.map(renderGroup)}
        {visibleActive.length === 0 && visibleClosed.length === 0 && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的作业" />
        )}
        {visibleClosed.length > 0 && (
          <div className="project-closed-block">
            <button
              type="button"
              className="project-closed-toggle"
              onClick={() => setClosedOpen((v) => !v)}
            >
              {showClosedList ? <DownOutlined /> : <RightOutlined />}
              已关闭项目（{visibleClosed.length}）
            </button>
            {showClosedList && (
              <div className="project-closed-list">{visibleClosed.map(renderGroup)}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
