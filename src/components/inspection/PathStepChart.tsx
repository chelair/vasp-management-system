/**
 * 自由能路径**台阶图**（2026-10-15，v0.9.62 从自绘 SVG 迁到 ECharts）。
 *
 * 迁移口径：**布局、功能、读数一律不变**，只换实现并顺带做一点美术打磨。
 * - 纵轴仍是**相对自由能**（第一个有数据的中间体为参考，ΔE = E − E_ref）；
 * - 台阶仍是「渐变面积 + 4px 圆头台阶边 + 数值标签 + 结构编号 chip + 状态点」，
 *   几何与旧 SVG 完全一致（同样的边距 68/24/34/60、同样的 `GAP_RATIO = 0.45`）；
 * - 交互照旧：悬停上浮发光 + 信息卡（自由能 / 相对 ΔE / DFT / 矫正项 + 收敛矫正状态）、
 *   点击台阶打开该结构的巡检详情；纯色仍是青（收敛且已矫正）/ 琥珀（未收敛或未矫正）/ 灰虚线（无数据）；
 * - 美术微调：台阶边与面积改用**横向渐变**（青/琥珀同族深浅），chip 圆角与描边随悬停加亮，
 *   入场动画改为 ECharts 的错峰生长（尊重 `prefers-reduced-motion`）。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';

import type { FreeEnergyStructure } from '../../api/inspections';
import useEcharts from '../dashboard/useEcharts';

interface Props {
  structures: FreeEnergyStructure[];
  onSelect: (taskId: string) => void;
}

/** 与旧 SVG 完全一致的画布几何（保证布局不变） */
const MARGIN = { left: 68, right: 24, top: 34, bottom: 60 };
const GAP_RATIO = 0.45; // 台阶之间连接区占台阶宽度的比例

const OK_COLOR = '#2C9DA8';
const WARN_COLOR = '#E8A33D';
const EMPTY_COLOR = '#C3CEDA';

function fmt(v: number | null | undefined, digits = 3) {
  return v == null ? '—' : v.toFixed(digits);
}

function signed(v: number, digits = 3) {
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}

/** 相对能口径：参考 = 第一个有自由能的中间体（缺失时退回最小值） */
export function freeEnergyReference(structures: FreeEnergyStructure[]): {
  ref: number | null;
  relOf: (s: FreeEnergyStructure) => number | null;
} {
  const available = structures.filter((s) => s.free_energy != null);
  if (!available.length) return { ref: null, relOf: () => null };
  const ref =
    (available.find((s) => s.free_energy != null)?.free_energy as number) ??
    Math.min(...available.map((s) => s.free_energy as number));
  return {
    ref,
    relOf: (s) => (s.free_energy == null ? null : s.free_energy - ref),
  };
}

function areaGradient(color: string) {
  return {
    type: 'linear' as const,
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: `${color}42` },
      { offset: 1, color: `${color}05` },
    ],
    global: false,
  };
}

function barGradient(from: string, to: string, mirrored: boolean) {
  return {
    type: 'linear' as const,
    x: 0,
    y: 0,
    x2: 1,
    y2: 0,
    colorStops: mirrored
      ? [
          { offset: 0, color: to },
          { offset: 1, color: from },
        ]
      : [
          { offset: 0, color: from },
          { offset: 1, color: to },
        ],
    global: false,
  };
}

/** custom 系列 renderItem 用到的 api（只取本图用得到的几个方法，避免引 echarts 深路径类型） */
interface CustomApi {
  coord(value: (number | string)[]): number[];
  getWidth(): number;
  getHeight(): number;
}

/** 悬停信息卡（沿用 `.fe-tip` 的 DOM 与样式，只是换成 ECharts 的 tooltip 承载） */
function tipHtml(s: FreeEnergyStructure, rel: number | null): string {
  const warn = !s.converged || !s.corrected;
  return (
    '<div class="fe-tip fe-tip--ec">' +
    `<div class="fe-tip__title">结构 ${s.structure_label}<span class="fe-tip__dot${
      warn ? ' is-warn' : ''
    }"></span></div>` +
    `<div class="fe-tip__row"><span>自由能</span><b>${fmt(s.free_energy, 4)} eV</b></div>` +
    `<div class="fe-tip__row"><span>相对 ΔE</span><b>${
      rel == null ? '—' : `${signed(rel, 4)} eV`
    }</b></div>` +
    `<div class="fe-tip__row"><span>DFT 能量</span><b>${fmt(s.dft_energy, 4)} eV</b></div>` +
    `<div class="fe-tip__row"><span>矫正项</span><b>${
      s.correction == null ? '—' : `${signed(s.correction, 4)} eV`
    }</b></div>` +
    '<div class="fe-tip__foot">' +
    `${s.converged ? '已收敛' : '未收敛'} · ${s.corrected ? '已矫正' : '未矫正'}` +
    '<span class="fe-tip__hint">点击查看巡检详情</span></div></div>'
  );
}

