import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, App as AntApp, Button, Card, Checkbox, Empty, InputNumber, Modal, Popconfirm, Space, Switch, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  FileTextOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  fetchManagedPlans,
  fetchResourcePlan,
  fetchScriptPreview,
  patchManagedPlan,
  setManagedStatus,
} from '../../api/managed';
import type {
  ManagedCandidate,
  ManagedPlan,
  ManagedPlanItem,
  ManagedStage,
  ResourcePlanResult,
} from '../../api/managed';

const STATUS_LABEL: Record<ManagedPlan['status'], string> = {
  active: '进行中',
  paused: '已暂停',
  ended: '已结束',
};

const INTENT_LABEL: Record<ManagedCandidate['intent'], string> = {
  first_submit: '首发提交',
  continuation: '续算',
  in_flight: '在跑',
  waiting_upstream: '等待上游',
};

const PRIORITY_SOURCE_LABEL: Record<ManagedCandidate['priority_source'], string> = {
  override: '人工/AI 覆盖',
  stage: '阶段优先级',
  default: '默认',
};

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

/** 单任务优先级编辑：保存时才写入计划（写入后版本号 +1）。 */
function PriorityEditor({
  value,
  locked,
  disabled,
  onSave,
}: {
  value: number;
  locked: boolean;
  disabled?: boolean;
  onSave: (priority: number, locked: boolean) => Promise<void>;
}) {
  const [priority, setPriority] = useState(value);
  const [lock, setLock] = useState(locked);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPriority(value);
    setLock(locked);
  }, [value, locked]);

  return (
    <Space size={4}>
      <InputNumber
        size="small"
        min={0}
        max={100}
        value={priority}
        disabled={disabled}
        onChange={(next) => setPriority(typeof next === 'number' ? next : 0)}
        style={{ width: 72 }}
      />
      <Switch
        size="small"
        checked={lock}
        disabled={disabled}
        checkedChildren="锁"
        unCheckedChildren="锁"
        onChange={setLock}
      />
      <Button
        size="small"
        loading={busy}
        disabled={disabled}
        onClick={async () => {
          setBusy(true);
          try {
            await onSave(priority, lock);
          } finally {
            setBusy(false);
          }
        }}
      >
        保存
      </Button>
    </Space>
  );
}

const stageColumns: ColumnsType<ManagedStage> = [
  { title: '阶段', dataIndex: 'title', key: 'title' },
  {
    title: '交付',
    dataIndex: 'due',
    key: 'due',
    width: 130,
    render: (due?: string) => (due ? due : <Typography.Text type="secondary">未指定</Typography.Text>),
  },
  { title: '优先级', dataIndex: 'priority', key: 'priority', width: 90 },
  {
    title: '任务',
    dataIndex: 'task_ids',
    key: 'task_ids',
    render: (ids: string[]) => <Typography.Text>{ids.length} 个：{ids.join('、')}</Typography.Text>,
  },
  {
    title: '来源原话',
    dataIndex: 'source_quote',
    key: 'source_quote',
    render: (quote?: string) => (quote ? <Typography.Text type="secondary">{quote}</Typography.Text> : '—'),
  },
];

