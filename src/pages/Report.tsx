import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Button,
  Dropdown,
  message as antdMessage,
  Card,
  Checkbox,
  Empty,
  Input,
  Popconfirm,
  Popover,
  Select,
  Skeleton,
  Tag,
} from 'antd';
import {
  DownOutlined,
  ExportOutlined,
  FileMarkdownOutlined,
  FileTextOutlined,
  PrinterOutlined,
  ReloadOutlined,
  RightOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  deleteProjectReport,
  fetchProjectReport,
  fetchProjectReports,
  generateProjectReports,
  reportChartUrl,
  reportImageUrl,
  reportHtmlUrl,
  reportMarkdownUrl,
  saveReportEdits,
} from '../api/reports';
import { fetchProjects } from '../api/projects';
import { createPortal } from 'react-dom';

import { getToken } from '../api/client';
import PageHeader from '../components/common/PageHeader';
import ReportNoteDialog from '../components/reports/ReportNoteDialog';
import ReportNotePanel from '../components/reports/ReportNotePanel';
import PageTransition from '../components/common/PageTransition';
import type { Project, ProjectReportDetail, ProjectReportMeta, ReportNote } from '../types';
import { renderMarkdown } from '../utils/markdown';

const STATUS_META: Record<string, { label: string; color: string }> = {
  normal: { label: '正常', color: 'success' },
  warning: { label: '警告', color: 'warning' },
  critical: { label: '异常', color: 'error' },
};

/** 工作量与工期（后端按「1 当量 = 1728 核时（24 核 × 3 天）、200 核 × 24h × 70% 产能」折算） */
interface ReportWorkload {
  total_units: number;
  done_units: number;
  remaining_units: number;
  core_hours_total: number;
  core_hours_done: number;
  core_hours_remaining: number;
  core_hours_per_weight: number;
  core_hours_per_day: number;
  max_cores: number;
  utilization: number;
  eta_days: number | null;
  eta_at: string | null;
}

/**
 * 智能报告（v0.7.0 重构）：以**单个项目**为报告单位。
 *
 * 后端生成结构化数据（report.json，schema 版本化，可直接喂大模型）+ Markdown +
 * SVG 图表；本页负责：按项目生成 / 列表 / 渲染 Markdown / 查看结构化数据 /
 * 按章节范围导出 HTML 与 PDF（浏览器打印）/ 下载 Markdown 与 JSON。
 */
