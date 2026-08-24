import { motion } from 'framer-motion';
import type { TrendPoint } from '../../types';

/** 轻量 SVG 趋势图（面积 + 折线 + 数据点），无第三方图表依赖 */
export default function TrendChart({ data }: { data: TrendPoint[] }) {
  const W = 640;
  const H = 220;
  const P = { top: 24, right: 18, bottom: 34, left: 34 };
  const innerW = W - P.left - P.right;
  const innerH = H - P.top - P.bottom;
  const max = Math.max(...data.map((d) => d.value)) + 2;
  const min = 0;

  const points = data.map((d, i) => {
    const x = P.left + (i * innerW) / (data.length - 1);
    const y = P.top + innerH - ((d.value - min) / (max - min)) * innerH;
    return { ...d, x, y };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L${points[points.length - 1].x},${P.top + innerH} L${points[0].x},${P.top + innerH} Z`;
  const gridTicks = [0, 0.5, 1];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="trend-chart" role="img" aria-label="任务趋势图">
      <defs>
        <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#5B8DEF" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#5B8DEF" stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id="trendLine" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#5B8DEF" />
          <stop offset="100%" stopColor="#67C6B0" />
        </linearGradient>
      </defs>

      {gridTicks.map((t) => {
        const y = P.top + innerH - t * innerH;
        const label = Math.round(min + t * (max - min));
        return (
          <g key={t}>
            <line
              x1={P.left}
              y1={y}
              x2={W - P.right}
              y2={y}
              stroke="#EDF1F7"
              strokeDasharray="4 4"
            />
            <text x={P.left - 8} y={y + 4} textAnchor="end" fontSize="11" fill="#9AA7B8">
              {label}
            </text>
          </g>
        );
      })}

      <motion.path
        d={areaPath}
        fill="url(#trendFill)"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.2 }}
      />
      <motion.path
        d={linePath}
        fill="none"
        stroke="url(#trendLine)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.9, ease: 'easeInOut' }}
      />

      {points.map((p) => (
        <g key={p.date}>
          <circle cx={p.x} cy={p.y} r="4.5" fill="#fff" stroke="#5B8DEF" strokeWidth="2.5" />
          <text x={p.x} y={p.y - 11} textAnchor="middle" fontSize="11" fontWeight="600" fill="#6B7A90">
            {p.value}
          </text>
          <text x={p.x} y={P.top + innerH + 20} textAnchor="middle" fontSize="11" fill="#9AA7B8">
            {p.date}
          </text>
        </g>
      ))}
    </svg>
  );
}
