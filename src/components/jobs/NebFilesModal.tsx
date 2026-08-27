import { useMemo, useState } from 'react';
import { Alert, App, Form, InputNumber, Modal, Select } from 'antd';
import { createNebFiles } from '../../api/jobs';
import type { Project, Task } from '../../types';

interface Props {
  open: boolean;
  project: Project | null;
  nebTask: Task | null;
  onCancel: () => void;
  onCreated: () => void;
}

/** NEB 任务：根据初末态 opt 任务创建计算文件（nebmake.pl 插值映像） */
export default function NebFilesModal({
  open,
  project,
  nebTask,
  onCancel,
  onCreated,
}: Props) {
  const { message } = App.useApp();
  const [initialId, setInitialId] = useState<string | undefined>();
  const [finalId, setFinalId] = useState<string | undefined>();
  const [numImages, setNumImages] = useState(3);
  const [building, setBuilding] = useState(false);

  const optCandidates = useMemo(
    () => (project?.tasks ?? []).filter((t) => t.task_type === 'opt'),
    [project],
  );

  const create = async () => {
    if (!nebTask) return;
    if (!initialId || !finalId) {
      message.warning('请选择初态和末态优化任务');
      return;
    }
    setBuilding(true);
    try {
      const r = await createNebFiles(nebTask.task_id, {
        initial_opt_task_id: initialId,
        final_opt_task_id: finalId,
        num_images: numImages,
      });
      message.success(`NEB 计算文件已生成：${r.neb_dir}（${r.images.length} 个映像）`);
      onCancel();
      onCreated();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建 NEB 计算文件失败');
    } finally {
      setBuilding(false);
    }
  };

  return (
    <Modal
      title={`创建计算文件 · ${nebTask?.model_name ?? ''}`}
      open={open}
      onCancel={onCancel}
      onOk={() => void create()}
      okText={building ? '创建中…' : '创建计算文件'}
      confirmLoading={building}
      cancelText="取消"
      destroyOnClose
    >
      <Form layout="vertical">
        <Form.Item label="初态优化任务（IS）">
          <Select
            style={{ width: '100%' }}
            placeholder="选择初态 opt 任务"
            value={initialId}
            onChange={setInitialId}
            options={optCandidates.map((t) => ({
              value: t.task_id,
              label: `${t.model_name}（${t.status}）`,
            }))}
          />
        </Form.Item>
        <Form.Item label="末态优化任务（FS）">
          <Select
            style={{ width: '100%' }}
            placeholder="选择末态 opt 任务"
            value={finalId}
            onChange={setFinalId}
            options={optCandidates.map((t) => ({
              value: t.task_id,
              label: `${t.model_name}（${t.status}）`,
            }))}
          />
        </Form.Item>
        <Form.Item label="中间态数量（生成 00..NN 映像，NN = 中间态 + 1）">
          <InputNumber
            min={1}
            max={30}
            value={numImages}
            onChange={(v) => setNumImages(v ?? 3)}
          />
        </Form.Item>
      </Form>
      <Alert
        type="info"
        showIcon
        message="创建内容"
        description="从初末态 opt 最新 CONTCAR 生成 00/NN 端点，nebmake.pl 线性插值中间映像；POTCAR/KPOINTS/提交脚本复制到 NEB 目录；INCAR 设置 IMAGES / SPRING=-5。"
      />
    </Modal>
  );
}