/**
 * 纯函数：台阶图 option（详情页与报告页共用同一套配置）。
 * `hovered` 由外部状态驱动（悬停上浮 + 高亮 chip），点击事件在组件里绑。
 */
export function buildFreeEnergyStepOption(
  structures: FreeEnergyStructure[],
  { hovered = null }: { hovered?: number | null } = {},
): EChartsCoreOption {
  const n = structures.length;
  const { relOf } = freeEnergyReference(structures);
  const rels = structures
    .map((s) => relOf(s))
    .filter((v): v is number => v != null);
  const hiRaw = Math.max(0, ...rels);
  const loRaw = Math.min(0, ...rels);
  const pad = Math.max((hiRaw - loRaw) * 0.18, 0.2);
  const hi = rels.length ? hiRaw + pad : 0.5;
  const lo = rels.length ? loRaw - pad : -0.5;

  const renderItem = (params: { dataIndex: number }, api: CustomApi) => {
    const index = params.dataIndex;
    const item = structures[index];
    if (!item) return { type: 'group', children: [] };
    const width = api.getWidth();
    const height = api.getHeight();
    const plotW = width - MARGIN.left - MARGIN.right;
    const plotH = height - MARGIN.top - MARGIN.bottom;
    const stepW = plotW / (n + Math.max(0, n - 1) * GAP_RATIO);
    const gap = stepW * GAP_RATIO;
    const x1 = MARGIN.left + index * (stepW + gap);
    const x2 = x1 + stepW;
    const center = (x1 + x2) / 2;
    const zeroY = api.coord([index, 0])[1] as number;
    const rel = relOf(item);
    const y = rel == null ? zeroY : (api.coord([index, rel])[1] as number);
    const warn = !item.converged || !item.corrected;
    const hover = hovered === index;
    const lift = hover ? -3 : 0;
    const plotBottom = MARGIN.top + plotH;
    const color = rel == null ? EMPTY_COLOR : warn ? WARN_COLOR : OK_COLOR;

    const children: Record<string, unknown>[] = [];
    // 面积（仅有效数据）：从台阶边向下渐变到 ΔE = 0
    if (rel != null) {
      children.push({
        type: 'rect',
        shape: {
          x: x1,
          y: Math.min(y + lift, zeroY),
          width: stepW,
          height: Math.abs(zeroY - (y + lift)),
        },
        style: { fill: areaGradient(color) },
        silent: true,
      });
    }
    // 台阶边（4px 圆头；无数据为灰虚线）
    children.push({
      type: 'line',
      shape: { x1, y1: y + lift, x2, y2: y + lift },
      style: {
        stroke:
          rel == null
            ? EMPTY_COLOR
            : warn
              ? barGradient('#F5BE68', WARN_COLOR, rel < 0)
              : barGradient('#3FB3BD', OK_COLOR, rel < 0),
        lineWidth: hover ? 5 : 4,
        lineCap: 'round',
        lineDash: rel == null ? [6, 6] : undefined,
      },
      silent: true,
    });
    // 能量标签
    children.push({
      type: 'text',
      style: {
        text: rel == null ? '无数据' : signed(rel),
        x: center,
        y: y + lift - 8,
        textAlign: 'center',
        textVerticalAlign: 'bottom',
        fill: rel == null ? '#96A3B5' : warn ? '#C07A1E' : '#1F7C86',
        fontSize: 11,
        fontWeight: hover ? 700 : 600,
        fontFamily: 'inherit',
      },
      silent: true,
    });
    // 状态点（未收敛 / 未矫正）
    if (warn && rel != null) {
      children.push({
        type: 'circle',
        shape: { cx: x2 - 4, cy: y + lift - 16, r: 3.2 },
        style: { fill: WARN_COLOR },
        silent: true,
      });
    }
    // 结构编号 chip（横轴下方）
    children.push({
      type: 'rect',
      shape: { x: center - 34, y: plotBottom + 14, width: 68, height: 22, r: 11 },
      style: {
        fill: hover ? '#EAF1FF' : '#F4F7FB',
        stroke: hover ? 'rgba(91,141,239,.45)' : '#E3E9F2',
      },
      silent: true,
    });
    children.push({
      type: 'text',
      style: {
        text: `结构 ${item.structure_label || index + 1}`,
        x: center,
        y: plotBottom + 25,
        textAlign: 'center',
        textVerticalAlign: 'middle',
        fill: hover ? '#3F68B8' : '#5A6A80',
        fontSize: 11,
        fontFamily: 'inherit',
      },
      silent: true,
    });
    // 交互热区（整列，含 chip）
    children.push({
      type: 'rect',
      shape: { x: x1 - 2, y: MARGIN.top, width: stepW + 4, height: plotH + 40 },
      style: { fill: 'transparent' },
      cursor: 'pointer',
    });
    return { type: 'group', children };
  };

  return {
    animation: true,
    // 台阶生长 / 悬停高亮的速度（与 NEB 曲线同一口径，2026-10-15 调快）
    animationDuration: 300,
    animationDurationUpdate: 80,
    animationEasing: 'cubicOut',
    animationDelay: (index: number) => index * 45,
    grid: { ...MARGIN, containLabel: false },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'transparent',
      borderWidth: 0,
      padding: 0,
      extraCssText: 'box-shadow:none;',
      confine: true,
      formatter: (params: { dataIndex?: number }) => {
        const item = structures[params.dataIndex ?? -1];
        return item ? tipHtml(item, relOf(item)) : '';
      },
    },
    xAxis: {
      type: 'category',
      data: structures.map((s) => String(s.structure_label || '')),
      boundaryGap: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
    },
    yAxis: {
      type: 'value',
      min: lo,
      max: hi,
      splitNumber: 4,
      name: 'ΔE (eV)',
      nameTextStyle: { color: '#8A98AC', fontSize: 11, align: 'left' },
      axisLine: { show: true, lineStyle: { color: '#DCE3EC' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#8A98AC',
        fontSize: 10,
        // 0 这档由参考线自己标注（见下面的零线系列），这里不出，避免同一个值标两遍
        formatter: (value: number) => (Math.abs(value) < 1e-9 ? '' : signed(value, 2)),
      },
      splitLine: { lineStyle: { color: '#EDF1F7', type: [3, 5] } },
    },
    series: [
      {
        type: 'custom',
        name: '自由能台阶',
        renderItem: renderItem as never,
        // 数据本身不画，交给 renderItem；保留 value 以便 tooltip/事件拿到 dataIndex
        data: structures.map((s) => [s.structure_label, relOf(s)]),
        encode: { x: 0, y: 1 },
        // ΔE = 0 参考线（与旧图一致：浅灰实线 + 轴线外的 0.00 标注）。
        // 实测 ECharts 6.1 的 custom 系列 **支持** markLine（line/custom/scatter 都正常）；
        // 反过来"用一条被 null 隔开的折线代替"是错的——孤立点 ECharts 不画线，整条会消失。
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: '#C3CEDA', width: 1 },
          data: [
            {
              yAxis: 0,
              // 标注放到**轴线外**（右对齐贴在 y 轴刻度那一列）——放图内会压住曲线与第一个点
              label: {
                show: true,
                formatter: '0.00',
                position: 'start',
                distance: 6,
                color: '#5A6A80',
                fontSize: 10,
                fontWeight: 600,
              },
            },
          ],
        },
        z: 3,
      },
    ],
  };
}

