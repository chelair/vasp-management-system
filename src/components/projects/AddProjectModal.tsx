import { useEffect, useState } from 'react';
import { App, Button, DatePicker, Form, Input, InputNumber, Modal, Select } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { fetchServers, fetchTaskTypes, createProject } from '../../api/projects';
import type { CreateProjectPayload, ServerOption, TaskType, TaskTypeOption } from '../../types';

interface Props {
  open: boolean;
  onCancel: () => void;
  onCreated: () => void | Promise<void>;
}

const CATEGORY_ORDER: { type: TaskType; label: string }[] = [
  { type: 'opt', label: '结构优化' },
  { type: 'frac', label: '自由能' },
  { type: 'neb', label: 'NEB' },
  { type: 'ele', label: '电子结构' },
];

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
        tasks: [{ task_type: 'opt', model_name: '' }],
      });
    });
  }, [open, form]);

  const typeLabel = (type: string) =>
    taskTypeOptions.find((t) => t.type === type)?.description ?? type;

  const submit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload: CreateProjectPayload = {
        name: values.name,
        deadline: values.deadline.format('YYYY-MM-DD'),
        server: values.server,
        tasks: values.tasks.map((t: { task_type: TaskType; model_name: string }) => ({
          task_type: t.task_type,
          model_name: t.model_name,
        })),
        description: values.description || '',
        estimated_hours: values.estimated_hours ?? null,
      };
      const result = await createProject(payload);
      form.resetFields();
      onCancel();
      message.success(
        `项目「${values.name}」创建成功：${result.project_id}（${result.priority_quadrant}）`,
      );
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

        <Form.Item label="子任务（按类型分组，至少 1 个）" required style={{ marginBottom: 8 }}>
          <Form.List name="tasks">
            {(fields, { add, remove }) => (
              <div className="addproject-groups">
                {CATEGORY_ORDER.map((cat) => {
                  const catFields = fields.filter(
                    (f) => taskValues[f.name]?.task_type === cat.type,
                  );
                  return (
                    <div key={cat.type} className="addproject-group">
                      <div className="addproject-group__head">
                        <span>{cat.label}</span>
                        <Button
                          type="text"
                          size="small"
                          icon={<PlusOutlined />}
                          onClick={() => add({ task_type: cat.type, model_name: '' })}
                        >
                          添加
                        </Button>
                      </div>
                      {catFields.length === 0 && (
                        <div className="preview-note" style={{ padding: '4px 0 8px' }}>
                          暂无任务
                        </div>
                      )}
                      {catFields.map(({ key, name, ...restField }) => (
                        <div key={key} className="task-form-row">
                          <Form.Item
                            {...restField}
                            name={[name, 'task_type']}
                            hidden
                          >
                            <Input />
                          </Form.Item>
                          <span className="addproject-group__type">{typeLabel(cat.type)}</span>
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
