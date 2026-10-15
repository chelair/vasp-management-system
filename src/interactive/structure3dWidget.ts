/**
 * 结构 **3D 视图**（框架无关，2026-10-16）：导出的单文件 HTML 用它。
 *
 * 与站内巡检详情 / 报告页同一套口径（都走 3Dmol + `utils/structure3d`）：
 * VESTA 元素配色、共价半径成键、晶胞框、正交投影；工具栏给主要几个开关
 * （球棍/空间填充、原子缩放、自动旋转、重置视角、初始/优化后切换）。
 * Bader 场景额外**按净电荷 Δq 着色**（红=失电子、蓝=得电子，同 `utils/chargeColor`）。
 *
 * 降级：拿不到 `window.$3Dmol`、或 WebGL 初始化失败 → 返回 null，调用方
 * **保留静态三视图 PNG**（打印 / 老设备就是看那个）。
 */

import { ELEMENT_COLORS, computeBonds, parseCif, type Structure3D } from '../utils/structure3d';
import { buildChargeColors } from '../utils/chargeColor';

interface MolAtom {
  index: number;
  element?: string;
  charge?: number | null;
  zval?: number | null;
  net_charge?: number | null;
}

export interface Structure3DPayload {
  task_name?: string;
  /** 结构优化任务：初始 / 优化后（两个都给时出现切换） */
  poscar_cif?: string | null;
  contcar_cif?: string | null;
  /** Bader：单个结构 + 逐原子读数 */
  cif?: string | null;
  atoms?: MolAtom[];
}

export interface Structure3DHandle {
  dispose(): void;
}

/** 自由能路径的一个中间体 */
export interface FreeEnergyStructure3D {
  structure_label?: string;
  cif?: string | null;
}

/** 3Dmol viewer 的**最小接口**（只列我们用到的；3Dmol 本身没有类型声明） */
interface MolViewer {
  setProjection: (p: string) => void;
  addModel: (text: string, fmt: string) => unknown;
  removeAllModels?: () => void;
  setStyle: (sel: Record<string, unknown>, style: unknown) => void;
  addLine?: (spec: Record<string, unknown>) => void;
  zoomTo: (a?: unknown, b?: number) => void;
  zoom: (f: number, t?: number) => void;
  spin: (axis: string | false, speed?: number) => void;
  render: () => void;
  setView?: (v: unknown) => void;
  clear?: () => void;
  resize?: () => void;
}

const STYLE_ID = 'report-3d-style';
const STYLE = `
.r3d { border: 1px solid #e9eef6; border-radius: 10px; background: #fff; overflow: hidden; }
.r3d__bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 10px;
  border-bottom: 1px solid #eef2f8; background: #fbfdff;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
.r3d__btn { border: 1px solid #d9e1ee; background: #fff; color: #3f68b8; border-radius: 6px;
  padding: 3px 10px; font-size: 12.5px; cursor: pointer; }
.r3d__btn:hover { border-color: #9ab4e4; background: #f7faff; }
.r3d__btn.is-on { border-color: #5B8DEF; background: #eef4ff; color: #2f5bd0; }
.r3d__label { font-size: 12px; color: #8a98ac; }
.r3d__scale { width: 110px; }
.r3d__stage { position: relative; background: #f7f9fc; }
.r3d__canvas { width: 100%; }
.r3d__empty { padding: 24px 16px; text-align: center; color: #8a98ac; font-size: 12.5px; }
.r3d__switch { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px 0; }
.r3d__chip { border: 1px solid #d9e1ee; background: #fff; color: #3f68b8; border-radius: 999px;
  padding: 2px 10px; font-size: 12px; cursor: pointer; }
.r3d__chip.is-on { border-color: #5b8def; background: #eef4ff; color: #2f5bd0; }
mark.chip.is-on, button.chip.is-on { border-color: #5b8def !important; background: #eef4ff !important;
  color: #2f5bd0 !important; }
`;

function ensureStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = STYLE;
  doc.head.appendChild(style);
}

function elementStyle(element: string, scale: number, ball: boolean) {
  const color = ELEMENT_COLORS[element];
  const sphere: Record<string, unknown> = { scale };
  if (color) sphere.color = color;
  if (!ball) return { sphere };
  const stick: Record<string, unknown> = { radius: 0.16 };
  if (color) stick.color = color;
  return { sphere, stick };
}

