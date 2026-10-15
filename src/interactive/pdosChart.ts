/**
 * PDOS 图表**计算内核**（框架无关，2026-10-15）。
 *
 * 同一张 PDOS 图要在三处出现：
 *   1. 巡检详情「电子结构分析 → PDOS」—— React + AntD 控件；
 *   2. 报告页「重点科学结果分析」—— 原生 DOM（portal 挂载）；
 *   3. 导出的单文件 HTML —— 原生 DOM，**没有 React**。
 *
 * 后两处共用 `interactive/pdosWidget.ts`（原生控件）；本模块是它们共同的内核：
 * 输入「数据 + 界面状态」，输出 ECharts option 以及图例/带中心等派生量。
 * 巡检详情只复用本模块算 option/图例，控件仍是 AntD —— 于是三处的
 * 曲线口径、范围裁剪、带中心算法**只有一份实现**，不会漂移。
 *
 * 口径（与后端 `build_view` 一致）：能量一律**相对费米能级**；自旋 down 在镜像布局下取负。
 */

import type { EChartsCoreOption } from 'echarts/core';

import type { PdosTreeNode, PdosView } from '../types';
import { bandCenters, formatCenter } from '../utils/bandCenter';
import type { ExportTable } from './exportData';

export type PdosSpin = 'up' | 'down' | 'total';

/** 图表状态：对应界面上的控件（轨道勾选 / 镜像 / 零线 / 带中心 / 范围 / 只看一条） */
export interface PdosChartState {
  /** 菜单里勾选的节点 key（`total` / `el:Fe:d` / `el:Fe:d:dxy` …） */
  checkedKeys: string[];
  /** 镜像布局：自旋 down 取负画在下方（非自旋时无意义） */
  mirror: boolean;
  /** 画 E_F（x=0）竖直虚线 */
  showZero: boolean;
  /** 画带中心虚线 + 数值 */
  showCenter: boolean;
  /** 横轴范围自适应（跟当前显示曲线走） */
  autoRange: boolean;
  xMin: number;
  xMax: number;
  /** 「只看这条曲线」（曲线 id）；null = 全部显示 */
  isolated: string | null;
}

/** 一条可见曲线（由菜单勾选项展开而来） */
export interface PdosCurveEntry {
  id: string;
  /** 曲线所属的菜单节点 key（点图例芯片的 × = 取消勾选它） */
  nodeKey: string;
  name: string;
  spin: PdosSpin;
  color: string;
  level: 1 | 2 | 3;
  grid: 'total' | 'partial';
  values: number[];
  dashed: boolean;
}

/** 带中心虚线（`row` = 标签错行号，两条挨太近时上下错开） */
export interface PdosCenterLine {
  curve: PdosCurveEntry;
  value: number;
  row: number;
}

export interface PdosChartModel {
  curves: PdosCurveEntry[];
  /** 曲线 id → 带中心（相对 E_F，含未占据态）；算不出为 null */
  centers: Record<string, number | null>;
  centerLines: PdosCenterLine[];
  range: { min: number; max: number };
  /** ECharts option（`setOption(option, true)` 直接可用） */
  option: EChartsCoreOption;
  /** 该算例有没有投影态密度（没有的话菜单里只有总态密度） */
  hasProjection: boolean;
}

const LEVEL_WIDTH: Record<number, number> = { 1: 3, 2: 1.8, 3: 1.2 };
const SPIN_LABEL: Record<string, string> = { up: '↑', down: '↓', total: '' };

/** 默认状态：非自旋算例不镜像、默认只看总态密度 */
export function defaultPdosState(spin: boolean): PdosChartState {
  return {
    checkedKeys: ['total'],
    mirror: spin,
    showZero: true,
    showCenter: false,
    autoRange: false,
    xMin: -10,
    xMax: 10,
    isolated: null,
  };
}

/** 该算例是不是自旋极化 */
export function pdosSpin(view: PdosView | null | undefined): boolean {
  return Boolean(view?.meta?.spin_polarized);
}

/**
 * 统一的 x 轴：**所有曲线都用「总态密度」那条能量网格**。
 *
 * 为什么：总态密度的能量来自 DOSCAR，投影态密度来自 VASPKIT 的 PDOS_*.dat（脚本已把
 * `E−Efermi` 加回来），两边四舍五入后能差 ~1e-3 eV —— ECharts 的 axis tooltip 按 x
 * **精确匹配**取点，差这一点就会出现"某些点只有部分曲线显示"（2026-10-13 用户反馈）。
 * 投影网格 = 总网格去掉 EMIN 首行，所以这里按"起点偏移"对齐（容差 2e-3，默认 1）。
 */
