import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Checkbox, Radio, Slider } from 'antd';
import {
  ELEMENT_COLORS,
  parseCif,
  type Structure3D,
} from '../../utils/structure3d';
import type { InspectionDetail } from '../../types';
import './structure3d.css';

type NebImage = NonNullable<NonNullable<InspectionDetail['analysis']>['neb_images']>[number];

interface Props {
  images: NebImage[];
}

const ROLE_LABEL: Record<NebImage['role'], string> = {
  is: '初态',
  fs: '末态',
  middle: '中间态',
};

/** 原子球尺寸（球棍模型）默认值 —— 界面上唯一的"原子缩放"滑杆 */
const DEFAULT_ATOM_SCALE = 0.35;
/** 画面整体缩放倍率：固定 2.5（3Dmol zoom(k)，k>1 为拉近），不单独暴露控制 */
const VIEW_ZOOM = 2.5;

/**
 * NEB 映像结构横向对比（v0.6.9，3Dmol.js）
 *
 * 只展示**优化后**的结构：IS → 中间态… → FS 从左到右排列。
 * - 旋转/缩放联动：拖动或滚轮操作任一格，其余视角同步；
 * - 球棍 / 空间填充切换、自动旋转、缩放、重置视角；
 * - 鞍点（相对能最高）高亮边框；格子下方给出相对能垒与最大受力。
 */
