import { useEffect, useRef, useState } from 'react';
import { CheckOutlined, LoadingOutlined, RightOutlined, PauseOutlined } from '@ant-design/icons';
import { isActiveRun, type AIRun } from '../../api/aiChat';
import { TOOL_NAMES } from '../ai/RunActivity';

export default function ReportRunActivity({ run, reportId, commentId }: { run: AIRun; reportId?: string; commentId?: string }) {
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const follow = useRef(true);
  const steps = (run.report_activity ?? []).filter(s => !commentId || s.comment_id === commentId && s.report_id === reportId);
  const last = steps[steps.length - 1];
  const current = run.report_activity?.[run.report_activity.length - 1];
  const active = isActiveRun(run) && (!commentId || current?.comment_id === commentId || !current)
    && last?.state !== 'completed' && last?.state !== 'blocked' && last?.state !== 'failed';
  const open = expanded ?? active;
  const tools = commentId ? [] : run.tool_events ?? [];
  const rows = steps.length ? steps : tools.map(e => ({ label: `${TOOL_NAMES[e.name] ?? '处理报告数据'}${e.status === 'completed' ? ' · 完成' : e.status === 'failed' ? ' · 未完成' : ''}`, at: e.at, state: e.status }));
  const preparing = run.status === 'queued' ? '已收到要求，等待开始处理' : tools.length ? '正在整理后续处理与回复' : '正在处理要求与报告数据';
  const modelActive = active && !steps.length && !tools.some(t => t.status === 'running');
  useEffect(() => {
    if (open && active && follow.current && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [open, active, rows.length, modelActive]);
  if (!rows.length && !active) return null;
  const failed = run.status === 'failed' || last?.state === 'failed';
  const stopped = ['cancelled', 'interrupted'].includes(run.status);
  return <div className={`report-run-trace${active ? ' is-running' : ''}`}>
    <button type="button" className="report-run-trace-toggle" aria-expanded={open} onClick={() => setExpanded(!open)}>
      {active ? <LoadingOutlined spin aria-hidden /> : stopped || failed ? <PauseOutlined aria-hidden /> : <CheckOutlined aria-hidden />}
      <span>{active ? open ? 'AI 正在处理' : last?.label || preparing : failed ? '本次处理未完成' : stopped ? '本次处理已停止' : last?.state === 'blocked' ? '已整理现有内容，等待补充' : '查看处理过程'}</span>
      <RightOutlined aria-hidden className={open ? 'is-open' : ''} />
    </button>
    {open && <ol className="report-run-trace-lines" aria-label="AI处理步骤" aria-live="polite" ref={listRef}
      onScroll={e => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 35; }}>
      {rows.map((step, i) => <li key={`${i}-${step.at}`} className={active && i === rows.length - 1 ? 'is-current' : ''}>
        <span className="report-run-trace-dot" /><span>{step.label}</span>
      </li>)}
      {modelActive && <li className="is-current"><span className="report-run-trace-dot" /><span>{preparing}</span></li>}
    </ol>}
  </div>;
}
