import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AnimatedCollapse from '../components/common/AnimatedCollapse';
import {
  App,
  Button,
  Dropdown,
  message as antdMessage,
  Card,
  Empty,
  Input,
  Popconfirm,
  Popover,
  Select,
  Skeleton,
  Switch,
  Tag,
} from 'antd';
import {
  DownOutlined,
  DownloadOutlined,
  ExportOutlined,
  FileTextOutlined,
  PrinterOutlined,
  RightOutlined,
} from '@ant-design/icons';
import {
  deleteProjectReport,
  fetchProjectReport,
  fetchProjectReports,
  reportChartUrl,
  reportImageUrl,
  reportHtmlUrl,
  saveReportEdits,
} from '../api/reports';
import { fetchProjects, updateProject } from '../api/projects';
import { createPortal } from 'react-dom';
import EnergyForceCharts, { type EnergyForcePoint } from '../components/common/EnergyForceCharts';

import { getToken } from '../api/client';
import PageHeader from '../components/common/PageHeader';
import ReportNoteDialog from '../components/reports/ReportNoteDialog';
import ReportCompositionEditor from '../components/reports/ReportCompositionEditor';
import ScientificPropertiesPanel from '../components/reports/ScientificPropertiesPanel';
import ImageLightbox from '../components/reports/ImageLightbox';
import ReportNotePanel from '../components/reports/ReportNotePanel';
import { ReportAIProvider, ReportAIControls } from '../components/reports/ReportAIContext';
import { ReportReviewProvider, ReportReviewControls } from '../components/reports/ReportReview';
import { ReportGenerateButton, ReportWorkControls, ReportWorkProvider } from '../components/reports/ReportWorkContext';
import { applyHiddenBlocks, collectHiddenBlocks, hiddenKeyLabel } from '../utils/reportHidden';
import {
  BaderChargePanel,
  PdosReportChart,
  WorkFunctionReportChart,
  type BaderAtom,
  type WorkFunctionSummary,
} from '../components/reports/ReportScienceWidgets';
import ReportStructure3D from '../components/reports/ReportStructure3D';
import ReportFreeEnergy3D from '../components/reports/ReportFreeEnergy3D';
import ReportNeb3D from '../components/reports/ReportNeb3D';
import {
  FreeEnergyReportPanel,
  NebReportPanel,
  ProjectProgressPanel,
  type ReportFreeEnergyPath,
  type ReportNebItem,
  type ReportProgressSegment,
} from '../components/reports/ReportPanels';
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

/** 报告注解面板的挂载点（2026-10-13）：**只在「重点科学结果分析」章节内**用 portal 渲染 */
interface NoteTarget {
  element: HTMLElement;
  /** 注解 key：`type_opt` / `task_id` / `path:<group_id>` */
  noteKey: string;
  title: string;
  hint?: string;
  /** 只读汇总用的 note_blocks 标签（自由能路径 = 组名） */
  summaryLabel?: string;
}

/**
 * 注解的「类型级」落点（用户 2026-10-13 口径）：科学结果分析章节里 markdown `### 标题` → 注解 key。
 * 四个类型各一条"总的"；电子结构目前是占位区块（子任务未完成），只有类型级没有子项级。
 * 与后端 `report_builder.NOTE_TYPE_KEYS` 保持一致。
 */
const NOTE_TYPE_KEYS: Record<string, string> = {
  结构优化: 'type_opt',
  自由能路径: 'type_free_energy',
  'NEB 过渡态': 'type_neb',
  电子结构: 'type_ele',
};

/**
 * 标题纯文本：**排除运行时追加的「隐藏」按钮**（按钮挂在标题元素内部，
 * 直接读 textContent 会带上"隐藏"两个字，导致第二轮起认不出标题、注解面板丢失）。
 */
function headingLabel(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.report-hide-btn,.report-review-anchor').forEach((btn) => btn.remove());
  return (clone.textContent ?? '').trim();
}

/**
 * 把紧随挂点之后的**图片行**标成"仅打印"（v0.9.72）：
 * 结构 3D 视图挂在正文里之后，紧跟的就是原来那 2 行 a/b/c 三视图 PNG ——
 * 屏幕上看 3D，打印 / PDF 才显示这些 PNG（`.report-static-fallback` 的打印反向规则）。
 * 只吃 `.report-img-row` / `<figure>` 这两种相邻块，遇到标题/分隔线/别的挂点就停。
 */
