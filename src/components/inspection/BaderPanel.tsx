/**
 * Bader 电荷面板（2026-10-14）：入口在**巡检详情**的「电子结构分析 → Bader」标签。
 *
 * 本轮只做**处理链路**（用户口径："先写处理链路，后面写分析链路"）：
 *   ① 远端校验 AECCAR0/1/2 是否存在、大小差别 < 1%
 *   ② 远端 `chgsum.pl AECCAR0 AECCAR2` → `CHGCAR_sum`（已有就跳过）
 *   ③ 远端 `bader CHGCAR -ref CHGCAR_sum`（**耗时可能较长**）→ `ACF.dat`
 *   ④ 回传并本地解析 → 这里展示**原子电荷表**（Bader 电荷 / 到最近表面距离 / 原子体积）
 *
 * **还没做**（分析链路，下一轮）：净电荷（要 POTCAR 的 ZVAL，Δq = ZVAL − Bader 电荷）、
 * 按元素/原子分组统计、图表、写进报告。
 *
 * 中断补偿同差分电荷：远端已有 ACF.dat 就只回传；本地已有就只解析，不重跑。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Popconfirm,
  Segmented,
  Spin,
  Table,
  Tag,
  Tooltip,
} from 'antd';
import { DeleteOutlined, ExperimentOutlined, ReloadOutlined } from '@ant-design/icons';

import {
  clearBader,
  fetchBaderData,
  fetchBaderStatus,
  fetchTaskInput,
  triggerBader,
} from '../../api/jobs';
import { parseCif } from '../../utils/structure3d';
import type { BaderAtom, BaderData, BaderStatus } from '../../types';
import Structure3DFrame, { type AtomRef } from '../jobs/Structure3DFrame';

interface Props {
  taskId: string;
  taskName?: string;
  /** 远端是否具备 AECCAR（来自 available-analyses；false 时给"缺文件"提示） */
  available?: boolean | null;
}

const STATE_LABELS: Record<string, string> = {
  ready: '远端可算（AECCAR 齐全、大小一致）',
  remote_acf: '远端已有 ACF.dat（回传即可）',
  incomplete: '远端 AECCAR 不完整',
  no_bader: '远端找不到 bader 可执行文件',
  no_chgsum: '远端找不到 chgsum.pl',
  local: '本地已有结果（只重新解析）',
};

function fmt(value: number | null | undefined, digits = 4): string {
  return value == null ? '—' : value.toFixed(digits);
}

