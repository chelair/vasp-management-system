import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Switch, Tooltip } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import type { InspectionDetail } from '../../types';
import { ELEMENT_COLORS, parseCif } from '../../utils/structure3d';
import Structure3DFrame, { type AtomRef } from '../jobs/Structure3DFrame';
import NebEnergyCurve from './NebEnergyCurve';

type NebImage = NonNullable<NonNullable<InspectionDetail['analysis']>['neb_images']>[number];
type BarrierImage = NonNullable<InspectionDetail['neb_barrier']>['images'][number];

/** 合并后的映像条目：能量/受力来自 nebef.pl，结构来自巡检同步的 CONTCAR（可能缺） */
interface NebEntry {
  label: string;
  relative: number | null;
  energy: number | null;
  max_force: number | null;
  cif: string | null;
}

interface Props {
  /** 已同步结构的映像（含 CIF）；可能为空（还没推进到 25 离子步桶） */
  images: NebImage[];
  /** nebef.pl 的全部映像（只含能量/受力，无结构）——用于在还没同步结构时也能看曲线 */
  barrier?: BarrierImage[] | null;
  /** 该 NEB 推进的离子步数（仅展示） */
  steps?: number | null;
}

/** 主视图高度（与作业管理同一套 3Dmol 视图） */
const MAIN_HEIGHT = 460;
/** 缩略图画布尺寸（2× 便于高分屏清晰） */
const THUMB_W = 150;
const THUMB_H = 104;
/** 离屏渲染画布尺寸（3Dmol 只开一个 WebGL 上下文） */
const OFF_W = 420;
const OFF_H = 300;
/** 缩略图跟随主视图旋转的最小间隔（ms），避免拖拽时 20 张缩略图逐帧重绘 */
const THUMB_SYNC_INTERVAL = 160;

