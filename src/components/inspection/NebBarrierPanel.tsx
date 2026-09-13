import { useMemo, useRef, useState } from 'react';
import type { InspectionDetail } from '../../types';

type NebImage = NonNullable<InspectionDetail['neb_barrier']>['images'][number];

interface Props {
  images: NebImage[];
}

const W = 820;
const H = 320;
const M = { left: 66, right: 26, top: 38, bottom: 54 };
const LINE = '#7B61D6';
const LINE_SOFT = '#A78BFA';

const fmt = (v: number | null, d = 4) => (v == null ? '—' : v.toFixed(d));
const signed = (v: number | null, d = 4) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;

/**
 * NEB 过渡态能垒看板（v0.6.8）
 *
 * 统计卡（映像数 / 能垒 Ea / 最大受力 / 末态相对能）+ 能垒曲线（直线段如实反映各映像、
 * 鞍点竖线标注、渐变面积、悬停信息卡）+ 映像明细列表。
 * 动画：曲线从左向右绘制、数据点依次弹出、鞍点标注与面积随后淡入；
 * `prefers-reduced-motion` 下关闭。
 */
export default function NebBarrierPanel({ images }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [tip, setTip] = useState<{ index: number; x: number; y: number } | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  const geo = useMemo(() => {
    const n = images.length;
    const plotW = W - M.left - M.right;
    const plotH = H - M.top - M.bottom;
    const rels = images
      .map((x) => x.relative)
      .filter((v): v is number => v != null);
    const hiRaw = Math.max(0, ...rels);
    const loRaw = Math.min(0, ...rels);
    const pad = Math.max((hiRaw - loRaw) * 0.16, 0.05);
    const hi = hiRaw + pad;
    const lo = loRaw - pad;
    const px = (i: number) => (n > 1 ? M.left + (i * plotW) / (n - 1) : M.left + plotW / 2);
    const py = (v: number) => M.top + plotH * (1 - (v - lo) / (hi - lo));
    const ticks = Array.from({ length: 5 }, (_, k) => lo + ((hi - lo) * k) / 4);

    // 鞍点（相对能最高）与最大受力点
    let saddle = -1;
    let maxForceIdx = -1;
    images.forEach((x, i) => {
      if (x.relative != null && (saddle < 0 || x.relative > (images[saddle].relative ?? -1e9))) {
        saddle = i;
      }
      if (
        x.max_force != null &&
        (maxForceIdx < 0 || x.max_force > (images[maxForceIdx].max_force ?? -1e9))
      ) {
        maxForceIdx = i;
      }
    });
    return { n, plotW, plotH, px, py, ticks, y0: py(0), saddle, maxForceIdx };
  }, [images]);

  if (images.length === 0) {
    return <div className="analysis-chart-empty">暂无 NEB 映像数据</div>;
  }

  const { n, plotW, plotH, px, py, ticks, y0, saddle, maxForceIdx } = geo;
  const saddleRel = saddle >= 0 ? images[saddle].relative : null;
  const cornerRel = n > 0 ? images[n - 1].relative : null;
  const maxForce = maxForceIdx >= 0 ? images[maxForceIdx].max_force : null;
  const labelStep = n > 12 ? Math.ceil(n / 12) : 1;

  // 折线（跳过缺失点）
  let pen = false;
  const linePath = images
    .map((x, i) => {
      if (x.relative == null) {
        pen = false;
        return '';
      }
      const cmd = pen ? 'L' : 'M';
      pen = true;
      return `${cmd}${px(i).toFixed(1)},${py(x.relative).toFixed(1)}`;
    })
    .filter(Boolean)
    .join(' ');
  const areaPath = (() => {
    const pts = images
      .map((x, i) => (x.relative == null ? null : { x: px(i), y: py(x.relative) }))
      .filter((p): p is { x: number; y: number } => p != null);
    if (pts.length < 2) return '';
    return `M${pts[0].x},${y0} ${pts.map((p) => `L${p.x},${p.y}`).join(' ')} L${pts[pts.length - 1].x},${y0} Z`;
  })();

  const tipData = tip ? images[tip.index] : null;
  const moveTip = (index: number, e: React.MouseEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ index, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  return (
    <div className="fe-path">
      <div className="fe-stat-grid">
        <div className="fe-stat fe-anim" style={{ animationDelay: '0ms' }}>
          <div className="fe-stat__label">映像数量</div>
          <div className="fe-stat__value">{n}</div>
          <div className="fe-stat__sub">
            {n >= 2 ? `端点 2 + 中间 ${n - 2}` : '含端点'}
          </div>
        </div>
        <div className="fe-stat fe-anim" style={{ animationDelay: '60ms' }}>
          <div className="fe-stat__label">能垒 Ea</div>
          <div className="fe-stat__value">{signed(saddleRel, 3)}</div>
          <div className="fe-stat__sub">
            {saddle >= 0 ? `最高点：映像 ${images[saddle].label}` : '暂无数据'}
          </div>
        </div>
        <div className="fe-stat fe-anim" style={{ animationDelay: '120ms' }}>
          <div className="fe-stat__label">最大受力</div>
          <div className="fe-stat__value">{fmt(maxForce, 3)}</div>
          <div className="fe-stat__sub">
            {maxForceIdx >= 0 ? `映像 ${images[maxForceIdx].label}（eV/Å）` : '暂无数据'}
          </div>
        </div>
        <div className="fe-stat fe-anim" style={{ animationDelay: '180ms' }}>
          <div className="fe-stat__label">末态相对能</div>
          <div className="fe-stat__value">{signed(cornerRel, 3)}</div>
          <div className="fe-stat__sub">
            {cornerRel != null && Math.abs(cornerRel) < 0.01
              ? '与初态基本一致'
              : '相对初态（映像 00）'}
          </div>
        </div>
      </div>

      <div className="fe-chart-wrap" ref={wrapRef}>
        <div className="fe-chart__legend">
          <span className="fe-legend-item">
            <span className="fe-legend-dot" style={{ background: LINE }} />
            相对能垒（nebef.pl）
          </span>
          <span className="fe-legend-item">
            <span className="fe-legend-dot" style={{ background: '#D9535B' }} />
            鞍点（能垒最高）
          </span>
          <span className="fe-legend-ref">
            横轴为 NEB 映像（00 = 初态，{String(n - 1).padStart(2, '0')} = 末态）
          </span>
        </div>

        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="fe-chart__svg"
          role="img"
          aria-label="NEB 过渡态能垒曲线"
        >
          <defs>
            <linearGradient id="nebArea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={LINE} stopOpacity="0.26" />
              <stop offset="100%" stopColor={LINE} stopOpacity="0.02" />
            </linearGradient>
            <linearGradient id="nebStroke" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={LINE_SOFT} />
              <stop offset="100%" stopColor={LINE} />
            </linearGradient>
          </defs>

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

          {/* 初态基准线 */}
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

          {/* 渐变面积 */}
          {areaPath && (
            <path
              className="neb-area"
              d={areaPath}
              fill="url(#nebArea)"
              pointerEvents="none"
            />
          )}

          {/* 能垒曲线（从左向右绘制） */}
          <path
            className="neb-line"
            d={linePath}
            fill="none"
            stroke="url(#nebStroke)"
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
          />

          {/* 鞍点竖线 + 标注 */}
          {saddle >= 0 && saddleRel != null && (
            <g className="neb-saddle">
              <line
                x1={px(saddle)}
                y1={py(saddleRel)}
                x2={px(saddle)}
                y2={y0}
                stroke="#D9535B"
                strokeWidth="1.2"
                strokeDasharray="4 4"
              />
              <g transform={`translate(${px(saddle)}, ${Math.max(py(saddleRel) - 30, 12)})`}>
                <rect x="-52" y="-16" width="104" height="22" rx="11" fill="#FDECED" stroke="#F3C3C7" />
                <text x="0" y="-1" fontSize="11" fill="#C8434B" textAnchor="middle" fontWeight="600">
                  Ea = {signed(saddleRel, 3)} eV
                </text>
              </g>
            </g>
          )}

          {/* 数据点 */}
          {images.map((x, i) => {
            if (x.relative == null) return null;
            const isEnd = i === 0 || i === n - 1;
            const isSaddle = i === saddle;
            return (
              <circle
                key={`dot-${x.label}-${i}`}
                className="neb-dot"
                style={{ animationDelay: `${260 + i * 55}ms` }}
                cx={px(i)}
                cy={py(x.relative)}
                r={isSaddle ? 6 : isEnd ? 5 : 4}
                fill="#fff"
                stroke={isSaddle ? '#D9535B' : LINE}
                strokeWidth={isSaddle ? 3 : 2.4}
              />
            );
          })}

          {/* 悬停竖线 + 放大点 */}
          {hovered != null && images[hovered].relative != null && (
            <>
              <line
                x1={px(hovered)}
                y1={M.top}
                x2={px(hovered)}
                y2={M.top + plotH}
                stroke="#9CA3AF"
                strokeWidth="1"
                strokeDasharray="4 3"
              />
              <circle
                cx={px(hovered)}
                cy={py(images[hovered].relative as number)}
                r="6.5"
                fill={LINE}
                stroke="#fff"
                strokeWidth="2.5"
              />
            </>
          )}

          {/* 横轴映像标签 */}
          {images.map((x, i) =>
            i % labelStep === 0 || i === n - 1 ? (
              <text
                key={`xl-${x.label}-${i}`}
                x={px(i)}
                y={M.top + plotH + 20}
                fontSize="10"
                fill={i === 0 || i === n - 1 ? '#5A6A80' : '#8A98AC'}
                fontWeight={i === 0 || i === n - 1 ? 600 : 400}
                textAnchor="middle"
              >
                {x.label}
              </text>
            ) : null,
          )}
          <text x={M.left - 8} y={M.top + plotH + 20} fontSize="10" fill="#8A98AC" textAnchor="end">
            映像
          </text>

          {/* 交互热区 */}
          {images.map((x, i) => {
            const bandW = n > 1 ? plotW / (n - 1) : plotW;
            return (
              <rect
                key={`hit-${x.label}-${i}`}
                className="fe-step__hit"
                x={px(i) - bandW / 2}
                y={M.top}
                width={bandW}
                height={plotH + 30}
                fill="transparent"
                onMouseEnter={(e) => {
                  setHovered(i);
                  moveTip(i, e);
                }}
                onMouseMove={(e) => moveTip(i, e)}
                onMouseLeave={() => {
                  setHovered(null);
                  setTip(null);
                }}
              />
            );
          })}
        </svg>

        {tipData && tip && (
          <div
            className="fe-tip"
            style={{
              left: Math.min(Math.max(tip.x + 14, 8), (wrapRef.current?.clientWidth ?? 400) - 200),
              top: Math.max(tip.y - 8, 8),
            }}
          >
            <div className="fe-tip__title">
              映像 {tipData.label}
              {tip.index === 0 && <span className="fe-badge is-ok">初态</span>}
              {tip.index === n - 1 && <span className="fe-badge is-ok">末态</span>}
              {tip.index === saddle && <span className="fe-badge is-warn">鞍点</span>}
            </div>
            <div className="fe-tip__row">
              <span>相对能垒</span>
              <b>{signed(tipData.relative, 4)} eV</b>
            </div>
            <div className="fe-tip__row">
              <span>绝对能量</span>
              <b>{fmt(tipData.energy, 4)} eV</b>
            </div>
            <div className="fe-tip__row">
              <span>最大受力</span>
              <b>{fmt(tipData.max_force, 4)} eV/Å</b>
            </div>
          </div>
        )}
      </div>

      <div className="fe-list">
        <div className="fe-row fe-row--head">
          <span>映像</span>
          <span>相对能垒 (eV)</span>
          <span>绝对能量 (eV)</span>
          <span>最大受力 (eV/Å)</span>
          <span>角色</span>
          <span />
        </div>
        {images.map((x, i) => (
          <div
            key={`row-${x.label}-${i}`}
            className={`fe-row fe-anim${i === saddle ? ' fe-row--warn' : ''}`}
            style={{ animationDelay: `${220 + i * 45}ms` }}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="fe-chip">映像 {x.label}</span>
            <span className={`fe-num fe-num--strong`}>{signed(x.relative)}</span>
            <span className="fe-num">{fmt(x.energy)}</span>
            <span className={`fe-num${i === maxForceIdx ? ' fe-num--pos' : ''}`}>
              {fmt(x.max_force)}
            </span>
            <span className="fe-badges">
              {i === 0 && <span className="fe-badge is-ok">初态</span>}
              {i === n - 1 && <span className="fe-badge is-ok">末态</span>}
              {i === saddle && <span className="fe-badge is-warn">鞍点</span>}
              {i !== 0 && i !== n - 1 && i !== saddle && (
                <span className="fe-badge">中间态</span>
              )}
            </span>
            <span />
          </div>
        ))}
      </div>

      <div className="fe-footnote">
        数据来自 nebef.pl：相对能垒以初态（映像 {images[0]?.label ?? '00'}）为 0；曲线按各映像实际数值直线连接，不做插值。
        悬停曲线或明细行可查看该映像的绝对能量与受力。
      </div>
    </div>
  );
}
