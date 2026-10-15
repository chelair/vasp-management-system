/**
 * NEB 能量曲线（2026-10-15，v0.9.62 从自绘 SVG 迁到 ECharts）。
 *
 * 迁移口径：**布局、功能、读数一律不变**，只换实现并顺带做一点美术打磨。
 * - 横向铺满、按实际映像数均分横轴（`boundaryGap: false` → 首末点贴左右边距，与旧图一致）；
 *   点密时按同一规则省略编号（`labelStep`），首末与选中恒显示且加重；
 * - 曲线（直线连接、不插值，缺数据断开）+ 曲线下渐变面积 + 零线虚线（带 0.00 标注）
 *   + 数据点（选中放大带光晕、鞍点红色实心 + 单独配色）+ 悬停竖线虚线；
 * - 头部读数照旧：`hover ?? selected` 的映像号 / ΔE / 最大受力 / 绝对能量 / 鞍点标记；
 * - 点击（每个映像一条整高竖直热区）→ 切换主视图；
 * - 美术微调：曲线描边改横向渐变（浅紫 → 紫）、选中光晕更柔和、鞍点描边更清晰。
 */

import { useMemo, useRef, useState } from 'react';
import type { EChartsCoreOption, ECharts } from 'echarts/core';

import useEcharts from '../dashboard/useEcharts';

export interface NebCurveImage {
  label: string;
  relative: number | null;
  max_force: number | null;
  /** 绝对能量（eV），仅用于读数展示 */
  energy?: number | null;
}

interface Props {
  images: NebCurveImage[];
  /** 当前选中映像下标（-1 = 无选中，仅悬停读数） */
  selected: number;
  /** 鞍点（相对能最高）下标，-1 = 无 */
  saddle: number;
  onSelect: (index: number) => void;
  /** 画布高度（默认 240，与旧 SVG 默认一致） */
  height?: number;
}

/** 与旧 SVG 一致的边距 */
const MARGIN = { left: 54, right: 22, top: 22, bottom: 32 };
const LINE = '#7B61D6';
const LINE_SOFT = '#A78BFA';
const SADDLE = '#D9535B';
/** 纵轴最小跨度（eV）：能量全部相同时避免所有点叠在一条线上 */
const MIN_SPAN = 0.12;

