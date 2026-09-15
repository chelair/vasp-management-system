import { useEffect, useState } from 'react';
import { App, Button, DatePicker, Form, Input, InputNumber, Modal, Select, Tooltip } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { fetchServers, fetchTaskTypes, createProject } from '../../api/projects';
import { createFreeEnergyGroup, createNebGroup } from '../../api/groups';
import type { CreateProjectPayload, ServerOption, TaskType, TaskTypeOption } from '../../types';

interface Props {
  open: boolean;
  onCancel: () => void;
  onCreated: () => void | Promise<void>;
}

/** 子任务分类：opt/ele 是单个任务；free_energy/neb 走"建组"（组内任务由后端一并登记） */
type RowKind = 'opt' | 'ele' | 'free_energy' | 'neb';

interface CategoryDef {
  kind: RowKind;
  label: string;
  /** 该分类下每行填什么、会自动登记哪些任务 */
  hint: string;
  /** 组类分类的默认数量（自由能结构数 / NEB 映像数） */
  countDefault?: number;
  countLabel?: string;
}

const CATEGORY_ORDER: CategoryDef[] = [
  { kind: 'opt', label: '结构优化', hint: '单个结构优化任务，一行一个任务' },
  {
    kind: 'free_energy',
    label: '自由能路径',
    hint: '按组创建：每个结构自动登记「结构优化 + 频率矫正」两个任务（频率矫正作为子项）',
    countDefault: 1,
    countLabel: '结构数',
  },
  {
    kind: 'neb',
    label: 'NEB',
    hint: '按组创建：自动登记初态/末态优化 + NEB 计算任务',
    countDefault: 6,
    countLabel: '映像数',
  },
  { kind: 'ele', label: '电子结构', hint: '单个电子结构任务，一行一个任务' },
];

interface TaskRow {
  kind: RowKind;
  /** opt / ele：模型名 */
  model_name?: string;
  /** free_energy / neb：组名 */
  group_name?: string;
  /** 组内数量（自由能=结构数，NEB=映像数） */
  count?: number;
}

