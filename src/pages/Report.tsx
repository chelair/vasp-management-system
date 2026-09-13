import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
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
  reportHtmlUrl,
  reportMarkdownUrl,
} from '../api/reports';
import { fetchProjects } from '../api/projects';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import type { Project, ProjectReportDetail, ProjectReportMeta } from '../types';
import { renderMarkdown } from '../utils/markdown';

const STATUS_META: Record<string, { label: string; color: string }> = {
  normal: { label: '正常', color: 'success' },
  warning: { label: '警告', color: 'warning' },
  critical: { label: '异常', color: 'error' },
};

/** 工作量与工期（后端按「1 当量 = 600 核时、200 核 × 24h × 70% 产能」折算） */
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
    const url = reportHtmlUrl(detail.meta.report_id, selectedSections, print);
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

  const renderedSections = useMemo(
    () =>
      visibleSections.map((section) => ({
        ...section,
        html: renderMarkdown(section.markdown, {
          chartResolver: (path) =>
            detail ? reportChartUrl(detail.meta.report_id, path) : path,
        }),
      })),
    [visibleSections, detail],
  );

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
              <span className="path-cell">{item.report_id}</span>
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
                  <div className="report-content">
                    {renderedSections.map((s) => (
                      <section key={s.key} id={`report-${s.key}`}>
                        <h2 className="report-section-title">{s.title}</h2>
                        <div
                          className="report-markdown"
                          dangerouslySetInnerHTML={{ __html: s.html }}
                        />
                      </section>
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
