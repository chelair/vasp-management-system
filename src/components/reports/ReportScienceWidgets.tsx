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
import { Alert, Button, Collapse, Spin, Table, Tag } from 'antd';

import { fetchPdosData } from '../../api/jobs';
import { mountPdosWidget, type PdosWidgetHandle } from '../../interactive/pdosWidget';
import useEcharts from '../dashboard/useEcharts';

/** 逐原子 Bader 数据（后端 `bader_summary.atoms`） */
export interface BaderAtom {
  index: number;
  element?: string;
  charge?: number | null;
  zval?: number | null;
  net_charge?: number | null;
}

/** Bader 完整表：默认折叠（用户口径"数据报表，滑动折叠"），展开后分页浏览 */
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
    <Collapse
      className="report-bader-collapse"
      size="small"
      items={[
        {
          key: 'atoms',
          label: (
            <span>
              完整表（{atoms.length} 个原子）
              {taskName ? <Tag style={{ marginLeft: 8 }}>{taskName}</Tag> : null}
            </span>
          ),
          children: (
            <Table
              size="small"
              rowKey="key"
              columns={columns as never}
              dataSource={data as never}
              scroll={{ x: 560, y: 320 }}
              pagination={{ pageSize: 50, size: 'small', showSizeChanger: false }}
            />
          ),
        },
      ]}
    />
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
      </div>
      <div style={{ height: 300 }} ref={containerRef} />
      {(summary.warnings ?? []).map((warning) => (
        <Alert key={warning} type="warning" showIcon message={warning} style={{ marginTop: 6 }} />
      ))}
    </div>
  );
}

/**
 * PDOS 交互图：**点击才加载**（整合数据 1~3 MB）。加载后挂的是巡检详情同款的
 * 原生控件组件（`interactive/pdosWidget.ts`），交互能力完全一致：勾轨道、改范围、
 * 带中心、只看一条曲线、镜像/叠加。
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
  const widgetRef = useRef<PdosWidgetHandle | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');

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

  return (
    <div className="report-pdos">
      {!loaded && (
        <div className="report-pdos__cta">
          <Button type="primary" size="small" onClick={() => void load()} loading={loading}>
            加载交互图{taskName ? `（${taskName}）` : ''}
          </Button>
          <span className="report-pdos__hint">
            勾选轨道、改能量范围、开关带中心虚线都会实时重画（整合数据约 1–3 MB，点一下才加载；
            上面那张静态图是同一份数据）
          </span>
        </div>
      )}
      {error && <Alert type="error" showIcon message={error} />}
      <div ref={hostRef} className="report-pdos__host">
        {loading && <Spin size="small" />}
      </div>
    </div>
  );
}
