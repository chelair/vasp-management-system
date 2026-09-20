import { useEffect, useState } from 'react';
import { App, Checkbox, Modal } from 'antd';
import type { TaskRef } from '../../types';
import TaskPickerList from './TaskPickerList';

interface Props {
  open: boolean;
  title: string;
  targets: TaskRef[];
  /** 单选 = 只挑一个作业（复制结构）；多选 = 批量（同步 INCAR 参数） */
  mode: 'single' | 'multiple';
  onCancel: () => void;
  /** 回传选中的任务 id（单选恒为 1 个） */
  onConfirm: (taskIds: string[]) => void;
  /** 工具栏说明文案 */
  hint?: string;
  /** 确认按钮文案；多选可传函数按数量生成 */
  okText?: string | ((count: number) => string);
  defaultExpandedIds?: string[];
  initialSelectedIds?: string[];
}

/**
 * 通用任务选择弹窗（v0.8.9）：INCAR 参数复制到其他作业（多选）与
 * 从其他任务复制 POSCAR（单选）共用。列表按项目分组、可折叠、带搜索，
 * 已关闭项目折叠在最后（见 `TaskPickerList`）。
 */
export default function TaskPickerModal({
  open,
  title,
  targets,
  mode,
  onCancel,
  onConfirm,
  hint,
  okText,
  defaultExpandedIds,
  initialSelectedIds,
}: Props) {
  const { message } = App.useApp();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSelectedIds ?? []));

  // 每次打开都回到初始选择（不被上一次的操作影响）
  useEffect(() => {
    if (open) setSelected(new Set(initialSelectedIds ?? []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const toggle = (taskId: string) => {
    setSelected((prev) => {
      if (mode === 'single') return new Set([taskId]);
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const toggleGroup = (taskIds: string[], checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of taskIds) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  const allChecked = targets.length > 0 && selected.size === targets.length;
  const confirm = () => {
    if (selected.size === 0) {
      message.warning(mode === 'single' ? '请选择一个作业' : '请至少选择一个目标任务');
      return;
    }
    onConfirm(Array.from(selected));
  };

  const okLabel =
    typeof okText === 'function'
      ? okText(selected.size)
      : okText ?? (mode === 'single' ? '确定' : `同步到 ${selected.size} 个作业`);

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={confirm}
      okText={okLabel}
      okButtonProps={{ disabled: selected.size === 0 }}
      cancelText="取消"
      width={560}
      destroyOnClose
    >
      <div className="task-picker-modal">
        <div className="task-picker__toolbar">
          {mode === 'multiple' && (
            <Checkbox
              checked={allChecked}
              indeterminate={selected.size > 0 && !allChecked}
              onChange={(e) =>
                setSelected(e.target.checked ? new Set(targets.map((t) => t.taskId)) : new Set())
              }
            >
              全选
            </Checkbox>
          )}
          <span className="preview-note">
            {hint ?? (mode === 'single' ? '选择要复制结构来源的作业' : '当前参数将覆盖所选任务的 INCAR')}
            {mode === 'multiple' ? `（共 ${targets.length} 个可选）` : ''}
          </span>
        </div>
        <TaskPickerList
          targets={targets}
          mode={mode}
          selectedIds={Array.from(selected)}
          onToggle={(taskId) => toggle(taskId)}
          onToggleGroup={mode === 'multiple' ? toggleGroup : undefined}
          defaultExpandedIds={defaultExpandedIds}
          emptyText="没有可选的作业"
        />
      </div>
    </Modal>
  );
}