function markFollowingImagesPrintOnly(anchor: HTMLElement): void {
  let node: Element | null = anchor.nextElementSibling;
  while (node) {
    const isImages =
      node.classList.contains('report-img-row') ||
      node.tagName === 'FIGURE' ||
      node.classList.contains('img-row');
    if (!isImages) break;
    node.classList.add('report-static-fallback');
    node = node.nextElementSibling;
  }
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
  const [compositionOpen, setCompositionOpen] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  /** 报告注解（结果分析 / 论文参考）：key = type_* / task_id / path:<组>（2026-10-13） */
  const [notes, setNotes] = useState<Record<string, ReportNote>>({});
  /** 注解面板挂载点（只在「重点科学结果分析」章节内），用 portal 渲染 */
  const [noteTargets, setNoteTargets] = useState<Record<string, NoteTarget>>({});
  /** 隐藏的章节 / 元素（持久化到 reports/edits/<id>.json） */
  const [hidden, setHidden] = useState<string[]>([]);
  /** 表格里「注」按钮打开的编辑弹窗 */
  const [tableNote, setTableNote] = useState<{ key: string; title: string } | null>(null);
  /** 图片查看器：点报告里任意一张结构图/图表 → 看原图（可缩放，桌面+手机） */
  const [imageViewer, setImageViewer] = useState<{ src: string; caption: string } | null>(null);
  /** 「选择项目」下拉里的"已关闭项目"是否展开（默认折叠，2026-10-13） */
  const [closedInSelectOpen, setClosedInSelectOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [showClosedReports, setShowClosedReports] = useState(false);
  const [reportAIConnection, setReportAIConnection] = useState('');
  /** 项目级 AI 批注处理开关。 */
  const [aiNotesSaving, setAINotesSaving] = useState(false);

  const currentProject = projects.find((p) => p.id === selectedProject) ?? null;
  const aiNotesEnabled = currentProject?.ai_report_notes_enabled === true;

  const toggleAINotes = async (enabled: boolean) => {
    if (!selectedProject) return;
    setAINotesSaving(true);
    try {
      const res = await updateProject(selectedProject, { ai_report_notes_enabled: enabled });
      setProjects((old) => old.map((p) => (p.id === selectedProject ? res.project : p)));
      message.success(enabled ? '已开启 AI 批注处理' : '已关闭 AI 批注处理（已有内容保留）');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setAINotesSaving(false);
    }
  };

  const loadReports = useCallback(async () => {
    const list = await fetchProjectReports();
    setReports(list);
    return list;
  }, []);

  useEffect(() => {
    Promise.all([fetchProjects(), loadReports()])
      .then(([ps, list]) => {
        setProjects(ps);
        // 默认选中**未关闭项目**的第一份报告，已关闭项目默认折叠、不主动抢焦点
        const closedNames = new Set(ps.filter((p) => p.closed).map((p) => p.name));
        const preferred = list.find((r) => !closedNames.has(r.project_name)) ?? list[0];
        setSelectedProject(preferred?.project_id ?? ps[0]?.id ?? null);
        setSelectedReportId((prev) => prev ?? preferred?.report_id ?? null);
      })
      .finally(() => setLoading(false));
  }, [loadReports]);

  useEffect(() => {
    if (reports.some(r => r.report_id === selectedReportId && r.project_id === selectedProject)) return;
    setSelectedReportId(reports.find(r => r.project_id === selectedProject)?.report_id ?? null);
  }, [reports, selectedProject, selectedReportId]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedReportId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    setDetail(null);
    fetchProjectReport(selectedReportId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (!cancelled) message.error(err instanceof Error ? err.message : '读取报告失败');
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedReportId, message]);

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
    // 导出范围 = 当前**未隐藏**的章节（隐藏的章节在导出/打印里直接不出现，v0.9.71）
    const url = reportHtmlUrl(detail.meta.report_id, undefined, print, hidden, true);
    window.open(url, '_blank', 'noopener');
    if (print) message.info('已打开打印视图，选择「另存为 PDF」即可导出');
  };

  /**
   * 下载单文件 HTML（v0.9.65，用户："导出没有下载按钮"）：走 `?download=1`，
   * 服务端给 `Content-Disposition: attachment` → 浏览器直接存文件（文件名由服务端定：
   * `项目名_项目报告_日期.html`）。用隐藏 `<a>` 点击而不是 `window.open`，避免留下空白标签页；
   * **不用 blob 下载**：几十 MB 的报告全读进内存不划算，让浏览器自己流式落盘。
   */
  const downloadHtml = () => {
    if (!detail) return;
    const url = reportHtmlUrl(detail.meta.report_id, undefined, false, hidden, true, true);
    const link = document.createElement('a');
    link.href = url;
    link.rel = 'noopener';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
    message.success('已开始下载单文件 HTML（不含隐藏章节）');
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

  /**
   * 「选择项目」下拉的选项：未关闭项目正常列出，**已关闭项目折成一块**（默认收起，
   * 与左侧报告列表 / 总览 / 巡检中心同一个口径，2026-10-13 用户要求）。
   * 当前选中的项目即使已关闭也要留在 options 里 —— 否则 Select 会拿 value（项目 ID）当标签显示。
   */
  const selectOptions = useMemo(
    () =>
      projects
        .filter((p) => !p.closed || p.id === selectedProject)
        .map((p) => ({ value: p.id, label: p.name })),
    [projects, selectedProject],
  );
  const selectClosedProjects = useMemo(
    () => projects.filter((p) => p.closed),
    [projects],
  );

  // 选中的报告属于已关闭项目时，自动展开折叠区，避免"选中了却看不见"
  const selectedIsClosed = useMemo(() => {
    if (!selectedReportId) return false;
    const report = reports.find((r) => r.report_id === selectedReportId);
    return !!report && closedProjectNames.has(report.project_name);
  }, [selectedReportId, reports, closedProjectNames]);
  useEffect(() => {
    if (selectedIsClosed) setShowClosedReports(true);
  }, [selectedIsClosed]);

  /** 页面显示所有章节；要"去掉某一章"用标题行的「隐藏本章」（隐藏状态导出/打印同样生效） */
  const visibleSections = useMemo(() => detail?.markdown_sections ?? [], [detail]);

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

  /** 注解落点（用户 2026-10-13 口径，只在「重点科学结果分析」章节内）：
   *  - 类型级一条总的：结构优化 / 自由能路径 / NEB 过渡态（电子结构暂不提供）；
   *  - 子项级：结构优化的每个任务、NEB 的每个组 = `task_id`；自由能路径的每个组 = `path:<group_id>`。
   *  值里的 `label` 是 markdown 里 `#### 标题`（页面上是 <h6>），用来找挂载点。
   */
  const notePlan = useMemo(() => {
    const science =
      (detail?.structured as { science?: Record<string, any> } | undefined)?.science ?? {};
    const items: Record<string, { key: string; title: string; hint: string; summaryLabel?: string }> = {};
    const opt = (science.opt ?? []) as { task_id?: string; task_name?: string }[];
    const neb = (science.neb ?? []) as { task_id?: string; task_name?: string }[];
    const paths = (science.free_energy ?? []) as { group_id?: string; group_name?: string }[];
    for (const item of [...opt, ...neb]) {
      if (!item?.task_name || !item?.task_id) continue;
      items[String(item.task_name)] = {
        key: String(item.task_id),
        title: `${item.task_name} · 结果分析与论文参考`,
        hint: '这一条只跟本任务绑定',
      };
    }
    for (const path of paths) {
      if (!path?.group_name) continue;
      items[String(path.group_name)] = {
        key: `path:${path.group_id ?? path.group_name}`,
        title: `${path.group_name} · 结果分析与论文参考`,
        hint: '自由能路径按组一条（组内各结构可在下表里单独点「注」）',
        summaryLabel: String(path.group_name),
      };
    }
    return items;
  }, [detail]);

  const noteBlocks = detail?.note_blocks ?? {};

  /** 章节标题（「已隐藏」列表里把 key 显示成人话用） */
  const sectionTitles = useMemo(
    () => Object.fromEntries((detail?.sections ?? []).map((s) => [s.key, s.title])),
    [detail],
  );

  /**
   * 能量/力收敛曲线：**用 ECharts 组件替换报告里那张 SVG 图**（v0.9.60 迁移）。
   *
   * 后端仍会生成 `<task_id>_energy_force.svg`（导出单文件 HTML 时用它当静态图），
   * 但页面上更希望是**可交互的组件**（悬停十字线 + 两图联动）——与巡检详情同一套配置
   * （`components/common/EnergyForceCharts.tsx`）。做法与注解面板一致：渲染后按
   * `<task_id>_energy_force.svg` 找到那张图，就地换成 host div，再用 portal 挂组件。
   */
  const [efHosts, setEfHosts] = useState<
    { key: string; taskId: string; el: HTMLElement; dialogId: string | null }[]
  >([]);

  const renderedSections = useMemo(
    () =>
      visibleSections.map((section) => ({
        ...section,
        html: renderMarkdown(section.markdown, {
          widgetRenderer: (kind, id) => kind === 'review-element' ? detail?.review_elements_html?.[id] : undefined,
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

  /** 把报告里那张能量/力 SVG 图换成 ECharts 组件（渲染后按文件名找图，就地替换 + portal 挂载） */
  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const hosts: { key: string; taskId: string; el: HTMLElement; dialogId: string | null }[] = [];
    root.querySelectorAll('img').forEach((img) => {
      const src = img.getAttribute('src') || '';
      const matched = /([^/\\]+)_energy_force\.svg/.exec(src);
      if (!matched) return;
      const taskId = matched[1];
      const host = document.createElement('div');
      host.className = 'report-ef-chart';
      host.setAttribute('data-ef-task', taskId);
      // 收敛历史弹窗里那张图（2026-10-15）：记下所属 dialog，**弹窗打开时才挂 ECharts**
      // —— 关闭的 <dialog> 是 display:none，容器尺寸为 0，直接 init 会画不出来
      const dialogEl = img.closest('dialog');
      const figure = img.closest('figure');
      if (figure) figure.replaceWith(host);
      else img.replaceWith(host);
      hosts.push({ key: taskId, taskId, el: host, dialogId: dialogEl?.id ?? null });
    });
    setEfHosts(hosts);
    // Portal 子节点由 React 卸载；不要在 effect 清理中删除宿主或清空其内容。
    // 切换报告后旧宿主随 Markdown 脱离文档，React 仍需完成其子树的卸载。
  }, [renderedSections, detail]);

  /** 哪些弹窗是打开的（`toggle` 事件）：弹窗里的图表只在打开时挂载（见上） */
  const [openDialogs, setOpenDialogs] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const dialogs = Array.from(root.querySelectorAll('dialog'));
    const onToggle = (event: Event) => {
      const el = event.currentTarget as HTMLDialogElement;
      setOpenDialogs((prev) =>
        prev[el.id] === el.open ? prev : { ...prev, [el.id]: el.open },
      );
    };
    dialogs.forEach((dialog) => dialog.addEventListener('toggle', onToggle));
    return () => dialogs.forEach((dialog) => dialog.removeEventListener('toggle', onToggle));
  }, [renderedSections, detail]);

  /**
   * 电子结构挂点（2026-10-15，v0.9.61）：后端 Markdown 里的 `@[kind:task_id]` 渲染成
   * `<div data-report-widget="...">`，这里就地 portal 挂交互组件 ——
   * Bader 折叠表 / PDOS 交互图（点击加载）/ 功函数曲线。
   * 与导出的单文件 HTML 同源：那边的 `widget_renderer` 出的是同一套宿主 div。
   */
  const [widgetHosts, setWidgetHosts] = useState<
    { kind: string; taskId: string; el: HTMLElement; figure: HTMLElement | null }[]
  >([]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const hosts: {
      kind: string;
      taskId: string;
      el: HTMLElement;
      figure: HTMLElement | null;
    }[] = [];
    root.querySelectorAll<HTMLElement>('[data-report-widget]').forEach((el) => {
      const kind = el.getAttribute('data-report-widget') || '';
      const taskId = el.getAttribute('data-task-id') || '';
      if (!kind || !taskId) return;
      const prev = el.previousElementSibling;
      const figure = prev && prev.tagName === 'FIGURE' ? (prev as HTMLElement) : null;
      // 功函数曲线挂上就是交互版（曲线数值内联在报告里），静态图直接收起来
      // （用 class 而不是纯 inline 隐藏：打印/PDF 时 CSS 会把它重新显示出来，见 global.css）
      if (kind === 'work-function-chart' && figure) {
        figure.classList.add('report-static-fallback');
      }
      // PDOS：屏幕上一律显示交互图，**静态兜底图只在打印/PDF 里出现**
      //（否则会"先闪一张静态图，滚到了才换成交互图" —— 用户 2026-10-15 反馈）
      if (kind === 'pdos-chart' && figure) figure.classList.add('report-static-fallback');
      // 结构 3D（2026-10-16）：3D 视图后面那几行三视图 PNG 是**仅打印**的（屏幕上看 3D）
      if (kind === 'structure-3d') markFollowingImagesPrintOnly(el);
      hosts.push({ kind, taskId, el, figure });
    });
    setWidgetHosts(hosts);
    // 不可 replaceChildren()：这些子节点属于 React Portal，必须由 React 清理。
  }, [renderedSections, detail]);

  /**
   * 自由能台阶图 / NEB 能垒曲线（v0.9.62）：报告里那两张后端看板 SVG
   * （`<group_id>_step.svg` / `<task_id>_barrier.svg`）就地换成 ECharts 看板 ——
   * 做法与能量/力曲线一致：渲染后按文件名找到 `<img>`，换成 host div 再 portal 挂组件。
   * 图注（figcaption）保留，图的版式与读数对齐原静态图。
   */
  const [panelHosts, setPanelHosts] = useState<
    { kind: 'fe' | 'neb' | 'progress'; key: string; el: HTMLElement }[]
  >([]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const hosts: {
      kind: 'fe' | 'neb' | 'progress';
      key: string;
      el: HTMLElement;
    }[] = [];
    root.querySelectorAll('img').forEach((img) => {
      const src = img.getAttribute('src') || '';
      // 项目进度条（`charts/progress.svg`）：换成 DOM 版进度看板
      if (/(^|\/)progress\.svg$/.test(src)) {
        const host = document.createElement('div');
        host.className = 'report-panel-host';
        host.setAttribute('data-panel', 'progress');
        img.replaceWith(host);
        hosts.push({ kind: 'progress', key: 'progress', el: host });
        return;
      }
      const fe = /([^/\\]+)_step\.svg/.exec(src);
      const neb = /([^/\\]+)_barrier\.svg/.exec(src);
      const matched = fe ?? neb;
      if (!matched) return;
      if (neb) {
        const item = (detail?.structured as { science?: { neb?: ReportNebItem[] } })?.science?.neb
          ?.find(item => String(item.task_id ?? '') === neb[1]);
        const has3DHost = Array.from(root.querySelectorAll<HTMLElement>('[data-report-widget="neb-3d"]'))
          .some(el => el.dataset.taskId === neb[1]);
        if (has3DHost && item?.images?.some(image => image.cif)) {
          img.closest('figure')?.classList.add('report-static-fallback');
          return;
        }
      }
      const host = document.createElement('div');
      host.className = 'report-panel-host';
      host.setAttribute('data-panel', fe ? 'free-energy' : 'neb');
      host.setAttribute('data-panel-key', matched[1]);
      // 只替换图片本身：figcaption（图注）留在原处，版式观感与原来一致
      img.replaceWith(host);
      hosts.push({ kind: fe ? 'fe' : 'neb', key: matched[1], el: host });
    });
    setPanelHosts(hosts);
  }, [renderedSections, detail]);

  /** 打开报告里某个结构三视图弹窗（与点击 `.report-chip[data-dialog]` 同一行为） */
  const openReportDialog = useCallback((dialogId: string) => {
    const dialog = document.getElementById(dialogId);
    if (dialog instanceof HTMLDialogElement && !dialog.open) dialog.showModal();
  }, []);

  /** 报告里的自由能路径 / NEB 任务（结构化数据，按 group_id / task_id 索引） */
  const freeEnergyPaths = useMemo<ReportFreeEnergyPath[]>(() => {
    const structured = detail?.structured as
      | { science?: { free_energy?: ReportFreeEnergyPath[] } }
      | undefined;
    return structured?.science?.free_energy ?? [];
  }, [detail]);
  const nebItems = useMemo<ReportNebItem[]>(() => {
    const structured = detail?.structured as
      | { science?: { neb?: ReportNebItem[] } }
      | undefined;
    return structured?.science?.neb ?? [];
  }, [detail]);

  /**
   * 自由能中间体 3D 视图的「切到第 N 个中间体」回调（v0.9.73）：
   * 组件挂载时把 setter 注册进来，表格里的「结构 N」芯片点击时从这里取。
   */
  const feSelectRef = useRef<Map<string, (index: number) => void>>(new Map());
  const registerFeSelect = useCallback(
    (group: string) => (select: (index: number) => void) => {
      feSelectRef.current.set(group, select);
      return () => {
        feSelectRef.current.delete(group);
      };
    },
    [],
  );

  /** 报告里的电子结构结果（PDOS / Bader / 功函数）：结构化数据里取，按 task_id 索引 */
  const eleTasks = useMemo(() => {
    const structured = detail?.structured as
      | {
          science?: {
            ele?: {
              tasks?: {
                task_id?: string;
                task_name?: string;
                bader_summary?: { atoms?: BaderAtom[] };
                work_function_summary?: WorkFunctionSummary;
              }[];
            };
          };
        }
      | undefined;
    return structured?.science?.ele?.tasks ?? [];
  }, [detail]);

  /** 渲染后给注解找挂载点：**只在「重点科学结果分析」章节内**
   *  - 类型标题（### → <h5>）：挂载点插在标题正下方（该类型"总的"一条）；
   *  - 子项标题（#### → <h6>）：挂载点插在该子块末尾（每个任务/组一条）。
   */
  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    const targets: Record<string, NoteTarget> = {};
    const section = root.querySelector('section[data-report-section="science"]');
    const body = section?.querySelector('.report-markdown') as HTMLElement | null;
    if (body) {
      const children = Array.from(body.children) as HTMLElement[];
      /** 找/建挂载点：按 data-note-anchor 幂等（effect 每次渲染都会跑一遍） */
      const ensureAnchor = (anchorKey: string, index: number, mode: 'after' | 'end') => {
        let anchor = body.querySelector(
          `[data-note-anchor="${anchorKey.replace(/"/g, '')}"]`,
        ) as HTMLElement | null;
        if (anchor) return anchor;
        anchor = document.createElement('div');
        anchor.className = 'report-note-anchor';
        anchor.setAttribute('data-note-anchor', anchorKey);
        if (mode === 'after') {
          children[index].after(anchor);
          return anchor;
        }
        // 块结束 = 下一个同级标题 / HR 之前；到章节末尾就追加在最后
        let cursor = index + 1;
        let endEl: Element | null = null;
        while (cursor < children.length) {
          const tag = children[cursor].tagName;
          if (tag === 'H5' || tag === 'H6' || tag === 'HR' || tag === 'H2') {
            endEl = children[cursor];
            break;
          }
          cursor += 1;
        }
        if (endEl) endEl.before(anchor);
        else body.append(anchor);
        return anchor;
      };

      // 类型级（总的）：结构优化 / 自由能路径 / NEB 过渡态 / 电子结构（后者无子项级）
      children.forEach((el, index) => {
        if (el.tagName !== 'H5') return;
        const label = headingLabel(el);
        const key = NOTE_TYPE_KEYS[label];
        if (!key) return;
        const anchorKey = `science:type:${key}`;
        targets[anchorKey] = {
          element: ensureAnchor(anchorKey, index, 'after'),
          noteKey: key,
          title: `${label} · 结果分析与论文参考`,
          hint: '这一条是该类型"总的"分析',
        };
      });

      // 子项级：结构优化每个任务 / NEB 每个组 / 自由能路径每个组
      children.forEach((el, index) => {
        if (el.tagName !== 'H6') return;
        const label = headingLabel(el);
        const plan = notePlan[label];
        if (!plan) return;
        const anchorKey = `science:item:${plan.key}`;
        targets[anchorKey] = {
          element: ensureAnchor(anchorKey, index, 'end'),
          noteKey: plan.key,
          title: plan.title,
          hint: plan.hint,
          summaryLabel: plan.summaryLabel,
        };
      });
    }
    // 元素级隐藏（v0.9.69 扩展）：章节 / 类型 / **单个任务** / **电子结构整任务** / 单图
    // 粒度与 key 的完整说明见 utils/reportHidden.ts
    root.querySelectorAll('section[data-report-section]').forEach((section: Element) => {
      const sectionKey = section.getAttribute('data-report-section') ?? '';
      section.classList.toggle('report-hidden', hidden.includes(`section:${sectionKey}`));
    });
    const hiddenBlocks = collectHiddenBlocks(root);
    applyHiddenBlocks(hiddenBlocks, hidden);
    hiddenBlocks.forEach((block) => {
      if (block.anchor.querySelector(`.report-hide-btn[data-hide-key="${block.key}"]`)) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `report-hide-btn report-hide-btn--${block.kind}`;
      btn.dataset.hideKey = block.key;
      btn.textContent = block.buttonText ?? '隐藏';
      btn.title = block.buttonTitle ?? '隐藏（可在右上角「已隐藏」里恢复）';
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleHidden(block.key, true);
      });
      if (block.kind === 'figure') block.anchor.prepend(btn);
      else block.anchor.append(btn);
    });

    // 自由能表格里的「结构 N」行：在可点 chip 旁加一个「注」按钮（编辑该中间体的注解）。
    // v0.9.73 起自由能中间体的芯片改成"切换 3D 视图"（`data-note-task` 带任务 id），
    // 老的三视图弹窗芯片（`data-dialog="dlg_..."`）也一并支持。
    root
      .querySelectorAll(
        'section[data-report-section] .report-markdown button.chip[data-note-task],' +
          ' section[data-report-section] .report-markdown button.chip[data-dialog]',
      )
      .forEach((chip: Element) => {
        const label = (chip.textContent ?? '').trim();
        if (!label.startsWith('结构 ')) return; // 只处理自由能表格（NEB 用映像块面板）
        const dialogId = chip.getAttribute('data-dialog') ?? '';
        const taskId =
          chip.getAttribute('data-note-task') ||
          (dialogId.startsWith('dlg_') ? dialogId.slice(4) : '');
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
      });
    setNoteTargets(targets);
  }, [renderedSections, notes, hidden, toggleHidden, notePlan]);


  /** 点「结构 N / 映像 N」→ 打开原生 <dialog> 三视图弹窗；点报告里的图片 → 打开原图查看器。 */
  const handleReportViewerClick = useCallback((event: React.MouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    // 图片：正文里的结构图/图表，以及三视图弹窗里的图，都点开「原图」（可缩放）
    const img = target.closest('img') as HTMLImageElement | null;
    if (img && target.closest('.report-markdown, dialog.report-viewer')) {
      event.preventDefault();
      const figure = img.closest('figure');
      const caption =
        figure?.querySelector('figcaption')?.textContent?.trim() || img.alt || '结构图';
      setImageViewer({
        // currentSrc 在浏览器按 srcset 选图时更准；一般两者一致
        src: img.currentSrc || img.src,
        caption,
      });
      return;
    }
    // 自由能中间体：点「结构 N」→ 切换上面那个 3D 视图（v0.9.73，不再开三视图弹窗）
    const feChip = target.closest('[data-fe-3d]') as HTMLElement | null;
    if (feChip) {
      const group = feChip.dataset.fe3d ?? '';
      const index = Number(feChip.dataset.feIndex ?? '0');
      const select = feSelectRef.current.get(group);
      if (select) {
        select(Number.isFinite(index) ? index : 0);
        feChip
          .closest('table')
          ?.querySelectorAll('.report-chip.is-on')
          .forEach((el) => el.classList.remove('is-on'));
        feChip.classList.add('is-on');
        return;
      }
    }
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
    // 遮罩点击：图片查看器也支持点外部关闭
    const imageDialog = target.closest('dialog.report-image-viewer');
    if (imageDialog instanceof HTMLDialogElement && target === imageDialog) {
      setImageViewer(null);
    }
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
            onClick={() => { setSelectedReportId(item.report_id); setSelectedProject(item.project_id); }}
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
              <span>{item.weighted_progress_percent != null
                ? `项目进度 ${item.weighted_progress_percent}%`
                : `未归档任务完成率 ${item.completion_percent ?? '—'}%`}</span>
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

  const selection = useRef({ project: selectedProject, report: selectedReportId });
  selection.current = { project: selectedProject, report: selectedReportId };
  const reloadBackgroundReport = useCallback(async () => {
    const before = selection.current;
    const list = await loadReports();
    if (before.project !== selection.current.project) return;
    const reportId = before.report ?? list.find(r => r.project_id === before.project)?.report_id;
    if (!reportId) return;
    const updated = await fetchProjectReport(reportId);
    if (before.project !== selection.current.project || before.report !== selection.current.report) return;
    setSelectedReportId(reportId); setDetail(updated);
  }, [loadReports]);

  return (
    <ReportWorkProvider projectId={selectedProject ?? ''} connectionId={reportAIConnection} onConnectionChange={setReportAIConnection} onChanged={reloadBackgroundReport}>
    <ReportAIProvider
      reportId={detail?.meta.report_id ?? ''} notes={notes} onSaved={setNotes}
      enabled={aiNotesEnabled}
      connectionId={reportAIConnection} onConnectionChange={setReportAIConnection}>
    <ReportReviewProvider
      reportId={detail?.meta.report_id ?? ''} contentRef={contentRef} version={renderedSections}
      connectionId={reportAIConnection} onConnectionChange={setReportAIConnection}>
    <PageTransition>
      {propertiesOpen && selectedProject && <ScientificPropertiesPanel key={selectedProject} projectRef={selectedProject} projects={projects} onClose={() => setPropertiesOpen(false)}/>}
      {compositionOpen && selectedProject && <ReportCompositionEditor key={selectedProject} projectRef={selectedProject}
        projectName={projects.find(p => p.id === selectedProject)?.name || selectedProject} legacyHidden={detail?.meta.project_id === selectedProject ? hidden : []} onClose={() => setCompositionOpen(false)}/>}
      <PageHeader
        title="智能报告"
        subtitle="以项目为单位生成结构化报告：结构化数据（可喂大模型）+ Markdown + 图表，支持按章节导出 HTML / PDF"
        extra={
          <div className="report-actions">
            <label
              className="report-ai-toggle"
              title="AI仅处理你提交的批注；生成报告不会自动撰写其他模块。关闭保留已有内容。"
            >
              <span>AI 批注处理</span>
              <Switch
                size="small"
                checked={aiNotesEnabled}
                loading={aiNotesSaving}
                disabled={!selectedProject}
                onChange={(checked) => void toggleAINotes(checked)}
                aria-label="AI 批注处理"
              />
            </label>
            <Button disabled={!selectedProject} onClick={() => setPropertiesOpen(true)}>科学性质</Button>
            <Button disabled={!selectedProject} onClick={() => setCompositionOpen(true)}>专题报告</Button>
            <Select
              value={selectedProject}
              onChange={setSelectedProject}
              style={{ width: 190 }}
              options={selectOptions}
              placeholder="选择项目"
              onOpenChange={(open) => {
                if (!open) setClosedInSelectOpen(false); // 收起下拉时把"已关闭项目"也折回去
              }}
              popupRender={(menu) => (
                <>
                  {menu}
                  {selectClosedProjects.length > 0 && (
                    <div
                      className="report-select-closed"
                      // 别让点击落到 Select 上（否则下拉会立刻关闭/抢焦点）
                      onMouseDown={(e) => e.preventDefault()}
                    >
                      <button
                        type="button"
                        className="report-select-closed__toggle"
                        onClick={() => setClosedInSelectOpen((v) => !v)}
                      >
                        {closedInSelectOpen ? <DownOutlined /> : <RightOutlined />}
                        已关闭项目（{selectClosedProjects.length}）
                      </button>
                      {closedInSelectOpen && (
                        <div className="report-select-closed__list">
                          {selectClosedProjects.map((p) => (
                            <button
                              type="button"
                              key={p.id}
                              className={`report-select-closed__item${
                                p.id === selectedProject ? ' is-selected' : ''
                              }`}
                              onClick={() => {
                                setSelectedProject(p.id);
                                setClosedInSelectOpen(false);
                              }}
                            >
                              {p.name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            />
            <ReportGenerateButton projectId={selectedProject} />
            <ReportGenerateButton all />
            <ReportWorkControls />
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
                    aria-expanded={showClosedReports}
                    onClick={() => setShowClosedReports((v) => !v)}
                  >
                    <RightOutlined className={`collapse-chevron${showClosedReports ? ' collapse-chevron--open' : ''}`} />
                    已关闭项目（{closedGroups.length}）
                  </button>
                  <AnimatedCollapse open={showClosedReports}>
                    <div className="project-closed-list">
                      {closedGroups.map((group) => renderReportGroup(group, true))}
                    </div>
                  </AnimatedCollapse>
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
                              {hiddenKeyLabel(key, sectionTitles)}
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
                    <p className="report-export-pop__hint">
                      导出范围 = 当前**未隐藏**的章节；要整章去掉就在章节标题行点「隐藏本章」
                      （HTML 里图表都是可交互版，静态图留作打印 / PDF 兜底）
                    </p>
                    <div className="report-export-pop__actions">
                      <Button
                        size="small"
                        type="primary"
                        icon={<DownloadOutlined />}
                        onClick={downloadHtml}
                      >
                        下载 HTML
                      </Button>
                      <Button
                        size="small"
                        icon={<FileTextOutlined />}
                        onClick={() => exportHtml(false)}
                      >
                        预览 HTML
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
                    （未归档任务完成率 {detail.meta.completion_percent ?? '—'}%）
                  </span>
                  <span>
                    风险 高 {detail.meta.risk_summary?.high ?? 0} / 中{' '}
                    {detail.meta.risk_summary?.medium ?? 0} / 低{' '}
                    {detail.meta.risk_summary?.low ?? 0}
                  </span>
                  <span className="preview-note">点任意结构图 / 图表可看原图（可缩放）</span>
                </div>
              </div>

              <ReportAIControls />
              <ReportReviewControls />
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
                      </section>
                    ))}
                    {/* 能量/力收敛曲线：ECharts 组件（替代报告里那张 SVG 图，v0.9.60） */}
                    {efHosts.map((host) => {
                      if (!contentRef.current?.contains(host.el)) return null;
                      // 弹窗里的图：等弹窗打开再挂（关闭时容器 0 尺寸，ECharts 画不出来）
                      if (host.dialogId && !openDialogs[host.dialogId]) return null;
                      const item = (
                        ((detail?.structured as { science?: { opt?: unknown[] } } | undefined)
                          ?.science?.opt ?? []) as {
                          task_id?: string;
                          task_name?: string;
                          energy_force_series?: EnergyForcePoint[];
                        }[]
                      ).find((x) => String(x?.task_id ?? '') === host.taskId);
                      const points = item?.energy_force_series ?? [];
                      if (!points.length) return null;
                      return createPortal(
                        <EnergyForceCharts points={points} height={260} />,
                        host.el,
                        host.key,
                      );
                    })}

                    {/* 自由能台阶图 / NEB 能垒曲线（v0.9.62）：换成就地挂载的 ECharts 看板 */}
                    {panelHosts.map((host) => {
                      if (!contentRef.current?.contains(host.el)) return null;
                      if (host.kind === 'progress') {
                        const basic = (detail?.structured as
                          | {
                              basic_info?: {
                                progress_segments?: ReportProgressSegment[];
                                weighted_progress_percent?: number;
                                /** 与本文件顶部的 `ReportWorkload` 同一份字段 */
                                workload?: ReportWorkload;
                              };
                            }
                          | undefined)?.basic_info;
                        if (!basic?.progress_segments?.length) return null;
                        const stats = (detail?.structured as
                          | { executive_summary?: { task_stats?: Record<string, number> } }
                          | undefined)?.executive_summary?.task_stats;
                        return createPortal(
                          <ProjectProgressPanel
                            segments={basic.progress_segments}
                            mainPercent={basic.weighted_progress_percent}
                            taskStats={
                              stats
                                ? {
                                    completed: stats.completed,
                                    total: stats.total,
                                    archived: stats.archived,
                                  }
                                : undefined
                            }
                            workload={basic.workload}
                          />,
                          host.el,
                          'progress',
                        );
                      }
                      if (host.kind === 'fe') {
                        const path = freeEnergyPaths.find(
                          (p) =>
                            String(p.group_id ?? '') === host.key ||
                            String(p.group_name ?? '') === host.key,
                        );
                        if (!path?.structures?.length) return null;
                        return createPortal(
                          <FreeEnergyReportPanel path={path} onOpenDialog={openReportDialog} />,
                          host.el,
                          `fe:${host.key}`,
                        );
                      }
                      const item = nebItems.find(
                        (n) => String(n.task_id ?? '') === host.key,
                      );
                      if (!item?.images?.length) return null;
                      return createPortal(
                        <NebReportPanel item={item} onOpenDialog={openReportDialog} />,
                        host.el,
                        `neb:${host.key}`,
                      );
                    })}

                    {/* 电子结构挂点（v0.9.61）：Bader 折叠表 / PDOS 交互图 / 功函数曲线 */}
                    {widgetHosts.map((host) => {
                      if (!contentRef.current?.contains(host.el)) return null;
                      if (host.kind === 'neb-3d') {
                        const neb = nebItems.find(item => String(item.task_id ?? '') === host.taskId);
                        return neb?.images?.some(image => image.cif) ? createPortal(
                          <ReportNeb3D item={neb} />, host.el, `neb-3d:${host.taskId}`,
                        ) : null;
                      }
                      const item = eleTasks.find(
                        (x) => String(x?.task_id ?? '') === host.taskId,
                      );
                      if (host.kind === 'bader-table') {
                        const atoms = item?.bader_summary?.atoms ?? [];
                        if (!atoms.length) return null;
                        return createPortal(
                          <BaderChargePanel
                            atoms={atoms}
                            cif={(item?.bader_summary as { cif?: string } | undefined)?.cif}
                            taskName={item?.task_name}
                          />,
                          host.el,
                          `${host.kind}:${host.taskId}`,
                        );
                      }
                      if (host.kind === 'structure-3d') {
                        const opt = (
                          ((detail?.structured as { science?: { opt?: unknown[] } } | undefined)
                            ?.science?.opt ?? []) as {
                            task_id?: string;
                            task_name?: string;
                            structure?: { poscar_cif?: string | null; contcar_cif?: string | null };
                          }[]
                        ).find((x) => String(x?.task_id ?? '') === host.taskId);
                        const structure = opt?.structure;
                        if (!structure?.poscar_cif && !structure?.contcar_cif) return null;
                        return createPortal(
                          <ReportStructure3D
                            poscarCif={structure.poscar_cif}
                            contcarCif={structure.contcar_cif}
                            taskName={opt?.task_name}
                          />,
                          host.el,
                          `structure-3d:${host.taskId}`,
                        );
                      }
                      if (host.kind === 'free-energy-3d') {
                        const path = freeEnergyPaths.find(
                          (p) =>
                            String(p.group_id ?? '') === host.taskId ||
                            String(p.group_name ?? '') === host.taskId,
                        );
                        if (!path?.structures?.length) return null;
                        return createPortal(
                          <ReportFreeEnergy3D
                            groupName={path.group_name}
                            structures={path.structures}
                            register={registerFeSelect(String(path.group_id ?? host.taskId))}
                          />,
                          host.el,
                          `free-energy-3d:${host.taskId}`,
                        );
                      }
                      if (host.kind === 'work-function-chart') {
                        const summary = item?.work_function_summary;
                        if (!summary?.z?.length) return null;
                        return createPortal(
                          <WorkFunctionReportChart summary={summary} taskName={item?.task_name} />,
                          host.el,
                          `${host.kind}:${host.taskId}`,
                        );
                      }
                      if (host.kind === 'pdos-chart') {
                        return createPortal(
                          <PdosReportChart
                            taskId={host.taskId}
                            taskName={item?.task_name}
                          />,
                          host.el,
                          `${host.kind}:${host.taskId}`,
                        );
                      }
                      return null;
                    })}

                    {/* 注解面板（结果分析 / 论文参考）：只在「重点科学结果分析」章节内的挂载点上 */}
                    {Object.entries(noteTargets).map(([anchorKey, target]) => {
                      if (!contentRef.current?.contains(target.element)) return null;
                      const note = notes[target.noteKey] ?? { analysis_note: '', paper_note: '' };
                      const readOnly = target.summaryLabel
                        ? (noteBlocks[target.summaryLabel] ?? []).filter(
                            (e) => e.label && (e.analysis_note || e.paper_note),
                          )
                        : [];
                      return createPortal(
                        <ReportNotePanel
                          reportId={detail?.meta.report_id ?? ''}
                          noteKey={target.noteKey}
                          title={target.title}
                          hint={target.hint}
                          analysis={note.analysis_note}
                          paper={note.paper_note}
                          readOnly={readOnly}
                          onSaved={setNotes}
                        />,
                        target.element,
                        anchorKey,
                      );
                    })}
                    {/* 表格里「注」按钮打开的注解编辑弹窗 */}
                    <ImageLightbox
                      open={imageViewer !== null}
                      src={imageViewer?.src ?? ''}
                      caption={imageViewer?.caption}
                      onClose={() => setImageViewer(null)}
                    />

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
                          {/* 图表弹窗（收敛历史，v0.9.67）：正文页里这张 SVG 会被换成可交互 ECharts */}
                          {dialog.chart ? (
                            <>
                              {dialog.note ? <p className="row-label">{dialog.note}</p> : null}
                              <figure className="report-figure">
                                <img
                                  src={reportChartUrl(detail.meta.report_id, dialog.chart)}
                                  alt={dialog.title}
                                  decoding="async"
                                />
                              </figure>
                            </>
                          ) : null}
                          {(dialog.rows ?? []).map((row) => (
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
    </ReportReviewProvider>
    </ReportAIProvider>
    </ReportWorkProvider>
  );
}
