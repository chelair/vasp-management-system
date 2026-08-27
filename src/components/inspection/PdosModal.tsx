import { useState } from 'react';
import { App, Button, Input, Modal, Radio, Space } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { analyzePdos } from '../../api/jobs';

interface Props {
  open: boolean;
  taskId: string | undefined;
  onCancel: () => void;
}

interface PdosGroup {
  elements: string;
  orbitals: string;
}

/** PDOS 分析对话框：vaspkit 111（总态密度）/ 113（投影轨道态密度）/ 115（自定义） */
export default function PdosModal({ open, taskId, onCancel }: Props) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<number>(111);
  const [groups, setGroups] = useState<PdosGroup[]>([{ elements: '', orbitals: '' }]);
  const [running, setRunning] = useState(false);
  const [files, setFiles] = useState<string[]>([]);

  const run = async () => {
    if (!taskId) return;
    if (mode === 115 && !groups.some((g) => g.elements.trim())) {
      message.warning('自定义分析至少需要一组元素');
      return;
    }
    setRunning(true);
    setFiles([]);
    try {
      const r = await analyzePdos(taskId, {
        mode,
        groups: mode === 115 ? groups.filter((g) => g.elements.trim()) : undefined,
      });
      message.success(`PDOS 分析完成，回传 ${r.files.length} 个文件`);
      setFiles(r.files);
    } catch (err) {
      message.error(err instanceof Error ? err.message : 'PDOS 分析失败');
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal
      title="PDOS 分析"
      open={open}
      onCancel={onCancel}
      onOk={() => void run()}
      okText={running ? '分析中…' : '开始分析'}
      confirmLoading={running}
      cancelText="取消"
      destroyOnClose
    >
      <Radio.Group
        value={mode}
        onChange={(e) => setMode(e.target.value)}
        style={{ marginBottom: 14 }}
        options={[
          { value: 111, label: '总态密度（vaspkit 111）' },
          { value: 113, label: '投影轨道态密度（vaspkit 113）' },
          { value: 115, label: '自定义选择（vaspkit 115）' },
        ]}
      />

      {mode === 115 && (
        <div style={{ marginBottom: 8 }}>
          <div className="preview-note" style={{ marginBottom: 6 }}>
            每组：元素/原子序号（空格隔开）+ 轨道（如 d、pz）
          </div>
          <Space direction="vertical" style={{ width: '100%' }}>
            {groups.map((g, i) => (
              <Space key={i} style={{ width: '100%' }}>
                <Input
                  placeholder="如 Fe 或 1 2"
                  value={g.elements}
                  onChange={(e) =>
                    setGroups((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, elements: e.target.value } : x)),
                    )
                  }
                  style={{ width: 180 }}
                />
                <Input
                  placeholder="轨道，如 d"
                  value={g.orbitals}
                  onChange={(e) =>
                    setGroups((prev) =>
                      prev.map((x, j) => (j === i ? { ...x, orbitals: e.target.value } : x)),
                    )
                  }
                  style={{ width: 140 }}
                />
                <Button
                  danger
                  type="text"
                  icon={<DeleteOutlined />}
                  disabled={groups.length <= 1}
                  onClick={() => setGroups((prev) => prev.filter((_, j) => j !== i))}
                />
              </Space>
            ))}
          </Space>
          <Button
            size="small"
            icon={<PlusOutlined />}
            style={{ marginTop: 8 }}
            onClick={() => setGroups((prev) => [...prev, { elements: '', orbitals: '' }])}
          >
            添加一组
          </Button>
        </div>
      )}

      {files.length > 0 && (
        <div className="inspection-detail__section">
          <h3>生成文件（已回传本地）</h3>
          {files.map((f) => (
            <div key={f} className="preview-note">
              {f}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