const pad2 = (i: number) => String(i).padStart(2, '0');
const signed = (v: number | null, d = 3) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}`);
/** 映像编号归一化：目录名 `00` 与 nebef.pl 的 `0` 视为同一个映像 */
const normLabel = (value: unknown) => {
  const text = String(value ?? '').trim();
  return /^\d+$/.test(text) ? String(Number.parseInt(text, 10)) : text;
};

/**
 * NEB 映像主从视图（v0.9.40）
 *
 * 一段搞定整条 NEB 路径：统计卡 → 能量曲线（铺满、可点选）→ 主视图 → 缩略图条。
 * 四段通过当前选中索引联动：点曲线点 / 点缩略图 / 按方向键 / 点左右按钮，四种方式都能切换。
 *
 * **3D 部分直接复用作业管理那套组件 `Structure3DFrame`（3Dmol）**：配色、球棍模型、
 * 点选原子、Shift 框选、a/b/c 视角、选中原子分数坐标等与其它任务完全一致。
 * 缩略图同样出自 3Dmol —— 一个**离屏 viewer** 逐张渲染后 `drawImage` 到 2D 画布，
 * 只占 1 个 WebGL 上下文（浏览器上限约 16 个，每张开一个会直接崩），30 张也不卡。
 *
 * 能量曲线用 nebef.pl 的**全部**映像（还没同步结构的映像也画点），结构缺失的映像在主视图/
 * 缩略图里显示占位，保证三段索引始终对齐。
 */
export default function NebImageMasterDetail({ images, barrier, steps }: Props) {
  /** 合并映像列表（曲线/缩略图/主视图共用同一份索引） */
  const entries = useMemo<NebEntry[]>(() => {
    const byLabel = new Map<string, NebImage>();
    images.forEach((img) => byLabel.set(normLabel(img.label), img));
    const base: { key: string; label: string; relative: number | null; energy: number | null; max_force: number | null }[] =
      barrier && barrier.length
        ? barrier.map((b) => ({
            key: normLabel(b.label),
            label: String(b.label),
            relative: b.relative,
            energy: b.energy,
            max_force: b.max_force,
          }))
        : images.map((img) => ({
            key: normLabel(img.label),
            label: String(img.label),
            relative: img.relative,
            energy: img.energy,
            max_force: img.max_force,
          }));
    return base.map((b) => {
      const struct = byLabel.get(b.key);
      return {
        label: b.label,
        relative: b.relative ?? struct?.relative ?? null,
        energy: b.energy ?? struct?.energy ?? null,
        max_force: b.max_force ?? struct?.max_force ?? null,
        cif: struct?.cif ?? null,
      };
    });
  }, [images, barrier]);

  const count = entries.length;
  const [selected, setSelected] = useState(0);
  const [syncRotate, setSyncRotate] = useState(true);
  const [selectedAtoms, setSelectedAtoms] = useState<AtomRef[]>([]);

  const stripRef = useRef<HTMLDivElement | null>(null);
  const offscreenHostRef = useRef<HTMLDivElement | null>(null);
  const thumbItemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const thumbCanvasRefs = useRef<(HTMLCanvasElement | null)[]>([]);
  const mainViewerRef = useRef<any>(null);
  const offscreenRef = useRef<any>(null);
  const hoveredRef = useRef(false);
  const countRef = useRef(count);
  const syncRef = useRef(syncRotate);
  const entriesRef = useRef(entries);
  const structuresRef = useRef<(ReturnType<typeof parseCif>)[]>([]);
  const thumbTimerRef = useRef(0);
  const renderThumbsRef = useRef<() => void>(() => {});
  countRef.current = count;
  syncRef.current = syncRotate;
  entriesRef.current = entries;

  /** 结构解析（缩略图取元素表与配色；主视图由 Structure3DFrame 自己解析） */
  const structures = useMemo(
    () =>
      entries.map((e) => {
        if (!e.cif) return null;
        try {
          return parseCif(e.cif);
        } catch {
          return null;
        }
      }),
    [entries],
  );
  structuresRef.current = structures;

  /** 鞍点：相对能最高的映像 */
  const saddle = useMemo(() => {
    let idx = -1;
    entries.forEach((e, i) => {
      if (e.relative == null) return;
      if (idx < 0 || e.relative > (entries[idx].relative ?? -Infinity)) idx = i;
    });
    return idx;
  }, [entries]);

  /** 顶部统计（与旧「能垒看板」同一口径） */
  const stats = useMemo(() => {
    let maxForceIdx = -1;
    entries.forEach((e, i) => {
      if (e.max_force == null) return;
      if (maxForceIdx < 0 || e.max_force > (entries[maxForceIdx].max_force ?? -Infinity)) {
        maxForceIdx = i;
      }
    });
    return {
      saddleRel: saddle >= 0 ? entries[saddle].relative : null,
      maxForce: maxForceIdx >= 0 ? entries[maxForceIdx].max_force : null,
      maxForceIdx,
      endRel: count > 0 ? entries[count - 1].relative : null,
    };
  }, [entries, saddle, count]);

  const hasAnyStructure = entries.some((e) => e.cif);

  // 映像数变化时收敛选中索引
  useEffect(() => {
    setSelected((prev) => (prev >= count ? Math.max(0, count - 1) : prev));
  }, [count]);

  /** 用离屏 3Dmol viewer 逐张渲染缩略图（与主视图同一套渲染，视觉完全一致） */
  const renderThumbs = useCallback(() => {
    const off = offscreenRef.current;
    if (!off) return;
    const mainQuat =
      syncRef.current && mainViewerRef.current?.rotationGroup?.quaternion
        ? mainViewerRef.current.rotationGroup.quaternion
        : null;
    entriesRef.current.forEach((entry, i) => {
      const canvas = thumbCanvasRefs.current[i];
      if (!canvas || !entry.cif) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      try {
        off.removeAllModels();
        const model = off.addModel(entry.cif, 'cif');
        const structure = structuresRef.current[i];
        if (structure) {
          for (const el of structure.elements) {
            const color = ELEMENT_COLORS[el];
            const style: any = { sphere: { scale: 0.55 } };
            if (color) style.sphere.color = color;
            model.setStyle({ elem: el }, style);
          }
        }
        off.zoomTo({}, 0);
        if (mainQuat && off.rotationGroup?.quaternion) {
          off.rotationGroup.quaternion.set(mainQuat.x, mainQuat.y, mainQuat.z, mainQuat.w);
        } else if (off.rotationGroup?.quaternion) {
          // 关闭「同步旋转」：缩略图保持固定视角
          off.rotationGroup.quaternion.set(0, 0, 0, 1);
        }
        off.render();
        const src = off.container?.querySelector?.('canvas') as HTMLCanvasElement | null;
        if (src && src.width > 0) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
        }
      } catch {
        // 单张缩略图失败不影响其它映像
      }
    });
  }, []);
  renderThumbsRef.current = renderThumbs;

  /** 节流：拖拽期间最多每 THUMB_SYNC_INTERVAL 毫秒同步一次缩略图 */
  const scheduleThumbs = useCallback(() => {
    if (thumbTimerRef.current) return;
    thumbTimerRef.current = window.setTimeout(() => {
      thumbTimerRef.current = 0;
      renderThumbsRef.current();
    }, THUMB_SYNC_INTERVAL);
  }, []);

  useEffect(
    () => () => {
      if (thumbTimerRef.current) window.clearTimeout(thumbTimerRef.current);
    },
    [],
  );

  /** 离屏 viewer：只创建一个，供缩略图逐张渲染 */
  useEffect(() => {
    const host = offscreenHostRef.current;
    const $3Dmol = (window as any).$3Dmol;
    if (!host || !$3Dmol || !hasAnyStructure) return undefined;
    host.innerHTML = '';
    let viewer: any = null;
    try {
      viewer = $3Dmol.createViewer(host, { backgroundColor: '#fbfcfe' });
      viewer.setProjection('orthographic');
    } catch {
      viewer = null;
    }
    offscreenRef.current = viewer;
    const timer = window.setTimeout(() => renderThumbsRef.current(), 0);
    return () => {
      window.clearTimeout(timer);
      offscreenRef.current = null;
      try {
        viewer?.clear();
      } catch {
        /* ignore */
      }
    };
  }, [entries, hasAnyStructure]);

  /** 主视图 viewer 就绪：记下引用；相机变化（拖拽/滚轮）时同步缩略图视角 */
  const handleViewerReady = useCallback(
    (viewer: any | null) => {
      mainViewerRef.current = viewer;
      const el = viewer?.container as HTMLElement | undefined;
      if (el && el.dataset.nebmdBound !== '1') {
        el.dataset.nebmdBound = '1';
        el.addEventListener('mousemove', (e: MouseEvent) => {
          if (e.buttons !== 0) scheduleThumbs();
        });
        el.addEventListener('mouseup', scheduleThumbs);
        el.addEventListener('wheel', scheduleThumbs, { passive: true });
      }
      renderThumbsRef.current();
    },
    [scheduleThumbs],
  );

  const goto = useCallback((index: number) => {
    const max = Math.max(0, countRef.current - 1);
    setSelected((prev) => {
      const next = Math.min(max, Math.max(0, index));
      return next === prev ? prev : next;
    });
  }, []);
  const step = useCallback((delta: number) => {
    setSelected((prev) => {
      const max = Math.max(0, countRef.current - 1);
      return Math.min(max, Math.max(0, prev + delta));
    });
  }, []);

  // 切换映像：清空原子选中
  useEffect(() => {
    setSelectedAtoms([]);
  }, [selected]);

  // 选中 / 同步开关变化 → 立即重绘缩略图
  useEffect(() => {
    renderThumbsRef.current();
  }, [selected, syncRotate]);

  /** 键盘左右方向键：鼠标在视图内时生效 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!hoveredRef.current) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        step(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        step(1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step]);

  /** 选中项自动滚动到缩略图条可视区域（只动横向，不动页面） */
  useEffect(() => {
    const strip = stripRef.current;
    const item = thumbItemRefs.current[selected];
    if (!strip || !item) return;
    const target = item.offsetLeft - (strip.clientWidth - item.clientWidth) / 2;
    strip.scrollTo({ left: Math.max(0, target), behavior: 'smooth' });
  }, [selected]);

  if (count === 0) {
    return <div className="analysis-chart-empty">暂无 NEB 映像数据</div>;
  }

  const current = entries[selected];
  const isEndpoint = selected === 0 || selected === count - 1;
  const roleLabel =
    selected === saddle ? '鞍点' : selected === 0 ? '初态' : selected === count - 1 ? '末态' : '中间态';
  const roleClass = selected === saddle ? 'is-warn' : isEndpoint ? 'is-ok' : '';

  return (
    <div
      className="nebmd"
      onMouseEnter={() => {
        hoveredRef.current = true;
      }}
      onMouseLeave={() => {
        hoveredRef.current = false;
      }}
    >
      {/* 统计卡（原「NEB 过渡态能垒」看板的四张卡，合并到这一段里，不再重复出第二条曲线） */}
      <div className="fe-stat-grid">
        <div className="fe-stat">
          <div className="fe-stat__label">映像数量</div>
          <div className="fe-stat__value">{count}</div>
          <div className="fe-stat__sub">{count >= 2 ? `端点 2 + 中间 ${count - 2}` : '含端点'}</div>
        </div>
        <div className="fe-stat">
          <div className="fe-stat__label">能垒 Ea</div>
          <div className="fe-stat__value">{signed(stats.saddleRel)}</div>
          <div className="fe-stat__sub">
            {saddle >= 0 ? `最高点：映像 ${pad2(saddle)}` : '暂无数据'}
          </div>
        </div>
        <div className="fe-stat">
          <div className="fe-stat__label">最大受力</div>
          <div className="fe-stat__value">
            {stats.maxForce == null ? '—' : stats.maxForce.toFixed(3)}
          </div>
          <div className="fe-stat__sub">
            {stats.maxForceIdx >= 0 ? `映像 ${pad2(stats.maxForceIdx)}（eV/Å）` : '暂无数据'}
          </div>
        </div>
        <div className="fe-stat">
          <div className="fe-stat__label">末态相对能</div>
          <div className="fe-stat__value">{signed(stats.endRel)}</div>
          <div className="fe-stat__sub">
            {stats.endRel != null && Math.abs(stats.endRel) < 0.01
              ? '与初态基本一致'
              : '相对初态（映像 00）'}
          </div>
        </div>
      </div>

      <NebEnergyCurve images={entries} selected={selected} saddle={saddle} onSelect={goto} />

      {!hasAnyStructure ? (
        <div className="analysis-chart-empty">
          尚未同步 NEB 映像结构：需要巡检推进到 25 离子步桶后自动抓取各映像 CONTCAR
          （能量曲线与统计已可用）
        </div>
      ) : (
        <>
          <div className="nebmd__stage">
            {current.cif ? (
              <Structure3DFrame
                cif={current.cif}
                height={MAIN_HEIGHT}
                selected={selectedAtoms}
                onClickAtom={(atom, additive) =>
                  setSelectedAtoms((prev) => {
                    if (!additive) return [atom];
                    const exists = prev.some((x) => x.index === atom.index);
                    return exists ? prev.filter((x) => x.index !== atom.index) : [...prev, atom];
                  })
                }
                onBoxSelect={(atoms, additive) =>
                  setSelectedAtoms((prev) => {
                    if (!additive) return atoms;
                    const seen = new Set(prev.map((x) => x.index));
                    return [...prev, ...atoms.filter((x) => !seen.has(x.index))];
                  })
                }
                onClearSelection={() => setSelectedAtoms([])}
                showSelectedCoords
                onViewerReady={handleViewerReady}
                toolbarExtra={
                  <span className="nebmd__extra">
                    <span className="fe-chip">映像 {pad2(selected)}</span>
                    <span className={`fe-badge ${roleClass}`}>{roleLabel}</span>
                    {current.relative != null && (
                      <span className="fe-num fe-num--strong">
                        ΔE {current.relative >= 0 ? '+' : ''}
                        {current.relative.toFixed(3)} eV
                      </span>
                    )}
                    {current.max_force != null && (
                      <span className="fe-num">F {current.max_force.toFixed(3)}</span>
                    )}
                    <Tooltip title="打开后拖动主视图，所有缩略图一起转，便于横向对比">
                      <span className="nebmd__switch">
                        同步旋转
                        <Switch size="small" checked={syncRotate} onChange={setSyncRotate} />
                      </span>
                    </Tooltip>
                  </span>
                }
              />
            ) : (
              <div className="nebmd__no-structure">
                映像 {pad2(selected)} 尚未同步结构（缺 CONTCAR），暂不能显示 3D 视图
              </div>
            )}

            <button
              type="button"
              className="nebmd__nav nebmd__nav--prev"
              onClick={() => step(-1)}
              disabled={selected === 0}
              aria-label="上一个映像"
            >
              <LeftOutlined />
            </button>
            <button
              type="button"
              className="nebmd__nav nebmd__nav--next"
              onClick={() => step(1)}
              disabled={selected === count - 1}
              aria-label="下一个映像"
            >
              <RightOutlined />
            </button>
            {current.cif && (
              <div className="nebmd__hint">
                拖拽旋转 · 滚轮缩放 · ←/→ 切换映像 · 点击原子选中
              </div>
            )}
          </div>

          <div className="nebmd__thumbs" ref={stripRef}>
            {entries.map((entry, i) => {
              const itemSaddle = i === saddle;
              return (
                <button
                  type="button"
                  key={`${entry.label}-${i}`}
                  ref={(el) => {
                    thumbItemRefs.current[i] = el;
                  }}
                  className={`nebmd__thumb${i === selected ? ' is-selected' : ''}${
                    itemSaddle ? ' is-saddle' : ''
                  }${entry.cif ? '' : ' is-empty'}`}
                  onClick={() => goto(i)}
                  title={`映像 ${pad2(i)}${itemSaddle ? ' · 鞍点' : ''}${
                    entry.cif ? '' : ' · 尚未同步结构'
                  }`}
                >
                  {entry.cif ? (
                    <canvas
                      width={THUMB_W * 2}
                      height={THUMB_H * 2}
                      ref={(el) => {
                        thumbCanvasRefs.current[i] = el;
                      }}
                    />
                  ) : (
                    <span className="nebmd__thumb-none">无结构</span>
                  )}
                  <span className="nebmd__thumb-cap">
                    <span className="nebmd__thumb-idx">{pad2(i)}</span>
                    <span className="nebmd__thumb-role">
                      {itemSaddle ? '鞍点' : i === 0 ? '初态' : i === count - 1 ? '末态' : '中间'}
                    </span>
                    {entry.relative != null && (
                      <span className="nebmd__thumb-de">
                        {entry.relative >= 0 ? '+' : ''}
                        {entry.relative.toFixed(2)}
                      </span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}

      <div className="fe-footnote">
        能量曲线来自 nebef.pl（全部映像）；3D 展示各映像<b>优化后</b>的结构（只取 CONTCAR，
        还没有 CONTCAR 的映像在缩略图里显示「无结构」占位）。3D 与其它任务共用同一套 3Dmol 视图，
        可点选原子、Shift 框选、a/b/c 视角；拖动主视图时缩略图跟着一起转（可在工具栏关掉「同步旋转」）。
        {steps != null ? ` 当前 NEB 推进约 ${steps} 离子步。` : ''}
      </div>

      {/* 离屏 3Dmol viewer：只用于把每张映像渲染成缩略图，不额外占用可见 WebGL 上下文 */}
      {hasAnyStructure && (
        <div
          className="nebmd__offscreen"
          ref={offscreenHostRef}
          aria-hidden="true"
          style={{ width: OFF_W, height: OFF_H }}
        />
      )}
    </div>
  );
}
