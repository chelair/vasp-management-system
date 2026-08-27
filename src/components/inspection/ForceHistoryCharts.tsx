import { useState } from 'react';
import LineChart from './LineChart';
import type { ForceHistoryPoint } from '../../types';

interface Props {
  history: ForceHistoryPoint[];
}

/**
 * 能量/力双图组：悬停状态只在组件内部管理，
 * 避免 mousemove 触发整个详情弹窗重渲染导致卡顿。
 */
export default function ForceHistoryCharts({ history }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  return (
    <div className="analysis-charts">
      <LineChart
        title="能量 随离子步"
        series={history.map((p) => p.energy)}
        color="#2C6FBB"
        unit="能量 (eV)"
        points={history}
        hovered={hovered}
        onHover={setHovered}
      />
      <LineChart
        title="最大力 随离子步"
        series={history.map((p) => p.max_force)}
        color="#C0392B"
        unit="最大力 (eV/Å)"
        threshold={0.02}
        points={history}
        hovered={hovered}
        onHover={setHovered}
      />
    </div>
  );
}