export default function BaderPanel({ taskId, taskName, available }: Props) {
  const { message } = App.useApp();
  const [status, setStatus] = useState<BaderStatus | null>(null);
  const [data, setData] = useState<BaderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  /** 结构预览用的结构（含 POSCAR/CONTCAR 的 CIF；ele 任务的巡检详情里没有 analysis，走 /input） */
  const [cifState, setCifState] = useState<{ poscar: string | null; contcar: string | null }>({
    poscar: null,
    contcar: null,
  });
  const [structureView, setStructureView] = useState<'contcar' | 'poscar'>('contcar');
  const [selectedAtoms, setSelectedAtoms] = useState<AtomRef[]>([]);
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
      const payload = await fetchBaderData(taskId);
      if (aliveRef.current) setData(payload);
    } catch {
      if (aliveRef.current) setData(null);
    }
  }, [taskId]);

  /** 结构预览：本地 POSCAR/CONTCAR 的 CIF（ele 详情没有 analysis，这里走 /input，纯本地读文件） */
  useEffect(() => {
    let alive = true;
    fetchTaskInput(taskId)
      .then((state) => {
        if (alive) {
          setCifState({ poscar: state.poscar_cif ?? null, contcar: state.contcar_cif ?? null });
        }
      })
      .catch(() => {
        /* 取不到结构就不显示预览，不影响 Bader 结果本身 */
      });
    return () => {
      alive = false;
    };
  }, [taskId]);

  const load = useCallback(
    async (remote: boolean) => {
      try {
        const payload = await fetchBaderStatus(taskId, { remote });
        if (!aliveRef.current) return null;
        setStatus(payload);
        setError(payload.status === 'failed' ? String(payload.error || '计算失败') : '');
        if (payload.status === 'running') setBusy(true);
        return payload;
      } catch (e) {
        if (aliveRef.current) setError(e instanceof Error ? e.message : '读取 Bader 状态失败');
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
          message.success('Bader 分析完成');
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
      if (local?.local?.has_acf) {
        await loadData();
      } else if (available !== false) {
        await load(true); // 本地没有 → 探一次远端，给出"能不能算"
      }
    })();
    return () => {
      aliveRef.current = false;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  const analyze = useCallback(
    async (force: boolean) => {
      setBusy(true);
      setError('');
      try {
        await triggerBader(taskId, { force });
        message.info(force ? '已重新开始 Bader 分析' : '已开始 Bader 分析');
        await load(false);
        startPolling();
      } catch (e) {
        setBusy(false);
        setError(e instanceof Error ? e.message : '触发失败');
      }
    },
    [load, message, startPolling, taskId],
  );

  const clearAll = useCallback(async () => {
    try {
      await clearBader(taskId);
      setData(null);
      message.success('已清除本地 Bader 结果');
      await load(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '清除失败');
    }
  }, [load, message, taskId]);

  const running = status?.status === 'running' || busy;
  const hasLocal = Boolean(status?.local?.has_acf);
  const remote = status?.remote;
  const stateLabel = STATE_LABELS[String(remote?.state || '')] || '';
  const activeView: 'contcar' | 'poscar' =
    structureView === 'contcar' && !cifState.contcar ? 'poscar' : structureView;
  const activeCif = (activeView === 'contcar' ? cifState.contcar : cifState.poscar) ?? null;
  /** 结构预览里的 CIF 原子数（用来确认与 ACF.dat 是同一份结构） */
  const cifAtoms = useMemo(() => {
    if (!activeCif) return 0;
    try {
      return parseCif(activeCif)?.atoms.length ?? 0;
    } catch {
      return 0;
    }
  }, [activeCif]);
  /**
   * 逐原子读数（点原子看 Bader 电荷）。**坐标口径**：ACF.dat 的行序 = POSCAR 原子序（1 起），
   * 而 3D 框按 CIF 下标（0 起）取值 → 这里做 -1 换算；原子数对不上就整块不挂（避免错位）。
   */
  const atomReadouts = useMemo(() => {
    if (!data || !activeCif) return null;
    if (cifAtoms && cifAtoms !== data.n_atoms) return null;
    const map: Record<number, string> = {};
    for (const atom of data.atoms) {
      const parts = [`q ${atom.charge.toFixed(6)} e`];
      if (atom.min_dist != null) parts.push(`dmin ${atom.min_dist.toFixed(3)} Å`);
      if (atom.atomic_vol != null) parts.push(`V ${atom.atomic_vol.toFixed(2)} Å³`);
      map[atom.index - 1] = parts.join('  ·  ');
    }
    return map;
  }, [data, activeCif, cifAtoms]);
  const atomCountMismatch = Boolean(data && activeCif && !atomReadouts);
  const result = (status?.result || (data?.meta?.result as Record<string, unknown>) || {}) as Record<
    string,
    unknown
  >;

  return (
    <div>
      {available === false && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="远端没有 AECCAR0/1/2"
          description="Bader 需要芯电荷 AECCAR0 / 价电荷 AECCAR2：INCAR 里加 LAECHG=.TRUE. 后重新算一轮，文件才会写出来。"
        />
      )}

      <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="当前状态">
          {running ? (
            <Tag color="processing">{status?.stage_label || '计算中'}</Tag>
          ) : hasLocal ? (
            <Tag color="success">已完成（本地有 ACF.dat）</Tag>
          ) : (
            <Tag>{stateLabel || (available === false ? '缺 AECCAR' : '未计算')}</Tag>
          )}
        </Descriptions.Item>
        {remote && (
          <Descriptions.Item label="远端检查">
            {remote.reason || stateLabel || '—'}
            {remote.bader_exe ? (
              <span className="preview-note"> （bader: {remote.bader_exe}）</span>
            ) : null}
          </Descriptions.Item>
        )}
        {hasLocal && data && (
          <Descriptions.Item label="本地结果">
            ACF.dat · {data.n_atoms} 个原子 · 总电荷 {fmt(data.total_charge, 6)}
            {data.n_electrons != null ? ` · 电子数 ${fmt(data.n_electrons, 4)}` : ''}
            {typeof result.elapsed_seconds === 'number'
              ? ` · 用时 ${result.elapsed_seconds} s`
              : ''}
          </Descriptions.Item>
        )}
      </Descriptions>

      <p className="preview-note" style={{ marginBottom: 12 }}>
        点击后依次执行：远端校验 AECCAR0/1/2（大小差别 &lt; 1%）→
        在子目录里 <code>chgsum.pl AECCAR0 AECCAR2</code> 生成 <b>Bader 自己的</b>参考电荷
        <code>CHGCAR_sum_aec</code>（<b>不碰</b>目录里那份差分电荷留下的 <code>CHGCAR_sum</code>）→
        <code>bader CHGCAR -ref CHGCAR_sum_aec</code>（这一步可能跑很久）→ 回传
        <code>ACF.dat</code> 并解析。远端已有 ACF.dat 就只回传、本地已有就只解析，不会重复算。
        <br />
        <span className="preview-note">
          本轮先给 <b>Bader 原始电荷</b>；<b>净电荷 Δq = ZVAL − 电荷</b>、按元素分组与图表属于分析链路，下一轮再做。
        </span>
      </p>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <Button
          type="primary"
          icon={<ExperimentOutlined />}
          loading={running}
          onClick={() => void analyze(hasLocal)}
        >
          {hasLocal ? '重新计算（含重跑 bader）' : busy ? '计算中…' : '计算 Bader 电荷'}
        </Button>
        {hasLocal && (
          <Popconfirm
            title="清除本地 Bader 结果？"
            description="只删本地 ACF.dat / meta；远端文件不动，重新点击会重新回传。"
            okText="清除"
            cancelText="取消"
            onConfirm={() => void clearAll()}
          >
            <Button danger icon={<DeleteOutlined />}>
              清除本地结果
            </Button>
          </Popconfirm>
        )}
        {!running && (
          <Tooltip title="重新探测远端（AECCAR / bader / 远端 ACF.dat）">
            <Button icon={<ReloadOutlined />} onClick={() => void load(true)}>
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
          message="Bader 链路失败"
          description={error}
          action={
            <Button size="small" onClick={() => void analyze(false)}>
              重试
            </Button>
          }
        />
      ) : null}

      {hasLocal && data ? (
        <>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 8 }}>
            <span>
              原子数：<b>{data.n_atoms}</b>
            </span>
            <span>
              总电荷：<b>{fmt(data.total_charge, 6)}</b> e
            </span>
            {data.n_electrons != null && (
              <span>
                电子数：<b>{fmt(data.n_electrons, 4)}</b>
              </span>
            )}
            {data.vacuum_charge != null && (
              <span>
                VACUUM CHARGE：<b>{fmt(data.vacuum_charge, 4)}</b>
              </span>
            )}
            {data.vacuum_volume != null && (
              <span>
                VACUUM VOLUME：<b>{fmt(data.vacuum_volume, 4)}</b>
              </span>
            )}
          </div>
          <div className="structure-panel__section-title">结构预览 · 逐原子 Bader 电荷</div>
          {activeCif ? (
            <>
              <Structure3DFrame
                cif={activeCif}
                height={420}
                selected={selectedAtoms}
                atomReadouts={atomReadouts}
                atomReadoutTitle="选中原子 · Bader 电荷"
                showSelectedCoords
                onClickAtom={(atom, additive) =>
                  setSelectedAtoms((prev) => {
                    if (!additive) return [atom];
                    const exists = prev.some((x) => x.index === atom.index);
                    return exists
                      ? prev.filter((x) => x.index !== atom.index)
                      : [...prev, atom];
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
                toolbarExtra={
                  cifState.poscar && cifState.contcar ? (
                    <Segmented
                      size="small"
                      value={activeView}
                      onChange={(v) => setStructureView(v as 'contcar' | 'poscar')}
                      options={[
                        { label: '优化后（CONTCAR）', value: 'contcar' },
                        { label: '初始（POSCAR）', value: 'poscar' },
                      ]}
                    />
                  ) : null
                }
              />
              <p className="preview-note" style={{ marginTop: 6, marginBottom: 10 }}>
                在结构上<b>点原子</b>（或 Ctrl 多选 / Shift 框选）看它的 Bader 电荷；当前
                <b>只显示数值、不着色</b>（按元素配色）。按数值着色、按元素分组统计属于分析链路，下一轮做。
                {atomCountMismatch
                  ? ' ⚠ 结构原子数与 ACF.dat 对不上，暂不挂电荷读数（先确认两边是同一份结构）。'
                  : ''}
              </p>
            </>
          ) : (
            <p className="preview-note" style={{ marginBottom: 10 }}>
              本地还没有可预览的结构（POSCAR/CONTCAR 未同步到本地），只能看下面的表。
            </p>
          )}
          <Table<BaderAtom>
            size="small"
            rowKey="index"
            dataSource={data.atoms}
            pagination={{ pageSize: 20, showSizeChanger: false, size: 'small' }}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '#', dataIndex: 'index', width: 64, fixed: 'left' },
              {
                title: 'Bader 电荷 (e)',
                dataIndex: 'charge',
                width: 140,
                render: (value: number) => <b>{fmt(value, 6)}</b>,
              },
              {
                title: '最近表面距离 (Å)',
                dataIndex: 'min_dist',
                width: 150,
                render: (value: number | null | undefined) => fmt(value, 4),
              },
              ...(data.has_atomic_vol
                ? [
                    {
                      title: '原子体积 (Å³)',
                      dataIndex: 'atomic_vol',
                      width: 130,
                      render: (value: number | null | undefined) => fmt(value, 4),
                    },
                  ]
                : []),
              { title: 'x (Å)', dataIndex: 'x', render: (value: number) => fmt(value, 4) },
              { title: 'y (Å)', dataIndex: 'y', render: (value: number) => fmt(value, 4) },
              { title: 'z (Å)', dataIndex: 'z', render: (value: number) => fmt(value, 4) },
            ]}
          />
          <p className="preview-note" style={{ marginTop: 8 }}>
            {taskName ? `${taskName} · ` : ''}以上是 bader 的 ACF.dat 原样解析（
            {data.has_min_dist ? '含 MIN DIST' : '无 MIN DIST 列'}
            {data.has_atomic_vol ? ' / 含 ATOMIC VOL 列' : ''}）。净电荷与分组统计待分析链路。
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
                ? '远端还没有 AECCAR0/1/2：先按上面提示补 LAECHG 重算'
                : '还没有 Bader 结果：点上面的「计算 Bader 电荷」'
            }
          />
        )
      )}
    </div>
  );
}
