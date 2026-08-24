import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
} from 'antd';
import {
  CloudServerOutlined,
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  UnlockOutlined,
} from '@ant-design/icons';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatCard from '../components/common/StatCard';
import { useSSH } from '../context/SSHContext';
import type { AuthType, ConnectionTestResult, ServerConfig } from '../types';

export default function SSH() {
  const { message } = App.useApp();
  const {
    servers,
    loading,
    activeServer,
    addServer,
    updateServer,
    removeServer,
    toggleConnection,
    testConnection,
  } = useSSH();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ServerConfig | null>(null);
  const [form] = Form.useForm();
  const authType = (Form.useWatch('authType', form) as AuthType | undefined) ?? 'key';

  // 默认选中当前连接服务器（无连接时选第一个）
  useEffect(() => {
    if (servers.length > 0 && !selectedId) {
      setSelectedId(activeServer?.id ?? servers[0].id);
    }
  }, [servers, activeServer, selectedId]);

  const selected = servers.find((s) => s.id === selectedId) ?? null;

  const stats = useMemo(() => {
    const latencies = servers
      .map((s) => s.latencyMs)
      .filter((v): v is number => v != null);
    const avg = latencies.length
      ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
      : null;
    return {
      total: servers.length,
      connected: servers.filter((s) => s.connected).length,
      avg,
    };
  }, [servers]);

  const nameValidator = (_: unknown, value: string) => {
    if (!editing && value && servers.some((s) => s.name === value)) {
      return Promise.reject(new Error('服务器名称已存在'));
    }
    return Promise.resolve();
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (cfg: ServerConfig) => {
    setEditing(cfg);
    form.setFieldsValue(cfg);
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    if (editing) {
      updateServer(editing.id, values);
      message.success(`服务器「${values.name}」已更新（演示）`);
    } else {
      addServer({
        ...values,
        id: values.name,
        connected: false,
        latencyMs: null,
        lastTestAt: null,
      });
      setSelectedId(values.name);
      message.success(`服务器「${values.name}」已添加（演示）`);
    }
    setModalOpen(false);
  };

  const handleTest = async (cfg: ServerConfig) => {
    setTestingId(cfg.id);
    const result = await testConnection(cfg.id);
    setTestingId(null);
    setTestResults((prev) => ({ ...prev, [cfg.id]: result }));
    setSelectedId(cfg.id);
    if (result.ok) {
      message.success(result.message);
    } else {
      message.error(result.message);
    }
  };

  const handleToggle = (cfg: ServerConfig) => {
    toggleConnection(cfg.id);
    setSelectedId(cfg.id);
    if (cfg.connected) {
      message.info(`已断开 ${cfg.name}（演示）`);
    } else {
      message.success(`已连接 ${cfg.name}（演示）`);
    }
  };

  const handleDelete = (cfg: ServerConfig) => {
    removeServer(cfg.id);
    if (selectedId === cfg.id) {
      setSelectedId(null);
    }
    message.info(`已删除 ${cfg.name}（演示）`);
  };

  const lastTest = selected ? testResults[selected.id] : undefined;

  return (
    <PageTransition>
      <PageHeader
        title="SSH 连接"
        subtitle="配置远程计算服务器、测试握手并管理连接状态"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建服务器
          </Button>
        }
      />

      <Alert
        type="info"
        showIcon
        message="演示模式说明"
        description="连接测试为前端模拟握手；配置保存在浏览器 localStorage。正式版将由后端统一读写网站同级 data/config/servers.json，密码与私钥不落前端。"
        style={{ marginBottom: 16 }}
      />

      <div className="stats-grid stats-grid--3">
        <StatCard
          label="已配置服务器"
          value={stats.total}
          icon={<CloudServerOutlined />}
          accent="blue"
          delay={0}
        />
        <StatCard
          label="当前连接"
          value={stats.connected}
          icon={<LinkOutlined />}
          accent="teal"
          delay={0.06}
          trend={activeServer ? `${activeServer.user}@${activeServer.host}` : '未连接'}
        />
        <StatCard
          label="平均延迟"
          value={stats.avg ?? '—'}
          icon={<ThunderboltOutlined />}
          accent="green"
          delay={0.12}
          trend="最近一次握手"
        />
      </div>

      <div className="ssh-grid">
        <Card title="服务器列表" loading={loading}>
          {servers.length === 0 ? (
            <Empty description="尚未配置服务器，点击右上角新建" />
          ) : (
            <div className="ssh-server-list">
              {servers.map((s) => (
                <div
                  key={s.id}
                  className={`ssh-server-item${s.id === selectedId ? ' selected' : ''}`}
                  onClick={() => setSelectedId(s.id)}
                >
                  <div className="ssh-server-item__head">
                    <span className={`ssh-status-dot${s.connected ? ' on' : ''}`} />
                    <span className="ssh-server-item__name">{s.name}</span>
                    {s.connected && <span className="ssh-active-badge">当前连接</span>}
                  </div>
                  <div className="ssh-server-item__host">
                    {s.user}@{s.host}:{s.port}
                  </div>
                  <div className="ssh-server-item__meta">
                    {String(s.queueSystem).toUpperCase()} ·{' '}
                    {s.authType === 'key' ? '密钥认证' : '密码认证'}
                    {s.latencyMs != null ? ` · ${s.latencyMs}ms` : ' · 未测试'}
                  </div>
                  <div className="ssh-server-item__actions" onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="small"
                      type={s.connected ? 'default' : 'primary'}
                      icon={s.connected ? <UnlockOutlined /> : <LinkOutlined />}
                      onClick={() => handleToggle(s)}
                    >
                      {s.connected ? '断开' : '连接'}
                    </Button>
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      loading={testingId === s.id}
                      onClick={() => handleTest(s)}
                    >
                      测试
                    </Button>
                    <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(s)} />
                    <Popconfirm
                      title="删除该服务器配置？"
                      description="删除后需重新填写连接信息"
                      onConfirm={() => handleDelete(s)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title={`连接详情${selected ? ` · ${selected.name}` : ''}`} loading={loading}>
          {selected ? (
            <>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="主机地址">{selected.host}</Descriptions.Item>
                <Descriptions.Item label="端口">{selected.port}</Descriptions.Item>
                <Descriptions.Item label="用户名">{selected.user}</Descriptions.Item>
                <Descriptions.Item label="认证方式">
                  {selected.authType === 'key'
                    ? `密钥文件 · ${selected.keyPath ?? '—'}`
                    : '密码认证'}
                </Descriptions.Item>
                <Descriptions.Item label="队列系统">
                  {String(selected.queueSystem).toUpperCase()}
                </Descriptions.Item>
                <Descriptions.Item label="用户主目录">{selected.home ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="项目远程根目录">
                  {selected.remoteBase ?? '—'}
                </Descriptions.Item>
                <Descriptions.Item label="连接状态">
                  <span
                    className={`status-tag${selected.connected ? ' status-tag--normal' : ' status-tag--pending'}`}
                  >
                    <span className="status-tag__dot" />
                    {selected.connected ? '已连接' : '未连接'}
                  </span>
                </Descriptions.Item>
                <Descriptions.Item label="最近延迟">
                  {selected.latencyMs != null ? `${selected.latencyMs} ms` : '—'}
                </Descriptions.Item>
                <Descriptions.Item label="最近测试">{selected.lastTestAt ?? '—'}</Descriptions.Item>
              </Descriptions>

              {lastTest && (
                <Alert
                  className="ssh-test-result"
                  type={lastTest.ok ? 'success' : 'error'}
                  showIcon
                  message={`测试结果 · ${lastTest.latencyMs}ms`}
                  description={lastTest.message}
                />
              )}

              <div className="ssh-detail-actions">
                <Button
                  icon={<ReloadOutlined />}
                  loading={testingId === selected.id}
                  onClick={() => handleTest(selected)}
                >
                  测试连接
                </Button>
                <Button
                  type={selected.connected ? 'default' : 'primary'}
                  icon={selected.connected ? <UnlockOutlined /> : <LinkOutlined />}
                  onClick={() => handleToggle(selected)}
                >
                  {selected.connected ? '断开连接' : '连接服务器'}
                </Button>
                <Button icon={<EditOutlined />} onClick={() => openEdit(selected)}>
                  编辑配置
                </Button>
              </div>
            </>
          ) : (
            <Empty description="请选择或新建服务器" />
          )}
        </Card>
      </div>

      <Modal
        title={editing ? `编辑服务器 · ${editing.name}` : '新建服务器'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            label="服务器名称"
            name="name"
            rules={[
              { required: true, message: '请输入服务器名称' },
              {
                pattern: /^[A-Za-z0-9_-]+$/,
                message: '仅允许字母、数字、下划线、连字符',
              },
              { validator: nameValidator },
            ]}
          >
            <Input placeholder="如 server1" />
          </Form.Item>
          <Form.Item
            label="主机地址"
            name="host"
            rules={[{ required: true, message: '请输入主机地址' }]}
          >
            <Input placeholder="hpc.xmu.edu.cn 或 192.168.1.100" />
          </Form.Item>
          <div className="form-row">
            <Form.Item
              label="端口"
              name="port"
              initialValue={22}
              rules={[{ required: true, message: '请输入端口' }]}
            >
              <InputNumber min={1} max={65535} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              label="用户名"
              name="user"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input placeholder="如 mdye" />
            </Form.Item>
          </div>
          <Form.Item label="认证方式" name="authType" initialValue="key">
            <Radio.Group>
              <Radio.Button value="key">密钥文件</Radio.Button>
              <Radio.Button value="password">密码</Radio.Button>
            </Radio.Group>
          </Form.Item>
          {authType === 'key' ? (
            <Form.Item
              label="私钥路径"
              name="keyPath"
              rules={[{ required: true, message: '请输入私钥路径' }]}
            >
              <Input placeholder="~/.ssh/id_rsa" />
            </Form.Item>
          ) : (
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password placeholder="仅用于演示，正式版由后端保管" />
            </Form.Item>
          )}
          <Form.Item label="队列系统" name="queueSystem" initialValue="lsf">
            <Select
              options={[
                { value: 'lsf', label: 'LSF (IBM)' },
                { value: 'slurm', label: 'SLURM' },
                { value: 'pbs', label: 'PBS / Torque' },
                { value: 'other', label: '其他' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="项目远程根目录"
            name="remoteBase"
            extra="后续新增项目将在此根目录下创建 <项目名>/<任务类型>/<模型名> 目录"
          >
            <Input placeholder="/data/gpfs03/mdye/projects/test" />
          </Form.Item>
          <Collapse
            ghost
            items={[
              {
                key: 'advanced',
                label: '高级设置（可选）',
                children: (
                  <>
                    <Form.Item label="用户主目录" name="home">
                      <Input placeholder="/data/gpfs03/mdye" />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </PageTransition>
  );
}
