import { useMemo, useState } from 'react';
import { App, Button, Card, InputNumber, Radio, Tag, Tooltip } from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { buildKpoints, parsePoscar, recommendKgrid } from '../../utils/poscar';
import { uploadKpoints, type TaskInputState } from '../../api/jobs';

interface Props {
  taskId: string;
  taskName: string;
  poscarContent: string | null;
  kpointsContent: string | null;
  input: TaskInputState | null;
  onGenerate: (content: string) => void;
  /** 确认 k 网格修改（写入草稿，下次续算生效） */
  onConfirmMesh: (mesh: number[]) => void;
}

export default function KpointsPanel({
  taskId,
  taskName,
  poscarContent,
  kpointsContent,
  input,
  onGenerate,
  onConfirmMesh,
}: Props) {
  const { message } = App.useApp();
  const [density, setDensity] = useState(20);
  const [meshType, setMeshType] = useState<'Gamma' | 'Monkhorst-Pack'>('Gamma');
  /** 参数编辑闸门（与 INCAR 页一致：默认只读） */
  const [editing, setEditing] = useState(false);

  const snapshotMesh = input?.files?.KPOINTS?.mesh ?? null;
  const pendingMesh = input?.draft?.KPOINTS?.mesh ?? null;
  const [meshDraft, setMeshDraft] = useState<number[]>(
    pendingMesh ?? snapshotMesh ?? [1, 1, 1],
  );

  const info = useMemo(() => (poscarContent ? parsePoscar(poscarContent) : null), [poscarContent]);
  const grid = useMemo(
    () => (info ? recommendKgrid(info.lengths, density) : null),
    [info, density],
  );

  /** 当前生效网格（草稿优先，其次快照） */
  const effectiveMesh = pendingMesh ?? snapshotMesh;
  const meshChanged = (index: number) =>
    !!snapshotMesh && meshDraft[index] !== snapshotMesh[index];
  const densityProducts = useMemo(() => {
    if (!info || !meshDraft) return null;
    return (['a', 'b', 'c'] as const).map((axis, i) =>
      Number((meshDraft[i] * info.lengths[axis]).toFixed(2)),
    );
  }, [info, meshDraft]);

  const generate = () => {
    if (!grid || !info) {
      message.warning('请先在 POSCAR 页导入结构文件');
      return;
    }
    const content = buildKpoints(taskName, meshType, grid, density);
    onGenerate(content);
    message.success(
      `KPOINTS 已生成：${grid.join(' × ')}（${meshType}，密度 ${density}）`,
    );
  };

  const handleUploadRemote = async () => {
    if (!kpointsContent) return;
    // 只有 k 网格（或内容）真的变了才提交修改
    const current = input?.files?.KPOINTS?.text ?? null;
    if (current && current.trim() === kpointsContent.trim()) {
      message.info('KPOINTS 与本次计算一致，无需上传');
      return;
    }
    try {
      const r = await uploadKpoints(taskId, { content: kpointsContent });
      message.success(
        `KPOINTS 已上传到远端${r.backup_file ? `，旧文件已备份为 ${r.backup_file}` : ''}`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : '上传 KPOINTS 失败');
    }
  };

  return (
    <div className="job-panel">
      <Card
        size="small"
        title="本次计算的 K 点网格"
        className="job-card"
        extra={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {pendingMesh && (
              <Tag color="orange" bordered={false}>
                待生效 {pendingMesh.join(' × ')}
              </Tag>
            )}
            {editing ? (
              <>
                <Button
                  type="primary"
                  size="small"
                  icon={<CheckOutlined />}
                  onClick={() => {
                    onConfirmMesh(meshDraft);
                    setEditing(false);
                  }}
                >
                  确认修改
                </Button>
                <Button
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={() => {
                    setMeshDraft(pendingMesh ?? snapshotMesh ?? [1, 1, 1]);
                    setEditing(false);
                  }}
                >
                  取消
                </Button>
              </>
            ) : (
              <Tooltip title="默认只读；点「修改参数」解锁，确认后记为待生效修改（下次续算应用）">
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<EditOutlined />}
                  disabled={!snapshotMesh}
                  onClick={() => setEditing(true)}
                >
                  修改参数
                </Button>
              </Tooltip>
            )}
          </div>
        }
      >
        {snapshotMesh ? (
          <>
            <div className="job-kpoints-form">
              <div className="job-kpoints-field">
                <span className="job-kpoints-field__label">k 网格</span>
                {[0, 1, 2].map((i) => (
                  <InputNumber
                    key={i}
                    min={1}
                    max={40}
                    value={meshDraft[i]}
                    disabled={!editing}
                    className={meshChanged(i) ? 'is-pending' : undefined}
                    onChange={(v) => {
                      const next = [...meshDraft];
                      next[i] = Number(v ?? 1);
                      setMeshDraft(next);
                    }}
                    style={{ width: 84 }}
                  />
                ))}
                <span className="preview-note">
                  {input?.files?.KPOINTS?.mesh_note || '自动网格'} · 实际生效{' '}
                  {effectiveMesh ? effectiveMesh.join(' × ') : '—'}
                </span>
              </div>
            </div>
            {densityProducts && (
              <div className="job-kpoints-density">
                网格密度系数（k × 晶格常数，巡检要求 &gt; 20）：
                {densityProducts.map((v, i) => (
                  <Tag key={i} color={v > 20 ? 'green' : 'orange'} bordered={false}>
                    {['a', 'b', 'c'][i]} {v}
                  </Tag>
                ))}
              </div>
            )}
          </>
        ) : (
          <div className="job-empty-hint">
            尚未同步本次计算的 KPOINTS；点「同步最新参数」后可直接改 k 点个数。
          </div>
        )}
      </Card>

      <Card size="small" title="K 点网格生成" className="job-card">
        {info && grid ? (
          <>
            <div className="job-kpoints-form">
              <div className="job-kpoints-field">
                <span className="job-kpoints-field__label">网格密度系数</span>
                <InputNumber
                  min={5}
                  max={200}
                  value={density}
                  onChange={(v) => setDensity(v ?? 20)}
                  style={{ width: 140 }}
                />
                <span className="preview-note">默认 20（约每埃 20 个 k 点）</span>
              </div>
              <div className="job-kpoints-field">
                <span className="job-kpoints-field__label">网格类型</span>
                <Radio.Group
                  value={meshType}
                  onChange={(e) => setMeshType(e.target.value)}
                  optionType="button"
                  buttonStyle="solid"
                  options={[
                    { value: 'Gamma', label: 'Gamma-centered' },
                    { value: 'Monkhorst-Pack', label: 'Monkhorst-Pack' },
                  ]}
                />
              </div>
            </div>

            <div className="job-kpoints-result">
              <div className="job-kpoints-result__label">
                推荐网格
                <span className="preview-note">
                  {' '}
                  ≈ 密度系数 / 晶格常数（四舍五入，最小 1）
                </span>
              </div>
              <div className="job-kpoints-grid">
                {(['a', 'b', 'c'] as const).map((axis, i) => (
                  <div key={axis} className="job-kpoints-grid__cell">
                    <div className="job-kpoints-grid__num">{grid[i]}</div>
                    <div className="job-kpoints-grid__lbl">
                      {axis} = {info.lengths[axis].toFixed(3)} Å
                    </div>
                  </div>
                ))}
                <div className="job-kpoints-grid__arrow">→</div>
                <div className="job-kpoints-grid__sum">
                  <div className="job-kpoints-grid__num">{grid.join(' ')}</div>
                  <div className="job-kpoints-grid__lbl">{meshType}</div>
                </div>
              </div>
              <Tag color="geekblue" style={{ marginTop: 12 }}>
                总 k 点数：{grid[0] * grid[1] * grid[2]}
              </Tag>
            </div>

            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={generate}
              style={{ marginTop: 16 }}
            >
              生成 KPOINTS 文件
            </Button>
          </>
        ) : (
          <div className="job-empty-hint">
            未检测到 POSCAR 结构，请先在「POSCAR」页导入文件。
          </div>
        )}
      </Card>

      <Card
        size="small"
        title="KPOINTS 预览"
        className="job-card mt-16"
        extra={
          kpointsContent && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="preview-note">已生成 · 保存至 {taskName}/KPOINTS</span>
              <Button size="small" icon={<UploadOutlined />} onClick={() => void handleUploadRemote()}>
                上传到远端
              </Button>
            </div>
          )
        }
      >
        {kpointsContent ? (
          <pre className="file-preview">{kpointsContent}</pre>
        ) : (
          <div className="job-empty-hint">尚未生成 KPOINTS 文件。</div>
        )}
      </Card>
    </div>
  );
}
