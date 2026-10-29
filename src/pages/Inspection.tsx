import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import AnimatedCollapse from '../components/common/AnimatedCollapse';
import InspectionProjectTable from '../components/inspection/InspectionProjectTable';
import { useAuth } from '../context/AuthContext';
import { useSearchParams } from 'react-router-dom';
import {
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Skeleton,
  Spin,
  Switch,
  Tag,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { FilterDropdownProps } from 'antd/es/table/interface';
import type { Key } from 'react';
import {
  InboxOutlined,
  ClearOutlined,
  FileSearchOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  RightOutlined,
  SyncOutlined,
  UndoOutlined,
} from '@ant-design/icons';
import {
  fetchInspectionDetail,
  fetchInspectionMeta,
  fetchInspectionResults,
  runInspection,
  runSingleInspection,
  updateAutoInspection,
} from '../api/inspections';
import type { InspectionMeta } from '../api/inspections';
import { archiveTask, calculateCorrection, unarchiveTask } from '../api/jobs';
import CheckErrorsPanel from '../components/inspection/CheckErrorsPanel';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import OutcarTailDialog from '../components/inspection/OutcarTailDialog';
import StatusTag from '../components/common/StatusTag';

const ForceHistoryCharts = lazy(() => import('../components/inspection/ForceHistoryCharts'));
const EleAnalysisPanel = lazy(() => import('../components/inspection/EleAnalysisPanel'));
const PathSummaryModal = lazy(() => import('../components/inspection/PathSummaryModal'));
const StructurePanel = lazy(() => import('../components/inspection/StructurePanel'));
const NebImageMasterDetail = lazy(() => import('../components/inspection/NebImageMasterDetail'));

/**
 * 详情分区（可折叠）：`defaultOpen` 的分区**直接渲染**，其余仍「点一下再加载」。
 *
 * 口径（2026-10-14 用户反馈）：懒加载只在**真贵**的时候才值 —— 要连远端探测
 * （电子结构分析的 available-analyses）、要拉大 JSON（PDOS 图表）才值得挡一下；
 * 数据本来就在详情载荷里、只是画两张曲线或一张小表的（能量与力、差分电荷分块表），
 * 默认展开，省掉每次看详情都多一次点击。切换任务时靠 `key` 重置。
 */
function LazySection({
  title,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string;
  hint?: string;
  /**
   * 默认展开（2026-10-14）：**数据已经随详情载荷一起返回**、渲染开销又小的分区
   * （能量/力曲线、差分电荷分块状态表）不必再让用户点一下 —— 实测这一步省不下什么，
   * 反而每次看详情都多一次点击。真正贵的（远端探测 / 大图 / 大 JSON）仍然按需。
   */
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="inspection-detail__section">
      <h3>
        {title}
        <button
          type="button"
          className="inspection-lazy-btn"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '收起' : '点击加载'}
        </button>
      </h3>
      {open ? (
        children
      ) : (
        <p className="preview-note">
          {hint ?? '内容按需加载：点右侧「点击加载」再取数据/画图，避免拖慢详情打开速度。'}
        </p>
      )}
    </div>
  );
}
import type {
  CheckStatus,
  InspectionDetail,
  InspectionResult,
  TaskStatus,
} from '../types';
import { TASK_STATUS_LABELS } from '../types';
import { formatTime } from '../utils/format';

const READ_CHANGES_KEY = 'vasp.inspection.read-changes.v1';
const FILTERS_KEY = 'vasp.inspection.filters.v1';

const TASK_CATEGORY_META: Record<string, { color: string; bg: string }> = {
  '结构优化': { color: '#2C6FBB', bg: '#EAF1FF' },
  '自由能': { color: '#2C9DA8', bg: '#E4F6F8' },
  NEB: { color: '#7B61D6', bg: '#F0EDFC' },
  '电子结构': { color: '#D18A2B', bg: '#FEF3E0' },
};

/** 巡检列表状态优先级（数字越小越靠前）：错误 > 警告 > 待提交（未检）> 正常 > 关闭 */
const CHECK_STATUS_RANK: Record<string, number> = {
  error: 0,
  warning: 1,
  pending: 2,
  normal: 3,
  archived: 4,
};

const TASK_CATEGORY_ORDER: Record<string, number> = {
  '结构优化': 0,
  '自由能': 1,
  NEB: 2,
  '电子结构': 3,
};

const STATUS_FILTER_OPTIONS = [
  { text: '正常', value: 'normal' },
  { text: '警告', value: 'warning' },
  { text: '错误', value: 'error' },
  { text: '待提交', value: 'pending' },
  { text: '关闭', value: 'archived' },
];

const TASK_CATEGORY_FILTER_OPTIONS = [
  { text: '结构优化', value: '结构优化' },
  { text: '自由能', value: '自由能' },
  { text: 'NEB', value: 'NEB' },
  { text: '电子结构', value: '电子结构' },
];