function ResourceSuggestion({
  result,
  saving,
  onSaveQueues,
}: {
  result: ResourcePlanResult;
  saving?: boolean;
  onSaveQueues: (queues: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(result.rules?.queues_allowed ?? []);
  useEffect(() => {
    setSelected(result.rules?.queues_allowed ?? []);
  }, [result]);

  return (
    <Card size="small" title="资源建议（只读；没有写入或提交）">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {result.state !== 'ok' && (
          <Alert type={result.state === 'blocked' ? 'warning' : 'info'} showIcon message={result.reason} />
        )}
        {result.snapshot?.queriedAt && (
          <Typography.Text type="secondary">
            集群快照 {result.snapshot.queriedAt}
            {typeof result.snapshot.ageSeconds === 'number' ? `（${Math.round(result.snapshot.ageSeconds)} 秒前）` : ''}
          </Typography.Text>
        )}
        {result.candidates.map((candidate, index) => (
          <Card key={`${candidate.queue}-${candidate.nodes}`} size="small" type="inner"
            title={`${index + 1}. ${candidate.queue} · ${candidate.nodes} 节点 × ${candidate.cores_per_node} 核 · ${candidate.walltime_hours} 小时`}
            extra={<Tag color="blue">评分 {candidate.score}</Tag>}>
            <Space direction="vertical" size={2}>
              {candidate.explain.map((line) => <Typography.Text key={line}>{line}</Typography.Text>)}
              {candidate.notes.map((line) => <Typography.Text key={line} type="secondary">注意：{line}</Typography.Text>)}
            </Space>
          </Card>
        ))}
        {!!result.server_queues?.length && (
          <div>
            <Typography.Text strong>这台服务器可用的队列</Typography.Text>
            <div style={{ margin: '6px 0' }}>
              <Checkbox.Group value={selected} onChange={(values) => setSelected(values as string[])} style={{ display: 'block' }}>
                {result.server_queues.map((queue) => (
                  <Checkbox
                    key={queue.queue}
                    value={queue.queue}
                    disabled={queue.paid && !result.rules?.paid_allowed}
                    style={{ display: 'block', marginLeft: 0 }}
                  >
                    {queue.queue}（{queue.cores_per_node} 核/节点 · {queue.walltime_hours ? `${queue.walltime_hours} 小时` : '不限'} · {queue.paid ? '付费' : '免费'} · {queue.nodes} 节点）
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </div>
            <Button size="small" type="primary" loading={saving} disabled={selected.length === 0}
              onClick={() => onSaveQueues(selected)}>保存队列并评分</Button>
          </div>
        )}
        {result.candidates.length === 0 && <Typography.Text type="secondary">还没有可评分的资源方案：先选队列，再按当前集群快照评分。</Typography.Text>}
        {(result.filtered ?? []).length > 0 && (
          <Typography.Text type="secondary">
            已过滤：{result.filtered?.map((row) => `${row.queue}（${row.reason}）`).join('；')}
          </Typography.Text>
        )}
        {result.heuristic && <Typography.Text type="secondary">{result.heuristic}</Typography.Text>}
      </Space>
    </Card>
  );
}

export function ManagedPanel() {
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [plans, setPlans] = useState<ManagedPlanItem[]>([]);
  const [executionEnabled, setExecutionEnabled] = useState(false);
  const [resources, setResources] = useState<Record<string, ResourcePlanResult>>({});
  const [busy, setBusy] = useState('');
  const [script, setScript] = useState<{ text: string; issues: string[] } | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await fetchManagedPlans();
      setPlans(data.plans ?? []);
      setExecutionEnabled(Boolean(data.execution_enabled));
    } catch (error) {
      message.error(errorText(error, '加载托管计划失败'));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const changeStatus = async (plan: ManagedPlan, status: 'active' | 'paused' | 'ended') => {
    setBusy(plan.id);
    try {
      await setManagedStatus(plan.id, status);
      message.success(status === 'ended' ? '计划已结束（不会停止远端作业）' : status === 'paused' ? '已暂停推进' : '已恢复');
      await load(true);
    } catch (error) {
      message.error(errorText(error, '更新失败'));
    } finally {
      setBusy('');
    }
  };

  const savePriority = async (plan: ManagedPlan, candidate: ManagedCandidate, priority: number, locked: boolean) => {
    try {
      await patchManagedPlan(plan.id, plan.revision, {
        task_overrides: [{ task_id: candidate.task_id, priority, locked, reason: '人工在托管页调整' }],
      });
      message.success('优先级已保存');
      await load(true);
    } catch (error) {
      message.error(errorText(error, '保存优先级失败'));
      await load(true);
    }
  };

  const saveQueues = async (plan: ManagedPlan, queues: string[]) => {
    setBusy(`queues:${plan.id}`);
    try {
      const updated = await patchManagedPlan(plan.id, plan.revision, { resource_rules: { queues_allowed: queues } });
      message.success('已保存可用队列，正在按当前快照评分');
      await load(true);
      const result = await fetchResourcePlan(updated.plan.id);
      setResources((prev) => ({ ...prev, [plan.id]: result }));
    } catch (error) {
      message.error(errorText(error, '保存队列失败'));
      await load(true);
    } finally {
      setBusy('');
    }
  };

  const showResource = async (plan: ManagedPlan) => {
    setBusy(`res:${plan.id}`);
    try {
      const result = await fetchResourcePlan(plan.id);
      setResources((prev) => ({ ...prev, [plan.id]: result }));
    } catch (error) {
      message.error(errorText(error, '获取资源建议失败'));
    } finally {
      setBusy('');
    }
  };

  const showScript = async (plan: ManagedPlan) => {
    setBusy(`script:${plan.id}`);
    try {
      const result = await fetchScriptPreview(plan.id);
      if (!result.script) {
        message.info(result.reason ?? '当前没有可预览的脚本');
        return;
      }
      setScript({ text: result.script, issues: result.issues ?? [] });
    } catch (error) {
      message.error(errorText(error, '生成脚本预览失败'));
    } finally {
      setBusy('');
    }
  };

  const candidateColumns = (plan: ManagedPlan): ColumnsType<ManagedCandidate> => [
    {
      title: '任务',
      dataIndex: 'task_name',
      key: 'task_name',
      render: (name: string, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary">{row.task_id}</Typography.Text>
        </Space>
      ),
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
    {
      title: '下一步',
      dataIndex: 'intent',
      key: 'intent',
      width: 100,
      render: (intent: ManagedCandidate['intent']) => (
        <Tag color={intent === 'in_flight' || intent === 'waiting_upstream' ? 'default' : intent === 'first_submit' ? 'green' : 'orange'}>
          {INTENT_LABEL[intent]}
        </Tag>
      ),
    },
    {
      title: '优先级',
      key: 'priority',
      width: 190,
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          <PriorityEditor
            value={row.priority}
            locked={row.locked}
            disabled={plan.status === 'ended'}
            onSave={(priority, locked) => savePriority(plan, row, priority, locked)}
          />
          <Typography.Text type="secondary">{PRIORITY_SOURCE_LABEL[row.priority_source]}</Typography.Text>
        </Space>
      ),
    },
    { title: '阶段', dataIndex: 'stage_title', key: 'stage_title', width: 120, render: (title?: string) => title ?? '—' },
    { title: '交付', dataIndex: 'due', key: 'due', width: 110, render: (due?: string) => due || '—' },
    { title: '说明', dataIndex: 'reason', key: 'reason', render: (reason: string) => <Typography.Text type="secondary">{reason}</Typography.Text> },
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
        <Button icon={<RobotOutlined />} onClick={() => navigate('/ai')}>去 AI 工作台</Button>
      </Space>

      {!executionEnabled && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="自主执行当前关闭"
          description="这里保存的计划和规则不会自动提交或续算。需要管理员在「自动化」页开启执行开关后，托管才可能真正推进。"
        />
      )}

      {plans.length === 0 && !loading && (
        <Card>
          <Empty description="还没有托管计划">
            <Space direction="vertical" size={8}>
              <Typography.Text type="secondary">
                到 AI 工作台说一句，例如：“这个项目周五先交 model1 的阶段报告，把它放最高；有输入的任务帮我接着跑，只用 normal_2week 队列。”
              </Typography.Text>
              <Button type="primary" onClick={() => navigate('/ai')}>去 AI 工作台</Button>
            </Space>
          </Empty>
        </Card>
      )}

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {plans.map(({ plan, summary }) => {
          const counts = summary.counts ?? {};
          const actionable = (counts.ready ?? 0) + (counts.continuation ?? 0);
          return (
            <Card
              key={plan.id}
              title={
                <Space wrap>
                  <Typography.Text strong>{plan.goal.summary || plan.goal.text}</Typography.Text>
                  <Tag color={plan.status === 'active' ? 'green' : plan.status === 'paused' ? 'orange' : 'default'}>
                    {STATUS_LABEL[plan.status]}
                  </Tag>
                  <Tag>v{plan.revision}</Tag>
                </Space>
              }
              extra={
                <Space wrap>
                  <Button size="small" icon={<ReloadOutlined />} loading={busy === `res:${plan.id}`}
                    onClick={() => void showResource(plan)}>资源建议</Button>
                  <Button size="small" icon={<FileTextOutlined />} loading={busy === `script:${plan.id}`}
                    onClick={() => void showScript(plan)}>脚本预览</Button>
                  {plan.status === 'active' && (
                    <Button size="small" icon={<PauseCircleOutlined />} loading={busy === plan.id}
                      onClick={() => void changeStatus(plan, 'paused')}>暂停</Button>
                  )}
                  {plan.status === 'paused' && (
                    <Button size="small" type="primary" icon={<PlayCircleOutlined />} loading={busy === plan.id}
                      onClick={() => void changeStatus(plan, 'active')}>恢复</Button>
                  )}
                  {plan.status !== 'ended' && (
                    <Popconfirm
                      title="结束这个托管计划？"
                      description="只结束计划，不会停止远端作业。"
                      onConfirm={() => void changeStatus(plan, 'ended')}
                    >
                      <Button size="small" danger icon={<StopOutlined />} loading={busy === plan.id}>结束</Button>
                    </Popconfirm>
                  )}
                </Space>
              }
            >
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Typography.Text type="secondary">{plan.goal.text}</Typography.Text>
                <Space wrap>
                  <Tag>{plan.project}</Tag>
                  <Tag>{plan.server}</Tag>
                  <Tag color={actionable > 0 ? 'blue' : 'default'}>待推进 {actionable}</Tag>
                  <Tag>在跑 {counts.in_flight ?? 0}</Tag>
                  {summary.next && (
                    <Typography.Text>
                      下一步：{summary.next.task_name}（{INTENT_LABEL[summary.next.intent]}）
                    </Typography.Text>
                  )}
                </Space>

                {(summary.needs_user ?? []).map((text) => (
                  <Alert key={text} type="warning" showIcon message={text} />
                ))}
                {summary.error && <Alert type="error" showIcon message={summary.error} />}

                {plan.stages.length > 0 && (
                  <div>
                    <Typography.Text strong>阶段交付</Typography.Text>
                    <Table<ManagedStage>
                      size="small"
                      rowKey="stage_id"
                      columns={stageColumns}
                      dataSource={plan.stages}
                      pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
                      style={{ marginTop: 8 }}
                    />
                  </div>
                )}

                <div>
                  <Typography.Text strong>候选任务（按规则排序；在这里调整会记为人工修改）</Typography.Text>
                  <Table<ManagedCandidate>
                    size="small"
                    rowKey="task_id"
                    columns={candidateColumns(plan)}
                    dataSource={summary.candidates ?? []}
                    pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
                    style={{ marginTop: 8 }}
                  />
                </div>

                {resources[plan.id] && <ResourceSuggestion result={resources[plan.id]} saving={busy === `queues:${plan.id}`} onSaveQueues={(queues) => void saveQueues(plan, queues)} />}
              </Space>
            </Card>
          );
        })}
      </Space>

      <Modal
        open={Boolean(script)}
        title="vasp.lsf 预览（未写入远端、未提交）"
        footer={null}
        width={900}
        onCancel={() => setScript(null)}
      >
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {(script?.issues ?? []).map((issue) => <Alert key={issue} type="error" showIcon message={issue} />)}
          <pre style={{ maxHeight: '60vh', overflow: 'auto', fontSize: 12, margin: 0 }}>{script?.text}</pre>
        </Space>
      </Modal>
    </>
  );
}
