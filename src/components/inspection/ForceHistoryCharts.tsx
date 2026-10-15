import EnergyForceCharts from '../common/EnergyForceCharts';
import type { ForceHistoryPoint } from '../../types';

interface Props {
  history: ForceHistoryPoint[];
  /** 最大力收敛阈值（真实值来自 INCAR 的 EDIFFG；缺省退回 0.02） */
  forceThreshold?: number | null;
  /** 阈值来源：`incar:EDIFFG` / `registry` */
  forceThresholdSource?: string | null;
}

/**
 * 能量/力双图组（2026-10-15 从自研 SVG 迁到 ECharts，v0.9.60）：
 * 实现全部在 `components/common/EnergyForceCharts.tsx`（与报告页共用同一套 ECharts 配置），
 * 这里只把巡检详情的 props 映射过去。
 */
export default function ForceHistoryCharts({
  history,
  forceThreshold,
  forceThresholdSource,
}: Props) {
  const thresholdNote =
    forceThresholdSource === 'incar:EDIFFG'
      ? 'EDIFFG'
      : forceThresholdSource === 'registry'
        ? '默认值'
        : undefined;
  return (
    <EnergyForceCharts
      points={history}
      forceThreshold={forceThreshold}
      forceThresholdNote={thresholdNote}
    />
  );
}
