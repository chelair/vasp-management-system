import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Modal,
  Select,
  Skeleton,
  Tag,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
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
} from '../api/inspections';
import type { InspectionMeta } from '../api/inspections';
import LineChart from '../components/inspection/LineChart';
import StructurePanel from '../components/inspection/StructurePanel';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import StatusTag from '../components/common/StatusTag';
import type {
  CheckCategory,
  CheckStatus,
  InspectionDetail,
  InspectionResult,
  TaskStatus,
} from '../types';
import { CHECK_CATEGORY_LABELS } from '../types';
import { formatTime } from '../utils/format';

const CATEGORY_META: Record<CheckCategory, { color: string; bg: string }> = {
  convergence: { color: '#4A7BDD', bg: '#EAF1FF' },
  resource: { color: '#D18A2B', bg: '#FEF3E0' },
  file: { color: '#2C9DA8', bg: '#E4F6F8' },
  ssh: { color: '#7B61D6', bg: '#F0EDFC' },
  queue: { color: '#7A8BA1', bg: '#EEF2F7' },
};

type StatusFilter = 'all' | CheckStatus;
type AnalysisScope = 'all' | 'needed';

export default function Inspection() {
  const { message } = App.useApp();
  const [results, setResults] = useState<InspectionResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [category, setCategory] = useState<string>('all');
  const [detail, setDetail] = useState<InspectionResult | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState<InspectionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [meta, setMeta] = useState<InspectionMeta | null>(null);
  const [analysisScope, setAnalysisScope] = useState<AnalysisScope>('all');

  useEffect(() => {
    Promise.all([fetchInspectionResults(), fetchInspectionMeta()])
      .then(([rows, m]) => {
        setResults(rows);
        setMeta(m);
      })
      .finally(() => setLoading(false));
  }, []);

  const counts = useMemo(
    () => ({
      all: results.length,
      normal: results.filter((r) => r.status === 'normal').length,
      warning: results.filter((r) => r.status === 'warning').length,
      error: results.filter((r) => r.status === 'error').length,
    }),
    [results],
  );

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return results.filter((r) => {
      if (status !== 'all' && r.status !== status) return false;
      if (category !== 'all' && r.category !== category) return false;
      if (analysisScope === 'needed' && !r.analysis_needed) return false;
      if (
        kw &&
        !`${r.project_name} ${r.task_name} ${r.message}`.toLowerCase().includes(kw)
      ) {
        return false;
      }
      return true;
    });
  }, [results, keyword, status, category, analysisScope]);

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
      setStatus('all');
      setCategory('all');
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

  const openDetail = async (row: InspectionResult) => {
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
    { title: '项目', dataIndex: 'project_name', key: 'project_name', width: 150, ellipsis: true },
    { title: '任务', dataIndex: 'task_name', key: 'task_name', width: 190, ellipsis: true },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (c: CheckCategory) => {
        const meta = CATEGORY_META[c];
        return (
          <span className="category-tag" style={{ color: meta.color, background: meta.bg }}>
            {CHECK_CATEGORY_LABELS[c]}
          </span>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s: CheckStatus) => <StatusTag status={s} />,
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
      width: 80,
      render: (_, row) => (
        <Button size="small" type="link" icon={<InfoCircleOutlined />} onClick={() => openDetail(row)}>
          详情
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
          <div className="chip-row">
            {(
              [
                { k: 'all', label: `全部 ${counts.all}` },
                { k: 'normal', label: `正常 ${counts.normal}` },
                { k: 'warning', label: `警告 ${counts.warning}` },
                { k: 'error', label: `错误 ${counts.error}` },
              ] as { k: StatusFilter; label: string }[]
            ).map((c) => (
              <button
                key={c.k}
                type="button"
                className={`chip${status === c.k ? ' chip--active' : ''}`}
                onClick={() => setStatus(c.k)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="chip-row">
            <span className="filter-bar__label">分析范围</span>
            {(
              [
                { k: 'all', label: '全部' },
                { k: 'needed', label: '需结构分析' },
              ] as { k: AnalysisScope; label: string }[]
            ).map((c) => (
              <button
                key={c.k}
                type="button"
                className={`chip${analysisScope === c.k ? ' chip--active' : ''}`}
                onClick={() => setAnalysisScope(c.k)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div style={{ flex: 1 }} />
          <Input
            allowClear
            prefix={<FileSearchOutlined style={{ color: 'var(--color-text-muted)' }} />}
            placeholder="搜索项目 / 任务 / 信息"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 240 }}
          />
          <Select
            value={category}
            onChange={setCategory}
            style={{ width: 140 }}
            options={[
              { value: 'all', label: '全部类别' },
              { value: 'convergence', label: '收敛性' },
              { value: 'resource', label: '资源' },
              { value: 'file', label: '文件' },
              { value: 'ssh', label: 'SSH 连接' },
              { value: 'queue', label: '队列' },
            ]}
          />
        </div>

        <Table
          rowKey="id"
          dataSource={filtered}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          size="middle"
        />
      </Card>

      <Modal
        title={detail ? `${detail.task_name} · 巡检详情` : '巡检结果详情'}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
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
              <Descriptions.Item label="队列状态">
                {detailData.queue_status ?? '—'}
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
