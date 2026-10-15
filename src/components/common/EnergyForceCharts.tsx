/**
 * 能量 / 力收敛曲线（ECharts 版，2026-10-15 从自研 SVG 迁移 · v0.9.60）。
 *
 * 用户口径（`待办.md`）："现有的能量、力收敛曲线是在SVG写的，把这个迁移到 ECharts 吧，
 * 图风格要保持统一，生成单 html 报告时可以将组件嵌入以实现前端的功能（暂时只迁移这个曲线）"。
 *
 * 因此：
 * - 图配置写成**纯函数** `buildEnergyForceOption`（详情页 React 组件与报告页直接挂载**共用同一套配置**，
 *   保证"图风格统一"，也方便以后把组件嵌进单文件 HTML 报告）；
 * - 保留旧 SVG 的全部信息：标题、单位轴名、4 档 y 刻度、首/中/末步号、力收敛**阈值虚线 + 标注**、
 *   悬停十字线 + 数值提示（提示里同时给能量与力）、空状态；
 * - 两张图**悬停联动**（在能量图上移动，力图同步高亮同一步）——旧实现的手感保持不变。
 */

import { useEffect, useMemo, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';

import useEcharts from '../dashboard/useEcharts';

export interface EnergyForcePoint {
  step: number;
  energy: number | null;
  max_force: number | null;
}

export type EnergyForceKind = 'energy' | 'force';

const ENERGY_COLOR = '#2C6FBB';
const FORCE_COLOR = '#C0392B';
const THRESHOLD_COLOR = '#D9535B';
const AXIS_COLOR = '#9CA3AF';
const LABEL_COLOR = '#6B7A90';

const TITLES: Record<EnergyForceKind, string> = {
  energy: '能量 随离子步',
  force: '最大力 随离子步',
};
const UNITS: Record<EnergyForceKind, string> = {
  energy: '能量 (eV)',
  force: '最大力 (eV/Å)',
};

function fmtTick(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs !== 0 && abs < 1e-3) return value.toExponential(1);
  if (abs >= 1000) return value.toFixed(0);
  if (abs >= 10) return value.toFixed(2);
  return value.toFixed(3);
}

/**
 * 纯函数：一张收敛曲线的 ECharts 配置。**详情页与报告页共用**（口径改这里即可）。
 *
 * - `threshold`：力收敛阈值（只在力图里画虚线 + 标注）；
 * - y 轴按"数据 + 阈值"的真实范围贴合（与旧 SVG 一致），不做 ECharts 默认留白；
 * - 提示卡里同时给能量与力（旧实现的 `analysis-chart__hint` 就是这两行信息）。
 */
export function buildEnergyForceOption(
  kind: EnergyForceKind,
  points: EnergyForcePoint[],
  options: { threshold?: number | null; thresholdNote?: string | null } = {},
): EChartsCoreOption {
  const valueOf = (p: EnergyForcePoint) => (kind === 'energy' ? p.energy : p.max_force);
  const values = points
    .map(valueOf)
    .filter((v): v is number => v != null && Number.isFinite(v));
  const threshold = options.threshold ?? null;
  const scaled = threshold != null ? [...values, threshold] : values;
  const yMin = scaled.length ? Math.min(...scaled) : 0;
  const yMax = scaled.length ? Math.max(...scaled) : 1;
  const color = kind === 'energy' ? ENERGY_COLOR : FORCE_COLOR;

  const markLines =
    threshold != null
      ? [
          {
            yAxis: threshold,
            lineStyle: { type: 'dashed' as const, color: THRESHOLD_COLOR, width: 1.5 },
            label: {
              show: true,
              position: 'insideEndTop' as const,
              formatter: `阈值 ${threshold.toFixed(3)}${options.thresholdNote ? `（${options.thresholdNote}）` : ''}`,
              color: THRESHOLD_COLOR,
              fontSize: 11,
            },
          },
        ]
      : [];

  return {
    animation: false,
    grid: { left: 70, right: 20, top: 38, bottom: 30 },
    title: {
      text: TITLES[kind],
      left: 8,
      top: 6,
      textStyle: { fontSize: 12.5, fontWeight: 'normal' as const, color: '#374151' },
    },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'line' as const, lineStyle: { color: AXIS_COLOR, type: 'dashed' as const } },
      confine: true,
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params];
        const first = list[0] as { dataIndex?: number } | undefined;
        const index = typeof first?.dataIndex === 'number' ? first.dataIndex : -1;
        const point = index >= 0 ? points[index] : undefined;
        if (!point) return '';
        return [
          `步 ${point.step}`,
          `能量 ${point.energy != null ? `${point.energy.toFixed(4)} eV` : '—'}`,
          `最大力 ${point.max_force != null ? `${point.max_force.toFixed(4)} eV/Å` : '—'}`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'value' as const,
      min: 'dataMin' as const,
      max: 'dataMax' as const,
      minInterval: 1,
      splitLine: { show: true, lineStyle: { color: '#E7ECF3' } },
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisTick: { show: false },
      axisLabel: { color: LABEL_COLOR, fontSize: 10, showMinLabel: true, showMaxLabel: true },
    },
    yAxis: {
      type: 'value' as const,
      min: yMin,
      max: yMax === yMin ? yMin + 1 : yMax,
      splitNumber: 3,
      name: UNITS[kind],
      nameLocation: 'middle' as const,
      nameGap: 46,
      nameTextStyle: { color: LABEL_COLOR, fontSize: 11 },
      axisLine: { show: true, lineStyle: { color: AXIS_COLOR } },
      axisLabel: { color: LABEL_COLOR, fontSize: 10, formatter: fmtTick },
      splitLine: { show: true, lineStyle: { color: '#E7ECF3' } },
    },
    series: [
      {
        name: TITLES[kind],
        type: 'line' as const,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 7,
        sampling: 'lttb' as const,
        connectNulls: false,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        emphasis: { focus: 'none' as const, scale: 1.4 },
        data: points.map((p) => [p.step, valueOf(p)]),
        markLine: { silent: true, symbol: 'none', label: { show: false }, data: markLines },
      },
    ],
  };
}

