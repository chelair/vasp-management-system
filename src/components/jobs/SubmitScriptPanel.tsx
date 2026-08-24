import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Input,
  InputNumber,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Table,
  Tag,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CodeOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type {
  ClusterNode,
  ClusterQueueSummary,
  ClusterSnapshot,
  JobWorkspace,
  NodeStatus,
  ScriptFormat,
  SuspendRisk,
  Task,
} from '../../types';
import { NODE_STATUS_LABELS } from '../../types';
import {
  fetchQueueOptions,
  generateSubmitScript,
  getRecommendedCores,
} from '../../api/jobs';

interface Props {
  task: Task;
  workspace: JobWorkspace;
  snapshot: ClusterSnapshot | null;
  loading: boolean;
  onRefresh: () => void;
  onSaved: (script: string) => void;
}

const NODE_STATUS_META: Record<NodeStatus, { color: string; tag: string }> = {
  ok: { color: '#1e9e7f', tag: 'success' },
  warning: { color: '#d18a2b', tag: 'warning' },
  busy: { color: '#d9535b', tag: 'error' },
  closed: { color: '#9aa7b8', tag: 'default' },
  unavail: { color: '#7b61d6', tag: 'purple' },
};

const RISK_META: Record<SuspendRisk, { label: string; tag: string }> = {
  low: { label: '挂起风险低', tag: 'success' },
  medium: { label: '挂起风险中', tag: 'warning' },
  high: { label: '易挂起', tag: 'error' },
};

function busyColor(percent: number): string {
  if (percent >= 90) return '#d9535b';
  if (percent >= 70) return '#d18a2b';
  return '#3f6fe0';
}

function QueueSummaryCard({ q }: { q: ClusterQueueSummary }) {
  const bq = q.bqueues && Object.keys(q.bqueues).length > 0 ? q.bqueues : null;
  return (
    <div className="queue-card">
      <div className="queue-card__head">
        <span className="queue-card__name">{q.queue}</span>
        <span>
          {q.paid ? (
            <Tag color="gold">付费 {q.price}元/核时</Tag>
          ) : (
            <Tag color="blue">免费</Tag>
          )}
          <Tag color={RISK_META[q.suspendRisk].tag}>{RISK_META[q.suspendRisk].label}</Tag>
        </span>
      </div>
      <div className="queue-card__stats">
        <div>
          <strong>{q.nodeCount}</strong>
          <span>节点</span>
        </div>
        <div>
          <strong>{q.totalCores}</strong>
          <span>总核</span>
        </div>
        <div>
          <strong style={{ color: 'var(--color-primary-strong)' }}>{q.runningCores}</strong>
          <span>运行</span>
        </div>
        <div>
          <strong style={{ color: 'var(--color-success)' }}>{q.idleCores}</strong>
          <span>空闲</span>
        </div>
      </div>
      <div className="queue-card__bar">
        <Progress
          percent={q.busyPercent}
          size="small"
          strokeColor={busyColor(q.busyPercent)}
          format={(p) => `拥堵 ${p}%`}
        />
      </div>
      <div className="queue-card__meta">
        <span>
          walltime {q.walltime} · {q.coresPerNode}核/节点
        </span>
        <span>
          {q.cpuModel} @ {q.cpuFreq}
        </span>
        {bq && (
          <span>
            运行 {bq.running ?? 0} 作业 · 排队 {bq.pending ?? 0} · 挂起 {bq.suspended ?? 0}
          </span>
        )}
      </div>
    </div>
  );
}

