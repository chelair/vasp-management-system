/**
 * 报告**交互版运行时**（2026-10-15，v0.9.62）：单文件 HTML 导出用的入口。
 *
 * 后端 `report_export.build_html(interactive_js=..., interactive_data=...)` 会把
 * 这个文件（esbuild 打成的 IIFE，含 ECharts）与数据一起内联进 HTML；本文件在页面加载后
 * 扫描 `[data-report-widget]` 宿主 div，按 kind 挂上原生组件：
 *
 *   pdos-chart          → interactive/pdosWidget.ts（勾轨道 / 改范围 / 带中心 / 只看一条）
 *   work-function-chart → interactive/workFunctionWidget.ts（曲线 + 真空能级/E_F 标记 + 数值卡）
 *
 * 数据从 `window.__VASP_REPORT_DATA__`（后端注入：`{pdos: {task_id: view}, work_function: {...}}`）取。
 * **挂点旁边的那张静态 SVG 就是兜底**：这里跑不起来（老浏览器 / 关闭 JS / 打印）时用户照样看图。
 */

import { mountPdosWidget } from './pdosWidget';
import { mountWorkFunctionWidget, type WorkFunctionWidgetData } from './workFunctionWidget';
import { mountStructure3D, type Structure3DPayload } from './structure3dWidget';

interface ReportData {
  pdos?: Record<string, unknown>;
  work_function?: Record<string, unknown>;
  /** 结构 3D（结构优化任务的 POSCAR/CONTCAR CIF），v0.9.72 */
  structure?: Record<string, Structure3DPayload>;
  /** Bader 的 3D 结构 + 逐原子读数 */
  bader?: Record<string, Structure3DPayload>;
}

function reportData(): ReportData {
  const raw = (window as unknown as { __VASP_REPORT_DATA__?: ReportData }).__VASP_REPORT_DATA__;
  return raw && typeof raw === 'object' ? raw : {};
}

/**
 * 挂好后把紧邻的静态图收起来（导出 HTML 里静态图在前、宿主在后）。
 *
 * 只加 class + 内联隐藏，**不删节点**：打印 / PDF 时 CSS 会把 `.report-static-taken-over`
 * 重新显示出来（`.report-widget` 在打印时隐藏），于是 PDF 用静态图兜底、屏幕上用交互图
 * —— 用户口径（2026-10-15）："HTML 只导出可交互的，不可交互的图留给 PDF 兜底"。
 */
function hideStaticFigure(host: HTMLElement): void {
  const prev = host.previousElementSibling;
  if (prev && prev.tagName === 'FIGURE') {
    const figure = prev as HTMLElement;
    figure.classList.add('report-static-taken-over');
    figure.style.display = 'none';
  }
}

function mountOne(host: HTMLElement, data: ReportData): boolean {
  const kind = host.getAttribute('data-report-widget') || '';
  const taskId = host.getAttribute('data-task-id') || '';
  if (!taskId) return false;
  if (kind === 'pdos-chart') {
    const view = data.pdos?.[taskId];
    if (!view) return false;
    try {
      mountPdosWidget(host, view as never);
      hideStaticFigure(host);
      return true;
    } catch {
      return false; // 出问题就留着静态图，别白屏
    }
  }
  if (kind === 'work-function-chart') {
    const summary = data.work_function?.[taskId];
    if (!summary) return false;
    try {
      mountWorkFunctionWidget(host, summary as WorkFunctionWidgetData);
      hideStaticFigure(host);
      return true;
    } catch {
      return false;
    }
  }
  if (kind === 'structure-3d') {
    // 结构优化：任务的结构；Bader：host 上带 data-source="bader"
    const fromBader = host.getAttribute('data-source') === 'bader';
    const payload = (fromBader ? data.bader : data.structure)?.[taskId];
    if (!payload) return false;
    const handle = mountStructure3D(host, payload, { bader: fromBader, height: 420 });
    if (!handle) return false; // 没有 3Dmol / WebGL 失败 → 保留静态三视图 PNG
    // 正文里紧跟其后的三视图 PNG：屏幕隐藏、打印/PDF 显示（导出器只给结构 3D 用）
    if (!fromBader) {
      let node = host.nextElementSibling as HTMLElement | null;
      while (node) {
        const isImages =
          node.classList.contains('img-row') ||
          node.classList.contains('report-img-row') ||
          node.tagName === 'FIGURE';
        if (!isImages) break;
        node.classList.add('report-static-taken-over');
        node.style.display = 'none';
        node = node.nextElementSibling as HTMLElement | null;
      }
    }
    return true;
  }
  return false;
}

/** 页面加载后挂全部交互组件（幂等：已挂过的宿主加 data-mounted 标记） */
export function mountReportWidgets(): number {
  const data = reportData();
  let mounted = 0;
  document.querySelectorAll<HTMLElement>('[data-report-widget]').forEach((host) => {
    if (host.dataset.mounted === '1') return;
    if (mountOne(host, data)) {
      host.dataset.mounted = '1';
      mounted += 1;
    }
  });
  return mounted;
}

declare global {
  interface Window {
    VaspReportInteractive?: { mount: typeof mountReportWidgets };
  }
}

window.VaspReportInteractive = { mount: mountReportWidgets };

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    mountReportWidgets();
  });
} else {
  mountReportWidgets();
}