export default function Report() {
  const { message } = App.useApp();
  const [projects, setProjects] = useState<Project[]>([]);
  const [reports, setReports] = useState<ProjectReportMeta[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [generating, setGenerating] = useState<string | null>(null);
  const [selectedSections, setSelectedSections] = useState<string[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  /** 报告注解（结果分析 / 论文参考）：key = task_id 或 section_<章节>（2026-10-12） */
  const [notes, setNotes] = useState<Record<string, ReportNote>>({});
  /** 任务块里的注解面板挂载点（<h5> 块尾），用 portal 渲染 */
  const [noteAnchors, setNoteAnchors] = useState<Record<string, HTMLElement>>({});
  /** 隐藏的章节 / 元素（持久化到 reports/edits/<id>.json） */
  const [hidden, setHidden] = useState<string[]>([]);
  /** 表格里「注」按钮打开的编辑弹窗 */
  const [tableNote, setTableNote] = useState<{ key: string; title: string } | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [showClosedReports, setShowClosedReports] = useState(false);

  const loadReports = useCallback(async () => {
    const list = await fetchProjectReports();
    setReports(list);
    return list;
  }, []);

  useEffect(() => {
    Promise.all([fetchProjects(), loadReports()])
      .then(([ps, list]) => {
        setProjects(ps);
        setSelectedProject(ps[0]?.id ?? null);
        // 默认选中**未关闭项目**的第一份报告，已关闭项目默认折叠、不主动抢焦点
        const closedNames = new Set(ps.filter((p) => p.closed).map((p) => p.name));
        const preferred = list.find((r) => !closedNames.has(r.project_name)) ?? list[0];
        setSelectedReportId((prev) => prev ?? preferred?.report_id ?? null);
      })
      .finally(() => setLoading(false));
  }, [loadReports]);

  useEffect(() => {
    if (!selectedReportId) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    fetchProjectReport(selectedReportId)
      .then((data) => {
        setDetail(data);
        setSelectedSections((data.sections ?? []).map((s) => s.key));
      })
      .catch((err) => message.error(err instanceof Error ? err.message : '读取报告失败'))
      .finally(() => setDetailLoading(false));
  }, [selectedReportId, message]);

  const handleGenerate = async (scope: { project_id?: string; all?: boolean }) => {
    const key = scope.all ? 'all' : scope.project_id ?? '';
    setGenerating(key);
    try {
      const result = await generateProjectReports({ ...scope, window_days: 7 });
      message.success(
        `已生成 ${result.reports.length} 份报告` +
          (result.failed.length ? `，失败 ${result.failed.length} 份` : ''),
      );
      if (result.failed.length) {
        message.warning(`${result.failed[0].project}：${result.failed[0].error}`);
      }
      const list = await loadReports();
      const fresh = result.reports[0] ?? list[0];
      if (fresh) setSelectedReportId(fresh.report_id);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '生成报告失败');
    } finally {
      setGenerating(null);
    }
  };

  const handleDelete = async (reportId: string) => {
    try {
      await deleteProjectReport(reportId);
      message.success('报告已删除');
      const list = await loadReports();
      if (selectedReportId === reportId) setSelectedReportId(list[0]?.report_id ?? null);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除报告失败');
    }
  };

  /** 导出 HTML / PDF（PDF 走浏览器打印，按勾选章节导出） */
  const exportHtml = (print: boolean) => {
    if (!detail) return;
    if (selectedSections.length === 0) {
      message.warning('请至少勾选一个章节');
      return;
    }
    const url = reportHtmlUrl(detail.meta.report_id, selectedSections, print, hidden);
    window.open(url, '_blank', 'noopener');
    if (print) message.info('已打开打印视图，选择「另存为 PDF」即可导出');
  };

  const projectsWithReports = useMemo(() => {
    const grouped = new Map<string, ProjectReportMeta[]>();
    reports.forEach((r) => {
      const list = grouped.get(r.project_name) ?? [];
      list.push(r);
      grouped.set(r.project_name, list);
    });
    return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh-CN'));
  }, [reports]);

  const filteredGroups = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return projectsWithReports;
    return projectsWithReports
      .map(([name, items]) => [
        name,
        items.filter(
          (i) =>
            name.toLowerCase().includes(kw) ||
            i.report_id.toLowerCase().includes(kw) ||
            (i.summary ?? '').toLowerCase().includes(kw),
        ),
      ] as [string, ProjectReportMeta[]])
      .filter(([, items]) => items.length > 0);
  }, [projectsWithReports, keyword]);

  /** 已关闭项目（全部可见任务归档后关闭）的报告折叠成一块，排在最后 */
  const closedProjectNames = useMemo(
    () => new Set(projects.filter((p) => p.closed).map((p) => p.name)),
    [projects],
  );
  const { activeGroups, closedGroups } = useMemo(() => {
    const active: [string, ProjectReportMeta[]][] = [];
    const closed: [string, ProjectReportMeta[]][] = [];
    filteredGroups.forEach((group) => {
      (closedProjectNames.has(group[0]) ? closed : active).push(group);
    });
    return { activeGroups: active, closedGroups: closed };
  }, [filteredGroups, closedProjectNames]);

  // 选中的报告属于已关闭项目时，自动展开折叠区，避免"选中了却看不见"
  const selectedIsClosed = useMemo(() => {
    if (!selectedReportId) return false;
    const report = reports.find((r) => r.report_id === selectedReportId);
    return !!report && closedProjectNames.has(report.project_name);
  }, [selectedReportId, reports, closedProjectNames]);
  useEffect(() => {
    if (selectedIsClosed) setShowClosedReports(true);
  }, [selectedIsClosed]);

  const visibleSections = useMemo(
    () => (detail?.markdown_sections ?? []).filter((s) => selectedSections.includes(s.key)),
    [detail, selectedSections],
  );

  useEffect(() => {
    setNotes(detail?.notes ?? {});
    setHidden(detail?.edits?.hidden_elements ?? []);
  }, [detail]);

  /** 隐藏/恢复：本地 state 立即生效并持久化（同一报告刷新后仍在） */
  const toggleHidden = useCallback(
    (key: string, hide: boolean) => {
      setHidden((prev) => {
        const next = hide ? Array.from(new Set([...prev, key])) : prev.filter((x) => x !== key);
        const reportId = detail?.meta.report_id;
        if (reportId) {
          void saveReportEdits(reportId, [], next).catch(() =>
            antdMessage.warning('隐藏状态保存失败（仅本次会话有效）'),
          );
        }
        return next;
      });
    },
    [detail?.meta.report_id],
  );

  /** 任务块标签（= markdown 里 #### 标题）→ 注解 key：opt/neb 任务用 task_id；自由能路径用 path:<组名> */
  const labelToTaskId = useMemo(() => {
    const map: Record<string, string> = {};
    const science = (detail?.structured as { science?: Record<string, any[]> } | undefined)?.science;
    for (const key of ['opt', 'neb']) {
      for (const item of (science?.[key] ?? []) as { task_id?: string; task_name?: string }[]) {
        if (item?.task_name && item?.task_id) map[String(item.task_name)] = String(item.task_id);
      }
    }
    for (const path of (science?.free_energy ?? []) as { group_name?: string }[]) {
      if (path?.group_name) map[String(path.group_name)] = `path:${path.group_name}`;
    }
    return map;
  }, [detail]);

  const noteBlocks = detail?.note_blocks ?? {};

  const renderedSections = useMemo(
    () =>
      visibleSections.map((section) => ({
        ...section,
        html: renderMarkdown(section.markdown, {
          // charts/xxx.svg 与 images/xxx.png 都按报告目录解析（后端两个接口）
          chartResolver: (path) =>
            detail
              ? path.startsWith('images/')
                ? reportImageUrl(detail.meta.report_id, path)
                : reportChartUrl(detail.meta.report_id, path)
              : path,
        }),
      })),
    [visibleSections, detail],
  );

  /** 渲染后在每个任务块（<h5> 起 → 下一个 h5/hr/h2 前）末尾放一个面板挂载点 */
  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const anchors: Record<string, HTMLElement> = {};
    root.querySelectorAll('section[data-report-section]').forEach((section: Element) => {
      const sectionKey = section.getAttribute('data-report-section') ?? '';
      const body = section.querySelector('.report-markdown');
      if (!body) return;
      const children = Array.from(body.children) as HTMLElement[];
      children.forEach((el, index) => {
        if (el.tagName !== 'H5') return;
        const label = (el.textContent ?? '').trim();
        if (!label) return;
        const anchorKey = `${sectionKey}:task:${label}`;
        let anchor = body.querySelector(
          `[data-note-anchor="${anchorKey.replace(/"/g, '')}"]`,
        ) as HTMLElement | null;
        if (!anchor) {
          anchor = document.createElement('div');
          anchor.className = 'report-note-anchor';
          anchor.setAttribute('data-note-anchor', anchorKey);
          // 块结束 = 下一个 H5 / HR / H2 之前；到章节末尾就追加在最后
          let cursor = index + 1;
          let endEl: Element | null = null;
          while (cursor < children.length) {
            const tag = children[cursor].tagName;
            if (tag === 'H5' || tag === 'HR' || tag === 'H2') {
              endEl = children[cursor];
              break;
            }
            cursor += 1;
          }
          if (endEl) endEl.before(anchor);
          else body.append(anchor);
        }
        anchors[anchorKey] = anchor;
      });
    });
    // 元素级隐藏：章节 / 任务块 / 图（三类），并给可隐藏元素挂「隐藏」按钮
    root.querySelectorAll('section[data-report-section]').forEach((section: Element) => {
      const sectionKey = section.getAttribute('data-report-section') ?? '';
      section.classList.toggle('report-hidden', hidden.includes(`section:${sectionKey}`));
      const body = section.querySelector('.report-markdown');
      if (!body) return;
      const children = Array.from(body.children) as HTMLElement[];
      let figureIndex = 0;
      children.forEach((el) => {
        if (el.tagName === 'H5') {
          const label = (el.textContent ?? '').trim();
          const key = `task:${sectionKey}:${label}`;
          el.classList.toggle('report-hidden', hidden.includes(key));
          if (!el.querySelector('.report-hide-btn')) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'report-hide-btn';
            btn.textContent = '隐藏';
            btn.title = '隐藏这个任务块（可在右上角「已隐藏」里恢复）';
            btn.addEventListener('click', (event) => {
              event.stopPropagation();
              toggleHidden(key, true);
            });
            el.append(btn);
          }
        }
        if (el.tagName === 'FIGURE' || el.querySelector(':scope > figure')) {
          const figures = el.tagName === 'FIGURE' ? [el] : Array.from(el.querySelectorAll('figure'));
          figures.forEach((fig) => {
            const key = `figure:${sectionKey}:${figureIndex}`;
            figureIndex += 1;
            fig.classList.toggle('report-hidden', hidden.includes(key));
            if (!fig.querySelector('.report-hide-btn')) {
              const btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'report-hide-btn';
              btn.textContent = '隐藏';
              btn.title = '隐藏这张图（可在右上角「已隐藏」里恢复）';
              btn.addEventListener('click', (event) => {
                event.stopPropagation();
                toggleHidden(key, true);
              });
              fig.prepend(btn);
            }
          });
        }
      });
    });

    // 自由能表格里的「结构 N」行：在可点 chip 旁加一个「注」按钮（编辑该中间体的注解）
    root.querySelectorAll('section[data-report-section] .report-markdown button.chip[data-dialog]').forEach(
      (chip: Element) => {
        const label = (chip.textContent ?? '').trim();
        if (!label.startsWith('结构 ')) return; // 只处理自由能表格（NEB 用映像块面板）
        const dialogId = chip.getAttribute('data-dialog') ?? '';
        if (!dialogId.startsWith('dlg_')) return;
        const taskId = dialogId.slice(4);
        if (!taskId || chip.nextElementSibling?.classList.contains('report-note-btn')) return;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'report-note-btn';
        btn.textContent = '注';
        btn.title = '填写结果分析描述 / 论文写作参考';
        btn.addEventListener('click', () =>
          setTableNote({ key: taskId, title: `${label} · 结果分析与论文参考` }),
        );
        chip.after(btn);
      },
    );
    setNoteAnchors(anchors);
  }, [renderedSections, notes, hidden, toggleHidden]);


  /** 点「结构 N / 映像 N」→ 打开对应的原生 <dialog> 三视图弹窗；点遮罩/× 关闭。 */
  const handleReportViewerClick = useCallback((event: { target: EventTarget | null }) => {
    const target = event.target as HTMLElement;
    const trigger = target.closest('[data-dialog]') as HTMLElement | null;
    if (trigger) {
      const dialog = document.getElementById(trigger.dataset.dialog ?? '');
      if (dialog instanceof HTMLDialogElement && !dialog.open) dialog.showModal();
      return;
    }
    const closeBtn = target.closest('[data-close]') as HTMLElement | null;
    if (closeBtn) {
      const dialog = closeBtn.closest('dialog');
      if (dialog instanceof HTMLDialogElement) dialog.close();
      return;
    }
    const dialog = target.closest('dialog.report-viewer');
    if (dialog instanceof HTMLDialogElement && target === dialog) dialog.close();
  }, []);

  /**
   * 图片兜底：`<img src="/api/reports/...">` 只带 Cookie 不带 Authorization，
   * Cookie 缺失/过期时会 401 裂图 —— 这里在 onError 时带 token 重新拉一次，转成 blob URL。
   */
  const handleReportAssetError = useCallback((event: { target: EventTarget | null }) => {
    const img = event.target as HTMLImageElement;
    if (!img || img.tagName !== 'IMG' || img.dataset.authRetry) return;
    img.dataset.authRetry = '1';
    const token = getToken();
    fetch(img.src, token ? { headers: { Authorization: `Bearer ${token}` } } : undefined)
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (blob) img.src = URL.createObjectURL(blob);
      })
      .catch(() => undefined);
  }, []);

  /** 当量 → 核时 → 工期（后端 basic_info.workload，口径见 process.md §6） */
  const detailBasic = useMemo(() => {
    return (
      (detail?.structured as
        | { basic_info?: { workload?: ReportWorkload; weighted_progress_percent?: number } }
        | undefined)?.basic_info ?? null
    );
  }, [detail]);
  const detailWorkload = detailBasic?.workload ?? null;
  const detailWeightedPercent = detailBasic?.weighted_progress_percent ?? null;

  /** 单个项目分组（已关闭项目的分组灰显） */
  const renderReportGroup = (
    [projectName, items]: [string, ProjectReportMeta[]],
    closed = false,
  ) => (
    <div
      key={projectName}
      className={`report-group${closed ? ' report-group--closed' : ''}`}
    >
      <div className="report-group__head">
        {projectName}
        <span className="report-group__count">{items.length}</span>
        {closed && <span className="report-group__closed">已关闭</span>}
      </div>
      {items.map((item) => {
        const meta = STATUS_META[item.project_status] ?? STATUS_META.normal;
        return (
          <button
            type="button"
            key={item.report_id}
            className={`report-item${selectedReportId === item.report_id ? ' is-active' : ''}`}
            onClick={() => setSelectedReportId(item.report_id)}
          >
            <span className="report-item__top">
              <Tag color={meta.color} bordered={false}>
                {meta.label}
              </Tag>
              <span className="report-item__time">
                {item.generated_at.replace('T', ' ').slice(5, 16)}
              </span>
            </span>
            <span className="report-item__summary">{item.summary}</span>
            <span className="report-item__stats">
              <span>完成度 {item.completion_percent ?? '—'}%</span>
              <span>图表 {item.chart_count}</span>
              <span className="report-item__risk">
                风险 {item.risk_summary?.high ?? 0}/{item.risk_summary?.medium ?? 0}/
                {item.risk_summary?.low ?? 0}
              </span>
            </span>
            <span className="report-item__footer">
              {/* 报告代码（rpt_…）不再显示：太长会把「删除」挤没（2026-10-12 用户反馈）；
                  搜索仍然按它匹配（见 filteredReports） */}
              <span className="report-item__hint">点开查看 / 导出</span>
              <Popconfirm
                title="删除该报告？"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => handleDelete(item.report_id)}
              >
                <span className="report-item__delete" onClick={(e) => e.stopPropagation()}>
                  删除
                </span>
              </Popconfirm>
            </span>
          </button>
        );
      })}
    </div>
  );

  return (
    <PageTransition>
      <PageHeader
        title="智能报告"
        subtitle="以项目为单位生成结构化报告：结构化数据（可喂大模型）+ Markdown + 图表，支持按章节导出 HTML / PDF"
        extra={
          <div className="report-actions">
            <Select
              value={selectedProject}
              onChange={setSelectedProject}
              style={{ width: 190 }}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              placeholder="选择项目"
            />
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={generating === selectedProject}
              disabled={!selectedProject}
              onClick={() => selectedProject && handleGenerate({ project_id: selectedProject })}
            >
              生成报告
            </Button>
            <Button
              icon={<ReloadOutlined />}
              loading={generating === 'all'}
              onClick={() => handleGenerate({ all: true })}
            >
              生成所有项目
            </Button>
          </div>
        }
      />

      <div className="report-grid">
        <Card
          className="report-list-card"
          title="项目报告"
          extra={
            <Input
              allowClear
              size="small"
              placeholder="搜索项目 / 报告 ID"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 170 }}
            />
          }
        >
          {loading ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : filteredGroups.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有报告，先点右上角「生成报告」"
            />
          ) : (
            <div className="report-list">
              {activeGroups.map((group) => renderReportGroup(group))}
              {closedGroups.length > 0 && (
                <div className="project-closed-block">
                  <button
                    type="button"
                    className="project-closed-toggle"
                    onClick={() => setShowClosedReports((v) => !v)}
                  >
                    {showClosedReports ? <DownOutlined /> : <RightOutlined />}
                    已关闭项目（{closedGroups.length}）
                  </button>
                  {showClosedReports && (
                    <div className="project-closed-list">
                      {closedGroups.map((group) => renderReportGroup(group, true))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>

        <Card
          className="report-detail-card"
          title="报告内容"
          extra={
            detail ? (
              <span className="report-hidden-control">
                {hidden.length > 0 ? (
                  <Dropdown
                    trigger={['click']}
                    menu={{
                      items: [
                        {
                          key: 'restore',
                          label: '恢复全部隐藏项',
                          onClick: () => {
                            setHidden([]);
                            if (detail.meta.report_id) {
                              void saveReportEdits(detail.meta.report_id, [], []).catch(() =>
                                antdMessage.warning('保存失败，仅本次会话有效'),
                              );
                            }
                          },
                        },
                        ...hidden.map((key) => ({
                          key,
                          label: (
                            <span className="report-hidden-item">
                              {key}
                              <a
                                onClick={(event) => {
                                  event.stopPropagation();
                                  toggleHidden(key, false);
                                }}
                              >
                                恢复
                              </a>
                            </span>
                          ),
                        })),
                      ],
                    }}
                  >
                    <Button size="small">已隐藏 {hidden.length} 项 ▾</Button>
                  </Dropdown>
                ) : null}
              <Popover
                trigger="click"
                placement="bottomRight"
                open={exportOpen}
                onOpenChange={setExportOpen}
                content={
                  <div className="report-export-pop">
                    <div className="report-export-pop__head">
                      <span>导出范围</span>
                      <Checkbox
                        checked={selectedSections.length === (detail.sections?.length ?? 0)}
                        indeterminate={
                          selectedSections.length > 0 &&
                          selectedSections.length < (detail.sections?.length ?? 0)
                        }
                        onChange={(e) =>
                          setSelectedSections(
                            e.target.checked
                              ? (detail.sections ?? []).map((s) => s.key)
                              : [],
                          )
                        }
                      >
                        全选
                      </Checkbox>
                    </div>
                    <div className="report-export-pop__sections">
                      {(detail.sections ?? []).map((s) => (
                        <Checkbox
                          key={s.key}
                          checked={selectedSections.includes(s.key)}
                          onChange={(e) =>
                            setSelectedSections((prev) =>
                              e.target.checked
                                ? [...prev, s.key]
                                : prev.filter((k) => k !== s.key),
                            )
                          }
                        >
                          {s.title}
                        </Checkbox>
                      ))}
                    </div>
                    <div className="report-export-pop__actions">
                      <Button
                        size="small"
                        icon={<FileMarkdownOutlined />}
                        onClick={() => {
                          window.open(reportMarkdownUrl(detail.meta.report_id), '_blank');
                          setExportOpen(false);
                        }}
                      >
                        下载 Markdown
                      </Button>
                      <Button
                        size="small"
                        icon={<FileTextOutlined />}
                        onClick={() => exportHtml(false)}
                      >
                        导出 HTML
                      </Button>
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        icon={<PrinterOutlined />}
                        onClick={() => exportHtml(true)}
                      >
                        导出 PDF
                      </Button>
                    </div>
                  </div>
                }
              >
                <Button size="small" type="primary" icon={<ExportOutlined />}>
                  导出
                </Button>
              </Popover>
              </span>
            ) : null
          }
        >
          {detailLoading ? (
            <Skeleton active paragraph={{ rows: 10 }} />
          ) : !detail ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="请选择左侧报告，或先生成一份新报告"
            />
          ) : (
            <div className="report-detail">
              <div className="report-detail__head">
                <div className="report-detail__title">
                  {detail.meta.project_name}
                  <Tag
                    color={STATUS_META[detail.meta.project_status]?.color ?? 'default'}
                    bordered={false}
                  >
                    {STATUS_META[detail.meta.project_status]?.label ?? detail.meta.project_status}
                  </Tag>
                </div>
                <div className="report-detail__meta">
                  <span className="path-cell">{detail.meta.report_id}</span>
                  <span>{detail.meta.generated_at.replace('T', ' ')}</span>
                  <span>schema {detail.schema_version}</span>
                  <span>
                    进度{' '}
                    {detailWeightedPercent != null
                      ? `${detailWeightedPercent}%（当量）`
                      : `${detail.meta.completion_percent ?? '—'}%`}
                    （任务 {detail.meta.completion_percent ?? '—'}%）
                  </span>
                  {detailWorkload ? (
                    <span>
                      工作量 {detailWorkload.total_units?.toFixed(1)} 当量 ≈{' '}
                      {Math.round(detailWorkload.core_hours_total).toLocaleString()} 核时
                    </span>
                  ) : null}
                  {detailWorkload ? (
                    <span className="report-detail__eta">
                      {detailWorkload.core_hours_remaining > 0 && detailWorkload.eta_at
                        ? `预计完成 ${detailWorkload.eta_at}（还需 ${detailWorkload.eta_days?.toFixed(1)} 天 · 有效算力 ${Math.round(detailWorkload.core_hours_per_day).toLocaleString()} 核时/天）`
                        : '已收尾（剩余工作量 0）'}
                    </span>
                  ) : null}
                  <span>
                    风险 高 {detail.meta.risk_summary?.high ?? 0} / 中{' '}
                    {detail.meta.risk_summary?.medium ?? 0} / 低{' '}
                    {detail.meta.risk_summary?.low ?? 0}
                  </span>
                </div>
              </div>

              <div className="report-body">
                  <nav className="report-toc">
                    {renderedSections.map((s) => (
                      <a key={s.key} href={`#report-${s.key}`}>
                        {s.title}
                      </a>
                    ))}
                  </nav>
                  <div className="report-content" ref={contentRef}>
                    {renderedSections.map((s) => (
                      <section key={s.key} id={`report-${s.key}`} data-report-section={s.key}>
                        <h2 className="report-section-title">{s.title}</h2>
                        <div
                          className="report-markdown"
                          onClick={handleReportViewerClick}
                          onErrorCapture={handleReportAssetError}
                          dangerouslySetInnerHTML={{ __html: s.html }}
                        />
                        {/* 模块级注解（结果分析 / 论文参考） */}
                        <ReportNotePanel
                          reportId={detail?.meta.report_id ?? ''}
                          noteKey={`section_${s.key}`}
                          title={`本章结果分析与论文参考（${s.title}）`}
                          entries={[notes[`section_${s.key}`] ?? { analysis_note: '', paper_note: '' }]}
                          onSaved={setNotes}
                        />
                      </section>
                    ))}
                    {/* 任务级注解面板：渲染到每个任务块（<h5> 起、到下一个 h5/hr 前）末尾 */}
                    {Object.entries(noteAnchors).map(([anchorKey, element]) => {
                      const label = anchorKey.split(':task:')[1] ?? '';
                      const entries = noteBlocks[label] ?? [];
                      const noteKey = labelToTaskId[label] ?? '';
                      if (!noteKey) {
                        // 自由能路径块：只读汇总各中间体的注解（各结构在表格行里点「注」编辑）
                        const filled = entries.filter((e) => e.analysis_note || e.paper_note);
                        if (filled.length === 0) return null;
                        return createPortal(
                          <details className="notes-panel">
                            <summary>
                              {label} · 结果分析与论文参考
                              <span className="notes-panel__state">{filled.length} 个结构已填写</span>
                            </summary>
                            <div className="notes-body">
                              {filled.map((entry, index) => (
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
                              ))}
                            </div>
                          </details>,
                          element,
                          anchorKey,
                        );
                      }
                      return createPortal(
                        <ReportNotePanel
                          reportId={detail?.meta.report_id ?? ''}
                          noteKey={noteKey}
                          title={`${label} · 结果分析与论文参考`}
                          entries={entries}
                          onSaved={setNotes}
                        />,
                        element,
                        anchorKey,
                      );
                    })}
                    {/* 表格里「注」按钮打开的注解编辑弹窗 */}
                    <ReportNoteDialog
                      open={tableNote !== null}
                      reportId={detail?.meta.report_id ?? ''}
                      noteKey={tableNote?.key ?? ''}
                      title={tableNote?.title ?? ''}
                      initialAnalysis={tableNote ? notes[tableNote.key]?.analysis_note ?? '' : ''}
                      initialPaper={tableNote ? notes[tableNote.key]?.paper_note ?? '' : ''}
                      onClose={() => setTableNote(null)}
                      onSaved={setNotes}
                    />

                    {/* 结构三视图弹窗：与导出的单文件 HTML 同一份数据（detail.dialogs） */}
                    {(detail?.dialogs ?? []).map((dialog) => (
                      <dialog
                        key={dialog.id}
                        id={dialog.id}
                        className="report-viewer"
                        onClick={handleReportViewerClick}
                        onErrorCapture={handleReportAssetError}
                      >
                        <header>
                          <h3>{dialog.title}</h3>
                          <button type="button" className="close" data-close aria-label="关闭">
                            ×
                          </button>
                        </header>
                        <div className="body">
                          {dialog.rows.map((row) => (
                            <div key={row.label}>
                              <p className="row-label">{row.label}</p>
                              <div className="report-img-row">
                                {(['a', 'b', 'c'] as const)
                                  .filter((axis) => row.views[axis])
                                  .map((axis) => (
                                    <figure className="report-figure" key={axis}>
                                      <img
                                        src={reportImageUrl(detail.meta.report_id, row.views[axis])}
                                        alt={`${axis} 视图`}
                                        loading="lazy"
                                        decoding="async"
                                      />
                                      <figcaption>{axis} 视图</figcaption>
                                    </figure>
                                  ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </dialog>
                    ))}
                    {renderedSections.length === 0 && (
                      <Empty description="未勾选任何章节" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    )}
                  </div>
              </div>
            </div>
          )}
        </Card>
      </div>
    </PageTransition>
  );
}
