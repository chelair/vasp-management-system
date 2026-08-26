import { useMemo, useState } from 'react';
import { Alert, App, Form, Input, Modal, Select } from 'antd';
import type { EleSubtype, Project, TaskType, TaskTypeOption } from '../../types';

interface Props {
  open: boolean;
  project: Project | null;
  taskTypes: TaskTypeOption[];
  initialType?: TaskType;
  onCancel: () => void;
  onCreate: (payload: {
    modelName: string;
    taskType: TaskType;
    subtype?: EleSubtype | null;
  }) => void;
}

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_@]*$/;
const CATEGORY_DIR: Record<TaskType, string> = {
  opt: 'opt',
  frac: 'free_energy',
  neb: 'neb',
  ele: 'ele',
};

export default function NewTaskModal({
  open,
  project,
  taskTypes,
  initialType = 'opt',
  onCancel,
  onCreate,
}: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [taskType, setTaskType] = useState<TaskType>(initialType);
  const name = Form.useWatch('modelName', form) ?? '';

  const availableTypes = useMemo(
    () => taskTypes.filter((t) => ['opt', 'frac', 'neb', 'ele'].includes(t.type)),
    [taskTypes],
  );

  const selectedOption = availableTypes.find((t) => t.type === taskType);
  const exists = useMemo(() => {
    if (!project || !name) return false;
    return project.tasks.some((t) => t.model_name === name);
  }, [project, name]);

  const localDir = project
    ? `${project.name}/${CATEGORY_DIR[taskType]}/${name || '<名称>'}`
    : '';
  const remoteDir = project
    ? `${project.name}/${CATEGORY_DIR[taskType]}/${name || '<名称>'}`
    : '';

  const submit = async () => {
    try {
      const values = await form.validateFields();
      onCreate({
        modelName: values.modelName as string,
        taskType: values.taskType as TaskType,
        subtype: (values.subtype as EleSubtype | undefined) ?? null,
      });
      form.resetFields();
      setTaskType(initialType);
    } catch {
      message.warning('请检查子项名称与类型');
    }
  };

  return (
    <Modal
      title={`新建子项 · ${project?.name ?? ''}`}
      open={open}
      onCancel={() => {
        form.resetFields();
        setTaskType(initialType);
        onCancel();
      }}
      onOk={submit}
      okText="创建子项"
      cancelText="取消"
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 8 }}
        initialValues={{ taskType: initialType }}
      >
        <Form.Item
          name="modelName"
          label="子项名称"
          rules={[
            { required: true, message: '请输入子项名称' },
            {
              pattern: NAME_PATTERN,
              message: '仅支持字母、数字、下划线、@，且不能以数字开头',
            },
            {
              validator: () =>
                exists ? Promise.reject(new Error('当前项目已存在同名子项')) : Promise.resolve(),
            },
          ]}
        >
          <Input placeholder="如 Ag111 / Ag@Al2O3_opt" allowClear />
        </Form.Item>
        <Form.Item
          name="taskType"
          label="任务类型"
          rules={[{ required: true, message: '请选择任务类型' }]}
        >
          <Select
            onChange={(v: TaskType) => {
              setTaskType(v);
              if (v !== 'ele') form.setFieldValue('subtype', undefined);
            }}
            options={availableTypes.map((t) => ({ value: t.type, label: t.description }))}
          />
        </Form.Item>
        {taskType === 'ele' && (
          <Form.Item name="subtype" label="后处理子类型">
            <Select
              allowClear
              placeholder="选择后处理类型（PDOS / Bader / 差分电荷 / 功函数）"
              options={(selectedOption?.subtypes ?? []).map((s) => ({
                value: s,
                label: selectedOption?.subtype_labels?.[s] ?? s,
              }))}
            />
          </Form.Item>
        )}
      </Form>

      <div className="job-path-preview">
        <div>
          <span>本地目录（相对根）</span>
          <code>{localDir}</code>
        </div>
        <div>
          <span>远程目录（相对根）</span>
          <code>{remoteDir}</code>
        </div>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginTop: 14 }}
        message="独立任务"
        description="创建后由后端在本地与远程建立目录并生成默认 INCAR/KPOINTS；复杂流程请使用「新建自由能组 / NEB 组」。"
      />
    </Modal>
  );
}
