import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts';
import {
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
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

/**
 * ECharts 挂载 Hook：返回容器 ref，自动 init / setOption / 尺寸自适应 / dispose。
 * `option` 变化时按 `deps` 重新渲染（默认每次渲染都 setOption）。
 */
export default function useEcharts(
  option: EChartsCoreOption,
  deps: unknown[] = [],
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const chart = echarts.init(el);
    chartRef.current = chart;
    const resize = () => chart.resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    window.addEventListener('resize', resize);
    return () => {
      observer.disconnect();
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
