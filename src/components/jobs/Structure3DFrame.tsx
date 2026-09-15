import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Checkbox, Empty, Segmented, Slider, Tag } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { ELEMENT_COLORS, computeBonds, parseCif, type Structure3D } from '../../utils/structure3d';

declare global {
  interface Window {
    $3Dmol: any;
  }
}

export interface AtomRef {
  index: number;
  element: string;
}

interface Props {
  cif: string | null;
  height?: number;
  /** 已选中的原子（索引 + 元素），用于高亮与后续"固定原子"功能 */
  selected: AtomRef[];
  onToggleAtom: (atom: AtomRef) => void;
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
  onToggleAtom,
  onClearSelection,
}: Props) {
  const holderRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<any>(null);
  const modelRef = useRef<any>(null);
  const structureRef = useRef<Structure3D | null>(null);
  const [ballStick, setBallStick] = useState(true);
  const [scale, setScale] = useState(0.35);
  const [spin, setSpin] = useState(false);

  const selectedRef = useRef<AtomRef[]>(selected);
  const ballStickRef = useRef(ballStick);
  const scaleRef = useRef(scale);
  const spinRef = useRef(spin);
  const handlersRef = useRef({ onToggleAtom, onClearSelection });
  selectedRef.current = selected;
  ballStickRef.current = ballStick;
  scaleRef.current = scale;
  spinRef.current = spin;
  handlersRef.current = { onToggleAtom, onClearSelection };

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

  // 结构变化 → 重建 viewer
  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return;
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
    viewer.setClickable({}, true, (atom: any) => {
      if (atom && typeof atom.index === 'number') {
        handlersRef.current.onToggleAtom({ index: atom.index, element: String(atom.elem || '') });
      } else {
        handlersRef.current.onClearSelection();
      }
    });
    viewerRef.current = viewer;
    modelRef.current = model;
    paintModel();
    drawCellBox(viewer, structure);
    viewer.zoomTo({}, 0);
    viewer.zoom(1.25, 0);
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
        {selected.length > 0 && (
          <Tag color="gold" bordered={false}>
            已选 {selected.length} 个原子
          </Tag>
        )}
      </div>
      <div className="s3d-editor__stage">
        <div ref={holderRef} className="s3d-editor__canvas" style={{ height }} />
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
