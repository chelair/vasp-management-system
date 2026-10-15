/**
 * 功函数面板（2026-10-15）：入口在**巡检详情**的「电子结构分析 → 功函数」标签。
 *
 * 链路（用户 `待办.md` 口径）：
 *   ① 前端选方向（默认 **c 轴**，支持 a / b；VASPKIT 的 `-dir` 要的是笛卡尔 x/y/z → a↔x、b↔y、c↔z）；
 *   ② 远端检查 `LOCPOT`/`OUTCAR` 存在非零、**所选方向有没有开偶极矫正**
 *      （`LDIPOL=.TRUE.` 且 `IDIPOL` 匹配：a→1、b→2、c→3、4=全方向）—— 没开只**警告**不拦；
 *   ③ 远端 VASPKIT 426 提平面平均电位（写 `PLANAR_AVERAGE.dat`，约 8 KB）；
 *   ④ 回传后本地解析：**功函数 = 真空能级 − E_F**（真空能级优先取 VASPKIT 汇总值）。
 * 出图：电位随轴向距离的曲线 + 真空能级 / E_F 两条水平虚线 + 关键数值卡。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Popconfirm, Segmented, Spin, Tag, Tooltip } from 'antd';
import { CalculatorOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';

import {
  clearWorkFunction,
  fetchWorkFunctionData,
  fetchWorkFunctionStatus,
  triggerWorkFunction,
} from '../../api/jobs';
import type { WorkFunctionData, WorkFunctionStatus } from '../../types';
import useEcharts from '../dashboard/useEcharts';

interface Props {
  taskId: string;
  taskName?: string;
  /** 远端是否具备 LOCPOT（来自 available-analyses；false 时给"缺文件"提示） */
  available?: boolean | null;
}

const AXIS_OPTIONS = [
  { value: 'c', label: 'c 轴（z）' },
  { value: 'a', label: 'a 轴（x）' },
  { value: 'b', label: 'b 轴（y）' },
];

const STATE_LABELS: Record<string, string> = {
  ready: '远端可算（LOCPOT / OUTCAR 齐备）',
  no_locpot: '远端没有 LOCPOT',
  no_outcar: '远端没有 OUTCAR',
  no_vaspkit: '远端找不到 vaspkit',
};

