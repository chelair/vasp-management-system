/**
 * 电子结构任务页（2026-10-13）：主任务 + 差分电荷分块合并展示（与自由能的
 * 「结构优化 + 频率矫正」同一个思路）。
 *
 * 分块子任务在左侧树里不单独成节点、巡检列表里也不单独成行；归档/重开跟随主任务。
 */

import { Button, Tabs, Tag, Tooltip } from 'antd';
import type { ReactNode } from 'react';
import { ExperimentOutlined } from '@ant-design/icons';
import type { Task } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  task: Task;
  /** 该 ele 任务下的差分电荷分块（按块序号排序；空数组 = 还没做差分电荷） */
  blocks: Task[];
  renderTask: (task: Task) => ReactNode;
  onCreateDiffCharge: (task: Task) => void;
  creating: boolean;
  /** 主任务是否具备做差分电荷的条件（有 POSCAR） */
  canCreate: boolean;
  disconnectHint?: string;
  activeKey: string;
  onActiveKeyChange: (key: string) => void;
}

export default function EleDetail({
  task,
  blocks,
  renderTask,
  onCreateDiffCharge,
  creating,
  canCreate,
  disconnectHint,
  activeKey,
  onActiveKeyChange,
}: Props) {
  const hasBlocks = blocks.length > 0;
  const disabledReason = hasBlocks
    ? '已有差分电荷分块（要重做先删除旧分块）'
    : !canCreate
      ? disconnectHint || '主任务还没有 POSCAR（先在 POSCAR 页生成/上传）'
      : '按原子划分分块后创建各分块的静态计算';
  return (
    <div className="job-panel">
      <div className="job-detail-head">
        <span className="job-detail-head__title">{task.model_name}</span>
        <Tag color="purple">电子结构</Tag>
        <span className="preview-note">
          电子结构任务{hasBlocks ? ` + 差分电荷 ${blocks.length} 个分块` : ''}
        </span>
        <Tooltip title={disabledReason}>
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={creating}
            disabled={!canCreate || hasBlocks}
            onClick={() => onCreateDiffCharge(task)}
            style={{ marginLeft: 'auto' }}
          >
            差分电荷计算
          </Button>
        </Tooltip>
      </div>
      <Tabs
        activeKey={activeKey}
        onChange={onActiveKeyChange}
        items={[
          {
            key: 'main',
            label: (
              <span>
                主任务 <StatusTag status={task.status} />
              </span>
            ),
            children: renderTask(task),
          },
          ...blocks.map((block) => ({
            key: `block:${block.task_id}`,
            label: (
              <span>
                {block.ele_block_label || `分块${block.ele_block}`}
                {Array.isArray(block.ele_block_atoms)
                  ? `（${block.ele_block_atoms.length} 原子）`
                  : ''}
                <StatusTag status={block.status} />
              </span>
            ),
            children: renderTask(block),
          })),
        ]}
      />
    </div>
  );
}