export function partialOffsetOf(view: PdosView | null | undefined): number {
  const total = view?.energy?.total ?? [];
  const partial = view?.energy?.partial ?? [];
  if (!total.length || !partial.length) return 0;
  const target = partial[0];
  const index = total.findIndex((x) => Math.abs(x - target) < 0.002);
  return index >= 0 ? index : 1;
}

/** 曲线第 i 个点落在哪个 x（绝对能量，未减 E_F） */
export function makeXAt(view: PdosView | null | undefined, offset: number) {
  return (curve: PdosCurveEntry, index: number): number => {
    const total = view?.energy?.total ?? [];
    const own = view?.energy?.[curve.grid] ?? [];
    if (curve.grid === 'partial') {
      return total[index + offset] ?? own[index] ?? index;
    }
    return total[index] ?? own[index] ?? index;
  };
}

/** 菜单节点是不是"元素"那一行（`el:Fe`；`el:Fe:d` 是轨道，不算） */
function isElementNode(node: PdosTreeNode): boolean {
  return node.key.startsWith('el:') && !node.key.slice(3).includes(':');
}

/** 勾选项 → 要画的曲线（父节点勾选后其自身曲线也被选中） */
export function flattenCurves(
  view: PdosView | null | undefined,
  checkedKeys: string[],
  spin: boolean,
): PdosCurveEntry[] {
  if (!view) return [];
  const picked = new Set(checkedKeys);
  const out: PdosCurveEntry[] = [];
  const walk = (node: PdosTreeNode, elementLabel = '') => {
    const element = isElementNode(node) ? node.label : elementLabel;
    if (picked.has(node.key)) {
      for (const curve of node.curves ?? []) {
        const seriesRef = view.series?.[curve.id];
        if (!seriesRef) continue;
        // 图例/提示里带上元素，例如 `Al p`（方向投影用方向名：`Fe dxy`）
        const head = element && !isElementNode(node) ? `${element} ${node.label}` : node.label;
        out.push({
          id: curve.id,
          nodeKey: node.key,
          name: `${head}${spin ? ` ${SPIN_LABEL[curve.spin] ?? ''}` : ''}`,
          spin: curve.spin,
          color: curve.color || '#5B8DEF',
          level: node.level,
          grid: seriesRef.grid,
          values: seriesRef.values,
          dashed: curve.spin === 'down',
        });
      }
    }
    (node.children ?? []).forEach((child) => walk(child, element));
  };
  (view.tree ?? []).forEach((node) => walk(node));
  return out;
}

/** 菜单树拍平成有序列表（原生控件按 level 缩进渲染，AntD 树用自己的结构） */
export function flatMenuNodes(
  view: PdosView | null | undefined,
): { key: string; label: string; level: 1 | 2 | 3; color?: string; checkable: boolean }[] {
  const out: { key: string; label: string; level: 1 | 2 | 3; color?: string; checkable: boolean }[] = [];
  const walk = (node: PdosTreeNode) => {
    out.push({
      key: node.key,
      label: node.label,
      level: node.level,
      color: node.color,
      checkable: node.checkable !== false,
    });
    (node.children ?? []).forEach(walk);
  };
  (view?.tree ?? []).forEach(walk);
  return out;
}

/** 当前显示曲线的横轴范围（自适应时按可见曲线算，带 2% 余量） */
export function visibleRange(
  view: PdosView | null | undefined,
  curves: PdosCurveEntry[],
  state: PdosChartState,
  offset: number,
): { min: number; max: number } {
  if (!state.autoRange || curves.length === 0) return { min: state.xMin, max: state.xMax };
  const xAt = makeXAt(view, offset);
  const efermi = view?.meta?.efermi ?? 0;
  let min = Infinity;
  let max = -Infinity;
  curves.forEach((curve) => {
    const n = curve.values.length;
    for (let i = 0; i < n; i += 1) {
      const x = xAt(curve, i) - efermi;
      if (x < min) min = x;
      if (x > max) max = x;
    }
  });
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return { min: state.xMin, max: state.xMax };
  }
  const pad = (max - min) * 0.02;
  return { min: min - pad, max: max + pad };
}