/** 晶胞框（与站内 Structure3DFrame.drawCellBox 同一套） */
function drawCellBox(viewer: never, structure: Structure3D): void {
  const [a, b, c] = structure.lattice;
  const corners = [
    [0, 0, 0],
    a,
    b,
    c,
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    [a[0] + c[0], a[1] + c[1], a[2] + c[2]],
    [b[0] + c[0], b[1] + c[1], b[2] + c[2]],
    [a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]],
  ];
  const edges = [
    [0, 1], [0, 2], [0, 3], [1, 4], [1, 5], [2, 4], [2, 6], [3, 5], [3, 6], [4, 7], [5, 7], [6, 7],
  ];
  const api = viewer as unknown as {
    addBox?: (spec: { center: { x: number; y: number; z: number }; dimensions: { w: number; h: number; d: number } }) => void;
    addLine?: (spec: Record<string, unknown>) => void;
  };
  edges.forEach(([i, j]) => {
    const from = corners[i];
    const to = corners[j];
    api.addLine?.({
      start: { x: from[0], y: from[1], z: from[2] },
      end: { x: to[0], y: to[1], z: to[2] },
      color: '#c3ceda',
      dashed: false,
    });
  });
}

/**
 * 挂载结构 3D 视图。返回 null = 环境不支持（调用方保留静态图）。
 */
