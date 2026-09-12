import { App, Button, Card, Descriptions, Empty, Popconfirm, Space, Tag, Tooltip } from 'antd';
import {
  CheckCircleFilled,
  InboxOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  MinusCircleFilled,
  RedoOutlined,
  RocketOutlined,
  StopOutlined,
  ToolOutlined,
  UndoOutlined,
} from '@ant-design/icons';
import type { JobWorkspace, Task, TaskStatus, TaskType } from '../../types';
import { GROUP_ROLE_LABELS, TASK_STATUS_LABELS, TASK_TYPE_LABELS } from '../../types';
import { openTaskFolder } from '../../api/jobs';
import StatusTag from '../common/StatusTag';

interface Props {
  task: Task;
  workspace: JobWorkspace;
  onGenerateInputs: () => void;
  onContinuation: () => void;
  onSubmitScript: () => void;
  onSubmit: (task: Task) => void;
  submitting: boolean;
  onStop: (task: Task) => void;
  stopping: boolean;
  onBuildEle: (task: Task) => void;
  onRename: (task: Task) => void;
  onDelete: (task: Task) => void;
  /** 关闭（归档）任务 / 重新打开已归档任务 */
  onArchive?: (task: Task) => void;
  onUnarchive?: (task: Task) => void;
}

const FILE_ORDER = ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR', 'submit.sh', 'CONTCAR', 'WAVECAR'];

