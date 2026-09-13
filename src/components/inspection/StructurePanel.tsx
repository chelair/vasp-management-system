import { CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { Alert, Empty, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type {
  ForceHistoryPoint,
  LatticeParams,
  StructureAnalysis,
} from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import Structure3DViewer from './Structure3DViewer';

interface LatticeRow {
  key: string;
  label: string;
  poscar: string;
  contcar: string;
  delta: string | null;
}

function pct(value: number | null | undefined): string | null {
  if (value == null) return null;
  return `${value > 0 ? '+' : ''}${value.toFixed(3)}%`;
}

function fmt(value: number | undefined, digits: number): string {
  return value == null ? '—' : value.toFixed(digits);
}

function buildLatticeRows(poscar: LatticeParams | null, contcar: LatticeParams | null, deltas: StructureAnalysis['deltas']): LatticeRow[] {
  const rows: LatticeRow[] = [
    { key: 'a', label: 'a (Å)', poscar: fmt(poscar?.a, 4), contcar: fmt(contcar?.a, 4), delta: pct(deltas?.a_pct) },
    { key: 'b', label: 'b (Å)', poscar: fmt(poscar?.b, 4), contcar: fmt(contcar?.b, 4), delta: pct(deltas?.b_pct) },
    { key: 'c', label: 'c (Å)', poscar: fmt(poscar?.c, 4), contcar: fmt(contcar?.c, 4), delta: pct(deltas?.c_pct) },
    { key: 'alpha', label: 'α (°)', poscar: fmt(poscar?.alpha, 2), contcar: fmt(contcar?.alpha, 2), delta: null },
    { key: 'beta', label: 'β (°)', poscar: fmt(poscar?.beta, 2), contcar: fmt(contcar?.beta, 2), delta: null },
    { key: 'gamma', label: 'γ (°)', poscar: fmt(poscar?.gamma, 2), contcar: fmt(contcar?.gamma, 2), delta: null },
    { key: 'volume', label: '体积 (Å³)', poscar: fmt(poscar?.volume, 2), contcar: fmt(contcar?.volume, 2), delta: pct(deltas?.volume_pct) },
  ];
  return rows;
}

const latticeColumns: ColumnsType<LatticeRow> = [
  { title: '参数', dataIndex: 'label', key: 'label', width: 110 },
  { title: 'POSCAR', dataIndex: 'poscar', key: 'poscar', align: 'right' },
  { title: 'CONTCAR', dataIndex: 'contcar', key: 'contcar', align: 'right' },
  {
    title: '变化',
    dataIndex: 'delta',
    key: 'delta',
    align: 'right',
    render: (v: string | null) =>
      v == null ? (
        <span style={{ color: 'var(--color-text-muted)' }}>—</span>
      ) : (
        <span
          style={{
            color: v.startsWith('+') ? '#D9535B' : '#1E9E7F',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {v}
        </span>
      ),
  },
];

interface Props {
  analysis: StructureAnalysis;
  taskType: string;
  forceHistory: ForceHistoryPoint[];
  forceMax: number | null;
  forceRms: number | null;
  forceConverged: boolean | null;
}

export default function StructurePanel({
  analysis,
  taskType,
  forceHistory,
  forceMax,
  forceRms,
  forceConverged,
}: Props) {
  const isifText =
    analysis.isif == null
      ? 'ISIF 未知'
      : analysis.cell_fixed
        ? `ISIF=${analysis.isif} · 晶格固定，仅离子弛豫`
        : `ISIF=${analysis.isif} · 晶格可弛豫`;
  const isifNote =
    analysis.isif_source === 'incar' ? '来自本地 INCAR' : '本地未同步 INCAR，按 VASP 默认值';

  const forceColumns: ColumnsType<ForceHistoryPoint> = [
    { title: '离子步', dataIndex: 'step', key: 'step', width: 90 },
    {
      title: '能量 (eV)',
      dataIndex: 'energy',
      key: 'energy',
      render: (v: number | null) => (v == null ? '—' : v.toFixed(6)),
    },
    {
      title: '最大力 (eV/Å)',
      dataIndex: 'max_force',
      key: 'max_force',
      render: (v: number | null) => (v == null ? '—' : v.toFixed(6)),
    },
  ];

  return (
    <div className="structure-panel">
      <div className="structure-panel__scope">
        <Tag color={analysis.in_scope ? 'processing' : 'default'}>
          {analysis.in_scope
            ? '在分析范围内（两次巡检状态有变化：如 running→completed / running→zombied）'
            : '不在分析范围（两次巡检状态未发生变化）'}
        </Tag>
        <Tag color={analysis.cell_fixed ? 'default' : 'warning'}>{isifText}</Tag>
        <span className="preview-note">
          {TASK_TYPE_LABELS[taskType as keyof typeof TASK_TYPE_LABELS] ?? taskType}
          {analysis.steps != null ? ` · 离子步数 ${analysis.steps}` : ''}
          {analysis.isif != null ? ` · ${isifNote}` : ''}
        </span>
      </div>

      <div className="structure-stats">
        <div className="structure-stat">
          <div className="structure-stat__num">{analysis.steps ?? '—'}</div>
          <div className="structure-stat__lbl">离子步数</div>
        </div>
        <div className="structure-stat">
          <div className="structure-stat__num">
            {forceMax != null ? forceMax.toFixed(4) : '—'}
          </div>
          <div className="structure-stat__lbl">最大力 (eV/Å)</div>
        </div>
        <div className="structure-stat">
          <div className="structure-stat__num">
            {forceRms != null ? forceRms.toFixed(4) : '—'}
          </div>
          <div className="structure-stat__lbl">RMS 力 (eV/Å)</div>
        </div>
        <div className="structure-stat">
          <div className="structure-stat__num">
            {forceConverged == null ? (
              '—'
            ) : forceConverged ? (
              <span style={{ color: 'var(--color-success)' }}>已收敛</span>
            ) : (
              <span style={{ color: 'var(--color-danger)' }}>未收敛</span>
            )}
          </div>
          <div className="structure-stat__lbl">收敛判定</div>
        </div>
      </div>

      {analysis.skipped && (
        <Alert type="warning" showIcon message={analysis.skipped} style={{ marginBottom: 12 }} />
      )}
      {(analysis.warnings ?? []).map((w, i) => (
        <div key={i} className="structure-panel__warning">
          <WarningOutlined /> {w}
        </div>
      ))}

      <div className="structure-panel__section-title">
        {analysis.cell_fixed
          ? '原子位移分析（ISIF=2 · 晶格固定，仅离子弛豫）'
          : '晶格参数对比（POSCAR → CONTCAR）'}
      </div>
      {analysis.cell_fixed ? (
        analysis.displacements ? (
          <div className="structure-stats">
            <div className="structure-stat">
              <div className="structure-stat__num">
                {analysis.displacements.max.toFixed(4)}
              </div>
              <div className="structure-stat__lbl">最大位移 (Å)</div>
            </div>
            <div className="structure-stat">
              <div className="structure-stat__num">
                {analysis.displacements.rms.toFixed(4)}
              </div>
              <div className="structure-stat__lbl">RMS 位移 (Å)</div>
            </div>
            <div className="structure-stat">
              <div className="structure-stat__num">
                {analysis.displacements.mean.toFixed(4)}
              </div>
              <div className="structure-stat__lbl">平均位移 (Å)</div>
            </div>
            <div className="structure-stat">
              <div className="structure-stat__num">{analysis.displacements.count}</div>
              <div className="structure-stat__lbl">原子数</div>
            </div>
          </div>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="原子坐标解析失败或原子数不一致，无法计算位移"
            style={{ margin: '12px 0' }}
          />
        )
      ) : analysis.poscar && analysis.contcar ? (
        <>
          <Table
            rowKey="key"
            size="small"
            bordered
            pagination={false}
            columns={latticeColumns}
            dataSource={buildLatticeRows(analysis.poscar, analysis.contcar, analysis.deltas)}
          />
          {analysis.deltas?.volume_pct != null && (
            <div className="structure-panel__verdict">
              <CheckCircleOutlined style={{ color: 'var(--color-success)' }} />
              体积变化 {analysis.deltas.volume_pct > 0 ? '+' : ''}
              {analysis.deltas.volume_pct.toFixed(3)}%（优化前 → 优化后）
            </div>
          )}
        </>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            analysis.files?.poscar || analysis.files?.contcar
              ? '结构文件解析失败'
              : '结构文件未同步，无法分析'
          }
          style={{ margin: '12px 0' }}
        />
      )}

      {analysis.poscar_cif || analysis.contcar_cif ? (
        <>
          <div className="structure-panel__section-title">结构 3D 对比（3Dmol.js）</div>
          <Structure3DViewer
            poscarCif={analysis.poscar_cif ?? null}
            contcarCif={analysis.contcar_cif ?? null}
          />
        </>
      ) : null}

      {forceHistory.length > 0 && (
        <>
          <div className="structure-panel__section-title">力收敛历史</div>
          <Table
            rowKey="step"
            size="small"
            dataSource={forceHistory}
            columns={forceColumns}
            pagination={false}
            scroll={{ y: 260 }}
          />
        </>
      )}
    </div>
  );
}
