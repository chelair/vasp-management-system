import { useRef } from 'react';
import { motion } from 'framer-motion';

interface Props {
  title: string;
  series: (number | null)[];
  color: string;
  unit?: string;
  threshold?: number;
  /** 悬停提示数据点（与 series 索引对齐） */
  points?: { step: number; energy: number | null; max_force: number | null }[];
  hovered?: number | null;
  onHover?: (index: number | null) => void;
}

/**
 * SVG 折线图（对齐参考实现 generate_summary_html._svg_line_chart 的格式）：
 * 4 档 y 轴刻度、首/中/末步号、轴单位、可选收敛基准线（虚线 + 标注）。
 */
export default function LineChart({
  title,
  series,
  color,
  unit,
  threshold,
  points,
  hovered,
  onHover,
}: Props) {
  const values = series.filter((v): v is number => v != null);
  if (values.length === 0) {
    return (
      <div className="analysis-chart-empty">
        {title}：暂无数据
      </div>
    );
  }

  const W = 560;
  const H = 220;
  const M = { left: 66, right: 18, top: 24, bottom: 34 };
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const all = threshold != null ? [...values, threshold] : values;
  const yMin = Math.min(...all);
  const yMax = Math.max(...all);
  const span = yMax - yMin || 1;
  const n = series.length;

  const px = (index: number) =>
    n > 1 ? M.left + (index * plotW) / (n - 1) : M.left + plotW / 2;
  const py = (value: number | null) =>
    value == null ? M.top : M.top + plotH * (1 - (value - yMin) / span);

  const yTicks = [0, 1, 2, 3].map((k) => {
    const value = yMin + (yMax - yMin) * (k / 3);
    return { value, y: py(value) };
  });
  const xTicks = [
    { step: 1, x: px(0) },
    { step: Math.ceil(series.length / 2), x: px(Math.floor((series.length - 1) / 2)) },
    { step: series.length, x: px(series.length - 1) },
  ];

  let penDown = false;
  const linePath = series
    .map((v, i) => {
      if (v == null) {
        penDown = false;
        return '';
      }
      const cmd = penDown ? 'L' : 'M';
      penDown = true;
      return `${cmd}${px(i).toFixed(1)},${py(v).toFixed(1)}`;
    })
    .filter(Boolean)
    .join(' ');
  const hoverPoint = hovered != null ? points?.[hovered] : null;
  const hoverValue = hovered != null ? series[hovered] : null;
  const lastHoverRef = useRef<number | null>(null);

  return (
    <div className="analysis-chart">
      {hoverPoint && (
        <div className="analysis-chart__hint">
          步 {hoverPoint.step} · 能量 {hoverPoint.energy != null ? hoverPoint.energy.toFixed(4) : '—'} eV · 力{' '}
          {hoverPoint.max_force != null ? hoverPoint.max_force.toFixed(4) : '—'} eV/Å
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="analysis-chart__svg" role="img" aria-label={title}>
        <text x={M.left} y="16" fontSize="13" fill="#374151">
          {title}
        </text>
        {yTicks.map(({ value, y }) => (
          <g key={value}>
            <line
              x1={M.left}
              y1={y}
              x2={W - M.right}
              y2={y}
              stroke="#E7ECF3"
              strokeWidth="1"
            />
            <text x={M.left - 6} y={y + 4} fontSize="10" fill="#6B7A90" textAnchor="end">
              {formatTick(value)}
            </text>
          </g>
        ))}
        <line x1={M.left} y1={M.top} x2={M.left} y2={M.top + plotH} stroke="#9CA3AF" />
        <line x1={M.left} y1={M.top + plotH} x2={W - M.right} y2={M.top + plotH} stroke="#9CA3AF" />
        {xTicks.map(({ step, x }) => (
          <text key={step} x={x} y={H - 14} fontSize="10" fill="#6B7A90" textAnchor="middle">
            {step}
          </text>
        ))}
        {/* 打开时从左到右绘制 */}
        <motion.path
          d={linePath}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.9, ease: 'easeInOut' }}
        />
        {threshold != null && (
          <>
            <motion.line
              x1={M.left}
              y1={py(threshold)}
              x2={W - M.right}
              y2={py(threshold)}
              stroke="#D9535B"
              strokeWidth="1.5"
              strokeDasharray="6,4"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5, duration: 0.4 }}
            />
            <text
              x={W - M.right - 4}
              y={py(threshold) - 5}
              fontSize="10"
              fill="#D9535B"
              textAnchor="end"
            >
              阈值 {threshold.toFixed(3)}
            </text>
          </>
        )}
        {/* 悬停：竖线 + 交点放大 */}
        {hovered != null && hoverValue != null && (
          <>
            <line
              x1={px(hovered)}
              y1={M.top}
              x2={px(hovered)}
              y2={M.top + plotH}
              stroke="#9CA3AF"
              strokeWidth="1"
              strokeDasharray="4,3"
            />
            <circle
              cx={px(hovered)}
              cy={py(hoverValue)}
              r="5"
              fill={color}
              stroke="#FFFFFF"
              strokeWidth="2.5"
            />
          </>
        )}
        {unit && (
          <text
            x="14"
            y={M.top + plotH / 2}
            fontSize="11"
            fill="#6B7A90"
            transform={`rotate(-90 14 ${M.top + plotH / 2})`}
            textAnchor="middle"
          >
            {unit}
          </text>
        )}
        <text x={M.left + plotW / 2} y={H - 2} fontSize="11" fill="#6B7A90" textAnchor="middle">
          离子步
        </text>
        {onHover && (
          <rect
            x={M.left}
            y={M.top}
            width={plotW}
            height={plotH}
            fill="transparent"
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              // rect 覆盖层在 viewBox 中的宽度是 plotW；用实际渲染宽度换算，
              // 自动适配不同设备/缩放（CSS 像素 -> viewBox 坐标）
              const scaleX = rect.width / plotW;
              const x = (e.clientX - rect.left) / scaleX; // 相对绘图区左缘的 viewBox 坐标
              const idx = n > 1 ? Math.round((x / plotW) * (n - 1)) : 0;
              const clamped = Math.max(0, Math.min(n - 1, idx));
              // 仅当索引变化才回调，减少无效重渲染
              if (lastHoverRef.current !== clamped) {
                lastHoverRef.current = clamped;
                onHover(clamped);
              }
            }}
            onMouseLeave={() => {
              lastHoverRef.current = null;
              onHover(null);
            }}
          />
        )}
      </svg>
    </div>
  );
}

function formatTick(value: number): string {
  if (Math.abs(value) >= 1000) return value.toExponential(2);
  return value.toPrecision(4).replace(/\.?0+$/, '');
}
