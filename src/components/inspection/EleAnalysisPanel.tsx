import { useState } from 'react';
import { Button, Descriptions, Tooltip } from 'antd';
import PdosModal from './PdosModal';
import type { InspectionDetail } from '../../types';

interface Props {
  detail: InspectionDetail;
}

/** 电子结构任务分析面板：基础信息 + 可分析内容识别 + 分析入口 */
export default function EleAnalysisPanel({ detail }: Props) {
  const [pdosOpen, setPdosOpen] = useState(false);
  const aa = detail.available_analyses;

  const items = [
    { key: 'pdos', label: 'PDOS', available: aa?.pdos ?? false, reason: '需要 DOSCAR' },
    { key: 'bader', label: 'Bader', available: aa?.bader ?? false, reason: '需要 AECCAR0/1/2' },
    { key: 'cohp', label: 'COHP', available: aa?.cohp ?? false, reason: '开发中' },
    { key: 'work_function', label: '功函数', available: aa?.work_function ?? false, reason: '开发中' },
    { key: 'diff_charge', label: '差分电荷', available: false, reason: '开发中' },
  ];

  return (
    <div>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="子类型">{detail.model_name || '—'}</Descriptions.Item>
        <Descriptions.Item label="远程目录">
          {detail.current_output?.dir || '—'}
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {items.map((it) => {
          const disabled = !it.available || it.reason === '开发中';
          return (
            <Tooltip
              key={it.key}
              title={
                it.reason === '开发中'
                  ? '该分析暂未实现'
                  : it.available
                    ? '点击开始分析'
                    : it.reason
              }
            >
              <Button
                disabled={disabled}
                onClick={() => {
                  if (it.key === 'pdos') setPdosOpen(true);
                }}
              >
                {it.label}
                {it.reason === '开发中' ? '（开发中）' : !it.available ? '（文件缺失）' : ''}
              </Button>
            </Tooltip>
          );
        })}
      </div>
      <PdosModal open={pdosOpen} taskId={detail.task_id} onCancel={() => setPdosOpen(false)} />
    </div>
  );
}
