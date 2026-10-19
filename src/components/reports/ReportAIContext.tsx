import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Modal, Select, Space, Tag } from 'antd';
import { listAIConnections, type AIConnection } from '../../api/aiChat';
import { fetchReportAIStatus, generateReportNote, type ReportAIDraft, type ReportAIStatus } from '../../api/reports';
import type { ReportNote } from '../../types';
import ReportNoteDialog from './ReportNoteDialog';

interface ReportAIValue {
  status: ReportAIStatus | null;
  notes: Record<string, ReportNote>;
  drafts: Record<string, ReportAIDraft>;
  available: boolean;
  busy: boolean;
  generatingKey: string | null;
  generate: (key: string) => Promise<ReportAIDraft>;
  cancel: () => void;
  saved: (notes: Record<string, ReportNote>, key: string) => void;
  discard: (key: string) => void;
}
const Context = createContext<ReportAIValue | null>(null);
export const useReportAI = () => useContext(Context);

export function ReportAIProvider({ reportId, notes, onSaved, connectionId, onConnectionChange,
  autoGenerate, onAutoStarted, children }: {
  reportId: string; notes: Record<string, ReportNote>; onSaved: (notes: Record<string, ReportNote>) => void;
  connectionId: string; onConnectionChange: (id: string) => void;
  autoGenerate: boolean; onAutoStarted: () => void; children: ReactNode;
}) {
  const [status, setStatus] = useState<ReportAIStatus | null>(null);
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [error, setError] = useState('');
  const [drafts, setDrafts] = useState<Record<string, ReportAIDraft>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [generatingKey, setGeneratingKey] = useState<string | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const stopBatch = useRef(false);
  const autoStarted = useRef(false);
  const currentNotes = useRef(notes);
  currentNotes.current = notes;
  const available = Boolean(status?.enabled && connections.some(c => c.id === connectionId));

  useEffect(() => {
    active.current = true;
    if (reportId) {
      const initialNotes = currentNotes.current;
      Promise.all([fetchReportAIStatus(reportId), listAIConnections()]).then(([value, models]) => {
        if (!active.current) return;
        setStatus(value); setConnections(models.items);
        if (currentNotes.current === initialNotes) onSaved(value.notes);
      }).catch(e => { if (active.current) setError(e instanceof Error ? e.message : '无法加载 AI 设置'); });
    }
    return () => { active.current = false; stopBatch.current = true; controller.current?.abort(); };
  }, [reportId, onSaved]);

  const discard = (key: string) => setDrafts(old => { const next = { ...old }; delete next[key]; return next; });
  const cancel = () => { stopBatch.current = true; controller.current?.abort(); };
  const generate = async (key: string) => {
    if (!available) throw new Error('请先在项目设置开启 AI 撰写，并选择自己的模型连接');
    if (controller.current) throw new Error('请等待当前草稿完成或取消生成');
    const pending = new AbortController(); controller.current = pending; setGeneratingKey(key);
    try {
      const draft = await generateReportNote(reportId, key, connectionId, pending.signal);
      if (pending.signal.aborted || !active.current) throw new Error('生成已取消');
      setDrafts(old => ({ ...old, [key]: draft }));
      setFailures(old => { const next = { ...old }; delete next[key]; return next; });
      return draft;
    } catch (e) {
      const reason = pending.signal.aborted ? '已取消；原注解未改动' : (e instanceof Error ? e.message : '生成失败');
      if (active.current) setFailures(old => ({ ...old, [key]: reason }));
      throw new Error(reason);
    } finally {
      if (controller.current === pending) controller.current = null;
      if (active.current) setGeneratingKey(null);
    }
  };

  const batch = async () => {
    if (batchRunning || controller.current) return;
    stopBatch.current = false; setBatchRunning(true); setBatchOpen(true);
    try {
      // 任一字段有人填写即整条跳过，批量从不替换人工或已保存的 AI 注解。
      for (const target of status?.targets ?? []) {
        const note = currentNotes.current[target.key];
        if (stopBatch.current || !active.current) break;
        if (note?.analysis_note?.trim() || note?.paper_note?.trim() || drafts[target.key]) continue;
        try { await generate(target.key); } catch { /* 部分失败保留其他草稿，后续可逐条重试 */ }
      }
    } finally { if (active.current) setBatchRunning(false); }
  };

  useEffect(() => {
    if (!autoGenerate || !status || !available || autoStarted.current) return;
    autoStarted.current = true; onAutoStarted(); void batch();
    // 自动撰写仅在用户本轮生成报告且明确选择连接后启动；普通打开报告不会付费调用模型。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoGenerate, status, available]);

  const saved = (value: Record<string, ReportNote>, key: string) => { onSaved(value); discard(key); };
  const value: ReportAIValue = { status, notes, drafts, available, busy: batchRunning || generatingKey !== null,
    generatingKey, generate, cancel, saved, discard };
  const title = (key: string) => status?.targets.find(t => t.key === key)?.title ?? key;

  return <Context.Provider value={value}>
    <ControlsContext.Provider value={reportId ? <div className="report-ai-controls">
      {error ? <Alert type="warning" showIcon message={`AI 撰写暂不可用：${error}；普通报告正常`} /> :
        status && !status.enabled ? <span>AI 撰写未开启，可在项目设置中开启；人工注解正常使用。</span> :
        <Space wrap>
          <Tag color="blue">AI 分析草稿</Tag>
          <Select aria-label="报告模型连接" placeholder="选择自己的模型连接" style={{ minWidth: 220 }}
            value={connectionId || undefined} disabled={value.busy} onChange={onConnectionChange}
            options={connections.map(c => ({ value: c.id, label: `${c.name} · ${c.model}` }))} />
          <Button disabled={!available || value.busy} onClick={() => void batch()}>生成缺失注解</Button>
          {value.busy && <Button onClick={cancel}>取消生成</Button>}
          <Button onClick={() => setBatchOpen(true)}>草稿与状态（{Object.keys(drafts).length}）</Button>
          {!connections.length && status && <span>未配置模型，请先到 AI 工作台添加自己的连接。</span>}
          {autoGenerate && !connectionId && <span>普通报告已就绪；选择连接后自动生成缺失草稿。</span>}
          <small>草稿须预览确认后保存，批量跳过已有注解。</small>
        </Space>}
    </div> : null}>
      {children}
    </ControlsContext.Provider>
    <Modal title="AI 草稿与生成状态" open={batchOpen} onCancel={() => { cancel(); setBatchOpen(false); }}
      footer={<Space>{value.busy && <Button onClick={cancel}>取消生成</Button>}<Button onClick={() => setBatchOpen(false)}>返回报告</Button></Space>}>
      <p>关闭此窗口会取消当前生成。成功草稿暂存本页，离开报告即放弃；已有注解不会自动覆盖。</p>
      {(status?.targets ?? []).map(target => {
        const note = notes[target.key];
        const filled = Boolean(note?.analysis_note?.trim() || note?.paper_note?.trim());
        return <div key={target.key} style={{ marginBlock: 12 }}>
          <strong>{target.title}</strong>{' '}
          <span>{generatingKey === target.key ? '生成中…' : drafts[target.key] ? '草稿待审阅' :
            failures[target.key] || (filled ? '已保存，批量跳过' : '未生成')}</span>{' '}
          {drafts[target.key] && <Button size="small" onClick={() => { setBatchOpen(false); setEditing(target.key); }}>预览与编辑</Button>}
        </div>;
      })}
    </Modal>
    <ReportNoteDialog open={editing !== null} reportId={reportId} noteKey={editing ?? ''} title={editing ? title(editing) : ''}
      initialAnalysis={editing ? notes[editing]?.analysis_note ?? '' : ''}
      initialPaper={editing ? notes[editing]?.paper_note ?? '' : ''}
      onClose={() => setEditing(null)} onSaved={onSaved} />
  </Context.Provider>;
}

const ControlsContext = createContext<ReactNode>(null);
export function ReportAIControls() { return useContext(ControlsContext); }