export function mountStructure3D(
  host: HTMLElement,
  data: Structure3DPayload,
  options: { height?: number; bader?: boolean } = {},
): Structure3DHandle | null {
  const doc = host.ownerDocument || document;
  const win = doc.defaultView || window;
  const mol = (win as unknown as { $3Dmol?: unknown }).$3Dmol as
    | { createViewer?: (el: HTMLElement, opts: Record<string, unknown>) => unknown }
    | undefined;
  if (!mol || typeof mol.createViewer !== 'function') return null;

  const poscar = data.poscar_cif || null;
  const contcar = data.contcar_cif || null;
  let current = data.cif || contcar || poscar || null;
  if (!current) return null;

  ensureStyle(doc);
  const root = doc.createElement('div');
  root.className = 'r3d';
  const bar = doc.createElement('div');
  bar.className = 'r3d__bar';
  root.appendChild(bar);
  const stage = doc.createElement('div');
  stage.className = 'r3d__stage';
  const canvas = doc.createElement('div');
  canvas.className = 'r3d__canvas';
  canvas.style.height = `${options.height ?? 420}px`;
  stage.appendChild(canvas);
  root.appendChild(stage);
  host.appendChild(root);

  let viewer: MolViewer | null = null;
  let structure: Structure3D | null = null;
  let model: { setStyle: (sel: Record<string, unknown>, style: unknown) => void } | null = null;
  let ballStick = true;
  let scale = 0.35;
  let spinning = false;
  let savedView: unknown = null;

  const charges = options.bader
    ? buildChargeColors(
        (() => {
          const values: (number | null)[] = [];
          (data.atoms || []).forEach((atom) => {
            values[atom.index - 1] = atom.net_charge ?? null;
          });
          return values;
        })(),
      )
    : { colors: null, scale: null };

  function paint(): void {
    if (!viewer || !model || !structure) return;
    structure.elements.forEach((element) => {
      model!.setStyle({ elem: element }, elementStyle(element, scale, ballStick));
    });
    // Bader：逐原子按净电荷覆盖颜色（必须在元素样式之后）
    if (charges.colors) {
      Object.entries(charges.colors).forEach(([index, color]) => {
        model!.setStyle({ index: Number(index) }, { sphere: { color, scale: scale * 0.9 } });
      });
    }
    viewer.render();
  }

  function load(cif: string): boolean {
    try {
      if (!viewer) {
        const created = mol!.createViewer!(canvas, { backgroundColor: '#f7f9fc' }) as unknown as MolViewer;
        viewer = created;
        created.setProjection('orthographic');
      } else {
        viewer.removeAllModels?.();
      }
      structure = parseCif(cif);
      if (!structure) return false;
      const built = viewer.addModel(cif, 'cif') as unknown as {
        atoms?: { bonds?: number[] }[];
        selectedAtoms?: (sel: Record<string, unknown>) => { bonds?: number[] }[];
      };
      model = built as never;
      const bonds = computeBonds(structure);
      const atoms = built.atoms || built.selectedAtoms?.({}) || [];
      bonds.forEach(([i, j]) => {
        if (!atoms[i] || !atoms[j]) return;
        atoms[i].bonds = atoms[i].bonds || [];
        atoms[j].bonds = atoms[j].bonds || [];
        if (!atoms[i].bonds!.includes(j)) atoms[i].bonds!.push(j);
        if (!atoms[j].bonds!.includes(i)) atoms[j].bonds!.push(i);
      });
      paint();
      drawCellBox(viewer as never, structure);
      if (savedView) {
        try {
          (viewer as unknown as { setView: (v: unknown) => void }).setView(savedView);
        } catch {
          viewer.zoomTo({}, 0);
          viewer.zoom(1.25, 0);
        }
      } else {
        viewer.zoomTo({}, 0);
        viewer.zoom(1.25, 0);
      }
      if (spinning) viewer.spin('y', 1.2);
      viewer.render();
      return true;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[structure3d] 挂载失败：', err);
      return false; // WebGL 不可用等 → 交给调用方保留静态图
    }
  }

  // ---------- 工具栏 ----------
  const buttons: HTMLButtonElement[] = [];
  function addButton(label: string, onClick: () => void, on = false): HTMLButtonElement {
    const btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = `r3d__btn${on ? ' is-on' : ''}`;
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    bar.appendChild(btn);
    buttons.push(btn);
    return btn;
  }

  let modelSwitch: HTMLButtonElement | null = null;
  if (poscar && contcar) {
    const showingContcar = () => current === contcar;
    modelSwitch = addButton('优化后（CONTCAR）', () => {
      if (showingContcar()) return;
      savedView = null;
      current = contcar;
      load(contcar);
      if (modelSwitch) {
        modelSwitch.textContent = '优化后（CONTCAR）';
        modelSwitch.classList.add('is-on');
      }
    }, true);
    addButton('初始（POSCAR）', () => {
      if (!showingContcar()) return;
      savedView = null;
      current = poscar;
      load(poscar);
      if (modelSwitch) {
        modelSwitch.textContent = '优化后（CONTCAR）';
        modelSwitch.classList.remove('is-on');
      }
    });
  }

  let styleBtn: HTMLButtonElement | null = null;
  styleBtn = addButton('球棍模型', () => {
    ballStick = !ballStick;
    if (styleBtn) {
      styleBtn.textContent = ballStick ? '球棍模型' : '空间填充';
      styleBtn.classList.toggle('is-on', ballStick);
    }
    paint();
  }, true);

  const scaleLabel = doc.createElement('span');
  scaleLabel.className = 'r3d__label';
  scaleLabel.textContent = '原子缩放';
  bar.appendChild(scaleLabel);
  const slider = doc.createElement('input');
  slider.type = 'range';
  slider.className = 'r3d__scale';
  slider.min = '0.15';
  slider.max = '0.85';
  slider.step = '0.05';
  slider.value = String(scale);
  slider.addEventListener('input', () => {
    scale = Number(slider.value);
    paint();
  });
  bar.appendChild(slider);

  const spinBtn = addButton('自动旋转', () => {
    spinning = !spinning;
    spinBtn.classList.toggle('is-on', spinning);
    viewer?.spin(spinning ? 'y' : false, spinning ? 1.2 : undefined);
  });
  addButton('重置视角', () => {
    savedView = null;
    viewer?.zoomTo({}, 0);
    viewer?.zoom(1.25, 0);
    viewer?.render();
  });
  const hint = doc.createElement('span');
  hint.className = 'r3d__label';
  hint.textContent = '拖动旋转 · 滚轮缩放';
  bar.appendChild(hint);

  // ---------- 起步 ----------
  if (!load(current)) {
    host.innerHTML = '';
    return null;
  }
  // 切换结构时保留视角
  const originalLoad = load;
  const loadWithSavedView = (cif: string) => {
    savedView = null;
    return originalLoad(cif);
  };
  void loadWithSavedView;

  let observer: ResizeObserver | null = null;
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => {
      try {
        (viewer as unknown as { resize?: () => void })?.resize?.();
        viewer?.render();
      } catch {
        /* 忽略 */
      }
    });
    observer.observe(canvas);
  }

  return {
    dispose: () => {
      observer?.disconnect();
      try {
        viewer?.spin(false);
        viewer?.clear?.();
      } catch {
        /* 忽略 */
      }
      host.innerHTML = '';
    },
  };
}

