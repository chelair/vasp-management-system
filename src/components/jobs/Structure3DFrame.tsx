import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Checkbox, Empty, Segmented, Slider } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { ELEMENT_COLORS, computeBonds, parseCif, type Structure3D } from '../../utils/structure3d';

declare global {
  interface Window {
    $3Dmol: any;
  }
}

export interface AtomRef {
  /** 模型内部下标（0 起） */
  index: number;
  /** 对应 POSCAR 坐标行的序号（1 起，与 CIF 里的 Ag1/O33 编号一致） */
  poscarIndex: number;
  element: string;
}

interface Props {
  cif: string | null;
  height?: number;
  /** 已选中的原子（索引 + 元素），用于高亮与后续"固定原子"功能 */
  selected: AtomRef[];
  /** 点击原子：`additive=true` 表示按住 Ctrl/⌘（多选），否则单选替换 */
  onClickAtom: (atom: AtomRef, additive: boolean) => void;
  /** 框选（Shift + 拖拽）：atoms = 框内原子；additive=true 表示 Ctrl/⌘+Shift（并入当前选择） */
  onBoxSelect: (atoms: AtomRef[], additive: boolean) => void;
  onClearSelection: () => void;
}

/**
 * 结构 3D 视图（作业管理输入文件页，v0.8.2）。
 *
 * 与巡检详情页同一套 3Dmol 用法：VESTA 元素配色 + 共价半径成键 + 晶胞框，
 * 额外支持**点击选中原子**（金色高亮，选中列表在父组件维护，供后续固定原子用）。
 */
