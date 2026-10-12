/**
 * 报告注解编辑弹窗（原生 <dialog>，≤720px 全屏）。面板与表格里的「注」按钮共用。
 */

import { useEffect, useRef, useState } from 'react';
import { Input, message } from 'antd';

import { saveReportNote } from '../../api/reports';

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

  useEffect(() => {
    if (open) {
      setAnalysis(initialAnalysis);
      setPaper(initialPaper);
    }
  }, [open, initialAnalysis, initialPaper]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await saveReportNote(reportId, noteKey, analysis, paper);
      message.success('已保存');
      onSaved?.(res.notes);
      onClose();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败');
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
      onClose();
      }}
      onClick={(event) => {
      if (event.target === ref.current) onClose();
      }}
    >
      <header>
        <h3>{title}</h3>
        <button type="button" className="close" aria-label="关闭" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="body">
        <label className="field">
          <span>结果分析描述（支持 **加粗** 与 - 列表）</span>
          <Input.TextArea
            value={analysis}
            autoSize={{ minRows: 4, maxRows: 12 }}
            placeholder="例如：结构 1–5 的离子步均已收敛，最大力 ≤ 0.02 eV/Å；NEB 能垒 0.12 eV，鞍点为映像 1"
            onChange={(e) => setAnalysis(e.target.value)}
          />
        </label>
        <label className="field">
          <span>论文写作参考</span>
          <Input.TextArea
            value={paper}
            autoSize={{ minRows: 4, maxRows: 12 }}
            placeholder="例如：可用作图 3 的能垒对比；方法部分需说明 NEB 使用 5 个映像与 VTST 优化"
            onChange={(e) => setPaper(e.target.value)}
          />
        </label>
        <p className="hint">保存后写入 data/reports/notes/&lt;report_id&gt;.json，刷新与导出都在。</p>
      </div>
      <footer>
        <button type="button" className="btn" onClick={onClose}>
          取消
        </button>
        <button type="button" className="btn btn--primary" disabled={saving} onClick={handleSave}>
          {saving ? '保存中…' : '保存'}
        </button>
      </footer>
    </dialog>
  );
}
