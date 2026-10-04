import { useEffect, useMemo, useRef, useState } from 'react';

export interface NebCurveImage {
  label: string;
  relative: number | null;
  max_force: number | null;
  /** 绝对能量（eV），仅用于读数展示 */
  energy?: number | null;
}

interface Props {
  images: NebCurveImage[];
  /** 当前选中映像下标 */
  selected: number;
  /** 鞍点（相对能最高）下标，-1 = 无 */
  saddle: number;
  onSelect: (index: number) => void;
}

const H = 196;
const M = { left: 54, right: 22, top: 22, bottom: 32 };
const LINE = '#7B61D6';
const LINE_SOFT = '#A78BFA';
const SADDLE = '#D9535B';
/** 纵轴最小跨度（eV）：能量全部相同时避免所有点叠在一条线上 */
const MIN_SPAN = 0.12;

const signed = (v: number, d = 3) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;

/**
 * NEB 能量曲线（v0.9.40）：横向铺满、按实际映像数均分横轴，点击数据点切换主视图。
 * 选中点突出、鞍点单独标记、零线虚线、曲线下方渐变填充；点密时自动缩小并省略编号。
 */
export default function NebEnergyCurve({ images, selected, saddle, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(880);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const apply = () => setWidth(Math.max(320, el.clientWidth || 880));
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = images.length;
  const geo = useMemo(() => {
    const W = width;
    const plotW = Math.max(10, W - M.left - M.right);
    const plotH = H - M.top - M.bottom;
    const rels = images
      .map((x) => x.relative)
      .filter((v): v is number => v != null && Number.isFinite(v));
    let hi = Math.max(0, ...rels);
    let lo = Math.min(0, ...rels);
    if (!rels.length) {
      hi = 0.06;
      lo = -0.06;
    }
    // 最小跨度（全部相同时撑开），再加 18% 余量
    if (hi - lo < MIN_SPAN) {
      const mid = (hi + lo) / 2;
      hi = mid + MIN_SPAN / 2;
      lo = mid - MIN_SPAN / 2;
    }
    const pad = Math.max((hi - lo) * 0.18, 0.03);
    hi += pad;
    lo -= pad;
    const px = (i: number) =>
      n > 1 ? M.left + (i * plotW) / (n - 1) : M.left + plotW / 2;
    const py = (v: number) => M.top + plotH * (1 - (v - lo) / (hi - lo));
    const ticks = Array.from({ length: 4 }, (_, k) => lo + ((hi - lo) * (k + 0.5)) / 4);
    return { W, plotW, plotH, px, py, ticks, y0: py(0) };
  }, [images, width, n]);

  const { W, plotW, plotH, px, py, ticks, y0 } = geo;
  const rBase = n > 16 ? 3 : n > 10 ? 3.6 : 4.4;
  const labelStep = n > 16 ? Math.ceil(n / 12) : 1;

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
    const base = Math.min(Math.max(y0, M.top), M.top + plotH);
    return `M${pts[0].x},${base} ${pts.map((p) => `L${p.x},${p.y}`).join(' ')} L${pts[pts.length - 1].x},${base} Z`;
  })();

  const active = hover ?? selected;
  const activeImg = images[active];
  const hasEnergy = images.some((x) => x.relative != null);

  return (
    <div className="nebmd-curve" ref={wrapRef}>
      <div className="nebmd-curve__head">
        <span className="nebmd-curve__title">能量曲线</span>
        <span className="nebmd-curve__hint">相对初态（映像 00）的能量差 · 点击数据点切换主视图</span>
        {activeImg && (
          <span className="nebmd-curve__read">
            映像 {String(active).padStart(2, '0')}
            {activeImg.relative != null ? ` · ΔE ${signed(activeImg.relative)} eV` : ''}
            {activeImg.max_force != null ? ` · F ${activeImg.max_force.toFixed(3)}` : ''}
            {activeImg.energy != null ? ` · E ${activeImg.energy.toFixed(4)} eV` : ''}
            {active === saddle && <em className="nebmd-curve__saddle">鞍点</em>}
          </span>
        )}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        className="nebmd-curve__svg"
        role="img"
        aria-label="NEB 映像相对能量曲线"
      >
        <defs>
          <linearGradient id="nebmdArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={LINE} stopOpacity="0.24" />
            <stop offset="100%" stopColor={LINE} stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="nebmdStroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={LINE_SOFT} />
            <stop offset="100%" stopColor={LINE} />
          </linearGradient>
        </defs>

        {ticks.map((value, k) => {
          const y = py(value);
          return (
            <g key={`t-${k}`}>
              <line x1={M.left} y1={y} x2={W - M.right} y2={y} stroke="#EDF1F7" strokeDasharray="3 5" />
              <text x={M.left - 8} y={y + 4} fontSize="10" fill="#8A98AC" textAnchor="end">
                {signed(value, 2)}
              </text>
            </g>
          );
        })}

        <line x1={M.left} y1={y0} x2={W - M.right} y2={y0} stroke="#B9C6D6" strokeDasharray="5 4" />
        <text x={M.left - 8} y={y0 + 4} fontSize="10" fill="#5A6A80" textAnchor="end" fontWeight="600">
          0.00
        </text>

        {areaPath && <path d={areaPath} fill="url(#nebmdArea)" pointerEvents="none" />}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke="url(#nebmdStroke)"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* 悬停竖线 */}
        {hover != null && (
          <line
            x1={px(hover)}
            y1={M.top}
            x2={px(hover)}
            y2={M.top + plotH}
            stroke="#9CA3AF"
            strokeWidth="1"
            strokeDasharray="4 3"
          />
        )}

        {/* 数据点 */}
        {images.map((x, i) => {
          if (x.relative == null) return null;
          const isSel = i === selected;
          const isSaddle = i === saddle;
          const r = rBase + (isSel ? 2 : 0);
          return (
            <g key={`dot-${x.label}-${i}`} pointerEvents="none">
              {isSel && <circle cx={px(i)} cy={py(x.relative)} r={r + 5} fill={LINE} opacity="0.16" />}
              {isSaddle && (
                <circle cx={px(i)} cy={py(x.relative)} r={r + 3.4} fill="none" stroke={SADDLE} strokeWidth="1.4" opacity="0.75" />
              )}
              <circle
                cx={px(i)}
                cy={py(x.relative)}
                r={r}
                fill={isSaddle ? SADDLE : '#fff'}
                stroke={isSel ? LINE : isSaddle ? SADDLE : LINE}
                strokeWidth={isSel ? 3 : 2.2}
              />
            </g>
          );
        })}

        {/* 横轴编号（点密时省略） */}
        {images.map((x, i) =>
          labelStep === 1 || i % labelStep === 0 || i === n - 1 ? (
            <text
              key={`xl-${x.label}-${i}`}
              x={px(i)}
              y={M.top + plotH + 19}
              fontSize="10"
              fill={i === selected ? '#4A7BDD' : i === 0 || i === n - 1 ? '#5A6A80' : '#8A98AC'}
              fontWeight={i === selected || i === 0 || i === n - 1 ? 600 : 400}
              textAnchor="middle"
            >
              {String(i).padStart(2, '0')}
            </text>
          ) : null,
        )}

        {!hasEnergy && (
          <text x={M.left + plotW / 2} y={M.top + plotH / 2} fontSize="12" fill="#8A98AC" textAnchor="middle">
            暂无相对能量数据（nebef.pl 未输出）
          </text>
        )}

        {/* 点击热区（每个映像一条，条带宽度按实际间距均分） */}
        {images.map((x, i) => {
          const bandW = n > 1 ? plotW / (n - 1) : plotW;
          return (
            <rect
              key={`hit-${x.label}-${i}`}
              x={px(i) - bandW / 2}
              y={M.top}
              width={bandW}
              height={plotH + 26}
              fill="transparent"
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((h) => (h === i ? null : h))}
              onClick={() => onSelect(i)}
            />
          );
        })}
      </svg>
    </div>
  );
}
