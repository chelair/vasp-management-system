import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Collapse, Descriptions, Drawer, Empty, Form, Input, Modal, Popconfirm, Select, Spin, Tabs, Tag, Tooltip } from 'antd';
import { ApiOutlined, ArrowDownOutlined, ArrowUpOutlined, BookOutlined, DeleteOutlined, EditOutlined, FolderOpenOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, StopOutlined } from '@ant-design/icons';
import ConnectionSettings from '../components/ai/ConnectionSettings';
import WorkExperience from '../components/ai/WorkExperience';
import StreamingAnswer from '../components/ai/StreamingAnswer';
import RunActivity, { runProgress } from '../components/ai/RunActivity';
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
  const [experienceOpen,setExperienceOpen]=useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia('(max-width: 900px)').matches);
  const [contextOpen, setContextOpen] = useState(false);
  const [sessionSearch, setSessionSearch] = useState('');
  const [awayFromBottom, setAwayFromBottom] = useState(false);
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
    const update = (event: Event) => {
      const info = (event as CustomEvent<{conversationId?:string;error?:string}>).detail;
      if (!info?.conversationId || selectedRef.current !== info.conversationId) return;
      if (info.error) setError(info.error);
      void getAIConversation(info.conversationId).then(value => {
        if (selectedRef.current === value.id) setDetail(value);
      }).catch(e => setError(errorText(e)));
      void reloadList().catch(() => undefined);
    };
    window.addEventListener('vasp:topic-updated', update);
    return () => window.removeEventListener('vasp:topic-updated', update);
  }, [reloadList]);
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
    autoScroll.current = true; setAwayFromBottom(false);
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
  }, [detail?.id, detail?.project_id, targets]);

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
          if (!isActiveRun(run)) {
            void reloadList().catch(() => undefined);
            if (run.tool_events.some(event => ['create_project_from_request', 'create_calculation_contents', 'update_project_details', 'save_project_requirements'].includes(event.name) && event.status === 'completed')) {
              void Promise.all([listAITargets(), getAIConversation(conversationId), getAIContext(conversationId)]).then(([projects, current, snapshot]) => {
                setTargets(projects.items);
                if (selectedRef.current === conversationId) { setDetail(current); setContextState({ id: conversationId, value: snapshot }); }
              }).catch(e => setError(errorText(e)));
            }
          }
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
    const query = sessionSearch.trim().toLocaleLowerCase();
    for (const conversation of visibleConversations) {
      const projectName = targets.find((project) => project.id === conversation.project_id)?.name ?? '';
      if (query && !`${conversation.title} ${projectName}`.toLocaleLowerCase().includes(query)) continue;
      const id = conversation.project_id ?? 'general';
      if (!groups.has(id)) groups.set(id, { id, name: targets.find((project) => project.id === id)?.name ?? '通用对话', conversations: [] });
      groups.get(id)!.conversations.push(conversation);
    }
    // 已按时间排序的会话依次入组：组内倒序，分组也按最近一次对话排序。
    return [...groups.values()];
  }, [visibleConversations, targets, sessionSearch]);
  const model = connections.find((c) => c.id === detail?.connection_id);
  const choose = (id: string | null) => {
    setParams(id ? { conversation: id } : {});
    if (window.matchMedia('(max-width: 900px)').matches) setSidebarOpen(false);
  };

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
  const requirements = asObject(context?.requirements), bindings = asObject(requirements.binding_summary);
  const unbound = Array.isArray(bindings.unbound) ? bindings.unbound.length : 0;
  const projectTasks = Array.isArray(context?.tasks) ? context.tasks.map(asObject) : [];
  const checks = asObject(context?.checks), actions = asObject(context?.actions);


  return <div className="ai-page">
    {topicId&&<TopicReportEditor key={topicId} topicId={topicId} connectionId={detail?.connection_id} onClose={()=>setTopicId(undefined)} onSaved={()=>setTopicRevision(r=>r+1)}/>}
    <div className={`ai-workspace${sidebarOpen ? ' ai-workspace--sidebar' : ''}`}>
      {sidebarOpen && <button className="ai-session-overlay" aria-label="关闭会话栏" onClick={() => setSidebarOpen(false)} />}
      <aside className="ai-sessions" aria-label="会话列表" aria-hidden={!sidebarOpen} {...(!sidebarOpen ? { inert: '' } : {})}>
        <div className="ai-sessions-inner">
        <div className="ai-sidebar-brand"><span className="ai-brand-mark" aria-hidden="true">⌘</span><strong>AI 工作台</strong>
          <Button type="text" icon={<MenuFoldOutlined />} aria-label="收起会话栏" onClick={() => setSidebarOpen(false)} /></div>
        <Button className="ai-new-session" type="text" icon={<EditOutlined />} loading={busy} onClick={() => { void newConversation(); }}>新建对话</Button>
        <Input className="ai-session-search" aria-label="搜索对话" prefix={<SearchOutlined />} placeholder="搜索对话" allowClear value={sessionSearch} onChange={(e) => setSessionSearch(e.target.value)} />
        <Button className="ai-sidebar-action" type="text" icon={<BookOutlined />} onClick={() => setExperienceOpen(true)}>操作经验</Button>
        <label className="ai-label">新对话项目</label>
        <Select aria-label="选择新对话所属项目" showSearch optionFilterProp="label" value={scope} options={projectOptions} style={{ width: '100%' }} onChange={setScope} />
        <div className="ai-muted ai-scope-title">对话</div>
        <div className="ai-session-list">{conversationGroups.map((group) => <details className="ai-session-group" open key={group.id} aria-label={`${group.name}的对话`}>
          <summary className="ai-session-group-title"><FolderOpenOutlined /><strong>{group.name}</strong><span>{group.conversations.length}</span></summary>
          {group.conversations.map((conversation) => <button key={conversation.id}
          aria-current={selected === conversation.id ? 'page' : undefined} className={`ai-session${selected === conversation.id ? ' selected' : ''}`} onClick={() => choose(conversation.id)}>
          <strong>{conversation.title}</strong><span>{conversation.updated_at.replace('T', ' ').slice(0, 16)}</span>
        </button>)}</details>)}</div>
        {!visibleConversations.length && <div className="ai-muted ai-empty-hint">暂无对话。这里汇总通用对话和所有未关闭项目的对话，已关闭项目的对话自动归档隐藏。</div>}
        {sessionSearch && !conversationGroups.length && <p className="ai-muted ai-empty-hint">没有匹配的对话</p>}
        <div className="ai-sidebar-footer">
          <Button type="text" icon={<ApiOutlined />} onClick={() => setSettingsOpen(true)}>模型连接</Button>
        </div>
        </div>
      </aside>

      <section className="ai-chat" aria-label="AI 对话窗口">
        <header className="ai-chat-header">
          <div className="ai-chat-heading">
            {!sidebarOpen && <Button type="text" icon={<MenuUnfoldOutlined />} aria-label="展开会话栏" onClick={() => setSidebarOpen(true)} />}
            <div><strong>{detail?.title ?? '新对话'}</strong><span className="ai-chat-project">{detail?.project_id ? targets.find((p) => p.id === detail.project_id)?.name ?? '项目会话' : '通用对话'}</span></div>
          </div>
          <div className="ai-actions">
            <Button type="text" aria-label="项目资料" icon={<FolderOpenOutlined />} disabled={!detail} onClick={() => setContextOpen(true)}>项目资料</Button>
            {detail && <>
              <Tooltip title="会话名称与提示词"><Button size="small" icon={<EditOutlined />} disabled={!!active} onClick={() => { form.setFieldsValue({ title: detail.title, prompt: detail.prompt }); setEditOpen(true); }} aria-label="编辑会话提示词" /></Tooltip>
              <Popconfirm title="删除此会话及其全部聊天记录？" onConfirm={async () => {
                try { await deleteAIConversation(detail.id); delete drafts.current[detail.id]; choose(null); await reloadList(); }
                catch (e) { void message.error(errorText(e)); }
              }}><Button size="small" icon={<DeleteOutlined />} disabled={!!active} aria-label="删除会话" /></Popconfirm>
            </>}
          </div>
        </header>
        {!connections.length && !loading && <Alert className="ai-chat-notice" type="info" showIcon message="先配置模型接口，再开始对话" action={<Button size="small" onClick={() => setSettingsOpen(true)}>配置连接</Button>} />}
        {error && <Alert className="ai-chat-notice" type="warning" closable onClose={() => setError('')} message={error} action={active ? <Button size="small" onClick={() => setStreamRevision((n) => n + 1)}>重新连接</Button> : undefined} />}
        {detail ? <>
          <div className="ai-messages" ref={messagesRef} onScroll={() => {
            const box = messagesRef.current;
            if (box) { autoScroll.current = box.scrollHeight - box.scrollTop - box.clientHeight < 100; setAwayFromBottom(!autoScroll.current); }
          }}>
            <div className="ai-message-column">
            {detail.has_more && <Button type="link" onClick={async () => {
              const id = detail.id;
              try { const older = await getAIConversation(id, detail.messages[0]?.seq); setDetail((old) => old?.id === id ? { ...old,
                messages: [...older.messages.filter((m) => !old.messages.some((existing) => existing.id === m.id)), ...old.messages],
                runs: [...old.runs, ...older.runs.filter((r) => !old.runs.some((existing) => existing.id === r.id))], has_more: older.has_more } : old); }
              catch (e) { void message.error(errorText(e)); }
            }}>加载更早的消息</Button>}
            {!detail.messages.length && <div className="ai-welcome"><span className="ai-welcome-mark" aria-hidden="true">✳</span><h2>今天想研究什么？</h2><p>{detail.project_id ? '每次发问会附加整个项目的目标、预期、任务状态与结果摘要。' : '可以讨论研究思路，也可以把原始需求发来，让AI建立项目和计算任务。'}</p>
              {['帮我梳理整个项目的结果与缺失信息', '对比已有结果与预期，提出下一步验证计划', '比较两个模型的科学性质，生成专题科研报告'].map((text) => <Button key={text} onClick={() => { setDraft(text); drafts.current[detail.id] = text; }}>{text}</Button>)}</div>}
            {detail.messages.map((item) => {
              const run = detail.runs.find((r) => r.message_id === item.id);
              return <article key={item.id} className={`ai-message ai-message--${item.role}`}>
                {item.role === 'user' ? <div className="ai-message-meta"><span>{item.created_at.replace('T', ' ').slice(5, 16)}</span></div> : null}
                {item.role === 'assistant' && run && (run.reasoning || run.tool_events?.length || isActiveRun(run)) ? <RunActivity key={run.id} run={run} hasAnswer={!!item.content} /> : null}
                {item.role === 'user' ? <div className="ai-user-text">{item.content}</div> : item.content || !run || !isActiveRun(run) ? <StreamingAnswer text={item.content} status={item.status} fresh={!!run && freshRuns.current.has(run.id)} onProgress={scrollAnswer} /> : null}
                {run?.error && <div className="ai-run-error">{run.error}</div>}
                {item.role === 'assistant' && (!!item.content || !run || !isActiveRun(run)) && <div className="ai-answer-tools">{run && !isActiveRun(run) && <span className={`ai-answer-state${run.status === 'failed' ? ' ai-run-error' : ''}`}>{STATUS[run.status]}{run.usage.total_tokens != null ? ` · ${run.usage.total_tokens.toLocaleString()} tokens` : ''}</span>}<Button size="small" type="text" onClick={() => { void navigator.clipboard?.writeText(item.content); }}>复制回答</Button>
                  {run && <Button size="small" type="text" onClick={() => { void getAIRun(run.id).then(setInspecting).catch((e) => message.error(errorText(e))); }}>本轮依据</Button>}
                </div>}
              </article>;
            })}
            {detail.project_id&&<TopicReportLinks inline conversationId={detail.id} runs={detail.runs} onOpen={setTopicId} revision={topicRevision}/>}
            </div>
          </div>

          {model&&detail.project_id&&(model.reasoning_capabilities.tool_policy==='unsupported'||model.reasoning_capabilities.tool_policy==='none_only'&&model.effective_reasoning_effort!=='none')&&<Alert type="warning" message={model.reasoning_capabilities.note}/>}
          <div className="ai-composer-dock">
          {awayFromBottom && <Button className="ai-jump-latest" shape="round" icon={<ArrowDownOutlined />} onClick={() => { autoScroll.current = true; scrollAnswer(); setAwayFromBottom(false); }}>回到最新</Button>}
          {active && <div className="ai-live-status" role="status"><span className="ai-live-dot" />{runProgress(active, !!detail.messages.find((m) => m.id === active.message_id)?.content)}<span>可随时停止</span></div>}
          <div className="ai-composer"><Input.TextArea aria-label="输入 AI 对话消息" value={draft} maxLength={16000} autoSize={{ minRows: 2, maxRows: 8 }} placeholder={active ? "可以先写下一条问题，当前回答结束后发送" : "询问任何问题，或描述你想完成的任务…"} disabled={busy}
            onChange={(e) => { setDraft(e.target.value); drafts.current[detail.id] = e.target.value; }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
            <div className="ai-composer-footer"><div className="ai-composer-options"><div className="ai-model-select"><Select aria-label="当前会话模型" placeholder="选择模型连接" value={model?.id} disabled={!!active || busy}
            options={connections.map((c) => ({ value: c.id, label: `${c.name} · ${c.model}` }))} style={{ width: '100%' }} onChange={async (value) => {
              const id = detail.id; setBusy(true);
              try { const result = await updateAIConversation(id, { title: detail.title, prompt: detail.prompt, connection_id: value }); if (selectedRef.current === id) setDetail(result); await reloadList(); }
              catch (e) { void message.error(errorText(e)); }
              finally { setBusy(false); }
            }} />

          </div><div className="ai-effort-control">
              {model&&<Select className="ai-reasoning-select" variant="borderless" aria-label="当前模型思考深度" value={model.effective_reasoning_effort} options={model.reasoning_capabilities.options.map(option=>({...option,label:`思考 · ${option.label}`}))} disabled={!!active||busy||model.reasoning_capabilities.options.length<2} onChange={async effort=>{
              setBusy(true);try{await saveAIConnection({name:model.name,base_url:model.base_url,model:model.model,max_tokens:model.max_tokens,is_default:model.is_default,reasoning_api:model.reasoning_api,reasoning_effort:effort,thinking_mode:effort==='default'?'default':effort==='none'?'disabled':'enabled'},model.id);await reloadConnections();void message.success('已更新此连接的默认思考深度，后续请求生效');}catch(e){void message.error(errorText(e));}finally{setBusy(false);}
            }}/>}
              </div></div><div className="ai-actions">
              {!active && <Tooltip title="重新生成上一条回答"><Button type="text" aria-label="重新生成" icon={<ReloadOutlined />} disabled={busy || !model || !detail.messages.some((m) => m.role === 'user')} onClick={() => { void send(true); }} /></Tooltip>}
              {active ? <Button className="ai-stop-button" shape="circle" aria-label="停止生成" icon={<StopOutlined />} onClick={async () => {
                const id = detail.id;
                try { await stopAIRun(active.id); const result = await getAIConversation(id); if (selectedRef.current === id) setDetail(result); }
                catch (e) { void message.error(errorText(e)); }
              }} /> : <>
                <Button className="ai-send-button" type="primary" shape="circle" aria-label="发送" icon={<ArrowUpOutlined />} loading={busy} disabled={!draft.trim() || !model} onClick={() => { void send(); }} />
              </>}
            </div></div>
          </div>
          <div className="ai-composer-hint">{detail.project_id ? '已连接项目上下文 · 模型按需调用工具' : '通用对话'}<span>Enter 发送 · Shift + Enter 换行</span></div>
          </div>
        </> : <div className="ai-no-conversation">{loading ? <Spin /> : <div className="ai-welcome"><span className="ai-welcome-mark" aria-hidden="true">✳</span><h2>今天想研究什么？</h2><p>从一个问题开始，分析结构、理解结果或整理研究思路。</p><Select aria-label="新对话的项目" value={scope} options={projectOptions} onChange={setScope} /><Button icon={<PlusOutlined />} loading={busy} onClick={() => { void newConversation(); }}>新建对话</Button></div>}</div>}
      </section>

    </div>
    <Drawer title="项目资料" open={contextOpen} onClose={() => setContextOpen(false)} width={560} rootClassName="ai-context-drawer">
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
              <h4>需求对应</h4><p className="ai-context-text">{requirements.status === 'ready' ? unbound ? `计算内容与预期已整理，仍有${unbound}项计算内容待关联。` : '计算内容与预期已整理，AI可按需读取关联任务和结果。' : requirements.status === 'pending' ? '资料已保存，计算内容与预期对应表待整理。' : '尚未填写项目需求。'}</p>
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
        </> : <div className="ai-empty-hint ai-muted">选择会话后展示对应数据。每次发问会重新读取本地快照；刷新不会发起远端同步。</div>}
      </aside>
    </Drawer>
    <WorkExperience open={experienceOpen} close={()=>setExperienceOpen(false)} connections={connections}/>
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
