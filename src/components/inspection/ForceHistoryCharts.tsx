import { useState } from 'react';
import LineChart from './LineChart';
import type { ForceHistoryPoint } from '../../types';

interface Props {
  history: ForceHistoryPoint[];
  /** 最大力收敛阈值（真实值来自 INCAR 的 EDIFFG；缺省退回 0.02） */
  forceThreshold?: number | null;
  /** 阈值来源：`incar:EDIFFG` / `registry` */
  forceThresholdSource?: string | null;
}

/**
 * 能量/力双图组：悬停状态只在组件内部管理，
 * 避免 mousemove 触发整个详情弹窗重渲染导致卡顿。
 */
export default function ForceHistoryCharts({
  history,
  forceThreshold,
  forceThresholdSource,
}: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const threshold = forceThreshold ?? 0.02;
  const thresholdNote =
    forceThresholdSource === 'incar:EDIFFG'
      ? 'EDIFFG'
      : forceThresholdSource === 'registry'
        ? '默认值'
        : undefined;
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
        threshold={threshold}
        thresholdNote={thresholdNote}
        points={history}
        hovered={hovered}
        onHover={setHovered}
      />
    </div>
  );
}
