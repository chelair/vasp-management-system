import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Select, Space, Tag } from 'antd';
import { listAIConnections, type AIConnection } from '../../api/aiChat';
import { fetchReportAIStatus, type ReportAIDraft, type ReportAIStatus } from '../../api/reports';
import type { ReportNote } from '../../types';
import { useReportWork } from './ReportWorkContext';

interface ReportAIValue {
  status: ReportAIStatus | null;
  notes: Record<string, ReportNote>;
  drafts: Record<string, ReportAIDraft>;
  available: boolean;
  busy: boolean;
  generatingKey: string | null;
  generate: (key: string) => Promise<void>;
  cancel: () => void;
  saved: (notes: Record<string, ReportNote>, key: string) => void;
  discard: (key: string) => void;
}
const Context = createContext<ReportAIValue | null>(null);
export const useReportAI = () => useContext(Context);

export function ReportAIProvider({ reportId, notes, onSaved, connectionId, onConnectionChange, children }: {
  reportId: string; notes: Record<string, ReportNote>; onSaved: (notes: Record<string, ReportNote>) => void;
  connectionId: string; onConnectionChange: (id: string) => void; children: ReactNode;
}) {
  const work = useReportWork();
  const [status, setStatus] = useState<ReportAIStatus | null>(null);
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [error, setError] = useState('');
  const currentNotes = useRef(notes); currentNotes.current = notes;
  useEffect(() => {
    let active = true;
    if (reportId) {
      const initialNotes = currentNotes.current;
      Promise.all([fetchReportAIStatus(reportId), listAIConnections()]).then(([value, models]) => {
        if (!active) return;
        setStatus(value); setConnections(models.items);
        if (currentNotes.current === initialNotes) onSaved(value.notes);
      }).catch(e => { if (active) setError(e instanceof Error ? e.message : '无法加载AI设置'); });
    }
    return () => { active = false; };
  }, [reportId, onSaved]);
  const available = Boolean(status?.enabled && connections.some(c => c.id === connectionId));
  const drafts = Object.fromEntries((work?.drafts ?? []).filter(d => d.report_id === reportId).map(d => [d.draft.key, d.draft]));
  const generate = async (key: string) => {
    if (!available) throw new Error('请开启AI报告撰写，并选择自己的模型连接');
    if (!await work?.start({ action: 'notes', report_id: reportId, keys: [key] })) throw new Error('未能启动，请在后台对话窗口查看原因');
  };
  const discard = (key: string) => { void work?.discard(reportId, key).catch(e => setError(e.message)); };
  const value: ReportAIValue = { status, notes, drafts, available, busy: work?.busy ?? false,
    generatingKey: null, generate, cancel: () => work?.stop(),
    saved: (value, key) => { onSaved(value); discard(key); }, discard };
  return <Context.Provider value={value}>
    <ControlsContext.Provider value={reportId ? <div className="report-ai-controls">
      {error ? <Alert type="warning" showIcon message={error} /> : status && !status.enabled ?
        <span>AI撰写未开启，可在智能报告页开启；人工注解正常使用。</span> : <Space wrap>
          <Tag color="blue">AI分析草稿</Tag>
          <Select aria-label="报告模型连接" placeholder="选择自己的模型连接" style={{ minWidth: 220 }} value={connectionId || undefined}
            disabled={value.busy} onChange={onConnectionChange} options={connections.map(c => ({ value: c.id, label: `${c.name} · ${c.model}` }))} />
          <Button disabled={!available || value.busy} onClick={() => void work?.start({ action: 'notes', report_id: reportId })}>生成缺失注解</Button>
          <Button onClick={() => work?.open()}>草稿与状态（{Object.keys(drafts).length}）</Button>
          <small>后台生成，草稿保留；预览保存后写入报告，已有注解自动跳过。</small>
        </Space>}
    </div> : null}>{children}</ControlsContext.Provider>
  </Context.Provider>;
}
const ControlsContext = createContext<ReactNode>(null);
export function ReportAIControls() { return useContext(ControlsContext); }
