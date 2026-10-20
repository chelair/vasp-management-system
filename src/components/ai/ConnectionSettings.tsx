import { useEffect,useState } from 'react';
import { Alert, App, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Switch, Tag } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { deleteAIConnection, saveAIConnection, testAIConnection,fetchReasoningCapabilities } from '../../api/aiChat';
import type { AIConnection, AIConnectionInput,ReasoningCapabilities } from '../../api/aiChat';

export default function ConnectionSettings({ open, close, connections, reload }: {
  open: boolean; close: () => void; connections: AIConnection[]; reload: () => Promise<void>;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<AIConnectionInput>();
  const [editing, setEditing] = useState<AIConnection | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const baseUrl = Form.useWatch('base_url', form) as string | undefined;
  const modelName=Form.useWatch('model',form) as string|undefined;
  const reasoningApi=Form.useWatch('reasoning_api',form) as string|undefined;
  const [cap,setCap]=useState<ReasoningCapabilities>();
  const [capLoading,setCapLoading]=useState(false);
  const [capError,setCapError]=useState('');
  useEffect(()=>{
    if(!modalOpen)return;let active=true;setCapLoading(true);setCapError('');
    const timer=setTimeout(()=>{fetchReasoningCapabilities(baseUrl||'',modelName||'',reasoningApi||'auto').then(value=>{if(!active)return;setCap(value);const effort=form.getFieldValue('reasoning_effort')||'default';if(!value.options.some(o=>o.value===effort))form.setFieldValue('reasoning_effort','default');}).catch(e=>{if(active){setCap(undefined);setCapError(e.message);}}).finally(()=>{if(active)setCapLoading(false);});},150);
    return()=>{active=false;clearTimeout(timer);};
  },[modalOpen,baseUrl,modelName,reasoningApi,form]);
  const isDeepSeek = /^https:\/\/api\.deepseek\.com(?:\/|$)/i.test(baseUrl ?? '');
  const secure = window.location.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
  const edit = (connection: AIConnection | null) => {
    setEditing(connection); form.resetFields();
    form.setFieldsValue(connection ? { ...connection, api_key: '',reasoning_effort:connection.reasoning_effort==='default'&&connection.reasoning_capabilities.provider==='deepseek'&&connection.thinking_mode==='disabled'?'none':connection.reasoning_effort } : { base_url: 'https://api.openai.com/v1', max_tokens: 2048, is_default: connections.length === 0, thinking_mode: 'default',reasoning_api:'auto',reasoning_effort:'default' });
    setModalOpen(true);
  };
  const clearForm = () => { form.resetFields(); setModalOpen(false); setEditing(null); };
  const save = async () => {
    let values: AIConnectionInput;
    try { values = await form.validateFields(); } catch { return; }
    setBusy(true);
    try {
      if(cap?.provider==='deepseek'&&values.reasoning_effort!=='default')values.thinking_mode=values.reasoning_effort==='none'?'disabled':'enabled';
      else values.thinking_mode='default';
      await saveAIConnection(values, editing?.id);
      clearForm(); await reload(); void message.success('连接已保存，密钥不回传到页面');
    } catch (error) { void message.error(error instanceof Error ? error.message : '保存失败'); }
    finally { setBusy(false); }
  };
  return <>
    <Drawer title="模型连接" open={open} onClose={close} width={520} extra={<Button icon={<PlusOutlined />} onClick={() => edit(null)}>新增连接</Button>}>
      <p className="ai-muted">连接仅当前账号可用。API Key 加密保存在后端，页面不能读取原值。</p>
      {!connections.length && <Empty description="尚未配置模型接口" />}
      {connections.map((connection) => <div className="ai-connection" key={connection.id}>
        <div><strong>{connection.name}</strong> {connection.is_default && <Tag color="blue">默认</Tag>}</div>
        <div className="ai-muted">{connection.model}</div><div className="ai-url">{connection.base_url}</div>
        <div className="ai-muted">密钥已配置 · 单次输出上限 {connection.max_tokens} tokens · 思考深度：{connection.reasoning_capabilities.options.find(o=>o.value===connection.effective_reasoning_effort)?.label||connection.effective_reasoning_effort}</div>
        <div className="ai-actions">
          <Button size="small" loading={testing === connection.id} onClick={async () => {
            setTesting(connection.id);
            try { const result = await testAIConnection(connection.id); void message.info(`${result.message}${result.model_listed ? '' : '；列表未包含所填模型，请核对模型名称'}`); }
            catch (error) { void message.error(error instanceof Error ? error.message : '连接失败'); }
            finally { setTesting(null); }
          }}>测试连接</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => edit(connection)}>编辑</Button>
          <Popconfirm title="删除该模型连接？" description="已有对话和运行记录会保留。" onConfirm={async () => {
            try { await deleteAIConnection(connection.id); await reload(); }
            catch (error) { void message.error(error instanceof Error ? error.message : '删除失败'); }
          }}><Button size="small" danger icon={<DeleteOutlined />} aria-label={`删除连接 ${connection.name}`} /></Popconfirm>
        </div>
      </div>)}
    </Drawer>
    <Modal title={editing ? '编辑模型连接' : '新增模型连接'} zIndex={1200} open={modalOpen} onCancel={clearForm}
      onOk={() => { void save(); }} confirmLoading={busy} okButtonProps={{ disabled: !secure||capLoading||!!capError }} forceRender afterClose={() => form.resetFields()}>
      {!secure && <Alert type="error" showIcon message="请通过 HTTPS 或本机端口转发访问后配置密钥" style={{ marginBottom: 16 }} />}
      <Form form={form} layout="vertical" preserve={false} autoComplete="off">
        <div style={{ marginBottom: 16 }}><Button onClick={() => form.setFieldsValue({ name: 'DeepSeek', base_url: 'https://api.deepseek.com', model: 'deepseek-flash', api_key: '', max_tokens: 8192, thinking_mode: 'disabled',reasoning_api:'auto',reasoning_effort:'none' })}>填入 DeepSeek 官方配置</Button></div>
        <Form.Item name="name" label="连接名称" rules={[{ required: true, whitespace: true }]}><Input aria-label="连接名称" maxLength={80} placeholder="例如：科研助手" /></Form.Item>
        <Form.Item name="base_url" label="API 基础地址" extra="OpenAI 兼容接口，通常以 /v1 结尾。更换地址时须重新输入密钥。" rules={[{ required: true, whitespace: true }]}><Input aria-label="API 基础地址" maxLength={2000} placeholder="https://example.com/v1" /></Form.Item>
        <Form.Item name="model" label="模型名称" rules={[{ required: true, whitespace: true }]} extra={isDeepSeek ? <span>
          可手动填写，或选择：{['deepseek-flash', 'deepseek-v4-pro'].map((model) => <Button key={model} type="link" size="small" onClick={() => form.setFieldValue('model', model)}>{model}</Button>)}
        </span> : undefined}><Input aria-label="模型名称" maxLength={200} placeholder="填写服务商提供的模型 ID" /></Form.Item>
        <Form.Item name="api_key" label="API Key" extra={editing ? '留空保留原密钥；不会显示已保存的密钥。' : '仅保存时发送给后端，关闭表单后清除。'} rules={[{ required: !editing, whitespace: true }]}><Input.Password aria-label="API Key" maxLength={512} autoComplete="new-password" placeholder={editing ? '已配置，留空保留' : '输入密钥'} /></Form.Item>
        <Form.Item name="reasoning_api" label="思考接口类型" initialValue="auto" extra="官方地址自动识别；代理或其他兼容服务可按服务商说明手动选择。"><Select aria-label="思考接口类型" options={[
          {value:'auto',label:'自动识别'},{value:'openai',label:'OpenAI 兼容'},{value:'deepseek',label:'DeepSeek 兼容'},
        ]}/></Form.Item>
        <Form.Item name="reasoning_effort" label="思考深度" initialValue="default" extra={cap?.note}><Select aria-label="思考深度" loading={capLoading} disabled={capLoading||!cap} options={cap?.options||[{value:'default',label:'跟随模型默认'}]}/></Form.Item>
        {capError&&<Alert type="error" message={capError}/>}
        <Form.Item name="max_tokens" label="单次输出上限（tokens）" extra="思考与最终回答共用此额度，深度较高时可适当提高。报告段落另有输出额度上限。"><InputNumber min={128} max={32768} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="is_default" label="设为新会话的默认连接" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  </>;
}
