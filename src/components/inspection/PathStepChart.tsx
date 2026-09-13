import { useMemo, useRef, useState } from 'react';
import type { FreeEnergyStructure } from '../../api/inspections';

interface Props {
  structures: FreeEnergyStructure[];
  onSelect: (taskId: string) => void;
}

const W = 720;
const H = 300;
const M = { left: 68, right: 24, top: 34, bottom: 60 };
const GAP_RATIO = 0.45; // 台阶之间连接区占台阶宽度的比例

const OK_COLOR = '#2C9DA8';
const WARN_COLOR = '#E8A33D';
const EMPTY_COLOR = '#C3CEDA';

function fmt(v: number | null, digits = 3) {
  return v == null ? '—' : v.toFixed(digits);
}

function signed(v: number, digits = 3) {
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}

/**
 * 自由能路径台阶图（v0.6.7 视觉/交互重做）
 *
 * - 纵轴改为**相对自由能**（以第一个有数据的中间体为参考，ΔE = E − E_ref），
 *   绝对能量与矫正项在 tooltip 与下方列表里仍然可见；
 * - 台阶带渐变柱体与向下渐变面积，收敛+已矫正为青色、否则琥珀色、缺数据为灰色虚线；
 * - 交互：悬停台阶上浮 + 发光 + 跟随鼠标的信息卡；点击打开该结构巡检详情；
 * - 动画：台阶按顺序从左滑入、连接线淡入、标签依次出现（纯 CSS，尊重 reduced-motion）。
 */
