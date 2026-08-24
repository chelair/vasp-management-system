import { useMemo, useState } from 'react';
import { Alert, App, Form, Input, Modal, Select } from 'antd';
import type { Project, TaskType, TaskTypeOption } from '../../types';
import { JOB_DIRS } from '../../data/mock/cluster';

interface Props {
  open: boolean;
  project: Project | null;
  taskTypes: TaskTypeOption[];
  onCancel: () => void;
  onCreate: (payload: {
    modelName: string;
    taskType: TaskType;
    localDir: string;
    remoteDir: string;
  }) => void;
}

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_]*$/;

export default function NewTaskModal({ open, project, taskTypes, onCancel, onCreate }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [taskType, setTaskType] = useState<TaskType>('structure_opt');
  const name = Form.useWatch('modelName', form) ?? '';

  const availableTypes = useMemo(
    () =>
      taskTypes.filter(
        (t) =>
          t.type !== 'frequency' &&
          // 自由能自动衔接频率，不允许直接新建；仅放开结构优化/电子结构/自由能/NEB
          ['structure_opt', 'electronic_structure', 'free_energy', 'neb'].includes(t.type),
      ),
    [taskTypes],
  );

  const exists = useMemo(() => {
    if (!project || !name) return false;
    return project.tasks.some((t) => t.model_name === name);
  }, [project, name]);

  const localDir = project
    ? `${JOB_DIRS.localRoot}/${project.name}/${taskType}/${name || '<名称>'}`
    : '';
  const remoteDir = project
    ? `${JOB_DIRS.remoteBase}/${project.name}/${taskType}/${name || '<名称>'}`
    : '';

  const submit = async () => {
    try {
      const values = await form.validateFields();
      onCreate({
        modelName: values.modelName as string,
        taskType: values.taskType as TaskType,
        localDir: localDir.replace('/<名称>', `/${values.modelName}`),
        remoteDir: remoteDir.replace('/<名称>', `/${values.modelName}`),
      });
      form.resetFields();
      setTaskType('structure_opt');
    } catch {
      // 校验失败时由表单展示错误
      message.warning('请检查子项名称与类型');
    }
  };

  return (
    <Modal
      title={`新建子项 · ${project?.name ?? ''}`}
      open={open}
      onCancel={() => {
        form.resetFields();
        setTaskType('structure_opt');
        onCancel();
      }}
      onOk={submit}
      okText="创建子项"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }} initialValues={{ taskType: 'structure_opt' }}>
        <Form.Item
          name="modelName"
          label="子项名称"
          rules={[
            { required: true, message: '请输入子项名称' },
            {
              pattern: NAME_PATTERN,
              message: '仅支持字母、数字、下划线，且不能以数字开头',
            },
            {
              validator: () =>
                exists ? Promise.reject(new Error('当前项目已存在同名子项')) : Promise.resolve(),
            },
          ]}
        >
          <Input placeholder="如 Ag111 / Ag111_con1" allowClear />
        </Form.Item>
        <Form.Item
          name="taskType"
          label="作业类型"
          rules={[{ required: true, message: '请选择作业类型' }]}
        >
          <Select
            onChange={(v: TaskType) => setTaskType(v)}
            options={availableTypes.map((t) => ({
              value: t.type,
              label: (
                <div>
                  <div>{t.description}</div>
                  <div className="select-option-hint">权重 {t.workload_weight}</div>
                </div>
              ),
            }))}
          />
        </Form.Item>
      </Form>

      <div className="job-path-preview">
        <div>
          <span>本地目录</span>
          <code>{localDir}</code>
        </div>
        <div>
          <span>远程目录</span>
          <code>{remoteDir}</code>
        </div>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginTop: 14 }}
        message="框架阶段"
        description="创建后仅在当前会话生成子项并进入编辑区；正式版将调用后端在本地与远程服务器建立目录。频率计算与自由能绑定，需从自由能任务续算生成。"
      />
    </Modal>
  );
}
