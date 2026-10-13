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
import { App, Button, Checkbox, InputNumber, Segmented, Spin, Tree, Tooltip } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { ReloadOutlined, SaveOutlined, UnorderedListOutlined } from '@ant-design/icons';

import { clearPdos, fetchPdosData, fetchPdosStatus, triggerPdos } from '../../api/jobs';
import type { PdosTreeNode, PdosView } from '../../types';
import useEcharts from '../dashboard/useEcharts';

interface Props {
  open: boolean;
  taskId: string;
  taskName?: string;
  onClose: () => void;
}

/** 每条可见曲线的绘图信息（由菜单选中项展开而来） */
interface CurveEntry {
  id: string;
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

export default function PdosModal({ open, taskId, taskName, onClose }: Props) {
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

  // 打开：已有结果直接画；没有就跑一次
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
        if (!cancelled) await runAnalysis(false);
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, taskId]);

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

  const range = useMemo(() => {
    if (!autoRange || curves.length === 0) return { min: xMin, max: xMax };
    let min = Infinity;
    let max = -Infinity;
    const energy = view?.energy;
    curves.forEach((curve) => {
      const grid = energy?.[curve.grid] ?? [];
      const n = Math.min(grid.length, curve.values.length);
      for (let i = 0; i < n; i += 1) {
        const x = grid[i] - (meta?.efermi ?? 0);
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

  const option = useMemo(() => {
    const efermi = meta?.efermi ?? 0;
    const energy = view?.energy;
    const series = curves.map((curve) => {
      const grid = energy?.[curve.grid] ?? [];
      const n = Math.min(grid.length, curve.values.length);
      const data: [number, number][] = [];
      let maxAbs = 0;
      for (let i = 0; i < n; i += 1) {
        const value = curve.values[i];
        maxAbs = Math.max(maxAbs, Math.abs(value));
        data.push([grid[i] - efermi, mirror && curve.spin === 'down' ? -value : value]);
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
      grid: { left: 52, right: 18, top: 34, bottom: 44 },
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'cross' as const },
        valueFormatter: (v: number) => (v == null ? '—' : v.toFixed(4)),
      },
      legend: {
        type: 'scroll' as const,
        top: 0,
        itemHeight: 8,
        textStyle: { fontSize: 11 },
      },
      xAxis: {
        type: 'value' as const,
        name: 'E − E_F (eV)',
        nameLocation: 'middle' as const,
        nameGap: 26,
        min: range.min,
        max: range.max,
      },
      yAxis: { type: 'value' as const, name: 'Intensity', ...yAxis },
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
  }, [curves, view, meta, mirror, spin, range, showZero]);

  const containerRef = useEcharts(option, [option], (instance) =>
    setChart(instance ? { getDataURL: (opts?: unknown) => instance.getDataURL(opts as never) } : null),
  );

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
          <div className="pdos-layout">
            <div className="pdos-menu">
              <div className="pdos-menu__head">
                <UnorderedListOutlined /> 轨道选择
              </div>
              <Tree
                checkable
                blockNode
                defaultExpandAll
                treeData={treeData}
                checkedKeys={checkedKeys}
                onCheck={(keys) =>
                  setCheckedKeys(
                    (Array.isArray(keys) ? keys : keys.checked).map(String),
                  )
                }
              />
              {meta?.has_projection === false && (
                <p className="pdos-menu__hint">该算例没有投影态密度（只算了总态密度）</p>
              )}
              {meta?.has_projection && meta?.has_fine_orbitals === false && (
                <p className="pdos-menu__hint">该算例没有方向投影（dxy/dx²−y² 等），只到元素轨道这一级</p>
              )}
            </div>
            <div className="pdos-chart">
              <div className="pdos-chart__canvas" ref={containerRef} />
              {curves.length === 0 && (
                <p className="pdos-chart__empty">左侧至少勾选一条曲线</p>
              )}
            </div>
          </div>
        )}
        {status === 'idle' && !view && (
          <div className="pdos-progress">
            <Spin size="small" />
            <span>准备中…</span>
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
