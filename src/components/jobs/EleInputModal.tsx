import { useMemo, useState } from 'react';
import { Alert, App, Form, InputNumber, Modal, Radio, Select, Tooltip } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { buildEleInputs } from '../../api/jobs';
import type { Project, Task } from '../../types';

interface Props {
  open: boolean;
  project: Project | null;
  task: Task | null;
  onCancel: () => void;
  onCreated: () => void;
}

const ELEC_TYPES: { value: string; label: string; hint: string; disabled?: boolean }[] = [
  { value: 'pdos', label: 'PDOS', hint: '需要 LWAVE（波函数）与 LORBIT=11（轨道投影），NEDOS 默认 2000' },
  { value: 'bader', label: 'Bader', hint: '需要 LCHARG 与 LAECHG（全电子电荷密度）' },
  { value: 'cohp', label: 'COHP', hint: '需要 LWAVE、ISYM=-1、LORBIT 与较高 NBANDS' },
  { value: 'work_function', label: '功函数', hint: '需要 LVHAR（局域势输出）与 IDIPOL' },
  { value: 'diff_charge', label: '差分电荷', hint: '差分电荷计算后续实现', disabled: true },
];

/** 电子结构任务：构建输入文件（从 opt 导入或外部结构 + 类型参数调整） */
export default function EleInputModal({ open, project, task, onCancel, onCreated }: Props) {
  const { message } = App.useApp();
  const [sourceType, setSourceType] = useState<'opt' | 'external'>('opt');
  const [sourceTaskId, setSourceTaskId] = useState<string | undefined>();
  const [eleType, setEleType] = useState<string>('pdos');
  const [nedos, setNedos] = useState<number | null>(null);
  const [nbands, setNbands] = useState<number | null>(null);
  const [sigma, setSigma] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const optCandidates = useMemo(
    () =>
      (project?.tasks ?? []).filter(
        (t) => t.task_type === 'opt' && t.task_id !== task?.task_id,
      ),
    [project, task],
  );

  const selectedHint = ELEC_TYPES.find((t) => t.value === eleType)?.hint;

  const build = async () => {
    if (!task) return;
    setBuilding(true);
    try {
      const params: Record<string, string | number> = {};
      if (nedos != null) params.NEDOS = nedos;
      if (nbands != null) params.NBANDS = nbands;
      if (sigma != null && sigma.trim()) params.SIGMA = sigma.trim();
      const r = await buildEleInputs(task.task_id, {
        source_type: sourceType,
        source_task_id: sourceType === 'opt' ? sourceTaskId : undefined,
        ele_type: eleType,
        params,
      });
      message.success(`电子结构输入文件已生成：${r.ele_dir}`);
      if (r.warnings.length > 0) message.warning(r.warnings.join('；'));
      onCancel();
      onCreated();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '构建输入文件失败');
    } finally {
      setBuilding(false);
    }
  };

  return (
    <Modal
      title={`构建输入文件 · ${task?.model_name ?? ''}`}
      open={open}
      onCancel={onCancel}
      onOk={() => void build()}
      okText={building ? '构建中…' : '生成输入文件'}
      confirmLoading={building}
      cancelText="取消"
      destroyOnClose
    >
      <Form layout="vertical">
        <Form.Item label="结构来源">
          <Radio.Group
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            options={[
              { value: 'opt', label: '从结构优化任务导入' },
              { value: 'external', label: '外部结构（本地 files/POSCAR）' },
            ]}
          />
        </Form.Item>
        {sourceType === 'opt' && (
          <Form.Item label="来源结构优化任务">
            <Select
              style={{ width: '100%' }}
              placeholder="选择已完成/运行中的 opt 任务"
              value={sourceTaskId}
              onChange={setSourceTaskId}
              options={optCandidates.map((t) => ({
                value: t.task_id,
                label: `${t.model_name}（${t.status}）`,
              }))}
            />
          </Form.Item>
        )}
        <Form.Item label="电子结构类型">
          <Radio.Group value={eleType} onChange={(e) => setEleType(e.target.value)}>
            {ELEC_TYPES.map((t) => (
              <Radio key={t.value} value={t.value} disabled={t.disabled}>
                {t.label}
              </Radio>
            ))}
          </Radio.Group>
        </Form.Item>
        {selectedHint && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 14 }}
            message={
              <span>
                {selectedHint}
                <Tooltip title="系统会自动设置对应参数，可在下方覆盖或后续在 INCAR 编辑器中修改">
                  <QuestionCircleOutlined style={{ marginLeft: 8, color: '#5B8DEF' }} />
                </Tooltip>
              </span>
            }
          />
        )}
        <div className="filter-bar" style={{ gap: 12 }}>
          <Form.Item label="NEDOS（可留空用默认）" style={{ marginBottom: 0 }}>
            <InputNumber min={100} max={20000} value={nedos} onChange={setNedos} />
          </Form.Item>
          <Form.Item label="NBANDS（可留空用默认）" style={{ marginBottom: 0 }}>
            <InputNumber min={10} max={5000} value={nbands} onChange={setNbands} />
          </Form.Item>
          <Form.Item label="SIGMA（可留空）" style={{ marginBottom: 0 }}>
            <InputNumber
              min={0.001}
              step={0.01}
              value={sigma != null ? Number(sigma) : undefined}
              onChange={(v) => setSigma(v != null ? String(v) : null)}
            />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