export default function SubmitScriptPanel({
  task,
  workspace,
  snapshot,
  loading,
  onRefresh,
  onSaved,
}: Props) {
  const { message } = App.useApp();
  const [format, setFormat] = useState<ScriptFormat>(workspace.scriptFormat);
  const [jobName, setJobName] = useState(task.model_name);
  const [queue, setQueue] = useState<string>('');
  const [cores, setCores] = useState<number>(1);
  const [script, setScript] = useState<string>('');

  useEffect(() => {
    if (!snapshot) return;
    if (format === 'lsf') {
      setQueue((prev) =>
        snapshot.queues.some((q) => q.queue === prev)
          ? prev
          : (snapshot.queues[0]?.queue ?? ''),
      );
    }
    setCores(getRecommendedCores(snapshot.nodes));
  }, [snapshot, format]);

  const queueOptions = useMemo<{ value: string; label: ReactNode }[]>(() => {
    if (format === 'lsf' && snapshot && snapshot.queues.length > 0) {
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
    return fetchQueueOptions(format).map((q) => ({
      value: q.value,
      label: `${q.label}${q.hint ? `（${q.hint}）` : ''}`,
    }));
  }, [format, snapshot]);

  const onFormatChange = (f: ScriptFormat) => {
    setFormat(f);
    const names =
      f === 'lsf' && snapshot && snapshot.queues.length > 0
        ? snapshot.queues.map((q) => q.queue)
        : fetchQueueOptions(f).map((q) => q.value);
    setQueue(names[0] ?? '');
  };

  const generate = () => {
    const content = generateSubmitScript({
      format,
      jobName: jobName.trim() || task.model_name,
      queue,
      cores,
      remoteDir: task.remote_dir,
    });
    setScript(content);
    message.success('提交脚本已生成，可编辑后保存');
  };

  const save = () => {
    if (!script.trim()) {
      message.warning('请先生成脚本');
      return;
    }
    onSaved(script);
    message.success(`提交脚本已保存：${task.local_dir}/submit.sh`);
  };

  const columns: ColumnsType<ClusterNode> = [
    {
      title: '节点',
      dataIndex: 'name',
      key: 'name',
      width: 96,
      render: (v: string) => <span className="path-cell" style={{ fontSize: 12.5 }}>{v}</span>,
    },
    {
      title: '队列',
      dataIndex: 'queue',
      key: 'queue',
      width: 130,
      render: (v: string) => <Tag color="geekblue">{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 88,
      render: (s: NodeStatus) => (
        <Tag color={NODE_STATUS_META[s].tag}>{NODE_STATUS_LABELS[s]}</Tag>
      ),
    },
    {
      title: 'CPU',
      key: 'cpu',
      width: 150,
      render: (_, n) => (
        <span className="preview-note">
          {n.cpuModel} @ {n.cpuFreq}
        </span>
      ),
    },
    {
      title: '核数（最大 · 运行 · 空闲）',
      key: 'cores',
      minWidth: 210,
      render: (_, n) => {
        const pct = n.maxCores ? Math.round((n.runningCores / n.maxCores) * 100) : 0;
        return (
          <div className="node-core-cell">
            <Progress
              percent={pct}
              size="small"
              strokeColor={busyColor(pct)}
              showInfo={false}
            />
            <div className="node-core-cell__nums">
              <strong>{n.maxCores}</strong>
              <span style={{ color: 'var(--color-primary-strong)' }}>{n.runningCores}</span>
              <span style={{ color: 'var(--color-success)' }}>{n.idleCores}</span>
              {n.suspendedCores > 0 && (
                <Tooltip title={`挂起 ${n.suspendedCores} 核`}>
                  <span style={{ color: 'var(--color-warning)' }}>挂{n.suspendedCores}</span>
                </Tooltip>
              )}
            </div>
          </div>
        );
      },
    },
    {
      title: 'walltime',
      dataIndex: 'walltime',
      key: 'walltime',
      width: 86,
      render: (v: string) => <span className="preview-note">{v}</span>,
    },
    {
      title: '挂起风险',
      dataIndex: 'suspendRisk',
      key: 'suspendRisk',
      width: 100,
      render: (r: SuspendRisk) => <Tag color={RISK_META[r].tag}>{RISK_META[r].label}</Tag>,
    },
    {
      title: '计费',
      dataIndex: 'paid',
      key: 'paid',
      width: 84,
      render: (paid: boolean, n) =>
        paid ? <Tag color="gold">{n.price}元/核时</Tag> : <span className="preview-note">—</span>,
    },
  ];

  return (
    <div className="job-panel">
      <Card
        size="small"
        title={
          <span>
            <DatabaseOutlined /> 队列拥堵情况
            <span className="preview-note" style={{ marginLeft: 10 }}>
              {snapshot
                ? `${snapshot.nodes.length} 节点 · 查询于 ${
                    snapshot.queriedAt ? snapshot.queriedAt.replace('T', ' ').slice(5, 19) : '—'
                  }`
                : '查询中…'}
            </span>
          </span>
        }
        className="job-card"
        extra={
          <div className="header-actions">
            {snapshot &&
              (snapshot.source === 'real' ? (
                <Tag color="success" icon={<ThunderboltOutlined />}>
                  实时数据
                </Tag>
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
          </div>
        }
      >
        {loading && !snapshot ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : (
          <>
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
            <div className="queue-summary-grid">
              {(snapshot?.queues ?? []).map((q) => (
                <QueueSummaryCard key={q.queue} q={q} />
              ))}
            </div>
          </>
        )}
      </Card>

      <Card
        size="small"
        title="节点状态明细（bhost）"
        className="job-card mt-16"
      >
        {loading && !snapshot ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : (
          <Table
            rowKey="name"
            size="small"
            columns={columns}
            dataSource={snapshot?.nodes ?? []}
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        )}
      </Card>

      <Card size="small" title="提交配置" className="job-card mt-16">
        <div className="job-script-form">
          <div className="job-script-form__row">
            <span className="job-script-form__label">脚本格式</span>
            <Segmented
              value={format}
              onChange={(v) => onFormatChange(v as ScriptFormat)}
              options={[
                { value: 'lsf', label: 'LSF (bsub)' },
                { value: 'slurm', label: 'Slurm (sbatch)' },
              ]}
            />
          </div>
          <div className="job-script-form__row">
            <span className="job-script-form__label">作业名</span>
            <Input
              value={jobName}
              onChange={(e) => setJobName(e.target.value)}
              style={{ width: 260 }}
              placeholder="作业名"
            />
          </div>
          <div className="job-script-form__row">
            <span className="job-script-form__label">队列 / 分区</span>
            <Select
              value={queue}
              onChange={setQueue}
              style={{ width: 320 }}
              options={queueOptions}
            />
            {queue && (
              <span className="preview-note">
                {snapshot?.queues.find((q) => q.queue === queue)?.walltime ?? ''}
              </span>
            )}
          </div>
          <div className="job-script-form__row">
            <span className="job-script-form__label">核数</span>
            <InputNumber
              min={1}
              max={512}
              value={cores}
              onChange={(v) => setCores(v ?? 1)}
              style={{ width: 140 }}
              addonAfter="核"
            />
            <span className="preview-note">
              推荐 {snapshot ? getRecommendedCores(snapshot.nodes) : '—'} 核（健康节点最大空闲核数）
            </span>
          </div>
          <div className="job-script-form__row">
            <span className="job-script-form__label">远程目录</span>
            <code className="path-cell">{task.remote_dir}</code>
          </div>
          <div className="job-script-form__row">
            <span />
            <Button type="primary" icon={<CodeOutlined />} onClick={generate}>
              生成脚本
            </Button>
          </div>
        </div>
      </Card>

      <Card
        size="small"
        title="脚本内容"
        className="job-card mt-16"
        extra={
          <Button
            type="primary"
            icon={<SaveOutlined />}
            disabled={!script.trim()}
            onClick={save}
          >
            保存到本地
          </Button>
        }
      >
        {script ? (
          <>
            <Input.TextArea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              autoSize={{ minRows: 12, maxRows: 22 }}
              spellCheck={false}
              className="job-script-editor"
            />
            <div className="preview-note" style={{ marginTop: 8 }}>
              保存后写入 {task.local_dir}/submit.sh，后续点击「提交」由后端通过 SSH 执行
              {format === 'lsf' ? ' bsub < submit.sh' : ' sbatch submit.sh'}。
            </div>
          </>
        ) : (
          <div className="job-empty-hint">配置上方参数后点击「生成脚本」。</div>
        )}
      </Card>
    </div>
  );
}
