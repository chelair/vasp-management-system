/**
 * 报告里的「电子结构」交互组件（2026-10-15，v0.9.61）。
 *
 * 后端在 Markdown 里留**挂点行** `@[kind:task_id]`（见 report_builder 的电子结构章节），
 * 报告页把挂点 div 用 portal 挂上这里的三个组件 —— 与导出的单文件 HTML 一一对应：
 *
 *   @[bader-table:xxx]         → BaderFullTable（折叠报表，完整逐原子表）
 *   @[pdos-chart:xxx]          → PdosReportChart（点击加载 → 复用巡检同款原生控件 + 内核）
 *   @[work-function-chart:xxx] → WorkFunctionReportChart（平面平均电位曲线，数值内联在报告里）
 *
 * PDOS 走"点击加载"：整合数据 1~3 MB，进报告就自动拉会拖慢打开（与巡检详情同一取舍）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Table, Tag } from 'antd';

import { fetchPdosData } from '../../api/jobs';
import { mountPdosWidget, type PdosWidgetHandle } from '../../interactive/pdosWidget';
import { downloadWorkFunctionData } from '../../interactive/workFunctionWidget';
import useEcharts from '../dashboard/useEcharts';

/** 逐原子 Bader 数据（后端 `bader_summary.atoms`） */
export interface BaderAtom {
  index: number;
  element?: string;
  charge?: number | null;
  zval?: number | null;
  net_charge?: number | null;
}

/**
 * Bader 完整表：**直接展示全部原子**，放在一个可滚动的容器里
 * （2026-10-15 用户口径："Bader 直接展示完整表格，但是放在一个容器中可滑动查看"）。
 *
 * 实现：不分页（全部行都在 DOM 里）+ 表格表体自己滚动（表头固定），
 * 窄屏时横向可滑动；外层卡片只负责边框与标题。
 */
export function BaderFullTable({ atoms, taskName }: { atoms: BaderAtom[]; taskName?: string }) {
  const columns = useMemo(
    () => [
      {
        title: '原子',
        dataIndex: 'label',
        key: 'label',
        width: 96,
        render: (value: string) => <strong>{value}</strong>,
      },
      { title: '元素', dataIndex: 'element', key: 'element', width: 72 },
      {
        title: 'Bader 电荷 (e)',
        dataIndex: 'charge',
        key: 'charge',
        render: (v: number | null) => (v == null ? '—' : v.toFixed(4)),
      },
      {
        title: 'ZVAL (e)',
        dataIndex: 'zval',
        key: 'zval',
        render: (v: number | null) => (v == null ? '—' : v.toFixed(2)),
      },
      {
        title: '净电荷 Δq (e)',
        dataIndex: 'net_charge',
        key: 'net_charge',
        defaultSortOrder: 'descend' as const,
        sorter: (a: BaderAtom, b: BaderAtom) =>
          Math.abs(a.net_charge ?? 0) - Math.abs(b.net_charge ?? 0),
        render: (v: number | null) =>
          v == null ? (
            '—'
          ) : (
            <span
              style={{ color: v >= 0 ? '#C0392B' : '#2C7BE5', fontVariantNumeric: 'tabular-nums' }}
            >
              {v >= 0 ? '+' : ''}
              {v.toFixed(4)}
            </span>
          ),
      },
    ],
    [],
  );
  const data = useMemo(
    () =>
      atoms.map((atom) => ({
        ...atom,
        key: String(atom.index),
        label: `${atom.element ?? ''}${atom.index}`,
      })),
    [atoms],
  );
  if (!atoms.length) return null;
  return (
    <div className="report-bader">
      <div className="report-bader__head">
        <span className="report-bader__title">逐原子 Bader 电荷（完整表）</span>
        <span className="report-bader__meta">
          共 {atoms.length} 个原子
          {taskName ? <Tag style={{ marginLeft: 8 }}>{taskName}</Tag> : null}
        </span>
      </div>
      {/* 可滑动容器：表体在容器内滚动（表头固定），窄屏横向可滑动 */}
      <div className="report-bader__scroll">
        <Table
          size="small"
          rowKey="key"
          columns={columns as never}
          dataSource={data as never}
          pagination={false}
          scroll={{ x: 620 }}
        />
      </div>
    </div>
  );
}

/** 功函数结果（后端 `work_function_summary`；曲线数值内联，无需额外请求） */
export interface WorkFunctionSummary {
  task_id?: string;
  axis?: string;
  axis_cartesian?: string;
  efermi?: number | null;
  vacuum_level?: number | null;
  vacuum_level_source?: string;
  work_function?: number | null;
  points?: number;
  warnings?: string[];
  z?: number[];
  potential?: number[];
}