/**
 * 自由能路径的**中间体 3D 视图**（2026-10-16 用户："自由能的结构还是之前的三视图"）：
 * 一排「结构 N」切换按钮 + 一个 3D 窗口；**表格里的「结构 N」芯片也切换它**
 * （导出的 HTML 里用文档级监听 `[data-fe-3d]` 芯片实现，与站内报告页同一交互）。
 *
 * 返回 null = 环境不支持（无 3Dmol / 没结构），调用方保留静态内容。
 */
export function mountFreeEnergy3D(
  host: HTMLElement,
  structures: FreeEnergyStructure3D[],
  options: { group?: string; height?: number } = {},
): Structure3DHandle | null {
  const doc = host.ownerDocument || document;
  const available = (structures || [])
    .map((item, index) => ({ ...item, index }))
    .filter((item) => Boolean(item.cif));
  if (!available.length) return null;
  const group = options.group || host.getAttribute('data-task-id') || '';
  ensureStyle(doc);

  const root = doc.createElement('div');
  root.className = 'r3d';
  const switcher = doc.createElement('div');
  switcher.className = 'r3d__switch';
  root.appendChild(switcher);
  const stage = doc.createElement('div');
  stage.className = 'r3d__stage';
  const canvas = doc.createElement('div');
  stage.appendChild(canvas);
  root.appendChild(stage);
  host.appendChild(root);

  let current = available[0].index;
  let handle: Structure3DHandle | null = null;
  const buttons = new Map<number, HTMLButtonElement>();

  function paintSwitch(): void {
    buttons.forEach((btn, index) => btn.classList.toggle('is-on', index === current));
    // 不用 CSS.escape（老浏览器/测试环境可能没有）：遍历后按属性值比对
    doc.querySelectorAll<HTMLElement>('[data-fe-3d]').forEach((chip) => {
      if ((chip.getAttribute('data-fe-3d') || '') !== group) return;
      chip.classList.toggle('is-on', Number(chip.dataset.feIndex) === current);
    });
  }

  function show(index: number): void {
    const item = available.find((x) => x.index === index) ?? available[0];
    if (!item || item.index === current) return;
    current = item.index;
    handle?.dispose();
    handle = mountStructure3D(canvas, { cif: item.cif }, { height: options.height ?? 420 });
    paintSwitch();
  }

  available.forEach((item) => {
    const btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'r3d__chip';
    btn.textContent = `结构 ${item.structure_label ?? item.index + 1}`;
    btn.addEventListener('click', () => show(item.index));
    switcher.appendChild(btn);
    buttons.set(item.index, btn);
  });

  handle = mountStructure3D(canvas, { cif: available[0].cif }, { height: options.height ?? 420 });
  if (!handle) {
    // eslint-disable-next-line no-console
    console.warn('[structure3d] 自由能中间体 3D 挂载失败（无 3Dmol / WebGL？），保留原内容');
    host.innerHTML = '';
    return null;
  }
  paintSwitch();

  // 表格里的「结构 N」芯片 → 切换这个 3D（文档级监听；只认本组的芯片）
  const onChip = (event: Event) => {
    const target = event.target as HTMLElement | null;
    const chip = target?.closest?.('[data-fe-3d]') as HTMLElement | null;
    if (!chip || (chip.getAttribute('data-fe-3d') || '') !== group) return;
    const index = Number(chip.dataset.feIndex ?? '');
    if (Number.isFinite(index)) show(index);
  };
  doc.addEventListener('click', onChip);

  return {
    dispose: () => {
      doc.removeEventListener('click', onChip);
      handle?.dispose();
      host.innerHTML = '';
    },
  };
}
