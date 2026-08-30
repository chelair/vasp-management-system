import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Checkbox, Radio, Select, Slider } from 'antd';
import { parseCif, computeBonds, ELEMENT_COLORS, Structure3D } from '../../utils/structure3d';
import './structure3d.css';

declare global {
  interface Window {
    $3Dmol: any;
  }
}

type ViewMode = 'side' | 'overlay' | 'poscar' | 'contcar';

interface Props {
  poscarCif: string | null;
  contcarCif: string | null;
}

interface ModelEntry {
  viewer: any;
  model: any;
  structure: Structure3D;
  colorOverride?: string | null;
  opacity?: number | null;
}

/**
 * POSCAR / CONTCAR 3D 结构对比视图（3Dmol.js）。
 * 数据来自后端 vasp2cif 生成的 CIF 文本；功能对齐测试页：
 * 并排/叠加/单侧模式、球棍/空间填充、缩放、自动旋转、a/b/c 视角、
 * 双侧相机同步、点击原子金色高亮联动、空白取消、abc 方向图例、元素配色图例。
 */
export default function Structure3DViewer({ poscarCif, contcarCif }: Props) {
  const poscar = useMemo(() => (poscarCif ? parseCif(poscarCif) : null), [poscarCif]);
  const contcar = useMemo(() => (contcarCif ? parseCif(contcarCif) : null), [contcarCif]);

  const [mode, setMode] = useState<ViewMode>('side');
  const [scale, setScale] = useState(0.35);
  const [ballStick, setBallStick] = useState(true);
  const [spin, setSpin] = useState(false);

  const areaRef = useRef<HTMLDivElement>(null);
  const axisHolderRef = useRef<HTMLDivElement>(null);
  const elemLegendRef = useRef<HTMLDivElement>(null);
  const infoRef = useRef<HTMLDivElement>(null);

  const structuresRef = useRef<{ poscar: Structure3D | null; contcar: Structure3D | null }>({
    poscar,
    contcar,
  });
  structuresRef.current = { poscar, contcar };

  const activeViewersRef = useRef<any[]>([]);
  const modelEntriesRef = useRef<ModelEntry[]>([]);
  const syncPairRef = useRef<any[] | null>(null);
  const syncLastRef = useRef<{ a: string | null; b: string | null }>({ a: null, b: null });
  const activeMainRef = useRef<any>(null);
  const axisViewerRef = useRef<any>(null);
  const lastAxisKeyRef = useRef('');
  const selectedIndexRef = useRef<number | null>(null);
  const lastAtomClickAtRef = useRef(0);
  const labelDivsRef = useRef<Map<any, HTMLDivElement>>(new Map());

  const scaleRef = useRef(scale);
  const ballStickRef = useRef(ballStick);
  const spinRef = useRef(spin);
  const modeRef = useRef(mode);
  scaleRef.current = scale;
  ballStickRef.current = ballStick;
  spinRef.current = spin;
  modeRef.current = mode;

  function setError(msg: string) {
    if (infoRef.current) {
      const err = infoRef.current.querySelector('.s3d-error');
      if (err) err.textContent = msg || '';
    }
  }

  function elementStyle(el: string, s: number, colorOverride?: string | null, opacity?: number | null) {
    const color = colorOverride || ELEMENT_COLORS[el];
    const sphere: any = { scale: s };
    const stick: any = { radius: 0.16 };
    if (color) {
      sphere.color = color;
      stick.color = color;
    }
    if (opacity != null) {
      sphere.opacity = opacity;
      stick.opacity = opacity;
    }
    return { sphere, stick };
  }

  function applyStructureStyle(
    model: any,
    structure: Structure3D,
    s: number,
    colorOverride?: string | null,
    opacity?: number | null,
    ball = true,
  ) {
    for (const el of structure.elements) {
      const style = elementStyle(el, s, colorOverride, opacity);
      if (!ball) delete style.stick;
      model.setStyle({ elem: el }, style);
    }
  }

  function freshViewer(container: HTMLDivElement, height: number): any {
    container.innerHTML = '';
    container.style.width = '100%';
    container.style.height = `${height}px`;
    const v = window.$3Dmol.createViewer(container, { backgroundColor: '#f7f9fc' });
    v.setProjection('orthographic');
    v.resize();
    v.render();
    activeViewersRef.current.push(v);
    return v;
  }

  function drawCellBox(viewer: any, structure: Structure3D, color: string) {
    const a = structure.lattice[0];
    const b = structure.lattice[1];
    const c = structure.lattice[2];
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
      [0, 1],
      [0, 2],
      [0, 3],
      [1, 4],
      [1, 5],
      [2, 4],
      [2, 6],
      [3, 5],
      [3, 6],
      [4, 7],
      [5, 7],
      [6, 7],
    ];
    for (const [p, q] of edges) {
      viewer.addLine({
        start: { x: corners[p][0], y: corners[p][1], z: corners[p][2] },
        end: { x: corners[q][0], y: corners[q][1], z: corners[q][2] },
        color,
        linewidth: 1,
      });
    }
  }

  function buildStructureView(
    viewer: any,
    structure: Structure3D,
    cifText: string,
    colorOverride: string | null | undefined,
    opacity: number | null | undefined,
    cellColor: string,
  ) {
    const model = viewer.addModel(cifText, 'cif');
    viewer.setClickable({}, true, (atom: any) => {
      lastAtomClickAtRef.current = Date.now();
      selectAtom(atom && typeof atom.index === 'number' ? atom.index : null);
    });
    const bonds = computeBonds(structure);
    if (bonds.length) {
      const atoms = model.atoms || model.selectedAtoms({});
      for (const [i, j] of bonds) {
        if (!atoms[i].bonds) atoms[i].bonds = [];
        if (!atoms[j].bonds) atoms[j].bonds = [];
        if (atoms[i].bonds.indexOf(j) === -1) atoms[i].bonds.push(j);
        if (atoms[j].bonds.indexOf(i) === -1) atoms[j].bonds.push(i);
      }
    }
    applyStructureStyle(model, structure, scaleRef.current, colorOverride, opacity, ballStickRef.current);
    drawCellBox(viewer, structure, cellColor);
    modelEntriesRef.current.push({
      viewer,
      model,
      structure,
      colorOverride: colorOverride ?? null,
      opacity: opacity ?? null,
    });
    return model;
  }

  function highlightSelected(model: any, index: number | null) {
    if (index == null || index < 0) return;
    model.setStyle(
      { index },
      {
        sphere: { scale: scaleRef.current, color: '#ffd700' },
        stick: { radius: 0.16, color: '#ffd700' },
      },
    );
  }

  function selectAtom(index: number | null) {
    selectedIndexRef.current = index;
    for (const e of modelEntriesRef.current) {
      applyStructureStyle(
        e.model,
        e.structure,
        scaleRef.current,
        e.colorOverride,
        e.opacity,
        ballStickRef.current,
      );
      highlightSelected(e.model, selectedIndexRef.current);
      // 标签用 2D 覆盖层：由 rAF 循环按投影实时钉在原子屏幕位置，避免精灵随视角漂移
      const div = getLabelDiv(e.viewer);
      if (div) {
        const idx = selectedIndexRef.current;
        const at = idx != null && idx >= 0 ? e.structure.atoms[idx] : undefined;
        if (at) {
          div.textContent = `${at.element} #${(idx as number) + 1}`;
          div.style.display = 'block';
        } else {
          div.style.display = 'none';
        }
      }
      e.viewer.render();
    }
    updateInfo();
  }

  function getLabelDiv(viewer: any): HTMLDivElement | null {
    const cached = labelDivsRef.current.get(viewer);
    if (cached) return cached;
    const container = viewer.container as HTMLElement | undefined;
    if (!container) return null;
    let div = container.querySelector('.s3d-select-label') as HTMLDivElement | null;
    if (!div) {
      div = document.createElement('div');
      div.className = 's3d-select-label';
      container.appendChild(div);
    }
    labelDivsRef.current.set(viewer, div);
    return div;
  }

  /** 模型坐标 → 画布 CSS 像素（正交投影，供 2D 标签定位） */
  function atomToScreen(
    viewer: any,
    x: number,
    y: number,
    z: number,
  ): { x: number; y: number } | null {
    try {
      viewer.rotationGroup.updateMatrixWorld(true);
      const me = viewer.modelGroup.matrixWorld.elements;
      const wx = me[0] * x + me[4] * y + me[8] * z + me[12];
      const wy = me[1] * x + me[5] * y + me[9] * z + me[13];
      const wz = me[2] * x + me[6] * y + me[10] * z + me[14];
      const cam = viewer.camera;
      cam.updateMatrixWorld(true);
      // 这版 3Dmol 数学库无 Matrix4.invert，直接用渲染器维护的 matrixWorldInverse
      const inv = cam.matrixWorldInverse || cam.matrixWorld;
      const ve = inv.elements;
      const vx = ve[0] * wx + ve[4] * wy + ve[8] * wz + ve[12];
      const vy = ve[1] * wx + ve[5] * wy + ve[9] * wz + ve[13];
      const vz = ve[2] * wx + ve[6] * wy + ve[10] * wz + ve[14];
      const pe = cam.projectionMatrix.elements;
      const cx = pe[0] * vx + pe[4] * vy + pe[8] * vz + pe[12];
      const cy = pe[1] * vx + pe[5] * vy + pe[9] * vz + pe[13];
      const cw = pe[3] * vx + pe[7] * vy + pe[11] * vz + pe[15];
      if (!cw) return null;
      const canvas = viewer.container.querySelector('canvas');
      if (!canvas) return null;
      const w = canvas.clientWidth || canvas.width;
      const h = canvas.clientHeight || canvas.height;
      return { x: ((cx / cw + 1) / 2) * w, y: ((1 - cy / cw) / 2) * h };
    } catch (err) {
      return null;
    }
  }

  function updateSelectionLabels() {
    const idx = selectedIndexRef.current;
    const handled = new Set<any>();
    for (const e of modelEntriesRef.current) {
      if (handled.has(e.viewer)) continue;
      handled.add(e.viewer);
      const div = getLabelDiv(e.viewer);
      if (!div) continue;
      if (idx == null || idx < 0 || !e.structure.atoms[idx]) {
        div.style.display = 'none';
        continue;
      }
      const at = e.structure.atoms[idx];
      const pos = atomToScreen(e.viewer, at.x, at.y, at.z);
      div.style.display = pos ? 'block' : 'none';
      if (pos) {
        div.style.left = `${pos.x}px`;
        div.style.top = `${pos.y}px`;
      }
    }
  }

  function applyScale() {
    for (const e of modelEntriesRef.current) {
      applyStructureStyle(
        e.model,
        e.structure,
        scaleRef.current,
        e.colorOverride,
        e.opacity,
        ballStickRef.current,
      );
      highlightSelected(e.model, selectedIndexRef.current);
      e.viewer.render();
    }
  }

  function applyStyleMode() {
    applyScale();
  }

  function toggleSpin() {
    for (const v of activeViewersRef.current) {
      if (spinRef.current) v.spin('y', 1.2);
      else v.spin(false);
    }
  }

  function quaternionFromMatrix(elements: number[]) {
    const m00 = elements[0];
    const m01 = elements[1];
    const m02 = elements[2];
    const m10 = elements[4];
    const m11 = elements[5];
    const m12 = elements[6];
    const m20 = elements[8];
    const m21 = elements[9];
    const m22 = elements[10];
    const trace = m00 + m11 + m22;
    let x: number;
    let y: number;
    let z: number;
    let w: number;
    let s: number;
    if (trace > 0) {
      s = 0.5 / Math.sqrt(trace + 1);
      w = 0.25 / s;
      x = (m21 - m12) * s;
      y = (m02 - m20) * s;
      z = (m10 - m01) * s;
    } else if (m00 > m11 && m00 > m22) {
      s = 2 * Math.sqrt(1 + m00 - m11 - m22);
      w = (m21 - m12) / s;
      x = 0.25 * s;
      y = (m01 + m10) / s;
      z = (m02 + m20) / s;
    } else if (m11 > m22) {
      s = 2 * Math.sqrt(1 + m11 - m00 - m22);
      w = (m02 - m20) / s;
      x = (m01 + m10) / s;
      y = 0.25 * s;
      z = (m12 + m21) / s;
    } else {
      s = 2 * Math.sqrt(1 + m22 - m00 - m11);
      w = (m10 - m01) / s;
      x = (m02 + m20) / s;
      y = (m12 + m21) / s;
      z = 0.25 * s;
    }
    return { x, y, z, w };
  }

  function viewAlongAxis(axisIndex: number) {
    const structure = structuresRef.current.poscar || structuresRef.current.contcar;
    const viewer = activeMainRef.current;
    if (!structure || !viewer) return;
    const v = structure.lattice[axisIndex];
    const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    const z = [v[0] / len, v[1] / len, v[2] / len];
    const upVec = axisIndex === 2 ? structure.lattice[0] : structure.lattice[2];
    const dot = z[0] * upVec[0] + z[1] * upVec[1] + z[2] * upVec[2];
    const upRaw = [upVec[0] - dot * z[0], upVec[1] - dot * z[1], upVec[2] - dot * z[2]];
    const ulen = Math.sqrt(upRaw[0] * upRaw[0] + upRaw[1] * upRaw[1] + upRaw[2] * upRaw[2]) || 1;
    const up = [upRaw[0] / ulen, upRaw[1] / ulen, upRaw[2] / ulen];
    const x = [
      up[1] * z[2] - up[2] * z[1],
      up[2] * z[0] - up[0] * z[2],
      up[0] * z[1] - up[1] * z[0],
    ];
    const q = quaternionFromMatrix([
      x[0], x[1], x[2], 0,
      up[0], up[1], up[2], 0,
      z[0], z[1], z[2], 0,
      0, 0, 0, 1,
    ]);
    const qobj = viewer.rotationGroup.quaternion;
    qobj.x = q.x;
    qobj.y = q.y;
    qobj.z = q.z;
    qobj.w = q.w;
    viewer.render();
  }

  function cameraKey(v: any): string {
    return v
      .getView()
      .map((n: number) => n.toFixed(5))
      .join(',');
  }

  function syncAxisCamera() {
    const axis = axisViewerRef.current;
    const main = activeMainRef.current;
    if (!axis || !main) return;
    const q = main.rotationGroup.quaternion;
    const key = [q.x, q.y, q.z, q.w].map((n) => n.toFixed(4)).join(',');
    if (key === lastAxisKeyRef.current) return;
    lastAxisKeyRef.current = key;
    axis.rotationGroup.quaternion.copy(q);
    axis.render();
  }

  function updateAxisLegend() {
    const holder = axisHolderRef.current;
    if (!holder) return;
    holder.innerHTML = '';
    axisViewerRef.current = window.$3Dmol.createViewer(holder, { backgroundColor: '0x000000' });
    const axis = axisViewerRef.current;
    axis.setBackgroundColor('0x000000', 0);
    axis.setProjection('orthographic');
    axis.resize();
    const structure = structuresRef.current.poscar || structuresRef.current.contcar;
    if (!structure) return;
    const L = 4;
    const axes = [
      { vec: structure.lattice[0], label: 'a', color: '#c0392b' },
      { vec: structure.lattice[1], label: 'b', color: '#1e8449' },
      { vec: structure.lattice[2], label: 'c', color: '#2471a3' },
    ];
    for (const ax of axes) {
      const v = ax.vec;
      const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
      const end = { x: (v[0] / len) * L, y: (v[1] / len) * L, z: (v[2] / len) * L };
      axis.addArrow({
        start: { x: 0, y: 0, z: 0 },
        end,
        color: ax.color,
        radius: 0.16,
        radiusRatio: 2.4,
        mid: 0.86,
      });
      axis.addLabel(ax.label, {
        position: {
          x: end.x + (v[0] / len) * 0.6,
          y: end.y + (v[1] / len) * 0.6,
          z: end.z + (v[2] / len) * 0.6,
        },
        fontColor: ax.color,
        showBackground: false,
        fontSize: 16,
        alignment: 'center',
        inFront: true,
      });
    }
    axis.zoomTo({}, 0);
    axis.render();
  }

  function updateElemLegend() {
    const el = elemLegendRef.current;
    if (!el) return;
    const els: string[] = [];
    for (const s of [structuresRef.current.poscar, structuresRef.current.contcar]) {
      if (!s) continue;
      for (const e of s.elements) {
        if (!els.includes(e)) els.push(e);
      }
    }
    el.innerHTML = els
      .map(
        (e) =>
          `<div class="s3d-legend-item"><span class="s3d-legend-swatch" style="background:${ELEMENT_COLORS[e] || '#cccccc'}"></span>${e}</div>`,
      )
      .join('');
  }

  function updateInfo() {
    const el = infoRef.current;
    if (!el) return;
    const idx = selectedIndexRef.current;
    const st = structuresRef.current.poscar;
    let text = '';
    if (idx != null && st && st.atoms[idx]) {
      const at = st.atoms[idx];
      text = `选中：${at.element} #${idx + 1} · 坐标 (${at.x.toFixed(3)}, ${at.y.toFixed(3)}, ${at.z.toFixed(3)}) Å · 另一侧已同步高亮`;
    }
    const line = el.querySelector('.s3d-info-line');
    if (line) line.textContent = text;
  }

  function renderViewers() {
    const area = areaRef.current;
    if (!area || !window.$3Dmol) return;
    const m = modeRef.current;
    setError('');
    activeViewersRef.current = [];
    modelEntriesRef.current = [];
    labelDivsRef.current.clear();
    selectedIndexRef.current = null;
    syncPairRef.current = null;
    syncLastRef.current = { a: null, b: null };
    lastAxisKeyRef.current = '';
    area.innerHTML = '';
    const mk = (cap: string): HTMLDivElement => {
      const box = document.createElement('div');
      box.className = 's3d-viewer-box';
      const capEl = document.createElement('div');
      capEl.className = 's3d-viewer-cap';
      capEl.textContent = cap;
      const el = document.createElement('div');
      el.className = 's3d-viewer';
      box.appendChild(capEl);
      box.appendChild(el);
      area.appendChild(box);
      return el;
    };
    const st = structuresRef.current;
    if (m === 'side') {
      area.classList.remove('s3d-overlay');
      const elP = mk('POSCAR（优化前）');
      const elC = mk('CONTCAR（优化后）');
      const vp = freshViewer(elP, 460);
      if (st.poscar && poscarCif) {
        buildStructureView(vp, st.poscar, poscarCif, null, null, '#8899aa');
      }
      vp.zoomTo({}, 0);
      vp.render();
      vp.zoom(2, 0);
      if (spinRef.current) vp.spin('y', 1.2);
      const vc = freshViewer(elC, 460);
      if (st.contcar && contcarCif) {
        buildStructureView(vc, st.contcar, contcarCif, null, null, '#c0392b');
      }
      vc.zoomTo({}, 0);
      vc.render();
      vc.zoom(2, 0);
      if (spinRef.current) vc.spin('y', 1.2);
      activeMainRef.current = vp;
      syncPairRef.current = [vp, vc];
      syncLastRef.current = { a: cameraKey(vp), b: cameraKey(vc) };
    } else {
      area.classList.add('s3d-overlay');
      const cap =
        m === 'overlay'
          ? 'POSCAR（灰色半透明） + CONTCAR（元素彩色）'
          : m === 'poscar'
            ? 'POSCAR（优化前）'
            : 'CONTCAR（优化后）';
      const el = mk(cap);
      const v = freshViewer(el, 500);
      if (m !== 'contcar' && st.poscar) {
        if (poscarCif) buildStructureView(v, st.poscar, poscarCif, '#9aa0a6', 0.45, '#8899aa');
      }
      if (m !== 'poscar' && st.contcar) {
        if (contcarCif) buildStructureView(v, st.contcar, contcarCif, null, null, '#c0392b');
      }
      v.zoomTo({}, 0);
      v.render();
      v.zoom(2, 0);
      if (spinRef.current) v.spin('y', 1.2);
      activeMainRef.current = v;
    }
    updateInfo();
    updateAxisLegend();
    updateElemLegend();
  }

  // 挂载一次：rAF 相机同步循环 + 空白点击取消 + 窗口 resize
  useEffect(() => {
    let raf = 0;
    let lastSyncAt = 0;
    const tick = (ts: number) => {
      if (ts - lastSyncAt > 30) {
        lastSyncAt = ts;
        const pair = syncPairRef.current;
        if (pair) {
          const a = pair[0];
          const b = pair[1];
          const ka = cameraKey(a);
          const kb = cameraKey(b);
          if (ka !== syncLastRef.current.a || kb !== syncLastRef.current.b) {
            if (ka === syncLastRef.current.a) {
              a.setView(b.getView());
              a.render();
            } else {
              b.setView(a.getView());
              b.render();
            }
            const shared = cameraKey(a);
            syncLastRef.current = { a: shared, b: shared };
          }
        }
        syncAxisCamera();
        updateSelectionLabels();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    const area = areaRef.current;
    let downPos: { x: number; y: number } | null = null;
    const onDown = (e: MouseEvent) => {
      downPos = { x: e.clientX, y: e.clientY };
    };
    const onClick = (e: MouseEvent) => {
      if (!downPos) return;
      const moved = Math.abs(e.clientX - downPos.x) > 5 || Math.abs(e.clientY - downPos.y) > 5;
      if (moved) return;
      if (Date.now() - lastAtomClickAtRef.current > 400) {
        selectAtom(null);
      }
    };
    if (area) {
      area.addEventListener('mousedown', onDown);
      area.addEventListener('click', onClick);
    }
    const onResize = () => {
      for (const v of activeViewersRef.current) {
        try {
          v.resize();
          v.render();
        } catch (err) {
          /* ignore */
        }
      }
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(raf);
      if (area) {
        area.removeEventListener('mousedown', onDown);
        area.removeEventListener('click', onClick);
      }
      window.removeEventListener('resize', onResize);
    };
  }, []);

  // 模式 / 结构数据变化时重建视图
  useEffect(() => {
    renderViewers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, poscar, contcar]);

  return (
    <div className="s3d">
      <div className="s3d-toolbar">
        <span className="s3d-label">对比</span>
        <Select
          size="small"
          value={mode}
          onChange={(v) => setMode(v as ViewMode)}
          style={{ width: 130 }}
          options={[
            { value: 'side', label: '并排对比' },
            { value: 'overlay', label: '叠加对比' },
            { value: 'poscar', label: '仅 POSCAR' },
            { value: 'contcar', label: '仅 CONTCAR' },
          ]}
        />
        <span className="s3d-label">球体大小</span>
        <Slider
          min={0.2}
          max={1.5}
          step={0.05}
          value={scale}
          onChange={(v) => {
            setScale(v);
            scaleRef.current = v;
            applyScale();
          }}
          style={{ width: 140 }}
        />
        <Radio.Group
          size="small"
          value={ballStick ? 'ball' : 'spacefill'}
          onChange={(e) => {
            setBallStick(e.target.value === 'ball');
            ballStickRef.current = e.target.value === 'ball';
            applyStyleMode();
          }}
        >
          <Radio.Button value="ball">球棍</Radio.Button>
          <Radio.Button value="spacefill">空间填充</Radio.Button>
        </Radio.Group>
        <Checkbox
          checked={spin}
          onChange={(e) => {
            setSpin(e.target.checked);
            spinRef.current = e.target.checked;
            toggleSpin();
          }}
        >
          自动旋转
        </Checkbox>
        <span className="s3d-label">视角</span>
        <Button size="small" onClick={() => viewAlongAxis(0)}>
          a 轴
        </Button>
        <Button size="small" onClick={() => viewAlongAxis(1)}>
          b 轴
        </Button>
        <Button size="small" onClick={() => viewAlongAxis(2)}>
          c 轴
        </Button>
      </div>
      <div className="s3d-stage">
        <div ref={areaRef} className="s3d-viewer-area" />
        <div className="s3d-axis-legend">
          <div ref={axisHolderRef} className="s3d-axis-holder" />
        </div>
        <div ref={elemLegendRef} className="s3d-elem-legend" />
      </div>
      <div ref={infoRef} className="s3d-info">
        <span className="s3d-info-line" />
        <span className="s3d-error" />
      </div>
    </div>
  );
}