export default function TaskOverview({
  task,
  workspace,
  onGenerateInputs,
  onContinuation,
  onSubmitScript,
  onSubmit,
  submitting,
  onStop,
  stopping,
  onBuildEle,
  onRename,
  onDelete,
  onArchive,
  onUnarchive,
}: Props) {
  const { message } = App.useApp();

  const handleOpenFolder = async () => {
    try {
      const r = await openTaskFolder(task.task_id);
      message.success(`已打开文件夹：${r.path}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '打开文件夹失败');
    }
  };

  return (
    <div className="job-overview">
      <Card size="small" title="快捷操作" className="job-card">
        <Space wrap>
          <Button type="primary" icon={<FileTextOutlined />} onClick={onGenerateInputs}>
            生成输入文件
          </Button>
          {['opt', 'neb'].includes(task.task_type) && (
            <Button icon={<RedoOutlined />} onClick={onContinuation}>
              创建续算
            </Button>
          )}
          <Button icon={<CodeOutlined />} onClick={onSubmitScript}>
            生成提交脚本
          </Button>
          <Tooltip
            title={
              task.job_id && ['queued', 'running'].includes(task.status)
                ? '作业已提交/运行中'
                : undefined
            }
          >
          <Button
            type="primary"
            icon={<RocketOutlined />}
              loading={submitting}
              disabled={Boolean(task.job_id) && ['queued', 'running'].includes(task.status)}
              onClick={() => onSubmit(task)}
            >
              提交作业
            </Button>
          </Tooltip>
          {task.task_type === 'ele' && (
            <Button icon={<ToolOutlined />} onClick={() => onBuildEle(task)}>
              构建输入文件
            </Button>
          )}
          {task.job_id && ['queued', 'running'].includes(task.status) && (
            <Popconfirm
              title="确认停止该作业？"
              description={`作业 ${task.job_id} 将被 bkill 终止，状态回到待提交`}
              okText="停止"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => onStop(task)}
            >
              <Button danger icon={<StopOutlined />} loading={stopping}>
                停止作业
              </Button>
            </Popconfirm>
          )}
          <Button icon={<FolderOpenOutlined />} onClick={() => void handleOpenFolder()}>
            打开文件夹
          </Button>
          <Button icon={<EditOutlined />} onClick={() => onRename(task)}>
            重命名
          </Button>
          {task.status === 'archived'
            ? onUnarchive && (
                <Popconfirm
                  title="重新打开该任务？"
                  description={`任务将恢复为「${
                    TASK_STATUS_LABELS[
                      (task.archived_from as TaskStatus) ?? 'pending'
                    ] ?? '待提交'
                  }」状态，可继续巡检 / 续算`}
                  okText="重新打开"
                  cancelText="取消"
                  onConfirm={() => onUnarchive(task)}
                >
                  <Button icon={<UndoOutlined />}>重新打开</Button>
                </Popconfirm>
              )
            : onArchive && (
                <Popconfirm
                  title="关闭（归档）该任务？"
                  description={
                    task.status === 'completed'
                      ? '任务已正常结束，关闭后不再参与全局巡检（可随时重新打开）'
                      : `任务当前状态为「${
                          TASK_STATUS_LABELS[task.status]
                        }」，并非正常结束；关闭后不再参与全局巡检（可随时重新打开）`
                  }
                  okText="关闭"
                  cancelText="取消"
                  onConfirm={() => onArchive(task)}
                >
                  <Button icon={<InboxOutlined />}>关闭（归档）</Button>
                </Popconfirm>
              )}
          <Popconfirm
            title="确认删除该子项？"
            description="本地目录将移入回收站，远端目录不自动删除。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(task)}
          >
            <Button danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
          {task.continuation_ready && (
            <Tag color="processing">
              <FolderOpenOutlined /> 续算目录：{task.continuation_dir}
            </Tag>
          )}
        </Space>
      </Card>

      <Card size="small" title="任务信息" className="job-card">
        <Descriptions column={2} size="small" bordered className="job-desc">
          <Descriptions.Item label="任务 ID">{task.task_id}</Descriptions.Item>
          <Descriptions.Item label="作业类型">
            {TASK_TYPE_LABELS[task.task_type as TaskType] ?? task.task_type}
            {task.subtype ? `（${task.subtype}）` : ''}
          </Descriptions.Item>
          {task.group && (
            <Descriptions.Item label="流程组" span={2}>
              <Tag
                color={task.group.group_type === 'free_energy' ? 'cyan' : 'purple'}
              >
                {task.group.group_type === 'free_energy' ? '自由能组' : 'NEB 组'}
              </Tag>
              <span className="preview-note" style={{ marginLeft: 6 }}>
                {GROUP_ROLE_LABELS[task.group.group_role]} · {task.group.structure_label} ·{' '}
                {task.group.group_id}
              </span>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="状态">
            <StatusTag status={task.status} />
          </Descriptions.Item>
          <Descriptions.Item label="作业号">
            {task.job_id ? <span className="path-cell">{task.job_id}</span> : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="最近能量 (eV)" span={2}>
            {task.last_energy != null ? task.last_energy.toFixed(6) : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="最近巡检" span={2}>
            {task.last_check_time ? (
              <span className="path-cell">{task.last_check_time}</span>
            ) : (
              <span className="preview-note">尚未巡检</span>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="本地路径" span={2}>
            <Tooltip title={task.local_dir}>
              <span className="path-cell">{task.local_dir}</span>
            </Tooltip>
          </Descriptions.Item>
          <Descriptions.Item label="远程路径" span={2}>
            <Tooltip title={task.remote_dir}>
              <span className="path-cell">{task.remote_dir}</span>
            </Tooltip>
          </Descriptions.Item>
          {task.notes && (
            <Descriptions.Item label="备注" span={2}>
              {task.notes}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card
        size="small"
        title="文件结构"
        className="job-card mt-16"
        extra={
          <Button type="primary" icon={<FileTextOutlined />} size="small" onClick={onGenerateInputs}>
            生成输入文件
          </Button>
        }
      >
        <div className="job-files">
          {FILE_ORDER.map((name) => {
            const present = workspace.files[name];
            return (
              <div key={name} className={`job-file${present ? ' job-file--on' : ''}`}>
                {present ? (
                  <CheckCircleFilled style={{ color: 'var(--color-success)' }} />
                ) : (
                  <MinusCircleFilled style={{ color: 'var(--color-text-muted)' }} />
                )}
                <span className="job-file__name">{name}</span>
                <span className="job-file__state">{present ? '已就绪' : '未生成'}</span>
              </div>
            );
          })}
        </div>
        <div className="preview-note" style={{ marginTop: 10 }}>
          输入文件将写入本地目录，并由「提交脚本」同步到远程后执行。
        </div>
      </Card>

      {Object.values(workspace.files).every((v) => !v) && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="尚未生成任何输入文件，点击「生成输入文件」开始"
          style={{ marginTop: 28 }}
        />
      )}
    </div>
  );
}
