/**
 * PDOS **原生控件组件**（框架无关，2026-10-15）。
 *
 * 用在哪：报告页「重点科学结果分析」与**导出的单文件 HTML** —— 两处的共同点是
 * "只有 DOM，没有 React/AntD"。控件（轨道勾选、镜像、E_F 虚线、带中心、范围、只看一条）
 * 用原生 DOM 写一份，图表计算全部走 `interactive/pdosChart.ts` 内核，
 * 于是导出文件里的交互体验与站内巡检详情**是同一套口径**。
 *
 * 样式随 JS 一起注入（`<style>` 常量）—— 这样单文件导出不必额外内联 CSS，
 * 后端只要把这一个 JS 塞进 HTML 就行。
 */

import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

import type { PdosView } from '../types';
import { formatCenter } from '../utils/bandCenter';
import {
  defaultPdosState,
  flatMenuNodes,
  pdosChartModel,
  pdosSpin,
  type PdosChartState,
} from './pdosChart';

// 按需注册（与巡检详情的 useEcharts 同一套组件；多注册几个组件不会互相影响）
echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  MarkLineComponent,
  TitleComponent,
  LegendComponent,
  CanvasRenderer,
]);

const STYLE_ID = 'pdos-widget-style';
const STYLE = `
.pdosw { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Microsoft YaHei", Helvetica, Arial, sans-serif; color: #233043; font-size: 13px; }
.pdosw__bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 2px 0 6px; }
.pdosw__btn { border: 1px solid #d9e1ee; background: #fff; color: #3f68b8; border-radius: 6px;
  padding: 3px 10px; font-size: 12.5px; cursor: pointer; }
.pdosw__btn:hover { border-color: #9ab4e4; background: #f7faff; }
.pdosw__btn--on { border-color: #5B8DEF; color: #2f5bd0; background: #eef4ff; }
.pdosw__chip { display: inline-flex; align-items: center; gap: 4px; border: 1px solid #e3e9f2;
  background: #fff; border-radius: 999px; padding: 2px 6px 2px 8px; font-size: 12px; }
.pdosw__chip.is-dim { opacity: .55; }
.pdosw__chip.is-picked { border-color: #5B8DEF; background: #eef4ff; }
.pdosw__chip button { border: none; background: transparent; cursor: pointer; font: inherit;
  color: inherit; padding: 0 2px; }
.pdosw__dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.pdosw__center { color: #8a98ac; font-variant-numeric: tabular-nums; }
.pdosw__menu { border: 1px solid #e3e9f2; border-radius: 8px; background: #fbfcfe;
  padding: 8px 10px; margin: 0 0 8px; max-height: 240px; overflow: auto; }
.pdosw__menu.is-hidden { display: none; }
.pdosw__row { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.pdosw__row label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.pdosw__row--l2 { padding-left: 16px; }
.pdosw__row--l3 { padding-left: 32px; }
.pdosw__row.is-group { color: #5a6a80; }
.pdosw__hint { color: #8a98ac; font-size: 11.5px; margin: 6px 0 0; }
.pdosw__canvas { width: 100%; height: 380px; }
.pdosw__foot { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
  margin-top: 6px; color: #5a6a80; font-size: 12.5px; }
.pdosw__foot label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.pdosw__foot input[type="number"] { width: 68px; border: 1px solid #d9e1ee; border-radius: 5px;
  padding: 2px 6px; font: inherit; }
.pdosw__foot input[type="number"]:disabled { background: #f4f7fb; color: #8a98ac; }
.pdosw__meta { color: #8a98ac; }
.pdosw__err { color: #c0392b; }
`;

function ensureStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = STYLE;
  doc.head.appendChild(style);
}

export interface PdosWidgetHandle {
  setState(patch: Partial<PdosChartState>): void;
  getState(): PdosChartState;
  reset(): void;
  exportPng(name?: string): void;
  dispose(): void;
}

/**
 * 挂载 PDOS 交互组件。
 *
 * @param container 宿主元素（组件会往里塞 DOM；调用方负责给宽度）
 * @param view      `GET /api/jobs/tasks/{id}/pdos` 的返回（或导出文件里内联的同一份数据）
 */
