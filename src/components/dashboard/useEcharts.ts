import { useCallback, useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, CustomChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';

// 按需注册，避免整包引入 echarts（体积：整包 ~1MB，按需约 1/3）
echarts.use([
  PieChart,
  LineChart,
  BarChart,
  ScatterChart,
  // 自定义系列：自由能「台阶图」用它一次画出面积/台阶边/数值/结构编号（v0.9.62）
  CustomChart,
  GridComponent,
  TooltipComponent,
  // 十字准线（tooltip.axisPointer.type='cross'，PDOS 折线要用）
  AxisPointerComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

/**
 * ECharts 挂载 Hook：返回容器 ref，自动 init / setOption / 尺寸自适应 / dispose。
 * `option` 变化时按 `deps` 重新渲染（默认每次渲染都 setOption）。
 *
 * ⚠️ 用**回调 ref** 而不是 `useRef` + 空依赖的 init effect（v0.9.34 修）：
 * 容器 div 常常是"有数据才渲染"（骨架屏 → 图表），而挂载时机早于容器出现，
 * 旧写法 `if (!el) return;` 之后**再也不会初始化** —— 表现为图表（例如核数圆环）
 * 一直空白。回调 ref 在容器真正挂载/卸载时被调用，天然覆盖这种时序。
 */
export default function useEcharts(
  option: EChartsCoreOption,
  deps: unknown[] = [],
  /** 图表实例就绪/销毁回调（导出图片时要用实例，如 PDOS 弹窗的 getDataURL） */
  onReady?: (chart: echarts.ECharts | null) => void,
) {
  const chartRef = useRef<echarts.ECharts | null>(null);
  const optionRef = useRef<EChartsCoreOption>(option);
  optionRef.current = option;
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const teardownRef = useRef<(() => void) | null>(null);

  const containerRef = useCallback((el: HTMLDivElement | null) => {
    // 容器被卸载或替换：先销毁上一次的实例
    teardownRef.current?.();
    teardownRef.current = null;
    if (!el) {
      chartRef.current = null;
      readyRef.current?.(null);
      return;
    }
    const chart = echarts.init(el);
    chartRef.current = chart;
    readyRef.current?.(chart);
    // 初始化时立刻用"当前最新"的 option 渲染一次（之后交给 deps 更新）
    chart.setOption(optionRef.current, true);
    const resize = () => chart.resize();
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(resize);
      observer.observe(el);
    }
    window.addEventListener('resize', resize);
    teardownRef.current = () => {
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}

/** 总览图表统一配色（与设计令牌一致） */
export const DASHBOARD_PALETTE = [
  '#5B8DEF',
  '#67C6B0',
  '#F5A65B',
  '#A78BFA',
  '#4FC3F7',
  '#F2748A',
  '#8BC34A',
  '#FFB74D',
];
