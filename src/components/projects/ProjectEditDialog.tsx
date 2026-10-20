/**
 * 项目编辑弹窗（2026-10-12）：基础信息 + 两个报告辅助字段。
 *
 * - 原生 `<dialog>`（ESC/遮罩关闭、自带焦点管理），≤720px 时全屏；
 * - **名称只读**：本地/远端目录名就是项目名，改名会把路径全打断（2026-10-12 用户确认）；
 * - **优先级只读**：它是算出来的（urgency × workload），由交付日期与工作量决定；
 * - 交付日期沿用项目现有 `deadline` 字段（不新增 delivery_date）。
 */

import { useEffect, useRef, useState } from 'react';
import { Input, message } from 'antd';

import { updateProject } from '../../api/projects';
import type { Project } from '../../types';

/** 优先级象限 → 中文（urgent/not_urgent × large/small） */
function priorityLabel(project: Project | null): string {
  if (!project) return '';
  const urgency = project.urgency === 'urgent' ? '紧急' : '不紧急';
  const workload = project.workload === 'large' ? '大工作量' : '小工作量';
  return `${urgency} · ${workload}（${project.deadline || '无交付日期'}）`;
}

interface Props {
  open: boolean;
  project: Project | null;
  onClose: () => void;
  onSaved?: (project: Project) => void;
}

export default function ProjectEditDialog({ open, project, onClose, onSaved }: Props) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const [description, setDescription] = useState('');
  const [deadline, setDeadline] = useState('');
  const [calcDescription, setCalcDescription] = useState('');
  const [expectedResults, setExpectedResults] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!project) return;
    setDescription(project.description === '暂无描述' ? '' : (project.description ?? ''));
    setDeadline(project.deadline ?? '');
    setCalcDescription(project.calc_description ?? '');
    setExpectedResults(project.expected_results ?? '');
  }, [project, open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const handleSave = async () => {
    if (!project) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(deadline)) {
      message.warning('交付日期格式应为 YYYY-MM-DD');
      return;
    }
    setSaving(true);
    try {
      const res = await updateProject(project.id, {
        description,
        deadline,
        calc_description: calcDescription,
        expected_results: expectedResults,
      });
      message.success('项目已保存');
      onSaved?.(res.project);
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
      className="project-edit-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <header>
        <h3>编辑项目{project ? ` · ${project.name}` : ''}</h3>
        <button type="button" className="close" aria-label="关闭" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="body">
        <label className="field">
          <span>项目名称（不可改，目录名即项目名）</span>
          <Input value={project?.name ?? ''} readOnly disabled />
        </label>
        <div className="field-row">
          <label className="field">
            <span>交付日期</span>
            <Input
              value={deadline}
              placeholder="YYYY-MM-DD"
              onChange={(e) => setDeadline(e.target.value.trim())}
            />
          </label>
          <label className="field">
            <span>优先级（按交付日期与工作量计算，只读）</span>
            <Input value={priorityLabel(project)} readOnly disabled />
          </label>
        </div>
        <label className="field">
          <span>项目描述</span>
          <Input.TextArea
            value={description}
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <label className="field">
          <span>计算内容描述（写进报告「基本信息」，可空）</span>
          <Input.TextArea
            value={calcDescription}
            autoSize={{ minRows: 3, maxRows: 8 }}
            placeholder="例如：Ag@Al2O3 表面 7 条自由能路径的结构优化 + 频率矫正 + NEB"
            onChange={(e) => setCalcDescription(e.target.value)}
          />
        </label>
        <label className="field">
          <span>预期结果（写进报告「基本信息」，可空）</span>
          <Input.TextArea
            value={expectedResults}
            autoSize={{ minRows: 3, maxRows: 8 }}
            placeholder="例如：得到各路径的能垒与自由能台阶图，判断最优反应路径"
            onChange={(e) => setExpectedResults(e.target.value)}
          />
        </label>
        <p className="hint">
          保存后立即写入 data/projects.json；报告生成时会带进「基本信息」章节
          （交付日期 {deadline || '—'}，保存时间以文件修改为准）。
        </p>
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
