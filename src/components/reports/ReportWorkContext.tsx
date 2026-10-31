import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Drawer, Input, Modal, Select, Tag, message } from 'antd';
import { request } from '../../api/client';
import { isActiveRun, listAIConnections, stopAIRun, watchAIRun, type AIConnection, type AIConversationDetail, type AIRun } from '../../api/aiChat';
import { saveReportNote, type ReportAIDraft } from '../../api/reports';
import ChatMarkdown from '../ai/ChatMarkdown';
import ReportRunActivity from './ReportRunActivity';
import './ReportWorkContext.css';
import { ReloadOutlined, ThunderboltOutlined, CommentOutlined, LoadingOutlined } from '@ant-design/icons';

type Action = 'generate' | 'notes' | 'comment' | 'chat';
interface WorkInput { action: Action; report_id?: string; comment_id?: string; keys?: string[]; content?: string }
interface Draft { report_id: string; run_id: string; title: string; draft: ReportAIDraft }
interface State { conversation: AIConversationDetail | null; drafts: Draft[] }
interface WorkValue {
  busy: boolean; run: AIRun | undefined; runs: AIRun[]; drafts: Draft[]; error: string;
  open: () => void; start: (input: WorkInput, scope?: string, reveal?: boolean) => Promise<boolean>;
  discard: (reportId: string, key: string) => Promise<void>; refresh: () => Promise<void>; reconnect: () => void; stop: () => void;
}
const Context = createContext<WorkValue | null>(null);
export const useReportWork = () => useContext(Context);
export function ReportWorkControls() {
  const work = useReportWork();
  return work ? <Button icon={work.busy ? <LoadingOutlined spin aria-hidden /> : <CommentOutlined aria-hidden />} onClick={work.open}>{work.busy ? '报告活动 · 处理中' : '报告活动'}{work.drafts.length ? `（${work.drafts.length}份草稿）` : ''}</Button> : null;
}
export function ReportGenerateButton({ projectId, all = false }: { projectId?: string | null; all?: boolean }) {
  const work = useReportWork();
  return <Button type={all ? 'default' : 'primary'} icon={all ? <ReloadOutlined /> : <ThunderboltOutlined />}
    disabled={!all && !projectId || work?.busy} onClick={() => void work?.start({ action: 'generate' }, all ? 'all' : projectId || '')}>
    {all ? '生成所有项目' : '生成报告'}
  </Button>;
}