function fmt(value: number | null | undefined, digits = 3): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export default function WorkFunctionPanel({ taskId, taskName, available }: Props) {
  const { message } = App.useApp();
  const [status, setStatus] = useState<WorkFunctionStatus | null>(null);
  const [data, setData] = useState<WorkFunctionData | null>(null);
  const [axis, setAxis] = useState<'a' | 'b' | 'c'>('c');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef<number | null>(null);
  const aliveRef = useRef(true);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadData = useCallback(async () => {
    try {
      const payload = await fetchWorkFunctionData(taskId);
      if (aliveRef.current) {
        setData(payload);
        if (payload.axis) setAxis(payload.axis);
      }
      return payload;
    } catch {
      if (aliveRef.current) setData(null);
      return null;
    }
  }, [taskId]);

  const load = useCallback(
    async (remote: boolean) => {
      try {
        const payload = await fetchWorkFunctionStatus(taskId, { remote });
        if (!aliveRef.current) return null;
        setStatus(payload);
        setError(payload.status === 'failed' ? String(payload.error || '计算失败') : '');
        if (payload.status === 'running') setBusy(true);
        return payload;
      } catch (e) {
        if (aliveRef.current) setError(e instanceof Error ? e.message : '读取功函数状态失败');
        return null;
      } finally {
        if (aliveRef.current) setLoading(false);
      }
    },
    [taskId],
  );

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const payload = await load(false);
      if (!payload) return;
      if (payload.status !== 'running') {
        stopPolling();
        setBusy(false);
        if (payload.status === 'done') {
          message.success('功函数计算完成');
          await load(true);
          await loadData();
        }
      }
    }, 1500);
  }, [load, loadData, message, stopPolling]);

  useEffect(() => {
    aliveRef.current = true;
    (async () => {
      const local = await load(false);
      if (!aliveRef.current) return;
      if (local?.status === 'running') {
        startPolling();
        return;
      }
      if (local?.local?.has_result) {
        await loadData();
      } else if (available !== false) {
        await load(true);
      }
    })();
    return () => {
      aliveRef.current = false;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  const analyze = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      await triggerWorkFunction(taskId, axis);
      message.info(`已开始计算 ${axis} 轴功函数（远端 VASPKIT 426）`);
      await load(false);
      startPolling();
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : '触发失败');
    }
  }, [axis, load, message, startPolling, taskId]);

  const clearAll = useCallback(async () => {
    try {
      await clearWorkFunction(taskId);
      setData(null);
      message.success('已清除本地功函数结果');
      await load(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '清除失败');
    }
  }, [load, message, taskId]);

  const running = status?.status === 'running' || busy;
  const remote = status?.remote;
  const hasLocal = Boolean(status?.local?.has_result);
  const axisDirty = Boolean(data && data.axis && data.axis !== axis);
  const dipole = data?.dipole;
  const vacuum = data?.vacuum_level ?? null;
  const wf = data?.work_function ?? null;
  const efermi = data?.efermi ?? null;

  const option = useMemo(() => {
    const z = data?.z ?? [];
    const potential = data?.potential ?? [];
    const marks = [
      ...(vacuum != null
        ? [
            {
              yAxis: vacuum,
              lineStyle: { type: 'dashed' as const, color: '#E4572E', width: 1.2 },
              label: {
                show: true,
                formatter: `真空能级 ${vacuum.toFixed(3)} eV`,
                color: '#E4572E',
                position: 'insideEndTop' as const,
              },
            },
          ]
        : []),
      ...(efermi != null
        ? [
            {
              yAxis: efermi,
              lineStyle: { type: 'dashed' as const, color: '#2E86DE', width: 1.2 },
              label: {
                show: true,
                formatter: `E_F ${efermi.toFixed(3)} eV`,
                color: '#2E86DE',
                position: 'insideEndBottom' as const,
              },
            },
          ]
        : []),
    ];
    return {
      animation: false,
      grid: { left: 72, right: 26, top: 26, bottom: 48 },
      tooltip: {
        trigger: 'axis' as const,
        valueFormatter: (v: unknown) => `${Number(v).toFixed(3)} eV`,
      },
      xAxis: {
        type: 'value' as const,
        name: 'Distance (Å)',
        nameLocation: 'middle' as const,
        nameGap: 28,
        min: 'dataMin' as const,
        max: 'dataMax' as const,
      },
      yAxis: {
        type: 'value' as const,
        name: 'Potential (eV)',
        scale: true,
        axisLabel: { formatter: (v: number) => v.toFixed(1) },
      },
      series: [
        {
          name: '平面平均电位',
          type: 'line' as const,
          showSymbol: false,
          sampling: 'lttb' as const,
          data: z.map((x, i) => [x, potential[i]] as [number, number]),
          lineStyle: { width: 1.6, color: '#5B8DEF' },
          itemStyle: { color: '#5B8DEF' },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            data: marks,
          },
        },
      ],
    };
  }, [data, vacuum, efermi]);

  const containerRef = useEcharts(option, [option], () => {});

  return (
    <div>
      {available === false && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="远端没有 LOCPOT"
          description="功函数需要静电势 LOCPOT：INCAR 里 LVHAR=.TRUE.（INCAR 页有这一项）后重新算一轮，文件才会写出来。"
        />
      )}

      <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="当前状态">
          {running ? (
            <Tag color="processing">{status?.stage_label || '计算中'}</Tag>
          ) : hasLocal ? (
            <Tag color="success">已完成（本地有 PLANAR_AVERAGE.dat）</Tag>
          ) : (
            <Tag>{STATE_LABELS[String(remote?.state || '')] || (available === false ? '缺 LOCPOT' : '未计算')}</Tag>
          )}
        </Descriptions.Item>
        {remote && (
          <Descriptions.Item label="远端检查">
            {remote.reason || '—'}
            {remote.dipole?.ldipol != null ? (
              <span className="preview-note">
                （INCAR: LDIPOL={remote.dipole.ldipol ? '.TRUE.' : '.FALSE.'}
                {remote.dipole.idipol != null ? `, IDIPOL=${remote.dipole.idipol}` : ''}）
              </span>
            ) : null}
          </Descriptions.Item>
        )}
        {hasLocal && data && (
          <Descriptions.Item label="本地结果">
            {data.axis_cartesian?.toUpperCase()} 方向 · {data.points ?? 0} 个点 ·{' '}
            {data.source}
            {typeof data.elapsed_seconds === 'number' ? ` · 用时 ${data.elapsed_seconds} s` : ''}
          </Descriptions.Item>
        )}
      </Descriptions>

      <div className="wf-toolbar">
        <span className="preview-note">计算方向</span>
        <Segmented
          size="small"
          value={axis}
          onChange={(v) => setAxis(v as 'a' | 'b' | 'c')}
          options={AXIS_OPTIONS}
        />
        <Tooltip title="VASPKIT 的 -dir 参数是笛卡尔方向：a↔x、b↔y、c↔z（斜晶胞时以晶轴对应的笛卡尔方向为准）">
          <span className="preview-note">a↔x · b↔y · c↔z</span>
        </Tooltip>
        <Button
          type="primary"
          size="small"
          icon={<CalculatorOutlined />}
          loading={running}
          onClick={() => void analyze()}
          style={{ marginLeft: 'auto' }}
        >
          {hasLocal ? (axisDirty ? `重算（${axis} 轴）` : '重新计算') : '计算功函数'}
        </Button>
        {hasLocal && (
          <Popconfirm
            title="清除本地功函数结果？"
            description="只删本地 PLANAR_AVERAGE.dat / meta；远端文件不动。"
            okText="清除"
            cancelText="取消"
            onConfirm={() => void clearAll()}
          >
            <Button danger size="small" icon={<DeleteOutlined />}>
              清除
            </Button>
          </Popconfirm>
        )}
        {!running && (
          <Tooltip title="重新探测远端（LOCPOT/OUTCAR/vaspkit/偶极矫正）">
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void load(true)}>
              刷新远端状态
            </Button>
          </Tooltip>
        )}
      </div>

      {running && (
        <div style={{ marginBottom: 12 }}>
          <Spin size="small" /> {status?.stage_label || '处理中…'}
        </div>
      )}

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="功函数链路失败"
          description={error}
          action={
            <Button size="small" onClick={() => void analyze()}>
              重试
            </Button>
          }
        />
      ) : null}

      {hasLocal && data ? (
        <>
          {data.warnings?.length ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="注意"
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {data.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              }
            />
          ) : null}

          <div className="structure-stats" style={{ marginBottom: 12 }}>
            <div className="structure-stat">
              <div className="structure-stat__num">{fmt(wf)}</div>
              <div className="structure-stat__lbl">功函数 (eV)</div>
            </div>
            <div className="structure-stat">
              <div className="structure-stat__num">{fmt(vacuum)}</div>
              <div className="structure-stat__lbl">
                真空能级 (eV)
                {data.vacuum_level_source === 'local' ? ' · 本地估' : ''}
              </div>
            </div>
            <div className="structure-stat">
              <div className="structure-stat__num">{fmt(efermi)}</div>
              <div className="structure-stat__lbl">费米能级 E_F (eV)</div>
            </div>
          </div>

          <p className="preview-note" style={{ marginBottom: 8 }}>
            功函数 = 真空能级 − E_F = {fmt(vacuum)} − ({fmt(efermi)}) = <b>{fmt(wf)} eV</b>
            {data.work_function_vaspkit != null ? `（VASPKIT 汇总 ${fmt(data.work_function_vaspkit)} eV）` : ''}
            {data.plateau
              ? ` · 真空平台取样 ${fmt(data.plateau.start, 2)}–${fmt(data.plateau.end, 2)} Å（波动 ${fmt(
                  data.plateau.spread,
                  2,
                )} eV）`
              : ''}
            {dipole && !dipole.ok ? ` · ⚠ ${dipole.reason}` : ''}
          </p>

          <div className="wf-chart" ref={containerRef} />
          <p className="preview-note" style={{ marginTop: 8 }}>
            {taskName ? `${taskName} · ` : ''}
            曲线 = 沿 {data.axis_cartesian?.toUpperCase()} 方向的平面平均静电势（VASPKIT 426，
            `PLANAR_AVERAGE.dat`）；图中两条水平虚线分别是真空能级与 E_F。
            {data.vaspkit_exe ? ` （vaspkit: ${data.vaspkit_exe}）` : ''}
          </p>
        </>
      ) : loading ? (
        <Spin />
      ) : (
        !running && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              available === false
                ? '远端还没有 LOCPOT：先按上面提示补 LVHAR=.TRUE. 重算'
                : `还没有功函数结果：选好方向后点「计算功函数」（当前选 ${axis} 轴）`
            }
          />
        )
      )}
    </div>
  );
}
