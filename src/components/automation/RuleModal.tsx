import { useEffect, useMemo, useState } from 'react';
import { App, Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space, TimePicker, Tooltip, TreeSelect } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ActionCatalogItem, AutomationRule } from '../../api/automation';
import {
  WEEKDAY_LABELS,
  cronToSchedule,
  describeSchedule,
  scheduleToCron,
  type ScheduleKind,
  type ScheduleSpec,
} from '../../utils/schedule';
import {
  CONDITION_FIELDS,
  RULE_TARGET_OPTIONS,
  conditionToSelection,
  findConditionField,
  normalizeConditionValue,
  selectionToCondition,
  toFormValue,
  buildFreeEnergyGroupTree,
  buildOptTaskTree,
  buildNebTaskTree,
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
  const [scheduleMode, setScheduleMode] = useState<'repeat' | 'after'>('repeat');
  /** 周期任务的人话设定（界面里不出现调度表达式） */
  const [repeatKind, setRepeatKind] = useState<ScheduleKind>('daily');
  const [repeatEvery, setRepeatEvery] = useState(30);
  const [repeatUnit, setRepeatUnit] = useState<'minutes' | 'hours'>('minutes');
  const [repeatTime, setRepeatTime] = useState('02:00');
  const [repeatWeekday, setRepeatWeekday] = useState(1);
  const [repeatDay, setRepeatDay] = useState(1);
  const [customExpression, setCustomExpression] = useState('');
  /** 主动作成功后是否自动提交作业（续算后一般都要提交） */
  const [followUpSubmit, setFollowUpSubmit] = useState(false);
  const [mainAction, setMainAction] = useState<string>('');
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
  /** 任务/组都做成"项目 → 组 → 任务"的树，避免长列表里翻找 */
  const optTaskTree = useMemo(() => buildOptTaskTree(refs), [refs]);
  const nebTaskTree = useMemo(() => buildNebTaskTree(refs), [refs]);
  const freeEnergyGroupTree = useMemo(() => buildFreeEnergyGroupTree(refs), [refs]);

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
      (rawTrigger.mode as 'repeat' | 'after') ||
        (rawTrigger.after_seconds || rawTrigger.mode === 'after' ? 'after' : 'repeat'),
    );
    // 新建规则时还没有表达式 → 默认『每天 02:00』，不要落到自定义
    const parsed = rawTrigger.cron
      ? cronToSchedule(rawTrigger.cron)
      : { kind: 'daily' as const, hour: 2, minute: 0 };
    setRepeatKind(parsed.kind === 'custom' ? 'custom' : parsed.kind);
    setRepeatEvery(parsed.every ?? 30);
    setRepeatUnit(parsed.kind === 'hours' ? 'hours' : 'minutes');
    setRepeatTime(`${String(parsed.hour ?? 2).padStart(2, '0')}:${String(parsed.minute ?? 0).padStart(2, '0')}`);
    setRepeatWeekday(parsed.weekday ?? 1);
    setRepeatDay(parsed.day ?? 1);
    setCustomExpression(parsed.kind === 'custom' ? parsed.expression ?? '' : '');
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
    setFollowUpSubmit(rule?.follow_up_action === 'task.submit');
    setMainAction(rule?.action ?? actions[0]?.name ?? '');
    form.setFieldsValue({
      id: rule?.id ?? '',
      description: rule?.description ?? '',
      action: rule?.action ?? actions[0]?.name,
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
      const repeatSpec: ScheduleSpec =
        repeatKind === 'custom'
          ? { kind: 'custom', expression: customExpression }
          : repeatKind === 'minutes' || repeatKind === 'hours'
            ? { kind: repeatKind, every: repeatEvery }
            : repeatKind === 'weekly'
              ? {
                  kind: 'weekly',
                  weekday: repeatWeekday,
                  hour: Number(repeatTime.slice(0, 2)),
                  minute: Number(repeatTime.slice(3, 5)),
                }
              : repeatKind === 'monthly'
                ? { kind: 'monthly', day: repeatDay, hour: Number(repeatTime.slice(0, 2)), minute: Number(repeatTime.slice(3, 5)) }
                : { kind: 'daily', hour: Number(repeatTime.slice(0, 2)), minute: Number(repeatTime.slice(3, 5)) };
      const cronExpression = scheduleToCron(repeatSpec);
      const { condition, scope } = selectionToCondition(
        { target, projects, tasks, groups, extra, isSchedule },
        refs,
      );
      const payload: Partial<AutomationRule> = {
        id: String(values.id).trim(),
        description: values.description ?? '',
        enabled: values.enabled,
        trigger:
          isSchedule && scheduleMode === 'repeat'
            ? { type: 'schedule', mode: 'cron', cron: cronExpression, scope: scope || 'all' }
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
        follow_up_action: followUpSubmit && values.action !== 'task.submit' ? 'task.submit' : null,
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
      width={800}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Space wrap size={12} style={{ display: 'flex' }} align="start">
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

        <Space wrap size={12} style={{ display: 'flex' }} align="start">
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
              <Form.Item label="什么时候执行" style={{ width: 190 }}>
                <Select
                  value={scheduleMode}
                  onChange={(v) => setScheduleMode(v as 'repeat' | 'after')}
                  options={[
                    { value: 'repeat', label: '按周期重复' },
                    { value: 'after', label: '稍后执行一次' },
                  ]}
                />
              </Form.Item>
              {scheduleMode === 'after' && (
                <Form.Item name="after_minutes" label="多少分钟后执行一次" style={{ width: 190 }}>
                  <InputNumber min={1} step={5} style={{ width: '100%' }} addonAfter="分钟" />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && (
                <Form.Item label="重复方式" style={{ width: 170 }}>
                  <Select
                    value={repeatKind}
                    onChange={(v) => setRepeatKind(v as ScheduleKind)}
                    options={[
                      { value: 'minutes', label: '每隔几分钟' },
                      { value: 'hours', label: '每隔几小时' },
                      { value: 'daily', label: '每天' },
                      { value: 'weekly', label: '每周' },
                      { value: 'monthly', label: '每月' },
                      { value: 'custom', label: '高级：手动填写表达式' },
                    ]}
                  />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && repeatKind === 'custom' && (
                <Form.Item label="表达式（高级）" style={{ width: 200 }}>
                  <Input
                    value={customExpression}
                    placeholder="仅在标准选项满足不了时使用"
                    onChange={(e) => setCustomExpression(e.target.value)}
                  />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && (repeatKind === 'minutes' || repeatKind === 'hours') && (
                <Form.Item label="间隔" style={{ width: 190 }}>
                  <Space.Compact>
                    <InputNumber
                      min={1}
                      max={repeatUnit === 'minutes' ? 59 : 23}
                      value={repeatEvery}
                      onChange={(v) => setRepeatEvery(Number(v) || 1)}
                      style={{ width: 90 }}
                    />
                    <Select
                      value={repeatUnit}
                      onChange={(v) => {
                        const unit = v as 'minutes' | 'hours';
                        setRepeatUnit(unit);
                        setRepeatKind(unit);
                      }}
                      options={[
                        { value: 'minutes', label: '分钟' },
                        { value: 'hours', label: '小时' },
                      ]}
                      style={{ width: 80 }}
                    />
                  </Space.Compact>
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && repeatKind === 'weekly' && (
                <Form.Item label="星期几" style={{ width: 130 }}>
                  <Select
                    value={repeatWeekday}
                    onChange={(v) => setRepeatWeekday(Number(v))}
                    options={WEEKDAY_LABELS.map((label, index) => ({ value: index, label }))}
                  />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && repeatKind === 'monthly' && (
                <Form.Item label="每月几号" style={{ width: 130 }}>
                  <InputNumber min={1} max={28} value={repeatDay} onChange={(v) => setRepeatDay(Number(v) || 1)} style={{ width: '100%' }} />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && (repeatKind === 'daily' || repeatKind === 'weekly' || repeatKind === 'monthly') && (
                <Form.Item label="时间" style={{ width: 130 }}>
                  <TimePicker
                    format="HH:mm"
                    minuteStep={5}
                    allowClear={false}
                    value={dayjs(repeatTime, 'HH:mm')}
                    onChange={(value) => setRepeatTime(value ? value.format('HH:mm') : '02:00')}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              )}
              {scheduleMode === 'repeat' && (
                <span className="preview-note" style={{ lineHeight: '30px' }}>
                  将按「{describeSchedule(repeatKind === 'custom' ? { kind: 'custom', expression: customExpression } : repeatKind === 'minutes' || repeatKind === 'hours' ? { kind: repeatKind, every: repeatEvery } : repeatKind === 'weekly' ? { kind: 'weekly', weekday: repeatWeekday, hour: Number(repeatTime.slice(0,2)), minute: Number(repeatTime.slice(3,5)) } : repeatKind === 'monthly' ? { kind: 'monthly', day: repeatDay, hour: Number(repeatTime.slice(0,2)), minute: Number(repeatTime.slice(3,5)) } : { kind: 'daily', hour: Number(repeatTime.slice(0,2)), minute: Number(repeatTime.slice(3,5)) })}」执行
                </span>
              )}
            </>
          )}
          <Form.Item name="action" label="动作" style={{ width: 240 }} rules={[{ required: true }]}>
            <Select
              onChange={(value) => setMainAction(String(value))}
              options={actions.map((a) => ({
                value: a.name,
                label: `${a.label}（${a.name}）`,
              }))}
            />
          </Form.Item>
          <Form.Item label=" " style={{ width: 220 }}>
            <Tooltip
              title={
                mainAction === 'task.submit'
                  ? '动作本身就是提交作业，不需要再接一次'
                  : '主动作成功后自动执行「提交作业」（续算完成后一般都要提交）'
              }
            >
              <Checkbox
                checked={followUpSubmit && mainAction !== 'task.submit'}
                disabled={mainAction === 'task.submit'}
                onChange={(e) => setFollowUpSubmit(e.target.checked)}
              >
                执行成功后自动提交作业
              </Checkbox>
            </Tooltip>
          </Form.Item>
        </Space>

        <Space wrap size={12} style={{ display: 'flex' }} align="start">
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
                  : target === 'neb'
                    ? '具体 NEB 任务（可多选；留空 = 该项目下全部 NEB）'
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
              <TreeSelect
                multiple
                allowClear
                showSearch
                treeDefaultExpandAll={false}
                treeNodeFilterProp="title"
                placeholder="按 项目 → 组 → 任务 选择（可直接搜索任务名）"
                value={tasks}
                onChange={(value) => setTasks((value as string[]) ?? [])}
                treeData={optTaskTree}
                maxTagCount="responsive"
              />
            )}
            {target === 'neb' && (
              <TreeSelect
                multiple
                allowClear
                showSearch
                treeDefaultExpandAll={false}
                treeNodeFilterProp="title"
                placeholder="按 项目 → NEB 组 → 任务 选择（可直接搜索任务名）"
                value={tasks}
                onChange={(value) => setTasks((value as string[]) ?? [])}
                treeData={nebTaskTree}
                maxTagCount="responsive"
              />
            )}
            {target === 'free_energy' && (
              <TreeSelect
                multiple
                allowClear
                showSearch
                treeDefaultExpandAll={false}
                treeNodeFilterProp="title"
                placeholder="按 项目 → 自由能组 选择（可直接搜索组名）"
                value={groups}
                onChange={(value) => setGroups((value as string[]) ?? [])}
                treeData={freeEnergyGroupTree}
                maxTagCount="responsive"
              />
            )}
            <div className="job-field-hint">{targetHint}</div>
          </Form.Item>
        </Space>

        <Space wrap size={12} style={{ display: 'flex' }} align="start">
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