/**
 * 图上画哪几条带中心虚线：显示 ≤4 条时全画（常见的"选一组轨道 = up/down 两条"），
 * 更多时只画「只看这条」选中的那条 —— 否则 40 多条虚线叠在一起没法看。
 * 顺带算**标签错行号**：两条带中心挨得近（< 可视范围的 ~4.5%）时标签上下错开
 * （用户 2026-10-15 反馈：up/down 离得近时数值标签会叠在一起）。
 */
function buildCenterLines(
  curves: PdosCurveEntry[],
  centers: Record<string, number | null>,
  isolated: string | null,
  range: { min: number; max: number },
  showCenter: boolean,
): PdosCenterLine[] {
  if (!showCenter) return [];
  const picked = curves
    .filter((curve) => curves.length <= 4 || curve.id === isolated)
    .map((curve) => ({ curve, value: centers[curve.id] }))
    .filter((item): item is { curve: PdosCurveEntry; value: number } => item.value != null)
    .sort((a, b) => b.value - a.value);
  const span = Math.max(range.max - range.min, 1e-6);
  const rowGap = span * 0.045;
  let row = 0;
  let prev: number | null = null;
  return picked.map((item) => {
    row = prev !== null && Math.abs(item.value - prev) < rowGap ? (row + 1) % 4 : 0;
    prev = item.value;
    return { ...item, row };
  });
}

/**
 * 计算内核：一次算出曲线、带中心、范围与 ECharts option。
 * 纯函数（同样的输入 → 同样的输出），可在任意环境（浏览器 / 测试）里跑。
 */
export function pdosChartModel(
  view: PdosView | null | undefined,
  state: PdosChartState,
): PdosChartModel {
  const spin = pdosSpin(view);
  const meta = view?.meta;
  const curves = flattenCurves(view, state.checkedKeys, spin);
  const offset = partialOffsetOf(view);
  const xAt = makeXAt(view, offset);
  const range = visibleRange(view, curves, state, offset);

  /** 各条曲线的带中心（相对 E_F，含未占据态 —— 用户 2026-10-15 口径） */
  const efermi = meta?.efermi ?? 0;
  const centerItems = curves.map((curve) => {
    const n = curve.values.length;
    const xs = new Array<number>(n);
    for (let i = 0; i < n; i += 1) xs[i] = xAt(curve, i) - efermi;
    return { id: curve.id, xs, values: curve.values };
  });
  const centers = bandCenters(centerItems, range.min, range.max);
  const centerLines = buildCenterLines(curves, centers, state.isolated, range, state.showCenter);

  const option = buildOption(view, curves, centers, centerLines, range, state);
  return {
    curves,
    centers,
    centerLines,
    range,
    option,
    hasProjection: meta?.has_projection !== false,
  };
}

