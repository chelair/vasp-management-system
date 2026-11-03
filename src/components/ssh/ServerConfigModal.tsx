import { useEffect } from 'react';
import { Collapse, Form, Input, InputNumber, Modal, Radio, Select } from 'antd';
import type { AuthType, ServerConfig } from '../../types';

export type ServerFormValues = Pick<ServerConfig,
  'name' | 'host' | 'port' | 'user' | 'authType' | 'keyPath' | 'password' | 'queueSystem' | 'remoteBase' | 'home'
>;

interface Props {
  open: boolean;
  editing: ServerConfig | null;
  servers: ServerConfig[];
  onCancel: () => void;
  onSave: (values: ServerFormValues) => void;
}

export default function ServerConfigModal({ open, editing, servers, onCancel, onSave }: Props) {
  const [form] = Form.useForm<ServerFormValues>();
  const authType = (Form.useWatch('authType', form) as AuthType | undefined) ?? 'key';

  useEffect(() => {
    if (open) {
      form.resetFields();
      if (editing) form.setFieldsValue(editing);
    }
  }, [open, editing, form]);

  return (
    <Modal title={editing ? `编辑服务器 · ${editing.name}` : '新建服务器'} className="ssh-config-modal" open={open} onOk={() => form.submit()} onCancel={onCancel} okText="保存配置" cancelText="取消" width={560} forceRender>
      <Form form={form} layout="vertical" initialValues={{ port: 22, authType: 'key', queueSystem: 'lsf' }} onFinish={onSave}>
        <p className="ssh-form-intro">填写服务器地址与登录方式，保存后可在详情中测试连接。</p>
        <Form.Item label="服务器名称" name="name" rules={[
          { required: true, message: '请输入服务器名称' },
          { pattern: /^[A-Za-z0-9_-]+$/, message: '仅允许字母、数字、下划线、连字符' },
          { validator: (_, value) => servers.some((s) => s.name === value && s.id !== editing?.id) ? Promise.reject(new Error('服务器名称已存在')) : Promise.resolve() },
        ]}><Input placeholder="如 server1" /></Form.Item>
        <Form.Item label="主机地址" name="host" rules={[{ required: true, message: '请输入主机地址' }]}><Input placeholder="服务器域名或 IP 地址" /></Form.Item>
        <div className="ssh-form-row">
          <Form.Item label="登录用户" name="user" rules={[{ required: true, message: '请输入用户名' }]}><Input placeholder="如 mdye" /></Form.Item>
          <Form.Item label="端口" name="port" rules={[{ required: true, message: '请输入端口' }]}><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item>
        </div>
        <Form.Item label="认证方式" name="authType"><Radio.Group optionType="button" options={[{ value: 'key', label: '密钥文件' }, { value: 'password', label: '密码' }]} /></Form.Item>
        {authType === 'key' ? (
          <Form.Item label="私钥路径" name="keyPath" extra="填写运行此系统的机器上可访问的私钥文件路径。" rules={[{ required: true, message: '请输入私钥路径' }]}><Input placeholder="~/.ssh/id_rsa" /></Form.Item>
        ) : (
          <Form.Item label="密码" name="password" rules={[{ required: !editing?.passwordConfigured, message: '请输入密码' }]}><Input.Password placeholder={editing?.passwordConfigured ? '已配置，留空保留原密码' : '输入登录密码'} autoComplete="new-password" /></Form.Item>
        )}
        <Form.Item label="队列系统" name="queueSystem"><Select options={[{ value: 'lsf', label: 'LSF (IBM)' }, { value: 'slurm', label: 'SLURM' }, { value: 'pbs', label: 'PBS / Torque' }, { value: 'other', label: '其他' }]} /></Form.Item>
        <Form.Item label="项目远程根目录" name="remoteBase" extra="新建项目的计算目录将位于此路径下。"><Input placeholder="/data/gpfs03/mdye/projects" /></Form.Item>
        <Collapse ghost items={[{ key: 'advanced', label: '更多设置', children: <Form.Item label="用户主目录" name="home"><Input placeholder="/data/gpfs03/mdye" /></Form.Item> }]} />
      </Form>
    </Modal>
  );
}
