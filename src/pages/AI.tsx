import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Collapse, Descriptions, Empty, Form, Input, Modal, Popconfirm, Select, Spin, Tabs, Tag, Tooltip } from 'antd';
import { ApiOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SendOutlined, StopOutlined } from '@ant-design/icons';
import PageHeader from '../components/common/PageHeader';
import ConnectionSettings from '../components/ai/ConnectionSettings';
import StreamingAnswer from '../components/ai/StreamingAnswer';
import WorkspacePanel from '../components/ai/WorkspacePanel';
import TopicReportLinks from '../components/ai/TopicReportLinks';
import TopicReportEditor from '../components/reports/TopicReportEditor';
import {
  createAIConversation, deleteAIConversation, getAIContext, getAIConversation, getAIRun,
  isActiveRun, listAIConnections, listAIConversations, listAITargets, sendAIMessage,
  stopAIRun, updateAIConversation, watchAIRun,saveAIConnection,
} from '../api/aiChat';
import type { AIConnection, AIContext, AIConversation, AIConversationDetail, AIRun, AITarget } from '../api/aiChat';
import '../styles/ai.css';

const STATUS: Record<string, string> = { queued: '等待响应', running: '生成中', completed: '已完成', cancelled: '已停止', failed: '失败', interrupted: '已中断' };
const TYPES: Record<string, string> = { opt: '结构优化', neb: 'NEB', frac: '频率矫正', ele: '电子结构' };
const TASK_STATUS: Record<string, string> = { completed: '已完成', running: '运行中', pending: '待提交', queued: '排队中', archived: '已归档', unconverged: '未收敛', zombied: '异常', low_precision: '低精度收敛' };
const asObject = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const show = (value: unknown) => value == null || value === '' ? '—' : String(value);
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试';
const toolBrief = (value: unknown) => { const text = JSON.stringify(value ?? {}); return text.length > 140 ? `${text.slice(0, 140)}…` : text; };
function JsonView({ value }: { value: unknown }) { return <pre className="ai-json">{JSON.stringify(value ?? {}, null, 2)}</pre>; }

