import { useEffect, useState } from 'react';
import { App, Alert, Form, Input, InputNumber, Modal, Segmented, Select } from 'antd';
import type { Project } from '../../types';
import {
  createFreeEnergyGroup,
  createNebGroup,
  fetchAuxMolecules,
} from '../../api/groups';
import type { AuxMolecule } from '../../api/groups';

interface Props {
  open: boolean;
  project: Project | null;
  initialKind?: 'free_energy' | 'neb';
  onCancel: () => void;
  onCreated: (groupType: 'free_energy' | 'neb') => void;
}

export default function GroupWizardModal({
  open,
  project,
  initialKind = 'free_energy',
  onCancel,
  onCreated,
}: Props) {
  const { message } = App.useApp();
  const [kind, setKind] = useState<'free_energy' | 'neb'>(initialKind);
  const [structures, setStructures] = useState(2);
  const [aux, setAux] = useState<string[]>([]);
  const [auxOptions, setAuxOptions] = useState<AuxMolecule[]>([]);
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      fetchAuxMolecules()
        .then(setAuxOptions)
        .catch(() => setAuxOptions([]));
    }
  }, [open]);

  const reset = () => {
    setKind(initialKind);
    setStructures(2);
    setAux([]);
    setName('');
  };

  const submit = async () => {
    if (!project) return;
    setSubmitting(true);
    try {
      const result =
        kind === 'free_energy'
          ? await createFreeEnergyGroup({
              project: project.name,
              name: name.trim() || undefined,
              structures,
              aux_molecules: aux,
            })
          : await createNebGroup({
              project: project.name,
              name: name.trim() || undefined,
            });
      message.success(
        `${kind === 'free_energy' ? '自由能组' : 'NEB 组'}已创建：${result.group_id}（${result.task_count} 个任务）`,
      );
      if (result.warnings.length > 0) {
        message.warning(result.warnings.join('；'));
      }
      reset();
      onCreated(kind);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建组失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`新建计算流程组 · ${project?.name ?? ''}`}
      open={open}
      onCancel={() => {
        reset();
        onCancel();
      }}
      onOk={() => void submit()}
      okText="创建组"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
    >
      <div style={{ margin: '8px 0 18px' }}>
        <Segmented
          value={kind}
          onChange={(v) => setKind(v as 'free_energy' | 'neb')}
          options={[
            { value: 'free_energy', label: '自由能路径组' },
            { value: 'neb', label: 'NEB 流程组' },
          ]}
        />
      </div>

      <Form layout="vertical">
        <Form.Item label="组名（可选，默认 free_energy_PATH1 / neb_PATH1，目录名使用英文）">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 free_energy_ag111 / neb_ag111"
            allowClear
          />
        </Form.Item>

        {kind === 'free_energy' ? (
          <>
            <Form.Item label="主结构数量（每个结构自动生成 opt + frac 任务）">
              <InputNumber
                min={1}
                max={50}
                value={structures}
                onChange={(v) => setStructures(v ?? 1)}
                style={{ width: 140 }}
              />
            </Form.Item>
            <Form.Item
              label="辅助分子（全局统一存储，跨项目复用）"
              extra="可从已有分子选择或直接输入新标签，创建组时自动注册"
            >
              <Select
                mode="tags"
                value={aux}
                onChange={setAux}
                placeholder="如 H2、O2、N2"
                options={auxOptions.map((m) => ({ value: m.label, label: m.label }))}
              />
            </Form.Item>
          </>
        ) : (
          <Alert
            type="info"
            showIcon
            message="NEB 映像"
            description="映像数量由系统默认生成（00..n+1），无需手动指定"
          />
        )}
      </Form>

      <Alert
        type="info"
        showIcon
        message="创建内容"
        description={
          kind === 'free_energy'
            ? '自动生成 struct_01..N 与辅助分子的 opt/frac 任务目录、默认 INCAR/KPOINTS，并写入 group 元数据。'
            : '自动生成 initial_opt / final_opt / neb_calc 任务与 00..n+1 映像目录（映像 POSCAR 插值待接入）。'
        }
      />
    </Modal>
  );
}
