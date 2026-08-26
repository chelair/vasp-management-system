import { Tabs, Tag } from 'antd';
import type { ReactNode } from 'react';
import type { Task } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  structureLabel: string;
  optTask: Task;
  fracTask: Task | null;
  renderTask: (task: Task) => ReactNode;
}

/** 自由能组内单个结构：结构优化 + 频率矫正 合并到一个页面 */
export default function StructureDetail({
  structureLabel,
  optTask,
  fracTask,
  renderTask,
}: Props) {
  return (
    <div className="job-panel">
      <div className="job-detail-head">
        <span className="job-detail-head__title">{structureLabel}</span>
        <Tag color="cyan">自由能路径 · 主结构</Tag>
        <span className="preview-note">
          结构优化 + 频率矫正合并展示
        </span>
      </div>
      <Tabs
        items={[
          {
            key: 'opt',
            label: (
              <span>
                结构优化 <StatusTag status={optTask.status} />
              </span>
            ),
            children: renderTask(optTask),
          },
          ...(fracTask
            ? [
                {
                  key: 'frac',
                  label: (
                    <span>
                      频率矫正 <StatusTag status={fracTask.status} />
                    </span>
                  ),
                  children: renderTask(fracTask),
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
