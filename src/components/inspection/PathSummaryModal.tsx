import { useEffect, useState } from 'react';
import { App, Modal, Skeleton, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { fetchFreeEnergySummary } from '../../api/inspections';
import type { FreeEnergyStructure } from '../../api/inspections';
import PathStepChart from './PathStepChart';

interface Props {
  open: boolean;
  groupId: string | null;
  groupName?: string;
  onCancel: () => void;
  onOpenDetail: (taskId: string) => void;
}

/** 自由能路径综合分析看板：台阶图 + 中间体汇总表 */
export default function PathSummaryModal({
  open,
  groupId,
  groupName,
  onCancel,
  onOpenDetail,
}: Props) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [structures, setStructures] = useState<FreeEnergyStructure[]>([]);

  useEffect(() => {
    if (!open || !groupId) return;
    setLoading(true);
    setStructures([]);
    fetchFreeEnergySummary(groupId)
      .then((r) => setStructures(r.structures))
      .catch((err) => message.error(err instanceof Error ? err.message : '读取路径汇总失败'))
      .finally(() => setLoading(false));
  }, [open, groupId, message]);

  const columns: ColumnsType<FreeEnergyStructure> = [
    {
      title: '中间体',
      dataIndex: 'structure_label',
      width: 90,
      render: (v) => `结构 ${v}`,
    },
    {
      title: 'DFT 能量 (eV)',
      dataIndex: 'dft_energy',
      render: (v) => (v != null ? v.toFixed(4) : '—'),
    },
    {
      title: '矫正项 (eV)',
      dataIndex: 'correction',
      render: (v) => (v != null ? v.toFixed(4) : '—'),
    },
    {
      title: '自由能 (eV)',
      dataIndex: 'free_energy',
      render: (v) => (v != null ? v.toFixed(4) : '—'),
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_, r) =>
        `${r.converged ? '已收敛' : '未收敛'} · ${r.corrected ? '已矫正' : '未矫正'}`,
    },
  ];

  return (
    <Modal
      title={`自由能路径看板 · ${groupName ?? groupId ?? ''}`}
      open={open}
      onCancel={onCancel}
      footer={null}
      width="min(760px, calc(100vw - 32px))"
      destroyOnClose
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <>
          <PathStepChart
            structures={structures}
            onSelect={(taskId) => {
              // 三级窗口：详情叠加在总览之上，保留总览（叉掉详情回到总览）
              onOpenDetail(taskId);
            }}
          />
          <Table
            rowKey="task_id"
            columns={columns}
            dataSource={structures}
            pagination={false}
            size="small"
            style={{ marginTop: 14 }}
            onRow={(r) => ({
              onClick: () => {
                onOpenDetail(r.task_id);
              },
              style: { cursor: 'pointer' },
            })}
          />
        </>
      )}
    </Modal>
  );
}
