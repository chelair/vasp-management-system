import { useMemo, useState } from 'react';
import { Alert, App, Modal, Segmented, Select, Tag } from 'antd';
import { FileDoneOutlined, SwapOutlined } from '@ant-design/icons';
import { createContinuation } from '../../api/jobs';
import type {
  ContinuationPayload,
  Project,
  Task,
  TaskType,
  TaskTypeOption,
} from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import { JOB_DIRS } from '../../data/mock/cluster';

interface Props {
  open: boolean;
  task: Task | null;
  project: Project | null;
  taskTypes: TaskTypeOption[];
  onCancel: () => void;
  /** 跨类型续算（原逻辑，会话级创建） */
  onConfirm: (payload: ContinuationPayload) => void;
  /** 同类型续算创建成功后（后端返回续算信息） */
  onSameTypeCreated: (result: {
    task_id: string;
    con: string;
    remote_dir: string;
    warnings: string[];
  }) => void;
}

const CROSS_PREFIX: Record<string, string> = {
  opt: 'opt',
  frac: 'frac',
  neb: 'neb',
  ele: 'ele',
};

export default function ContinuationModal({
  open,
  task,
  project,
  taskTypes,
  onCancel,
  onConfirm,
  onSameTypeCreated,
}: Props) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<'same' | 'cross'>('same');
  const [targetType, setTargetType] = useState<TaskType>('ele');
  const [creating, setCreating] = useState(false);

  const crossTypes = useMemo(
    () => taskTypes.filter((t) => ['opt', 'frac', 'neb', 'ele'].includes(t.type)),
    [taskTypes],
  );

  const crossIndex = useMemo(() => {
    if (!project || !task) return 1;
    const prefix = `${task.model_name}_${CROSS_PREFIX[targetType] ?? 'x'}`;
    return project.tasks.filter((t) => t.model_name.startsWith(prefix)).length + 1;
  }, [project, task, targetType]);

  const crossName = task
    ? `${task.model_name}_${CROSS_PREFIX[targetType] ?? 'x'}${crossIndex}`
    : '';
  const type = mode === 'same' ? (task?.task_type as TaskType) : targetType;
  const localDir = project ? `${JOB_DIRS.localRoot}/${project.name}/${type}/${crossName}` : '';
  const remoteDir = project
    ? `${JOB_DIRS.remoteBase}/${project.name}/${type}/${crossName}`
    : '';

  const ops =
    mode === 'same'
      ? [
          '在远程服务器定位最新有效输出目录（conN / 主目录）',
          '创建续算目录 conN+1，复制 CONTCAR→POSCAR、POTCAR、KPOINTS、提交脚本；WAVECAR 采用移动（省磁盘）',
          'INCAR 修改：ISTART=1（读 WAVECAR）、ICHARG=0',
          '登记续算子任务（parent_task_id 指向原任务）',
        ]
      : [
          '复制源任务 CONTCAR → 新任务 POSCAR',
          '复制源任务 POTCAR（必要时更新 KPOINTS）',
          `生成目标类型 ${TASK_TYPE_LABELS[targetType] ?? targetType} 的 INCAR 模板`,
          'INCAR 修改：ICHARG=0、NSW=0（单点/电子结构）',
        ];

  const confirmSame = async () => {
    if (!task) return;
    setCreating(true);
    try {
      const r = await createContinuation(task.task_id);
      message.success(`续算目录已创建：${r.con}（${r.remote_dir}）`);
      if (r.warnings.length > 0) {
        message.warning(r.warnings.join('；'));
      }
      setMode('same');
      onCancel();
      onSameTypeCreated(r);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同类型续算失败');
    } finally {
      setCreating(false);
    }
  };

  const confirmCross = () => {
    if (!task || !project) return;
    onConfirm({
      name: crossName,
      taskType: type,
      localDir,
      remoteDir,
      ops,
      crossType: true,
    });
    message.success(`跨类型续算子项已创建：${crossName}`);
    setMode('same');
    setTargetType('ele');
  };

  return (
    <Modal
      title={`创建续算 · ${task?.model_name ?? ''}`}
      open={open}
      onCancel={() => {
        setMode('same');
        onCancel();
      }}
      onOk={mode === 'same' ? confirmSame : confirmCross}
      okText={creating ? '创建中…' : '创建续算'}
      confirmLoading={creating}
      cancelText="取消"
      destroyOnClose
    >
      <div style={{ margin: '8px 0 16px' }}>
        <Segmented
          value={mode}
          onChange={(v) => setMode(v as 'same' | 'cross')}
          options={[
            {
              value: 'same',
              label: (
                <span>
                  <FileDoneOutlined /> 同类型续算
                </span>
              ),
            },
            {
              value: 'cross',
              label: (
                <span>
                  <SwapOutlined /> 跨类型续算
                </span>
              ),
            },
          ]}
        />
      </div>

      {mode === 'cross' && (
        <div style={{ marginBottom: 12 }}>
          <div className="preview-note" style={{ marginBottom: 6 }}>
            目标作业类型
          </div>
          <Select
            style={{ width: '100%' }}
            value={targetType}
            onChange={(v: TaskType) => setTargetType(v)}
            options={crossTypes.map((t) => ({
              value: t.type,
              label: `${t.description}（权重 ${t.workload_weight}）`,
            }))}
          />
        </div>
      )}

      <div className="job-path-preview">
        <div>
          <span>{mode === 'same' ? '续算目录' : '新子项名称'}</span>
          <code>
            {mode === 'same' ? `${task?.remote_dir ?? ''}/con…（服务器端编号）` : crossName}
          </code>
        </div>
        {mode === 'cross' && (
          <>
            <div>
              <span>本地目录</span>
              <code>{localDir}</code>
            </div>
            <div>
              <span>远程目录</span>
              <code>{remoteDir}</code>
            </div>
          </>
        )}
      </div>

      <div className="job-ops-list">
        <div className="job-ops-list__title">文件操作</div>
        {ops.map((op) => (
          <div key={op} className="job-ops-item">
            <Tag color="processing">文件</Tag>
            {op}
          </div>
        ))}
      </div>

      <Alert
        type={mode === 'same' ? 'success' : 'info'}
        showIcon
        message={
          mode === 'same' ? '同类型续算（服务器端完成）' : '跨类型续算（框架阶段）'
        }
        description={
          mode === 'same'
            ? '点击创建后由后端通过 SSH 在远程服务器生成 conN 目录并复制/修改文件，不经过本地；完成后自动登记续算子任务并选中。'
            : '跨类型续算在会话内生成子项；真实文件生成后续接入。'
        }
      />
    </Modal>
  );
}
