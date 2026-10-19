/**
 * 报告注解（结果分析与论文参考）面板（2026-10-13 按用户口径重做）。
 *
 * 用户口径：**只在「重点科学结果分析」章节里出现** ——
 * - 每个类型一条总的（结构优化 / 自由能路径 / NEB 过渡态）；
 * - 结构优化：每个子项一条；自由能路径 / NEB：每个组一条；
 * - 电子结构子任务未完成，暂不提供。
 *
 * 交互：「＋ 添加分析」按钮 → 原生 `<dialog>` 编辑（ReportNoteDialog）；
 * 已填写时直接显示内容，并提供「编辑」「删除」（删除 = 两条都清空，后端会删掉该条）。
 */

import { useState } from 'react';
import { Alert, Button, Popconfirm, Tag, message } from 'antd';

import { saveReportNote } from '../../api/reports';
import { renderMarkdown } from '../../utils/markdown';
import ReportNoteDialog from './ReportNoteDialog';
import { useReportAI } from './ReportAIContext';

export interface NoteEntry {
  label?: string;
  analysis_note?: string;
  paper_note?: string;
}

interface Props {
  reportId: string;
  /** 注解 key：`type_opt` / `task_id` / `path:<group_id>` */
  noteKey: string;
  title: string;
  analysis?: string;
  paper?: string;
  /** 按钮旁的小字说明（例如"这一条只跟本任务绑定"） */
  hint?: string;
  /** 只读补充：自由能路径块里汇总组内各结构已填写的注解 */
  readOnly?: NoteEntry[];
  onSaved?: (notes: Record<string, { analysis_note: string; paper_note: string }>) => void;
}

function NoteText({ text }: { text: string }) {
  return (
    <div
      className="notes-text"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(text, { allowImages: false }) }}
    />
  );
}

export default function ReportNotePanel({
  reportId,
  noteKey,
  title,
  analysis = '',
  paper = '',
  hint,
  readOnly = [],
  onSaved,
}: Props) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const ai = useReportAI();
  const meta = ai?.notes[noteKey];
  const filled = Boolean(analysis.trim() || paper.trim());

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const res = await saveReportNote(reportId, noteKey, '', '', { expected_revision: meta?.revision });
      message.success('已删除这条分析');
      onSaved?.(res.notes);
      ai?.saved(res.notes, noteKey);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      {!filled ? (
        <div className="note-add-row">
          <button type="button" className="note-add-btn" onClick={() => setOpen(true)}>
            ＋ 添加分析
          </button>
          {hint ? <span className="note-hint">{hint}</span> : null}
        </div>
      ) : (
        <div className="notes-panel notes-panel--filled">
          <div className="notes-head">
            <span className="notes-head__title">{title}</span>
            <span className="notes-head__actions">
              <Button size="small" onClick={() => setOpen(true)}>
                编辑
              </Button>
              <Popconfirm
                title="删除这条分析？"
                description="删除后可以重新添加。"
                okText="删除"
                cancelText="取消"
                onConfirm={handleDelete}
              >
                <Button size="small" danger loading={deleting}>
                  删除
                </Button>
              </Popconfirm>
            </span>
          </div>
          <div className="notes-body">
            {analysis.trim() ? (
              <>
                <p className="notes-label">结果分析描述</p>
                <NoteText text={analysis} />
              </>
            ) : null}
            {paper.trim() ? (
              <>
                <p className="notes-label">论文写作参考</p>
                <NoteText text={paper} />
              </>
            ) : null}
            {readOnly.map((entry, index) => (
              <div className="notes-extra" key={`${entry.label ?? ''}-${index}`}>
                {entry.label ? <p className="notes-extra__title">{entry.label}</p> : null}
                {entry.analysis_note ? <NoteText text={entry.analysis_note} /> : null}
                {entry.paper_note ? <NoteText text={entry.paper_note} /> : null}
              </div>
            ))}
          </div>
        </div>
      )}
      {meta && filled && <div className="note-hint">
        <Tag>{meta.source === 'ai' ? 'AI' : '人工'}{meta.ai_origin ? '（基于 AI 草稿）' : ''}</Tag>
        {meta.model && <span>{meta.model} · {meta.generated_at}</span>}
        {meta.stale && <Alert type="warning" showIcon message="分析可能过期" description={meta.stale_reason} />}
      </div>}
      <ReportNoteDialog
        open={open}
        reportId={reportId}
        noteKey={noteKey}
        title={title}
        initialAnalysis={analysis}
        initialPaper={paper}
        onClose={() => setOpen(false)}
        onSaved={onSaved}
      />
    </>
  );
}
