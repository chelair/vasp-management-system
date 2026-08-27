import { Button, Tabs, Tag, Tooltip } from 'antd';
import type { ReactNode } from 'react';
import { ExperimentOutlined } from '@ant-design/icons';
import type { Task } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  structureLabel: string;
  optTask: Task;
  fracTask: Task | null;
  renderTask: (task: Task) => ReactNode;
  onCreateFrac: (optTask: Task) => void;
  fracCreating: boolean;
}

/** 自由能组内单个结构：结构优化 + 频率矫正 合并到一个页面 */
export default function StructureDetail({
  structureLabel,
  optTask,
  fracTask,
  renderTask,
  onCreateFrac,
  fracCreating,
}: Props) {
  const optDone = ['completed', 'unconverged', 'zombied'].includes(optTask.status);
  return (
    <div className="job-panel">
      <div className="job-detail-head">
        <span className="job-detail-head__title">{structureLabel}</span>
        <Tag color="cyan">自由能路径 · 主结构</Tag>
        <span className="preview-note">
          结构优化 + 频率矫正合并展示
        </span>
        <Tooltip title={optDone ? '从结构优化最新输出生成频率矫正输入文件' : '结构优化完成后可创建频率矫正'}>
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={fracCreating}
            disabled={!optDone}
            onClick={() => onCreateFrac(optTask)}
            style={{ marginLeft: 'auto' }}
          >
            频率计算
          </Button>
        </Tooltip>
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
