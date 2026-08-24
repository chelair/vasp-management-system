import { useMemo, useState } from 'react';
import { Alert, App, Modal, Segmented, Select, Tag } from 'antd';
import { FileDoneOutlined, SwapOutlined } from '@ant-design/icons';
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
  onConfirm: (payload: ContinuationPayload) => void;
}

const CROSS_PREFIX: Record<string, string> = {
  structure_opt: 'so',
  electronic_structure: 'es',
  free_energy: 'fe',
  neb: 'neb',
};

export default function ContinuationModal({
  open,
  task,
  project,
  taskTypes,
  onCancel,
  onConfirm,
}: Props) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<'same' | 'cross'>('same');
  const [targetType, setTargetType] = useState<TaskType>('electronic_structure');

  const crossTypes = useMemo(
    () =>
      taskTypes.filter(
        (t) => t.type !== 'frequency' && t.type !== 'structure_opt',
      ),
    [taskTypes],
  );

  const sameIndex = useMemo(() => {
    if (!project || !task) return 1;
    const prefix = `${task.model_name}_con`;
    return project.tasks.filter((t) => t.model_name.startsWith(prefix)).length + 1;
  }, [project, task]);

  const crossIndex = useMemo(() => {
    if (!project || !task) return 1;
    const prefix = `${task.model_name}_${CROSS_PREFIX[targetType] ?? 'x'}`;
    return project.tasks.filter((t) => t.model_name.startsWith(prefix)).length + 1;
  }, [project, task, targetType]);

  const name = task
    ? mode === 'same'
      ? `${task.model_name}_con${sameIndex}`
      : `${task.model_name}_${CROSS_PREFIX[targetType] ?? 'x'}${crossIndex}`
    : '';

  const type = mode === 'same' ? (task?.task_type as TaskType) : targetType;
  const localDir = project ? `${JOB_DIRS.localRoot}/${project.name}/${type}/${name}` : '';
  const remoteDir = project ? `${JOB_DIRS.remoteBase}/${project.name}/${type}/${name}` : '';

  const ops =
    mode === 'same'
      ? [
          '复制 CONTCAR → POSCAR（从上次中断处继续）',
          '复制 INCAR / KPOINTS / POTCAR 到新目录',
          'INCAR 修改：ISTART=1（读 WAVECAR）、ICHARG=0',
        ]
      : [
          '复制源任务 CONTCAR → 新任务 POSCAR',
          '复制源任务 POTCAR（必要时更新 KPOINTS）',
          `生成目标类型 ${TASK_TYPE_LABELS[targetType] ?? targetType} 的 INCAR 模板`,
          'INCAR 修改：ICHARG=0、NSW=0（单点/电子结构）',
        ];

  const confirm = () => {
    if (!task || !project) return;
    onConfirm({
      name,
      taskType: type,
      localDir,
      remoteDir,
      ops,
      crossType: mode === 'cross',
    });
    message.success(`续算子项已创建：${name}`);
    setMode('same');
    setTargetType('electronic_structure');
  };

  return (
    <Modal
      title={`创建续算 · ${task?.model_name ?? ''}`}
      open={open}
      onCancel={() => {
        setMode('same');
        onCancel();
      }}
      onOk={confirm}
      okText="创建续算"
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
          <span>新子项名称</span>
          <code>{name}</code>
        </div>
        <div>
          <span>本地目录</span>
          <code>{localDir}</code>
        </div>
        <div>
          <span>远程目录</span>
          <code>{remoteDir}</code>
        </div>
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
        type="info"
        showIcon
        message="框架阶段"
        description="创建后在当前会话生成新子项并自动选中；正式版将由后端在本地与远程目录执行实际文件复制。"
      />
    </Modal>
  );
}
