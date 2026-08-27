import { Button, Tabs, Tag, Tooltip } from 'antd';
import type { ReactNode } from 'react';
import { FileAddOutlined } from '@ant-design/icons';
import type { Task } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  groupName: string;
  initialTask: Task | null;
  finalTask: Task | null;
  nebTask: Task | null;
  renderTask: (task: Task) => ReactNode;
  onCreateNebFiles: (nebTask: Task) => void;
  activeKey?: string;
  onActiveKeyChange?: (key: string) => void;
}

/** NEB 组详情：初态优化(IS) / 末态优化(FS) / NEB 映像 合并页面 */
export default function NebGroupDetail({
  groupName,
  initialTask,
  finalTask,
  nebTask,
  renderTask,
  onCreateNebFiles,
  activeKey,
  onActiveKeyChange,
}: Props) {
  const items = [
    ...(initialTask
      ? [
          {
            key: 'is',
            label: (
              <span>
                初态优化 IS <StatusTag status={initialTask.status} />
              </span>
            ),
            children: renderTask(initialTask),
          },
        ]
      : []),
    ...(finalTask
      ? [
          {
            key: 'fs',
            label: (
              <span>
                末态优化 FS <StatusTag status={finalTask.status} />
              </span>
            ),
            children: renderTask(finalTask),
          },
        ]
      : []),
    ...(nebTask
      ? [
          {
            key: 'neb',
            label: (
              <span>
                NEB 映像 <StatusTag status={nebTask.status} />
              </span>
            ),
            children: renderTask(nebTask),
          },
        ]
      : []),
  ];
  return (
    <div className="job-panel">
      <div className="job-detail-head">
        <span className="job-detail-head__title">{groupName}</span>
        <Tag color="purple">NEB 流程组</Tag>
        <span className="preview-note">初态 / 末态 / NEB 映像合并展示</span>
        {nebTask && (
          <Tooltip title="根据初末态 opt 最新输出生成 NEB 映像与输入文件">
            <Button
              type="primary"
              icon={<FileAddOutlined />}
              onClick={() => onCreateNebFiles(nebTask)}
              style={{ marginLeft: 'auto' }}
            >
              创建计算文件
            </Button>
          </Tooltip>
        )}
      </div>
      <Tabs
        activeKey={activeKey}
        onChange={onActiveKeyChange}
        items={items}
      />
    </div>
  );
}
