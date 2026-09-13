import { useEffect, useMemo, useState } from 'react';
import { App, Modal, Skeleton, Tooltip } from 'antd';
import { RightOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { fetchFreeEnergySummary } from '../../api/inspections';
import type { FreeEnergyStructure } from '../../api/inspections';
import PathStepChart from './PathStepChart';

interface Props {
  open: boolean;
  groupId: string | null;
  groupName?: string;
  onCancel: () => void;
  onOpenDetail: (taskId: string) => void;
}

const fmt = (v: number | null, d = 4) => (v == null ? '—' : v.toFixed(d));
const signed = (v: number | null, d = 4) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;

/**
 * 自由能路径看板（v0.6.7 视觉/交互重做）
 *
 * 顶部统计卡（中间体数 / 矫正进度 / 最大相对能）→ 台阶图 → 中间体明细列表。
 * 列表与图表都可点进该结构的巡检详情；进入时按行依次淡入上浮。
 */
export default function PathSummaryModal({
  open,
  groupId,
  groupName,
  onCancel,
  onOpenDetail,
}: Props) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [structures, setStructures] = useState<FreeEnergyStructure[]>([]);
  const [name, setName] = useState<string>('');

  useEffect(() => {
    if (!open || !groupId) return;
    setLoading(true);
    setStructures([]);
    fetchFreeEnergySummary(groupId)
      .then((r) => {
        setStructures(r.structures);
        setName(r.name);
      })
      .catch((err) => message.error(err instanceof Error ? err.message : '读取路径汇总失败'))
      .finally(() => setLoading(false));
  }, [open, groupId, message]);

  const stats = useMemo(() => {
    const withEnergy = structures.filter((s) => s.free_energy != null);
    const ref = withEnergy.length ? (withEnergy[0].free_energy as number) : null;
    const rels = withEnergy.map((s) => (s.free_energy as number) - (ref as number));
    const maxRel = rels.length ? Math.max(...rels) : null;
    const maxRelLabel = maxRel == null ? '—' : `+${maxRel.toFixed(3)} eV`;
    return {
      count: structures.length,
      corrected: structures.filter((s) => s.corrected).length,
      converged: structures.filter((s) => s.converged).length,
      maxRel,
      maxRelLabel,
      maxStructure:
        maxRel != null
          ? withEnergy[rels.indexOf(maxRel)]?.structure_label ?? ''
          : '',
      hasAny: withEnergy.length > 0,
    };
  }, [structures]);

  const displayName = groupName || name || groupId || '';

  return (
    <Modal
      title={
        <span className="fe-modal__title">
          <ThunderboltOutlined />
          自由能路径看板 · {displayName}
          <span className="fe-modal__subtitle">相对能台阶图 + 中间体明细</span>
        </span>
      }
      open={open}
      onCancel={onCancel}
      footer={null}
      width="min(940px, calc(100vw - 32px))"
      destroyOnClose
      styles={{ body: { maxHeight: '74vh', overflowY: 'auto' } }}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : structures.length === 0 ? (
        <div className="analysis-chart-empty">路径上暂无中间体数据</div>
      ) : (
        <>
          <div className="fe-stat-grid">
            <div className="fe-stat fe-anim" style={{ animationDelay: '0ms' }}>
              <div className="fe-stat__label">中间体数量</div>
              <div className="fe-stat__value">{stats.count}</div>
              <div className="fe-stat__sub">结构 1 – {stats.count}</div>
            </div>
            <div className="fe-stat fe-anim" style={{ animationDelay: '60ms' }}>
              <div className="fe-stat__label">矫正项完成度</div>
              <div className="fe-stat__value">
                {stats.corrected}
                <span className="fe-stat__value-sub"> / {stats.count}</span>
              </div>
              <div className="fe-stat__sub">
                {stats.corrected === stats.count ? '全部已矫正' : '部分中间体待矫正'}
              </div>
            </div>
            <div className="fe-stat fe-anim" style={{ animationDelay: '120ms' }}>
              <div className="fe-stat__label">结构优化收敛</div>
              <div className="fe-stat__value">
                {stats.converged}
                <span className="fe-stat__value-sub"> / {stats.count}</span>
              </div>
              <div className="fe-stat__sub">
                {stats.converged === stats.count ? '全部已收敛' : '存在未收敛中间体'}
              </div>
            </div>
            <div className="fe-stat fe-anim" style={{ animationDelay: '180ms' }}>
              <div className="fe-stat__label">最高相对能</div>
              <div className="fe-stat__value">{stats.maxRelLabel}</div>
              <div className="fe-stat__sub">
                {stats.maxStructure ? `结构 ${stats.maxStructure}` : '暂无对比数据'}
              </div>
            </div>
          </div>

          <PathStepChart structures={structures} onSelect={onOpenDetail} />

          <div className="fe-list">
            <div className="fe-row fe-row--head">
              <span>中间体</span>
              <span>DFT 能量 (eV)</span>
              <span>矫正项 (eV)</span>
              <span>自由能 (eV)</span>
              <span>相对 ΔE</span>
              <span>状态</span>
              <span />
            </div>
            {structures.map((s, i) => {
              const ref = structures.find((x) => x.free_energy != null)?.free_energy ?? null;
              const rel =
                s.free_energy == null || ref == null ? null : s.free_energy - ref;
              const warn = !s.converged || !s.corrected;
              return (
                <div
                  key={s.task_id}
                  className={`fe-row fe-anim${warn ? ' fe-row--warn' : ''}`}
                  style={{ animationDelay: `${220 + i * 55}ms` }}
                  role="button"
                  tabIndex={0}
                  onClick={() => onOpenDetail(s.task_id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onOpenDetail(s.task_id);
                    }
                  }}
                >
                  <span className="fe-chip">结构 {s.structure_label || i + 1}</span>
                  <span className="fe-num">{fmt(s.dft_energy)}</span>
                  <span
                    className={`fe-num${s.correction == null ? '' : s.correction >= 0 ? ' fe-num--pos' : ' fe-num--neg'}`}
                  >
                    {signed(s.correction)}
                  </span>
                  <span className="fe-num fe-num--strong">{fmt(s.free_energy)}</span>
                  <span
                    className={`fe-num${rel == null ? '' : rel > 0 ? ' fe-num--pos' : ''}`}
                  >
                    {signed(rel)}
                  </span>
                  <span className="fe-badges">
                    <span className={`fe-badge${s.converged ? ' is-ok' : ' is-warn'}`}>
                      {s.converged ? '已收敛' : '未收敛'}
                    </span>
                    <span className={`fe-badge${s.corrected ? ' is-ok' : ' is-warn'}`}>
                      {s.corrected ? '已矫正' : '未矫正'}
                    </span>
                  </span>
                  <Tooltip title="查看该结构的巡检详情">
                    <RightOutlined className="fe-row__go" />
                  </Tooltip>
                </div>
              );
            })}
          </div>

          <div className="fe-footnote">
            ΔE 以第一个有自由能的中间体为参考；台阶颜色：青色 = 已收敛且已矫正，琥珀 = 存在未收敛 / 未矫正。
            点击台阶或列表行可打开该结构的巡检详情（叠加在当前看板之上）。
          </div>
        </>
      )}
    </Modal>
  );
}