export default function Structure3DFrame({
  cif,
  height = 460,
  selected,
  onClickAtom,
  onBoxSelect,
  onClearSelection,
}: Props) {
  const holderRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<any>(null);
  const modelRef = useRef<any>(null);
  const structureRef = useRef<Structure3D | null>(null);
  /** 上一次的相机视角（getView 原样保存），切换 POSCAR/CONTCAR 时恢复 */
  const savedViewRef = useRef<number[] | null>(null);
  const [ballStick, setBallStick] = useState(true);
  const [scale, setScale] = useState(0.35);
  const [spin, setSpin] = useState(false);
  /** Shift 按住时启用"框选"覆盖层（同时屏蔽 3Dmol 的旋转拖拽） */
  const [shiftHeld, setShiftHeld] = useState(false);
  const [band, setBand] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const bandRef = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const shiftRef = useRef(false);
  /** 上一次点击是否命中原子（用于判断"双击空白区"） */
  const lastHitAtomRef = useRef(false);
  const stageRef = useRef<HTMLDivElement>(null);

  const selectedRef = useRef<AtomRef[]>(selected);
  const ballStickRef = useRef(ballStick);
  const scaleRef = useRef(scale);
  const spinRef = useRef(spin);
  const handlersRef = useRef({ onClickAtom, onBoxSelect, onClearSelection });
  /** Ctrl/⌘ 按下状态（部分环境下 3Dmol 回调不带原生事件时兜底） */
  const modifierRef = useRef(false);
  selectedRef.current = selected;
  ballStickRef.current = ballStick;
  scaleRef.current = scale;
  spinRef.current = spin;
  handlersRef.current = { onClickAtom, onBoxSelect, onClearSelection };

  useEffect(() => {
    const sync = (e: KeyboardEvent) => {
      modifierRef.current = e.ctrlKey || e.metaKey;
      shiftRef.current = e.shiftKey;
      setShiftHeld(e.shiftKey);
    };
    const clear = () => {
      modifierRef.current = false;
      shiftRef.current = false;
      setShiftHeld(false);
      endAtomSelectionDrag();
    };
    // 兜底：鼠标在框选层外松开（甚至松开在窗口外）时，结束拖动并恢复文本选择
    const stopDrag = () => {
      if (bandRef.current) finishBand(modifierRef.current);
      else endAtomSelectionDrag();
    };
    window.addEventListener('keydown', sync);
    window.addEventListener('keyup', sync);
    window.addEventListener('blur', clear);
    window.addEventListener('mouseup', stopDrag);
    // 双击空白区域 → 取消选中（挂在 stage 上，画布与框选层都能覆盖到）
    const onDoubleClick = (e: MouseEvent) => {
      const viewer = viewerRef.current;
      const parsed = structureRef.current;
      // 用原子屏幕投影自己判定"是否点在原子上"，不依赖 3Dmol 的 click 回调
      // （不同版本的 3Dmol 对空白区点击是否回调并不一致）
      let hitAtom: boolean | null = null;
      if (viewer && parsed) {
        const canvas = viewer.container?.querySelector?.('canvas') as HTMLElement | null;
        const rect = (canvas ?? stageRef.current)?.getBoundingClientRect();
        if (rect) {
          const px = e.clientX - rect.left;
          const py = e.clientY - rect.top;
          hitAtom = parsed.atoms.some((atom) => {
            const p = atomToScreen(viewer, atom.x, atom.y, atom.z);
            return !!p && Math.abs(p.x - px) <= 10 && Math.abs(p.y - py) <= 10;
          });
        }
      }
      if (hitAtom === null) hitAtom = lastHitAtomRef.current; // 兜底：用最近一次点击结果
      if (!hitAtom) handlersRef.current.onClearSelection();
    };
    const stage = stageRef.current;
    stage?.addEventListener('dblclick', onDoubleClick);
    return () => {
      window.removeEventListener('keydown', sync);
      window.removeEventListener('keyup', sync);
      window.removeEventListener('blur', clear);
      window.removeEventListener('mouseup', stopDrag);
      stage?.removeEventListener('dblclick', onDoubleClick);
      endAtomSelectionDrag();
    };
  }, []);

  const structure = useMemo(() => (cif ? parseCif(cif) : null), [cif]);
  structureRef.current = structure;

  /** 每个元素一套球棍/空间填充样式 */
  function elementStyle(element: string, s: number, ball: boolean) {
    const color = ELEMENT_COLORS[element];
    const sphere: Record<string, unknown> = { scale: s };
    if (color) sphere.color = color;
    if (!ball) return { sphere };
    const stick: Record<string, unknown> = { radius: 0.16 };
    if (color) stick.color = color;
    return { sphere, stick };
  }

  function paintModel() {
    const model = modelRef.current;
    const viewer = viewerRef.current;
    const parsed = structureRef.current;
    if (!model || !viewer || !parsed) return;
    for (const element of parsed.elements) {
      model.setStyle({ elem: element }, elementStyle(element, scaleRef.current, ballStickRef.current));
    }
    for (const atom of selectedRef.current) {
      model.setStyle(
        { index: atom.index },
        { sphere: { scale: Math.max(scaleRef.current, 0.45), color: '#ffd700' }, stick: { radius: 0.18, color: '#ffd700' } },
      );
    }
    viewer.render();
  }

  function drawCellBox(viewer: any, parsed: Structure3D) {
    const [a, b, c] = parsed.lattice;
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
        color: '#c3ceda',
        linewidth: 1,
      });
    }
  }

  /** 沿晶格向量看过去（a/b/c 视角），与巡检详情页同一套算法 */
  function viewAlongAxis(axisIndex: number) {
    const viewer = viewerRef.current;
    const parsed = structureRef.current;
    if (!viewer || !parsed) return;
    const v = parsed.lattice[axisIndex];
    const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    const z = [v[0] / len, v[1] / len, v[2] / len];
    const upVec = axisIndex === 2 ? parsed.lattice[0] : parsed.lattice[2];
    const dot = z[0] * upVec[0] + z[1] * upVec[1] + z[2] * upVec[2];
    const upRaw = [upVec[0] - dot * z[0], upVec[1] - dot * z[1], upVec[2] - dot * z[2]];
    const ulen = Math.sqrt(upRaw[0] ** 2 + upRaw[1] ** 2 + upRaw[2] ** 2) || 1;
    const up = [upRaw[0] / ulen, upRaw[1] / ulen, upRaw[2] / ulen];
    const x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]];
    const q = quaternionFromMatrix([
      x[0], x[1], x[2], 0,
      up[0], up[1], up[2], 0,
      z[0], z[1], z[2], 0,
      0, 0, 0, 1,
    ]);
    const target = viewer.rotationGroup.quaternion;
    target.x = q.x;
    target.y = q.y;
    target.z = q.z;
    target.w = q.w;
    viewer.render();
  }

  function quaternionFromMatrix(m: number[]) {
    const [m00, m01, m02] = [m[0], m[1], m[2]];
    const [m10, m11, m12] = [m[4], m[5], m[6]];
    const [m20, m21, m22] = [m[8], m[9], m[10]];
    const trace = m00 + m11 + m22;
    if (trace > 0) {
      const s = 0.5 / Math.sqrt(trace + 1);
      return { w: 0.25 / s, x: (m21 - m12) * s, y: (m02 - m20) * s, z: (m10 - m01) * s };
    }
    if (m00 > m11 && m00 > m22) {
      const s = 2 * Math.sqrt(1 + m00 - m11 - m22);
      return { w: (m21 - m12) / s, x: 0.25 * s, y: (m01 + m10) / s, z: (m02 + m20) / s };
    }
    if (m11 > m22) {
      const s = 2 * Math.sqrt(1 + m11 - m00 - m22);
      return { w: (m02 - m20) / s, x: (m01 + m10) / s, y: 0.25 * s, z: (m12 + m21) / s };
    }
    const s = 2 * Math.sqrt(1 + m22 - m00 - m11);
    return { w: (m10 - m01) / s, x: (m02 + m20) / s, y: (m12 + m21) / s, z: 0.25 * s };
  }

  function resetView() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.zoomTo({}, 0);
    viewer.zoom(1.25, 0);
    viewer.render();
  }

  /** 世界坐标 → 画布像素坐标（用于把原子投影到屏幕上判断是否落在框内） */
  function atomToScreen(viewer: any, x: number, y: number, z: number): { x: number; y: number } | null {
    try {
      viewer.rotationGroup.updateMatrixWorld(true);
      const me = viewer.modelGroup.matrixWorld.elements;
      const wx = me[0] * x + me[4] * y + me[8] * z + me[12];
      const wy = me[1] * x + me[5] * y + me[9] * z + me[13];
      const wz = me[2] * x + me[6] * y + me[10] * z + me[14];
      const cam = viewer.camera;
      cam.updateMatrixWorld(true);
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
    } catch {
      return null;
    }
  }

  /** 结束框选：把投影落在矩形内的原子交给父组件 */
  function finishBand(additive: boolean) {
    const rect = bandRef.current;
    const viewer = viewerRef.current;
    const parsed = structureRef.current;
    bandRef.current = null;
    setBand(null);
    endAtomSelectionDrag();
    if (!rect || !viewer || !parsed) return;
    const x0 = Math.min(rect.x0, rect.x1);
    const x1 = Math.max(rect.x0, rect.x1);
    const y0 = Math.min(rect.y0, rect.y1);
    const y1 = Math.max(rect.y0, rect.y1);
    if (x1 - x0 < 4 || y1 - y0 < 4) return; // 误触：当作没有框选
    const picked: AtomRef[] = [];
    parsed.atoms.forEach((atom, index) => {
      const pos = atomToScreen(viewer, atom.x, atom.y, atom.z);
      if (!pos) return;
      if (pos.x >= x0 && pos.x <= x1 && pos.y >= y0 && pos.y <= y1) {
      // index 是 CIF（= vasp2cif 从 POSCAR 转出，顺序与 POSCAR 坐标行一致）的下标，
      // poscarIndex 换成人们习惯的 1 起编号，方便后续"固定原子"直接对应 POSCAR 行
      picked.push({ index, poscarIndex: index + 1, element: atom.element });
      }
    });
    handlersRef.current.onBoxSelect(picked, additive);
  }

  function bandPoint(event: React.MouseEvent<HTMLDivElement>) {
    const rect = (event.currentTarget as HTMLDivElement).getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  // 结构变化（POSCAR ⇄ CONTCAR）→ 重建 viewer，但**保留当前视角**：
  // 切换前后用同一个相机参数，不会跳回默认角度/缩放。
  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return;
    // 先记下当前视角（3Dmol 的 getView/setView 可原样往返）
    const previous = viewerRef.current;
    if (previous) {
      try {
        const view = previous.getView();
        if (Array.isArray(view) && view.length) savedViewRef.current = view;
      } catch {
        // 忽略：取不到就退回默认取景
      }
    }
    holder.innerHTML = '';
    viewerRef.current = null;
    modelRef.current = null;
    if (!cif || !structure || !window.$3Dmol) return;

    const viewer = window.$3Dmol.createViewer(holder, { backgroundColor: '#f7f9fc' });
    viewer.setProjection('orthographic');
    const model = viewer.addModel(cif, 'cif');
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
    viewer.setClickable({}, true, (atom: any, _viewer: any, event: any) => {
      const additive =
        typeof event?.ctrlKey === 'boolean'
          ? !!event.ctrlKey || !!event.metaKey
          : modifierRef.current;
      if (atom && typeof atom.index === 'number') {
        lastHitAtomRef.current = true;
        handlersRef.current.onClickAtom(
          {
            index: atom.index,
            poscarIndex: atom.index + 1,
            element: String(atom.elem || ''),
          },
          additive,
        );
      } else {
        // 空白区单击**不再**清空选中（旋转时的误触很容易触发 click），
        // 清空改由「双击空白区」显式触发（见下面的 dblclick 监听）
        lastHitAtomRef.current = false;
      }
    });
    viewerRef.current = viewer;
    modelRef.current = model;
    paintModel();
    drawCellBox(viewer, structure);
    const saved = savedViewRef.current;
    if (saved && saved.length) {
      // POSCAR ⇄ CONTCAR 切换：沿用上一个视角，不重置
      try {
        viewer.setView(saved);
      } catch {
        viewer.zoomTo({}, 0);
        viewer.zoom(1.25, 0);
      }
    } else {
      viewer.zoomTo({}, 0);
      viewer.zoom(1.25, 0);
    }
    if (spinRef.current) viewer.spin('y', 1.2);
    viewer.render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cif, structure]);

  // 选中/样式变化 → 只重绘样式
  useEffect(() => {
    paintModel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, ballStick, scale]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (spin) viewer.spin('y', 1.2);
    else viewer.spin(false);
  }, [spin]);

  return (
    <div className="s3d-editor">
      <div className="s3d-editor__toolbar">
        <Segmented
          size="small"
          value={ballStick ? 'ball' : 'space'}
          onChange={(v) => setBallStick(v === 'ball')}
          options={[
            { value: 'ball', label: '球棍模型' },
            { value: 'space', label: '空间填充' },
          ]}
        />
        <span className="s3d-editor__label">原子缩放</span>
        <Slider
          min={0.15}
          max={0.85}
          step={0.05}
          value={scale}
          onChange={setScale}
          style={{ width: 120 }}
        />
        <Checkbox checked={spin} onChange={(e) => setSpin(e.target.checked)}>
          自动旋转
        </Checkbox>
        <Button size="small" onClick={() => viewAlongAxis(0)}>
          a 轴
        </Button>
        <Button size="small" onClick={() => viewAlongAxis(1)}>
          b 轴
        </Button>
        <Button size="small" onClick={() => viewAlongAxis(2)}>
          c 轴
        </Button>
        <Button size="small" icon={<ReloadOutlined />} onClick={resetView}>
          重置视角
        </Button>
        <span className="s3d-editor__label">Shift + 拖拽 = 框选</span>
        <span className="s3d-editor__label">双击空白 = 取消选中</span>
      </div>
      <div className="s3d-editor__stage" ref={stageRef}>
        <div ref={holderRef} className="s3d-editor__canvas" style={{ height }} />
        {/* Shift 按住时出现的框选覆盖层：拦截拖拽，避免 3Dmol 同时旋转 */}
        <div
          className={`s3d-editor__band-layer${shiftHeld ? ' is-active' : ''}`}
          onMouseDown={(e) => {
            if (!shiftHeld || e.button !== 0) return;
            // 关键：阻止默认行为，否则 Shift+点击/拖拽会扩展浏览器文本选区
            e.preventDefault();
            beginAtomSelectionDrag();
            const p = bandPoint(e);
            const next = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
            bandRef.current = next;
            setBand(next);
          }}
          onMouseMove={(e) => {
            if (!bandRef.current) return;
            const p = bandPoint(e);
            const next = { ...bandRef.current, x1: p.x, y1: p.y };
            bandRef.current = next;
            setBand(next);
          }}
          onMouseUp={(e) => {
            if (!bandRef.current) return;
            finishBand(!!e.ctrlKey || !!e.metaKey);
          }}
          onMouseLeave={() => {
            if (bandRef.current) finishBand(modifierRef.current);
          }}
        >
          {band && (
            <div
              className="s3d-editor__band"
              style={{
                left: Math.min(band.x0, band.x1),
                top: Math.min(band.y0, band.y1),
                width: Math.abs(band.x1 - band.x0),
                height: Math.abs(band.y1 - band.y0),
              }}
            />
          )}
          {shiftHeld && !band && <div className="s3d-editor__band-hint">按住拖动框选原子</div>}
        </div>
        {!cif && (
          <div className="s3d-editor__empty">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无结构文件（可导入 POSCAR，或点「同步最新参数」从远端取回）"
            />
          </div>
        )}
      </div>
    </div>
  );
}
  /** 框选期间临时禁用浏览器文本选择（Shift+点击/拖拽会顺带选中周围页面文字） */
  function beginAtomSelectionDrag() {
    window.getSelection()?.removeAllRanges();
    document.body.classList.add('is-atom-selecting');
  }

  function endAtomSelectionDrag() {
    document.body.classList.remove('is-atom-selecting');
  }
