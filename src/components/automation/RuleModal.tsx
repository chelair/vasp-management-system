import { useEffect, useMemo, useState } from 'react';
import { App, Button, Checkbox, Collapse, Form, Input, InputNumber, Modal, Select, Space } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import type { ActionCatalogItem, AutomationRule } from '../../api/automation';
import {
  RULE_TARGET_OPTIONS,
  buildRuleCondition,
  inferRuleTarget,
  type RuleTargetType,
} from '../../utils/ruleTarget';

/** condition 里可用的字段（来自后端 rules.build_context()） */
const CONDITION_KEYS = [
  'task_type',
  'status',
  'converged',
  'group_type',
  'group_role',
  'frac_missing',
  'initial_converged',
  'final_converged',
  'images_created',
  'is_continuation',
  'archived',
  'project',
  'model_name',
  'job_id',
];

interface CondRow {
  id: number;
  key: string;
  value: string;
}

interface Props {
  open: boolean;
  /** 传入表示编辑；不传表示新建 */
  rule?: AutomationRule | null;
  actions: ActionCatalogItem[];
  /** 可选项目名（"指定项目"下拉） */
  projects?: string[];
  onCancel: () => void;
  onSubmit: (payload: Partial<AutomationRule>) => Promise<void>;
}

function parseValue(raw: string): unknown {
  const text = String(raw ?? '').trim();
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (text.includes(',')) {
    const parts = text.split(',').map((s) => s.trim()).filter(Boolean);
    return parts.map((p) => (/^-?\d+$/.test(p) ? Number(p) : p));
  }
  if (/^-?\d+$/.test(text)) return Number(text);
  return text;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(',');
  return value === undefined || value === null ? '' : String(value);
}

