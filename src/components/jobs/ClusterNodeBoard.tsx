/**
 * 集群节点状态看板（v0.8.7 重构）
 *
 * 布局：左侧节点矩阵（一个队列一行，格子 = 节点）+ 右侧队列信息行（一队列一行）。
 * 视觉：格子用 radial-gradient 做中心实、边缘虚的透明衰减，靠阴影浮起，不用硬描边；
 *       左侧矩阵与右侧信息行**行高 14px、行距 8px 严格对齐**。
 * 交互：滚轮 / 拖动横向滑动，target / curr 分离 + rAF 插值（不用 CSS transition），
 *       Tooltip 事件委托，只显示 节点名 / 队列名 / 已用·总核。
 *
 * 样式在 `src/styles/global.css` 的 `.cnb-*` 段（类名加 `cnb-` 前缀避免与全局样式撞名）。
 */
import { useEffect, useMemo, useRef } from 'react';
import type { CSSProperties } from 'react';
import type { ClusterSnapshot } from '../../types';

export interface QueueNode {
  /** 节点名，如 b001 */
  name: string;
  /** 该节点总核数 */
  total: number;
  /** 该节点已用核数 */
  used: number;
}

export interface Queue {
  name: string;
  /** 每节点核数（后端元数据；统计以各节点 total 求和为准） */
  coresPerNode: number;
  nodes: QueueNode[];
}

interface Props {
  queues: Queue[];
  /** 头部「数据来源」文案 */
  sourceLabel?: string;
  /** 头部「缓存 X 分钟」文案（来自后端采集 TTL） */
  cacheMinutes?: number;
  /** 距上次采集的秒数（显示「刚刚采集 / N 分钟前采集」） */
  cacheAgeSeconds?: number;
}

/* ------------------------------------------------------------------ 常量 */

const CELL = 14; // 格子边长 px
const GAP = 3; // 格间距 px
const VIEW_W = 235; // 矩阵视口宽 px（14 格：14*14 + 13*3 = 235）
const EASE = 0.18; // 滚轮滑动 rAF 插值系数
const DRAG_GAIN = 0.5; // 拖动跟随系数（按规范取 0.5）
const WHEEL_STEP_MAX = 60; // 单次滚轮位移上限 px

type Level = 'high' | 'mid' | 'low';

const LEVEL_TEXT: Record<Level, string> = { high: '拥堵', mid: '较忙', low: '空闲' };

/** 空闲比例 → 色相/饱和/亮度（4° 暖红满载 → 142° 翠绿全空） */
function colorVars(free: number, total: number) {
  const r = total > 0 ? Math.max(0, Math.min(1, free / total)) : 0;
  return {
    h: 4 + r * 138,
    s: 60 + r * 12,
    l: 52 + r * 8,
  };
}

/** 拥堵等级：≥80% 拥堵 / ≥45% 较忙 / 其余空闲 */
export function queueLevel(pct: number): Level {
  return pct >= 80 ? 'high' : pct >= 45 ? 'mid' : 'low';
}

export interface QueueStats {
  n: number;
  totalCores: number;
  freeCores: number;
  usedCores: number;
  pct: number;
  level: Level;
  stateText: string;
}

export function computeQueueStats(q: Queue): QueueStats {
  const n = q.nodes.length;
  const totalCores = q.nodes.reduce((s, x) => s + Math.max(0, x.total), 0);
  const freeCores = q.nodes.reduce((s, x) => s + Math.max(0, x.total - x.used), 0);
  const usedCores = Math.max(0, totalCores - freeCores);
  const pct = totalCores > 0 ? (usedCores / totalCores) * 100 : 0;
  const level = queueLevel(pct);
  return { n, totalCores, freeCores, usedCores, pct, level, stateText: LEVEL_TEXT[level] };
}

/** ClusterSnapshot（/api/jobs/nodes）→ 看板队列数据：队列顺序跟随后端 queues 汇总 */
export function queuesFromSnapshot(snapshot: ClusterSnapshot | null): Queue[] {
  if (!snapshot) return [];
  const nodesByQueue = new Map<string, QueueNode[]>();
  snapshot.nodes.forEach((node) => {
    const list = nodesByQueue.get(node.queue) ?? [];
    list.push({
      name: node.name,
      total: node.maxCores,
      used: Math.max(0, node.maxCores - node.idleCores),
    });
    nodesByQueue.set(node.queue, list);
  });
  const declared = snapshot.queues.map((q) => q.queue);
  const coresPerNode = new Map(snapshot.queues.map((q) => [q.queue, q.coresPerNode]));
  const rest = [...nodesByQueue.keys()].filter((name) => !declared.includes(name));
  return [...declared, ...rest]
    .filter((name) => nodesByQueue.has(name))
    .map((name) => ({
      name,
      coresPerNode: coresPerNode.get(name) ?? 0,
      nodes: nodesByQueue.get(name) ?? [],
    }));
}

