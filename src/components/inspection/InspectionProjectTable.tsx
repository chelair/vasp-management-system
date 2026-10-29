import { useEffect, useMemo, useState } from 'react';
import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { InspectionResult } from '../../types';

export default function InspectionProjectTable({ rows, closed, loading, buildColumns }: {
  rows: InspectionResult[];
  closed: boolean;
  loading: boolean;
  buildColumns: (spans: Record<string, number>) => ColumnsType<InspectionResult>;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
  const current = Math.min(page, Math.max(1, Math.ceil(rows.length / pageSize)));
  useEffect(() => { setPage(1); }, [rows]);
  const spans = useMemo(() => {
    // 分组跨页时，在每页重新显示组名，合并单元格不能越过当前页。
    const visible = rows.slice((current - 1) * pageSize, current * pageSize);
    const result: Record<string, number> = {};
    const groupKey = (row: InspectionResult) => row.task_category === '自由能' ||
      (row.task_category === 'NEB' && row.group_name)
      ? `${row.task_category}|${row.group_name}` : null;
    for (let i = 0; i < visible.length;) {
      const key = groupKey(visible[i]);
      let end = i + 1;
      if (key) {
        while (end < visible.length && groupKey(visible[end]) === key) end++;
        result[visible[i].task_id] = end - i;
        for (let j = i + 1; j < end; j++) result[visible[j].task_id] = 0;
      }
      i = end;
    }
    return result;
  }, [rows, current, pageSize]);
  return <Table
    rowKey="id" dataSource={rows} columns={buildColumns(spans)} loading={loading}
    size="middle" rowClassName={() => closed ? 'inspection-row--closed' : ''}
    pagination={{
      current, pageSize, hideOnSinglePage: true, showSizeChanger: true,
      pageSizeOptions: [30, 60, 100], showTotal: total => `共 ${total} 项`,
      onChange: (next, size) => { setPage(size === pageSize ? next : 1); setPageSize(size); },
    }}
  />;
}