export default function NebImages3DViewer({ images }: Props) {
  const [ballStick, setBallStick] = useState(true);
  const [spin, setSpin] = useState(false);
  // 界面只暴露一个滑杆：原子缩放（画面倍率固定 VIEW_ZOOM）
  const [scale, setScale] = useState(DEFAULT_ATOM_SCALE);
  /** 3Dmol.js 不可用时的降级标记（避免直接抛错导致整个详情白屏） */
  const [engineMissing, setEngineMissing] = useState(false);

  const containerRefs = useRef<(HTMLDivElement | null)[]>([]);
  const viewerRefs = useRef<any[]>([]);
  const modelRefs = useRef<any[]>([]);
  const listenersRef = useRef<Array<() => void>>([]);
  const ballRef = useRef(ballStick);
  const scaleRef = useRef(scale);
  ballRef.current = ballStick;
  scaleRef.current = scale;

  const structures = useMemo(
    () =>
      images.map((img) => {
        try {
          return parseCif(img.cif) as Structure3D | null;
        } catch {
          return null;
        }
      }),
    [images],
  );

  /** 鞍点：相对能最高的映像 */
  const saddleIndex = useMemo(() => {
    let idx = -1;
    images.forEach((img, i) => {
      if (
        img.relative != null &&
        (idx < 0 || img.relative > (images[idx].relative ?? -Infinity))
      ) {
        idx = i;
      }
    });
    return idx;
  }, [images]);

  const elementSet = useMemo(() => {
    const set = new Set<string>();
    structures.forEach((s) => s?.elements.forEach((el) => set.add(el)));
    return [...set];
  }, [structures]);

  function styleFor(viewer: any, structure: Structure3D, ball: boolean, size: number) {
    for (const el of structure.elements) {
      const style: any = { sphere: { scale: size } };
      if (ball) style.stick = { radius: 0.16 };
      const color = ELEMENT_COLORS[el];
      if (color) {
        style.sphere.color = color;
        if (style.stick) style.stick.color = color;
      }
      viewer.setStyle({ elem: el }, style);
    }
  }

  function drawCell(viewer: any, structure: Structure3D) {
    const [a, b, c] = structure.lattice;
    const add = (p: number[], q: number[]) =>
      [p[0] + q[0], p[1] + q[1], p[2] + q[2]];
    const corners = [
      [0, 0, 0],
      a,
      b,
      c,
      add(a, b),
      add(a, c),
      add(b, c),
      add(add(a, b), c),
    ];
    const edges: [number, number][] = [
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
    edges.forEach(([i, j]) => {
      viewer.addLine({
        start: { x: corners[i][0], y: corners[i][1], z: corners[i][2] },
        end: { x: corners[j][0], y: corners[j][1], z: corners[j][2] },
        color: '#c3ceda',
        dashed: true,
      });
    });
  }

  function syncFrom(leader: any) {
    const view = leader.getView();
    viewerRefs.current.forEach((v) => {
      if (v && v !== leader) {
        v.setView(view);
        v.render();
      }
    });
  }

  // 初始化所有 3D 视图
  useEffect(() => {
    listenersRef.current.forEach((off) => off());
    listenersRef.current = [];
    viewerRefs.current.forEach((v) => {
      try {
        v?.clear();
      } catch {
        /* ignore */
      }
    });
    viewerRefs.current = [];
    modelRefs.current = [];

    if (!window.$3Dmol) {
      setEngineMissing(true);
      return undefined;
    }
    setEngineMissing(false);

    images.forEach((img, i) => {
      const container = containerRefs.current[i];
      const structure = structures[i];
      if (!container || !structure) return;
      let viewer: any = null;
      try {
        container.innerHTML = '';
        container.style.width = '100%';
        container.style.height = '240px';
        viewer = window.$3Dmol.createViewer(container, {
          backgroundColor: '#f7f9fc',
        });
        viewer.setProjection('orthographic');
        const model = viewer.addModel(img.cif, 'cif');
        styleFor(viewer, structure, ballRef.current, scaleRef.current);
        drawCell(viewer, structure);
        viewer.zoomTo();
        // 画面整体放大（在 zoomTo 自适应之后再按倍率拉近）
        viewer.zoom(VIEW_ZOOM);
        if (i > 0 && viewerRefs.current[0]) viewer.setView(viewerRefs.current[0].getView());
        viewer.resize();
        viewer.render();
        viewerRefs.current[i] = viewer;
        modelRefs.current[i] = model;
      } catch (err) {
        // 单个映像渲染失败不影响其他映像（也避免整个详情弹窗崩掉）
        console.warn('[neb3d] 映像渲染失败：', img.label, err);
        return;
      }
      if (!viewer) return;

      const onDrag = (e: MouseEvent) => {
        if (e.buttons !== 0) syncFrom(viewer);
      };
      const onWheel = () => syncFrom(viewer);
      container.addEventListener('mousemove', onDrag);
      container.addEventListener('mouseup', () => syncFrom(viewer));
      container.addEventListener('wheel', onWheel, { passive: true });
      listenersRef.current.push(() => {
        container.removeEventListener('mousemove', onDrag);
        container.removeEventListener('wheel', onWheel);
      });
    });

    return () => {
      listenersRef.current.forEach((off) => off());
      listenersRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [images, structures]);

  // 样式 / 缩放变化
  useEffect(() => {
    structures.forEach((structure, i) => {
      const viewer = viewerRefs.current[i];
      if (!viewer || !structure) return;
      styleFor(viewer, structure, ballStick, scale);
      viewer.render();
    });
  }, [ballStick, scale, structures]);

  // 自动旋转（联动旋转所有面板）
  useEffect(() => {
    if (!spin) return undefined;
    const timer = window.setInterval(() => {
      viewerRefs.current.forEach((v) => {
        if (!v) return;
        v.rotate(1.2, 'y');
        v.render();
      });
    }, 40);
    return () => window.clearInterval(timer);
  }, [spin]);

  const resetView = () => {
    setScale(DEFAULT_ATOM_SCALE);
    viewerRefs.current.forEach((v) => {
      if (!v) return;
      v.zoomTo();
      v.zoom(VIEW_ZOOM);
      v.render();
    });
    syncFrom(viewerRefs.current[0]);
  };

  if (images.length === 0) {
    return <div className="analysis-chart-empty">暂无 NEB 映像结构</div>;
  }

  if (engineMissing) {
    return (
      <div className="analysis-chart-empty">
        3D 渲染库（3Dmol）未加载，无法显示映像结构；请刷新页面重试
        （生产模式下 public/3dmol 需要由后端挂载到 /3dmol）。
      </div>
    );
  }

  const has3d = structures.some(Boolean);

  return (
    <div className="neb3d">
      <div className="neb3d__bar">
        <Radio.Group
          size="small"
          value={ballStick ? 'ball' : 'space'}
          onChange={(e) => setBallStick(e.target.value === 'ball')}
          optionType="button"
          options={[
            { label: '球棍', value: 'ball' },
            { label: '空间填充', value: 'space' },
          ]}
        />
        <span className="neb3d__scale">
          原子缩放
          <Slider
            min={0.15}
            max={0.85}
            step={0.05}
            value={scale}
            onChange={setScale}
            style={{ width: 110, margin: '0 6px' }}
          />
        </span>
        <Checkbox checked={spin} onChange={(e) => setSpin(e.target.checked)}>
          自动旋转
        </Checkbox>
        <Button size="small" onClick={resetView}>
          重置视角
        </Button>
        <span className="neb3d__legend">
          {elementSet.map((el) => (
            <span key={el} className="neb3d__legend-item">
              <span
                className="neb3d__legend-dot"
                style={{ background: ELEMENT_COLORS[el] ?? '#999' }}
              />
              {el}
            </span>
          ))}
        </span>
      </div>

      <div className="neb3d__grid">
        {images.map((img, i) => (
          <div
            key={img.label}
            className={`neb3d__panel${i === saddleIndex ? ' is-saddle' : ''}`}
          >
            <div className="neb3d__head">
              <span className="fe-chip">映像 {img.label}</span>
              <span className={`fe-badge${i === saddleIndex ? ' is-warn' : ''}`}>
                {i === saddleIndex ? '鞍点' : ROLE_LABEL[img.role]}
              </span>
            </div>
            <div
              className="neb3d__canvas"
              ref={(el) => {
                containerRefs.current[i] = el;
              }}
            />
            <div className="neb3d__foot">
              {img.relative != null && (
                <span className="fe-num fe-num--pos">
                  ΔE {img.relative >= 0 ? '+' : ''}
                  {img.relative.toFixed(3)}
                </span>
              )}
              {img.max_force != null && (
                <span className="fe-num">F {img.max_force.toFixed(3)}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="fe-footnote">
        展示各映像<b>优化后</b>的结构（优先 CONTCAR，缺失时用 POSCAR），从左到右为 初态 → 中间态 → 末态；
        拖动/滚轮操作任一结构，其余结构视角同步。结构由巡检在离子步推进到 25 步桶时自动从远端抓取并转 CIF。
        {!has3d && '（当前 CIF 无法解析，可能是文件缺失）'}
      </div>
    </div>
  );
}
