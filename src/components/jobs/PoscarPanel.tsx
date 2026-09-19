import { useMemo, useState } from 'react';
import { App, Button, Card, Descriptions, Empty, Segmented, Select, Tag, Tooltip, Upload } from 'antd';
import {
  CloudUploadOutlined,
  CopyOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LockOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { TaskRef } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import { parsePoscar } from '../../utils/poscar';
import type { TaskInputState } from '../../api/jobs';
import { generatePotcar, uploadPoscar } from '../../api/jobs';
import Structure3DFrame, { type AtomRef } from './Structure3DFrame';
import SelectiveDynamicsModal from './SelectiveDynamicsModal';

interface Props {
  taskId: string;
  poscarContent: string | null;
  poscarPath: string | null;
  copyTargets: TaskRef[];
  /** 输入文件状态：POSCAR/CONTCAR 的 CIF 与结构摘要都来自这里 */
  input: TaskInputState | null;
  onImport: (content: string) => void;
  onCopyFromTask: (taskId: string) => void;
  /** 远端文件变化（上传 POSCAR / 生成 POTCAR）后刷新本地文件清单 */
  onRemoteChanged?: () => void;
  /** 同步到远端成功后回传刷新过的输入状态 */
  onStatePushed?: (state: TaskInputState) => void;
  /** 固定原子生成新 POSCAR 后回传（刷新编辑器内容 + 输入状态 + 文件清单） */
  onPoscarGenerated?: (text: string, state: TaskInputState) => void;
}

export default function PoscarPanel({
  taskId,
  poscarContent,
  poscarPath,
  copyTargets,
  input,
  onImport,
  onCopyFromTask,
  onRemoteChanged,
  onStatePushed,
  onPoscarGenerated,
}: Props) {
  const { message } = App.useApp();
  const [showRaw, setShowRaw] = useState(false);
  const [copyFrom, setCopyFrom] = useState<string | undefined>(undefined);
  /** POSCAR = 提交时的输入结构（不会变）；CONTCAR = 这次计算的最新结构 */
  const [view, setView] = useState<'poscar' | 'contcar'>('poscar');
  const [selectedAtoms, setSelectedAtoms] = useState<AtomRef[]>([]);
  const [uploading, setUploading] = useState(false);
  const [potcarBusy, setPotcarBusy] = useState(false);
  const [sdOpen, setSdOpen] = useState(false);
  /** 生成 POTCAR 的结果（命令输出 + 摘要），就地展示，不用弹窗 */
  const [potcarResult, setPotcarResult] = useState<{
    ok: boolean;
    text: string;
    output: string;
  } | null>(null);

  const uploadRemote = async () => {
    if (!poscarContent) {
      message.warning('请先导入 POSCAR');
      return;
    }
    setUploading(true);
    try {
      const r = await uploadPoscar(taskId, { content: poscarContent });
      onStatePushed?.(r.state);
      message.success(
        `POSCAR 已同步到 ${r.dir}` + (r.backup_file ? `（原文件备份为 ${r.backup_file}）` : ''),
      );
      onRemoteChanged?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同步 POSCAR 到远端失败');
    } finally {
      setUploading(false);
    }
  };

  const runPos2pot = async () => {
    setPotcarBusy(true);
    setPotcarResult(null);
    try {
      const r = await generatePotcar(taskId);
      const elems = r.potcar.elements.join(' ');
      const summary = r.generated
        ? `POTCAR 已生成：${r.potcar.size} 字节 · ${r.potcar.lines} 行 · ${
            r.potcar.elements_count
          } 个元素块${elems ? `（${elems}）` : ''} · 命令 ${r.command}（${r.dir}）`
        : `pos2pot 结束但未生成 POTCAR（exit=${r.exit_code}）`;
      if (r.generated) message.success(summary);
      else message.warning(summary);
      setPotcarResult({ ok: r.generated, text: summary, output: r.output });
      onRemoteChanged?.();
    } catch (err) {
      const text = err instanceof Error ? err.message : '运行 pos2pot 失败';
      message.error(text);
      setPotcarResult({ ok: false, text, output: '' });
    } finally {
      setPotcarBusy(false);
    }
  };

  const info = useMemo(() => (poscarContent ? parsePoscar(poscarContent) : null), [poscarContent]);
  const poscarMeta = input?.files?.POSCAR;
  const contcarMeta = input?.files?.CONTCAR;
  const cif = view === 'contcar' ? input?.contcar_cif ?? null : input?.poscar_cif ?? null;
  const shownMeta = view === 'contcar' ? contcarMeta : poscarMeta;

  /** 点击原子：默认单选（替换）；按住 Ctrl/⌘ 累加多选（与常见三维编辑器一致） */
  const handleClickAtom = (atom: AtomRef, additive: boolean) => {
    setSelectedAtoms((prev) => {
      if (!additive) return [atom];
      return prev.some((a) => a.index === atom.index)
        ? prev.filter((a) => a.index !== atom.index)
        : [...prev, atom];
    });
  };

  /** 框选（Shift + 拖拽）：默认用框内原子替换选择；Ctrl/⌘+Shift 则并入选中的原子 */
  const handleBoxSelect = (atoms: AtomRef[], additive: boolean) => {
    setSelectedAtoms((prev) => {
      if (!additive) return atoms;
      const merged = new Map(prev.map((a) => [a.index, a]));
      atoms.forEach((a) => merged.set(a.index, a));
      return [...merged.values()];
    });
    if (atoms.length > 0) message.success(`框选了 ${atoms.length} 个原子`);
  };

  /**
   * 选中原子按 POSCAR 序号合并成区间显示：
   * 同一元素且序号连续 → `Al1-3`；单独一个 → `Al7`（例：Al1 Al2 Al3 Al6 Al7 → Al1-3 Al6-7）
   */
  const atomGroups = useMemo(() => {
    const sorted = [...selectedAtoms].sort((a, b) => a.poscarIndex - b.poscarIndex);
    const groups: { element: string; from: number; to: number; atoms: AtomRef[] }[] = [];
    for (const atom of sorted) {
      const last = groups[groups.length - 1];
      if (last && last.element === atom.element && atom.poscarIndex === last.to + 1) {
        last.to = atom.poscarIndex;
        last.atoms.push(atom);
      } else {
        groups.push({
          element: atom.element,
          from: atom.poscarIndex,
          to: atom.poscarIndex,
          atoms: [atom],
        });
      }
    }
    return groups;
  }, [selectedAtoms]);

  const removeGroup = (atoms: AtomRef[]) => {
    const drop = new Set(atoms.map((a) => a.index));
    setSelectedAtoms((prev) => prev.filter((a) => !drop.has(a.index)));
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
      <SelectiveDynamicsModal
        open={sdOpen}
        taskId={taskId}
        poscarContent={poscarContent}
        selectedAtoms={selectedAtoms}
        onClose={() => setSdOpen(false)}
        onApplied={(text, state) => {
          onPoscarGenerated?.(text, state);
          setSelectedAtoms([]);
        }}
      />
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
                { value: 'poscar', label: '输入结构（POSCAR）' },
                {
                  value: 'contcar',
                  label: '最新结果（CONTCAR）',
                  disabled: !input?.contcar_cif,
                },
              ]}
            />
            <Tooltip title="输入文件（INCAR/KPOINTS/POSCAR）在任务提交时即确定，之后不再变化；CONTCAR 是本次计算的结果，只读展示，不参与续算输入">
              <span className="preview-note">输入（提交时定） / 结果（只读）</span>
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
              onClickAtom={handleClickAtom}
              onBoxSelect={handleBoxSelect}
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
                  输入文件在提交时确定（来源 {input.source.con || '主目录'}）·{' '}
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
                  在左侧结构图上<b>点击原子</b>即选中（金色高亮）；<b>按住 Ctrl / ⌘ 再点</b>可多选；
                  <b>按住 Shift 拖拽</b>可框选一片原子（Ctrl/⌘+Shift 框选为并入）；
                  <b>双击空白处</b>取消选中。
                  编号（如 <code>Ag18</code>）与 <b>POSCAR 坐标行一致、从 1 开始</b>，用于后续的固定原子功能。
                </div>
              ) : (
                <div className="s3d-editor__atoms">
                  {atomGroups.map((g) => (
                    <Tooltip
                      key={`${g.element}-${g.from}-${g.to}`}
                      title={
                        g.from === g.to
                          ? `POSCAR 第 ${g.from} 个原子（${g.element}）`
                          : `POSCAR 第 ${g.from}–${g.to} 个原子（${g.element}，共 ${g.atoms.length} 个）`
                      }
                    >
                      <Tag color="gold" bordered={false} closable onClose={() => removeGroup(g.atoms)}>
                        {g.element}
                        {g.from === g.to ? g.from : `${g.from}-${g.to}`}
                      </Tag>
                    </Tooltip>
                  ))}
                  {atomGroups.length > 1 && (
                    <span className="s3d-editor__atoms-summary">
                      共 {selectedAtoms.length} 个原子 / {atomGroups.length} 段
                    </span>
                  )}
                </div>
              )}
              <Tooltip title="把选中原子写成 Selective Dynamics 的 F F F（其余 T T T），生成新的 POSCAR：本地 files/POSCAR（旧文件备份 old_POSCAR），可选同时同步到远端">
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<LockOutlined />}
                  disabled={!poscarContent}
                  style={{ marginTop: 10 }}
                  onClick={() => setSdOpen(true)}
                >
                  固定原子（Selective Dynamics）
                </Button>
              </Tooltip>
              <div className="job-field-hint" style={{ marginTop: 8 }}>
                固定原子会生成带 <code>Selective Dynamics</code> 的新 POSCAR：
                写回本地 <code>files/POSCAR</code>（旧文件备份 <code>old_POSCAR</code>），
                勾选「同时同步到远端」才会写入远端最新目录；坐标块之后的内容（CONTCAR 的速度块）会原样保留。
              </div>
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
        title="远端输入文件"
        className="job-card mt-16"
        extra={
          <span className="preview-note">
            作用于远端「最新计算目录」（conN 优先）；同名文件先备份为 old_*
          </span>
        }
      >
        <div className="job-import-row">
          <Button
            type="primary"
            icon={<CloudUploadOutlined />}
            disabled={!poscarContent}
            loading={uploading}
            onClick={() => void uploadRemote()}
          >
            同步 POSCAR 到远端
          </Button>
          <Tooltip title="在远端当前目录执行 pos2pot（服务器已有脚本），读取该目录的 POSCAR 生成 POTCAR；失败时下方会显示命令输出">
            <Button
              icon={<ThunderboltOutlined />}
              loading={potcarBusy}
              onClick={() => void runPos2pot()}
            >
              生成 POTCAR（pos2pot）
            </Button>
          </Tooltip>
          <span className="preview-note">
            <ExperimentOutlined /> POTCAR 由远端 pos2pot 生成，不走本地伪势库
          </span>
        </div>
        {potcarResult && (
          <div className="poscar-potcar-result">
            <div className={potcarResult.ok ? 'is-ok' : 'is-fail'}>{potcarResult.text}</div>
            {potcarResult.output && <pre>{potcarResult.output}</pre>}
          </div>
        )}
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
