import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Select,
  Skeleton,
  Tag,
  Tooltip,
} from 'antd';
import {
  CopyOutlined,
  FileMarkdownOutlined,
  FileTextOutlined,
  FileZipOutlined,
  PrinterOutlined,
  ReloadOutlined,
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
import NebImages3DViewer from '../components/inspection/NebImages3DViewer';
import Structure3DViewer from '../components/inspection/Structure3DViewer';
import type { Project, ProjectReportDetail, ProjectReportMeta } from '../types';
import { renderMarkdown } from '../utils/markdown';

const STATUS_META: Record<string, { label: string; color: string }> = {
  normal: { label: '正常', color: 'success' },
  warning: { label: '警告', color: 'warning' },
  critical: { label: '异常', color: 'error' },
};

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
  const [viewMode, setViewMode] = useState<'markdown' | 'structured'>('markdown');
  const [selectedSections, setSelectedSections] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');

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
        setSelectedReportId((prev) => prev ?? list[0]?.report_id ?? null);
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

  const downloadJson = async () => {
    if (!detail) return;
    const blob = new Blob([JSON.stringify(detail.structured, null, 2)], {
      type: 'application/json;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${detail.meta.report_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
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

  /** 科学结果里的交互式结构视图（前端 3Dmol；导出走静态三视图/对比矩阵） */
  const interactiveStructures = useMemo(() => {
    const science = (detail?.structured as Record<string, any> | undefined)?.science;
    if (!science) return null;
    const optItems: any[] = (science.opt ?? []).filter(
      (item: any) => item.structure?.contcar_cif || item.structure?.poscar_cif,
    );
    const nebItems: any[] = (science.neb ?? []).filter(
      (item: any) => (item.images_with_structure ?? []).some((i: any) => i.cif),
    );
    if (optItems.length === 0 && nebItems.length === 0) return null;
    return (
      <Collapse
        ghost
        className="report-3d"
        defaultActiveKey={[]}
        items={[
          ...optItems.map((item) => ({
            key: `opt-${item.task_id}`,
            label: `${item.task_name} · ${item.converged ? '已收敛' : '未收敛'} · 交互结构（可旋转缩放）`,
            children: (
              <Structure3DViewer
                poscarCif={item.structure?.poscar_cif ?? null}
                contcarCif={item.structure?.contcar_cif ?? null}
              />
            ),
          })),
          ...nebItems.map((item) => ({
            key: `neb-${item.task_id}`,
            label: `${item.task_name} · ${item.image_count} 个映像结构（IS → 中间态 → FS）`,
            children: (
              <NebImages3DViewer
                images={(item.images_with_structure ?? [])
                  .filter((image: any) => image.cif)
                  .map((image: any, index: number, list: any[]) => ({
                    label: String(image.label ?? index),
                    role:
                      index === 0 ? 'is' : index === list.length - 1 ? 'fs' : 'middle',
                    cif: image.cif,
                    energy:
                      (item.images ?? []).find((x: any) => x.label === image.label)?.energy_ev ??
                      null,
                    relative:
                      (item.images ?? []).find((x: any) => x.label === image.label)
                        ?.relative_energy_ev ?? null,
                    max_force:
                      (item.images ?? []).find((x: any) => x.label === image.label)
                        ?.max_force_ev_per_a ?? null,
                  }))}
              />
            ),
          })),
        ]}
      />
    );
  }, [detail]);

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
          title="报告历史"
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
              {filteredGroups.map(([projectName, items]) => (
                <div key={projectName} className="report-group">
                  <div className="report-group__head">
                    {projectName}
                    <span className="report-group__count">{items.length}</span>
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
                            <span
                              className="report-item__delete"
                              onClick={(e) => e.stopPropagation()}
                            >
                              删除
                            </span>
                          </Popconfirm>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="report-detail-card" title="报告内容">
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
                  <span>完成度 {detail.meta.completion_percent ?? '—'}%</span>
                  <span>
                    风险 高 {detail.meta.risk_summary?.high ?? 0} / 中{' '}
                    {detail.meta.risk_summary?.medium ?? 0} / 低{' '}
                    {detail.meta.risk_summary?.low ?? 0}
                  </span>
                </div>
              </div>

              <div className="report-toolbar">
                <Segmented
                  size="small"
                  value={viewMode}
                  onChange={(v) => setViewMode(v as 'markdown' | 'structured')}
                  options={[
                    { label: 'Markdown', value: 'markdown' },
                    { label: '结构化数据', value: 'structured' },
                  ]}
                />
                <span className="report-toolbar__label">导出范围</span>
                <Checkbox
                  checked={selectedSections.length === (detail.sections?.length ?? 0)}
                  indeterminate={
                    selectedSections.length > 0 &&
                    selectedSections.length < (detail.sections?.length ?? 0)
                  }
                  onChange={(e) =>
                    setSelectedSections(
                      e.target.checked ? (detail.sections ?? []).map((s) => s.key) : [],
                    )
                  }
                >
                  全选
                </Checkbox>
                <div className="report-toolbar__sections">
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
                <div className="report-toolbar__export">
                  <Tooltip title="下载 Markdown 全文">
                    <Button
                      size="small"
                      icon={<FileMarkdownOutlined />}
                      onClick={() => window.open(reportMarkdownUrl(detail.meta.report_id), '_blank')}
                    >
                      MD
                    </Button>
                  </Tooltip>
                  <Tooltip title="下载结构化数据（JSON，可直接作为大模型输入）">
                    <Button size="small" icon={<FileZipOutlined />} onClick={downloadJson}>
                      JSON
                    </Button>
                  </Tooltip>
                  <Tooltip title="按勾选章节导出为自包含 HTML（图表内联）">
                    <Button
                      size="small"
                      icon={<FileTextOutlined />}
                      onClick={() => exportHtml(false)}
                    >
                      导出 HTML
                    </Button>
                  </Tooltip>
                  <Tooltip title="打开打印视图，选择「另存为 PDF」">
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<PrinterOutlined />}
                      onClick={() => exportHtml(true)}
                    >
                      导出 PDF
                    </Button>
                  </Tooltip>
                  <Tooltip title="复制结构化数据到剪贴板">
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={async () => {
                        await navigator.clipboard.writeText(
                          JSON.stringify(detail.structured, null, 2),
                        );
                        message.success('结构化数据已复制');
                      }}
                    >
                      复制 JSON
                    </Button>
                  </Tooltip>
                </div>
              </div>

              {viewMode === 'markdown' ? (
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
                        {s.key === 'science' && interactiveStructures}
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
              ) : (
                <pre className="report-structured">
                  {JSON.stringify(detail.structured, null, 2)}
                </pre>
              )}
            </div>
          )}
        </Card>
      </div>
    </PageTransition>
  );
}
