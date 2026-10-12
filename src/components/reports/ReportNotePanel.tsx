/**
 * 报告注解面板（2026-10-12）：结果分析描述 + 论文写作参考。
 *
 * - 原生 `<details>` 折叠，标题旁显示"未填写"或内容摘要；
 * - 点「填写 / 编辑」→ 原生 `<dialog>`（≤720px 全屏，见 ReportNoteDialog）；
 * - 「AI 生成」按钮已预留，当前置灰提示"即将支持"；
 * - 内容为空时显示"待填写"占位。
 */

import { useState } from 'react';
import { Button } from 'antd';

import ReportNoteDialog from './ReportNoteDialog';

export interface NoteEntry {
  label?: string;
  analysis_note?: string;
  paper_note?: string;
}

interface Props {
  reportId: string;
  noteKey: string;
  title: string;
  entries: NoteEntry[];
  onSaved?: (notes: Record<string, { analysis_note: string; paper_note: string }>) => void;
}

function summarize(entries: NoteEntry[]): string {
  const text = entries
    .flatMap((e) => [e.analysis_note, e.paper_note])
    .map((v) => (v || '').trim())
    .filter(Boolean)
    .join(' / ');
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}

export default function ReportNotePanel({ reportId, noteKey, title, entries, onSaved }: Props) {
  const [open, setOpen] = useState(false);
  const single = entries.length <= 1;
  const current = entries[0] ?? {};
  const summary = summarize(entries);

  return (
    <>
      <details className="notes-panel">
        <summary>
          {title}
          <span className="notes-panel__state">{summary || '未填写'}</span>
        </summary>
        <div className="notes-body">
          {entries.filter((e) => e.analysis_note || e.paper_note).length > 0 ? (
            entries
              .filter((e) => e.analysis_note || e.paper_note)
              .map((entry, index) => (
                <div key={`${entry.label ?? ''}-${index}`}>
                  {entry.label ? <h4>{entry.label}</h4> : null}
                  {entry.analysis_note ? (
                    <>
                      <p className="notes-label">结果分析描述</p>
                      <p>{entry.analysis_note}</p>
                    </>
                  ) : null}
                  {entry.paper_note ? (
                    <>
                      <p className="notes-label">论文写作参考</p>
                      <p>{entry.paper_note}</p>
                    </>
                  ) : null}
                </div>
              ))
          ) : (
            <p className="notes-empty">待填写：点下方「填写」补充结果分析描述与论文写作参考。</p>
          )}
          <div className="notes-actions">
            <Button size="small" onClick={() => setOpen(true)}>
              {summary ? '编辑' : '填写'}
            </Button>
            <Button size="small" disabled title="即将支持：接入大模型后自动生成">
              AI 生成（即将支持）
            </Button>
          </div>
        </div>
      </details>
      <ReportNoteDialog
        open={open}
        reportId={reportId}
        noteKey={noteKey}
        title={title}
        initialAnalysis={single ? current.analysis_note ?? '' : ''}
        initialPaper={single ? current.paper_note ?? '' : ''}
        onClose={() => setOpen(false)}
        onSaved={onSaved}
      />
    </>
  );
}