function renderColumnFilter(
  options: { text: string; value: string }[],
  onChange: (v: string[] | null) => void,
) {
  return (props: FilterDropdownProps) => {
    const { setSelectedKeys, selectedKeys, confirm, close } = props;
    const checked = (selectedKeys as string[]) || [];
    return (
      <div style={{ padding: 8, minWidth: 170 }}>
        <Checkbox.Group
          value={checked}
          options={options.map((o) => ({ label: o.text, value: o.value }))}
          style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
          onChange={(vals) => setSelectedKeys(vals as Key[])}
        />
        <div
          style={{
            marginTop: 10,
            display: 'flex',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <Button
            size="small"
            onClick={() => {
              setSelectedKeys([]);
              onChange(null);
              confirm();
              close?.();
            }}
          >
            重置
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={() => {
              onChange(checked.length ? checked : null);
              confirm();
              close?.();
            }}
          >
            确定
          </Button>
        </div>
      </div>
    );
  };
}

function parseFilter(searchParams: URLSearchParams, key: string): string[] | null {
  const v = searchParams.get(key);
  return v ? v.split(',').filter(Boolean) : null;
}

function loadSavedFilters(): {
  q: string;
  projects: string[] | null;
  categories: string[] | null;
  statuses: string[] | null;
} {
  try {
    const saved = JSON.parse(localStorage.getItem(FILTERS_KEY) || 'null');
    if (saved && typeof saved === 'object') {
      return {
        q: typeof saved.q === 'string' ? saved.q : '',
        projects: Array.isArray(saved.projects) ? saved.projects : null,
        categories: Array.isArray(saved.categories) ? saved.categories : null,
        statuses: Array.isArray(saved.statuses) ? saved.statuses : null,
      };
    }
  } catch {
    /* ignore */
  }
  return { q: '', projects: null, categories: null, statuses: null };
}

const OUTPUT_STATUS_LABELS: Record<string, { label: string; color: string }> = {
  finished: { label: '已完成', color: 'success' },
  running: { label: '计算中', color: 'processing' },
  failed: { label: '失败', color: 'error' },
  waiting: { label: '等待', color: 'default' },
};

// 详情页分析区块标题（按任务类型区分，后续各类型专属分析接入后填充内容）
const ANALYSIS_SECTION_TITLE: Record<string, string> = {
  opt: '结构分析',
  frac: '频率矫正分析',
  neb: 'NEB 映像分析',
  ele: '电子结构分析',
};

const QUEUE_STATUS_LABELS: Record<string, string> = {
  PEND: '排队中',
  RUN: '运行中',
  SSUSP: '挂起（SSUSP）',
  PSUSP: '挂起（PSUSP）',
  USUSP: '挂起（USUSP）',
  DONE: '已结束',
  EXIT: '已结束（异常）',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
  NOT_FOUND: '作业不存在',
  UNKNOWN: '未知',
};

export default function Inspection() {
  const { isAdmin } = useAuth();
  const { message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const savedFilters = useMemo(loadSavedFilters, []);
  const [results, setResults] = useState<InspectionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [singleRunningIds, setSingleRunningIds] = useState<Set<string>>(new Set());
  const [keyword, setKeyword] = useState(() => searchParams.get('q') || savedFilters.q);
  const [projectFilter, setProjectFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'projects') ?? savedFilters.projects,
  );
  const [taskCategoryFilter, setTaskCategoryFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'categories') ?? savedFilters.categories,
  );
  const [statusFilter, setStatusFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'statuses') ?? savedFilters.statuses,
  );
  // 只记录手动选择；未操作时，进行中项目展开、已关闭项目收起。
  const [projectExpansion, setProjectExpansion] = useState<Map<string, boolean>>(() => new Map());
  const [autoSaving, setAutoSaving] = useState(false);
  const [outcarTail, setOutcarTail] = useState<{ taskId: string; title: string } | null>(null);
  const [detail, setDetail] = useState<InspectionResult | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState<InspectionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [meta, setMeta] = useState<InspectionMeta | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [pathSummaryOpen, setPathSummaryOpen] = useState(false);
  const [pathGroup, setPathGroup] = useState<{ id: string; name: string } | null>(null);
  // 已读的状态变化提醒（localStorage 持久化，点开详情后红点消失）
  const [readChanges, setReadChanges] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(READ_CHANGES_KEY) || '[]'));
    } catch {
      return new Set();
    }
  });

  /**
   * 详情框里**当前显示**的任务 id（竞态守卫，2026-10-15 修）。
   *
   * 用户反馈："A 任务单独巡检过程中退出详情页面然后进入 B 任务，待 A 巡检完成后 B 的详情页面会被替换为 A 的"。
   * 原因：`runSingle(row, fromDetail=true)` 巡检完无条件 `setDetailData(await fetchInspectionDetail(row.task_id))`，
   * 这一等（巡检 75–90s）期间用户完全可以切到别的任务；同理 `openDetail` 里"点 A 又马上点 B"也会串。
   * 现在所有"异步取回详情 → 写 state"的地方都先比一下这个 ref：**不是当前显示的那个任务就不写**。
   */
  const openDetailIdRef = useRef<string | null>(null);
  useEffect(() => {
    openDetailIdRef.current = detailOpen ? (detail?.task_id ?? null) : null;
  }, [detailOpen, detail]);

  const markRead = (taskId: string) => {
    setReadChanges((prev) => {
      if (prev.has(taskId)) return prev;
      const next = new Set(prev).add(taskId);
      try {
        localStorage.setItem(READ_CHANGES_KEY, JSON.stringify([...next]));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const handleCalculateCorrection = async () => {
    if (!detailData?.frac) return;
    const ownerId = detailData.task_id;
    setCorrecting(true);
    try {
      // 联动：frac 本地尚无已完成记录时先单独巡检，再计算矫正项
      if (detailData.frac.status !== 'completed') {
        await runSingleInspection(detailData.frac.task_id);
      }
      await calculateCorrection(detailData.frac.task_id);
      message.success('矫正项计算完成');
      const data = await fetchInspectionDetail(ownerId);
      if (openDetailIdRef.current === ownerId) setDetailData(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '计算矫正项失败');
    } finally {
      setCorrecting(false);
    }
  };

  const openDetailById = (taskId: string) => {
    const row = results.find((r) => r.task_id === taskId);
    if (row) void openDetail(row);
  };

  const openPathSummary = (row: InspectionResult) => {
    if (!row.group_id) return;
    setPathGroup({ id: row.group_id, name: row.group_name || row.group_id });
    setPathSummaryOpen(true);
  };

  const unreadCount = useMemo(
    () =>
      results.filter((r) => r.status_changed && !readChanges.has(r.task_id)).length,
    [results, readChanges],
  );

  const clearAllRead = () => {
    // 「一键清除」= 把当前所有状态变化标记为已读（与点开详情同一机制）。
    // 早前这里是 setReadChanges(new Set()) + 删除 localStorage，
    // 等于把已读记录清空，红点会全部重新出现（刷新后依旧）。
    const next = new Set(
      results.filter((r) => r.status_changed).map((r) => r.task_id),
    );
    setReadChanges(next);
    try {
      localStorage.setItem(READ_CHANGES_KEY, JSON.stringify([...next]));
    } catch {
      /* ignore */
    }
    message.success('已清除全部状态更新提醒');
  };

  useEffect(() => {
    let cancelled = false;
    void fetchInspectionResults().then(rows => { if (!cancelled) setResults(rows); })
      .catch(e => { if (!cancelled) void message.error(e instanceof Error ? e.message : '巡检结果加载失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    void fetchInspectionMeta().then(value => { if (!cancelled) setMeta(value); })
      .catch(e => { if (!cancelled) void message.error(e instanceof Error ? e.message : '巡检配置加载失败'); });
    return () => { cancelled = true; };
  }, []);

  // 筛选变化时重置折叠状态（关闭项目仍保持默认折叠）
  useEffect(() => {
    setProjectExpansion(new Map());
  }, [keyword, projectFilter, taskCategoryFilter, statusFilter]);

  // 筛选同步到 URL：切换页面 / 刷新后自动恢复
  useEffect(() => {
    try {
      localStorage.setItem(
        FILTERS_KEY,
        JSON.stringify({
          q: keyword.trim(),
          projects: projectFilter ?? [],
          categories: taskCategoryFilter ?? [],
          statuses: statusFilter ?? [],
        }),
      );
    } catch {
      /* ignore */
    }
    const next = new URLSearchParams();
    const kw = keyword.trim();
    if (kw) next.set('q', kw);
    if (projectFilter?.length) next.set('projects', projectFilter.join(','));
    if (taskCategoryFilter?.length) next.set('categories', taskCategoryFilter.join(','));
    if (statusFilter?.length) next.set('statuses', statusFilter.join(','));
    setSearchParams(next, { replace: true });
  }, [keyword, projectFilter, taskCategoryFilter, statusFilter, setSearchParams]);

  const projectFilterOptions = useMemo(() => {
    const names = [...new Set(results.map((r) => r.project_name))].sort((a, b) =>
      a.localeCompare(b, 'zh-CN'),
    );
    return names.map((n) => ({ text: n, value: n }));
  }, [results]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    // 路径分组行：自由能组与 NEB 组（按组名跨行合并路径列）
    const isGrouped = (r: InspectionResult) =>
      r.task_category === '自由能' ||
      (r.task_category === 'NEB' && Boolean(r.group_name));
    // 组键：项目 + 完整组名（自然排序，PATH1 < PATH2 < PATH10；同名组必然相邻）
    const groupKey = (r: InspectionResult) => `${r.project_name}|${r.group_name || ''}`;
    const natCmp = (x: string, y: string) => x.localeCompare(y, 'zh-CN', { numeric: true });
    // 组内排序：自由能按结构号（1..N），NEB 按 IS -> FS -> neb
    const structOrder = (r: InspectionResult) => {
      const label = r.structure_label || '';
      if (label === 'IS') return 0;
      if (label === 'FS') return 1;
      if (label === 'neb') return 2;
      const n = parseInt(label, 10);
      return Number.isFinite(n) ? n : 9;
    };
    const kept = results.filter((r) => {
        if (projectFilter && projectFilter.length && !projectFilter.includes(r.project_name))
          return false;
        if (
          taskCategoryFilter &&
          taskCategoryFilter.length &&
          !taskCategoryFilter.includes(r.task_category || '结构优化')
        )
          return false;
        if (statusFilter && statusFilter.length && !statusFilter.includes(r.status)) return false;
        if (
          kw &&
          !`${r.project_name} ${r.task_name} ${r.message}`.toLowerCase().includes(kw)
        ) {
          return false;
        }
        return true;
      });

    // 排序单元：自由能 / NEB 的同一组算一个整体，其余任务各自成单元。
    // 注意必须带上 task_category：同一项目下自由能组与 NEB 组可能同名（如都有 PATH1）
    const unitKey = (r: InspectionResult) =>
      isGrouped(r)
        ? `${r.project_name}|${r.task_category || ''}|${r.group_name || ''}`
        : `task|${r.task_id}`;
    // 状态优先级：错误 > 警告 > 待提交（未检）> 正常 > 关闭
    const unitRank = new Map<string, number>();
    const unitMembers = new Map<string, InspectionResult[]>();
    kept.forEach((r) => {
      const key = unitKey(r);
      unitMembers.set(key, [...(unitMembers.get(key) ?? []), r]);
    });
    unitMembers.forEach((list, key) => {
      const active = list.filter((r) => r.status !== 'archived');
      const pool = active.length ? active : list; // 整组归档才算"已关闭"
      unitRank.set(
        key,
        Math.min(...pool.map((r) => CHECK_STATUS_RANK[r.status] ?? 9)),
      );
    });

    return kept.sort((a, b) => {
        // ① 整组归档的单元沉到其他任务下面（"归档任务放在其他任务下面"）
        const ua = unitRank.get(unitKey(a)) ?? 9;
        const ub = unitRank.get(unitKey(b)) ?? 9;
        const closedA = ua === CHECK_STATUS_RANK.archived ? 1 : 0;
        const closedB = ub === CHECK_STATUS_RANK.archived ? 1 : 0;
        if (closedA !== closedB) return closedA - closedB;
        // ② 组/任务按状态优先级参与排序（组取组内最高优先级）
        if (ua !== ub) return ua - ub;
        // ③ 以下保持原有排序逻辑不变：类别 → 组名自然序（同组必然相邻）
        const ca = TASK_CATEGORY_ORDER[a.task_category || '结构优化'] ?? 9;
        const cb = TASK_CATEGORY_ORDER[b.task_category || '结构优化'] ?? 9;
        if (ca !== cb) return ca - cb;
        if (isGrouped(a) && isGrouped(b)) {
          const g = natCmp(groupKey(a), groupKey(b));
          if (g !== 0) return g;
        }
        // ④ 组内被归档的成员沉到该组末尾（不影响组之间的相邻关系）
        const archA = a.status === 'archived' ? 1 : 0;
        const archB = b.status === 'archived' ? 1 : 0;
        if (archA !== archB) return archA - archB;
        // ⑤ 组内结构顺序（自由能 1..N；NEB IS→FS→neb）→ 任务名
        if (isGrouped(a) && isGrouped(b)) {
          const s = structOrder(a) - structOrder(b);
          if (s !== 0) return s;
        }
        return `${a.project_name} ${a.task_name}`.localeCompare(
          `${b.project_name} ${b.task_name}`,
          'zh-CN',
        );
      });
  }, [results, keyword, projectFilter, taskCategoryFilter, statusFilter]);

  /** 按项目分块：项目内保持既有排序（类别 → 组 → 组内顺序），关闭项目排最后 */
  const projectBlocks = useMemo(() => {
    const byProject = new Map<string, InspectionResult[]>();
    filtered.forEach((row) => {
      const list = byProject.get(row.project_name) ?? [];
      list.push(row);
      byProject.set(row.project_name, list);
    });
    const blocks = [...byProject.entries()].map(([projectName, rows]) => ({
      projectName,
      closed: Boolean(rows[0]?.project_closed),
      rows,
      errors: rows.filter((r) => r.status === 'error').length,
      warnings: rows.filter((r) => r.status === 'warning').length,
      archived: rows.filter((r) => r.status === 'archived').length,
      // 已关闭任务不计入"未检"
      uninspected: rows.filter((r) => !r.has_inspection && r.status !== 'archived').length,
      changed: rows.filter((r) => r.status_changed).length,
    }));
    blocks.sort((a, b) => {
      if (a.closed !== b.closed) return a.closed ? 1 : -1;
      return a.projectName.localeCompare(b.projectName, 'zh-CN');
    });
    return blocks;
  }, [filtered]);

  /** 开关自动巡检（写入 settings.json，调度线程下一轮生效） */
  const handleToggleAuto = async (enabled: boolean) => {
    setAutoSaving(true);
    try {
      await updateAutoInspection({ enabled });
      setMeta(await fetchInspectionMeta());
      message.success(
        enabled
          ? `自动巡检已开启：距上次巡检超过 ${meta?.interval_hours ?? 2} 小时自动执行`
          : '自动巡检已停用',
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存自动巡检设置失败');
    } finally {
      setAutoSaving(false);
    }
  };

  /** 关闭（归档）当前详情里的任务；未正常结束时前端弹窗提醒（后端不做硬限制） */
  const handleArchiveDetailTask = async () => {
    if (!detail) return;
    try {
      const r = await archiveTask(detail.task_id);
      const siblingNote = r.archived_siblings?.length
        ? `，并一并归档频率矫正 ${r.archived_siblings
            .map((s) => s.model_name)
            .join('、')}`
        : '';
      message.success(
        r.was_completed
          ? `任务 ${detail.task_name} 已关闭（归档）${siblingNote}`
          : `任务 ${detail.task_name} 已关闭（归档，原状态 ${r.previous_status}）${siblingNote}`,
      );
      openDetailIdRef.current = null;
      setDetailOpen(false);
      setResults(await fetchInspectionResults());
    } catch (err) {
      message.error(err instanceof Error ? err.message : '关闭任务失败');
    }
  };

  /** 重新打开已归档任务（恢复到归档前状态） */
  const handleUnarchiveDetailTask = async () => {
    if (!detail) return;
    try {
      const r = await unarchiveTask(detail.task_id);
      const siblingNote = r.reopened_siblings?.length
        ? `，频率矫正 ${r.reopened_siblings.map((s) => s.model_name).join('、')} 也已恢复`
        : '';
      message.success(
        `任务 ${detail.task_name} 已重新打开（${r.new_status}）${siblingNote}`,
      );
      const reopenedId = detail.task_id;
      const data = await fetchInspectionDetail(reopenedId);
      if (openDetailIdRef.current === reopenedId) setDetailData(data);
      setResults(await fetchInspectionResults());
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重新打开任务失败');
    }
  };

  const handleTrigger = async () => {
    setTriggering(true);
    try {
      const summary = await runInspection();
      const [rows, m] = await Promise.all([
        fetchInspectionResults(),
        fetchInspectionMeta(),
      ]);
      setResults(rows);
      setMeta(m);
      message.success(
        `巡检完成：检查 ${summary.inspected} 项，更新 ${summary.updated} 项` +
          (summary.warnings ? `，警告 ${summary.warnings} 项` : ''),
      );
      if (summary.rejected.length > 0) {
        message.warning(
          `${summary.rejected.length} 项状态更新被拒绝：${summary.rejected[0].message}`,
        );
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '巡检失败');
    } finally {
      setTriggering(false);
    }
  };

  const runSingle = async (row: InspectionResult, fromDetail = false) => {
    setSingleRunningIds((prev) => new Set(prev).add(row.task_id));
    try {
      const summary = await runSingleInspection(row.task_id);
      message.success(
        `巡检完成：检查 ${summary.inspected} 项，更新 ${summary.updated} 项` +
          (summary.warnings ? `，警告 ${summary.warnings} 项` : ''),
      );
      if (summary.rejected.length > 0) {
        message.warning(
          `${summary.rejected.length} 项状态更新被拒绝：${summary.rejected[0].message}`,
        );
      }
      // 刷新列表（该任务 has_inspection 变为 true，按钮切换为“详情”）
      const rows = await fetchInspectionResults();
      setResults(rows);
      // 只有"详情框里现在还是这个任务"才回填详情 —— 巡检要 75–90s，
      // 期间用户可能已经退出详情或切到别的任务（2026-10-15 用户反馈的覆盖 bug）
      if (fromDetail && openDetailIdRef.current === row.task_id) {
        const data = await fetchInspectionDetail(row.task_id);
        if (openDetailIdRef.current === row.task_id) setDetailData(data);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '单任务巡检失败');
    } finally {
      setSingleRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(row.task_id);
        return next;
      });
    }
  };

  const openDetail = async (row: InspectionResult) => {
    if (row.status === 'pending') {
      message.info('该任务暂无巡检记录，请先用「单独巡检」获取当前状态');
      return;
    }
    markRead(row.task_id);
    setDetail(row);
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailData(null);
    // 立即标记"详情框现在属于哪个任务"（不等 effect），并防止"点 A 又马上点 B"时 A 的慢响应回填
    openDetailIdRef.current = row.task_id;
    try {
      const data = await fetchInspectionDetail(row.task_id);
      if (openDetailIdRef.current === row.task_id) setDetailData(data);
    } catch (err) {
      if (openDetailIdRef.current === row.task_id) {
        message.error(err instanceof Error ? err.message : '读取巡检详情失败');
      }
    } finally {
      if (openDetailIdRef.current === row.task_id) setDetailLoading(false);
    }
  };

  const isGroupedRow = (row: InspectionResult) =>
    row.task_category === '自由能' ||
    (row.task_category === 'NEB' && Boolean(row.group_name));

  /** 每个项目块单独生成列定义：组内跨行合并需要按块内的行序计算 */
  const buildColumns = (
    spanMap: Record<string, number>,
  ): ColumnsType<InspectionResult> => [
    {
      title: '检查时间',
      dataIndex: 'check_time',
      key: 'check_time',
      width: 150,
      render: (value: string) => {
        const [date, ...time] = (value || '—').replace('T', ' ').split(' ');
        return <span className="inspection-check-time" title={value}><span>{date}</span><small>{time.join(' ')}</small></span>;
      },
    },
    {
      title: '项目',
      dataIndex: 'project_name',
      key: 'project_name',
      width: 150,
      ellipsis: true,
      filterDropdown: renderColumnFilter(
        projectFilterOptions,
        setProjectFilter,
      ),
      filteredValue: projectFilter ?? null,
      onFilter: () => true,
    },
    {
      title: '',
      key: 'task_group',
      width: 130,
      ellipsis: true,
      onCell: (row) =>
        isGroupedRow(row)
          ? { rowSpan: spanMap[row.task_id] ?? 1 }
          : { colSpan: 2 },
      render: (_, row) =>
        isGroupedRow(row) ? (
          row.task_category === '自由能' && row.group_id ? (
            <div style={{ textAlign: 'center' }}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => openPathSummary(row)}
              >
                {row.group_name || '—'}
              </Button>
            </div>
          ) : (
            <div style={{ textAlign: 'center' }}>
              <span className="path-cell">{row.group_name || '—'}</span>
            </div>
          )
        ) : (
          <Tooltip title={row.task_name}>
            <span>{row.task_name}</span>
          </Tooltip>
        ),
    },
    {
      title: '任务',
      dataIndex: 'task_name',
      key: 'task_name',
      width: 190,
      ellipsis: true,
      onCell: (row) => (isGroupedRow(row) ? {} : { colSpan: 0 }),
      render: (v: string, row) =>
        isGroupedRow(row) ? (
          <Tooltip title={v}>
            <span>{v}</span>
          </Tooltip>
        ) : null,
    },
    {
      title: '任务类别',
      dataIndex: 'task_category',
      key: 'task_category',
      width: 100,
      filterDropdown: renderColumnFilter(
        TASK_CATEGORY_FILTER_OPTIONS,
        setTaskCategoryFilter,
      ),
      filteredValue: taskCategoryFilter ?? null,
      onFilter: () => true,
      render: (v?: string) => {
        const key = v || '结构优化';
        const meta = TASK_CATEGORY_META[key] ?? TASK_CATEGORY_META['结构优化'];
        return (
          <span className="category-tag" style={{ color: meta.color, background: meta.bg }}>
            {key}
          </span>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      filterDropdown: renderColumnFilter(STATUS_FILTER_OPTIONS, setStatusFilter),
      filteredValue: statusFilter ?? null,
      onFilter: () => true,
      render: (s: CheckStatus) => <StatusTag status={s} kind="check" />,
    },
    {
      title: '信息',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
      render: (v: string, row: InspectionResult) => {
        // 异常结束（错误/警告）时，点错误信息弹出 OUTCAR 最后数行（2026-10-13 用户要求）
        const clickable = row.status === 'error' || row.status === 'warning';
        return (
          <Tooltip title={clickable ? `${v}（点击查看 OUTCAR 末尾）` : v}>
            <span
              className={clickable ? 'inspection-msg inspection-msg--clickable' : undefined}
              onClick={
                clickable
                  ? (event) => {
                      event.stopPropagation();
                      setOutcarTail({
                        taskId: row.task_id,
                        title: `${row.task_name ?? row.task_id} · OUTCAR 最后数行`,
                      });
                    }
                  : undefined
              }
            >
              {v}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_, row) =>
        row.has_inspection ? (
          <Badge
            dot={Boolean(row.status_changed) && !readChanges.has(row.task_id)}
            offset={[-6, 6]}
          >
            <Button
              size="small"
              type="link"
              icon={<InfoCircleOutlined />}
              onClick={() => openDetail(row)}
            >
              详情
            </Button>
          </Badge>
        ) : (
          <Tooltip
            title={
              row.task_status === 'archived'
                ? '任务已关闭（归档），请先在作业管理里「重新打开」再巡检'
                : undefined
            }
          >
            <Button
              size="small"
              type="link"
              icon={<ReloadOutlined />}
              loading={singleRunningIds.has(row.task_id)}
              disabled={triggering || row.task_status === 'archived'}
              onClick={() => runSingle(row)}
            >
              单独巡检
            </Button>
          </Tooltip>
        ),
    },
  ];

  return (
    <PageTransition>
      <PageHeader
        title="巡检中心"
        subtitle="每 2 小时自动检查子项目运行状态，异常项按条件筛选呈现"
        extra={
          <div className="header-actions">
            <div className="auto-chip">
              <SyncOutlined spin={Boolean(meta?.scheduler?.running)} />
              {meta?.scheduler?.running
                ? '巡检进行中'
                : meta?.enabled === false
                  ? '自动巡检已停用'
                  : '自动巡检已启用'}
              <span>
                每 {meta?.interval_hours ?? 2} 小时
                {meta?.last_run_at
                  ? ` · 上次自动 ${formatTime(new Date(meta.last_run_at))}`
                  : ' · 尚未自动巡检'}
                {meta?.next_run_at ? ` · 下次 ${meta.next_run_at}` : ''}
                {meta?.scheduler?.last_any_run_at &&
                meta.scheduler.last_any_run_at !== meta.scheduler.last_run_at
                  ? ` · 最近一次（含手动）${formatTime(new Date(meta.scheduler.last_any_run_at))}`
                  : ''}
              </span>
              {isAdmin ? (
                <Tooltip
                  title={
                    meta?.scheduler?.last_error
                      ? `上次自动巡检失败：${meta.scheduler.last_error}`
                      : '按「上次自动巡检」计时：手动点「立即巡检」不影响下次自动执行的时间'
                  }
                >
                  <Switch
                    size="small"
                    checked={meta?.enabled !== false}
                    loading={autoSaving}
                    onChange={handleToggleAuto}
                  />
                </Tooltip>
              ) : (
                // 普通用户只读状态，开关是 admin 专属入口（后端 403 兜底）
                <Tooltip title="自动巡检开关由管理员维护">
                  <span className="preview-note">仅管理员可修改</span>
                </Tooltip>
              )}
            </div>
            {isAdmin && (
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                loading={triggering}
                onClick={handleTrigger}
              >
                立即巡检
              </Button>
            )}
            <Button
              icon={<ClearOutlined />}
              disabled={unreadCount === 0}
              onClick={clearAllRead}
            >
              一键清除
            </Button>
          </div>
        }
      />

      <Card>
        <div className="filter-bar" style={{ marginBottom: 16 }}>
          <div style={{ flex: 1 }} />
          <Input
            allowClear
            prefix={<FileSearchOutlined style={{ color: 'var(--color-text-muted)' }} />}
            placeholder="搜索项目 / 任务 / 信息"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 280 }}
          />
        </div>

        <div className={`inspection-projects${loading ? '' : ' content-enter'}`}>
          {projectBlocks.map((block) => {
            const expanded = projectExpansion.get(block.projectName) ?? !block.closed;
            return (
              <div
                key={block.projectName}
                className={`inspection-project${block.closed ? ' inspection-project--closed' : ''}`}
              >
                <button
                  type="button"
                  className="inspection-project__head"
                  aria-expanded={expanded}
                  aria-label={`${expanded ? '收起' : '展开'}项目 ${block.projectName}`}
                  onClick={() =>
                    setProjectExpansion((prev) => {
                      const next = new Map(prev);
                      next.set(block.projectName, !(prev.get(block.projectName) ?? !block.closed));
                      return next;
                    })
                  }
                >
                  <RightOutlined className={`collapse-chevron${expanded ? ' collapse-chevron--open' : ''}`} />
                  <span className="inspection-project__name">{block.projectName}</span>
                  {block.closed && (
                    <span className="inspection-project__closed">已关闭</span>
                  )}
                  <span className="inspection-project__meta">
                    共 {block.rows.length} 项
                    {block.errors > 0 && (
                      <span className="inspection-project__stat inspection-project__stat--error">
                        错误 {block.errors}
                      </span>
                    )}
                    {block.warnings > 0 && (
                      <span className="inspection-project__stat inspection-project__stat--warning">
                        警告 {block.warnings}
                      </span>
                    )}
                    {block.uninspected > 0 && (
                      <span className="inspection-project__stat">未检 {block.uninspected}</span>
                    )}
                    {block.archived > 0 && (
                      <span className="inspection-project__stat">关闭 {block.archived}</span>
                    )}
                    {block.changed > 0 && (
                      <span className="inspection-project__stat inspection-project__stat--changed">
                        状态变化 {block.changed}
                      </span>
                    )}
                  </span>
                </button>
                <AnimatedCollapse open={expanded}>
                  <InspectionProjectTable
                    rows={block.rows} closed={block.closed} loading={loading}
                    buildColumns={buildColumns}
                  />
                </AnimatedCollapse>
              </div>
            );
          })}
          {projectBlocks.length === 0 && (
            <Empty description="没有符合条件的巡检结果" />
          )}
        </div>
      </Card>

      <Modal
        title={detail ? `${detail.task_name} · 巡检详情` : '巡检结果详情'}
        open={detailOpen}
        onCancel={() => {
          openDetailIdRef.current = null;
          setDetailOpen(false);
        }}
        footer={
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 8,
            }}
          >
            {detailData?.status === 'archived' ? (
              <Popconfirm
                title="重新打开该任务？"
                description={`任务将恢复到归档前的状态，重新参与全局巡检${
                  detailData?.frac ? '；其频率矫正任务也会一并重新打开' : ''
                }`}
                okText="重新打开"
                cancelText="取消"
                onConfirm={handleUnarchiveDetailTask}
              >
                <Button icon={<UndoOutlined />}>重新打开</Button>
              </Popconfirm>
            ) : (
              detailData && (
                <Popconfirm
                  title="关闭（归档）该任务？"
                  description={
                    <span style={{ whiteSpace: 'pre-line' }}>
                      {(() => {
                        const base =
                          detailData.status === 'completed'
                            ? '任务已正常结束，关闭后不再参与全局巡检（可随时重新打开）'
                            : `任务当前状态为「${
                                TASK_STATUS_LABELS[
                                  detailData.status as TaskStatus
                                ] ?? detailData.status
                              }」，并非正常结束；关闭后不再参与全局巡检（可随时重新打开）`;
                        const frac = detailData.frac;
                        if (!frac) return base;
                        const fracLabel =
                          TASK_STATUS_LABELS[frac.status as TaskStatus] ?? frac.status;
                        if (frac.status !== 'completed') {
                          return `⚠️ 该任务的频率矫正（${frac.task_name}）当前为「${fracLabel}」，尚未正常结束；关闭主任务会一并归档它。\n${base}`;
                        }
                        return `${base}\n将同时归档其频率矫正任务（${frac.task_name}）。`;
                      })()}
                    </span>
                  }
                  okText="关闭"
                  cancelText="取消"
                  onConfirm={handleArchiveDetailTask}
                >
                  <Button icon={<InboxOutlined />}>关闭（归档）</Button>
                </Popconfirm>
              )
            )}
            <Tooltip
              title={
                detailData?.status === 'archived'
                  ? '任务已关闭（归档），请先「重新打开」再巡检'
                  : undefined
              }
            >
              <Button
                icon={<ReloadOutlined />}
                loading={detail ? singleRunningIds.has(detail.task_id) : false}
                disabled={
                  triggering || detailLoading || detailData?.status === 'archived'
                }
                onClick={() => detail && runSingle(detail, true)}
              >
                单独巡检
              </Button>
            </Tooltip>
          </div>
        }
        width={
          detailData?.analysis?.neb_images?.length
            ? 'min(1200px, calc(100vw - 32px))'
            : 'min(1000px, calc(100vw - 32px))'
        }
        destroyOnClose
        styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' } }}
      >
        <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
        {detailLoading ? (
          <Skeleton active paragraph={{ rows: 12 }} />
        ) : detailData ? (
          <div className="inspection-detail">
            {detailData.frac && detailData.task_type === 'opt' && (
              <div className="free-energy-equation">
                <div className="fe-box">
                  <div className="fe-box__label">自由能</div>
                  <div
                    className="fe-box__value"
                    style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 4 }}
                  >
                    {detailData.last_energy != null && detailData.frac.correction != null
                      ? (detailData.last_energy + detailData.frac.correction).toFixed(4)
                      : '—'}
                    <span className="preview-note">eV</span>
                  </div>
                </div>
                <span className="fe-op">=</span>
                <div className="fe-box">
                  <div className="fe-box__label">DFT 能量</div>
                  <div
                    className="fe-box__value"
                    style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 4 }}
                  >
                    {detailData.last_energy != null ? detailData.last_energy.toFixed(4) : '—'}
                    <span className="preview-note">eV</span>
                  </div>
                </div>
                <span className="fe-op">+</span>
                <div className="fe-box">
                  <div className="fe-box__label">矫正项 (ZPE − T·S)</div>
                  <Button
                    size="small"
                    type="link"
                    loading={correcting}
                    onClick={() => void handleCalculateCorrection()}
                    title="点击重新计算矫正项"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'baseline',
                      justifyContent: 'center',
                      gap: 4,
                      padding: 0,
                      height: 'auto',
                    }}
                  >
                    {detailData.frac.correction != null ? (
                      <>
                        {detailData.frac.correction.toFixed(4)}
                        <span className="preview-note">eV</span>
                      </>
                    ) : (
                      '未矫正 · 计算'
                    )}
                  </Button>
                </div>
              </div>
            )}
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="项目">{detailData.project_name}</Descriptions.Item>
              <Descriptions.Item label="任务 ID">{detailData.task_id}</Descriptions.Item>
              <Descriptions.Item label="检查时间">
                {detailData.check_time ?? '—'}
              </Descriptions.Item>
              {detailData.current_output &&
                (() => {
                  const co = detailData.current_output;
                  const meta = OUTPUT_STATUS_LABELS[co.status];
                  return (
                    <Descriptions.Item label="最新输出">
                      {co.latest_dir ? `${co.latest_dir}/（续算目录）` : '主目录'}
                      {meta && (
                        <Tag color={meta.color} style={{ marginLeft: 8 }}>
                          {meta.label}
                        </Tag>
                      )}
                      <div className="preview-note" style={{ marginTop: 4 }}>
                        CONTCAR：{co.contcar_path}
                      </div>
                      <div className="preview-note">OSZICAR：{co.oszicar_path}</div>
                    </Descriptions.Item>
                  );
                })()}
              <Descriptions.Item label="队列状态">
                {detailData.queue_status
                  ? (QUEUE_STATUS_LABELS[detailData.queue_status] ?? detailData.queue_status)
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="任务状态">
                <StatusTag status={detailData.status as TaskStatus} />
              </Descriptions.Item>
              <Descriptions.Item label="最近能量 (eV)">
                {detailData.last_energy != null ? detailData.last_energy.toFixed(8) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="收敛判定">
                {detailData.force_converged == null ? (
                  '—'
                ) : detailData.force_converged ? (
                  <Tag color="success">已收敛</Tag>
                ) : (
                  <Tag color="error">未收敛</Tag>
                )}
                {detailData.force_max != null && (
                  <span className="preview-note" style={{ marginLeft: 8 }}>
                    最大力 {detailData.force_max} eV/Å · RMS {detailData.force_rms} eV/Å
                  </span>
                )}
                {detailData.force_thresholds && (
                  <span className="preview-note" style={{ marginLeft: 8 }}>
                    阈值 {detailData.force_thresholds.max_force_threshold} eV/Å
                    （{detailData.force_thresholds.source === 'incar:EDIFFG'
                      ? 'INCAR EDIFFG'
                      : '默认值'}
                    ）
                  </span>
                )}
              </Descriptions.Item>
              {detailData.notes && (
                <Descriptions.Item label="备注">{detailData.notes}</Descriptions.Item>
              )}
              {detailData.errors.length > 0 && (
                <Descriptions.Item label="错误信息">
                  <span
                    className="inspection-msg inspection-msg--clickable"
                    onClick={() =>
                      setOutcarTail({
                        taskId: detailData.task_id,
                        title: `${detailData.model_name ?? detailData.task_id} · OUTCAR 最后数行`,
                      })
                    }
                  >
                    {detailData.errors.join('；')}（点开看 OUTCAR 末尾）
                  </span>
                </Descriptions.Item>
              )}
            </Descriptions>

            {((detailData.check_errors?.length ?? 0) > 0 || detailData.error_text) && (
              <div className="inspection-detail__section">
                <h3>OUTCAR 报错诊断</h3>
                <CheckErrorsPanel
                  errors={detailData.check_errors ?? []}
                  errorText={detailData.error_text ?? null}
                />
              </div>
            )}

            {detailData.force_history.length > 0 && (
              <LazySection
                key={`${detailData.task_id}-force`}
                title="能量与力 · 离子步"
                defaultOpen
                hint={`收起中：${detailData.force_history.length} 个离子步的能量与最大力曲线（数据随详情一起返回，展开即可看）`}
              >
                <ForceHistoryCharts
                  history={detailData.force_history}
                  forceThreshold={detailData.force_thresholds?.max_force_threshold ?? null}
                  forceThresholdSource={detailData.force_thresholds?.source ?? null}
                />
              </LazySection>
            )}

            <div className="inspection-detail__section">
              <h3>{ANALYSIS_SECTION_TITLE[detailData.task_type] ?? '结构分析'}</h3>
              {detailData.task_type === 'ele' ? (
                // 电子结构：分析入口是**并列的一级标签页**（PDOS / Bader / COHP / 功函数），
                // 标签页本身惰性挂载，所以这里不再套 LazySection
                <EleAnalysisPanel detail={detailData} />
              ) : detailData.task_type === 'neb' ? (
                // NEB 专属分析：只走映像结构视图，**不要**落到 StructurePanel
                // （StructurePanel 期望 opt 的 files/poscar/warnings 字段，NEB 载荷没有会白屏）
                (detailData.analysis?.neb_images?.length ?? 0) > 0 ||
                (detailData.neb_barrier?.images.length ?? 0) > 0 ? (
                  <NebImageMasterDetail
                    taskId={detailData.task_id}
                    images={detailData.analysis?.neb_images ?? []}
                    barrier={detailData.neb_barrier?.images}
                    steps={detailData.analysis?.steps}
                  />
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={
                      detailData.analysis?.skipped ??
                      '尚未同步 NEB 映像结构：需要巡检推进到 25 离子步桶后自动抓取各映像 CONTCAR'
                    }
                  />
                )
              ) : detailData.analysis ? (
                <StructurePanel
                  taskId={detailData.task_id}
                  analysis={detailData.analysis}
                  taskType={detailData.task_type}
                  forceHistory={detailData.force_history}
                  forceMax={detailData.force_max}
                  forceRms={detailData.force_rms}
                  forceConverged={detailData.force_converged}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="该任务类型的专属分析尚未接入，当前仅展示基础数据"
                />
              )}
            </div>

            {detailData.diff_charge && (
              <LazySection
                key={`${detailData.task_id}-diffcharge`}
                title={`差分电荷分块 · ${detailData.diff_charge.block_count} 个分块`}
                defaultOpen
                hint={
                  `收起中：${detailData.diff_charge.block_count} 个分块的提交/收敛状态表` +
                  '（数据随详情一起返回；计算与看图在「电子结构分析 → 差分电荷」标签）'
                }
              >

                <p className="preview-note">
                  各分块在主任务目录下独立提交（<code>/1</code>、<code>/2</code> …）；
                  在「电子结构分析 → 差分电荷」标签里点击计算时，远端主目录用
                  VTST 脚本算差分（<code>chgsum.pl 1/CHGCAR 2/CHGCAR …</code> 再
                  <code>chgdiff.pl CHGCAR CHGCAR_sum</code>），只把 <code>CHGCAR_diff</code> 回传本地，
                  落 <code>diffcharge_files/chgfiles/CHGCAR_diff.vasp</code>。
                  {(() => {
                    const cd = detailData.diff_charge?.charge_diff ?? null;
                    if (!cd) return null;
                    if (!cd.ok) {
                      return `（差分计算失败：${cd.error ?? '未知原因'}）`;
                    }
                    const bytes = cd.bytes ?? 0;
                    const size =
                      bytes >= 1024 * 1024
                        ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
                        : `${bytes} B`;
                    return `（已回传 ${size}，耗时 ${cd.elapsed_seconds ?? '-'} s）`;
                  })()}
                </p>
                <Table
                  size="small"
                  rowKey="task_id"
                  pagination={false}
                  dataSource={detailData.diff_charge.blocks}
                  columns={[
                    {
                      title: '分块',
                      dataIndex: 'block_label',
                      width: 110,
                      render: (value: string, row) =>
                        value || `分块${row.block}`,
                    },
                    {
                      title: '原子数',
                      dataIndex: 'atoms_count',
                      width: 80,
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 110,
                      render: (value: string, row) =>
                        row.has_inspection ? (
                          <StatusTag status={value as TaskStatus} />
                        ) : (
                          <Tag>待提交</Tag>
                        ),
                    },
                    {
                      title: '最近能量 (eV)',
                      dataIndex: 'last_energy',
                      width: 140,
                      render: (value: number | null) =>
                        value != null ? value.toFixed(6) : '—',
                    },
                    {
                      title: '最大受力 (eV/Å)',
                      dataIndex: 'force_max',
                      width: 130,
                      render: (value: number | null) =>
                        value != null ? value.toFixed(4) : '—',
                    },
                    {
                      title: '队列',
                      dataIndex: 'queue_status',
                      width: 110,
                      render: (value: string | null) =>
                        value
                          ? QUEUE_STATUS_LABELS[value] ?? value
                          : '—',
                    },
                    {
                      title: '检查时间',
                      dataIndex: 'check_time',
                      render: (value: string | null) => value ?? '—',
                    },
                    {
                      title: '错误信息',
                      dataIndex: 'errors',
                      render: (value: string[]) =>
                        value && value.length > 0 ? (
                          <span className="inspection-msg--clickable">
                            {value.join('；')}
                          </span>
                        ) : (
                          '—'
                        ),
                    },
                  ]}
                />
                            </LazySection>
            )}

            {detailData.frac && (
              <div className="inspection-detail__section">
                <h3>频率矫正 · {detailData.frac.task_name}</h3>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="状态">
                    {detailData.frac.has_inspection ? (
                      <StatusTag status={detailData.frac.status as TaskStatus} />
                    ) : (
                      <Tag>待提交</Tag>
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="检查时间">
                    {detailData.frac.check_time ?? '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="最近能量 (eV)">
                    {detailData.frac.last_energy != null
                      ? detailData.frac.last_energy.toFixed(8)
                      : '—'}
                  </Descriptions.Item>
                  <Descriptions.Item label="队列状态">
                    {detailData.frac.queue_status
                      ? (QUEUE_STATUS_LABELS[detailData.frac.queue_status] ??
                        detailData.frac.queue_status)
                      : '—'}
                  </Descriptions.Item>
                  {detailData.frac.current_output && (
                    <Descriptions.Item label="最新输出">
                      <div className="preview-note">
                        OSZICAR：{detailData.frac.current_output.oszicar_path}
                      </div>
                      <div className="preview-note">
                        OUTCAR：{detailData.frac.current_output.outcar_path}
                      </div>
                    </Descriptions.Item>
                  )}
                  {detailData.frac.errors.length > 0 && (
                    <Descriptions.Item label="错误信息">
                      {detailData.frac.errors.join('；')}
                    </Descriptions.Item>
                  )}
                  {detailData.frac.notes && (
                    <Descriptions.Item label="备注">
                      {detailData.frac.notes}
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}
          </div>
        ) : (
          <Empty description="暂无详情数据" />
        )}
        </Suspense>
      </Modal>

      <OutcarTailDialog
        open={outcarTail !== null}
        taskId={outcarTail?.taskId ?? ''}
        title={outcarTail?.title}
        onClose={() => setOutcarTail(null)}
      />

      {pathSummaryOpen && <Suspense fallback={<Spin />}><PathSummaryModal
        open={pathSummaryOpen}
        groupId={pathGroup?.id ?? null}
        groupName={pathGroup?.name}
        onCancel={() => setPathSummaryOpen(false)}
        onOpenDetail={openDetailById}
      /></Suspense>}
    </PageTransition>
  );
}
