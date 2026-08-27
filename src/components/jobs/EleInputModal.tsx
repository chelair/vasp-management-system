import { useMemo, useState } from 'react';
import { Alert, App, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Switch, Tooltip } from 'antd';
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
  { value: 'pdos', label: 'PDOS', hint: '需要轨道投影 LORBIT（10/11/12），可设置能量范围 EMIN/EMAX 与 NEDOS' },
  { value: 'bader', label: 'Bader', hint: '需要 LCHARG 与 LAECHG（全电子电荷密度）' },
  { value: 'cohp', label: 'COHP', hint: '需要 ISYM=-1、LWAVE、LORBIT 与较高 NBANDS' },
  { value: 'work_function', label: '功函数', hint: '需要 LVHAR（局域势输出）与偶极校正 LDIPOL + DIPOL 矫正中心' },
  { value: 'diff_charge', label: '差分电荷', hint: '差分电荷计算后续实现', disabled: true },
];

/** 电子结构任务：构建输入文件（从 opt 导入或外部结构 + 类型参数调整） */
export default function EleInputModal({ open, project, task, onCancel, onCreated }: Props) {
  const { message, modal } = App.useApp();
  const [sourceType, setSourceType] = useState<'opt' | 'external'>('opt');
  const [sourceTaskId, setSourceTaskId] = useState<string | undefined>();
  const [eleTypes, setEleTypes] = useState<string[]>(['pdos']);
  const [lorbit, setLorbit] = useState<number | null>(11);
  const [emin, setEmin] = useState<number | null>(-10);
  const [emax, setEmax] = useState<number | null>(10);
  const [nedos, setNedos] = useState<number | null>(1000);
  const [nbands, setNbands] = useState<number | null>(400);
  const [ldipol, setLdipol] = useState(true);
  const [dipolX, setDipolX] = useState('');
  const [dipolY, setDipolY] = useState('');
  const [dipolZ, setDipolZ] = useState('');
  const [building, setBuilding] = useState(false);

  const optCandidates = useMemo(
    () =>
      (project?.tasks ?? []).filter(
        (t) => t.task_type === 'opt' && t.task_id !== task?.task_id,
      ),
    [project, task],
  );

  const selectedHints = ELEC_TYPES.filter((t) => eleTypes.includes(t.value)).map(
    (t) => t.hint,
  );

  const build = async () => {
    if (!task) return;
    setBuilding(true);
    try {
      const params: Record<string, string | number> = {};
      if (lorbit != null) params.LORBIT = lorbit;
      if (emin != null) params.EMIN = emin;
      if (emax != null) params.EMAX = emax;
      if (nedos != null) params.NEDOS = nedos;
      if (nbands != null) params.NBANDS = nbands;
      if (!ldipol) {
        params.LDIPOL = '.FALSE.';
      } else if (dipolX.trim() || dipolY.trim() || dipolZ.trim()) {
        params.DIPOL = `${dipolX.trim() || '0'} ${dipolY.trim() || '0'} ${dipolZ.trim() || '0'}`;
      }
      const r = await buildEleInputs(task.task_id, {
        source_type: sourceType,
        source_task_id: sourceType === 'opt' ? sourceTaskId : undefined,
        ele_types: eleTypes,
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
          <Checkbox.Group
            value={eleTypes}
            onChange={(vals) => setEleTypes(vals as string[])}
            options={ELEC_TYPES.map((t) => ({
              label: t.label,
              value: t.value,
              disabled: t.disabled,
            }))}
          />
        </Form.Item>
        {selectedHints.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 14 }}
            message={
              <span>
                {selectedHints.join('；')}
                <Tooltip title="系统会自动设置对应参数，可在下方覆盖或后续在 INCAR 编辑器中修改">
                  <QuestionCircleOutlined style={{ marginLeft: 8, color: '#5B8DEF' }} />
                </Tooltip>
              </span>
            }
          />
        )}
        {(eleTypes.includes('pdos') || eleTypes.includes('cohp')) && (
          <Form.Item label="LORBIT（轨道投影，10 / 11 / 12）">
            <Select
              style={{ width: 140 }}
              value={lorbit}
              onChange={setLorbit}
              options={[10, 11, 12].map((v) => ({ value: v, label: String(v) }))}
            />
          </Form.Item>
        )}
        {eleTypes.includes('pdos') && (
          <div className="filter-bar" style={{ gap: 12 }}>
            <Form.Item label="EMIN" style={{ marginBottom: 0 }}>
              <InputNumber value={emin} onChange={setEmin} />
            </Form.Item>
            <Form.Item label="EMAX" style={{ marginBottom: 0 }}>
              <InputNumber value={emax} onChange={setEmax} />
            </Form.Item>
            <Form.Item label="NEDOS" style={{ marginBottom: 0 }}>
              <InputNumber min={100} max={20000} value={nedos} onChange={setNedos} />
            </Form.Item>
          </div>
        )}
        {eleTypes.includes('cohp') && (
          <Form.Item label="NBANDS">
            <InputNumber min={10} max={5000} value={nbands} onChange={setNbands} />
          </Form.Item>
        )}
        {eleTypes.includes('work_function') && (
          <>
            <Form.Item label="偶极校正 LDIPOL（默认开启）">
              <Switch
                checked={ldipol}
                onChange={(v) => {
                  if (!v) {
                    modal.warning({
                      title: '关闭偶极校正',
                      content:
                        '关闭后可能导致上下表面不对称结构的真空能级倾斜，建议保持开启并设置矫正中心。',
                    });
                  }
                  setLdipol(v);
                }}
              />
            </Form.Item>
            {ldipol && (
              <div className="filter-bar" style={{ gap: 12 }}>
                <Form.Item label="矫正中心 x" style={{ marginBottom: 0 }}>
                  <Input style={{ width: 100 }} value={dipolX} onChange={(e) => setDipolX(e.target.value)} />
                </Form.Item>
                <Form.Item label="矫正中心 y" style={{ marginBottom: 0 }}>
                  <Input style={{ width: 100 }} value={dipolY} onChange={(e) => setDipolY(e.target.value)} />
                </Form.Item>
                <Form.Item label="矫正中心 z" style={{ marginBottom: 0 }}>
                  <Input style={{ width: 100 }} value={dipolZ} onChange={(e) => setDipolZ(e.target.value)} />
                </Form.Item>
              </div>
            )}
          </>
        )}
      </Form>
    </Modal>
  );
}