/** 功函数：平面平均电位曲线（真空能级 / E_F 两条标记线）+ 关键数值卡 */
export function WorkFunctionReportChart({
  summary,
  taskName,
}: {
  summary: WorkFunctionSummary;
  taskName?: string;
}) {
  const z = summary.z ?? [];
  const potential = summary.potential ?? [];
  const option = useMemo(
    () => ({
      animation: false,
      grid: { left: 62, right: 90, top: 26, bottom: 42 },
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'cross' as const },
        confine: true,
      },
      xAxis: {
        type: 'value' as const,
        name: 'z (Å)',
        nameLocation: 'middle' as const,
        nameGap: 26,
        axisLine: { onZero: false },
        axisLabel: { onZero: false },
      },
      yAxis: {
        type: 'value' as const,
        name: '静电势 (eV)',
        nameLocation: 'middle' as const,
        nameRotate: 90,
        nameGap: 46,
        axisLine: { onZero: false },
        axisLabel: { onZero: false },
      },
      series: [
        {
          name: '平面平均电位',
          type: 'line' as const,
          showSymbol: false,
          sampling: 'lttb' as const,
          lineStyle: { width: 1.6, color: '#5B8DEF' },
          itemStyle: { color: '#5B8DEF' },
          data: z.map((value, index) => [value, potential[index]]),
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: true, position: 'insideEndTop' as const, fontSize: 11 },
            data: [
              ...(summary.vacuum_level != null
                ? [
                    {
                      yAxis: summary.vacuum_level,
                      lineStyle: { type: 'dashed' as const, color: '#2C9DA8' },
                      label: {
                        formatter: `真空能级 ${summary.vacuum_level.toFixed(3)} eV`,
                        color: '#2C9DA8',
                      },
                    },
                  ]
                : []),
              ...(summary.efermi != null
                ? [
                    {
                      yAxis: summary.efermi,
                      lineStyle: { type: 'dashed' as const, color: '#E8A33D' },
                      label: { formatter: `E_F ${summary.efermi.toFixed(3)} eV`, color: '#E8A33D' },
                    },
                  ]
                : []),
            ],
          },
        },
      ],
    }),
    [z, potential, summary.vacuum_level, summary.efermi],
  );
  const containerRef = useEcharts(option, [option]);
  return (
    <div className="report-wf">
      <div className="report-wf__cards">
        <span className="report-wf__card">
          真空能级 <strong>{summary.vacuum_level?.toFixed(4) ?? '—'}</strong> eV
          <em>{summary.vacuum_level_source === 'vaspkit' ? 'VASPKIT 汇总' : '本地平台估计'}</em>
        </span>
        <span className="report-wf__card">
          E_F <strong>{summary.efermi?.toFixed(4) ?? '—'}</strong> eV
        </span>
        <span className="report-wf__card report-wf__card--key">
          功函数 <strong>{summary.work_function?.toFixed(4) ?? '—'}</strong> eV
        </span>
        <span className="report-wf__card">
          方向 <strong>{summary.axis ?? '—'}</strong> ↗ {summary.axis_cartesian ?? '—'}
        </span>
        {taskName ? <span className="report-wf__card">{taskName}</span> : null}
        {/* 数据导出（csv / txt）：与原生版（导出 HTML 里用的那份）共用同一实现 */}
        <span className="report-wf__actions">
          <Button size="small" onClick={() => downloadWorkFunctionData(summary, 'csv')}>
            导出 CSV
          </Button>
          <Button size="small" onClick={() => downloadWorkFunctionData(summary, 'txt')}>
            导出 TXT
          </Button>
        </span>
      </div>
      <div style={{ height: 300 }} ref={containerRef} />
      {/* 警告不进报告（2026-10-15 用户："报告不出现警告和提示，报告是给客户看的"）：
          真空能级交叉校验等提示只在巡检详情面板与结构化数据（work_function_summary.warnings）里看 */}
    </div>
  );
}

/**
 * PDOS 交互图：**进报告就直接显示交互图**（不用点按钮、也不等滚动）——
 * 组件一挂载就拉数据并挂载组件（数据 1~3 MB，局域网里很快）。
 *
 * 页面上**看不到后端那张静态兜底图**：它在报告页里被标了 `.report-static-fallback`
 * （屏幕隐藏、打印/PDF 才显示），所以不会出现"先闪一张静态图、滚到了才换成交互图"
 * （2026-10-15 用户反馈的正是这个）。导出的单文件 HTML 仍按老办法：
 * 静态图先显示，运行时挂上组件后再收起（那边没有 JS 保证，必须留兜底）。
 *
 * ⚠️ **宿主 div 里不能渲染任何 React 子节点**：`mountPdosWidget()` 会 `container.innerHTML = ''`
 * 再写自己的 DOM，而 React 如果也往同一节点渲染过内容（例如 loading 的 Spin），
 * 之后 React 要移除它时就会抛 `NotFoundError: The node to be removed is not a child of this node`
 * → **整棵 React 树卸载 = 白屏**（2026-10-15 用户报的"加载后页面空白一片"，已用 jsdom 复现并修掉）。
 * 所以：loading / 错误提示一律放在宿主 **外面**（兄弟节点）。
 */
export function PdosReportChart({
  taskId,
  taskName,
  onLoaded,
}: {
  taskId: string;
  taskName?: string;
  /** 交互图挂好之后回调（报告页用它把上面那张静态图收起来，避免重复显示） */
  onLoaded?: () => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<PdosWidgetHandle | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  /** 只自动加载一次（失败后不再进入"失败→重试→失败"的循环，交给用户点「重试」） */
  const startedRef = useRef(false);

  useEffect(
    () => () => {
      widgetRef.current?.dispose();
      widgetRef.current = null;
    },
    [],
  );

  const load = useCallback(async () => {
    const host = hostRef.current;
    if (!host || loading) return;
    setLoading(true);
    setError('');
    try {
      const view = await fetchPdosData(taskId);
      widgetRef.current?.dispose();
      widgetRef.current = mountPdosWidget(host, view);
      setLoaded(true);
      onLoaded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载 PDOS 数据失败');
    } finally {
      setLoading(false);
    }
  }, [taskId, loading, onLoaded]);

  /** 挂载即加载（不等滚动、不用点按钮） */
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void load();
  }, [load]);

  return (
    <div className="report-pdos" ref={wrapRef}>
      {!loaded && !error && (
        <p className="report-pdos__hint">
          正在加载交互图{taskName ? `（${taskName}）` : ''}…（整合数据约 1–3 MB）
        </p>
      )}
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => void load()} loading={loading}>
              重试
            </Button>
          }
        />
      )}
      {/* 宿主：只由 mountPdosWidget 写 DOM，React 不往里渲染任何子节点（见上方警告） */}
      <div ref={hostRef} className="report-pdos__host" />
    </div>
  );
}
