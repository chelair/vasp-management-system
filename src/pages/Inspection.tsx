import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Input,
  Modal,
  Skeleton,
  Tag,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { FilterDropdownProps } from 'antd/es/table/interface';
import type { Key } from 'react';
import {
  FileSearchOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import {
  fetchInspectionDetail,
  fetchInspectionMeta,
  fetchInspectionResults,
  runInspection,
  runSingleInspection,
} from '../api/inspections';
import type { InspectionMeta } from '../api/inspections';
import LineChart from '../components/inspection/LineChart';
import StructurePanel from '../components/inspection/StructurePanel';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatusTag from '../components/common/StatusTag';
import type {
  CheckStatus,
  InspectionDetail,
  InspectionResult,
  TaskStatus,
} from '../types';
import { formatTime } from '../utils/format';

const SCROLL_PAGE_SIZE = 20;

const TASK_CATEGORY_META: Record<string, { color: string; bg: string }> = {
  '结构优化': { color: '#2C6FBB', bg: '#EAF1FF' },
  '自由能': { color: '#2C9DA8', bg: '#E4F6F8' },
  NEB: { color: '#7B61D6', bg: '#F0EDFC' },
  '电子结构': { color: '#D18A2B', bg: '#FEF3E0' },
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
  { text: '未巡检', value: 'pending' },
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

const OUTPUT_STATUS_LABELS: Record<string, { label: string; color: string }> = {
  finished: { label: '已完成', color: 'success' },
  running: { label: '计算中', color: 'processing' },
  failed: { label: '失败', color: 'error' },
  waiting: { label: '等待', color: 'default' },
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
  const [results, setResults] = useState<InspectionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [singleRunningIds, setSingleRunningIds] = useState<Set<string>>(new Set());
  const [keyword, setKeyword] = useState(() => searchParams.get('q') || '');
  const [projectFilter, setProjectFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'projects'),
  );
  const [taskCategoryFilter, setTaskCategoryFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'categories'),
  );
  const [statusFilter, setStatusFilter] = useState<string[] | null>(() =>
    parseFilter(searchParams, 'statuses'),
  );
  const [visibleCount, setVisibleCount] = useState(SCROLL_PAGE_SIZE);
  const [detail, setDetail] = useState<InspectionResult | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState<InspectionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [meta, setMeta] = useState<InspectionMeta | null>(null);

  useEffect(() => {
    Promise.all([fetchInspectionResults(), fetchInspectionMeta()])
      .then(([rows, m]) => {
        setResults(rows);
        setMeta(m);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setVisibleCount(SCROLL_PAGE_SIZE);
  }, [keyword, projectFilter, taskCategoryFilter, statusFilter]);

  // 筛选同步到 URL：切换页面 / 刷新后自动恢复
  useEffect(() => {
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
    return results
      .filter((r) => {
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
      })
      .sort((a, b) => {
        const ca = TASK_CATEGORY_ORDER[a.task_category || '结构优化'] ?? 9;
        const cb = TASK_CATEGORY_ORDER[b.task_category || '结构优化'] ?? 9;
        if (ca !== cb) return ca - cb;
        return `${a.project_name} ${a.task_name}`.localeCompare(
          `${b.project_name} ${b.task_name}`,
          'zh-CN',
        );
      });
  }, [results, keyword, projectFilter, taskCategoryFilter, statusFilter]);

  const visibleRows = filtered.slice(0, visibleCount);

  const handleScrollLoad = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 48) {
      setVisibleCount((v) =>
        v >= filtered.length ? v : Math.min(v + SCROLL_PAGE_SIZE, filtered.length),
      );
    }
  };

  const fallbackNextAutoTime = useMemo(() => {
    const d = new Date(Date.now() + 2 * 60 * 60 * 1000);
    return formatTime(d);
  }, []);

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
      setProjectFilter(null);
      setTaskCategoryFilter(null);
      setStatusFilter(null);
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
      message.info('该任务尚未巡检，暂无详情数据');
      return;
    }
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

  const columns: ColumnsType<InspectionResult> = [
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
    { title: '任务', dataIndex: 'task_name', key: 'task_name', width: 190, ellipsis: true },
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
      title: '输出位置',
      key: 'output',
      width: 140,
      render: (_, row) => {
        const meta = row.output_status ? OUTPUT_STATUS_LABELS[row.output_status] : null;
        return (
          <div className="cell-output">
            <Tooltip title={row.latest_dir ? `续算目录 ${row.latest_dir}/` : '任务主目录'}>
              <span className="path-cell">
                {row.latest_dir ? `${row.latest_dir}/` : '主目录/'}
              </span>
            </Tooltip>
            {meta && <Tag color={meta.color}>{meta.label}</Tag>}
          </div>
        );
      },
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
          <Button
            size="small"
            type="link"
            icon={<InfoCircleOutlined />}
            onClick={() => openDetail(row)}
          >
            详情
          </Button>
        ) : (
          <Button
            size="small"
            type="link"
            icon={<ReloadOutlined />}
            loading={singleRunningIds.has(row.task_id)}
            disabled={triggering}
            onClick={() => runSingle(row)}
          >
            check
          </Button>
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
              <SyncOutlined />
              {meta?.enabled === false ? '自动巡检已停用' : '自动巡检已启用'}
              <span>
                每 {meta?.interval_hours ?? 2} 小时
                {meta?.last_run_at
                  ? ` · 上次 ${meta.last_run_at}`
                  : ` · 下次约 ${fallbackNextAutoTime}`}
                {meta?.last_run_at && meta.next_run_at
                  ? ` · 下次 ${meta.next_run_at}`
                  : ''}
              </span>
            </div>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={triggering}
              onClick={handleTrigger}
            >
              立即巡检
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

        <div className="inspection-scroll" onScroll={handleScrollLoad}>
          <Table
            rowKey="id"
            dataSource={visibleRows}
            columns={columns}
            loading={loading}
            pagination={false}
            size="middle"
            sticky
          />
        </div>
        {visibleRows.length < filtered.length && (
          <div className="scroll-hint">
            下滑加载更多（{visibleRows.length} / {filtered.length}）
          </div>
        )}
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
            <Button
              icon={<ReloadOutlined />}
              loading={detail ? singleRunningIds.has(detail.task_id) : false}
              disabled={triggering || detailLoading}
              onClick={() => detail && runSingle(detail, true)}
            >
              check
            </Button>
          </div>
        }
        width="min(1000px, calc(100vw - 32px))"
        destroyOnClose
        styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' } }}
      >
        {detailLoading ? (
          <Skeleton active paragraph={{ rows: 12 }} />
        ) : detailData ? (
          <div className="inspection-detail">
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
                <div className="analysis-charts">
                  <LineChart
                    title="能量 随离子步"
                    series={detailData.force_history.map((p) => p.energy)}
                    color="#2C6FBB"
                    unit="能量 (eV)"
                  />
                  <LineChart
                    title="最大力 随离子步"
                    series={detailData.force_history.map((p) => p.max_force)}
                    color="#C0392B"
                    unit="最大力 (eV/Å)"
                    threshold={0.02}
                  />
                </div>
              </div>
            )}

            {detailData.frac && (
              <div className="inspection-detail__section">
                <h3>频率矫正 · {detailData.frac.task_name}</h3>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="状态">
                    {detailData.frac.has_inspection ? (
                      <StatusTag status={detailData.frac.status as TaskStatus} />
                    ) : (
                      <Tag>未巡检</Tag>
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

            <div className="inspection-detail__section">
              <h3>结构分析</h3>
              {detailData.analysis ? (
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
                  description="非结构优化任务，无结构分析"
                />
              )}
            </div>
          </div>
        ) : (
          <Empty description="暂无详情数据" />
        )}
      </Modal>
    </PageTransition>
  );
}