function buildOption(
  view: PdosView | null | undefined,
  curves: PdosCurveEntry[],
  _centers: Record<string, number | null>,
  centerLines: PdosCenterLine[],
  range: { min: number; max: number },
  state: PdosChartState,
): EChartsCoreOption {
  const meta = view?.meta;
  const spin = pdosSpin(view);
  const efermi = meta?.efermi ?? 0;
  const offset = partialOffsetOf(view);
  const xAt = makeXAt(view, offset);
  /** 每条曲线的 x 序列（相对 E_F），tooltip 自己找最近点要用 */
  const xsOf = (curve: PdosCurveEntry) => {
    const n = curve.values.length;
    const xs = new Array<number>(n);
    for (let i = 0; i < n; i += 1) xs[i] = xAt(curve, i) - efermi;
    return xs;
  };
  /** 指针 x 上该曲线最近的点（曲线 x 单调，二分即可） */
  const nearestIndex = (xs: number[], x: number) => {
    if (!xs.length) return -1;
    let lo = 0;
    let hi = xs.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (xs[mid] < x) lo = mid;
      else hi = mid;
    }
    return Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
  };
  // tooltip 仍然列**全部**曲线（隔离只是压暗，不隐藏数据），聚焦的那条排最前
  const tooltipRows = [...curves]
    .sort((a, b) => (a.id === state.isolated ? -1 : b.id === state.isolated ? 1 : 0))
    .map((curve) => ({ curve, xs: xsOf(curve) }));
  /** 参考线该挂哪条曲线（挂聚焦的那条，或第一条） */
  const focusIndex = Math.max(0, curves.findIndex((curve) => curve.id === state.isolated));
  const series = curves.map((curve) => {
    const n = curve.values.length;
    const data: [number, number][] = [];
    let maxAbs = 0;
    for (let i = 0; i < n; i += 1) {
      const value = curve.values[i];
      maxAbs = Math.max(maxAbs, Math.abs(value));
      data.push([
        xAt(curve, i) - efermi,
        state.mirror && curve.spin === 'down' ? -value : value,
      ]);
    }
    const dimmed = state.isolated !== null && curve.id !== state.isolated;
    return {
      name: curve.name,
      type: 'line' as const,
      showSymbol: false,
      sampling: 'lttb' as const,
      // 点图例"只看这条"时，其它曲线**压暗**（保留颜色、降低不透明度）而不是隐藏
      lineStyle: {
        width: LEVEL_WIDTH[curve.level] ?? 1.5,
        type: curve.dashed ? ('dashed' as const) : ('solid' as const),
        opacity: dimmed ? 0.18 : 1,
      },
      itemStyle: { color: curve.color, opacity: dimmed ? 0.18 : 1 },
      z: dimmed ? 1 : 3,
      // 不再用 ECharts 的 focus:'series'（hover 会把其它曲线压暗/隐藏，用户明确不要）；
      // "只看一条"改由点击图例芯片实现（见 state.isolated）
      data,
      // 镜像布局时纵轴上下对称，这里把最大值带出来给 yAxis 用
      __maxAbs: maxAbs,
    };
  });
  const maxAbs = series.reduce((acc, item) => Math.max(acc, item.__maxAbs), 0) || 1;
  const yAxis =
    state.mirror && spin
      ? {
          min: -maxAbs * 1.05,
          max: maxAbs * 1.05,
          axisLabel: { formatter: (v: number) => Math.abs(v).toFixed(0) },
        }
      : { min: undefined, max: undefined };
  return {
    animation: false,
    // 顶部不留图例空间（图例改成工具条上的芯片，避免与轴名重叠）
    // 左边留出竖排 "Intensity" 轴名的位置
    grid: { left: 66, right: 20, top: 18, bottom: 46 },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'cross' as const },
      // 卡片**不能被画布裁掉**（勾选多条曲线时卡片很长，指针在底部时原来会露出画面外，
      // 看起来像"只有部分曲线"）：限制在画布内 + 卡片自己滚动 + 数值多的排前面
      confine: true,
      order: 'valueDesc' as const,
      transitionDuration: 0,
      extraCssText: 'max-height: 260px; overflow: auto; max-width: 340px;',
      // 自定义卡片：**不依赖 ECharts 的"按 x 精确匹配取点"**（实测同一轨道 ↑/↓ 两条
      // 也会因为浮点/网格差异只列出一条）—— 这里拿指针的 x，自己对**每条可见曲线**
      // 找最近点再列出来，所以一定列全；镜像布局下自旋向下显示回绝对值。
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as { axisValue?: number }[];
        const x = list[0]?.axisValue;
        if (x == null) return '';
        const head = `<div style="font-weight:600;margin-bottom:4px">E − E_F = ${Number(x).toFixed(3)} eV</div>`;
        const rows = tooltipRows.map(({ curve, xs }) => {
          const index = nearestIndex(xs, Number(x));
          // 指针落在该曲线能量范围之外（例如投影少了 EMIN 首行）就显示 ——，别硬取端点值
          const inRange = index >= 0 && Math.abs((xs[index] ?? 0) - Number(x)) <= 0.05;
          const raw = inRange ? curve.values[index] : NaN;
          const shown = state.mirror && curve.spin === 'down' ? Math.abs(raw) : raw;
          const dot =
            `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
            `background:${curve.color};margin-right:6px"></span>`;
          return `${dot}${curve.name}: ${Number.isFinite(shown) ? shown.toFixed(4) : '—'}`;
        });
        return head + rows.join('<br/>');
      },
    },
    // 不用 ECharts 自带图例：曲线多时它会和轴名/彼此重叠（用户截图反馈），
    // 改用工具条上的芯片做图例（点一下取消该条曲线）。
    legend: { show: false },
    xAxis: {
      type: 'value' as const,
      name: 'E − E_F (eV)',
      nameLocation: 'middle' as const,
      nameGap: 26,
      min: range.min,
      max: range.max,
      position: 'bottom' as const,
      // 同上：默认会把 x 轴轴线画在 y=0 处（横穿图表中间）；轴线与刻度统一放到底部
      axisLine: { show: true, onZero: false },
      axisTick: { show: true, onZero: false },
      axisLabel: { onZero: false },
    },
    yAxis: {
      type: 'value' as const,
      name: 'Intensity',
      // 轴名竖排在**最左端**（默认 nameLocation='end' 会跑到轴顶端，用户要求放左边）
      nameLocation: 'middle' as const,
      nameRotate: 90,
      nameGap: 42,
      position: 'left' as const,
      // ⚠️ 镜像布局下 y 轴跨正负，默认 `onZero` 会把**轴线画到 x=0 处**（图表正中间，
      // 看起来像"0 eV 处多了一条坐标轴"）—— 关掉 onZero，轴线固定在最左端
      axisLine: { show: true, onZero: false },
      axisTick: { show: true, onZero: false },
      axisLabel: { onZero: false },
      ...yAxis,
    },
    // 参考线只挂第一条曲线上（挂多条会叠着画一堆同样的线）：
    //   · 费米能级：x=0 的竖直虚线（可按底部开关关掉）
    //   · 纵轴 0：一条水平基线（镜像布局的正负分界，固定画）
    //   · 带中心：每条显示曲线的加权平均能量（同色垂直虚线 + 数值标签）
    series: series.map(({ __maxAbs, ...rest }, index) =>
      index === focusIndex
        ? {
            ...rest,
            markLine: {
              silent: true,
              symbol: 'none',
              label: { show: false },
              data: [
                ...(state.showZero
                  ? [
                      {
                        xAxis: 0,
                        lineStyle: { type: 'dashed' as const, color: '#98a6bd' },
                      },
                    ]
                  : []),
                {
                  yAxis: 0,
                  lineStyle: { type: 'solid' as const, color: '#b9c4d4', width: 1 },
                },
                ...centerLines.map(({ curve, value, row }) => ({
                  xAxis: value,
                  lineStyle: {
                    // up / down 除了颜色不同，虚线样式也不同（长虚线 vs 点线）：
                    // 两条带中心挨得近时也能分清哪条是哪个自旋（2026-10-15 用户反馈）
                    type: (curve.spin === 'down' ? [2, 3] : [7, 4]) as number[],
                    color: curve.color,
                    width: 1.2,
                    opacity: 0.95,
                  },
                  label: {
                    show: true,
                    formatter: `${curve.name} 带中心 ${formatCenter(value)} eV`,
                    position: 'insideEndTop' as const,
                    distance: [0, 6 + row * 14],
                    color: curve.color,
                    fontSize: 11,
                  },
                })),
              ],
            },
          }
        : rest,
    ),
  };
}

