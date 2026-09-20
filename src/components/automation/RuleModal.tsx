import { useEffect, useMemo, useState } from 'react';
import { App, Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import type { ActionCatalogItem, AutomationRule } from '../../api/automation';
import {
  CONDITION_FIELDS,
  RULE_TARGET_OPTIONS,
  conditionToSelection,
  findConditionField,
  normalizeConditionValue,
  selectionToCondition,
  toFormValue,
  type RuleTargetType,
  type TaskRefLite,
} from '../../utils/ruleTarget';

interface ExtraRow {
  id: number;
  key: string;
  value: unknown;
}

interface Props {
  open: boolean;
  /** 传入表示编辑；不传表示新建 */
  rule?: AutomationRule | null;
  actions: ActionCatalogItem[];
  /** 项目 / 任务 / 组（由页面从 /api/projects 摊平） */
  refs: TaskRefLite[];
  onCancel: () => void;
  onSubmit: (payload: Partial<AutomationRule>) => Promise<void>;
}

/**
 * 规则新建 / 编辑弹窗（v0.9.9）。
 *
 * 三级交互：作用对象 → 具体对象（项目/任务/组，可搜索多选）→ 附加条件（字段与取值都是下拉，
 * 带中文名与说明，不需要用户记字段名和取值）。
 */
export default function RuleModal({ open, rule, actions, refs, onCancel, onSubmit }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [triggerType, setTriggerType] = useState<'inspection_completed' | 'schedule'>(
    'inspection_completed',
  );
  const [scheduleMode, setScheduleMode] = useState<'cron' | 'after'>('cron');
  const [target, setTarget] = useState<RuleTargetType>('project');
  const [projects, setProjects] = useState<string[]>([]);
  const [tasks, setTasks] = useState<string[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [rows, setRows] = useState<ExtraRow[]>([]);
  const seq = useMemo(() => ({ current: 0 }), []);

  const projectNames = useMemo(
    () => Array.from(new Set(refs.map((r) => r.project))).sort(),
    [refs],
  );
  const optTasks = useMemo(
    () => refs.filter((r) => r.task_type === 'opt'),
    [refs],
  );
  const freeEnergyGroups = useMemo(() => {
    const map = new Map<string, { group_id: string; name: string; project: string }>();
    for (const ref of refs) {
      if (ref.group_type !== 'free_energy' || !ref.group_id) continue;
      if (!map.has(ref.group_id)) {
        map.set(ref.group_id, {
          group_id: ref.group_id,
          name: ref.group_name || ref.group_id,
          project: ref.project,
        });
      }
    }
    return Array.from(map.values());
  }, [refs]);

  useEffect(() => {
    if (!open) return;
    const trigger = (rule?.trigger?.type as 'inspection_completed' | 'schedule') || 'inspection_completed';
    const rawTrigger = (rule?.trigger || {}) as {
      mode?: string;
      after_seconds?: number;
      cron?: string;
      scope?: string;
    };
    setTriggerType(trigger);
    setScheduleMode(
      (rawTrigger.mode as 'cron' | 'after') || (rawTrigger.after_seconds ? 'after' : 'cron'),
    );
    const selection = conditionToSelection(
      rule?.condition,
      trigger === 'schedule',
      rawTrigger.scope,
    );
    setTarget(selection.target);
    setProjects(selection.projects);
    setTasks(selection.tasks);
    setGroups(selection.groups);
    seq.current = 0;
    setRows(
      Object.entries(selection.extra).map(([key, value]) => ({
        id: (seq.current += 1),
        key,
        value: toFormValue(key, value),
      })),
    );
    form.setFieldsValue({
      id: rule?.id ?? '',
      description: rule?.description ?? '',
      action: rule?.action ?? actions[0]?.name,
      cron: rawTrigger.cron ?? '0 2 * * *',
      after_minutes: rawTrigger.after_seconds
        ? Math.max(1, Math.round(rawTrigger.after_seconds / 60))
        : 30,
      cooldown_seconds: rule?.guard?.cooldown_seconds ?? 1800,
      max_runs_per_task: rule?.guard?.max_runs_per_task ?? 5,
      enabled: rule?.enabled ?? true,
    });
  }, [open, rule, actions, form, seq]);

  const submit = async () => {
    try {
      const values = await form.validateFields();
      const extra: Record<string, unknown> = {};
      for (const row of rows) {
        if (!row.key) continue;
        const value = normalizeConditionValue(row.key, row.value);
        if (value === undefined) continue;
        extra[row.key] = value;
      }
      const isSchedule = triggerType === 'schedule';
      const { condition, scope } = selectionToCondition(
        { target, projects, tasks, groups, extra, isSchedule },
        refs,
      );
      const payload: Partial<AutomationRule> = {
        id: String(values.id).trim(),
        description: values.description ?? '',
        enabled: values.enabled,
        trigger:
          isSchedule && scheduleMode === 'cron'
            ? { type: 'schedule', mode: 'cron', cron: String(values.cron).trim(), scope: scope || 'all' }
            : isSchedule
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

  /** 附加条件的取值控件：布尔 / 多选 / 文本 */
  const renderValueControl = (row: ExtraRow) => {
    const field = findConditionField(row.key);
    if (!field) return <Input style={{ width: 280 }} disabled placeholder="请先选字段" />;
    if (field.type === 'bool') {
      return (
        <Select
          style={{ width: 280 }}
          placeholder="选择：是 / 否"
          value={row.value === true ? 'true' : row.value === false ? 'false' : undefined}
          onChange={(v) =>
            setRows((prev) =>
              prev.map((r) => (r.id === row.id ? { ...r, value: v === 'true' } : r)),
            )
          }
          options={[
            { value: 'true', label: '是' },
            { value: 'false', label: '否' },
          ]}
        />
      );
    }
    if (field.type === 'enum-multi') {
      return (
        <Select
          mode="multiple"
          style={{ width: 280 }}
          placeholder="可多选"
          value={Array.isArray(row.value) ? (row.value as string[]) : row.value ? [String(row.value)] : []}
          onChange={(v) =>
            setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, value: v } : r)))
          }
          options={field.options ?? []}
        />
      );
    }
    return (
      <Input
        style={{ width: 280 }}
        placeholder={field.hint}
        value={String(row.value ?? '')}
        onChange={(e) =>
          setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, value: e.target.value } : r)))
        }
      />
    );
  };

  const targetHint = RULE_TARGET_OPTIONS.find((o) => o.value === target)?.hint ?? '';

  return (
    <Modal
      open={open}
      title={rule ? `编辑规则 · ${rule.id}` : '新建规则'}
      onCancel={onCancel}
      onOk={() => void submit()}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      width={720}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item
            name="id"
            label="规则 ID"
            style={{ width: 250 }}
            rules={[
              { required: true, message: '请输入规则 ID' },
              { pattern: /^[a-z0-9][a-z0-9._-]{1,63}$/, message: '小写字母/数字/._-（2-64 位）' },
            ]}
          >
            <Input placeholder="opt-unconverged-continuation" disabled={!!rule} />
          </Form.Item>
          <Form.Item name="description" label="说明" style={{ width: 420 }}>
            <Input placeholder="这条规则做什么（会显示在列表里）" />
          </Form.Item>
        </Space>

        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item label="触发方式" style={{ width: 160 }}>
            <Select
              value={triggerType}
              onChange={(v) => setTriggerType(v as 'inspection_completed' | 'schedule')}
              options={[
                { value: 'inspection_completed', label: '巡检完成后' },
                { value: 'schedule', label: '定时' },
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
                <Form.Item name="after_minutes" label="多少分钟后（一次性）" style={{ width: 190 }}>
                  <InputNumber min={1} step={5} style={{ width: '100%' }} addonAfter="分钟" />
                </Form.Item>
              )}
            </>
          )}
          <Form.Item name="action" label="动作" style={{ width: 240 }} rules={[{ required: true }]}>
            <Select
              options={actions.map((a) => ({
                value: a.name,
                label: `${a.label}（${a.name}）`,
              }))}
            />
          </Form.Item>
        </Space>

        <Space size={12} style={{ display: 'flex' }} align="start">
          <Form.Item label="作用对象" style={{ width: 220 }}>
            <Select
              value={target}
              onChange={(v) => {
                setTarget(v as RuleTargetType);
                setProjects([]);
                setTasks([]);
                setGroups([]);
              }}
              options={RULE_TARGET_OPTIONS.map((o) => ({
                value: o.value,
                label: o.label,
                title: o.hint,
              }))}
            />
          </Form.Item>
          <Form.Item
            label={
              target === 'project'
                ? '具体项目（可多选；留空 = 全部）'
                : target === 'opt'
                  ? '具体 opt 任务（可多选；留空 = 该项目下全部 opt）'
                  : '具体自由能组（可多选；留空 = 全部自由能组）'
            }
            style={{ width: 420 }}
          >
            {target === 'project' && (
              <Select
                mode="multiple"
                allowClear
                showSearch
                placeholder="选择项目"
                value={projects}
                onChange={setProjects}
                options={projectNames.map((name) => ({ value: name, label: name }))}
              />
            )}
            {target === 'opt' && (
              <Select
                mode="multiple"
                allowClear
                showSearch
                placeholder="搜索并选择任务"
                value={tasks}
                onChange={setTasks}
                optionFilterProp="label"
                options={optTasks.map((t) => ({
                  value: t.task_id,
                  label: `${t.project} / ${t.model_name}`,
                }))}
              />
            )}
            {target === 'free_energy' && (
              <Select
                mode="multiple"
                allowClear
                showSearch
                placeholder="搜索并选择自由能路径组"
                value={groups}
                onChange={setGroups}
                optionFilterProp="label"
                options={freeEnergyGroups.map((g) => ({
                  value: g.group_id,
                  label: `${g.project} / ${g.name}`,
                }))}
              />
            )}
            <div className="job-field-hint">{targetHint}</div>
          </Form.Item>
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

        <div className="job-field-hint" style={{ margin: '4px 0 6px' }}>
          附加条件（可选）：在"作用对象"之上再加限制，字段与取值都从下拉里选
        </div>
        {rows.map((row) => {
          const field = findConditionField(row.key);
          return (
            <Space key={row.id} size={8} style={{ display: 'flex', marginBottom: 6 }} align="start">
              <Select
                showSearch
                style={{ width: 210 }}
                placeholder="条件字段"
                value={row.key || undefined}
                onChange={(v) =>
                  setRows((prev) =>
                    prev.map((r) => (r.id === row.id ? { ...r, key: String(v), value: undefined } : r)),
                  )
                }
                optionFilterProp="label"
                options={CONDITION_FIELDS.map((f) => ({
                  value: f.key,
                  label: f.label,
                  title: f.hint,
                }))}
              />
              {renderValueControl(row)}
              <span className="preview-note" style={{ lineHeight: '24px', maxWidth: 160 }}>
                {field?.hint ?? ''}
              </span>
              <Button
                type="text"
                icon={<DeleteOutlined />}
                onClick={() => setRows((prev) => prev.filter((r) => r.id !== row.id))}
              />
            </Space>
          );
        })}
        <Button
          size="small"
          type="dashed"
          icon={<PlusOutlined />}
          onClick={() =>
            setRows((prev) => [...prev, { id: (seq.current += 1), key: '', value: undefined }])
          }
        >
          添加附加条件
        </Button>
      </Form>
    </Modal>
  );
}
