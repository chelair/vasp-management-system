import { useState } from 'react';
import { CheckOutlined, CloseCircleOutlined, CodeOutlined, LoadingOutlined, PauseOutlined, RightOutlined } from '@ant-design/icons';
import { isActiveRun } from '../../api/aiChat';
import type { AIRun } from '../../api/aiChat';
import ThinkingText from './ThinkingText';
import AnimatedCollapse from '../common/AnimatedCollapse';

export const TOOL_NAMES: Record<string, string> = {
  get_project_setup_options: '查询项目创建选项', create_project_from_request: '建立项目与计算任务',
  create_calculation_contents: '登记计算任务', update_project_details: '更新项目资料',
  get_project_requirements: '读取计算内容与预期', save_project_requirements: '关联计算内容与预期',
  get_project_research_context: '读取研究目标与路径', analyze_reaction_path: '检查反应路径与端点结构',
  search_work_experience: '检索个人操作经验', list_workspace: '浏览目录', read_workspace: '读取文件', write_workspace: '创建草稿',
  find_project_tasks: '查找项目任务', get_task_inspections: '查看巡检结果', get_inspection_evidence: '读取巡检证据',
  get_opt_runs: '查看结构优化记录', get_task_parameter_history: '查看实际参数记录', get_remote_task_evidence: '远端只读补证',
  check_structure: '检查结构合理性与变化', get_structure_summary: '读取结构概览', get_structure_environment: '分析原子环境', compare_structures: '对比模型结构',
  get_bader_charges: '统计片段电荷', get_property_recipes: '查找性质计算方法', discover_property_tasks: '查找性质相关任务', evaluate_property: '计算科学性质',
  search_report_data: '搜索报告数据', create_topic_report: '生成专题报告', update_topic_report: '更新专题报告',
  list_topic_projects: '查找可访问项目', list_topic_reports: '查找已有报告', prepare_topic_report: '准备报告数据', plan_topic_report: '组织报告内容',
  write_topic_draft: '撰写报告草案', save_topic_report: '保存专题报告', get_topic_report: '读取专题报告',
  get_managed_plans: '查看托管计划', create_managed_plan: '创建托管计划', update_managed_plan: '更新托管计划', set_task_priority: '调整任务优先级',
};

const STATUS: Record<string, string> = { queued: '等待响应', running: '进行中', completed: '已完成', failed: '失败', cancelled: '已停止', interrupted: '已中断' };
const isPending = (status: string) => status === 'running' || status === 'queued';
function StateIcon({ status }: { status: string }) {
  return isPending(status) ? <LoadingOutlined spin /> : status === 'completed' ? <CheckOutlined />
    : status === 'failed' ? <CloseCircleOutlined /> : <PauseOutlined />;
}
function duration(run: AIRun) {
  if (!run.finished_at) return '';
  const seconds = Math.round((Date.parse(run.finished_at) - Date.parse(run.created_at)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function runProgress(run: AIRun, hasAnswer: boolean) {
  if (!isActiveRun(run)) return STATUS[run.status] ?? run.status;
  const tool = run.tool_events?.find((event) => isPending(event.status));
  if (tool) return TOOL_NAMES[tool.name] ?? `调用 ${tool.name}`;
  if (run.status === 'queued') return '等待模型响应';
  if (hasAnswer) return '正在整理回答';
  return run.reasoning ? '正在思考' : '正在分析';
}

/** 仅展示已有运行快照。思考是服务商汇总文本，不伪装为与工具交错的时间线。 */
export default function RunActivity({ run, hasAnswer }: { run: AIRun; hasAnswer: boolean }) {
  const active = isActiveRun(run);
  const [expanded, setExpanded] = useState<boolean>();
  const open = expanded ?? active;
  const events = run.tool_events ?? [];
  const failed = events.filter((event) => event.status === 'failed').length;
  const elapsed = duration(run);
  return <div className={`ai-activity${active ? ' ai-activity--active' : ''}`}>
    <button className="ai-activity-summary" aria-expanded={open} onClick={() => setExpanded(!open)}>
      <span className={`ai-state-icon ai-state-icon--${run.status}`}><StateIcon status={run.status} /></span>
      <span>{runProgress(run, hasAnswer)}</span>
      {events.length > 0 && <span className="ai-activity-count">{events.length} 次工具调用</span>}
      {failed > 0 && <span className="ai-activity-issues">{failed} 次调用失败</span>}
      {elapsed && <span className="ai-activity-duration">{elapsed}</span>}
      <RightOutlined className={`ai-activity-chevron collapse-chevron${open ? ' collapse-chevron--open' : ''}`} />
    </button>
    <AnimatedCollapse open={open}><div className="ai-activity-body">
      {run.reasoning && <details className="ai-thought">
        <summary>模型思考 <span>{active ? run.reasoning.trim().split('\n').filter(Boolean).slice(-1)[0]?.slice(0, 90) : '查看过程'}</span></summary>
        <ThinkingText text={run.reasoning} active={active} />
      </details>}
      {events.map((event) => {
        // 已停止的运行可能保留未收尾的工具状态，不继续显示旋转图标。
        const status = !active && isPending(event.status) ? 'interrupted' : event.status;
        const target = event.arguments?.path ?? event.arguments?.query ?? event.arguments?.task_name ?? event.arguments?.task_id;
        return <details className="ai-tool-call" key={event.id}>
          <summary>
            <span className={`ai-state-icon ai-state-icon--${status}`}><StateIcon status={status} /></span>
            <span className="ai-tool-call-title">{TOOL_NAMES[event.name] ?? event.name}</span>
            {target != null && <span className="ai-tool-target">{typeof target === 'string' ? target : JSON.stringify(target)}</span>}
            <span className="ai-tool-status">{STATUS[status] ?? status}</span><RightOutlined className="ai-tool-chevron" />
          </summary>
          <div className="ai-tool-detail">
            <div className="ai-tool-signature"><CodeOutlined /><code>{event.name}</code><span>工具调用</span></div>
            <div className="ai-tool-detail-label">输入</div><pre>{JSON.stringify(event.arguments, null, 2)}</pre>
            <div className="ai-tool-detail-label">{isPending(status) ? '等待工具返回' : status === 'interrupted' ? '已返回的记录 · 执行结果未确认' : '返回结果'}</div>
            {Object.keys(event.result ?? {}).length > 0 && <pre>{JSON.stringify(event.result, null, 2)}</pre>}
            {event.at && <div className="ai-tool-detail-label">记录时间 {event.at.replace('T', ' ')}</div>}
          </div>
        </details>;
      })}
      {!run.reasoning && !events.length && <p className="ai-muted">等待模型返回思考、工具调用或回答。</p>}
    </div></AnimatedCollapse>
  </div>;
}
