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
  busy: boolean;
  saved: (notes: Record<string, ReportNote>, key: string) => void;
  discard: (key: string) => void;
}
const Context = createContext<ReportAIValue | null>(null);
export const useReportAI = () => useContext(Context);

export function ReportAIProvider({ reportId, enabled, notes, onSaved, connectionId, onConnectionChange, children }: {
  reportId: string; notes: Record<string, ReportNote>; onSaved: (notes: Record<string, ReportNote>) => void;
  enabled?: boolean;
  connectionId: string; onConnectionChange: (id: string) => void; children: ReactNode;
}) {
  const work = useReportWork();
  const [status, setStatus] = useState<ReportAIStatus | null>(null);
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [error, setError] = useState('');
  const currentNotes = useRef(notes); currentNotes.current = notes;
  useEffect(() => {
    let active = true;
    setStatus(null); setError('');
    if (reportId) {
      const initialNotes = currentNotes.current;
      Promise.all([fetchReportAIStatus(reportId), listAIConnections()]).then(([value, models]) => {
        if (!active) return;
        setStatus(value); setConnections(models.items);
        if (currentNotes.current === initialNotes) onSaved(value.notes);
      }).catch(e => { if (active) setError(e instanceof Error ? e.message : '无法加载AI设置'); });
    }
    return () => { active = false; };
  }, [reportId, enabled, onSaved]);
  const drafts = Object.fromEntries((work?.drafts ?? []).filter(d => d.report_id === reportId).map(d => [d.draft.key, d.draft]));
  const discard = (key: string) => { void work?.discard(reportId, key).catch(e => setError(e.message)); };
  const value: ReportAIValue = { status, notes, drafts, busy: work?.busy ?? false,
    saved: (value, key) => { onSaved(value); discard(key); }, discard };
  return <Context.Provider value={value}>
    <ControlsContext.Provider value={reportId ? <div className="report-ai-controls">
      {error ? <Alert type="warning" showIcon message={error} /> : status && !status.enabled ?
        <span>AI批注处理未开启；报告生成和人工注解正常使用。</span> : <Space wrap>
          <Tag color="blue">AI批注处理</Tag>
          <Select aria-label="报告模型连接" placeholder="选择自己的模型连接" style={{ minWidth: 220 }} value={connectionId || undefined}
            disabled={value.busy} onChange={onConnectionChange} options={connections.map(c => ({ value: c.id, label: `${c.name} · ${c.model}` }))} />
          <Button onClick={() => work?.open()}>草稿与状态（{Object.keys(drafts).length}）</Button>
          <small>仅处理你提交的批注，不自动撰写其他部分。</small>
        </Space>}
    </div> : null}>{children}</ControlsContext.Provider>
  </Context.Provider>;
}
const ControlsContext = createContext<ReactNode>(null);
export function ReportAIControls() { return useContext(ControlsContext); }
