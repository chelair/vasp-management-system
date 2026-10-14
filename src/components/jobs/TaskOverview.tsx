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
import type { TaskInputState } from '../../api/jobs';
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
  /** 输入文件状态（远端快照 + 待生效草稿），用于「文件结构」的同步状态 */
  input?: TaskInputState | null;
}

/** 参与参数同步的文件（POTCAR / submit.sh 不在同步范围，只显示本地就绪状态） */
const SYNCED_FILES = ['INCAR', 'KPOINTS', 'POSCAR', 'CONTCAR'];
const FILE_ORDER = ['INCAR', 'KPOINTS', 'POSCAR', 'CONTCAR', 'POTCAR', 'vasp.lsf'];
/** 状态配色（一处定义，图标/文字/边框都跟它走） */
const STATE_COLOR = {
  fresh: 'var(--color-success)',
  stale: '#c98a1f',
  pending: '#e8a33d',
  muted: '#9aa7b8',
} as const;

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
  input,
}: Props) {
  const { message } = App.useApp();

  /** 待生效（有修改待提交）的文件集合 */
  const pendingFiles = new Set(
    (input?.changes ?? []).filter((c) => !c.applied_at).map((c) => c.file),
  );

  /**
   * 单个文件的展示状态（**2026-10-14 统一口径**，用户："这几个的显示逻辑改一下"）。
   *
   * 改之前有两种毛病：① 「本地没有」这一种情况在同步文件上叫「未同步」、在 POTCAR/vasp.lsf 上叫
   * 「未生成」，文案不统一；② 图标颜色只有不同步文件那条分支显式给了灰，同步文件那条继承成深色
   * ——同样是"没有这份文件"，CONTCAR 是黑 ⊖、POTCAR 是灰 ⊖。
   *
   * 现在按 **远端最新目录有没有 × 本地有没有** 判：
   *   远端有 + 本地有 → 最新（绿）        ｜ 草案未生效 → 有修改待提交（橙）
   *   远端有 + 本地无 → 待同步（灰）      ｜ 远端无 + 本地有 → 过时（黄）
   *   远端无 + 本地无 → 未生成（灰）      ｜ 不同步文件：本地有 → 已生成（绿）/ 无 → 未生成（灰）
   * 每个状态都带 tooltip 说明"下一步该做什么"。
   */
  const syncStateOf = (name: string) => {
    if (pendingFiles.has(name as 'INCAR' | 'KPOINTS')) {
      return {
        key: 'pending',
        label: '有修改待提交',
        icon: <EditOutlined style={{ color: STATE_COLOR.pending }} />,
        tip: '参数已改、还没生效：下次提交/续算时写入远端（不想改可撤销）',
      };
    }
    const remoteHas = Boolean(input?.files?.[name]);
    const localHas = Boolean(workspace.files[name]);
    if (remoteHas && localHas) {
      return {
        key: 'fresh',
        label: '最新',
        icon: <CheckCircleFilled style={{ color: STATE_COLOR.fresh }} />,
        tip: '本地与远端最新计算目录一致',
      };
    }
    if (remoteHas) {
      return {
        key: 'none',
        label: '待同步',
        icon: <MinusCircleFilled style={{ color: STATE_COLOR.muted }} />,
        tip: '远端最新目录里有这份文件、本地还没有：点「同步最新参数」拉回本地',
      };
    }
    if (localHas) {
      return {
        key: 'stale',
        label: '过时',
        icon: <MinusCircleFilled style={{ color: STATE_COLOR.stale }} />,
        tip: '本地有、远端最新计算目录里没有（远端换过计算目录或这份文件已被替换）',
      };
    }
    return {
      key: 'none',
      label: '未生成',
      icon: <MinusCircleFilled style={{ color: STATE_COLOR.muted }} />,
      tip: '远端和本地都还没有这份文件（还没生成输入文件 / 还没算出来）',
    };
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
          <Button type="primary" icon={<FileTextOutlined />} size="small" onClick={onGenerateInputs}>
            生成输入文件
          </Button>
        }
      >
        <div className="job-files">
          {FILE_ORDER.map((name) => {
            const synced = SYNCED_FILES.includes(name);
            const localReady = !!workspace.files[name];
            // 同步文件：远端×本地判状态；不同步文件（POTCAR / vasp.lsf）：只看本地有没有生成
            const state = synced
              ? syncStateOf(name)
              : {
                  key: localReady ? 'fresh' : 'none',
                  label: localReady ? '已生成' : '未生成',
                  icon: localReady ? (
                    <CheckCircleFilled style={{ color: STATE_COLOR.fresh }} />
                  ) : (
                    <MinusCircleFilled style={{ color: STATE_COLOR.muted }} />
                  ),
                  tip: localReady
                    ? '已生成（这份文件不走「同步最新参数」覆盖逻辑）'
                    : '还没生成：POTCAR 在 POSCAR 页生成、vasp.lsf 在提交脚本页生成',
                };
            return (
              <Tooltip key={name} title={state.tip}>
                <div className={`job-file job-file--${state.key}`}>
                  {state.icon}
                  <span className="job-file__name">{name}</span>
                  <span className="job-file__state">
                    {state.label}
                    {!synced && <span className="job-file__hint"> · 不参与同步</span>}
                  </span>
                </div>
              </Tooltip>
            );
          })}
        </div>
        <div className="preview-note" style={{ marginTop: 10 }}>
          <b style={{ color: STATE_COLOR.fresh }}>最新</b> = 本地与远端最新计算目录一致；
          <b style={{ color: STATE_COLOR.pending }}>有修改待提交</b> = 参数已改，等下次续算写入；
          <b style={{ color: STATE_COLOR.stale }}>过时</b> = 本地有、远端最新目录里没有；
          <b style={{ color: STATE_COLOR.muted }}>待同步</b> = 远端有、本地还没有（点下面按钮拉回）；
          <b style={{ color: STATE_COLOR.muted }}>未生成</b> = 远端和本地都还没有。
          POTCAR / vasp.lsf 只显示「已生成 / 未生成」，不参与同步覆盖。
          点「同步最新参数」会用远端最新目录覆盖本地文件（有未生效改动的文件跳过）。
          归档时后台会静默拉取该次计算的 OUTCAR / OSZICAR。
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