interface SingleProps {
  kind: EnergyForceKind;
  points: EnergyForcePoint[];
  threshold?: number | null;
  thresholdNote?: string | null;
  height?: number;
  /** 需要同步显示的"步下标"（来自兄弟图）；null = 隐藏提示 */
  followIndex?: number | null;
  /** 用户在本图悬停 → 回报步下标（null = 离开） */
  onHoverIndex?: (index: number | null) => void;
}

/** 一张收敛曲线（报告页单独用它；详情页用下面的双图组件） */
export function EnergyForceChart({
  kind,
  points,
  threshold,
  thresholdNote,
  height = 240,
  followIndex = null,
  onHoverIndex,
}: SingleProps) {
  const option = useMemo(
    () => buildEnergyForceOption(kind, points, { threshold, thresholdNote }),
    [kind, points, threshold, thresholdNote],
  );
  const [chart, setChart] = useState<{
    on: (event: string, handler: (payload: unknown) => void) => void;
    off: (event: string, handler: (payload: unknown) => void) => void;
    dispatchAction: (action: Record<string, unknown>) => void;
  } | null>(null);
  const containerRef = useEcharts(option, [option], (instance) => {
    setChart((prev) => (prev === instance ? prev : (instance as never)));
  });

  // 上报悬停：ECharts 的 updateAxisPointer 给的是**轴值**（步号），换算回数组下标
  useEffect(() => {
    if (!chart) return;
    const handler = (event: unknown) => {
      const axes = (event as { axesInfo?: { value?: number }[] } | null)?.axesInfo;
      const value = axes?.[0]?.value;
      const index = points.findIndex((p) => p.step === value);
      onHoverIndex?.(index >= 0 ? index : null);
    };
    const leave = () => onHoverIndex?.(null);
    chart.on('updateAxisPointer', handler);
    chart.on('globalout', leave);
    return () => {
      chart.off('updateAxisPointer', handler);
      chart.off('globalout', leave);
    };
  }, [chart, points, onHoverIndex]);

  // 跟随兄弟图（同步高亮 + 提示）
  useEffect(() => {
    if (!chart) return;
    if (followIndex == null) chart.dispatchAction({ type: 'hideTip' });
    else chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: followIndex });
  }, [chart, followIndex]);

  const hasData = points.some((p) =>
    kind === 'energy' ? p.energy != null : p.max_force != null,
  );
  if (!hasData) {
    return <div className="analysis-chart-empty">{TITLES[kind]}：暂无数据</div>;
  }
  return <div className="analysis-chart" style={{ height }} ref={containerRef} />;
}

interface PairProps {
  points: EnergyForcePoint[];
  /** 力收敛阈值（来自 INCAR 的 EDIFFG；缺省 0.02） */
  forceThreshold?: number | null;
  /** 阈值来源说明（`EDIFFG` / `默认值`） */
  forceThresholdNote?: string | null;
  height?: number;
}

/**
 * 能量 / 力双图（巡检详情页用）：两图**悬停联动** —— 在一张图上移动，
 * 另一张同步高亮同一步并弹出同样数值（旧 SVG 实现的行为）。
 */
export default function EnergyForceCharts({
  points,
  forceThreshold,
  forceThresholdNote,
  height = 240,
}: PairProps) {
  /** 当前悬停的步下标 + 来源（energy / force），避免互相回灌造成抖动 */
  const [hover, setHover] = useState<{ index: number | null; source: EnergyForceKind | null }>({
    index: null,
    source: null,
  });
  const makeHandler = (kind: EnergyForceKind) => (index: number | null) =>
    setHover({ index, source: index == null ? null : kind });
  return (
    <div className="analysis-charts">
      <EnergyForceChart
        kind="energy"
        points={points}
        height={height}
        followIndex={hover.source === 'force' ? hover.index : null}
        onHoverIndex={makeHandler('energy')}
      />
      <EnergyForceChart
        kind="force"
        points={points}
        height={height}
        threshold={forceThreshold ?? 0.02}
        thresholdNote={forceThresholdNote ?? null}
        followIndex={hover.source === 'energy' ? hover.index : null}
        onHoverIndex={makeHandler('force')}
      />
    </div>
  );
}
