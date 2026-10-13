/**
 * PDOS 分析弹窗（2026-10-13 链路重建）。
 *
 * 链路：点「PDOS · 开始分析」→ 后端异步跑远端 vaspkit（整合数据回传本地）→ 轮询状态 → 出图。
 * - 已有分析结果时直接展示（不重复跑远端）；
 * - 左侧三级轨道菜单（一级总态密度 / 二级元素×轨道 / 三级只对 p、d 分方向），右侧 ECharts 折线；
 * - 横轴 = 相对费米能级的能量（数据已由提取脚本校正），零点画竖直虚线；纵轴 Intensity；
 * - 自旋极化默认**镜像布局**（up 上 / down 下翻转），可切叠加；曲线：up 实线、down 虚线；
 * - 底部：费米能级 + 能量范围（默认 −10~10，可自适应）+ 重置 + 导出图片 + 重新分析；
 * - 原生 `<dialog>`，≤720px 全屏。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Checkbox, InputNumber, Popover, Segmented, Spin, Tree, Tooltip } from 'antd';
import type { DataNode } from 'antd/es/tree';
import {
  DownOutlined,
  ReloadOutlined,
  SaveOutlined,
  UnorderedListOutlined,
  UpOutlined,
} from '@ant-design/icons';

import { clearPdos, fetchPdosData, fetchPdosStatus, triggerPdos } from '../../api/jobs';
import type { PdosTreeNode, PdosView } from '../../types';
import useEcharts from '../dashboard/useEcharts';

interface Props {
  open: boolean;
  taskId: string;
  taskName?: string;
  /** 点「PDOS · 开始分析」进来的：没有结果就直接开始跑；从别处打开只展示 */
  autoStart?: boolean;
  onClose: () => void;
}

/** 每条可见曲线的绘图信息（由菜单选中项展开而来） */
interface CurveEntry {
  id: string;
  /** 曲线所属的菜单节点 key（点图例芯片 = 取消勾选它） */
  nodeKey: string;
  name: string;
  spin: 'up' | 'down' | 'total';
  color: string;
  level: 1 | 2 | 3;
  grid: 'total' | 'partial';
  values: number[];
  dashed: boolean;
}

const LEVEL_WIDTH: Record<number, number> = { 1: 3, 2: 1.8, 3: 1.2 };
const SPIN_LABEL: Record<string, string> = { up: '↑', down: '↓', total: '' };

