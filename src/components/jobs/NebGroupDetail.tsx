import { Tabs, Tag } from 'antd';
import type { ReactNode } from 'react';
import type { Task } from '../../types';
import StatusTag from '../common/StatusTag';

interface Props {
  groupName: string;
  initialTask: Task | null;
  finalTask: Task | null;
  nebTask: Task | null;
  renderTask: (task: Task) => ReactNode;
}

/** NEB 组详情：初态优化(IS) / 末态优化(FS) / NEB 映像 合并页面 */
export default function NebGroupDetail({
  groupName,
  initialTask,
  finalTask,
  nebTask,
  renderTask,
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
      </div>
      <Tabs items={items} />
    </div>
  );
}
