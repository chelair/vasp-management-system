import { useMemo, useState } from 'react';
import { App, Checkbox, Modal } from 'antd';
import type { TaskRef, TaskType } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  open: boolean;
  targets: TaskRef[];
  onCancel: () => void;
  onConfirm: (targets: TaskRef[]) => void;
}

export default function CopyParamsModal({ open, targets, onCancel, onConfirm }: Props) {
  const { message } = App.useApp();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const groups = useMemo(() => {
    const map = new Map<string, TaskRef[]>();
    for (const t of targets) {
      const list = map.get(t.projectId) ?? [];
      list.push(t);
      map.set(t.projectId, list);
    }
    return Array.from(map.entries()).map(([projectId, tasks]) => ({
      projectId,
      projectName: tasks[0].projectName,
      tasks,
    }));
  }, [targets]);

  const allChecked = targets.length > 0 && selected.size === targets.length;

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const confirm = () => {
    const picked = targets.filter((t) => selected.has(t.taskId));
    if (picked.length === 0) {
      message.warning('请至少选择一个目标任务');
      return;
    }
    onConfirm(picked);
    setSelected(new Set());
  };

  return (
    <Modal
      title="复制 INCAR 参数到其他作业"
      open={open}
      onCancel={() => {
        setSelected(new Set());
        onCancel();
      }}
      onOk={confirm}
      okText={`同步到 ${selected.size} 个作业`}
      cancelText="取消"
      width={560}
      destroyOnClose
    >
      <div className="copy-params">
        <div className="copy-params__toolbar">
          <Checkbox
            checked={allChecked}
            indeterminate={!allChecked && selected.size > 0}
            onChange={(e) => {
              setSelected(
                e.target.checked
                  ? new Set(targets.map((t) => t.taskId))
                  : new Set(),
              );
            }}
          >
            全选
          </Checkbox>
          <span className="preview-note">
            当前参数将覆盖所选任务的 INCAR（共 {targets.length} 个可选）
          </span>
        </div>
        {groups.map((g) => (
          <div key={g.projectId} className="copy-params__group">
            <div className="copy-params__group-name">{g.projectName}</div>
            {g.tasks.map((t) => (
              <label key={t.taskId} className="copy-params__item">
                <Checkbox
                  checked={selected.has(t.taskId)}
                  onChange={() => toggle(t.taskId)}
                />
                <span className="copy-params__name">{t.taskName}</span>
                <span className="preview-note">
                  {TASK_TYPE_LABELS[t.taskType as TaskType] ?? t.taskType}
                </span>
                <StatusTag status={t.status} />
              </label>
            ))}
          </div>
        ))}
      </div>
    </Modal>
  );
}