export default function PdosModal({ open, taskId, taskName, autoStart = false, onClose }: Props) {
  const { message } = App.useApp();
  const ref = useRef<HTMLDialogElement | null>(null);
  const pollRef = useRef<number | null>(null);

  const [view, setView] = useState<PdosView | null>(null);
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'failed'>('idle');
  const [error, setError] = useState('');
  const [checkedKeys, setCheckedKeys] = useState<string[]>(['total']);
  const [mirror, setMirror] = useState(true);
  const [showZero, setShowZero] = useState(true);
  const [autoRange, setAutoRange] = useState(false);
  const [xMin, setXMin] = useState(-10);
  const [xMax, setXMax] = useState(10);
  const [chart, setChart] = useState<{ getDataURL: (opts?: unknown) => string } | null>(null);
  /** 轨道选择面板是否展开（**内联面板**，不弹浮层 —— 原生 <dialog> 里 portal 会被遮住） */
  const [menuOpen, setMenuOpen] = useState(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadData = useCallback(async () => {
    const data = await fetchPdosData(taskId);
    setView(data);
    setStatus('done');
    setError('');
    setMirror(data.meta.spin_polarized !== false);
    setCheckedKeys(['total']);
    return data;
  }, [taskId]);

  /** 触发分析并轮询；完成 → 拉数据 */
  const runAnalysis = useCallback(
    async (fresh: boolean) => {
      stopPolling();
      setStatus('running');
      setError('');
      setView(null);
      try {
        if (fresh) await clearPdos(taskId);
        const started = await triggerPdos(taskId);
        const runId = started.run_id;
        const tick = async () => {
          try {
            const st = await fetchPdosStatus(taskId, runId);
            if (st.status === 'done') {
              stopPolling();
              await loadData();
            } else if (st.status === 'failed') {
              stopPolling();
              setStatus('failed');
              setError(st.error || '分析失败');
            }
          } catch (e) {
            stopPolling();
            setStatus('failed');
            setError(e instanceof Error ? e.message : '查询分析状态失败');
          }
        };
        pollRef.current = window.setInterval(() => void tick(), 2000);
        await tick();
      } catch (e) {
        setStatus('failed');
        setError(e instanceof Error ? e.message : '触发分析失败');
      }
    },
    [taskId, stopPolling, loadData],
  );

  // 打开：已有结果直接画；没有的话——点按钮进来的才自动开跑，否则等用户点「开始分析」
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setStatus('idle');
      try {
        const data = await fetchPdosData(taskId);
        if (!cancelled) {
          setView(data);
          setStatus('done');
          setMirror(data.meta.spin_polarized !== false);
          setCheckedKeys(['total']);
        }
      } catch {
        if (cancelled) return;
        // 没有结果：先看上一次是不是失败了 —— 失败就把原因摆出来等用户点重试，别反复占远端算力
        let lastFailed = false;
        let lastError = '';
        try {
          const st = await fetchPdosStatus(taskId);
          lastFailed = st.status === 'failed' && st.has_data !== true;
          lastError = st.error || '';
        } catch {
          lastFailed = false;
        }
        if (cancelled) return;
        if (lastFailed) {
          setStatus('failed');
          setError(lastError || '上次分析失败');
        } else if (autoStart) {
          await runAnalysis(false);
        } else {
          setStatus('idle');
        }
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, taskId, autoStart]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const meta = view?.meta;
  const spin = Boolean(meta?.spin_polarized);

  /** 菜单树（antd Tree：父节点勾选带动子节点，半选由 antd 处理） */
  const treeData = useMemo<DataNode[]>(() => {
    const mapNode = (node: PdosTreeNode): DataNode => ({
      key: node.key,
      // 元素节点只做分组：没有勾选框（见 build_view 的 checkable=false）
      disableCheckbox: node.checkable === false,
      className: node.checkable === false ? 'pdos-tree-node--group' : undefined,
      title: (
        <span className={`pdos-tree__title pdos-tree__title--l${node.level}`}>
          {node.color ? (
            <span className="pdos-tree__dot" style={{ background: node.color }} />
          ) : null}
          {node.label}
        </span>
      ),
      children: (node.children ?? []).map(mapNode),
    });
    return (view?.tree ?? []).map(mapNode);
  }, [view]);

  /** 默认展开到二级（元素 + 轨道），方向投影那级收起 —— 元素多时菜单不会太长 */
  const defaultExpandedKeys = useMemo(() => {
    const keys: string[] = [];
    const walk = (node: PdosTreeNode) => {
      if (node.level <= 2) keys.push(node.key);
      (node.children ?? []).forEach(walk);
    };
    (view?.tree ?? []).forEach(walk);
    return keys;
  }, [view]);

  /** 选中项 → 要画的曲线（父节点勾选后其自身曲线也被选中） */
  const curves = useMemo<CurveEntry[]>(() => {
    if (!view) return [];
    const picked = new Set(checkedKeys);
    const out: CurveEntry[] = [];
    const walk = (node: PdosTreeNode) => {
      if (picked.has(node.key)) {
        for (const curve of node.curves ?? []) {
          const seriesRef = view.series[curve.id];
          if (!seriesRef) continue;
          out.push({
            id: curve.id,
            nodeKey: node.key,
            name: `${node.label}${spin ? ` ${SPIN_LABEL[curve.spin] ?? ''}` : ''}`,
            spin: curve.spin,
            color: curve.color || '#5B8DEF',
            level: node.level,
            grid: seriesRef.grid,
            values: seriesRef.values,
            dashed: curve.spin === 'down',
          });
        }
      }
      (node.children ?? []).forEach(walk);
    };
    (view.tree ?? []).forEach(walk);
    return out;
  }, [view, checkedKeys, spin]);

  /**
   * 统一的 x 轴：**所有曲线都用「总态密度」那条能量网格**。
   *
   * 为什么：总态密度的能量来自 DOSCAR，投影态密度来自 VASPKIT 的 PDOS_*.dat（脚本已把
   * `E−Efermi` 加回来），两边四舍五入后能差 ~1e-3 eV —— ECharts 的 axis tooltip 是按 x
   * **精确匹配**取点的，差这一点就会导致"某些点只有部分曲线显示"（2026-10-13 用户反馈）。
   * 投影网格 = 总网格去掉 EMIN 首行，所以这里按"起点偏移"对齐（容差 2e-3 自动探测，默认 1）。
   */
  const partialOffset = useMemo(() => {
    const total = view?.energy.total ?? [];
    const partial = view?.energy.partial ?? [];
    if (!total.length || !partial.length) return 0;
    const target = partial[0];
    const index = total.findIndex((x) => Math.abs(x - target) < 0.002);
    return index >= 0 ? index : 1;
  }, [view]);

  const range = useMemo(() => {
    if (!autoRange || curves.length === 0) return { min: xMin, max: xMax };
    let min = Infinity;
    let max = -Infinity;
    curves.forEach((curve) => {
      const n = curve.values.length;
      for (let i = 0; i < n; i += 1) {
        const x = xAt(curve, i) - (meta?.efermi ?? 0);
        if (x < min) min = x;
        if (x > max) max = x;
      }
    });
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
      return { min: xMin, max: xMax };
    }
    const pad = (max - min) * 0.02;
    return { min: min - pad, max: max + pad };
  }, [autoRange, curves, view, meta, xMin, xMax]);

  /** 第 i 个点该落在哪个 x（绝对能量）：统一用总态密度的网格，投影按偏移对齐 */
  const xAt = useCallback(
    (curve: CurveEntry, index: number) => {
      const total = view?.energy.total ?? [];
      const own = view?.energy[curve.grid] ?? [];
      if (curve.grid === 'partial') {
        return total[index + partialOffset] ?? own[index] ?? index;
      }
      return total[index] ?? own[index] ?? index;
    },
    [view, partialOffset],
  );

  const option = useMemo(() => {
    const efermi = meta?.efermi ?? 0;
    const series = curves.map((curve) => {
      const n = curve.values.length;
      const data: [number, number][] = [];
      let maxAbs = 0;
      for (let i = 0; i < n; i += 1) {
        const value = curve.values[i];
        maxAbs = Math.max(maxAbs, Math.abs(value));
        data.push([xAt(curve, i) - efermi, mirror && curve.spin === 'down' ? -value : value]);
      }
      return {
        name: curve.name,
        type: 'line' as const,
        showSymbol: false,
        sampling: 'lttb' as const,
        lineStyle: {
          width: LEVEL_WIDTH[curve.level] ?? 1.5,
          type: curve.dashed ? ('dashed' as const) : ('solid' as const),
        },
        itemStyle: { color: curve.color },
        emphasis: { focus: 'series' as const },
        data,
        // 镜像布局时纵轴上下对称，这里把最大值带出来给 yAxis 用
        __maxAbs: maxAbs,
      };
    });
    const maxAbs = series.reduce((acc, item) => Math.max(acc, item.__maxAbs), 0) || 1;
    const yAxis = mirror && spin
      ? {
          min: -maxAbs * 1.05,
          max: maxAbs * 1.05,
          axisLabel: { formatter: (v: number) => Math.abs(v).toFixed(0) },
        }
      : { min: undefined, max: undefined };
    return {
      animation: false,
      // 顶部不留图例空间（图例改成工具条上的芯片，避免与轴名重叠）
      // 左边留出竖排 "Intensity" 轴名的位置
      grid: { left: 66, right: 20, top: 18, bottom: 46 },
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'cross' as const },
        // 自定义卡片：① 顶部显示当前能量；② **把该点的每条可见曲线都列出来**
        // （所有曲线已对齐到同一 x 网格，不会再有"只有部分曲线"）；
        // ③ 镜像布局下自旋向下已取负，这里显示回绝对值。
        formatter: (params: unknown) => {
          const list = (Array.isArray(params) ? params : [params]) as {
            axisValue?: number;
            value?: [number, number];
            seriesName?: string;
            marker?: string;
          }[];
          if (!list.length) return '';
          const x = list[0]?.axisValue ?? list[0]?.value?.[0];
          const head =
            x == null ? '' : `<div style="font-weight:600;margin-bottom:4px">E − E_F = ${Number(x).toFixed(3)} eV</div>`;
          const rows = list.map((item) => {
            const raw = Array.isArray(item.value) ? Number(item.value[1]) : Number(item.value);
            const shown = mirror && String(item.seriesName ?? '').includes('↓') ? Math.abs(raw) : raw;
            return `${item.marker ?? ''} ${item.seriesName ?? ''}: ${
              Number.isFinite(shown) ? shown.toFixed(4) : '—'
            }`;
          });
          return head + rows.join('<br/>');
        },
      },
      // 不用 ECharts 自带图例：曲线多时它会和轴名/彼此重叠（用户截图反馈），
      // 改用工具条上的芯片做图例（点一下取消该条曲线）。
      legend: { show: false },
      xAxis: {
        type: 'value' as const,
        name: 'E − E_F (eV)',
        nameLocation: 'middle' as const,
        nameGap: 26,
        min: range.min,
        max: range.max,
      },
      yAxis: {
        type: 'value' as const,
        name: 'Intensity',
        // 轴名竖排在**最左端**（默认 nameLocation='end' 会跑到轴顶端，用户要求放左边）
        nameLocation: 'middle' as const,
        nameRotate: 90,
        nameGap: 42,
        ...yAxis,
      },
      series: series.map(({ __maxAbs, ...rest }) => ({
        ...rest,
        ...(showZero
          ? {
              markLine: {
                silent: true,
                symbol: 'none',
                label: { show: false },
                lineStyle: { type: 'dashed' as const, color: '#98a6bd' },
                data: [{ xAxis: 0 }],
              },
            }
          : {}),
      })),
    };
  }, [curves, view, meta, mirror, spin, range, showZero, xAt]);

  const containerRef = useEcharts(option, [option], (instance) => {
    // 只保留实例（导出 PNG 用）；卸载时的 null 不回写 state，避免卸载后 setState
    if (instance) {
      setChart({ getDataURL: (opts?: unknown) => instance.getDataURL(opts as never) });
    }
  });

  const reset = () => {
    setCheckedKeys(['total']);
    setMirror(spin);
    setShowZero(true);
    setAutoRange(false);
    setXMin(-10);
    setXMax(10);
  };

  const exportImage = () => {
    if (!chart) {
      message.warning('图表还没准备好');
      return;
    }
    try {
      const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
      const link = document.createElement('a');
      link.href = url;
      link.download = `PDOS_${taskName || taskId}.png`;
      link.click();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出图片失败');
    }
  };

  const running = status === 'running';

  return (
    <dialog
      ref={ref}
      className="pdos-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <header>
        <h3>PDOS 分析{taskName ? ` · ${taskName}` : ''}</h3>
        <button type="button" className="close" aria-label="关闭" onClick={onClose}>
          ×
        </button>
      </header>

      <div className="body">
        {running && (
          <div className="pdos-progress">
            <Spin size="small" />
            <span>正在远端用 vaspkit 提取态密度（约 10–60 秒，取决于 DOSCAR/PROCAR 大小）…</span>
          </div>
        )}
        {status === 'failed' && (
          <div className="pdos-error">
            <p>分析失败：{error || '未知原因'}</p>
            <div className="pdos-error__actions">
              <Button size="small" onClick={() => void runAnalysis(false)}>
                重试
              </Button>
              <Button size="small" danger onClick={() => void runAnalysis(true)}>
                清除缓存后重试
              </Button>
            </div>
          </div>
        )}
        {status === 'done' && view && (
          <div className="pdos-main">
            <div className="pdos-toolbar">
              {/* 悬浮卡片式菜单：**必须挂在弹窗内部**（原生 <dialog> 在 top layer，
                  挂到 body 的浮层会被压在下面点不到，2026-10-13 踩过） */}
              <Popover
                trigger="click"
                placement="bottomLeft"
                open={menuOpen}
                onOpenChange={setMenuOpen}
                getPopupContainer={() => ref.current ?? document.body}
                content={
                  <div className="pdos-menu-card">
                    <Tree
                      checkable
                      checkStrictly
                      selectable={false}
                      blockNode
                      treeData={treeData}
                      defaultExpandedKeys={defaultExpandedKeys}
                      checkedKeys={checkedKeys}
                      onCheck={(keys) =>
                        setCheckedKeys((Array.isArray(keys) ? keys : keys.checked).map(String))
                      }
                    />
                    <p className="pdos-menu__hint">
                      勾哪条画哪条：点 p 只画 p，px/py/pz、dxy… 要单独勾（元素那行只是分组，不可勾）
                    </p>
                  </div>
                }
              >
                <Button size="small" icon={<UnorderedListOutlined />}>
                  轨道选择（已选 {checkedKeys.length}）
                  {menuOpen ? (
                    <UpOutlined style={{ fontSize: 10 }} />
                  ) : (
                    <DownOutlined style={{ fontSize: 10 }} />
                  )}
                </Button>
              </Popover>
              <span className="pdos-legend">
                {curves
                  .slice(0, 10)
                  .map((curve) => (
                    <button
                      type="button"
                      key={curve.id}
                      className="pdos-legend__item"
                      title="点一下取消这条曲线"
                      onClick={() =>
                        setCheckedKeys((prev) => prev.filter((key) => key !== curve.nodeKey))
                      }
                    >
                      <span className="pdos-legend__dot" style={{ background: curve.color }} />
                      {curve.name}
                    </button>
                  ))}
                {curves.length > 10 ? (
                  <span className="pdos-legend__more">等 {curves.length} 条</span>
                ) : null}
              </span>
            </div>
            <div className="pdos-chart">
              <div className="pdos-chart__canvas" ref={containerRef} />
              {curves.length === 0 && <p className="pdos-chart__empty">至少勾选一条曲线</p>}
            </div>
            {meta?.has_projection === false && (
              <p className="pdos-menu__hint">该算例没有投影态密度（只算了总态密度）</p>
            )}
          </div>
        )}
        {status === 'idle' && !view && (
          <div className="pdos-empty">
            <p>该任务还没有 PDOS 分析结果。</p>
            <Button type="primary" onClick={() => void runAnalysis(false)}>
              开始分析
            </Button>
            <p className="pdos-menu__hint">
              会在远端任务目录用 vaspkit 提取态密度，只回传整合后的数据（约 10–60 秒）
            </p>
          </div>
        )}
      </div>

      <footer className="pdos-footer">
        <span className="pdos-footer__meta">
          费米能级 E_F ={' '}
          {meta?.efermi != null ? `${Number(meta.efermi).toFixed(4)} eV` : '—'}
          {meta?.spin_polarized ? ' · 自旋极化' : ' · 非自旋'}
          {meta?.elements?.length ? ` · ${meta.elements.join('/')}` : ''}
        </span>
        {spin && (
          <Segmented
            size="small"
            value={mirror ? 'mirror' : 'overlay'}
            onChange={(value) => setMirror(value === 'mirror')}
            options={[
              { value: 'mirror', label: '镜像（↑/↓）' },
              { value: 'overlay', label: '叠加' },
            ]}
          />
        )}
        <Checkbox checked={showZero} onChange={(e) => setShowZero(e.target.checked)}>
          E_F 虚线
        </Checkbox>
        <span className="pdos-footer__range">
          范围
          <InputNumber
            size="small"
            value={range.min}
            step={1}
            disabled={autoRange}
            onChange={(v) => setXMin(Number(v ?? -10))}
            style={{ width: 74 }}
          />
          ~
          <InputNumber
            size="small"
            value={range.max}
            step={1}
            disabled={autoRange}
            onChange={(v) => setXMax(Number(v ?? 10))}
            style={{ width: 74 }}
          />
          <Checkbox checked={autoRange} onChange={(e) => setAutoRange(e.target.checked)}>
            自适应
          </Checkbox>
        </span>
        <span className="pdos-footer__actions">
          <Tooltip title="恢复默认勾选（仅总态密度）与默认坐标范围">
            <Button size="small" icon={<ReloadOutlined />} onClick={reset}>
              重置
            </Button>
          </Tooltip>
          <Button size="small" icon={<SaveOutlined />} onClick={exportImage}>
            导出图片
          </Button>
          <Tooltip title="清除本地缓存并重新跑一次远端分析">
            <Button size="small" danger onClick={() => void runAnalysis(true)} loading={running}>
              重新分析
            </Button>
          </Tooltip>
        </span>
      </footer>
    </dialog>
  );
}
