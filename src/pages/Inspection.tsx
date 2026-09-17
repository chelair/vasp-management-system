import { useEffect, useMemo, useState } from 'react';
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
  DownOutlined,
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
import ForceHistoryCharts from '../components/inspection/ForceHistoryCharts';
import EleAnalysisPanel from '../components/inspection/EleAnalysisPanel';
import PathSummaryModal from '../components/inspection/PathSummaryModal';
import StructurePanel from '../components/inspection/StructurePanel';
import NebBarrierPanel from '../components/inspection/NebBarrierPanel';
import NebImages3DViewer from '../components/inspection/NebImages3DViewer';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatusTag from '../components/common/StatusTag';
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
  // 关闭项目默认折叠：这里记录"被用户手动展开"的项目名
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set());
  const [autoSaving, setAutoSaving] = useState(false);
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
    setCorrecting(true);
    try {
      // 联动：frac 本地尚无已完成记录时先单独巡检，再计算矫正项
      if (detailData.frac.status !== 'completed') {
        await runSingleInspection(detailData.frac.task_id);
      }
      await calculateCorrection(detailData.frac.task_id);
      message.success('矫正项计算完成');
      const data = await fetchInspectionDetail(detailData.task_id);
      setDetailData(data);
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
    Promise.all([fetchInspectionResults(), fetchInspectionMeta()])
      .then(([rows, m]) => {
        setResults(rows);
        setMeta(m);
      })
      .finally(() => setLoading(false));
  }, []);

  // 筛选变化时重置折叠状态（关闭项目仍保持默认折叠）
  useEffect(() => {
    setExpandedProjects(new Set());
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

  /** 自由能路径 / NEB 组跨行合并：同项目同组的连续行合并为一格（按项目块分别计算） */
  const rowSpanByProject = useMemo(() => {
    const result: Record<string, Record<string, number>> = {};
    projectBlocks.forEach((block) => {
      const rows = block.rows;
      const map: Record<string, number> = {};
      let i = 0;
      while (i < rows.length) {
        const row = rows[i];
        const grouped =
          row.task_category === '自由能' ||
          (row.task_category === 'NEB' && Boolean(row.group_name));
        if (!grouped) {
          i += 1;
          continue;
        }
        const key = `${row.project_name}|${row.group_name}`;
        let j = i + 1;
        while (
          j < rows.length &&
          (rows[j].task_category === '自由能' ||
            (rows[j].task_category === 'NEB' && Boolean(rows[j].group_name))) &&
          `${rows[j].project_name}|${rows[j].group_name}` === key
        ) {
          j += 1;
        }
        map[row.task_id] = j - i;
        for (let k = i + 1; k < j; k += 1) {
          map[rows[k].task_id] = 0;
        }
        i = j;
      }
      result[block.projectName] = map;
    });
    return result;
  }, [projectBlocks]);

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
      setDetailData(await fetchInspectionDetail(detail.task_id));
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
      if (fromDetail) {
        const data = await fetchInspectionDetail(row.task_id);
        setDetailData(data);
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
    try {
      const data = await fetchInspectionDetail(row.task_id);
      setDetailData(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '读取巡检详情失败');
    } finally {
      setDetailLoading(false);
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
      render: (v: string) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>,
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
      render: (v: string) => (
        <Tooltip title={v}>
          <span>{v}</span>
        </Tooltip>
      ),
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
                  ? ` · 上次 ${formatTime(new Date(meta.last_run_at))}`
                  : ' · 尚未巡检'}
                {meta?.next_run_at ? ` · 下次 ${meta.next_run_at}` : ''}
              </span>
              <Tooltip
                title={
                  meta?.scheduler?.last_error
                    ? `上次自动巡检失败：${meta.scheduler.last_error}`
                    : '距上次巡检超过间隔后自动执行全局巡检（后端后台线程）'
                }
              >
                <Switch
                  size="small"
                  checked={meta?.enabled !== false}
                  loading={autoSaving}
                  onChange={handleToggleAuto}
                />
              </Tooltip>
            </div>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={triggering}
              onClick={handleTrigger}
            >
              立即巡检
            </Button>
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

        <div className="inspection-projects">
          {projectBlocks.map((block) => {
            const expanded =
              !block.closed || expandedProjects.has(block.projectName);
            return (
              <div
                key={block.projectName}
                className={`inspection-project${block.closed ? ' inspection-project--closed' : ''}`}
              >
                <button
                  type="button"
                  className="inspection-project__head"
                  onClick={() =>
                    setExpandedProjects((prev) => {
                      const next = new Set(prev);
                      if (next.has(block.projectName)) next.delete(block.projectName);
                      else next.add(block.projectName);
                      return next;
                    })
                  }
                >
                  {expanded ? <DownOutlined /> : <RightOutlined />}
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
                {expanded && (
                  <Table
                    rowKey="id"
                    dataSource={block.rows}
                    columns={buildColumns(rowSpanByProject[block.projectName] ?? {})}
                    loading={loading}
                    pagination={false}
                    size="middle"
                    rowClassName={() =>
                      block.closed ? 'inspection-row--closed' : ''
                    }
                  />
                )}
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
        onCancel={() => setDetailOpen(false)}
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
              </Descriptions.Item>
              {detailData.notes && (
                <Descriptions.Item label="备注">{detailData.notes}</Descriptions.Item>
              )}
              {detailData.errors.length > 0 && (
                <Descriptions.Item label="错误信息">
                  {detailData.errors.join('；')}
                </Descriptions.Item>
              )}
            </Descriptions>

            {detailData.force_history.length > 0 && (
              <div className="inspection-detail__section">
                <h3>能量与力 · 离子步</h3>
                <ForceHistoryCharts history={detailData.force_history} />
              </div>
            )}

            {detailData.task_type === 'neb' &&
              detailData.neb_barrier &&
              detailData.neb_barrier.images.length > 0 && (
                <div className="inspection-detail__section">
                  <h3>NEB 过渡态能垒</h3>
                  <NebBarrierPanel images={detailData.neb_barrier.images} />
                </div>
              )}

            <div className="inspection-detail__section">
              <h3>{ANALYSIS_SECTION_TITLE[detailData.task_type] ?? '结构分析'}</h3>
              {detailData.task_type === 'ele' ? (
                <EleAnalysisPanel detail={detailData} />
              ) : detailData.task_type === 'neb' ? (
                // NEB 专属分析：只走映像结构视图，**不要**落到 StructurePanel
                // （StructurePanel 期望 opt 的 files/poscar/warnings 字段，NEB 载荷没有会白屏）
                detailData.analysis?.neb_images?.length ? (
                  <>
                    <div className="fe-footnote" style={{ marginTop: 0, marginBottom: 8 }}>
                      已同步 {detailData.analysis.neb_images.length} 个映像的优化后结构
                      {detailData.analysis.steps != null
                        ? `（NEB 推进约 ${detailData.analysis.steps} 离子步）`
                        : ''}
                    </div>
                    <NebImages3DViewer images={detailData.analysis.neb_images} />
                  </>
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
      </Modal>

      <PathSummaryModal
        open={pathSummaryOpen}
        groupId={pathGroup?.id ?? null}
        groupName={pathGroup?.name}
        onCancel={() => setPathSummaryOpen(false)}
        onOpenDetail={openDetailById}
      />
    </PageTransition>
  );
}
