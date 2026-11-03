import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Collapse, Empty, Popconfirm, Skeleton } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, CloudServerOutlined, DeleteOutlined, EditOutlined, FolderOpenOutlined, LinkOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import RootPathsCard from '../components/ssh/RootPathsCard';
import ServerConfigModal, { type ServerFormValues } from '../components/ssh/ServerConfigModal';
import { useSSH } from '../context/SSHContext';
import type { ConnectionTestResult, ServerConfig } from '../types';
import '../styles/ssh.css';

export default function SSH() {
  const { message } = App.useApp();
  const { servers, loading, activeServer, addServer, updateServer, removeServer, toggleConnection, testConnection } = useSSH();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ServerConfig | null>(null);

  useEffect(() => {
    if (!servers.some((server) => server.id === selectedId)) {
      setSelectedId(activeServer?.id ?? servers[0]?.id ?? null);
    }
  }, [servers, activeServer, selectedId]);

  const selected = servers.find((server) => server.id === selectedId) ?? null;
  const lastTest = selected ? testResults[selected.id] : undefined;
  const openCreate = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (server: ServerConfig) => { setEditing(server); setModalOpen(true); };

  const handleSave = (values: ServerFormValues) => {
    if (editing) {
      updateServer(editing.id, values);
      setTestResults((previous) => {
        const next = { ...previous };
        delete next[editing.id];
        return next;
      });
      message.success(`已更新 ${values.name} 的配置`);
    } else {
      addServer({ ...values, id: values.name, connected: false, latencyMs: null, lastTestAt: null });
      setSelectedId(values.name);
      message.success(`已添加服务器 ${values.name}`);
    }
    setModalOpen(false);
  };

  const handleTest = async (server: ServerConfig) => {
    if (testingId) return;
    setTestingId(server.id);
    try {
      const result = await testConnection(server.id);
      setTestResults((previous) => ({ ...previous, [server.id]: result }));
      if (result.ok) message.success('连接测试通过');
      else message.error(result.message);
    } finally {
      setTestingId(null);
    }
  };

  const handleToggle = (server: ServerConfig) => {
    toggleConnection(server.id);
    message.info(server.connected ? `已取消选用 ${server.name}` : `当前选用 ${server.name}`);
  };

  const handleDelete = (server: ServerConfig) => {
    removeServer(server.id);
    setTestResults((previous) => {
      const next = { ...previous };
      delete next[server.id];
      return next;
    });
    message.info(`已删除服务器 ${server.name}`);
  };

  return (
    <PageTransition>
      <div className="ssh-page">
        <PageHeader title="SSH 连接" subtitle="管理计算服务器，随时检查连接是否可用。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建服务器</Button>} />

        <div className="ssh-overview" aria-label="服务器概况">
          <div className="ssh-overview__item">
            <span className="ssh-overview__icon"><CloudServerOutlined /></span>
            <div><span className="ssh-caption">已配置</span><strong>{loading ? '—' : servers.length}<small> 台服务器</small></strong></div>
          </div>
          <div className="ssh-overview__item">
            <span className="ssh-overview__icon"><LinkOutlined /></span>
            <div><span className="ssh-caption">当前选用</span><strong>{activeServer?.name ?? '尚未选择'}</strong></div>
          </div>
          <p className="ssh-overview__note">选择服务器查看配置，点击测试检查远程访问。</p>
        </div>

        <div className="ssh-workspace">
          <Card className="ssh-directory" title={<span>服务器 <span className="ssh-count">{servers.length}</span></span>}>
            {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : servers.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有服务器"><Button icon={<PlusOutlined />} onClick={openCreate}>添加第一台服务器</Button></Empty>
            ) : (
              <nav className="ssh-directory__list" aria-label="服务器列表">
                {servers.map((server) => (
                  <button key={server.id} type="button" className={`ssh-directory__entry${server.id === selectedId ? ' is-selected' : ''}`} aria-current={server.id === selectedId ? 'true' : undefined} onClick={() => setSelectedId(server.id)}>
                    <span className="ssh-directory__entry-top"><CloudServerOutlined /><strong>{server.name}</strong>{server.connected && <span className="ssh-selected-label">当前选用</span>}</span>
                    <span className="ssh-directory__address">{server.user}@{server.host}</span>
                    <span className="ssh-directory__entry-bottom"><span>{String(server.queueSystem).toUpperCase()} · {server.authType === 'key' ? '密钥认证' : '密码认证'}</span><ArrowRightOutlined /></span>
                  </button>
                ))}
              </nav>
            )}
          </Card>

          <Card className="ssh-connection-card">
            {loading ? <Skeleton active paragraph={{ rows: 8 }} /> : selected ? (
              <>
                <div className="ssh-connection-heading">
                  <div className="ssh-connection-heading__identity"><div className="ssh-server-symbol"><CloudServerOutlined /></div><div><span className="ssh-caption">服务器配置</span><h2>{selected.name}</h2><p>{selected.user}@{selected.host}:{selected.port}</p></div></div>
                  <Button icon={<EditOutlined />} onClick={() => openEdit(selected)}>编辑配置</Button>
                </div>

                <div className="ssh-connection-toolbar">
                  <div className="ssh-connection-toolbar__actions">
                    <Button type="primary" icon={<ReloadOutlined />} loading={testingId === selected.id} disabled={Boolean(testingId && testingId !== selected.id)} onClick={() => void handleTest(selected)}>测试连接</Button>
                    <Button icon={selected.connected ? <CheckCircleOutlined /> : <LinkOutlined />} onClick={() => handleToggle(selected)}>{selected.connected ? '取消选用' : '设为当前服务器'}</Button>
                  </div>
                  {selected.connected && <span className="ssh-selected-label"><CheckCircleOutlined /> 当前选用</span>}
                </div>

                {lastTest && <Alert className="ssh-connection-result" type={lastTest.ok ? 'success' : 'error'} showIcon message={lastTest.ok ? `连接测试通过 · ${lastTest.latencyMs} ms` : '连接测试未通过'} description={lastTest.message} />}

                <section className="ssh-info-section" aria-label="连接信息">
                  <h3>连接信息</h3>
                  <dl className="ssh-info-grid">
                    <div><dt>主机地址</dt><dd>{selected.host}</dd></div>
                    <div><dt>端口</dt><dd>{selected.port}</dd></div>
                    <div><dt>登录用户</dt><dd>{selected.user}</dd></div>
                    <div><dt>认证方式</dt><dd>{selected.authType === 'key' ? '密钥文件' : '密码'}</dd></div>
                    <div><dt>队列系统</dt><dd>{String(selected.queueSystem).toUpperCase()}</dd></div>
                    <div><dt>最近测得延迟</dt><dd>{selected.latencyMs != null ? <>{selected.latencyMs} <span className="ssh-unit">ms</span></> : '尚未测得'}</dd></div>
                  </dl>
                  <p className="ssh-last-tested">最近测试<span>{selected.lastTestAt ?? '尚未测试'}</span></p>
                </section>

                <section className="ssh-info-section" aria-label="服务器目录">
                  <h3>服务器目录</h3>
                  <dl className="ssh-path-list">
                    <div><dt>项目远程根目录</dt><dd>{selected.remoteBase || '未设置'}</dd></div>
                    <div><dt>用户主目录</dt><dd>{selected.home || '未设置'}</dd></div>
                    {selected.authType === 'key' && <div><dt>私钥文件</dt><dd>{selected.keyPath || '未设置'}</dd></div>}
                  </dl>
                </section>

                <div className="ssh-connection-footer">
                  <Popconfirm title="删除该服务器配置？" description="删除后需重新填写连接信息" onConfirm={() => handleDelete(selected)} okText="删除" cancelText="取消"><Button type="text" danger icon={<DeleteOutlined />}>删除配置</Button></Popconfirm>
                </div>
              </>
            ) : <div className="ssh-connection-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一台服务器，查看连接信息" /></div>}
          </Card>
        </div>

        <Collapse className="ssh-locations" items={[{ key: 'paths', label: <span className="ssh-locations__heading"><FolderOpenOutlined /><strong>项目文件位置</strong><span>本地与远程根目录</span></span>, children: <RootPathsCard /> }]} />
        <ServerConfigModal open={modalOpen} editing={editing} servers={servers} onCancel={() => setModalOpen(false)} onSave={handleSave} />
      </div>
    </PageTransition>
  );
}
