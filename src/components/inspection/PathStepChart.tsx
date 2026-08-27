import { useState } from 'react';
import type { FreeEnergyStructure } from '../../api/inspections';

interface Props {
  structures: FreeEnergyStructure[];
  onSelect: (taskId: string) => void;
}

/**
 * 自由能路径台阶图：每个中间体占据一个台阶（水平直线），台阶之间用更细虚线连接；
 * 无能量处断开；未收敛/未矫正用警示色；悬停时台阶轻微上浮，点击跳转详情。
 */
export default function PathStepChart({ structures, onSelect }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const valid = structures.filter((s) => s.free_energy != null);
  if (valid.length === 0) {
    return <div className="analysis-chart-empty">路径上暂无可用能量数据</div>;
  }

  const W = 620;
  const H = 260;
  const M = { left: 70, right: 20, top: 24, bottom: 42 };
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const energies = valid.map((s) => s.free_energy as number);
  const yMin = Math.min(...energies);
  const yMax = Math.max(...energies);
  const span = yMax - yMin || 1;
  const n = structures.length;
  // 每个结构占 1 格 + 结构间 1 格虚线连接区
  const padX = 12; // 首尾留白，台阶不紧贴坐标轴
  const unitX = (plotW - padX * 2) / Math.max(2 * n - 1, 1);
  const px = (k: number) => M.left + padX + k * unitX;
  const py = (v: number) => M.top + plotH * (1 - (v - yMin) / span);

  const warnOf = (s: FreeEnergyStructure) => !s.converged || !s.corrected;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="analysis-chart__svg" role="img" aria-label="自由能路径台阶图">
      <text x={M.left} y="16" fontSize="13" fill="#374151">
        自由能路径台阶图（eV）
      </text>
      {[0, 1, 2, 3].map((k) => {
        const value = yMin + (yMax - yMin) * (k / 3);
        const y = py(value);
        return (
          <g key={k}>
            <line x1={M.left} y1={y} x2={W - M.right} y2={y} stroke="#E7ECF3" />
            <text x={M.left - 6} y={y + 4} fontSize="10" fill="#6B7A90" textAnchor="end">
              {value.toFixed(3)}
            </text>
          </g>
        );
      })}
      <line x1={M.left} y1={M.top} x2={M.left} y2={M.top + plotH} stroke="#9CA3AF" />
      <line x1={M.left} y1={M.top + plotH} x2={W - M.right} y2={M.top + plotH} stroke="#9CA3AF" />

      {/* 台阶间细虚线连接（两端均有能量才连接） */}
      {structures.map((s, i) => {
        if (i >= n - 1 || s.free_energy == null || structures[i + 1].free_energy == null) {
          return null;
        }
        return (
          <line
            key={`link-${i}`}
            x1={px(2 * i + 1)}
            y1={py(s.free_energy)}
            x2={px(2 * i + 2)}
            y2={py(structures[i + 1].free_energy as number)}
            stroke="#B6C2D4"
            strokeWidth="1"
            strokeDasharray="4,4"
          />
        );
      })}

      {/* 台阶水平线 */}
      {structures.map((s, i) => {
        if (s.free_energy == null) return null;
        const x1 = px(2 * i);
        const x2 = px(2 * i + 1);
        const y = py(s.free_energy);
        const warn = warnOf(s);
        const hover = hovered === i;
        return (
          <g key={s.task_id}>
            {hover && (
              <line
                x1={x1}
                y1={y}
                x2={x2}
                y2={y}
                stroke={warn ? '#E8A33D' : '#2C9DA8'}
                strokeWidth={9}
                strokeLinecap="round"
                opacity="0.25"
                pointerEvents="none"
              />
            )}
            <line
              x1={x1}
              y1={y}
              x2={x2}
              y2={y}
              stroke={warn ? '#E8A33D' : '#2C9DA8'}
              strokeWidth={hover ? 4 : 2.5}
              strokeLinecap="round"
              pointerEvents="none"
            />
            <text
              x={(x1 + x2) / 2}
              y={y - 7}
              fontSize="10"
              fill={warn ? '#C97F24' : '#2C9DA8'}
              textAnchor="middle"
              fontWeight={hover ? 700 : 400}
            >
              {s.free_energy.toFixed(3)}
            </text>
            <text x={(x1 + x2) / 2} y={H - 16} fontSize="10" fill="#6B7A90" textAnchor="middle">
              结构 {s.structure_label}
            </text>
            {warn && (
              <title>{`结构 ${s.structure_label}：自由能 ${s.free_energy.toFixed(4)} eV`}</title>
            )}
            {/* 更大的悬停/点击热区（透明矩形覆盖台阶） */}
            <rect
              x={x1}
              y={y - 8}
              width={x2 - x1}
              height={16}
              fill="transparent"
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onSelect(s.task_id)}
            />
          </g>
        );
      })}

      <text x={M.left + plotW / 2} y={H - 2} fontSize="11" fill="#6B7A90" textAnchor="middle">
        中间体顺序
      </text>
    </svg>
  );
}
