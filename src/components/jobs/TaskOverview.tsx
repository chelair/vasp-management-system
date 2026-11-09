import { useEffect, useRef, useState } from 'react';
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
import { fetchTaskFileStatus, openTaskFolder } from '../../api/jobs';
import type { TaskFileStatus, TaskInputState } from '../../api/jobs';
import { INSPECTION_COMPLETED } from '../../api/inspections';
import StatusTag from '../common/StatusTag';
import { checkNeedsAttention } from '../../utils/project';

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
  /** 输入文件记录与待生效草稿；不作为远端实时文件清单。 */
  input?: TaskInputState | null;
}

const FILE_ORDER = ['INCAR', 'KPOINTS', 'POSCAR', 'POTCAR', 'CONTCAR', 'OUTCAR', 'OSZICAR'];
/** 状态配色（一处定义，图标/文字/边框都跟它走） */
const STATE_COLOR = {
  fresh: 'var(--color-success)',
  stale: '#c98a1f',
  pending: '#e8a33d',
  muted: '#9aa7b8',
} as const;

export default function TaskOverview({
  task,
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
  input,
}: Props) {
  const { message } = App.useApp();
  const [refreshVersion, setRefreshVersion] = useState(0);
  const lastManualRefresh = useRef(0);
  const [remoteFiles, setRemoteFiles] = useState<{
    taskId: string;
    status: 'loading' | 'ready' | 'error';
    files: TaskFileStatus['files'];
    remoteChecked?: boolean;
    remoteDir?: string | null;
    checkedAt?: number;
    error?: string | null;
  } | null>(null);

  // 文件卡片以远端当前计算目录为准；本地草稿变化不触发远端查询。
  useEffect(() => {
    let disposed = false;
    let generation = 0;
    const refresh = async (force = false) => {
      const version = ++generation;
      setRemoteFiles({ taskId: task.task_id, status: 'loading', files: [] });
      try {
        const data = await fetchTaskFileStatus(task.task_id, true, true, force);
        if (!disposed && version === generation) {
          setRemoteFiles({ taskId: task.task_id, status: 'ready', files: data.files,
            remoteChecked: data.remote_checked, remoteDir: data.remote_dir,
            checkedAt: data.checked_at, error: data.error });
        }
      } catch {
        if (!disposed && version === generation) {
          setRemoteFiles({ taskId: task.task_id, status: 'error', files: [] });
        }
      }
    };
    const force = refreshVersion !== lastManualRefresh.current;
    lastManualRefresh.current = refreshVersion;
    void refresh(force);
    const onInspection = () => void refresh();
    window.addEventListener(INSPECTION_COMPLETED, onInspection);
    return () => {
      disposed = true;
      window.removeEventListener(INSPECTION_COMPLETED, onInspection);
    };
  }, [task.task_id, task.remote_dir, task.current_output?.latest_dir, task.job_id, task.status, input?.source?.synced_at, refreshVersion]);

  const filesStatus = remoteFiles?.taskId === task.task_id ? remoteFiles.status : 'loading';
  const filesByName = new Map(
    (filesStatus === 'ready' ? remoteFiles?.files ?? [] : []).map((file) => [file.name, file]),
  );

  /** 待生效（有修改待提交）的文件集合 */
  const pendingFiles = new Set<string>(
    (input?.changes ?? []).filter((c) => !c.applied_at).map((c) => c.file),
  );

  if (Object.keys(input?.draft?.INCAR ?? {}).length) pendingFiles.add('INCAR');
  if (input?.draft?.KPOINTS) pendingFiles.add('KPOINTS');

  const fileStateOf = (name: string) => {
    if (filesStatus !== 'ready') {
      return {
        key: 'none', label: filesStatus === 'error' ? '状态未知' : '读取中',
        tip: filesStatus === 'error'
          ? '文件状态读取失败，点击「刷新状态」重试。'
          : '正在读取文件状态。',
      };
    }
    const file = filesByName.get(name);
    const states: Record<string, { key: string; label: string; tip: string }> = {
      present: { key: 'fresh', label: '远端已有', tip: '当前远端计算目录中已有非空文件。' },
      missing: { key: 'none', label: '远端缺失', tip: '当前远端计算目录中没有该文件。' },
      empty: { key: 'stale', label: '远端空文件', tip: '远端存在大小为0的文件；NEB可能有部分映像文件为空。' },
      changing: { key: 'stale', label: '远端更新中', tip: '远端文件在本次查询期间发生变化，请稍后刷新；此状态不代表任务正在运行。' },
      unknown: { key: 'none', label: '状态未知', tip: '远端未能读取或映像数量超限，点击「刷新状态」重试。' },
    };
    const state = states[remoteFiles?.remoteChecked ? file?.remote_status ?? 'unknown' : 'unknown'];
    return { ...state, tip: `${state.tip}${file?.remote_count != null ? ` 远端${file.remote_count}份，共${file.remote_size}字节。` : ''}${pendingFiles.has(name) ? ' 另有待生效参数修改，尚未写入远端。' : ''}` };
  };

  /** 归档确认文案：自由能主任务会连带归档频率矫正，未完成时特别提醒 */
  const archiveDescription = (() => {
    const base =
      task.status === 'completed'
        ? '任务已正常结束，关闭后不再参与全局巡检（可随时重新打开）'
        : `任务当前状态为「${
            TASK_STATUS_LABELS[task.status]
          }」，并非正常结束；关闭后不再参与全局巡检（可随时重新打开）`;
    const frac = task.frac_sibling;
    if (!frac) return base;
    const fracLabel = TASK_STATUS_LABELS[frac.status] ?? frac.status;
    if (frac.status !== 'completed') {
      return `⚠️ 该任务的频率矫正（${frac.model_name}）当前为「${fracLabel}」，尚未正常结束；关闭主任务会一并归档它。\n${base}`;
    }
    return `${base}\n将同时归档其频率矫正任务（${frac.model_name}，已完成）。`;
  })();

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
          {task.job_id && (
            <Popconfirm
              title="确认停止该作业？"
              description={`将停止作业 ${task.job_id}；若作业已经结束，将刷新任务状态`}
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
                  }」状态，可继续巡检 / 续算${
                    task.frac_sibling ? '；其频率矫正任务也会一并重新打开' : ''
                  }`}
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
                    <span style={{ whiteSpace: 'pre-line' }}>{archiveDescription}</span>
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
            {task.check?.has_inspection ? (
              <Space size={8} wrap>
                <StatusTag status={task.check.status} kind="check" />
                <span className={checkNeedsAttention(task.check) ? 'job-check-msg' : 'preview-note'}>
                  {task.check.message}
                </span>
                {task.last_check_time && (
                  <span className="path-cell">{task.last_check_time}</span>
                )}
              </Space>
            ) : task.last_check_time ? (
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
          <Space>
            <Button size="small" loading={filesStatus === 'loading'} onClick={() => setRefreshVersion((v) => v + 1)}>
              刷新状态
            </Button>
            <Button type="primary" icon={<FileTextOutlined />} size="small" onClick={onGenerateInputs}>
              生成输入文件
            </Button>
          </Space>
        }
      >
        <div className="job-files">
          {FILE_ORDER.map((name) => {
            const state = fileStateOf(name);
            const color = state.key === 'fresh' ? STATE_COLOR.fresh
              : state.key === 'pending' ? STATE_COLOR.pending
              : state.key === 'stale' ? STATE_COLOR.stale : STATE_COLOR.muted;
            return (
              <Tooltip key={name} title={state.tip}>
                <div className={`job-file job-file--${state.key}`}>
                  {state.key === 'pending' ? <EditOutlined style={{ color }} />
                    : state.key === 'fresh' ? <CheckCircleFilled style={{ color }} />
                    : <MinusCircleFilled style={{ color }} />}
                  <span className="job-file__name">{name}</span>
                  <span className="job-file__state">
                    {state.label}
                  </span>
                </div>
              </Tooltip>
            );
          })}
        </div>
        <div className="preview-note" style={{ marginTop: 10 }}>
          显示远端当前计算目录的文件状态，续算时优先查看最新 conN 目录。结果保留1分钟，点击「刷新状态」立即更新。文件存在不代表计算已收敛。
          {remoteFiles?.taskId === task.task_id && remoteFiles.remoteChecked && remoteFiles.checkedAt && (
            <span> 读取时间：{new Date(remoteFiles.checkedAt * 1000).toLocaleString()}；目录：{remoteFiles.remoteDir}。</span>
          )}
          {remoteFiles?.taskId === task.task_id && remoteFiles.error && <span> {remoteFiles.error}。</span>}
          {pendingFiles.size > 0 && (
            <span> 待生效修改：{[...pendingFiles].join('、')}（尚未写入远端）。</span>
          )}
        </div>
      </Card>

      {filesStatus === 'ready' && remoteFiles?.remoteChecked && FILE_ORDER.every((name) => filesByName.get(name)?.remote_status === 'missing') && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="当前远端计算目录中尚无这些文件"
          style={{ marginTop: 28 }}
        />
      )}
    </div>
  );
}
