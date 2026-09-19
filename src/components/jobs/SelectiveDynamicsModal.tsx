import { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Checkbox, InputNumber, Modal, Radio, Select, Tooltip } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import type { TaskInputState } from '../../api/jobs';
import { applySelectiveDynamics } from '../../api/jobs';
import { parsePoscar } from '../../utils/poscar';
import type { AtomRef } from './Structure3DFrame';

interface Props {
  open: boolean;
  taskId: string;
  /** 页面上的 POSCAR 文本（编辑器的当前内容） */
  poscarContent: string | null;
  /** 结构图上选中的原子（poscarIndex 与 POSCAR 坐标行一致，1 起） */
  selectedAtoms: AtomRef[];
  onClose: () => void;
  /** 生成成功：回传新文本 + 刷新后的输入状态 */
  onApplied: (text: string, state: TaskInputState, note: string) => void;
}

export default function SelectiveDynamicsModal({
  open,
  taskId,
  poscarContent,
  selectedAtoms,
  onClose,
  onApplied,
}: Props) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<'manual' | 'elements' | 'z_range'>('manual');
  const [numbering, setNumbering] = useState<'element' | 'global'>('element');
  const [labels, setLabels] = useState(true);
  const [syncRemote, setSyncRemote] = useState(false);
  const [elements, setElements] = useState<string[]>([]);
  const [zRange, setZRange] = useState<[number, number]>([0, 0.25]);
  const [busy, setBusy] = useState(false);

  const info = useMemo(
    () => (poscarContent ? parsePoscar(poscarContent) : null),
    [poscarContent],
  );

  useEffect(() => {
    if (!open) return;
    setMode(selectedAtoms.length > 0 ? 'manual' : 'elements');
    setElements((prev) => (prev.length > 0 ? prev : info ? [info.elements[0]] : []));
  }, [open, selectedAtoms.length, info]);

  const selectionLabel = useMemo(
    () =>
      selectedAtoms
        .slice()
        .sort((a, b) => a.poscarIndex - b.poscarIndex)
        .map((a) => `${a.element}${a.poscarIndex}`)
        .join(', '),
    [selectedAtoms],
  );

  const submit = async () => {
    setBusy(true);
    try {
      const r = await applySelectiveDynamics(taskId, {
        content: poscarContent ?? undefined,
        mode,
        atoms:
          mode === 'manual'
            ? selectedAtoms.map((a) => ({ element: a.element, poscarIndex: a.poscarIndex }))
            : undefined,
        elements: mode === 'elements' ? elements : undefined,
        zRange: mode === 'z_range' ? zRange : undefined,
        numbering,
        labels,
        syncRemote,
      });
      const note = r.synced_remote
        ? `已固定原子并同步到远端 ${r.remote_dir}${r.remote_backup ? `（原文件备份 ${r.remote_backup}）` : ''}`
        : '已固定原子并写入本地 POSCAR（旧文件备份为 old_POSCAR）';
      message.success(note);
      onApplied(r.text, r.state, r.summary);
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '生成 Selective Dynamics 失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="固定原子（生成 Selective Dynamics 的 POSCAR）"
      width={620}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          icon={<LockOutlined />}
          loading={busy}
          onClick={() => void submit()}
        >
          生成
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="固定原子 = 该原子三向都写 F（F F F），其余写 T T T；原文件会先备份为 old_POSCAR"
        description="生成结果写回本地 files/POSCAR 并刷新「本次计算值」；勾选「同时同步到远端」才会写入远端最新目录。"
      />

      <div className="sd-form">
        <div className="sd-row">
          <span className="sd-label">固定规则</span>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            optionType="button"
            buttonStyle="solid"
            options={[
              {
                value: 'manual',
                label: `选中原子（${selectedAtoms.length}）`,
                disabled: selectedAtoms.length === 0,
              },
              { value: 'elements', label: '整个元素' },
              { value: 'z_range', label: '按高度区间' },
            ]}
          />
        </div>

        {mode === 'manual' && (
          <div className="sd-row">
            <span className="sd-label">选中的原子</span>
            <Tooltip title={selectionLabel || '在左侧结构图上点击 / Ctrl 多选 / Shift 拖拽框选'}>
              <span className="sd-value">
                {selectionLabel || '（未选中：请先在结构图上选原子）'}
              </span>
            </Tooltip>
          </div>
        )}

        {mode === 'elements' && (
          <div className="sd-row">
            <span className="sd-label">元素</span>
            <Select
              mode="multiple"
              value={elements}
              onChange={setElements}
              style={{ minWidth: 260 }}
              placeholder="选择要固定的元素"
              options={(info?.elements ?? []).map((el) => ({ value: el, label: el }))}
            />
          </div>
        )}

        {mode === 'z_range' && (
          <div className="sd-row">
            <span className="sd-label">分数坐标 z</span>
            <InputNumber
              min={-1}
              max={2}
              step={0.05}
              value={zRange[0]}
              onChange={(v) => setZRange([Number(v ?? 0), zRange[1]])}
              style={{ width: 110 }}
            />
            <span>～</span>
            <InputNumber
              min={-1}
              max={2}
              step={0.05}
              value={zRange[1]}
              onChange={(v) => setZRange([zRange[0], Number(v ?? 0)])}
              style={{ width: 110 }}
            />
            <span className="preview-note">落在区间内的原子写 F F F（分数坐标，Direct 直接取 z）</span>
          </div>
        )}

        <div className="sd-row">
          <span className="sd-label">编号方式</span>
          <Radio.Group
            value={numbering}
            onChange={(e) => setNumbering(e.target.value)}
            optionType="button"
            buttonStyle="solid"
            options={[
              { value: 'element', label: '元素内序号（Fe1…Fe24, S1…S32）' },
              { value: 'global', label: '全局序号（Fe1…S56）' },
            ]}
          />
        </div>

        <div className="sd-row">
          <span className="sd-label">其它</span>
          <Checkbox checked={labels} onChange={(e) => setLabels(e.target.checked)}>
            坐标行末尾附「元素+序号」标签
          </Checkbox>
          <Checkbox checked={syncRemote} onChange={(e) => setSyncRemote(e.target.checked)}>
            生成后同时同步到远端（备份 old_POSCAR）
          </Checkbox>
        </div>
      </div>
    </Modal>
  );
}