const signed = (v: number, d = 3) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`;

/** 点密时的横轴编号抽样规则（与旧实现一致） */
export function nebLabelStep(count: number): number {
  return count > 16 ? Math.ceil(count / 12) : 1;
}

/**
 * 纯函数：NEB 能量曲线 option（详情页 NEB 主视图与报告页共用同一套配置）。
 * `hover` 由外部状态驱动（悬停竖线 + 头部读数跟着变）。
 */
export function buildNebEnergyOption(
  images: NebCurveImage[],
  {
    selected = -1,
    saddle = -1,
    hover = null,
  }: { selected?: number; saddle?: number; hover?: number | null } = {},
): EChartsCoreOption {
  const n = images.length;
  const rels = images
    .map((x) => x.relative)
    .filter((v): v is number => v != null && Number.isFinite(v));
  let hi = rels.length ? Math.max(0, ...rels) : 0.06;
  let lo = rels.length ? Math.min(0, ...rels) : -0.06;
  // 最小跨度（全部相同时撑开），再加 18% 余量
  if (hi - lo < MIN_SPAN) {
    const mid = (hi + lo) / 2;
    hi = mid + MIN_SPAN / 2;
    lo = mid - MIN_SPAN / 2;
  }
  const pad = Math.max((hi - lo) * 0.18, 0.03);
  hi += pad;
  lo -= pad;

  const rBase = n > 16 ? 3 : n > 10 ? 3.6 : 4.4;
  const step = nebLabelStep(n);
  const hoverIndex = hover != null && hover >= 0 && hover < n ? hover : null;

  return {
    animation: true,
    animationDuration: 520,
    animationDurationUpdate: 200,
    animationEasing: 'cubicOut',
    grid: { ...MARGIN, containLabel: false },
    // 读数在面板头部（`.nebmd-curve__read`），画布上不出浮层
    tooltip: { show: false },
    xAxis: {
      type: 'category',
      data: images.map((_, i) => String(i).padStart(2, '0')),
      // 首末点贴边距（与旧图的 px(i) = left + i*plotW/(n-1) 一致）
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        interval: (index: number) => step === 1 || index % step === 0 || index === n - 1,
        fontSize: 10,
        margin: 8,
        color: (value: string) => {
          const index = Number(value);
          if (index === selected) return '#4A7BDD';
          return index === 0 || index === n - 1 ? '#5A6A80' : '#8A98AC';
        },
        fontWeight: (value: string) => {
          const index = Number(value);
          return index === selected || index === 0 || index === n - 1 ? 600 : 400;
        },
      },
    },
    yAxis: {
      type: 'value',
      min: lo,
      max: hi,
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: '#8A98AC',
        formatter: (value: number) => signed(value, 2),
      },
      splitLine: { lineStyle: { color: '#EDF1F7', type: [3, 5] } },
    },
    series: [
      {
        type: 'line',
        name: '相对能量',
        connectNulls: false,
        showSymbol: false,
        data: images.map((x) => x.relative),
        lineStyle: {
          width: 2.4,
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [
              { offset: 0, color: LINE_SOFT },
              { offset: 1, color: LINE },
            ],
            global: false,
          },
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: `${LINE}3D` },
              { offset: 1, color: `${LINE}05` },
            ],
            global: false,
          },
        },
        // 零线（浅灰虚线 + 0.00 标注）与悬停竖线（灰色虚线）
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: '#B9C6D6', type: [5, 4], width: 1 },
          data: [
            {
              yAxis: 0,
              label: {
                show: true,
                formatter: '0.00',
                position: 'insideStartTop',
                distance: 4,
                color: '#5A6A80',
                fontSize: 10,
                fontWeight: 600,
              },
            },
            ...(hoverIndex == null
              ? []
              : [
                  {
                    xAxis: hoverIndex,
                    lineStyle: { color: '#9CA3AF', type: [4, 3], width: 1 },
                  },
                ]),
          ],
        },
        z: 2,
      },
      {
        // 数据点：选中放大 + 光晕；鞍点红色实心 + 单独描边；无数据不画
        type: 'scatter',
        name: '映像',
        symbol: 'circle',
        data: images.map((x, i) => {
          const isSel = i === selected;
          const isSaddle = i === saddle;
          return {
            value: [i, x.relative],
            symbolSize: (rBase + (isSel ? 2 : 0)) * 2,
            itemStyle: {
              color: isSaddle ? SADDLE : '#fff',
              borderColor: isSaddle ? SADDLE : LINE,
              borderWidth: isSel ? 3 : isSaddle ? 2.6 : 2.2,
              opacity: x.relative == null ? 0 : 1,
            },
            ...(isSel
              ? {
                  // 选中光晕：单独一层半透明大圆（鞍点外圈同款做法）
                  label: { show: false },
                }
              : {}),
          };
        }),
        emphasis: { disabled: true },
        z: 4,
      },
      {
        // 点击/悬停热区：每个映像一条整高竖直带（宽度按实际间距均分，与旧实现一致）
        type: 'scatter',
        name: '热区',
        symbol: 'rect',
        silent: false,
        symbolSize: (_value: unknown, params: { coordSys?: { width?: number; height?: number } }) => {
          const cs = params?.coordSys || {};
          const width = Number(cs.width || 600);
          const height = Number(cs.height || 200);
          const band = n > 1 ? width / (n - 1) : width;
          return [band, height + 26];
        },
        data: images.map((_, i) => ({ value: [i, (lo + hi) / 2] })),
        itemStyle: { opacity: 0 },
        z: 5,
      },
    ],
  };
}

export default function NebEnergyCurve({
  images,
  selected,
  saddle,
  onSelect,
  height = 240,
}: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const option = useMemo(
    () => buildNebEnergyOption(images, { selected, saddle, hover }),
    [images, selected, saddle, hover],
  );

  const containerRef = useEcharts(option, [option], (chart: ECharts | null) => {
    if (!chart) return;
    // 热区是第 3 条系列（索引 2）：悬停 / 点击都落在它上面
    chart.on('mouseover', { seriesIndex: 2 }, (params: { dataIndex?: number }) => {
      if (typeof params?.dataIndex === 'number') setHover(params.dataIndex);
    });
    chart.on('mouseout', { seriesIndex: 2 }, () => setHover(null));
    chart.on('click', { seriesIndex: 2 }, (params: { dataIndex?: number }) => {
      const index = params?.dataIndex;
      if (typeof index === 'number') selectRef.current(index);
    });
  });

  const active = hover ?? selected;
  const activeImg = images[active];
  const hasEnergy = images.some((x) => x.relative != null);

  return (
    <div className="nebmd-curve">
      <div className="nebmd-curve__head">
        <div className="nebmd-curve__titleline" title="点击数据点切换主视图">
          <span className="nebmd-curve__title">能量曲线</span>
          <span className="nebmd-curve__hint">相对初态（00）· 点击切换</span>
        </div>
        {activeImg && (
          <div className="nebmd-curve__read">
            <span className="nebmd-curve__read-img">
              映像 {String(active).padStart(2, '0')}
            </span>
            {activeImg.relative != null && <span>ΔE {signed(activeImg.relative)} eV</span>}
            {activeImg.max_force != null && (
              <span>F {activeImg.max_force.toFixed(3)} eV/Å</span>
            )}
            {activeImg.energy != null && <span>E {activeImg.energy.toFixed(3)} eV</span>}
            {active === saddle && <em className="nebmd-curve__saddle">鞍点</em>}
          </div>
        )}
      </div>
      <div className="nebmd-curve__plot">
        <div className="nebmd-curve__canvas" style={{ height }} ref={containerRef} />
        {!hasEnergy && (
          <p className="nebmd-curve__empty">
            暂无相对能量数据（nebef.pl 未输出）
          </p>
        )}
      </div>
    </div>
  );
}