export function mountPdosWidget(
  container: HTMLElement,
  view: PdosView,
  initial?: Partial<PdosChartState>,
): PdosWidgetHandle {
  const doc = container.ownerDocument || document;
  ensureStyle(doc);

  const spin = pdosSpin(view);
  let state: PdosChartState = { ...defaultPdosState(spin), ...(initial || {}) };

  container.innerHTML = '';
  const root = doc.createElement('div');
  root.className = 'pdosw';
  container.appendChild(root);

  const bar = doc.createElement('div');
  bar.className = 'pdosw__bar';
  const menuBtn = doc.createElement('button');
  menuBtn.type = 'button';
  menuBtn.className = 'pdosw__btn';
  bar.appendChild(menuBtn);
  const legend = doc.createElement('span');
  legend.className = 'pdosw__bar';
  legend.style.gap = '6px';
  bar.appendChild(legend);
  root.appendChild(bar);

  const menu = doc.createElement('div');
  menu.className = 'pdosw__menu is-hidden';
  const nodes = flatMenuNodes(view);
  nodes.forEach((node) => {
    const row = doc.createElement('div');
    row.className = `pdosw__row pdosw__row--l${node.level}${node.checkable ? '' : ' is-group'}`;
    const label = doc.createElement('label');
    const box = doc.createElement('input');
    box.type = 'checkbox';
    box.checked = state.checkedKeys.includes(node.key);
    if (!node.checkable) {
      // 元素节点只做分组（与巡检详情的 AntD 树、后端 checkable=false 一致）
      box.disabled = true;
    } else {
      box.addEventListener('change', () => {
        const keys = new Set(state.checkedKeys);
        if (box.checked) keys.add(node.key);
        else keys.delete(node.key);
        update({ checkedKeys: [...keys] });
      });
    }
    const dot = doc.createElement('span');
    dot.className = 'pdosw__dot';
    if (node.color) dot.style.background = node.color;
    else dot.style.display = 'none';
    const text = doc.createElement('span');
    text.textContent = node.label;
    label.append(box, dot, text);
    row.appendChild(label);
    row.dataset.key = node.key;
    menu.appendChild(row);
  });
  const menuHint = doc.createElement('p');
  menuHint.className = 'pdosw__hint';
  menuHint.textContent = '勾哪条画哪条：点 p 只画 p，px/py/pz、dxy… 要单独勾（元素那行只是分组，不可勾）';
  menu.appendChild(menuHint);
  root.appendChild(menu);

  menuBtn.addEventListener('click', () => {
    const hidden = menu.classList.toggle('is-hidden');
    menuBtn.classList.toggle('pdosw__btn--on', !hidden);
  });

  const canvas = doc.createElement('div');
  canvas.className = 'pdosw__canvas';
  root.appendChild(canvas);
  const chart = echarts.init(canvas);

  const foot = doc.createElement('div');
  foot.className = 'pdosw__foot';
  root.appendChild(foot);

  const meta = doc.createElement('span');
  meta.className = 'pdosw__meta';
  foot.appendChild(meta);

  /** 自旋算例才有"镜像/叠加"开关（非自旋没有上下之分） */
  let mirrorBox: HTMLInputElement | null = null;
  if (spin) {
    const mirrorLabel = doc.createElement('label');
    mirrorBox = doc.createElement('input');
    mirrorBox.type = 'checkbox';
    mirrorBox.checked = state.mirror;
    mirrorBox.addEventListener('change', () => update({ mirror: mirrorBox!.checked }));
    mirrorLabel.append(mirrorBox, doc.createTextNode('镜像（↑/↓）'));
    foot.appendChild(mirrorLabel);
  }

  const zeroLabel = doc.createElement('label');
  const zeroBox = doc.createElement('input');
  zeroBox.type = 'checkbox';
  zeroBox.checked = state.showZero;
  zeroBox.addEventListener('change', () => update({ showZero: zeroBox.checked }));
  zeroLabel.append(zeroBox, doc.createTextNode('E_F 虚线'));
  foot.appendChild(zeroLabel);

  const centerLabel = doc.createElement('label');
  const centerBox = doc.createElement('input');
  centerBox.type = 'checkbox';
  centerBox.checked = state.showCenter;
  centerBox.title =
    '带中心 = 对当前显示的每条曲线在「范围」内做加权平均能量 ∫E·DOS dE / ∫DOS dE；' +
    '含未占据态（跨过 E_F 也照算），up/down 各自算，数值相对 E_F。';
  centerBox.addEventListener('change', () => update({ showCenter: centerBox.checked }));
  centerLabel.append(centerBox, doc.createTextNode('带中心'));
  foot.appendChild(centerLabel);

  const rangeWrap = doc.createElement('span');
  rangeWrap.className = 'pdosw__bar';
  rangeWrap.style.margin = '0';
  const rangeText = doc.createTextNode('范围 ');
  const minInput = doc.createElement('input');
  minInput.type = 'number';
  minInput.step = '1';
  const tilde = doc.createTextNode(' ~ ');
  const maxInput = doc.createElement('input');
  maxInput.type = 'number';
  maxInput.step = '1';
  minInput.addEventListener('change', () => update({ xMin: Number(minInput.value) }));
  maxInput.addEventListener('change', () => update({ xMax: Number(maxInput.value) }));
  const autoLabel = doc.createElement('label');
  const autoBox = doc.createElement('input');
  autoBox.type = 'checkbox';
  autoBox.checked = state.autoRange;
  autoBox.addEventListener('change', () => update({ autoRange: autoBox.checked }));
  autoLabel.append(autoBox, doc.createTextNode('自适应'));
  rangeWrap.append(rangeText, minInput, tilde, maxInput, autoLabel);
  foot.appendChild(rangeWrap);

  const resetBtn = doc.createElement('button');
  resetBtn.type = 'button';
  resetBtn.className = 'pdosw__btn';
  resetBtn.textContent = '重置';
  resetBtn.addEventListener('click', () => {
    update(defaultPdosState(spin), true);
  });
  foot.appendChild(resetBtn);

  function renderLegend(): void {
    legend.innerHTML = '';
    for (const curve of model.curves) {
      const chip = doc.createElement('span');
      chip.className = `pdosw__chip${
        state.isolated === curve.id ? ' is-picked' : state.isolated ? ' is-dim' : ''
      }`;
      const pick = doc.createElement('button');
      pick.type = 'button';
      pick.title = state.isolated === curve.id ? '再点一下恢复显示全部曲线' : '点一下只看这条曲线';
      const dot = doc.createElement('span');
      dot.className = 'pdosw__dot';
      dot.style.background = curve.color;
      const name = doc.createElement('span');
      name.textContent = curve.name;
      pick.append(dot, name);
      if (state.showCenter) {
        const center = doc.createElement('span');
        center.className = 'pdosw__center';
        center.textContent = `${formatCenter(model.centers[curve.id])} eV`;
        pick.appendChild(center);
      }
      pick.addEventListener('click', () =>
        update({ isolated: state.isolated === curve.id ? null : curve.id }),
      );
      const remove = doc.createElement('button');
      remove.type = 'button';
      remove.title = '取消这条曲线';
      remove.textContent = '×';
      remove.addEventListener('click', () =>
        update({
          checkedKeys: state.checkedKeys.filter((key) => key !== curve.nodeKey),
          isolated: state.isolated === curve.id ? null : state.isolated,
        }),
      );
      chip.append(pick, remove);
      legend.appendChild(chip);
    }
    if (state.isolated) {
      const showAll = doc.createElement('button');
      showAll.type = 'button';
      showAll.className = 'pdosw__btn';
      showAll.textContent = `显示全部（${model.curves.length}）`;
      showAll.addEventListener('click', () => update({ isolated: null }));
      legend.appendChild(showAll);
    }
    if (state.showCenter && model.curves.length) {
      const summary = doc.createElement('span');
      summary.className = 'pdosw__center';
      const values = model.curves
        .map((curve) => `${curve.name} 带中心 ${formatCenter(model.centers[curve.id])} eV`)
        .join('；');
      summary.textContent = `（${values}）`;
      legend.appendChild(summary);
    }
  }

  function renderControls(): void {
    menu.querySelectorAll<HTMLElement>('.pdosw__row').forEach((row) => {
      const key = row.dataset.key || '';
      const box = row.querySelector('input');
      if (box && !box.disabled) box.checked = state.checkedKeys.includes(key);
    });
    menuBtn.textContent = `轨道选择（已选 ${state.checkedKeys.length}）`;
    zeroBox.checked = state.showZero;
    centerBox.checked = state.showCenter;
    autoBox.checked = state.autoRange;
    if (mirrorBox) mirrorBox.checked = state.mirror;
    // 自适应时两个输入框显示"算出来的范围"（与巡检详情一致：disabled + 回显）
    minInput.value = String(round2(model.range.min));
    maxInput.value = String(round2(model.range.max));
    minInput.disabled = state.autoRange;
    maxInput.disabled = state.autoRange;
    const efermi = view.meta?.efermi;
    meta.textContent =
      `费米能级 E_F = ${efermi != null ? `${Number(efermi).toFixed(4)} eV` : '—'}` +
      (spin ? ' · 自旋极化' : ' · 非自旋') +
      (view.meta?.elements?.length ? ` · ${view.meta.elements.join('/')}` : '');
  }

  function round2(value: number): number {
    return Math.round(value * 100) / 100;
  }

  let model = pdosChartModel(view, state);

  function update(patch: Partial<PdosChartState>, force = false): void {
    const next = { ...state, ...patch };
    const changed = force || (Object.keys(patch) as (keyof PdosChartState)[]).some(
      (key) => next[key] !== state[key],
    );
    if (!changed) return;
    state = next;
    model = pdosChartModel(view, state);
    renderLegend();
    renderControls();
    chart.setOption(model.option, true);
  }

  renderLegend();
  renderControls();
  chart.setOption(model.option, true);

  // 容器宽度变化（报告页里宽度随窗口变）→ 重算画布尺寸；导出文件里也不会白屏
  let observer: ResizeObserver | null = null;
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => chart.resize());
    observer.observe(canvas);
  }
  const onResize = () => chart.resize();
  window.addEventListener('resize', onResize);

  return {
    setState: (patch) => update(patch, true),
    getState: () => ({ ...state }),
    reset: () => update(defaultPdosState(spin), true),
    exportPng: (name?: string) => {
      const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
      const link = doc.createElement('a');
      link.href = url;
      link.download = `${name || 'PDOS'}.png`;
      link.click();
    },
    dispose: () => {
      observer?.disconnect();
      window.removeEventListener('resize', onResize);
      chart.dispose();
      container.innerHTML = '';
    },
  };
}