/** 新增项目（与总览共用）：截止日期点选式，子任务按四种类型树状分组 */
export default function AddProjectModal({ open, onCancel, onCreated }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [serverOptions, setServerOptions] = useState<ServerOption[]>([]);
  const [taskTypeOptions, setTaskTypeOptions] = useState<TaskTypeOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const taskValues = Form.useWatch('tasks', form) ?? [];

  useEffect(() => {
    if (!open) return;
    Promise.all([fetchServers(), fetchTaskTypes()]).then(([servers, types]) => {
      setServerOptions(servers);
      setTaskTypeOptions(types);
      form.setFieldsValue({
        server: servers[0]?.name ?? 'server1',
        tasks: [{ kind: 'opt', model_name: '' }],
      });
    });
  }, [open, form]);

  const typeLabel = (type: string) =>
    taskTypeOptions.find((t) => t.type === type)?.description ?? type;

  const submit = async () => {
    try {
      const values = await form.validateFields();
      const rows: TaskRow[] = values.tasks ?? [];
      // 单个任务（结构优化 / 电子结构）
      const plainTasks = rows
        .filter((r) => r.kind === 'opt' || r.kind === 'ele')
        .map((r) => ({ task_type: r.kind as TaskType, model_name: r.model_name as string }));
      // 组（自由能路径 / NEB）：项目建好后调 /api/groups，由后端一并登记组内任务
      const groupRows = rows.filter((r) => r.kind === 'free_energy' || r.kind === 'neb');
      if (plainTasks.length === 0 && groupRows.length === 0) {
        message.error('请至少添加 1 个子任务或 1 个组');
        return;
      }
      setSubmitting(true);
      const payload: CreateProjectPayload = {
        name: values.name,
        deadline: values.deadline.format('YYYY-MM-DD'),
        server: values.server,
        tasks: plainTasks,
        description: values.description || '',
        estimated_hours: values.estimated_hours ?? null,
      };
      const result = await createProject(payload);

      // 组创建（自由能：每个结构自动登记 opt + frac；NEB：初/末态优化 + NEB 任务）
      const warnings: string[] = [];
      let groupTaskCount = 0;
      for (const row of groupRows) {
        try {
          const created =
            row.kind === 'free_energy'
              ? await createFreeEnergyGroup({
                  project: values.name,
                  name: row.group_name || undefined,
                  structures: Number(row.count ?? 1),
                  aux_molecules: [],
                })
              : await createNebGroup({
                  project: values.name,
                  name: row.group_name || undefined,
                  images: Number(row.count ?? 6),
                });
          groupTaskCount += created.task_count;
          warnings.push(...(created.warnings ?? []));
        } catch (err) {
          warnings.push(
            `${row.group_name || row.kind}：${err instanceof Error ? err.message : '组创建失败'}`,
          );
        }
      }
      form.resetFields();
      onCancel();
      message.success(
        `项目「${values.name}」创建成功：${result.project_id}（${result.priority_quadrant}）` +
          (groupTaskCount ? `，组内任务 ${groupTaskCount} 个` : ''),
      );
      if (warnings.length) message.warning(warnings.join('；'));
      await onCreated();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新增项目"
      open={open}
      onOk={() => void submit()}
      onCancel={() => {
        onCancel();
        form.resetFields();
      }}
      confirmLoading={submitting}
      okText="创建"
      cancelText="取消"
      width={640}
      forceRender
    >
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        <div className="form-row">
          <Form.Item
            label="项目名称"
            name="name"
            rules={[
              { required: true, message: '请输入项目名称' },
              {
                pattern: /^[A-Za-z0-9][A-Za-z0-9_]*$/,
                message: '以字母/数字开头，仅含字母、数字、下划线',
              },
            ]}
          >
            <Input placeholder="如 Ag_20260830" />
          </Form.Item>
          <Form.Item
            label="截止日期"
            name="deadline"
            rules={[{ required: true, message: '请选择截止日期' }]}
          >
            <DatePicker style={{ width: '100%' }} placeholder="选择截止日期" />
          </Form.Item>
        </div>
        <Form.Item
          label="计算服务器"
          name="server"
          rules={[{ required: true, message: '请选择计算服务器' }]}
        >
          <Select
            placeholder="选择服务器"
            options={serverOptions.map((s) => ({
              value: s.name,
              label: `${s.name} (${s.user}@${s.host})`,
            }))}
          />
        </Form.Item>

        <Form.Item
          label="子任务 / 计算组（按类型分组，至少 1 项）"
          required
          style={{ marginBottom: 8 }}
        >
          <Form.List name="tasks">
            {(fields, { add, remove }) => (
              <div className="addproject-groups">
                {CATEGORY_ORDER.map((cat) => {
                  const catFields = fields.filter(
                    (f) => (taskValues[f.name] as TaskRow | undefined)?.kind === cat.kind,
                  );
                  const isGroup = cat.kind === 'free_energy' || cat.kind === 'neb';
                  return (
                    <div key={cat.kind} className="addproject-group">
                      <div className="addproject-group__head">
                        <Tooltip title={cat.hint}>
                          <span>{cat.label}</span>
                        </Tooltip>
                        <Button
                          type="text"
                          size="small"
                          icon={<PlusOutlined />}
                          onClick={() =>
                            add(
                              isGroup
                                ? { kind: cat.kind, group_name: '', count: cat.countDefault }
                                : { kind: cat.kind, model_name: '' },
                            )
                          }
                        >
                          添加
                        </Button>
                      </div>
                      {catFields.length === 0 && (
                        <div className="preview-note" style={{ padding: '4px 0 8px' }}>
                          {isGroup ? '暂无组' : '暂无任务'}
                        </div>
                      )}
                      {catFields.map(({ key, name, ...restField }) => (
                        <div key={key} className="task-form-row">
                          <Form.Item {...restField} name={[name, 'kind']} hidden>
                            <Input />
                          </Form.Item>
                          <span className="addproject-group__type">
                            {isGroup ? '组' : typeLabel(cat.kind)}
                          </span>
                          {isGroup ? (
                            <>
                              <Form.Item
                                {...restField}
                                name={[name, 'group_name']}
                                rules={[
                                  { required: true, message: '请输入组名' },
                                  {
                                    pattern: /^[A-Za-z0-9][A-Za-z0-9_@]*$/,
                                    message: '以字母/数字开头，仅含字母、数字、下划线、@',
                                  },
                                ]}
                                style={{ flex: 1, marginBottom: 8 }}
                              >
                                <Input placeholder="组名，如 PATH1" />
                              </Form.Item>
                              <Form.Item
                                {...restField}
                                name={[name, 'count']}
                                rules={[{ required: true, message: '请输入数量' }]}
                                style={{ width: 132, marginBottom: 8 }}
                              >
                                <InputNumber
                                  min={1}
                                  max={50}
                                  style={{ width: '100%' }}
                                  addonAfter={cat.countLabel}
                                />
                              </Form.Item>
                            </>
                          ) : (
                            <Form.Item
                              {...restField}
                              name={[name, 'model_name']}
                              rules={[
                                { required: true, message: '请输入模型名称' },
                                {
                                  pattern: /^[A-Za-z0-9][A-Za-z0-9_@]*$/,
                                  message: '以字母/数字开头，仅含字母、数字、下划线、@',
                                },
                              ]}
                              style={{ flex: 1, marginBottom: 8 }}
                            >
                              <Input placeholder="模型名称，如 Ag@Al2O3" />
                            </Form.Item>
                          )}
                          {fields.length > 1 && (
                            <Button
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() => remove(name)}
                              style={{ marginBottom: 8 }}
                              aria-label="删除该子任务"
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            )}
          </Form.List>
        </Form.Item>

        <div className="form-row">
          <Form.Item label="预计耗时（小时，可选）" name="estimated_hours">
            <InputNumber min={1} max={2000} style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item label="项目描述（可选）" name="description">
            <Input placeholder="研究内容简述" />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