export default function PathStepChart({ structures, onSelect }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const structuresRef = useRef(structures);
  structuresRef.current = structures;
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const option = useMemo(
    () => buildFreeEnergyStepOption(structures, { hovered }),
    [structures, hovered],
  );

  const containerRef = useEcharts(option, [option], (chart) => {
    if (!chart) return;
    // 事件只绑一次（用 ref 取最新数据，避免闭包陈旧）
    chart.on('mouseover', (params: { dataIndex?: number }) => {
      if (typeof params?.dataIndex === 'number') setHovered(params.dataIndex);
    });
    chart.on('mouseout', () => setHovered(null));
    chart.on('click', (params: { dataIndex?: number }) => {
      const index = params?.dataIndex;
      if (typeof index !== 'number') return;
      const item = structuresRef.current[index];
      if (item) selectRef.current(item.task_id);
    });
  });

  useEffect(() => {
    // 结构列表变了（切换路径）就清掉悬停态
    setHovered(null);
  }, [structures]);

  const legendRef = useMemo(() => {
    const { relOf } = freeEnergyReference(structures);
    return structures.find((s) => relOf(s) === 0)?.structure_label ?? '1';
  }, [structures]);

  if (structures.length === 0) {
    return <div className="analysis-chart-empty">路径上暂无中间体数据</div>;
  }

  return (
    <div className="fe-chart-wrap">
      <div className="fe-chart__legend">
        <span className="fe-legend-item">
          <span className="fe-legend-dot" style={{ background: OK_COLOR }} />
          收敛且已矫正
        </span>
        <span className="fe-legend-item">
          <span className="fe-legend-dot" style={{ background: WARN_COLOR }} />
          未收敛 / 未矫正
        </span>
        <span className="fe-legend-item">
          <span className="fe-legend-dot fe-legend-dot--empty" />
          无数据
        </span>
        <span className="fe-legend-ref">相对能以结构 {legendRef} 为参考</span>
      </div>

      <div className="fe-chart__canvas" ref={containerRef} />

      <p className="fe-chart__axis">中间体顺序（ΔE = E − E参考）</p>
    </div>
  );
}
