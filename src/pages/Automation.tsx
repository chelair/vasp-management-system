import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Card, Empty, Space, Switch, Table, Tag, Tooltip } from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import {
  fetchAutomationDecisions,
  fetchAutomationRuns,
  fetchAutomationStatus,
  reloadAutomation,
  runAutomationRule,
  saveAutomationSettings,
  setAutomationRuleEnabled,
  type AutomationDecision,
  type AutomationRule,
  type AutomationRun,
  type AutomationSchedule,
  type AutomationSettings,
} from '../api/automation';

/** 五种审计状态的展示样式（success / failed / skipped / blocked / dry_run） */
const STATUS_META: Record<string, { label: string; color: string }> = {
  success: { label: '成功', color: 'green' },
  failed: { label: '失败', color: 'red' },
  skipped: { label: '跳过', color: 'default' },
  blocked: { label: '拦截', color: 'orange' },
  dry_run: { label: '演练', color: 'blue' },
};

function statusTag(status: string) {
  const meta = STATUS_META[status] ?? { label: status, color: 'default' };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function formatTime(value?: string | null) {
  if (!value) return '—';
  return value.replace('T', ' ').slice(5, 19);
}

/**
 * 自动化页（v0.9.6，仅 admin）：全局开关 / 规则开关 / 定时任务 / 决策日志 / 运行记录。
 * 后端是防线（403），这里只是入口与可视化。
 */
export default function Automation() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState<AutomationSettings | null>(null);
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [schedules, setSchedules] = useState<AutomationSchedule[]>([]);
  const [decisions, setDecisions] = useState<AutomationDecision[]>([]);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});

  const load = useCallback(
    async (notify = false) => {
      setLoading(true);
      try {
        const [status, decisionData, runData] = await Promise.all([
          fetchAutomationStatus(),
          fetchAutomationDecisions(100),
          fetchAutomationRuns(50),
        ]);
        setSettings(status.settings);
        setRules(status.rules ?? []);
        setSchedules(status.schedules ?? []);
        setCounts(status.counts ?? {});
        setDecisions(decisionData.decisions ?? []);
        setRuns(runData.runs ?? []);
        if (notify) message.success('已刷新');
      } catch (err) {
        message.error(err instanceof Error ? err.message : '读取自动化状态失败');
      } finally {
        setLoading(false);
      }
    },
    [message],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const paused = settings ? !settings.enabled : false;

  const updateSettings = async (patch: Partial<AutomationSettings>) => {
    setSaving(true);
    try {
      const next = await saveAutomationSettings(patch);
      setSettings(next);
      message.success('已保存（立即生效）');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存设置失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleRule = async (rule: AutomationRule, enabled: boolean) => {
    try {
      await setAutomationRuleEnabled(rule.id, enabled);
      setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, enabled } : r)));
      message.success(`规则 ${rule.id} 已${enabled ? '启用' : '停用'}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '更新规则失败');
    }
  };

  const triggerSchedule = async (schedule: AutomationSchedule) => {
    try {
      await runAutomationRule(schedule.id);
      message.success('已投递触发信号，稍后可在决策日志查看结果');
      window.setTimeout(() => void load(), 1500);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '触发失败');
    }
  };

  const ruleColumns = useMemo(
    () => [
      {
        title: '规则',
        dataIndex: 'id',
        render: (id: string, rule: AutomationRule) => (
          <div>
            <div style={{ fontWeight: 500 }}>{rule.description || id}</div>
            <div className="preview-note">{id}</div>
          </div>
        ),
      },
      {
        title: '触发',
        dataIndex: 'trigger',
        width: 150,
        render: (trigger: AutomationRule['trigger']) =>
          trigger?.type === 'schedule' ? (
            <span>
              <Tag>定时</Tag>
              <code>{trigger.cron}</code>
            </span>
          ) : (
            <Tag color="geekblue">巡检完成</Tag>
          ),
      },
      {
        title: '条件',
        dataIndex: 'condition',
        render: (condition: Record<string, unknown>) => (
          <span className="preview-note" style={{ whiteSpace: 'pre-wrap' }}>
            {Object.entries(condition ?? {})
              .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('|') : String(v)}`)
              .join(' · ')}
          </span>
        ),
      },
      { title: '动作', dataIndex: 'action', width: 150 },
      {
        title: 'Guard',
        dataIndex: 'guard',
        width: 170,
        render: (guard: AutomationRule['guard'], rule: AutomationRule) => (
          <span className="preview-note">
            冷却 {guard?.cooldown_seconds ?? 0}s · 上限 {guard?.max_runs_per_task ?? '∞'}
            {rule.failures ? ` · 连续失败 ${rule.failures}` : ''}
          </span>
        ),
      },
      {
        title: '启用',
        dataIndex: 'enabled',
        width: 80,
        render: (enabled: boolean, rule: AutomationRule) => (
          <Switch size="small" checked={enabled} onChange={(v) => void toggleRule(rule, v)} />
        ),
      },
    ],
    [],
  );

  const scheduleColumns = [
    { title: '任务', dataIndex: 'description', render: (v: string, s: AutomationSchedule) => v || s.id },
    { title: 'cron', dataIndex: 'cron', width: 120 },
    { title: '范围', dataIndex: 'scope', width: 100 },
    { title: '动作', dataIndex: 'action', width: 150 },
    {
      title: '下次执行',
      dataIndex: 'next_run_at',
      width: 160,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (enabled: boolean, s: AutomationSchedule) => {
        const rule = rules.find((r) => r.id === s.id);
        return (
          <Switch
            size="small"
            checked={enabled}
            onChange={(v) => rule && void toggleRule(rule, v)}
          />
        );
      },
    },
    {
      title: '操作',
      width: 110,
      render: (_: unknown, s: AutomationSchedule) => (
        <Button size="small" type="link" onClick={() => void triggerSchedule(s)}>
          立即触发
        </Button>
      ),
    },
  ];

  const decisionColumns = [
    { title: '时间', dataIndex: 'at', width: 150, render: (v: string) => formatTime(v) },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => statusTag(v) },
    { title: '动作', dataIndex: 'action', width: 150 },
    {
      title: '任务 / 项目',
      width: 220,
      render: (_: unknown, d: AutomationDecision) => (
        <span className="preview-note">
          {d.project ? `${d.project} · ` : ''}
          {d.task_id || '—'}
        </span>
      ),
    },
    {
      title: '触发',
      width: 140,
      render: (_: unknown, d: AutomationDecision) => (
        <span className="preview-note">
          {d.trigger || '—'}
          {d.rule_id ? ` · ${d.rule_id}` : ''}
        </span>
      ),
    },
    { title: '原因', dataIndex: 'reason', render: (v: string) => v || '—' },
    {
      title: '耗时',
      dataIndex: 'elapsed_ms',
      width: 90,
      render: (v: number) => (v != null ? `${v} ms` : '—'),
    },
  ];

  const runColumns = [
    { title: 'run_id', dataIndex: 'run_id', width: 220, render: (v: string) => <code>{v}</code> },
    { title: '动作', dataIndex: 'action', width: 150 },
    { title: '任务', dataIndex: 'task_id', width: 200 },
    { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => statusTag(v) },
    { title: '开始', dataIndex: 'started_at', width: 150, render: (v: string) => formatTime(v) },
    { title: '结束', dataIndex: 'finished_at', width: 150, render: (v: string) => formatTime(v) },
    { title: '原因', dataIndex: 'reason', render: (v: string) => v || '—' },
  ];

  return (
    <PageTransition>
      <PageHeader
        title="自动化"
        subtitle="巡检事件与定时触发 → 规则匹配 → 动作执行 → 审计留痕（仅管理员可见）"
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void load(true)}
            >
              刷新
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={async () => {
                try {
                  const r = await reloadAutomation();
                  message.success(`配置已重载（${r.rules} 条规则，改 cron 无需重启）`);
                  void load();
                } catch (err) {
                  message.error(err instanceof Error ? err.message : '重载失败');
                }
              }}
            >
              重载配置
            </Button>
          </Space>
        }
      />

      {paused && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 14 }}
          message="自动化已全局暂停"
          description="当前不会执行任何规则动作（巡检仍照常进行）。需要恢复时把下面的「总开关」打开。"
        />
      )}

      <Card size="small" title="全局开关" className="job-card" style={{ marginBottom: 14 }}>
        <Space size={28} wrap>
          <Space size={8}>
            <span>总开关</span>
            <Tooltip title="关闭后所有规则与手动动作都会被拦截（立即生效）">
              <Switch
                checked={settings?.enabled ?? false}
                loading={saving}
                onChange={(v) => void updateSettings({ enabled: v })}
              />
            </Tooltip>
          </Space>
          <Space size={8}>
            <span>演练模式（dry_run）</span>
            <Tooltip title="只跑 preflight 并把 will_do 写进审计，不做任何远端操作、不改状态">
              <Switch
                checked={settings?.dry_run ?? false}
                loading={saving}
                onChange={(v) => void updateSettings({ dry_run: v })}
              />
            </Tooltip>
          </Space>
          <Space size={8}>
            <span>定时触发</span>
            <Tooltip title="关闭后 cron 不再投递触发信号（巡检事件触发不受影响）">
              <Switch
                checked={settings?.schedules_enabled ?? false}
                loading={saving}
                onChange={(v) => void updateSettings({ schedules_enabled: v })}
              />
            </Tooltip>
          </Space>
          <span className="preview-note">
            规则 {counts.enabled_rules ?? 0}/{counts.rules ?? 0} 启用 · 队列 {counts.queue ?? 0}
          </span>
        </Space>
      </Card>

      <Card size="small" title="定时任务" className="job-card" style={{ marginBottom: 14 }}>
        {schedules.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有定时规则" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={schedules}
            columns={scheduleColumns}
            pagination={false}
          />
        )}
      </Card>

      <Card size="small" title="规则" className="job-card" style={{ marginBottom: 14 }}>
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          dataSource={rules}
          columns={ruleColumns}
          pagination={false}
        />
      </Card>

      <Card size="small" title="决策日志" className="job-card" style={{ marginBottom: 14 }}>
        <Table
          size="small"
          rowKey={(d) => `${d.at}-${d.action}-${d.task_id ?? ''}`}
          loading={loading}
          dataSource={decisions}
          columns={decisionColumns}
          pagination={{ pageSize: 20, size: 'small' }}
        />
      </Card>

      <Card size="small" title="动作运行记录" className="job-card">
        <Table
          size="small"
          rowKey="run_id"
          loading={loading}
          dataSource={runs}
          columns={runColumns}
          pagination={{ pageSize: 10, size: 'small' }}
        />
      </Card>
    </PageTransition>
  );
}
