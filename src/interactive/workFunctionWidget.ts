/**
 * 功函数**原生控件组件**（框架无关，2026-10-15）：导出的单文件 HTML 用它，
 * 报告页那一份是 React 版（`components/reports/ReportScienceWidgets.tsx`），
 * 两者共用同一份数据口径（后端 `work_function_summary`：z / potential / 真空能级 / E_F）。
 *
 * 样式随 JS 注入，导出时无需额外内联 CSS。
 */

import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  TitleComponent,
  CanvasRenderer,
]);

export interface WorkFunctionWidgetData {
  task_id?: string;
  axis?: string;
  axis_cartesian?: string;
  efermi?: number | null;
  vacuum_level?: number | null;
  vacuum_level_source?: string;
  work_function?: number | null;
  warnings?: string[];
  z?: number[];
  potential?: number[];
}

const STYLE_ID = 'wf-widget-style';
const STYLE = `
.wfw { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Microsoft YaHei", Helvetica, Arial, sans-serif; color: #233043; }
.wfw__cards { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }
.wfw__card { display: inline-flex; align-items: baseline; gap: 6px; padding: 4px 10px;
  border: 1px solid #E3E9F2; border-radius: 8px; background: #FBFCFE; font-size: 12.5px;
  color: #5A6A80; }
.wfw__card b { color: #233043; font-variant-numeric: tabular-nums; }
.wfw__card--key { border-color: #B9D0F5; background: #EEF4FF; }
.wfw__card em { font-style: normal; font-size: 11.5px; color: #8A98AC; }
.wfw__chart { width: 100%; height: 300px; }
.wfw__warn { margin: 6px 0 0; padding: 6px 10px; border: 1px solid #F3DFC0; background: #FFF9EE;
  border-radius: 8px; color: #9A6A18; font-size: 12px; }
`;

function ensureStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = STYLE;
  doc.head.appendChild(style);
}

function fixed(value: number | null | undefined, digits: number, fallback = '—'): string {
  return value == null || !Number.isFinite(Number(value))
    ? fallback
    : Number(value).toFixed(digits);
}

/** 挂载功函数图（曲线 + 真空能级 / E_F 标记线 + 数值卡 + 告警） */
export function mountWorkFunctionWidget(
  container: HTMLElement,
  data: WorkFunctionWidgetData,
): { dispose: () => void } {
  const doc = container.ownerDocument || document;
  ensureStyle(doc);
  container.innerHTML = '';
  const root = doc.createElement('div');
  root.className = 'wfw';
  container.appendChild(root);

  const cards = doc.createElement('div');
  cards.className = 'wfw__cards';
  const entries: [string, string, string, boolean?][] = [
    ['真空能级', fixed(data.vacuum_level, 4), data.vacuum_level_source === 'vaspkit' ? 'VASPKIT 汇总' : '本地平台估计'],
    ['E_F', fixed(data.efermi, 4), 'eV'],
    ['功函数', fixed(data.work_function, 4), 'eV', true],
    ['方向', String(data.axis ?? '—'), `↗ ${data.axis_cartesian ?? '—'}`],
  ];
  for (const [label, value, hint, key] of entries) {
    const chip = doc.createElement('span');
    chip.className = `wfw__card${key ? ' wfw__card--key' : ''}`;
    const text = doc.createElement('span');
    text.textContent = `${label} `;
    const strong = doc.createElement('b');
    strong.textContent = value;
    const unit = doc.createElement('em');
    unit.textContent = hint;
    chip.append(text, strong, unit);
    cards.appendChild(chip);
  }
  root.appendChild(cards);

  const canvas = doc.createElement('div');
  canvas.className = 'wfw__chart';
  root.appendChild(canvas);
  const chart = echarts.init(canvas);
  const z = data.z ?? [];
  const potential = data.potential ?? [];
  chart.setOption(
    {
      animation: false,
      grid: { left: 62, right: 92, top: 26, bottom: 42 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
      },
      xAxis: {
        type: 'value',
        name: 'z (Å)',
        nameLocation: 'middle',
        nameGap: 26,
        axisLine: { onZero: false },
        axisLabel: { onZero: false },
      },
      yAxis: {
        type: 'value',
        name: '静电势 (eV)',
        nameLocation: 'middle',
        nameRotate: 90,
        nameGap: 46,
        axisLine: { onZero: false },
        axisLabel: { onZero: false },
      },
      series: [
        {
          name: '平面平均电位',
          type: 'line',
          showSymbol: false,
          sampling: 'lttb',
          lineStyle: { width: 1.6, color: '#5B8DEF' },
          itemStyle: { color: '#5B8DEF' },
          data: z.map((value, index) => [value, potential[index]]),
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: true, position: 'insideEndTop', fontSize: 11 },
            data: [
              ...(data.vacuum_level != null
                ? [
                    {
                      yAxis: data.vacuum_level,
                      lineStyle: { type: 'dashed', color: '#2C9DA8' },
                      label: {
                        formatter: `真空能级 ${Number(data.vacuum_level).toFixed(3)} eV`,
                        color: '#2C9DA8',
                      },
                    },
                  ]
                : []),
              ...(data.efermi != null
                ? [
                    {
                      yAxis: data.efermi,
                      lineStyle: { type: 'dashed', color: '#E8A33D' },
                      label: {
                        formatter: `E_F ${Number(data.efermi).toFixed(3)} eV`,
                        color: '#E8A33D',
                      },
                    },
                  ]
                : []),
            ],
          },
        },
      ],
    },
    true,
  );
  for (const warning of data.warnings ?? []) {
    const box = doc.createElement('p');
    box.className = 'wfw__warn';
    box.textContent = `⚠ ${warning}`;
    root.appendChild(box);
  }
  let observer: ResizeObserver | null = null;
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => chart.resize());
    observer.observe(canvas);
  }
  const onResize = () => chart.resize();
  window.addEventListener('resize', onResize);
  return {
    dispose: () => {
      observer?.disconnect();
      window.removeEventListener('resize', onResize);
      chart.dispose();
      container.innerHTML = '';
    },
  };
}
