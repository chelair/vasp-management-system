import { App, Button, Card, Descriptions, Empty, Space, Tag, Tooltip } from 'antd';
import {
  CheckCircleFilled,
  CodeOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  MinusCircleFilled,
  RedoOutlined,
} from '@ant-design/icons';
import type { JobWorkspace, Task, TaskType } from '../../types';
import { TASK_TYPE_LABELS } from '../../types';
import { openTaskFolder } from '../../api/jobs';
import StatusTag from '../common/StatusTag';

interface Props {
  task: Task;
  workspace: JobWorkspace;
  onGenerateInputs: () => void;
  onContinuation: () => void;
  onSubmitScript: () => void;
}

const FILE_ORDER = ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR', 'submit.sh', 'CONTCAR', 'WAVECAR'];

export default function TaskOverview({
  task,
  workspace,
  onGenerateInputs,
  onContinuation,
  onSubmitScript,
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
          <Button icon={<RedoOutlined />} onClick={onContinuation}>
            创建续算
          </Button>
          <Button icon={<CodeOutlined />} onClick={onSubmitScript}>
            生成提交脚本
          </Button>
          <Button icon={<FolderOpenOutlined />} onClick={() => void handleOpenFolder()}>
            打开文件夹
          </Button>
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
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <StatusTag status={task.status} />
          </Descriptions.Item>
          <Descriptions.Item label="作业号">
            {task.job_id ? <span className="path-cell">{task.job_id}</span> : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="最近能量 (eV)" span={2}>
            {task.last_energy != null ? task.last_energy.toFixed(6) : '—'}
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