export default function PathStepChart({ structures, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [tip, setTip] = useState<{ index: number; x: number; y: number } | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  const geometry = useMemo(() => {
    const n = structures.length;
    const plotW = W - M.left - M.right;
    const plotH = H - M.top - M.bottom;
    const stepW = plotW / (n + Math.max(0, n - 1) * GAP_RATIO);
    const gap = stepW * GAP_RATIO;
    const stepX = (i: number) => M.left + i * (stepW + gap);

    // 参考能量：第一个有自由能的中间体（化学上即初态），缺失时退回最小值
    const available = structures.filter((s) => s.free_energy != null);
    const ref =
      available.find((s) => s.free_energy != null)?.free_energy ??
      Math.min(...available.map((s) => s.free_energy as number));
    const relOf = (s: FreeEnergyStructure) =>
      s.free_energy == null ? null : s.free_energy - ref;

    const rels = available.map((s) => (s.free_energy as number) - ref);
    const hiRaw = Math.max(0, ...rels);
    const loRaw = Math.min(0, ...rels);
    const pad = Math.max((hiRaw - loRaw) * 0.18, 0.2);
    const hi = hiRaw + pad;
    const lo = loRaw - pad;
    const py = (v: number) => M.top + plotH * (1 - (v - lo) / (hi - lo));

    const ticks = Array.from({ length: 5 }, (_, k) => lo + ((hi - lo) * k) / 4);
    return { n, plotW, plotH, stepW, gap, stepX, ref, relOf, py, ticks, y0: py(0) };
  }, [structures]);

  if (structures.length === 0) {
    return <div className="analysis-chart-empty">路径上暂无中间体数据</div>;
  }

  const { plotW, plotH, stepW, stepX, relOf, py, ticks, y0 } = geometry;

  const handleEnter = (index: number, e: React.MouseEvent) => {
    setHovered(index);
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({
      index,
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };
  const handleMove = (index: number, e: React.MouseEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ index, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const tipData = tip ? structures[tip.index] : null;

  return (
    <div className="fe-chart-wrap" ref={wrapRef}>
      <div className="fe-chart__legend">
        <span className="fe-legend-item">
          <span className="fe-legend-dot" style={{ background: OK_COLOR }} />
          收敛且已矫正
        </span>
        <span className="fe-legend-item">
          <span className="fe-legend-dot" style={{ background: WARN_COLOR }} />
          未收敛 / 未矫正
        </span>
        <span className="fe-legend-item">
          <span className="fe-legend-dot fe-legend-dot--empty" />
          无数据
        </span>
        <span className="fe-legend-ref">
          相对能以结构 {structures.find((s) => relOf(s) === 0)?.structure_label ?? '1'} 为参考
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="fe-chart__svg"
        role="img"
        aria-label="自由能路径台阶图"
      >
        <defs>
          <linearGradient id="feAreaOk" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={OK_COLOR} stopOpacity="0.26" />
            <stop offset="100%" stopColor={OK_COLOR} stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="feAreaWarn" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={WARN_COLOR} stopOpacity="0.26" />
            <stop offset="100%" stopColor={WARN_COLOR} stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="feBarOk" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#3FB3BD" />
            <stop offset="100%" stopColor="#2C9DA8" />
          </linearGradient>
          <linearGradient id="feBarWarn" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#F5BE68" />
            <stop offset="100%" stopColor="#E8A33D" />
          </linearGradient>
        </defs>

        {/* 网格与刻度 */}
        {ticks.map((value, k) => {
          const y = py(value);
          return (
            <g key={`tick-${k}`}>
              <line
                x1={M.left}
                y1={y}
                x2={W - M.right}
                y2={y}
                stroke="#EDF1F7"
                strokeDasharray="3 5"
              />
              <text x={M.left - 8} y={y + 4} fontSize="10" fill="#8A98AC" textAnchor="end">
                {signed(value, 2)}
              </text>
            </g>
          );
        })}

        {/* 参考线（ΔE = 0） */}
        <line x1={M.left} y1={y0} x2={W - M.right} y2={y0} stroke="#C3CEDA" strokeWidth="1" />
        <text x={M.left - 8} y={y0 + 4} fontSize="10" fill="#5A6A80" textAnchor="end" fontWeight="600">
          0.00
        </text>

        <line x1={M.left} y1={M.top} x2={M.left} y2={M.top + plotH} stroke="#DCE3EC" />
        <line
          x1={M.left}
          y1={M.top + plotH}
          x2={W - M.right}
          y2={M.top + plotH}
          stroke="#DCE3EC"
        />

        {/* 台阶之间的虚线连接（两端都有能量才连） */}
        {structures.map((s, i) => {
          const next = structures[i + 1];
          const rel = relOf(s);
          const nextRel = next ? relOf(next) : null;
          if (!next || rel == null || nextRel == null) return null;
          return (
            <line
              key={`link-${s.task_id}`}
              className="fe-link"
              style={{ animationDelay: `${180 + i * 70}ms` }}
              x1={stepX(i) + stepW}
              y1={py(rel)}
              x2={stepX(i + 1)}
              y2={py(nextRel)}
              stroke="#C3CEDA"
              strokeWidth="1.2"
              strokeDasharray="5 5"
            />
          );
        })}

        {/* 台阶 */}
        {structures.map((s, i) => {
          const rel = relOf(s);
          const x1 = stepX(i);
          const x2 = x1 + stepW;
          const warn = !s.converged || !s.corrected;
          const y = rel == null ? y0 : py(rel);
          const hover = hovered === i;
          return (
            <g
              key={s.task_id}
              className={`fe-step${hover ? ' is-hover' : ''}`}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              {/* 面积（仅有效数据） */}
              {rel != null && (
                <path
                  className="fe-step__area"
                  style={{ animationDelay: `${120 + i * 80}ms` }}
                  d={`M${x1},${y0} L${x1},${y} L${x2},${y} L${x2},${y0} Z`}
                  fill={warn ? 'url(#feAreaWarn)' : 'url(#feAreaOk)'}
                  pointerEvents="none"
                />
              )}

              {/* 台阶柱体 */}
              <line
                className="fe-step__bar"
                x1={x1}
                y1={y}
                x2={x2}
                y2={y}
                stroke={rel == null ? EMPTY_COLOR : warn ? 'url(#feBarWarn)' : 'url(#feBarOk)'}
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray={rel == null ? '6 6' : undefined}
                pointerEvents="none"
              />

              {/* 能量标签 */}
              <text
                className="fe-step__value"
                style={{ animationDelay: `${240 + i * 80}ms` }}
                x={(x1 + x2) / 2}
                y={y - 10}
                fontSize="11"
                fontWeight={hover ? 700 : 600}
                fill={rel == null ? '#96A3B5' : warn ? '#C07A1E' : '#1F7C86'}
                textAnchor="middle"
                pointerEvents="none"
              >
                {rel == null ? '无数据' : signed(rel)}
              </text>

              {/* 结构编号 */}
              <g className="fe-step__label" style={{ animationDelay: `${300 + i * 80}ms` }}>
                <rect
                  x={(x1 + x2) / 2 - 34}
                  y={M.top + plotH + 14}
                  width="68"
                  height="22"
                  rx="11"
                  fill={hover ? '#EAF1FF' : '#F4F7FB'}
                  stroke={hover ? 'rgba(91,141,239,.45)' : '#E3E9F2'}
                />
                <text
                  x={(x1 + x2) / 2}
                  y={M.top + plotH + 29}
                  fontSize="11"
                  fill={hover ? '#3F68B8' : '#5A6A80'}
                  textAnchor="middle"
                >
                  结构 {s.structure_label || i + 1}
                </text>
              </g>

              {/* 状态点（未收敛/未矫正时可见） */}
              {warn && rel != null && (
                <circle cx={x2 - 4} cy={y - 16} r="3.2" fill={WARN_COLOR} />
              )}

              {/* 交互热区 */}
              <rect
                className="fe-step__hit"
                x={x1 - 2}
                y={M.top}
                width={x2 - x1 + 4}
                height={plotH + 40}
                fill="transparent"
                onMouseEnter={(e) => handleEnter(i, e)}
                onMouseMove={(e) => handleMove(i, e)}
                onMouseLeave={() => {
                  setHovered(null);
                  setTip(null);
                }}
                onClick={() => onSelect(s.task_id)}
              />
            </g>
          );
        })}

        <text
          x={M.left + plotW / 2}
          y={H - 6}
          fontSize="11"
          fill="#8A98AC"
          textAnchor="middle"
        >
          中间体顺序（ΔE = E − E参考）
        </text>
      </svg>

      {tipData && tip && (
        <div
          className="fe-tip"
          style={{
            left: Math.min(Math.max(tip.x + 14, 8), (wrapRef.current?.clientWidth ?? 400) - 210),
            top: Math.max(tip.y - 8, 8),
          }}
        >
          <div className="fe-tip__title">
            结构 {tipData.structure_label}
            <span className={`fe-tip__dot${tipData.converged && tipData.corrected ? '' : ' is-warn'}`} />
          </div>
          <div className="fe-tip__row">
            <span>自由能</span>
            <b>{fmt(tipData.free_energy, 4)} eV</b>
          </div>
          <div className="fe-tip__row">
            <span>相对 ΔE</span>
            <b>{relOf(tipData) == null ? '—' : `${signed(relOf(tipData) as number, 4)} eV`}</b>
          </div>
          <div className="fe-tip__row">
            <span>DFT 能量</span>
            <b>{fmt(tipData.dft_energy, 4)} eV</b>
          </div>
          <div className="fe-tip__row">
            <span>矫正项</span>
            <b>{tipData.correction == null ? '—' : `${signed(tipData.correction, 4)} eV`}</b>
          </div>
          <div className="fe-tip__foot">
            {tipData.converged ? '已收敛' : '未收敛'} · {tipData.corrected ? '已矫正' : '未矫正'}
            <span className="fe-tip__hint">点击查看巡检详情</span>
          </div>
        </div>
      )}
    </div>
  );
}
