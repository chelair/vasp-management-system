import { useState } from 'react';
import { Alert, App, Modal } from 'antd';
import { createContinuation } from '../../api/jobs';
import type { Task } from '../../types';

interface Props {
  open: boolean;
  task: Task | null;
  onCancel: () => void;
  onSameTypeCreated: (result: {
    task_id: string;
    con: string;
    remote_dir: string;
    warnings: string[];
  }, /** 发起续算的父任务 id（用于刷新它的输入状态） */ parentTaskId: string) => void;
}

/** 同类型续算：按任务类型由后端分发（opt/frac 通用 conN、neb 映像续算、ele 不支持） */
export default function ContinuationModal({
  open,
  task,
  onCancel,
  onSameTypeCreated,
}: Props) {
  const { message, modal } = App.useApp();
  const [creating, setCreating] = useState(false);

  const confirmCreate = async () => {
    if (!task) return;
    setCreating(true);
    try {
      const r = await createContinuation(task.task_id);
      if (r.action === 'created') {
        message.success(r.message || `续算目录已创建：${r.con}`);
        if (r.warnings.length > 0) {
          message.warning(r.warnings.join('；'));
        }
        onCancel();
        onSameTypeCreated(r as {
          task_id: string;
          con: string;
          remote_dir: string;
          warnings: string[];
        }, task.task_id);
      } else if (r.action === 'running') {
        modal.warning({
          title: '任务正在运行',
          content: r.message,
        });
        onCancel();
      } else if (r.action === 'input_complete_but_not_finished') {
        modal.info({
          title: '当前目录未正常完成',
          content: r.message,
        });
        onCancel();
      } else {
        modal.warning({
          title: '输入文件不完整',
          content: `${r.message}\n缺失文件：${(r.missing_files ?? []).join('、') || '未知'}`,
        });
        onCancel();
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '续算失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <Modal
      title={`创建续算 · ${task?.model_name ?? ''}`}
      open={open}
      onCancel={onCancel}
      onOk={() => void confirmCreate()}
      okText={creating ? '创建中…' : '创建续算'}
      confirmLoading={creating}
      cancelText="取消"
      destroyOnClose
    >
      <div className="job-path-preview">
        <div>
          <span>续算目录</span>
          <code>{task?.remote_dir ?? ''}/con…（服务器端自动编号）</code>
        </div>
      </div>
      <Alert
        type="success"
        showIcon
        message="同类型续算（服务器端完成）"
        description="定位最新有效输出目录（conN / 主目录）→ 创建 conN+1 → 复制 CONTCAR→POSCAR、POTCAR、KPOINTS、提交脚本（WAVECAR 移动）→ INCAR 修改 ISTART=1 / ICHARG=0。NEB 任务按映像目录处理；电子结构任务不支持续算。"
      />
    </Modal>
  );
}