export default function AI() {
  const { message } = App.useApp();
  const [params, setParams] = useSearchParams();
  const selected = params.get('conversation');
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [targets, setTargets] = useState<AITarget[]>([]);
  const [conversations, setConversations] = useState<AIConversation[]>([]);
  const [scope, setScope] = useState('general');
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const [detailState, setDetail] = useState<AIConversationDetail | null>(null);
  const detail = detailState?.id === selected ? detailState : null;
  const [contextState, setContextState] = useState<{ id: string; value: AIContext } | null>(null);
  const context = contextState?.id === selected ? contextState.value : null;
  const setContext = (value: AIContext | null) => setContextState(value && selectedRef.current ? { id: selectedRef.current, value } : null);
  const [draft, setDraft] = useState('');
  const drafts = useRef<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [inspecting, setInspecting] = useState<AIRun | null>(null);
  const [streamRevision, setStreamRevision] = useState(0);
  const [topicId,setTopicId] = useState<string>();
  const [topicRevision,setTopicRevision] = useState(0);
  const [form] = Form.useForm<{ title: string; prompt: string }>();
  const messagesRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);
  const freshRuns = useRef(new Set<string>());
  const scrollAnswer = useCallback(() => {
    const box = messagesRef.current;
    if (box && autoScroll.current) box.scrollTop = box.scrollHeight;
  }, []);
  const active = detail?.runs.find(isActiveRun);

  const reloadConnections = useCallback(async () => {
    const items = (await listAIConnections()).items;
    setConnections(items);
    setDetail((old) => old?.connection_id && !items.some((c) => c.id === old.connection_id) ? { ...old, connection_id: null } : old);
  }, []);
  const reloadList = useCallback(async () => { setConversations((await listAIConversations()).items); }, []);
  useEffect(() => {
    let cancelled = false;
    void Promise.all([listAIConnections(), listAITargets(), listAIConversations()]).then(([a, b, c]) => {
      if (!cancelled) { setConnections(a.items); setTargets(b.items); setConversations(c.items); }
    }).catch((e) => { if (!cancelled) setError(errorText(e)); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    freshRuns.current.clear();
    setDetail(null); setContext(null); setError(''); setDraft(selected ? drafts.current[selected] ?? '' : '');
    setEditOpen(false); setInspecting(null); setTopicId(undefined);
    autoScroll.current = true;
    if (!selected) { setLoading(false); return; }
    setLoading(true);
    void getAIConversation(selected).then((data) => {
      if (cancelled) return;
      setDetail(data);
      return getAIContext(selected).then((snapshot) => { if (!cancelled) setContext(snapshot); });
    }).catch((e) => { if (!cancelled) setError(errorText(e)); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selected]);

  useEffect(() => {
    if (detail) setScope(targets.some((project) => project.id === detail.project_id && !project.closed) ? detail.project_id! : 'general');
  }, [detail?.id, targets]);

  useEffect(() => {
    if (!active || !selected) return;
    const controller = new AbortController();
    const conversationId = selected;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const watch = async () => {
      try {
        await watchAIRun(active.id, controller.signal, ({ run, message: answer }) => {
          if (selectedRef.current !== conversationId) return;
          setError('');
          setDetail((old) => old?.id === conversationId ? {
            ...old,
            messages: old.messages.some((m) => m.id === answer.id) ? old.messages.map((m) => m.id === answer.id ? answer : m) : [...old.messages, answer],
            runs: [run, ...old.runs.filter((r) => r.id !== run.id)],
          } : old);
          if (!isActiveRun(run)) { void reloadList().catch(() => undefined); }
        });
      } catch (e) {
        if (controller.signal.aborted || selectedRef.current !== conversationId) return;
        if (/无权|权限/.test(errorText(e))) { setError(errorText(e)); setDetail(null); setContext(null); return; }
        setError(`${errorText(e)}；正在重新连接已有回答。`);
        timer = setTimeout(() => { if (!controller.signal.aborted) void watch(); }, 2500);
      }
    };
    void watch();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [active?.id, selected, reloadList, streamRevision]); // 同一运行只订阅一次，逐字更新不重建连接。

  useEffect(() => {
    const box = messagesRef.current;
    if (box && autoScroll.current) box.scrollTop = box.scrollHeight;
  }, [detail?.messages]);

  const projectOptions = useMemo(() => [
    { label: '通用对话 · 不附加项目', value: 'general' },
    ...targets.filter((project) => !project.closed).map((project) => ({ label: `${project.name} · ${project.tasks.length} 个任务`, value: project.id })),
  ], [targets]);
  const scopeName = targets.find((p) => p.id === scope)?.name ?? '通用对话';
  const visibleConversations = useMemo(() => {
    const openProjects = new Set(targets.filter((project) => !project.closed).map((project) => project.id));
    return conversations.filter((conversation) => !conversation.project_id || openProjects.has(conversation.project_id))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id));
  }, [conversations, targets]);
  const conversationGroups = useMemo(() => {
    const groups = new Map<string, { id: string; name: string; conversations: AIConversation[] }>();
    for (const conversation of visibleConversations) {
      const id = conversation.project_id ?? 'general';
      if (!groups.has(id)) groups.set(id, { id, name: targets.find((project) => project.id === id)?.name ?? '通用对话', conversations: [] });
      groups.get(id)!.conversations.push(conversation);
    }
    // 已按时间排序的会话依次入组：组内倒序，分组也按最近一次对话排序。
    return [...groups.values()];
  }, [visibleConversations, targets]);
  const model = connections.find((c) => c.id === detail?.connection_id);
  const choose = (id: string | null) => setParams(id ? { conversation: id } : {});

  const newConversation = async () => {
    const requestedScope = scope;
    if (scope !== 'general' && !targets.some((project) => project.id === scope && !project.closed)) {
      setScope('general'); void message.warning('请选择未关闭的项目或通用对话'); return;
    }
    setBusy(true);
    try {
      const count = conversations.filter((conversation) => (conversation.project_id ?? 'general') === scope).length;
      const result = await createAIConversation({ title: `${scopeName} · ${count + 1}`, project_id: scope === 'general' ? undefined : scope });
      await reloadList(); if (scopeRef.current === requestedScope) choose(result.id);
    } catch (e) { void message.error(errorText(e)); }
    finally { setBusy(false); }
  };
  const send = async (retry = false) => {
    if (!detail || active || busy || (!retry && !draft.trim())) return;
    const id = detail.id, text = draft;
    setBusy(true); setError(''); autoScroll.current = true;
    try {
      const started = await sendAIMessage(id, text, retry);
      freshRuns.current.add(started.id);
      if (!retry) drafts.current[id] = '';
      const fresh = await getAIConversation(id);
      if (selectedRef.current === id) { setDetail(fresh); if (!retry) setDraft(''); }
      void reloadList().catch(() => undefined);
    } catch (e) { if (selectedRef.current === id) setError(errorText(e)); }
    finally { setBusy(false); }
  };
  const refreshContext = async () => {
    const id = selected;
    if (!id) return;
    try { const result = await getAIContext(id); if (selectedRef.current === id) setContext(result); }
    catch (e) { if (selectedRef.current === id) void message.error(errorText(e)); }
  };
  const project = asObject(context?.project), summary = asObject(context?.summary);
  const projectTasks = Array.isArray(context?.tasks) ? context.tasks.map(asObject) : [];
  const checks = asObject(context?.checks), actions = asObject(context?.actions);


  return <div className="ai-page">
    {topicId&&<TopicReportEditor key={topicId} topicId={topicId} connectionId={detail?.connection_id} onClose={()=>setTopicId(undefined)} onSaved={()=>setTopicRevision(r=>r+1)}/>}
      <PageHeader title="AI 工作台" subtitle="按项目附加上下文 · 基于本地计算记录分析" extra={<Button icon={<ApiOutlined />} onClick={() => setSettingsOpen(true)}>模型连接</Button>} />
    {!connections.length && !loading && <Alert type="info" showIcon message="先配置模型接口，再开始对话" action={<Button size="small" onClick={() => setSettingsOpen(true)}>配置连接</Button>} />}
    {error && <Alert type="warning" closable onClose={() => setError('')} message={error} action={active ? <Button size="small" onClick={() => setStreamRevision((n) => n + 1)}>重新连接</Button> : undefined} />}
    <div className="ai-workspace">
      <aside className="ai-sessions">
        <label className="ai-label">新对话所属项目</label>
        <Select aria-label="选择新对话所属项目" showSearch optionFilterProp="label" value={scope} options={projectOptions} style={{ width: '100%' }} onChange={setScope} />
        <Button block icon={<PlusOutlined />} loading={busy} onClick={() => { void newConversation(); }} style={{ margin: '12px 0' }}>新建会话</Button>
        <div className="ai-muted ai-scope-title">最近对话</div>
        <div className="ai-session-list">{conversationGroups.map((group) => <section className="ai-session-group" key={group.id} aria-label={`${group.name}的对话`}>
          <div className="ai-session-group-title"><strong>{group.name}</strong><span>{group.conversations.length}</span></div>
          {group.conversations.map((conversation) => <button key={conversation.id}
          className={`ai-session${selected === conversation.id ? ' selected' : ''}`} onClick={() => choose(conversation.id)}>
          <strong>{conversation.title}</strong><span>{conversation.updated_at.replace('T', ' ').slice(0, 16)}</span>
        </button>)}</section>)}</div>
        {!visibleConversations.length && <div className="ai-muted ai-empty-hint">暂无对话。这里汇总通用对话和所有未关闭项目的对话，已关闭项目的对话自动归档隐藏。</div>}
      </aside>

      <section className="ai-chat" aria-label="AI 对话窗口">
        {detail ? <>
          <header className="ai-chat-header"><div><strong>{detail.title}</strong><div className="ai-muted">{detail.project_id ? '项目会话' : '通用会话'} · 提示词版本 {detail.prompt_version}</div></div>
            <div className="ai-actions">
              <Tooltip title="会话名称与提示词"><Button size="small" icon={<EditOutlined />} disabled={!!active} onClick={() => { form.setFieldsValue({ title: detail.title, prompt: detail.prompt }); setEditOpen(true); }} aria-label="编辑会话提示词" /></Tooltip>
              <Popconfirm title="删除此会话及其全部聊天记录？" onConfirm={async () => {
                try { await deleteAIConversation(detail.id); delete drafts.current[detail.id]; choose(null); await reloadList(); }
                catch (e) { void message.error(errorText(e)); }
              }}><Button size="small" icon={<DeleteOutlined />} disabled={!!active} aria-label="删除会话" /></Popconfirm>
            </div>
          </header>
          <div className="ai-model-select"><Select aria-label="当前会话模型" placeholder="选择模型连接" value={model?.id} disabled={!!active || busy}
            options={connections.map((c) => ({ value: c.id, label: `${c.name} · ${c.model}` }))} style={{ width: '100%' }} onChange={async (value) => {
              const id = detail.id; setBusy(true);
              try { const result = await updateAIConversation(id, { title: detail.title, prompt: detail.prompt, connection_id: value }); if (selectedRef.current === id) setDetail(result); await reloadList(); }
              catch (e) { void message.error(errorText(e)); }
              finally { setBusy(false); }
            }} />

          </div>
          <div className="ai-messages" ref={messagesRef} onScroll={() => {
            const box = messagesRef.current; if (box) autoScroll.current = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
          }}>
            {detail.has_more && <Button type="link" onClick={async () => {
              const id = detail.id;
              try { const older = await getAIConversation(id, detail.messages[0]?.seq); setDetail((old) => old?.id === id ? { ...old,
                messages: [...older.messages.filter((m) => !old.messages.some((existing) => existing.id === m.id)), ...old.messages],
                runs: [...old.runs, ...older.runs.filter((r) => !old.runs.some((existing) => existing.id === r.id))], has_more: older.has_more } : old); }
              catch (e) { void message.error(errorText(e)); }
            }}>加载更早的消息</Button>}
            {!detail.messages.length && <div className="ai-welcome"><h2>从一个具体问题开始</h2><p>{detail.project_id ? '每次发问会附加整个项目的目标、预期、任务状态与结果摘要。' : '这里可以讨论研究思路和计算计划。选择项目后可创建带项目上下文的会话。'}</p>
              {['帮我梳理整个项目的结果与缺失信息', '对比已有结果与预期，提出下一步验证计划', '比较两个模型的科学性质，生成专题科研报告'].map((text) => <Button key={text} onClick={() => { setDraft(text); drafts.current[detail.id] = text; }}>{text}</Button>)}</div>}
            {detail.messages.map((item) => {
              const run = detail.runs.find((r) => r.message_id === item.id);
              return <article key={item.id} className={`ai-message ai-message--${item.role}`}>
                <div className="ai-message-meta"><strong>{item.role === 'user' ? '你' : 'AI'}</strong><span>{item.created_at.replace('T', ' ').slice(5, 16)}</span>
                  {item.role === 'assistant' && <Tag color={item.status === 'failed' ? 'error' : isActiveRun({ status: item.status } as AIRun) ? 'processing' : 'default'}>{STATUS[item.status] ?? item.status}</Tag>}
                </div>
                {item.role === 'assistant' && run && (run.reasoning || run.tool_events?.length) ? (
                  <details className="ai-reasoning" open={isActiveRun(run)}>
                    <summary>
                      思考与工具调用
                      {run.tool_events?.length ? ` · ${run.tool_events.length} 次` : ''}
                      {isActiveRun(run) ? '（生成中）' : ''}
                    </summary>
                    {run.reasoning ? <div className="ai-reasoning__body">{run.reasoning}</div> : null}
                    {run.tool_events?.length ? (
                      <div className="ai-tool-events">
                        {run.tool_events.map((event) => (
                          <div className="ai-tool-event" key={event.id}>
                            <Tag color={event.status === 'failed' ? 'error' : event.status === 'running' ? 'processing' : 'default'}>{event.status}</Tag>
                            <strong>{event.name}</strong>
                            <span className="ai-muted">{toolBrief(event.arguments)}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </details>
                ) : null}
                {item.role === 'user' ? <div className="ai-user-text">{item.content}</div> : <StreamingAnswer text={item.content} status={item.status} fresh={!!run && freshRuns.current.has(run.id)} onProgress={scrollAnswer} />}
                {run?.error && <div className="ai-run-error">{run.error}</div>}
                {item.role === 'assistant' && <div className="ai-answer-tools"><Button size="small" type="text" onClick={() => { void navigator.clipboard?.writeText(item.content); }}>复制回答</Button>
                  {run && <Button size="small" type="text" onClick={() => { void getAIRun(run.id).then(setInspecting).catch((e) => message.error(errorText(e))); }}>本轮依据</Button>}
                </div>}
              </article>;
            })}
            {detail.project_id&&<TopicReportLinks inline conversationId={detail.id} runs={detail.runs} onOpen={setTopicId} revision={topicRevision}/>}
          </div>

          {model&&detail.project_id&&(model.reasoning_capabilities.tool_policy==='unsupported'||model.reasoning_capabilities.tool_policy==='none_only'&&model.effective_reasoning_effort!=='none')&&<Alert type="warning" message={model.reasoning_capabilities.note}/>}
          <div className="ai-composer"><Input.TextArea aria-label="输入 AI 对话消息" value={draft} maxLength={16000} autoSize={{ minRows: 3, maxRows: 8 }} placeholder="输入问题，Enter 发送，Shift + Enter 换行" disabled={busy}
            onChange={(e) => { setDraft(e.target.value); drafts.current[detail.id] = e.target.value; }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
            <div className="ai-composer-footer"><span className="ai-muted">{detail.project_id ? '模型可读取项目文件并调用工具 · 不执行计算操作' : '基于摘要对话分析'}</span><div className="ai-actions">
              {!active && <Button icon={<ReloadOutlined />} disabled={busy || !model || !detail.messages.some((m) => m.role === 'user')} onClick={() => { void send(true); }}>重新生成</Button>}
              {model&&<Select className="ai-reasoning-select" variant="borderless" aria-label="当前模型思考深度" value={model.effective_reasoning_effort} options={model.reasoning_capabilities.options.map(option=>({...option,label:`思考 · ${option.label}`}))} disabled={!!active||busy||model.reasoning_capabilities.options.length<2} onChange={async effort=>{
              setBusy(true);try{await saveAIConnection({name:model.name,base_url:model.base_url,model:model.model,max_tokens:model.max_tokens,is_default:model.is_default,reasoning_api:model.reasoning_api,reasoning_effort:effort,thinking_mode:effort==='default'?'default':effort==='none'?'disabled':'enabled'},model.id);await reloadConnections();void message.success('已更新此连接的默认思考深度，后续请求生效');}catch(e){void message.error(errorText(e));}finally{setBusy(false);}
            }}/>}
              {active ? <Button icon={<StopOutlined />} onClick={async () => {
                const id = detail.id;
                try { await stopAIRun(active.id); const result = await getAIConversation(id); if (selectedRef.current === id) setDetail(result); }
                catch (e) { void message.error(errorText(e)); }
              }}>停止生成</Button> : <>
                <Button type="primary" icon={<SendOutlined />} loading={busy} disabled={!draft.trim() || !model} onClick={() => { void send(); }}>发送</Button>
              </>}
            </div></div>
          </div>
        </> : <div className="ai-no-conversation">{loading ? <Spin /> : <Empty description="选择项目并新建会话，或打开已有会话" />}</div>}
      </section>

      <aside className="ai-context"><div className="ai-context-header"><strong>项目上下文</strong><Button size="small" icon={<ReloadOutlined />} disabled={!selected} onClick={() => { void refreshContext(); }}>刷新</Button></div>
        {context ? <><p className="ai-muted">本地快照 · {show(context.generated_at).replace('T', ' ').slice(0, 19)}</p>
          <Tabs size="small" items={[
            ...(detail?.project_id ? [{key:'topics',label:'专题报告',children:<TopicReportLinks conversationId={detail.id} runs={detail.runs} onOpen={setTopicId} revision={topicRevision}/>}]:[]),
            ...(detail?.project_id ? [{ key: 'workspace', label: '工作区', children: <WorkspacePanel key={detail.id} conversationId={detail.id} runs={detail.runs} enabled /> }] : []),
            { key: 'info', label: '基本信息', children: detail?.project_id ? <>
              <Descriptions column={1} size="small" items={[
                { key: 'p', label: '项目', children: show(project.name) },
                { key: 's', label: '状态', children: project.closed ? '已关闭' : '进行中' },
                { key: 'n', label: '任务数', children: show(summary.task_count) },
                { key: 'deadline', label: '截止时间', children: show(project.deadline) },
              ]} /><div className="ai-actions">{Object.entries(asObject(summary.status_counts)).map(([status, count]) => <Tag key={status}>{TASK_STATUS[status] ?? status} {show(count)}</Tag>)}</div>
              <h4>项目说明</h4><p className="ai-context-text">{show(project.description)}</p>
              <h4>计算目标</h4><p className="ai-context-text">{show(project.calc_description)}</p><h4>预期结果</h4><p className="ai-context-text">{show(project.expected_results)}</p>
              <h4>项目任务概览{projectTasks.length > 10 ? `（前 10 / 共 ${projectTasks.length}）` : ''}</h4>{projectTasks.slice(0, 10).map((task) => <div className="ai-record" key={String(task.task_id)}>
                <strong>{show(task.task_name)}</strong><span>{TYPES[String(task.task_type)] ?? show(task.task_type)} · {TASK_STATUS[String(task.status)] ?? show(task.status)}</span>
                <span>作业 {show(task.job_id)} · 输出 {show(task.output_dir || '主目录')}</span>
              </div>)}
              <h4>数据提示</h4>{Array.isArray(asObject(context.hints).missing) && <ul className="ai-context-hints">{(asObject(context.hints).missing as unknown[]).map((hint, index) => <li key={index}>{show(hint)}</li>)}</ul>}
              <p className="ai-muted">每轮按预算附加项目摘要，具体附加范围见“本轮依据”。</p>
            </> : <Empty description="通用会话未附加项目数据" /> },
            { key: 'history', label: '历史', children: <><h4>最近巡检</h4>{Array.isArray(checks.recent) && checks.recent.length ? checks.recent.map((value, index) => { const check = asObject(value); return <div className="ai-record" key={index}>
              <strong>{show(check.task_name)}</strong><span>{show(check.checked_at).replace('T', ' ').slice(0, 19)}</span><span>{TASK_STATUS[String(check.raw_status || check.task_status)] ?? show(check.raw_status || check.task_status)} · {show(check.output_dir || '主目录')}</span><span>能量 {show(check.energy_ev)} eV · 最大力 {show(check.force_max_ev_per_a)} eV/Å</span>
            </div>; }) : <p className="ai-muted">暂无巡检记录</p>}<h4>AI 回答记录</h4>{detail?.runs.map((run) => <button className="ai-run-row" key={run.id} onClick={() => { void getAIRun(run.id).then(setInspecting).catch((e) => message.error(errorText(e))); }}>
              <span>{run.created_at.replace('T', ' ').slice(5, 16)} · {STATUS[run.status]}</span><strong>{run.model}</strong><span>{run.usage.total_tokens == null ? '用量未由服务商返回' : `${run.usage.total_tokens} tokens`}</span>
            </button>)}</> },
            { key: 'results', label: '结果', children: <><h4>项目任务结果摘要</h4>{projectTasks.length ? projectTasks.map((task) => <div className="ai-record" key={String(task.task_id)}>
              <strong>{show(task.task_name)}</strong>
              <span>能量 {show(task.energy_ev)} eV · 最大力 {show(task.force_max_ev_per_a)} eV/Å</span>
              <span>力收敛：{task.force_converged == null ? '尚无判定' : task.force_converged ? '已收敛' : '未收敛'} · 来源 {show(task.result_source_dir || '主目录')}</span>
              {Array.isArray(task.data_warnings) && <span className="ai-run-error">{task.data_warnings.map(show).join('；')}</span>}
              <Collapse ghost size="small" items={[{ key: 'details', label: '查看任务结果与来源', children: <JsonView value={task} /> }]} />
            </div>) : <p className="ai-muted">暂无项目任务结果</p>}</> },
            { key: 'actions', label: '操作', children: <><h4>已有任务操作记录</h4>{Array.isArray(actions.recent) && actions.recent.length ? actions.recent.map((value, index) => { const action = asObject(value); return <div className="ai-record" key={index}>
              <strong>{show(action.task_name)} · {show(action.command)}</strong><span>{show(action.at).replace('T', ' ')} · {show(action.actor)}</span><p>{show(action.result)}</p>
            </div>; }) : <p className="ai-muted">暂无操作记录</p>}<Collapse ghost size="small" items={[{ key: 'manual', label: '查看人工修改痕迹', children: <JsonView value={context.manual} /> }]} /></> },
          ]} />
        </> : <div className="ai-empty-hint ai-muted">选择会话后展示对应数据。每次发问会重新读取本地快照；右侧刷新不会发起远端同步。</div>}
      </aside>
    </div>
    <ConnectionSettings open={settingsOpen} close={() => setSettingsOpen(false)} connections={connections} reload={reloadConnections} />
    <Modal title="会话设置" forceRender open={editOpen} onCancel={() => setEditOpen(false)} onOk={async () => {
      if (!detail) return;
      const values = await form.validateFields(), id = detail.id;
      try { const result = await updateAIConversation(id, { ...values, connection_id: detail.connection_id }); if (selectedRef.current === id) setDetail(result); setEditOpen(false); await reloadList(); }
      catch (e) { void message.error(errorText(e)); }
    }}><Form form={form} layout="vertical"><Form.Item name="title" label="会话名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={120} /></Form.Item>
      <Form.Item name="prompt" label="会话提示词" extra="可描述研究角色、目标和回答偏好。保存后增加版本，已有回答仍保留原版本记录。"><Input.TextArea rows={7} maxLength={8000} showCount placeholder="例如：重点检查几何结构和收敛证据，区分事实与假设。" /></Form.Item>
      <p className="ai-muted">系统规则固定要求证据与来源，禁止编造或声称已执行操作。</p>
    </Form></Modal>
    <Modal title="本轮回答依据" open={!!inspecting} onCancel={() => setInspecting(null)} footer={null} width={900}>
      {inspecting && <><p className="ai-muted">{inspecting.model} · 提示词版本 {inspecting.prompt_version} · {STATUS[inspecting.status]}</p>
        <JsonView value={inspecting.snapshot} />
        {!!inspecting.tool_events?.length && <Collapse items={[{ key: 'tools', label: '本轮工具调用与读取证据', children: <JsonView value={inspecting.tool_events} /> }]} />}</>}
    </Modal>
  </div>;
}
