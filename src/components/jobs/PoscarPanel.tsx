import { useMemo, useState } from 'react';
import { App, Button, Card, Descriptions, Empty, Segmented, Select, Tag, Tooltip, Upload } from 'antd';
import {
  CloudUploadOutlined,
  CopyOutlined,
  FileTextOutlined,
  LockOutlined,
} from '@ant-design/icons';
import type { TaskRef } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import { parsePoscar } from '../../utils/poscar';
import type { TaskInputState } from '../../api/jobs';
import Structure3DFrame, { type AtomRef } from './Structure3DFrame';

interface Props {
  poscarContent: string | null;
  poscarPath: string | null;
  copyTargets: TaskRef[];
  /** 输入文件状态：POSCAR/CONTCAR 的 CIF 与结构摘要都来自这里 */
  input: TaskInputState | null;
  onImport: (content: string) => void;
  onCopyFromTask: (taskId: string) => void;
}

export default function PoscarPanel({
  poscarContent,
  poscarPath,
  copyTargets,
  input,
  onImport,
  onCopyFromTask,
}: Props) {
  const { message } = App.useApp();
  const [showRaw, setShowRaw] = useState(false);
  const [copyFrom, setCopyFrom] = useState<string | undefined>(undefined);
  /** POSCAR = 提交时的输入结构（不会变）；CONTCAR = 这次计算的最新结构 */
  const [view, setView] = useState<'poscar' | 'contcar'>('poscar');
  const [selectedAtoms, setSelectedAtoms] = useState<AtomRef[]>([]);

  const info = useMemo(() => (poscarContent ? parsePoscar(poscarContent) : null), [poscarContent]);
  const poscarMeta = input?.files?.POSCAR;
  const contcarMeta = input?.files?.CONTCAR;
  const cif = view === 'contcar' ? input?.contcar_cif ?? null : input?.poscar_cif ?? null;
  const shownMeta = view === 'contcar' ? contcarMeta : poscarMeta;

  const toggleAtom = (atom: AtomRef) => {
    setSelectedAtoms((prev) =>
      prev.some((a) => a.index === atom.index)
        ? prev.filter((a) => a.index !== atom.index)
        : [...prev, atom],
    );
  };

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
      <Card
        size="small"
        title="结构视图"
        className="job-card"
        extra={
          <div className="s3d-editor__switch">
            <Segmented
              size="small"
              value={view}
              onChange={(v) => {
                setView(v as 'poscar' | 'contcar');
                setSelectedAtoms([]);
              }}
              options={[
                { value: 'poscar', label: '初始 POSCAR' },
                {
                  value: 'contcar',
                  label: '最新 CONTCAR',
                  disabled: !input?.contcar_cif,
                },
              ]}
            />
            <Tooltip title="POSCAR 是提交时使用的初始结构（不会变）；CONTCAR 是这次计算最新的结构">
              <span className="preview-note">初始结构 / 最新结构</span>
            </Tooltip>
          </div>
        }
      >
        <div className="s3d-editor__layout">
          <div className="s3d-editor__main">
            <Structure3DFrame
              cif={cif}
              height={460}
              selected={selectedAtoms}
              onToggleAtom={toggleAtom}
              onClearSelection={() => setSelectedAtoms([])}
            />
          </div>
          <div className="s3d-editor__side">
            <Card size="small" title="结构数据" className="job-card s3d-editor__data">
              {shownMeta && shownMeta.n_atoms ? (
                <Descriptions column={1} size="small" className="job-desc">
                  <Descriptions.Item label="元素组成">
                    {(shownMeta.elements ?? []).map((el, i) => `${el}${shownMeta.counts?.[i] ?? ''}`).join(' ')}
                  </Descriptions.Item>
                  <Descriptions.Item label="原子数">{shownMeta.n_atoms}</Descriptions.Item>
                  <Descriptions.Item label="晶格 (Å)">
                    {shownMeta.lengths
                      ? `${shownMeta.lengths.a.toFixed(3)} / ${shownMeta.lengths.b.toFixed(3)} / ${shownMeta.lengths.c.toFixed(3)}`
                      : '—'}
                  </Descriptions.Item>
                </Descriptions>
              ) : info ? (
                <Descriptions column={1} size="small" className="job-desc">
                  <Descriptions.Item label="元素组成">
                    {info.elements.map((el, i) => `${el}${info.counts[i]}`).join(' ')}
                  </Descriptions.Item>
                  <Descriptions.Item label="原子数">
                    {info.counts.reduce((s, n) => s + n, 0)}
                  </Descriptions.Item>
                  <Descriptions.Item label="晶格 (Å)">
                    {`${info.lengths.a.toFixed(3)} / ${info.lengths.b.toFixed(3)} / ${info.lengths.c.toFixed(3)}`}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无结构数据" />
              )}
              {input?.source?.synced_at && (
                <div className="preview-note" style={{ marginTop: 6 }}>
                  结构来自 {input.source.con || '主目录'} ·{' '}
                  {input.source.synced_at.replace('T', ' ').slice(5, 16)} 同步
                </div>
              )}
            </Card>

            <Card
              size="small"
              title={`选中原子（${selectedAtoms.length}）`}
              className="job-card s3d-editor__data"
              style={{ marginTop: 12 }}
              extra={
                selectedAtoms.length > 0 ? (
                  <Button size="small" type="link" onClick={() => setSelectedAtoms([])}>
                    清空
                  </Button>
                ) : null
              }
            >
              {selectedAtoms.length === 0 ? (
                <div className="job-field-hint">
                  在左侧结构图上<b>点击原子</b>即可选中（金色高亮），可多选；用于后续的固定原子功能。
                </div>
              ) : (
                <div className="s3d-editor__atoms">
                  {selectedAtoms.map((a) => (
                    <Tag
                      key={a.index}
                      color="gold"
                      bordered={false}
                      closable
                      onClose={() => toggleAtom(a)}
                    >
                      #{a.index} {a.element}
                    </Tag>
                  ))}
                </div>
              )}
              <Tooltip title="固定原子功能开发中：先在 POSCAR 的 Selective dynamics 里标记 T/F">
                <Button size="small" icon={<LockOutlined />} disabled style={{ marginTop: 10 }}>
                  固定选中原子（开发中）
                </Button>
              </Tooltip>
            </Card>
          </div>
        </div>
      </Card>

      <Card size="small" title="导入 / 复制 POSCAR" className="job-card mt-16">
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