export function ReportWorkProvider({ projectId, connectionId, onConnectionChange, onChanged, children }: {
  projectId: string; connectionId: string; onConnectionChange: (id: string) => void;
  onChanged: () => Promise<void>; children: ReactNode;
}) {
  const [scope, setScope] = useState(projectId);
  const [state, setState] = useState<State>({ conversation: null, drafts: [] });
  const [opened, setOpened] = useState(false);
  const [models, setModels] = useState<AIConnection[]>([]);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [posting, setPosting] = useState(false);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [analysis, setAnalysis] = useState('');
  const [paper, setPaper] = useState('');
  const [saving, setSaving] = useState(false);
  const [subscriptionVersion, setSubscriptionVersion] = useState(0);
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const callbacks = useRef({ onChanged, onConnectionChange, connectionId });
  callbacks.current = { onChanged, onConnectionChange, connectionId };
  const submitting = useRef(false);
  const completed = useRef(new Set<string>());
  const messagesRef = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const run = state.conversation?.runs.find(isActiveRun) ?? state.conversation?.runs[0];
  const busy = Boolean(run && isActiveRun(run));
  const messages = state.conversation?.messages;
  const lastMessage = messages && messages[messages.length - 1];
  useEffect(() => {
    if (opened && followMessages.current && messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [opened, lastMessage?.id, lastMessage?.content, run?.report_activity?.length, run?.tool_events?.length]);
  const refresh = useCallback(async () => {
    if (!scope) return;
    const result = await request<State>(`/reports/assistant/${encodeURIComponent(scope)}`);
    if (scopeRef.current !== scope) return;
    setState(result);
    if (!callbacks.current.connectionId && result.conversation?.connection_id) callbacks.current.onConnectionChange(result.conversation.connection_id);
  }, [scope]);
  useEffect(() => { setScope(projectId); setText(''); setError(''); setEditing(null); }, [projectId]);
  useEffect(() => {
    setState({ conversation: null, drafts: [] });
    void refresh().catch(e => { if (scopeRef.current === scope) setError(e.message || '无法恢复报告后台状态'); });
  }, [refresh, scope]);
  useEffect(() => {
    if (!opened) return;
    let alive = true;
    void listAIConnections().then(result => { if (alive) setModels(result.items); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [opened]);
  const activeId = run && isActiveRun(run) ? run.id : '';
  useEffect(() => {
    if (!activeId) return;
    const subscription = new AbortController();
    void watchAIRun(activeId, subscription.signal, update => {
      if (scopeRef.current !== scope) return;
      setState(old => old.conversation ? { ...old, conversation: { ...old.conversation,
        runs: [update.run, ...old.conversation.runs.filter(r => r.id !== update.run.id)],
        messages: old.conversation.messages.some(m => m.id === update.message.id)
          ? old.conversation.messages.map(m => m.id === update.message.id ? update.message : m)
          : [...old.conversation.messages, update.message] } } : old);
    }).catch(e => { if (!subscription.signal.aborted) setError(`${e.message}；后台仍在运行，可点击恢复连接。`); });
    // 仅取消订阅；关窗、切页或刷新都不向后台发送停止。
    return () => subscription.abort();
  }, [activeId, refresh, scope, subscriptionVersion]);
  useEffect(() => {
    if (!run || isActiveRun(run) || completed.current.has(run.id)) return;
    completed.current.add(run.id);
    void refresh().then(() => callbacks.current.onChanged()).catch(e => setError(e.message));
  }, [run, refresh]);
  const start = async (input: WorkInput, requestedScope = projectId, reveal = true) => {
    if (!requestedScope || submitting.current) return false;
    submitting.current = true; setPosting(true); if (reveal) setOpened(true); setError('');
    if (requestedScope !== scope) { scopeRef.current = requestedScope; setScope(requestedScope); }
    try {
      await request<AIRun>(`/reports/assistant/${encodeURIComponent(requestedScope)}`, {
        method: 'POST', body: JSON.stringify({ ...input, connection_id: connectionId || undefined,
          request_id: `${Date.now()}_${Math.random().toString(36).slice(2)}` }),
      });
      const result = await request<State>(`/reports/assistant/${encodeURIComponent(requestedScope)}`);
      if (scopeRef.current === requestedScope) { setState(result); setText(''); }
      return true;
    } catch (e) {
      if (scopeRef.current === requestedScope) setError(e instanceof Error ? e.message : '启动失败，请恢复连接核对后台状态');
      return false;
    } finally { submitting.current = false; setPosting(false); }
  };
  const discard = async (reportId: string, key: string) => {
    const item = state.drafts.find(d => d.report_id === reportId && d.draft.key === key);
    if (!item) return;
    await request(`/reports/assistant/${encodeURIComponent(scope)}/drafts/${item.run_id}/${encodeURIComponent(reportId + ':' + key)}`, { method: 'DELETE' });
    await refresh();
  };
  const stop = () => { if (run && isActiveRun(run)) void stopAIRun(run.id).then(refresh).catch(e => setError(e.message)); };
  const reconnect = () => { void refresh().then(() => { setError(''); setSubscriptionVersion(v => v + 1); }).catch(e => setError(e.message)); };
  return <Context.Provider value={{ busy: busy || posting, run, runs: state.conversation?.runs ?? [], error, drafts: state.drafts, open: () => { setOpened(true); void refresh().catch(e => setError(e.message)); }, start, discard, refresh, reconnect, stop }}>
    {children}
    <Drawer rootClassName="report-work-drawer" title="报告活动" open={opened} width={680} onClose={() => setOpened(false)}>
      <div className="report-work-intro"><strong>项目对话与处理记录</strong><p>批注的进展也会显示在对应批注下。关闭窗口后，后台继续处理。</p></div>
      {scope === 'all' && <Button onClick={() => setScope(projectId)}>返回当前项目对话</Button>}
      {error && <Alert type="warning" showIcon message={error} />}
      <div className="report-work-toolbar">
        <Select aria-label="后台处理范围" value={scope} onChange={setScope} style={{ minWidth: 130 }}
          options={[{ value: projectId, label: '当前项目' }, { value: 'all', label: '全部项目' }]} />
        <Select aria-label="报告后台模型" placeholder="选择自己的模型连接" value={connectionId || undefined} onChange={onConnectionChange}
          disabled={busy || posting} style={{ minWidth: 230 }} options={models.map(m => ({ value: m.id, label: `${m.name} · ${m.model}` }))} />
        <Button type="text" onClick={reconnect}>恢复连接</Button>
        {busy && <Button danger onClick={stop}>停止</Button>}
      </div>
      <div className="report-work-messages" role="log" aria-label="报告对话" ref={messagesRef}
        onScroll={e => { const el = e.currentTarget; followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; }}>
        {!state.conversation?.messages.length && <p>生成报告、处理批注或输入要求后，进度和交流会显示在这里。</p>}
        {state.conversation?.messages.map(item => {
          const task = state.conversation?.runs.find(r => r.message_id === item.id);
          return <article className={`report-work-message report-work-message--${item.role}`} key={item.id}>
            <div className="report-work-message-meta"><strong>{item.role === 'user' ? '你' : '报告助手'}</strong><time title={item.created_at}>{item.created_at.slice(11, 16)}</time></div>
            {task && <ReportRunActivity run={task} />}
            {!(task && item.content.startsWith('后台已开始')) && <ChatMarkdown text={item.content} />}
            {task?.error && <Alert type="warning" message={task.error} />}
          </article>;
        })}
      </div>
      {state.drafts.length > 0 && <div className="report-work-drafts"><strong>已保存的待审阅草稿</strong>
        {state.drafts.map(item => <div key={item.report_id + ':' + item.draft.key}><Tag>待审阅</Tag>{item.title}{' '}
          <Button size="small" onClick={() => { setEditing(item); setAnalysis(item.draft.analysis_note); setPaper(item.draft.paper_note); }}>预览与编辑</Button>
          <Button size="small" onClick={() => void discard(item.report_id, item.draft.key).catch(e => setError(e.message))}>放弃草稿</Button>
        </div>)}
      </div>}
      <div className="report-work-composer">
        <Input.TextArea aria-label="报告对话输入" rows={3} value={text} maxLength={16000} onChange={e => setText(e.target.value)}
          placeholder="补充数据、回答AI的问题，或说明希望怎样修改报告。" />
        <Button type="primary" disabled={busy || posting || !connectionId || !text.trim() || scope === 'all'} loading={posting}
          onClick={() => void start({ action: 'chat', content: text }, scope)}>发送</Button>
        {busy && <small>后台正在处理，可先填写补充内容，完成或停止后发送。</small>}
        {scope === 'all' && <small>这里查看批量进度；选择“当前项目”后可继续该项目的对话。</small>}
      </div>
    </Drawer>
    <Modal title={editing ? `草稿预览与编辑 · ${editing.title}` : '草稿预览'} open={Boolean(editing)} onCancel={() => setEditing(null)}
      onOk={async () => {
        if (!editing) return;
        setSaving(true);
        try {
          await saveReportNote(editing.report_id, editing.draft.key, analysis, paper, { draft_token: editing.draft.draft_token });
          await discard(editing.report_id, editing.draft.key); await callbacks.current.onChanged(); setEditing(null); message.success('已保存注解');
        } catch (e) { message.error(e instanceof Error ? e.message : '保存失败'); }
        finally { setSaving(false); }
      }} okText="保存到报告" confirmLoading={saving}>
      <p>核对并保存后才进入报告；已有人工修改与数据变化仍会检查。</p>
      <label>结果分析<Input.TextArea aria-label="后台草稿结果分析" rows={6} value={analysis} onChange={e => setAnalysis(e.target.value)} /></label>
      <label>论文参考<Input.TextArea aria-label="后台草稿论文参考" rows={6} value={paper} onChange={e => setPaper(e.target.value)} /></label>
    </Modal>
  </Context.Provider>;
}