/** 规则新建 / 编辑弹窗（v0.9.7） */
export default function RuleModal({ open, rule, actions, projects = [], onCancel, onSubmit }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [rows, setRows] = useState<CondRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [triggerType, setTriggerType] = useState<'inspection_completed' | 'schedule'>(
    'inspection_completed',
  );
  /** 定时子类型：cron 周期 / N 秒后执行一次（一次性） */
  const [scheduleMode, setScheduleMode] = useState<'cron' | 'after'>('cron');
  /** 作用对象（项目 / opt 任务 / 自由能组）——显式选择，不再让人直接填条件 */
  const [target, setTarget] = useState<RuleTargetType>('project');
  const [targetProject, setTargetProject] = useState<string | undefined>(undefined);
  const seq = useMemo(() => ({ current: 0 }), []);

  useEffect(() => {
    if (!open) return;
    const trigger = (rule?.trigger?.type as 'inspection_completed' | 'schedule') || 'inspection_completed';
    const rawTrigger = (rule?.trigger || {}) as { mode?: string; after_seconds?: number };
    setTriggerType(trigger);
    setScheduleMode(
      (rawTrigger.mode as 'cron' | 'after') || (rawTrigger.after_seconds ? 'after' : 'cron'),
    );
    form.setFieldsValue({
      id: rule?.id ?? '',
      description: rule?.description ?? '',
      action: rule?.action ?? actions[0]?.name,
      cron: rule?.trigger?.cron ?? '0 2 * * *',
      after_minutes: rawTrigger.after_seconds ? Math.max(1, Math.round(rawTrigger.after_seconds / 60)) : 30,
      scope: rule?.trigger?.scope ?? 'all',
      cooldown_seconds: rule?.guard?.cooldown_seconds ?? 1800,
      max_runs_per_task: rule?.guard?.max_runs_per_task ?? 5,
      enabled: rule?.enabled ?? true,
    });
    const inferred = inferRuleTarget(rule?.condition);
    setTarget(inferred.target);
    setTargetProject(inferred.project ?? (rule?.trigger?.scope?.startsWith('project:')
      ? rule?.trigger?.scope?.slice('project:'.length)
      : undefined));
    seq.current = 0;
    setRows(
      Object.entries(inferred.extra).map(([key, value]) => ({
        id: (seq.current += 1),
        key,
        value: formatValue(value),
      })),
    );
  }, [open, rule, actions, form, seq]);

  const submit = async () => {
    try {
      const values = await form.validateFields();
      const extra: Record<string, unknown> = {};
      for (const row of rows) {
        const key = row.key.trim();
        if (!key || row.value.trim() === '') continue;
        extra[key] = parseValue(row.value);
      }
      const isSchedule = triggerType === 'schedule';
      const { condition, scope } = buildRuleCondition(target, targetProject, extra, isSchedule);
      const payload: Partial<AutomationRule> = {
        id: String(values.id).trim(),
        description: values.description ?? '',
        enabled: values.enabled,
        trigger:
          triggerType === 'schedule' && scheduleMode === 'cron'
            ? { type: 'schedule', mode: 'cron', cron: String(values.cron).trim(), scope: scope || 'all' }
            : triggerType === 'schedule'
              ? {
                  type: 'schedule',
                  mode: 'after',
                  after_seconds: Math.max(1, Math.round(Number(values.after_minutes ?? 30) * 60)),
                  scope: scope || 'all',
                }
              : { type: 'inspection_completed' },
        condition,
        action: values.action,
        guard: {
          cooldown_seconds: values.cooldown_seconds ?? 0,
          max_runs_per_task: values.max_runs_per_task ?? 0,
        },
      };
      setSaving(true);
      await onSubmit(payload);
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存规则失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title={rule ? `编辑规则 · ${rule.id}` : '新建规则'}
      onCancel={onCancel}
      onOk={() => void submit()}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      width={640}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item
            name="id"
            label="规则 ID"
            style={{ width: 240 }}
            rules={[
              { required: true, message: '请输入规则 ID' },
              { pattern: /^[a-z0-9][a-z0-9._-]{1,63}$/, message: '小写字母/数字/._-（2-64 位）' },
            ]}
          >
            <Input placeholder="opt-unconverged-continuation" disabled={!!rule} />
          </Form.Item>
          <Form.Item name="description" label="说明" style={{ width: 340 }}>
            <Input placeholder="这条规则做什么" />
          </Form.Item>
        </Space>

        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item name="triggerType" label="触发方式" style={{ width: 170 }} initialValue={triggerType}>
            <Select
              value={triggerType}
              onChange={(v) => setTriggerType(v as 'inspection_completed' | 'schedule')}
              options={[
                { value: 'inspection_completed', label: '巡检完成后' },
                { value: 'schedule', label: '定时（cron）' },
              ]}
            />
          </Form.Item>
          {triggerType === 'schedule' && (
            <>
              <Form.Item label="定时类型" style={{ width: 170 }}>
                <Select
                  value={scheduleMode}
                  onChange={(v) => setScheduleMode(v as 'cron' | 'after')}
                  options={[
                    { value: 'cron', label: '按 cron 周期' },
                    { value: 'after', label: 'N 分钟后执行一次' },
                  ]}
                />
              </Form.Item>
              {scheduleMode === 'cron' ? (
                <Form.Item
                  name="cron"
                  label="cron（分 时 日 月 周）"
                  style={{ width: 190 }}
                  rules={[{ required: true, message: '请输入 cron' }]}
                >
                  <Input placeholder="0 2 * * *" />
                </Form.Item>
              ) : (
                <Form.Item name="after_minutes" label="多少分钟后执行（一次性）" style={{ width: 190 }}>
                  <InputNumber min={1} step={5} style={{ width: '100%' }} addonAfter="分钟" />
                </Form.Item>
              )}

            </>
          )}
          <Form.Item name="action" label="动作" style={{ width: 220 }} rules={[{ required: true }]}>
            <Select
              options={actions.map((a) => ({ value: a.name, label: `${a.label}（${a.name}）` }))}
            />
          </Form.Item>
        </Space>

        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item label="作用对象" style={{ width: 220 }}>
            <Select
              value={target}
              onChange={(v) => setTarget(v as RuleTargetType)}
              options={RULE_TARGET_OPTIONS.map((o) => ({
                value: o.value,
                label: o.label,
                title: o.hint,
              }))}
            />
          </Form.Item>
          <Form.Item label="指定项目（可选）" style={{ width: 220 }}>
            <Select
              allowClear
              placeholder="全部项目"
              value={targetProject}
              onChange={(v) => setTargetProject(v as string | undefined)}
              options={projects.map((name) => ({ value: name, label: name }))}
            />
          </Form.Item>
          <span className="preview-note" style={{ lineHeight: '30px' }}>
            {RULE_TARGET_OPTIONS.find((o) => o.value === target)?.hint}
          </span>
        </Space>

        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item name="cooldown_seconds" label="冷却期（秒）" style={{ width: 160 }}>
            <InputNumber min={0} step={300} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_runs_per_task" label="单任务执行上限" style={{ width: 160 }}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" style={{ width: 80 }}>
            <Checkbox />
          </Form.Item>
        </Space>

        <Collapse
          ghost
          size="small"
          items={[
            {
              key: 'extra',
              label: `附加条件（可选）${rows.length ? ` · 已填 ${rows.length} 条` : ''}`,
              children: (
                <>
                  <div className="job-field-hint" style={{ marginBottom: 6 }}>
                    在"作用对象"之上再加条件（全部满足才触发）；值支持 <code>true/false</code>、
                    逗号分隔列表、数字或字符串，例如 <code>status=unconverged</code>、
                    <code>frac_missing=true</code>
                  </div>
                  {rows.map((row) => (
          <Space key={row.id} size={8} style={{ display: 'flex', marginBottom: 6 }} align="start">
            <Select
              showSearch
              style={{ width: 200 }}
              placeholder="字段"
              value={row.key || undefined}
              onChange={(v) =>
                setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, key: String(v) } : r)))
              }
              options={CONDITION_KEYS.map((k) => ({ value: k, label: k }))}
            />
            <Input
              style={{ width: 260 }}
              placeholder="期望值"
              value={row.value}
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((r) => (r.id === row.id ? { ...r, value: e.target.value } : r)),
                )
              }
            />
            <Button
              type="text"
              icon={<DeleteOutlined />}
              onClick={() => setRows((prev) => prev.filter((r) => r.id !== row.id))}
            />
          </Space>
        ))}
                  <Button
                    size="small"
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() =>
                      setRows((prev) => [...prev, { id: (seq.current += 1), key: '', value: '' }])
                    }
                  >
                    添加条件
                  </Button>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  );
}