/* -------------------------------------------------------------- 组件本体 */

export default function ClusterNodeBoard({
  queues,
  sourceLabel = 'bhosts',
  cacheMinutes = 5,
  cacheAgeSeconds = 0,
}: Props) {
  const ageText =
    cacheAgeSeconds > 90
      ? `${Math.round(cacheAgeSeconds / 60)} 分钟前采集`
      : cacheAgeSeconds > 5
        ? `${Math.round(cacheAgeSeconds)} 秒前采集`
        : '刚刚采集';
  const viewportRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const tipNameRef = useRef<HTMLDivElement>(null);
  const tipQueueRef = useRef<HTMLDivElement>(null);
  const tipCoresRef = useRef<HTMLDivElement>(null);

  const currRef = useRef(0); // 当前位移
  const targetRef = useRef(0); // 目标位移
  const dragRef = useRef<{ x: number; start: number } | null>(null);

  const stats = useMemo(() => queues.map((q) => ({ q, ...computeQueueStats(q) })), [queues]);
  const nodeCount = useMemo(() => queues.reduce((s, q) => s + q.nodes.length, 0), [queues]);
  const columns = useMemo(
    () => queues.reduce((m, q) => Math.max(m, q.nodes.length), 0),
    [queues],
  );

  const totalW = columns > 0 ? columns * CELL + (columns - 1) * GAP : 0;
  const maxOffset = Math.max(0, totalW - VIEW_W);
  const thumbW = totalW > VIEW_W ? Math.max(18, (VIEW_W / totalW) * VIEW_W) : VIEW_W;
  const hasData = queues.length > 0;
  const metricsRef = useRef({ maxOffset, thumbW });
  metricsRef.current = { maxOffset, thumbW };

  // 依赖里带 hasData / maxOffset：空数据时组件返回占位块（视口与 tooltip 都不存在），
  // 等数据到达必须重新挂载监听；数据变短时也要把位移收回可视范围。
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const tooltip = tooltipRef.current;
    let raf: number | null = null;
    if (currRef.current > metricsRef.current.maxOffset) {
      currRef.current = metricsRef.current.maxOffset;
      targetRef.current = metricsRef.current.maxOffset;
    }

    const draw = () => {
      const m = metricsRef.current;
      if (trackRef.current) {
        trackRef.current.style.transform = `translate3d(${-currRef.current}px, 0, 0)`;
      }
      if (thumbRef.current) {
        const span = Math.max(0, VIEW_W - m.thumbW);
        const pos = m.maxOffset > 0 ? (currRef.current / m.maxOffset) * span : 0;
        thumbRef.current.style.transform = `translate3d(${pos}px, 0, 0)`;
      }
    };

    // 平滑滑动核心：target / curr 分离 + rAF 插值（不用 CSS transition）
    const tick = () => {
      const diff = targetRef.current - currRef.current;
      if (Math.abs(diff) < 0.1) {
        currRef.current = targetRef.current;
        draw();
        raf = null;
        return;
      }
      currRef.current += diff * EASE;
      draw();
      raf = requestAnimationFrame(tick);
    };
    const kick = () => {
      if (raf === null) raf = requestAnimationFrame(tick);
    };
    const clampTarget = (v: number) =>
      Math.max(0, Math.min(metricsRef.current.maxOffset, v));

    const onWheel = (e: WheelEvent) => {
      if (metricsRef.current.maxOffset <= 0) return;
      e.preventDefault();
      // 纵向 / 横向滚轮都映射为横向滑动，并按 deltaMode 归一化后限幅
      let d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (e.deltaMode === 1) d *= 16;
      else if (e.deltaMode === 2) d *= VIEW_W;
      d = Math.max(-WHEEL_STEP_MAX, Math.min(WHEEL_STEP_MAX, d));
      targetRef.current = clampTarget(targetRef.current + d);
      kick();
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0 || metricsRef.current.maxOffset <= 0) return;
      dragRef.current = { x: e.clientX, start: currRef.current };
      targetRef.current = currRef.current;
      viewport.classList.add('is-dragging');
      tooltip?.classList.remove('is-visible');
      e.preventDefault();
    };
    const onPointerMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      // 拖动时直接跟随（不走插值，避免滞后）
      currRef.current = clampTarget(drag.start - (e.clientX - drag.x) * DRAG_GAIN);
      targetRef.current = currRef.current;
      draw();
    };
    const onPointerUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      viewport.classList.remove('is-dragging');
    };

    // Tooltip：事件委托，只读 data-* 并直接写 DOM（不触发 React 重渲染）
    const onOver = (e: Event) => {
      if (dragRef.current) return;
      const cell = (e.target as HTMLElement | null)?.closest?.('.cnb-cell') as
        | HTMLElement
        | null;
      if (!cell || !tooltip) return;
      if (tipNameRef.current) tipNameRef.current.textContent = cell.dataset.name ?? '';
      if (tipQueueRef.current) tipQueueRef.current.textContent = cell.dataset.queue ?? '';
      if (tipCoresRef.current) {
        tipCoresRef.current.textContent = `${cell.dataset.used ?? '0'}/${cell.dataset.total ?? '0'}`;
      }
      tooltip.classList.add('is-visible');
    };
    const onMove = (e: MouseEvent) => {
      if (!tooltip || !tooltip.classList.contains('is-visible') || dragRef.current) return;
      const pad = 16;
      tooltip.style.left = `${e.clientX + pad}px`;
      tooltip.style.top = `${e.clientY + pad}px`;
      const rect = tooltip.getBoundingClientRect();
      if (rect.right > window.innerWidth) {
        tooltip.style.left = `${e.clientX - rect.width - pad}px`;
      }
      if (rect.bottom > window.innerHeight) {
        tooltip.style.top = `${e.clientY - rect.height - pad}px`;
      }
    };
    const onLeave = () => tooltip?.classList.remove('is-visible');

    draw();
    viewport.addEventListener('wheel', onWheel, { passive: false });
    viewport.addEventListener('pointerdown', onPointerDown);
    viewport.addEventListener('mouseover', onOver);
    viewport.addEventListener('mouseleave', onLeave);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
    window.addEventListener('mousemove', onMove);

    return () => {
      viewport.removeEventListener('wheel', onWheel);
      viewport.removeEventListener('pointerdown', onPointerDown);
      viewport.removeEventListener('mouseover', onOver);
      viewport.removeEventListener('mouseleave', onLeave);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
      window.removeEventListener('mousemove', onMove);
      if (raf !== null) cancelAnimationFrame(raf);
    };
  }, [hasData, maxOffset]);

  if (queues.length === 0) {
    return (
      <div className="cnb-board cnb-board--empty">
        <div className="cnb-title">集群节点状态</div>
        <div className="cnb-sub">暂无节点数据</div>
      </div>
    );
  }

  return (
    <div className="cnb-board">
      <div className="cnb-head">
        <div className="cnb-title">集群节点状态</div>
        <div className="cnb-sub">
          数据来源 {sourceLabel} · 缓存 {cacheMinutes} 分钟 · {queues.length} 个队列 /{' '}
          {nodeCount} 个节点 · {ageText}
        </div>
      </div>

      <div className="cnb-body">
        <div className="cnb-left">
          <div
            ref={viewportRef}
            className={`cnb-viewport${maxOffset > 0 ? ' is-scrollable' : ''}`}
          >
            <div className="cnb-matrix" ref={trackRef}>
              {queues.map((q) => (
                <div className="cnb-row" key={q.name}>
                  {q.nodes.map((node) => {
                    const free = Math.max(0, node.total - node.used);
                    const c = colorVars(free, node.total);
                    const style = {
                      '--h': c.h,
                      '--s': `${c.s}%`,
                      '--l': `${c.l}%`,
                    } as CSSProperties;
                    return (
                      <div
                        key={node.name}
                        className="cnb-cell"
                        style={style}
                        data-name={node.name}
                        data-queue={q.name}
                        data-used={node.used}
                        data-total={node.total}
                        aria-label={`${node.name} · ${q.name} · 已用 ${node.used}/${node.total} 核`}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
          <div className="cnb-indicator" aria-hidden="true">
            <div className="cnb-indicator__thumb" ref={thumbRef} style={{ width: thumbW }} />
          </div>
        </div>

        <div className="cnb-info">
          {stats.map(({ q, n, pct, level, stateText }) => (
            <div className="cnb-info-row" key={q.name}>
              <div className="cnb-q-block">
                <span className={`cnb-q-dot ${level}`} />
                <span className="cnb-q-name" title={q.name}>
                  {q.name}
                </span>
                <span className="cnb-q-nodes">
                  <b>{n}</b> 节点
                </span>
              </div>
              <div
                className="cnb-q-bar"
                role="progressbar"
                aria-valuenow={Math.round(pct)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${q.name} 拥堵率`}
              >
                {pct > 0 && (
                  <div className={`cnb-q-bar-fill ${level}`} style={{ width: `${pct.toFixed(1)}%` }} />
                )}
              </div>
              <div className="cnb-q-meta">
                <span className={`cnb-q-pct ${level}`}>{pct.toFixed(1)}%</span>
                <span className={`cnb-q-state ${level}`}>{stateText}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="cnb-tooltip" ref={tooltipRef} role="tooltip">
        <div className="cnb-tt-name" ref={tipNameRef} />
        <div className="cnb-tt-queue" ref={tipQueueRef} />
        <div className="cnb-tt-cores" ref={tipCoresRef} />
      </div>
    </div>
  );
}
