import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import {
  CodeOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type {
  ClusterSnapshot,
  Task,
} from '../../types';
import {
  fetchQueueOptions,
  getRecommendedCores,
  uploadSubmitScript,
} from '../../api/jobs';
import {
  buildVaspLsf,
  DEFAULT_WARN_MINUTES,
  estimateNodes,
  formatWalltime,
  normalizeMinute,
  vaspLsfSections,
} from '../../utils/vaspLsf';
import ClusterNodeBoard, { queuesFromSnapshot } from './ClusterNodeBoard';

interface Props {
  task: Task;
  snapshot: ClusterSnapshot | null;
  loading: boolean;
  onRefresh: () => void;
  /** 写入远端成功后回调（用于刷新本地文件清单） */
  onWritten?: () => void;
}

export default function SubmitScriptPanel({
  task,
  snapshot,
  loading,
  onRefresh,
  onWritten,
}: Props) {
  const { message } = App.useApp();
  /** 组 1：基本作业信息 */
  const [jobName, setJobName] = useState(task.model_name);
  const [queue, setQueue] = useState<string>('');
  const [hours, setHours] = useState<number>(24);
  const [minutes, setMinutes] = useState<number>(0);
  /** 组 2：资源 */
  const [cores, setCores] = useState<number>(24);
  const [ptile, setPtile] = useState<number>(1);
  /** 组 3：软结束模块 */
  const [softKill, setSoftKill] = useState<boolean>(true);
  const [warnMinutes, setWarnMinutes] = useState<number>(DEFAULT_WARN_MINUTES);
  const [writing, setWriting] = useState(false);
  const [script, setScript] = useState<string>('');

  useEffect(() => {
    if (!snapshot) return;
    setQueue((prev) =>
      snapshot.queues.some((q) => q.queue === prev) ? prev : (snapshot.queues[0]?.queue ?? ''),
    );
    // 注意：**不**按推荐值改总核数 —— 规范要求 #BSUB -n 默认 24，
    // 推荐值只在下方的提示里展示；否则快照一刷新就会把用户填的核数冲掉。
  }, [snapshot]);

  const queueOptions = useMemo<{ value: string; label: ReactNode }[]>(() => {
    if (snapshot && snapshot.queues.length > 0) {
      return snapshot.queues.map((q) => ({
        value: q.queue,
        label: (
          <span>
            <strong>{q.queue}</strong>
            <span className="preview-note" style={{ marginLeft: 8 }}>
              {q.walltime} · {q.coresPerNode}核/节点{q.paid ? ` · ${q.price}元/核时` : ''}
              {q.suspendRisk === 'high' ? ' · 易挂起' : ''}
            </span>
          </span>
        ),
      }));
    }
    return fetchQueueOptions('lsf').map((q) => ({
      value: q.value,
      label: `${q.label}${q.hint ? `（${q.hint}）` : ''}`,
    }));
  }, [snapshot]);

  /** 节点看板数据：ClusterSnapshot → 队列（每队列一行，格 = 节点） */
  const boardQueues = useMemo(() => queuesFromSnapshot(snapshot), [snapshot]);

  /** 队列节点规格：每节点核数默认从队列带出 */
  const queueSpec = snapshot?.queues.find((q) => q.queue === queue);
  useEffect(() => {
    if (queueSpec?.coresPerNode) setPtile(queueSpec.coresPerNode);
  }, [queueSpec?.coresPerNode, queue]);

  const opts = useMemo(
    () => ({
      jobName: jobName.trim() || task.model_name,
      queue,
      walltime: formatWalltime(hours, normalizeMinute(minutes)),
      cores,
      coresPerNode: ptile,
      softKill,
      warnMinutes,
    }),
    [jobName, task.model_name, queue, hours, minutes, cores, ptile, softKill, warnMinutes],
  );

  /** 截止时间非法（0:00）时阻止写入 */
  const walltimeInvalid = normalizeMinute(minutes) === 0 && Math.trunc(hours) === 0;
  const plannedNodes = estimateNodes(cores, ptile);
  /** 预警时间不小于截止时间时给非阻塞提醒（LSF 到点前 N 分钟才发 SIGURG） */
  const warnTooLate =
    softKill && warnMinutes > Math.trunc(hours) * 60 + normalizeMinute(minutes);

  const generate = () => {
    if (walltimeInvalid) {
      message.error('截止时间不能为 0:00，请填写小时或分钟');
      return;
    }
    setScript(buildVaspLsf(opts));
    message.success('已按 8 段模板生成 vasp.lsf');
  };

  const writeRemote = async () => {
    if (walltimeInvalid) {
      message.error('截止时间不能为 0:00，请填写小时或分钟');
      return;
    }
    const content = script.trim() ? script : buildVaspLsf(opts);
    setWriting(true);
    try {
      const r = await uploadSubmitScript(task.task_id, { content });
      setScript(content);
      message.success(
        `vasp.lsf 已写入 ${r.dir}`
          + (r.backup_file ? `（原文件备份为 ${r.backup_file}）` : ''),
      );
      onWritten?.();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '写入远端 vasp.lsf 失败');
    } finally {
      setWriting(false);
    }
  };

  return (
    <div className="job-panel">
      <div className="cluster-board-bar">
        <span className="cluster-board-bar__meta">
          <DatabaseOutlined />
          <span className="preview-note" style={{ marginLeft: 8 }}>
            {snapshot
              ? `${snapshot.nodes.length} 节点 · 查询于 ${
                  snapshot.queriedAt ? snapshot.queriedAt.replace('T', ' ').slice(5, 19) : '—'
                }`
              : '查询中…'}
          </span>
        </span>
        <span className="header-actions">
          {snapshot &&
            (snapshot.source === 'real' && !snapshot.stale ? (
              <Tag color="success" icon={<ThunderboltOutlined />}>
                  实时数据
              </Tag>
            ) : snapshot.source === 'real' ? (
              <Tooltip title={`这次采集失败，显示的是上次成功采集的数据：${snapshot.error ?? ''}`}>
                <Tag color="warning">缓存数据</Tag>
              </Tooltip>
            ) : (
              <Tooltip title={snapshot.error ?? 'SSH 未连接，使用模拟负载'}>
                <Tag color="warning">模拟数据</Tag>
              </Tooltip>
            ))}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={onRefresh}
          >
            刷新
          </Button>
        </span>
      </div>

      {snapshot?.source === 'mock' && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 14 }}
          message="当前显示模拟负载数据"
          description={
            snapshot?.error
              ? `查询真实节点失败：${snapshot.error}。请确认 SSH 已连接后刷新。`
              : 'SSH 未连接或后端不可用，节点占用为按映射生成的模拟值，仅用于界面预览。'
          }
        />
      )}

      {loading && !snapshot ? (
        <Card size="small" className="job-card">
          <Skeleton active paragraph={{ rows: 4 }} />
        </Card>
      ) : (
        <ClusterNodeBoard
          queues={boardQueues}
          cacheMinutes={Math.max(
            1,
            Math.round((snapshot?.cacheTtlSeconds ?? 300) / 60),
          )}
          cacheAgeSeconds={snapshot?.cacheAgeSeconds ?? 0}
        />
      )}

      <Card size="small" title="作业脚本参数（vasp.lsf）" className="job-card mt-16">
        <div className="lsf-form">
          <div className="lsf-group">
            <div className="lsf-group__head">
              ① 基本作业信息
              <span className="lsf-group__hint">#BSUB -J / -q / -W</span>
            </div>
            <div className="lsf-grid">
              <div className="lsf-field">
                <span className="lsf-field__label">任务名称</span>
                <Input
                  value={jobName}
                  onChange={(e) => setJobName(e.target.value)}
                  placeholder="任务名称（#BSUB -J）"
                />
              </div>
              <div className="lsf-field">
                <span className="lsf-field__label">队列</span>
                <Select value={queue} onChange={setQueue} options={queueOptions} />
                <span className="lsf-field__hint">
                  {queueSpec
                    ? `${queueSpec.walltime} · ${queueSpec.coresPerNode} 核/节点`
                    : '按队列节点规格带出每节点核数'}
                </span>
              </div>
              <div className="lsf-field">
                <span className="lsf-field__label">截止时间（小时 : 分钟）</span>
                <div className="lsf-field__inline">
                  <InputNumber
                    min={0}
                    max={999}
                    step={1}
                    value={hours}
                    onChange={(v) => setHours(v ?? 0)}
                    style={{ width: 76 }}
                    aria-label="截止小时"
                  />
                  <span className="lsf-colon">:</span>
                  <InputNumber
                    min={0}
                    max={59}
                    step={5}
                    value={minutes}
                    onChange={(v) => setMinutes(normalizeMinute(v))}
                    onBlur={() => setMinutes((m) => normalizeMinute(m))}
                    formatter={(v) =>
                      v === undefined || v === null ? '' : String(v).padStart(2, '0')
                    }
                    parser={(v) => normalizeMinute(Number((v ?? '').replace(/[^\d]/g, '')))}
                    style={{ width: 76 }}
                    aria-label="截止分钟"
                  />
                  <span className="lsf-field__hint">
                    #BSUB -W {formatWalltime(hours, normalizeMinute(minutes))}
                    {walltimeInvalid ? ' · 不能为 0:00' : ''}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="lsf-group">
            <div className="lsf-group__head">
              ② 资源
              <span className="lsf-group__hint">{'#BSUB -n / -R "span[ptile=X]"'}</span>
            </div>
            <div className="lsf-grid">
              <div className="lsf-field">
                <span className="lsf-field__label">总核数</span>
                <InputNumber
                  min={1}
                  max={512}
                  value={cores}
                  onChange={(v) => setCores(v ?? 24)}
                />
                <span className="lsf-field__hint">
                  推荐 {snapshot ? getRecommendedCores(snapshot.nodes) : '—'} 核（健康节点最大空闲核数）
                </span>
              </div>
              <div className="lsf-field">
                <span className="lsf-field__label">每节点核数</span>
                <InputNumber min={1} max={128} value={ptile} onChange={(v) => setPtile(v ?? 1)} />
                <span className="lsf-field__hint">
                  {`#BSUB -R "span[ptile=${ptile}]"（默认取队列规格）`}
                </span>
              </div>
              <div className="lsf-field">
                <span className="lsf-field__label">节点估算</span>
                <div className="lsf-field__value">将分配 {plannedNodes} 个节点</div>
                <span className="lsf-field__hint">
                  {`ceil(${cores} / ${ptile})，不整除时由 LSF 自行分配`}
                </span>
              </div>
            </div>
          </div>

          <div className="lsf-group">
            <div className="lsf-group__head">
              ③ 软结束模块
              <span className="lsf-group__hint">#BSUB -wt / -wa + lsf_watcher</span>
            </div>
            <div className="lsf-grid">
              <div className="lsf-field">
                <span className="lsf-field__label">开关</span>
                <div className="lsf-field__inline">
                  <Switch
                    checked={softKill}
                    onChange={setSoftKill}
                    checkedChildren="开"
                    unCheckedChildren="关"
                  />
                  <span className="lsf-field__hint">
                    {softKill ? '生成 lsf_watcher 段与收尾 kill' : '三处内容全部不生成'}
                  </span>
                </div>
              </div>
              <div className="lsf-field">
                <span className="lsf-field__label">预警时间（分钟）</span>
                <InputNumber
                  min={1}
                  max={999}
                  step={5}
                  value={warnMinutes}
                  disabled={!softKill}
                  onChange={(v) =>
                    setWarnMinutes(
                      Math.min(999, Math.max(1, Math.trunc(v ?? DEFAULT_WARN_MINUTES))),
                    )
                  }
                  aria-label="软结束预警时间（分钟）"
                />
                <span className="lsf-field__hint">
                  {`#BSUB -wt ${warnMinutes} · -wa URG`}
                  {warnTooLate && softKill
                    ? ` · 已不小于截止时间 ${formatWalltime(hours, normalizeMinute(minutes))}`
                    : ''}
                </span>
              </div>
            </div>
          </div>

          <div className="lsf-actions">
            <span className="lsf-field__label">远程目录</span>
            <code className="path-cell">{task.remote_dir}</code>
            <span className="lsf-actions__spacer" />
            <Button icon={<CodeOutlined />} onClick={generate}>
              生成预览
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={writing}
              disabled={walltimeInvalid}
              onClick={() => void writeRemote()}
            >
              写入远端 vasp.lsf
            </Button>
          </div>
        </div>
      </Card>

      <Card
        size="small"
        title="vasp.lsf 预览（8 段）"
        className="job-card mt-16"
        extra={<span className="preview-note">写入远端时同名文件先备份为 old_vasp.lsf</span>}
      >
        {script ? (
          <>
            <div className="vasp-lsf-legend">
              {vaspLsfSections(opts).map((s) => (
                <span
                  key={s.id}
                  className={`vasp-lsf-chip vasp-lsf-chip--${s.kind}${s.text ? '' : ' is-off'}`}
                >
                  {s.label} {s.title}
                </span>
              ))}
            </div>
            <Input.TextArea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              autoSize={{ minRows: 12, maxRows: 26 }}
              spellCheck={false}
              className="job-script-editor"
            />
            <div className="preview-note" style={{ marginTop: 8 }}>
              #BSUB 指令必须顶格且不写变量；写入远端后点击「提交」由后端在远端目录执行
              <code> bsub &lt; vasp.lsf</code>。
            </div>
          </>
        ) : (
          <div className="job-empty-hint">填好三组参数后点「生成预览」或直接「写入远端 vasp.lsf」。</div>
        )}
      </Card>
    </div>
  );
}
