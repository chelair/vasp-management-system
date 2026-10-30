/**
 * 报告注解编辑弹窗（原生 <dialog>，≤720px 全屏）。面板与表格里的「注」按钮共用。
 */

import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Space, message } from 'antd';

import { saveReportNote, type ReportAIDraft } from '../../api/reports';
import { useReportAI } from './ReportAIContext';
import { renderMarkdown } from '../../utils/markdown';

interface Props {
  open: boolean;
  reportId: string;
  noteKey: string;
  title: string;
  initialAnalysis: string;
  initialPaper: string;
  onClose: () => void;
  onSaved?: (notes: Record<string, { analysis_note: string; paper_note: string }>) => void;
}

export default function ReportNoteDialog({
  open,
  reportId,
  noteKey,
  title,
  initialAnalysis,
  initialPaper,
  onClose,
  onSaved,
}: Props) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const [analysis, setAnalysis] = useState(initialAnalysis);
  const [paper, setPaper] = useState(initialPaper);
  const [saving, setSaving] = useState(false);
  const ai = useReportAI();
  const [preview, setPreview] = useState<ReportAIDraft | null>(null);
  const [adopted, setAdopted] = useState<ReportAIDraft | null>(null);
  const [feedback, setFeedback] = useState('');
  const beforeGeneration = useRef<{ analysis: string; paper: string } | null>(null);
  const revision = useRef<string | undefined>(undefined);
  const active = useRef(false);
  const identity = useRef('');
  identity.current = `${reportId}:${noteKey}`;
  const generating = ai?.generatingKey === noteKey;

  useEffect(() => {
    if (open) {
      setAnalysis(initialAnalysis);
      setPaper(initialPaper);
      setPreview(ai?.drafts[noteKey] ?? null); setAdopted(null);
      setFeedback('');
      beforeGeneration.current = null;
      revision.current = ai?.notes[noteKey]?.revision ?? ai?.status?.empty_revision;
    }
    active.current = open;
    // 异步结果和外部注解更新不能覆盖正在输入的人工文本。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reportId, noteKey]);

  useEffect(() => () => { active.current = false; }, []);

  const close = () => { onClose(); };

  const backgroundDraft = ai?.drafts[noteKey];
  useEffect(() => {
    if (open && backgroundDraft) setPreview(backgroundDraft);
  }, [open, backgroundDraft]);

  const generate = async () => {
    const startedFor = identity.current;
    setFeedback('');
    try {
      await ai?.generate(noteKey);
      if (active.current && identity.current === startedFor) setFeedback('已交给后台，可关闭弹窗，在“报告进度与对话”中查看进度和草稿。');
    } catch (e) {
      if (active.current && identity.current === startedFor) setFeedback(e instanceof Error ? e.message : '生成失败');
    }
  };

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setFeedback('');
    try {
      const res = await saveReportNote(reportId, noteKey, analysis, paper, adopted ?
        { draft_token: adopted.draft_token } : { expected_revision: revision.current });
      message.success('已保存');
      ai?.saved(res.notes, noteKey);
      onSaved?.(res.notes);
      close();
    } catch (e) {
      setFeedback(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <dialog
      ref={ref}
      className="note-edit-dialog"
      onCancel={(event) => {
      event.preventDefault();
      close();
      }}
      onClick={(event) => {
      if (event.target === ref.current) close();
      }}
    >
      <header>
        <h3>{title}</h3>
        <button type="button" className="close" aria-label="关闭" onClick={close}>
          ×
        </button>
      </header>
      <div className="body">
        {ai && <Space wrap style={{ marginBottom: 12 }}>
          <Button disabled={!ai.available || ai.busy || saving} onClick={() => void generate()}>
            {preview || initialAnalysis || initialPaper ? 'AI 重新生成' : 'AI 生成'}
          </Button>
          {generating && <Button onClick={ai.cancel}>取消生成</Button>}
          <small>{generating ? '生成中…' : !ai.status?.enabled ? '项目未开启 AI 撰写' : !ai.available ? '请在报告上方选择自己的模型连接' : '生成只提供预览，不改动当前文本'}</small>
        </Space>}
        {feedback && <Alert type="warning" showIcon message={feedback} />}
        {ai?.notes[noteKey]?.stale && <Alert type="warning" showIcon message="分析可能过期" description={ai.notes[noteKey].stale_reason} />}
        {preview && <div className="report-ai-preview">
          <p><strong>AI 草稿预览 · 尚未保存</strong> · {preview.model} · {preview.generated_at}</p>
          <p>结果分析描述</p>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(preview.analysis_note, { allowImages: false }) }} />
          <p>论文写作参考</p>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(preview.paper_note, { allowImages: false }) }} />
          <Space wrap>
            <Button disabled={adopted?.draft_token === preview.draft_token} onClick={() => {
              beforeGeneration.current = { analysis, paper };
              setAnalysis(preview.analysis_note); setPaper(preview.paper_note); setAdopted(preview);
            }}>采用草稿到编辑区</Button>
            <Button onClick={() => {
              if (adopted && beforeGeneration.current) {
                setAnalysis(beforeGeneration.current.analysis); setPaper(beforeGeneration.current.paper);
              }
              setAdopted(null); setPreview(null); ai?.discard(noteKey);
            }}>放弃草稿</Button>
          </Space>
        </div>}
        <label className="field">
          <span>结果分析描述（支持 **加粗** 与 - 列表）</span>
          <Input.TextArea
            value={analysis}
            autoSize={{ minRows: 4, maxRows: 12 }}
            placeholder="例如：结构 1–5 的离子步均已收敛，最大力 ≤ 0.02 eV/Å；NEB 能垒 0.12 eV，鞍点为映像 1"
            disabled={saving} onChange={(e) => setAnalysis(e.target.value)}
          />
        </label>
        <label className="field">
          <span>论文写作参考</span>
          <Input.TextArea
            value={paper}
            autoSize={{ minRows: 4, maxRows: 12 }}
            placeholder="例如：可用作图 3 的能垒对比；方法部分需说明 NEB 使用 5 个映像与 VTST 优化"
            disabled={saving} onChange={(e) => setPaper(e.target.value)}
          />
        </label>
        {beforeGeneration.current && <Button disabled={saving} onClick={() => {
          const old = beforeGeneration.current;
          if (old) { setAnalysis(old.analysis); setPaper(old.paper); setAdopted(null); }
        }}>恢复本次生成前文本</Button>}
        {ai?.notes[noteKey]?.previous_note && <Button disabled={saving || ai.busy} onClick={async () => {
          setSaving(true);
          try {
            const result = await saveReportNote(reportId, noteKey, '', '', {
              restore_previous: true, expected_revision: revision.current,
            });
            ai.saved(result.notes, noteKey); onSaved?.(result.notes); close();
          } catch (e) { setFeedback(e instanceof Error ? e.message : '恢复失败'); }
          finally { setSaving(false); }
        }}>恢复上次生成前文本并保存</Button>}
        <p className="hint">AI 草稿需采用、核对并保存后才写入报告；人工修改优先。关闭弹窗保留原有已保存注解。</p>
      </div>
      <footer>
        <button type="button" className="btn" onClick={close}>
          取消
        </button>
        <button type="button" className="btn btn--primary" disabled={saving || generating} onClick={handleSave}>
          {saving ? '保存中…' : '保存'}
        </button>
      </footer>
    </dialog>
  );
}
