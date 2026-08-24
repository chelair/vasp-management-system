import { useMemo, useState } from 'react';
import { App, Button, Card, Descriptions, Select, Tag, Upload } from 'antd';
import { CloudUploadOutlined, CopyOutlined, FileTextOutlined } from '@ant-design/icons';
import type { TaskRef } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import { parsePoscar } from '../../utils/poscar';

interface Props {
  poscarContent: string | null;
  poscarPath: string | null;
  copyTargets: TaskRef[];
  onImport: (content: string) => void;
  onCopyFromTask: (taskId: string) => void;
}

export default function PoscarPanel({
  poscarContent,
  poscarPath,
  copyTargets,
  onImport,
  onCopyFromTask,
}: Props) {
  const { message } = App.useApp();
  const [showRaw, setShowRaw] = useState(false);
  const [copyFrom, setCopyFrom] = useState<string | undefined>(undefined);

  const info = useMemo(() => (poscarContent ? parsePoscar(poscarContent) : null), [poscarContent]);

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? '');
      if (!parsePoscar(text)) {
        message.error('无法解析该文件，请确认是合法的 POSCAR / VASP 结构文件');
        return;
      }
      onImport(text);
      message.success('POSCAR 已导入并保存到本地任务目录');
    };
    reader.onerror = () => message.error('读取文件失败');
    reader.readAsText(file);
  };

  return (
    <div className="job-panel">
      <Card size="small" title="导入 POSCAR" className="job-card">
        <div className="job-import-row">
          <Upload
            accept=".POSCAR,.poscar,.vasp,.CONTCAR,.contcar"
            showUploadList={false}
            beforeUpload={(file) => {
              readFile(file as unknown as File);
              return false;
            }}
          >
            <Button type="primary" icon={<CloudUploadOutlined />}>
              选择本地文件
            </Button>
          </Upload>
          <div className="job-import-sep">或</div>
          <Select
            style={{ minWidth: 260 }}
            placeholder="从其他任务复制 POSCAR"
            value={copyFrom}
            onChange={(v: string) => {
              setCopyFrom(v);
              onCopyFromTask(v);
            }}
            options={copyTargets.map((t) => ({
              value: t.taskId,
              label: `${t.projectName} / ${t.taskName}（${TASK_TYPE_LABELS[t.taskType] ?? t.taskType}）`,
            }))}
          />
          {copyFrom && (
            <Button
              icon={<CopyOutlined />}
              onClick={() => {
                onCopyFromTask(copyFrom);
                message.success('已从选中任务复制 POSCAR');
              }}
            >
              复制
            </Button>
          )}
        </div>
        <div className="job-file-loc">
          <span>当前文件</span>
          <code>{poscarPath ?? '尚未导入（当前为示例数据）'}</code>
        </div>
      </Card>

      <Card
        size="small"
        title="晶格信息预览"
        className="job-card mt-16"
        extra={
          poscarContent ? (
            <Button type="link" size="small" icon={<FileTextOutlined />} onClick={() => setShowRaw((v) => !v)}>
              {showRaw ? '隐藏内容' : '查看原文'}
            </Button>
          ) : null
        }
      >
        {info ? (
          <>
            <div className="job-lattice-stats">
              {(
                [
                  { label: 'a (Å)', value: info.lengths.a.toFixed(4) },
                  { label: 'b (Å)', value: info.lengths.b.toFixed(4) },
                  { label: 'c (Å)', value: info.lengths.c.toFixed(4) },
                  { label: '体积 (Å³)', value: info.volume.toFixed(2) },
                ] as { label: string; value: string }[]
              ).map((s) => (
                <div key={s.label} className="job-lattice-stat">
                  <div className="job-lattice-stat__num">{s.value}</div>
                  <div className="job-lattice-stat__lbl">{s.label}</div>
                </div>
              ))}
            </div>
            <Descriptions column={3} size="small" className="job-desc" style={{ marginTop: 12 }}>
              <Descriptions.Item label="α (°)">{info.angles.alpha.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="β (°)">{info.angles.beta.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="γ (°)">{info.angles.gamma.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="元素">
                {info.elements.join(' ')}
              </Descriptions.Item>
              <Descriptions.Item label="原子数">
                {info.counts.join(' ')}（共 {info.counts.reduce((s, n) => s + n, 0)}）
              </Descriptions.Item>
              <Descriptions.Item label="坐标模式">{info.coordMode}</Descriptions.Item>
            </Descriptions>
            <Tag color="success" style={{ marginTop: 10 }}>
              解析成功
            </Tag>
            {poscarPath && <span className="preview-note" style={{ marginLeft: 8 }}>{poscarPath}</span>}
            {showRaw && (
              <pre className="file-preview" style={{ marginTop: 12, maxHeight: 260 }}>
                {poscarContent}
              </pre>
            )}
          </>
        ) : (
          <div className="job-empty-hint">
            暂无 POSCAR。请通过上方按钮导入本地文件，或从其他任务复制。
          </div>
        )}
      </Card>
    </div>
  );
}