/**
 * 导出用的数据表（2026-10-15）：把**当前勾选的曲线**摊成"能量 × 各曲线"的宽表。
 *
 * - 第一列是 `E - E_F (eV)`（与图上的横轴同一套网格，用总态密度网格 + 投影偏移对齐）；
 * - 后面每条曲线一列，列名就是图例上的名字（`总态密度 ↑` / `Fe d ↓` …）；
 * - 值是**原始态密度**（自旋向下的曲线也保持正值，不做镜像取负 —— 导出给数据用，
 *   镜像只是显示口径），与 `dos.json` 里的一致；
 * - 行按**能量网格**走：曲线没覆盖到的点写 null（导出时空着 / `NaN`）。
 *
 * 返回 null 表示没有可导出的曲线。
 */
export function buildPdosTable(
  view: PdosView | null | undefined,
  state: PdosChartState,
): ExportTable | null {
  if (!view) return null;
  const curves = flattenCurves(view, state.checkedKeys, pdosSpin(view));
  if (!curves.length) return null;
  const offset = partialOffsetOf(view);
  const efermi = view?.meta?.efermi ?? 0;
  const grid = view.energy?.total ?? [];
  // 每一列：总网格下标 → 该曲线的取值（没覆盖到的点留空）
  const columns = curves.map((curve) => {
    const values = new Array<number | null>(grid.length).fill(null);
    const n = curve.values.length;
    for (let i = 0; i < n; i += 1) {
      const target = curve.grid === 'partial' ? i + offset : i;
      if (target >= 0 && target < values.length) values[target] = curve.values[i];
    }
    return { name: curve.name, values };
  });
  const rows: (number | null)[][] = grid.map((x, index) => [
    x - efermi,
    ...columns.map((column) => column.values[index]),
  ]);
  return {
    header: ['E - E_F (eV)', ...columns.map((column) => column.name)],
    rows,
  };
}
