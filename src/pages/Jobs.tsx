import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Card, Empty, Input, InputNumber, Modal, Tabs } from 'antd';
import { Space } from 'antd';
import {
  ApartmentOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { fetchProjects, fetchTaskTypes } from '../api/projects';
import { addGroupStructures, createIndependentTask } from '../api/groups';
import {
  deleteIncarPreset,
  fetchClusterSnapshot,
  fetchTaskFile,
  fetchTaskFiles,
  loadIncarPresets,
  saveIncarPreset,
  saveTaskFile,
  renameTask,
  deleteTask,
  submitTask,
  stopTask,
  createFracFiles,
  archiveTask,
  unarchiveTask,
  copyIncarParamsToTasks,
  fetchTaskInput,
  revertTaskInputDraft,
  saveTaskInputDraft,
  syncTaskInput,
} from '../api/jobs';
import type { TaskFileEntry, TaskInputChange, TaskInputState } from '../api/jobs';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import JobsTree from '../components/jobs/JobsTree';
import NewTaskModal from '../components/jobs/NewTaskModal';
import TaskOverview from '../components/jobs/TaskOverview';
import PoscarPanel from '../components/jobs/PoscarPanel';
import IncarEditor from '../components/jobs/IncarEditor';
import KpointsPanel from '../components/jobs/KpointsPanel';
import SubmitScriptPanel from '../components/jobs/SubmitScriptPanel';
import TaskPickerModal from '../components/jobs/TaskPickerModal';
import ContinuationModal from '../components/jobs/ContinuationModal';
import EleInputModal from '../components/jobs/EleInputModal';
import NebFilesModal from '../components/jobs/NebFilesModal';
import GroupWizardModal from '../components/jobs/GroupWizardModal';
import InputSourceBanner from '../components/jobs/InputSourceBanner';
import StructureDetail from '../components/jobs/StructureDetail';
import NebGroupDetail from '../components/jobs/NebGroupDetail';
import AddProjectModal from '../components/projects/AddProjectModal';
import {
  applyIncarGates,
  buildDefaultParams,
  buildIncarText,
  incarFormParams,
  parseIncarContent,
  revertIncarPatch,
} from '../data/mock/incar';
import { buildInputFiles } from '../data/mock/vaspFiles';
import type {
  ClusterSnapshot,
  IncarPreset,
  JobWorkspace,
  NewTaskPayload,
  PrecisionMode,
  Project,
  Task,
  TaskRef,
  TaskType,
  TaskTypeOption,
} from '../types';
import { parsePoscar, buildKpoints, recommendKgrid } from '../utils/poscar';
import { formatStructureLabel } from '../utils/project';

const INPUT_FILES = ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR'];

function defaultTaskFor(taskId: string): Task {
  return {
    task_id: taskId,
    task_type: 'opt',
    model_name: taskId,
    status: 'pending',
    last_energy: null,
    last_check_time: null,
    job_id: null,
    notes: '',
    continuation_ready: false,
    continuation_dir: null,
    remote_dir: '',
    local_dir: '',
  };
}

/** 任务工作区初始状态：文件是否就绪以本地目录扫描结果为准 */
function makeWorkspace(task: Task): JobWorkspace {
  return {
    incarParams: buildDefaultParams(task.task_type as TaskType),
    precision: 'custom',
    poscarContent: null,
    poscarPath: null,
    kpointsContent: null,
    files: {
      INCAR: false,
      POSCAR: false,
      KPOINTS: false,
      POTCAR: false,
      'submit.sh': false,
      'vasp.lsf': false,
      CONTCAR: false,
      WAVECAR: false,
    },
    scriptFormat: 'lsf',
  };
}

export default function Jobs() {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const [projects, setProjects] = useState<Project[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskTypeOption[]>([]);
  const [workspaces, setWorkspaces] = useState<Record<string, JobWorkspace>>({});
  const [taskFileList, setTaskFileList] = useState<Record<string, TaskFileEntry[]>>({});
  const [loadedDisk, setLoadedDisk] = useState<Record<string, boolean>>({});
  /** 输入文件状态（远端快照 + 草稿 + 变更台账），按任务缓存 */
  const [inputStates, setInputStates] = useState<Record<string, TaskInputState>>({});
  /** 同上，供异步回调读取最新值（避免闭包里拿到旧状态） */
  const inputStatesRef = useRef(inputStates);
  inputStatesRef.current = inputStates;
  const [inputSyncing, setInputSyncing] = useState<string | null>(null);
  const [clusterSnapshot, setClusterSnapshot] = useState<ClusterSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [submittingTaskId, setSubmittingTaskId] = useState<string | null>(null);
  const [stoppingTaskId, setStoppingTaskId] = useState<string | null>(null);
  const [fracCreatingId, setFracCreatingId] = useState<string | null>(null);
  const [eleBuildTask, setEleBuildTask] = useState<Task | null>(null);
  const [nebBuildTask, setNebBuildTask] = useState<Task | null>(null);
  const [presets, setPresets] = useState<IncarPreset[]>(() => loadIncarPresets());
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedStructureKey, setSelectedStructureKey] = useState<string | null>(null);
  const [selectedNebGroupKey, setSelectedNebGroupKey] = useState<string | null>(null);
  const [nebActiveTab, setNebActiveTab] = useState('is');
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [newTaskType, setNewTaskType] = useState<TaskType>('opt');
  const [addProjectOpen, setAddProjectOpen] = useState(false);
  const [groupWizardOpen, setGroupWizardOpen] = useState(false);
  const [groupWizardKind, setGroupWizardKind] = useState<'free_energy' | 'neb'>('free_energy');
  const [continuationTask, setContinuationTask] = useState<Task | null>(null);
  const [renameTaskState, setRenameTaskState] = useState<Task | null>(null);
  const [renameName, setRenameName] = useState('');
  const [addStructGroup, setAddStructGroup] = useState<string | null>(null);
  const [addStructCount, setAddStructCount] = useState(1);
  const [copyParamsOpen, setCopyParamsOpen] = useState(false);
  /** 复制 INCAR 参数的**来源作业**（组页面里 selectedTask 为 null，必须显式记住） */
  const [copyParamsSource, setCopyParamsSource] = useState<Task | null>(null);
  const [genTask, setGenTask] = useState<Task | null>(null);
  const [generating, setGenerating] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  /** 首次打开/刷新：扫描所有子项本地目录，构建文件清单并回填文件就绪状态 */
  const scanAllLocalDirs = useCallback(async (ps: Project[]) => {
    const results = await Promise.all(
      ps.flatMap((p) => p.tasks).map(async (t) => {
        try {
          return { task: t, files: await fetchTaskFiles(t.task_id) };
        } catch {
          return { task: t, files: [] as TaskFileEntry[] };
        }
      }),
    );
    const map: Record<string, TaskFileEntry[]> = {};
    for (const r of results) map[r.task.task_id] = r.files;
    setTaskFileList(map);
    setWorkspaces((prev) => {
      const next = { ...prev };
      for (const r of results) {
        const names = new Set(r.files.map((f) => f.name));
        const base = next[r.task.task_id] ?? makeWorkspace(r.task);
        next[r.task.task_id] = {
          ...base,
          poscarPath: names.has('POSCAR') ? `${r.task.local_dir}/files/POSCAR` : null,
          files: {
            ...base.files,
            INCAR: names.has('INCAR'),
            POSCAR: names.has('POSCAR'),
            KPOINTS: names.has('KPOINTS'),
            POTCAR: names.has('POTCAR'),
            CONTCAR: names.has('CONTCAR'),
            WAVECAR: names.has('WAVECAR'),
            'submit.sh': names.has('submit.sh'),
          },
        };
      }
      return next;
    });
  }, []);

  /** 打开网站/刷新时后台更新集群节点状态（提交脚本页直接读取） */
  const loadClusterSnapshot = useCallback(async (refresh = false) => {
    setSnapshotLoading(true);
    try {
      const snap = await fetchClusterSnapshot(refresh);
      setClusterSnapshot(snap);
    } catch {
      // fetchClusterSnapshot 内部已回退模拟，不会抛错
    } finally {
      setSnapshotLoading(false);
    }
  }, []);

  /** 从后端重新加载项目与文件清单（创建任务/组后调用） */
  const refreshProjects = useCallback(async () => {
    const ps = await fetchProjects();
    setProjects(ps);
    const ws: Record<string, JobWorkspace> = {};
    for (const p of ps) {
      for (const t of p.tasks) {
        ws[t.task_id] = makeWorkspace(t);
      }
    }
    setWorkspaces(ws);
    await scanAllLocalDirs(ps);
    return ps;
  }, [scanAllLocalDirs]);

  useEffect(() => {
    Promise.all([fetchProjects(), fetchTaskTypes()])
      .then(([ps, tts]) => {
        setProjects(ps);
        setTaskTypes(tts);
        const ws: Record<string, JobWorkspace> = {};
        for (const p of ps) {
          for (const t of p.tasks) {
            ws[t.task_id] = makeWorkspace(t);
          }
        }
        setWorkspaces(ws);
        const queryTask = searchParams.get('task');
        const initialTask = queryTask
          ? ps
              .flatMap((p) => p.tasks)
              .find((t) => t.model_name === queryTask || t.task_id === queryTask)
          : undefined;
        if (initialTask) {
          const owner = ps.find((p) => p.tasks.some((t) => t.task_id === initialTask.task_id));
          setSelectedProjectId(owner?.id ?? ps[0]?.id ?? null);
          setSelectedTaskId(initialTask.task_id);
        } else if (ps.length > 0) {
          setSelectedProjectId(ps[0].id);
          setSelectedTaskId(ps[0].tasks[0]?.task_id ?? null);
        }
        const queryTab = searchParams.get('tab');
        if (queryTab) setActiveTab(queryTab);
        void scanAllLocalDirs(ps);
        void loadClusterSnapshot(false);
      })
      .catch((err) => message.error(err instanceof Error ? err.message : '加载作业数据失败'))
      .finally(() => setLoading(false));
  }, [message, scanAllLocalDirs, searchParams, loadClusterSnapshot]);

  const selectedProject =
    projects.find((p) => p.id === selectedProjectId) ?? null;
  const selectedTask =
    selectedProject?.tasks.find((t) => t.task_id === selectedTaskId) ?? null;
  const selectedWorkspace = useMemo(() => {
    if (!selectedTask) return null;
    return workspaces[selectedTask.task_id] ?? makeWorkspace(selectedTask);
  }, [selectedTask, workspaces]);

  /** 自由能组内结构（opt+frac 合并页） */
  const selectedStructure = useMemo(() => {
    if (!selectedStructureKey) return null;
    const rest = selectedStructureKey.slice(2);
    const [gid, label] = rest.split(':');
    const proj = projects.find((p) => p.tasks.some((t) => t.group?.group_id === gid));
    if (!proj) return null;
    const members = proj.tasks.filter(
      (t) => t.group?.group_id === gid && t.group?.structure_label === label,
    );
    return {
      gid,
      label,
      projectName: proj.name,
      opt: members.find((t) => t.task_type === 'opt') ?? null,
      frac: members.find((t) => t.task_type === 'frac') ?? null,
    };
  }, [selectedStructureKey, projects]);

  /** NEB 组（初态/末态/NEB 合并页） */
  const selectedNebGroup = useMemo(() => {
    if (!selectedNebGroupKey) return null;
    const rest = selectedNebGroupKey.slice(2);
    const [pid, gid] = rest.split(':');
    const proj = projects.find((p) => p.id === pid);
    if (!proj) return null;
    const members = proj.tasks.filter((t) => t.group?.group_id === gid);
    return {
      gid,
      projectName: proj.name,
      initial: members.find((t) => t.group?.group_role === 'initial_opt') ?? null,
      final: members.find((t) => t.group?.group_role === 'final_opt') ?? null,
      neb: members.find((t) => t.group?.group_role === 'neb_images') ?? null,
    };
  }, [selectedNebGroupKey, projects]);

  /** 需要自动读取文件内容的聚焦任务（选中任务 + 结构/组内任务） */
  const focusTasks = useMemo(() => {
    const list: Task[] = [];
    if (selectedTask) list.push(selectedTask);
    if (selectedStructure) {
      if (selectedStructure.opt) list.push(selectedStructure.opt);
      if (selectedStructure.frac) list.push(selectedStructure.frac);
    }
    if (selectedNebGroup) {
      for (const t of [selectedNebGroup.initial, selectedNebGroup.final, selectedNebGroup.neb]) {
        if (t) list.push(t);
      }
    }
    return list;
  }, [selectedTask, selectedStructure, selectedNebGroup]);

  /** 选中任务/结构/组时，自动读取本地目录中已有的 POSCAR / INCAR / KPOINTS */
  /** 读本地镜像文件；不存在或读取失败返回 null（不打扰用户） */
  const readLocalFile = async (taskId: string, name: string) => {
    try {
      const { content } = await fetchTaskFile(taskId, name);
      return content;
    } catch {
      return null;
    }
  };

  useEffect(() => {
    for (const task of focusTasks) {
      const taskId = task.task_id;
      // 输入文件状态（远端快照/草稿/台账）：只读本地缓存，不主动 SSH
      if (!inputStates[taskId]) {
        void loadInputState(task);
      }
      if (loadedDisk[taskId]) continue;
      const names = new Set((taskFileList[taskId] ?? []).map((f) => f.name));
      if (!names.has('POSCAR') && !names.has('INCAR') && !names.has('KPOINTS')) continue;
      setLoadedDisk((prev) => ({ ...prev, [taskId]: true }));
      void (async () => {
        const poscarText = names.has('POSCAR') ? await readLocalFile(taskId, 'POSCAR') : null;
        const kpointsText = names.has('KPOINTS') ? await readLocalFile(taskId, 'KPOINTS') : null;
        // INCAR：只在**没有远端快照**时才用本地镜像兜底。有快照时编辑器以
        // 「本次计算值 + 待生效草稿」为准（applyInputState 已回填），本地
        // files/INCAR 是同步时的旧值，覆盖回来会让人以为"刚改的草稿没了"。
        const incarText =
          names.has('INCAR') && !inputStatesRef.current[taskId]?.files?.INCAR?.params
            ? await readLocalFile(taskId, 'INCAR')
            : null;
        const parsedIncar = incarText ? parseIncarContent(incarText) : null;
        setWorkspaces((prev) => {
          // 用函数式更新取最新 workspace：异步返回时可能已被 applyInputState 回填过
          const base = prev[taskId] ?? makeWorkspace(task);
          const next: JobWorkspace = { ...base };
          if (poscarText != null) {
            next.poscarContent = poscarText;
            next.poscarPath = `${task.local_dir}/files/POSCAR`;
          }
          if (kpointsText != null) next.kpointsContent = kpointsText;
          if (parsedIncar) {
            next.incarParams = { ...base.incarParams, ...parsedIncar };
            next.precision = 'custom';
          }
          return { ...prev, [taskId]: next };
        });
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTasks, taskFileList]);

  const patchWorkspace = (taskId: string, patch: Partial<JobWorkspace>) => {
    setWorkspaces((prev) => ({
      ...prev,
      [taskId]: { ...(prev[taskId] ?? makeWorkspace(defaultTaskFor(taskId))), ...patch },
    }));
  };

  /** 更新本地文件清单 + 文件就绪标志 */
  /** 用输入文件状态（远端快照）回填编辑器：参数 = 默认值 + 本次计算实际参数 */
  const applyInputState = useCallback((task: Task, state: TaskInputState) => {
    setInputStates((prev) => ({ ...prev, [task.task_id]: state }));
    const snapshotParams = state.files?.INCAR?.params ?? null;
    const draftParams = state.draft?.INCAR ?? null;
    const kpointsText = state.files?.KPOINTS?.text ?? null;
    const poscarText = state.files?.POSCAR?.text ?? null;
    setWorkspaces((prev) => {
      const base = prev[task.task_id] ?? makeWorkspace(task);
      return {
        ...prev,
        [task.task_id]: {
          ...base,
          snapshotParams: snapshotParams ?? {},
          // 本次计算真正用到的参数 + 待生效草稿：有远端快照时缺省值不掺进来
          // （否则会把"远端没写、编辑器有默认值"的参数误判成已修改），
          // 同时**必须把草稿盖上**，否则刷新页面后表单回到已同步值、
          // 与顶部横幅里的"待生效修改"自相矛盾。
          incarParams: incarFormParams(
            task.task_type as TaskType,
            snapshotParams,
            draftParams,
          ),
          kpointsContent: kpointsText ?? base.kpointsContent,
          poscarContent: poscarText ?? base.poscarContent,
          precision: 'custom',
        },
      };
    });
  }, []);

  /** 拉取输入文件状态（首次选中任务时；不主动 SSH，只读本地已同步的快照） */
  const loadInputState = useCallback(
    async (task: Task, force = false) => {
      if (!force && inputStates[task.task_id]) return inputStates[task.task_id];
      try {
        const state = await fetchTaskInput(task.task_id);
        applyInputState(task, state);
        return state;
      } catch {
        return null;
      }
    },
    [applyInputState, inputStates],
  );

  /** 同步远端最新计算目录的参数（1 次 exec + 4 次小文件下载） */
  const handleSyncInput = async (task: Task) => {
    setInputSyncing(task.task_id);
    try {
      const state = await syncTaskInput(task.task_id);
      applyInputState(task, state);
      message.success(
        `已同步 ${state.source?.con || '主目录'} 的输入参数（INCAR/KPOINTS/POSCAR/CONTCAR）`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : '同步输入参数失败');
    } finally {
      setInputSyncing(null);
    }
  };

  /** 确认参数修改：把与快照不同的参数写进草稿（下次续算生效） */
  const handleConfirmParams = async (task: Task, params: Record<string, string>) => {
    if (!inputStates[task.task_id]) {
      message.warning('尚未同步本次计算参数，先点「同步最新参数」再改参数');
      return;
    }
    try {
      // 主开关关闭的整组参数（DFT+U / 偶极矩修正）不进入草稿 → 续算时也不会写入
      const state = await saveTaskInputDraft(task.task_id, {
        file: 'INCAR',
        params: applyIncarGates(params),
      });
      setInputStates((prev) => ({ ...prev, [task.task_id]: state }));
      const count = state.changes.filter((c) => !c.applied_at).length;
      message.success(
        count > 0
          ? `已记录 ${count} 项参数修改，将在下次续算时写入新目录`
          : '参数与本次计算一致，无需修改',
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存参数修改失败');
    }
  };

  /** 取消编辑：回到「本次计算值 + 待生效修改」（草稿是已确认的修改，不属于本次编辑） */
  const handleResetParams = (task: Task) => {
    const state = inputStates[task.task_id];
    patchWorkspace(task.task_id, {
      incarParams: incarFormParams(
        task.task_type as TaskType,
        state?.files?.INCAR?.params ?? null,
        state?.draft?.INCAR ?? null,
      ),
    });
  };

  /** 撤销某（几）个文件的全部待生效修改；按顺序请求，最后一个 state 即最终状态 */
  const handleRevertDraft = async (task: Task, files: ('INCAR' | 'KPOINTS')[]) => {
    if (files.length === 0) return;
    try {
      let state = inputStates[task.task_id];
      for (const file of files) {
        state = await revertTaskInputDraft(task.task_id, file);
      }
      if (state) applyInputState(task, state);
      message.success(`已撤销 ${files.join(' / ')} 的全部待生效修改`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '撤销失败');
    }
  };

  /**
   * 撤销**单项**待生效修改：只回滚这一项，其余修改保持不变。
   *
   * - INCAR：向后端提交"该键置空"的补丁（空值 = 回到本次计算值）；
   *   如果撤销的是带主开关那一组（DFT+U / 偶极矩修正），主开关关掉时
   *   整组依赖参数一起置空，避免下次续算仍写入 LDAUU 之类的孤立参数。
   * - KPOINTS：只有 k 网格一项，等价于整文件撤销。
   */
  const handleRevertChange = async (task: Task, change: TaskInputChange) => {
    const current = inputStates[task.task_id];
    if (!current) return;
    try {
      if (change.file === 'KPOINTS') {
        const state = await revertTaskInputDraft(task.task_id, 'KPOINTS');
        applyInputState(task, state);
        message.success('已撤销 KPOINTS 的修改');
        return;
      }
      const patch = revertIncarPatch(
        change.key,
        current.draft?.INCAR ?? {},
        current.files?.INCAR?.params ?? {},
      );
      const state = await saveTaskInputDraft(task.task_id, { file: 'INCAR', params: patch });
      applyInputState(task, state);
      const extra = Object.keys(patch).length - 1;
      message.success(
        extra > 0
          ? `已撤销 ${change.key}，依赖的 ${extra} 个参数一并撤销`
          : `已撤销 ${change.key}`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : '撤销失败');
    }
  };

  /** 更新本地文件清单 + 文件就绪标志 */
  const upsertLocalFile = (taskId: string, name: string, size: number) => {
    setTaskFileList((prev) => {
      const list = prev[taskId] ?? [];
      const idx = list.findIndex((f) => f.name === name);
      const entry: TaskFileEntry = { name, size, modified: new Date().toISOString() };
      const next = idx >= 0 ? [...list.slice(0, idx), entry, ...list.slice(idx + 1)] : [...list, entry];
      return { ...prev, [taskId]: next };
    });
    setWorkspaces((prev) => {
      const base = prev[taskId] ?? makeWorkspace(defaultTaskFor(taskId));
      return {
        ...prev,
        [taskId]: { ...base, files: { ...base.files, [name]: true } },
      };
    });
  };

  /** 全部任务（除当前）作为复制 POSCAR / INCAR 的目标 */
  const copyTargets: TaskRef[] = useMemo(
    () =>
      projects.flatMap((p) =>
        p.tasks
          .filter((t) => t.task_id !== selectedTaskId)
          .map((t) => ({
            projectId: p.id,
            projectName: p.name,
            projectClosed: !!p.closed,
            taskId: t.task_id,
            taskName: t.model_name,
            taskType: t.task_type as TaskType,
            status: t.status,
          })),
      ),
    [projects, selectedTaskId],
  );

  const selectProject = (projectId: string) => {
    const p = projects.find((x) => x.id === projectId);
    setSelectedProjectId(projectId);
    setSelectedTaskId(p?.tasks[0]?.task_id ?? null);
    setSelectedStructureKey(null);
    setSelectedNebGroupKey(null);
  };

  const handleSelectTask = (taskId: string) => {
    const owner = projects.find((p) => p.tasks.some((t) => t.task_id === taskId));
    if (owner) setSelectedProjectId(owner.id);
    const task = owner?.tasks.find((t) => t.task_id === taskId);
    if (task?.group?.group_type === 'neb') {
      // NEB 组内任一子任务：显示 NEB 流程组页面并定位到对应 tab
      const gid = task.group.group_id;
      const role = task.group.group_role;
      setNebActiveTab(role === 'final_opt' ? 'fs' : role === 'neb_images' ? 'neb' : 'is');
      setSelectedTaskId(null);
      setSelectedStructureKey(null);
      setSelectedNebGroupKey(`g:${owner!.id}:${gid}`);
      return;
    }
    setSelectedTaskId(taskId);
    setSelectedStructureKey(null);
    setSelectedNebGroupKey(null);
  };

  /** 选择自由能组内结构（结构优化 + 频率矫正合并页面） */
  const handleSelectStructure = (key: string) => {
    const [gid] = key.split(':');
    const owner = projects.find((p) => p.tasks.some((t) => t.group?.group_id === gid));
    if (owner) setSelectedProjectId(owner.id);
    setSelectedTaskId(null);
    setSelectedNebGroupKey(null);
    setSelectedStructureKey(`s:${key}`);
  };

  /** 选择组节点：NEB 组打开合并页面，自由能组仅展开 */
  const handleSelectGroup = (key: string) => {
    const rest = key.split(':');
    const pid = rest[0];
    const gid = rest[1];
    const proj = projects.find((p) => p.id === pid);
    const member = proj?.tasks.find((t) => t.group?.group_id === gid);
    if (member?.group?.group_type !== 'neb') return;
    setSelectedProjectId(pid);
    setSelectedTaskId(null);
    setSelectedStructureKey(null);
    setNebActiveTab('is');
    setSelectedNebGroupKey(`g:${key}`);
  };

  const openNewGroup = (projectId: string, kind: 'free_energy' | 'neb') => {
    setSelectedProjectId(projectId);
    setGroupWizardKind(kind);
    setGroupWizardOpen(true);
  };

  const openNewTask = (projectId: string | null, type: TaskType = 'opt') => {
    if (!projectId) {
      message.warning('请先选择项目');
      return;
    }
    setSelectedProjectId(projectId);
    setNewTaskType(type);
    setSelectedTaskId(null);
    setNewTaskOpen(true);
  };

  const closeNewTask = () => {
    setNewTaskOpen(false);
    if (selectedProject) {
      setSelectedTaskId(selectedProject.tasks[0]?.task_id ?? null);
    }
  };

  const handleCreateTask = (payload: NewTaskPayload) => {
    if (!selectedProject) return;
    void (async () => {
      try {
        const created = await createIndependentTask({
          project: selectedProject.name,
          model_name: payload.modelName,
          task_type: payload.taskType,
          subtype: payload.subtype ?? null,
        });
        const ps = await refreshProjects();
        const target = ps
          .flatMap((p) => p.tasks)
          .find((t) => t.task_id === created.task_id);
        if (target) {
          setSelectedProjectId(selectedProject.id);
          setSelectedTaskId(target.task_id);
        }
        setNewTaskOpen(false);
        message.success(`子项已创建：${payload.modelName}`);
      } catch (err) {
        message.error(err instanceof Error ? err.message : '创建子项失败');
      }
    })();
  };

  const handleGroupCreated = async () => {
    setGroupWizardOpen(false);
    await refreshProjects();
  };

  /** 同类型续算创建成功后：续算子任务不单独展示，仅提示续算目录信息 */
  const handleSameTypeCreated = async (
    result: {
      task_id: string;
      con: string;
      remote_dir: string;
      warnings: string[];
    },
    parentTaskId?: string,
  ) => {
    await refreshProjects();
    // 续算会把父任务"已应用"的草稿清掉（台账标 applied_in=conN），
    // 这里必须重新读取它的输入状态，否则 INCAR/KPOINTS 的同步状态要刷新页面才更新
    if (parentTaskId) {
      try {
        const state = await fetchTaskInput(parentTaskId);
        setInputStates((prev) => ({ ...prev, [parentTaskId]: state }));
        const parent = projects
          .flatMap((p) => p.tasks)
          .find((t) => t.task_id === parentTaskId);
        if (parent) applyInputState(parent, state);
      } catch {
        /* 读取失败不阻塞续算成功提示 */
      }
    }
    message.success(`续算目录已创建：${result.con}（${result.remote_dir}）`);
  };

  /** 重命名独立任务 */
  const handleRenameTask = async () => {
    if (!renameTaskState) return;
    try {
      const r = await renameTask(renameTaskState.task_id, renameName.trim());
      message.success(`已重命名为：${r.model_name}`);
      setRenameTaskState(null);
      setRenameName('');
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重命名失败');
    }
  };

  /** 删除最末端子项 */
  const handleDeleteTask = async (task: Task) => {
    try {
      const r = await deleteTask(task.task_id);
      message.success(
        `已删除：${r.model_name}${r.local_trash ? '（本地目录已移入回收站）' : ''}`,
      );
      if (selectedTaskId === task.task_id) {
        setSelectedTaskId(null);
        setSelectedStructureKey(null);
        setSelectedNebGroupKey(null);
      }
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  /** 提交作业：远程 bsub < vasp.lsf，成功后刷新任务状态 */
  const handleSubmitTask = async (task: Task) => {
    if (submittingTaskId) return;
    setSubmittingTaskId(task.task_id);
    try {
      const r = await submitTask(task.task_id);
      message.success(`作业 ${r.job_id} 已提交到队列`);
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '提交作业失败');
    } finally {
      setSubmittingTaskId(null);
    }
  };

  /** 关闭（归档）任务：只改状态，文件不动；未正常结束时前端已弹窗提醒 */
  const handleArchiveTask = async (task: Task) => {
    try {
      const r = await archiveTask(task.task_id);
      const siblingNote = r.archived_siblings?.length
        ? `，并一并归档频率矫正 ${r.archived_siblings
            .map((s) => s.model_name)
            .join('、')}`
        : '';
      message.success(
        r.was_completed
          ? `任务 ${task.model_name} 已关闭（归档）${siblingNote}`
          : `任务 ${task.model_name} 已关闭（归档，原状态 ${r.previous_status}）${siblingNote}`,
      );
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '关闭任务失败');
    }
  };

  /** 重新打开已归档任务（恢复到归档前状态） */
  const handleUnarchiveTask = async (task: Task) => {
    try {
      const r = await unarchiveTask(task.task_id);
      const siblingNote = r.reopened_siblings?.length
        ? `，频率矫正 ${r.reopened_siblings.map((s) => s.model_name).join('、')} 也已恢复`
        : '';
      message.success(
        `任务 ${task.model_name} 已重新打开（${r.new_status}）${siblingNote}`,
      );
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '重新打开任务失败');
    }
  };

  /** 停止作业：远程 bkill 终止运行中的作业 */
  const handleStopTask = async (task: Task) => {
    if (stoppingTaskId) return;
    setStoppingTaskId(task.task_id);
    try {
      const r = await stopTask(task.task_id);
      message.success(`作业 ${r.job_id} 已停止`);
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '停止作业失败');
    } finally {
      setStoppingTaskId(null);
    }
  };

  /** 频率计算：为自由能结构 opt 任务构建 frac 输入文件 */
  const handleCreateFrac = async (optTask: Task) => {
    if (fracCreatingId) return;
    setFracCreatingId(optTask.task_id);
    try {
      const r = await createFracFiles(optTask.task_id);
      message.success(`频率矫正输入已生成：${r.frac_dir}`);
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建频率矫正失败');
    } finally {
      setFracCreatingId(null);
    }
  };

  /** 自由能组添加结构 */
  const handleAddStructure = async () => {
    if (!addStructGroup) return;
    try {
      const r = await addGroupStructures(addStructGroup, addStructCount);
      message.success(`已添加结构：${r.labels.join('、')}`);
      setAddStructGroup(null);
      setAddStructCount(1);
      await refreshProjects();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '添加结构失败');
    }
  };

  const handleParamsChange = (
    params: Record<string, string>,
    precision: PrecisionMode,
    task?: Task | null,
  ) => {
    const t = task ?? selectedTask;
    if (!t) return;
    patchWorkspace(t.task_id, { incarParams: params, precision });
  };

  const handleApplyPreset = (preset: IncarPreset, task?: Task | null) => {
    const t = task ?? selectedTask;
    if (!t) return;
    patchWorkspace(t.task_id, {
      incarParams: { ...preset.params },
      precision: 'custom',
    });
  };

  const handleSavePreset = (name: string, task?: Task | null) => {
    const t = task ?? selectedTask;
    const ws = t ? workspaces[t.task_id] ?? makeWorkspace(t) : null;
    if (!ws) return;
    saveIncarPreset(name, ws.incarParams);
    setPresets(loadIncarPresets());
    message.success(`预设已保存：${name}`);
  };

  const handleDeletePreset = (id: string) => {
    setPresets(deleteIncarPreset(id));
    message.success('预设已删除');
  };

  /**
   * 复制当前 INCAR 参数到其他作业。
   *
   * 修复（v0.8.9）：原来只改前端会话状态，切到目标任务时会被「本次计算值 /
   * 默认值」覆盖，看起来像"复制没生效、框里还是默认值"。现在与「确认修改」
   * 同一口径——**把参数写成目标任务的待生效草稿**（下次续算写入，也可在目标
   * 任务点「同步到远端」立即生效），并把返回的输入状态回填，打开就能看到。
   */
  const handleCopyParams = async (targets: TaskRef[], task?: Task | null) => {
    // 来源作业：显式传入 > 打开弹窗时记住的 > 当前选中的（自由能/NEB 组页面里 selectedTask 是 null）
    const t = task ?? copyParamsSource ?? selectedTask;
    const ws = t ? workspaces[t.task_id] ?? makeWorkspace(t) : null;
    if (!t || !ws) {
      // 以前这里是静默 return：弹窗不关、没有提示、也不发请求，看起来像"点了没反应"
      message.error('没找到要复制的来源作业，请重新打开该作业的 INCAR 页再试');
      return;
    }
    setCopyParamsOpen(false);
    // 来源作业自己不能当目标（组页面里可能被列进去）
    const effective = targets.filter((x) => x.taskId !== t.task_id);
    if (effective.length === 0) {
      message.warning('请至少选择一个目标任务');
      return;
    }
    // 主开关关闭的整组参数（DFT+U / 偶极矩修正）不写入，与「确认修改」一致
    const params = applyIncarGates({ ...ws.incarParams });
    const results = await copyIncarParamsToTasks(
      effective.map((x) => x.taskId),
      params,
    );
    const allTasks = projects.flatMap((p) => p.tasks);
    let ok = 0;
    for (const { taskId, state } of results) {
      if (!state) continue;
      ok += 1;
      const real = allTasks.find((x) => x.task_id === taskId);
      // 回填目标任务：表单显示「本次计算值 + 刚复制的待生效修改」
      if (real) applyInputState(real, state);
      else setInputStates((prev) => ({ ...prev, [taskId]: state }));
    }
    if (ok === effective.length) {
      message.success(
        `已把当前参数记为 ${ok} 个作业的待生效修改（下次续算写入；在目标任务点「同步到远端」可立即生效）`,
      );
    } else if (ok > 0) {
      message.warning(`已写入 ${ok}/${effective.length} 个作业，其余失败请重试`);
    } else {
      message.error('复制失败：未能写入任何作业');
    }
  };

  /** 导入 POSCAR：写入本地任务目录 files/POSCAR，并同步会话状态 */
  const handleImportPoscar = async (content: string, task?: Task | null) => {
    const t = task ?? selectedTask;
    if (!t) return;
    const info = parsePoscar(content);
    let path = `${t.local_dir}/files/POSCAR`;
    try {
      const r = await saveTaskFile(t.task_id, 'POSCAR', content);
      path = r.path;
      upsertLocalFile(t.task_id, 'POSCAR', r.size);
      message.success(`POSCAR 已保存：${r.path}`);
    } catch (err) {
      message.warning(
        err instanceof Error
          ? `后端写入失败，仅更新当前会话：${err.message}`
          : '后端写入失败，仅更新当前会话',
      );
    }
    patchWorkspace(t.task_id, {
      poscarContent: content,
      poscarPath: path,
      kpointsContent: info
        ? buildKpoints(t.model_name, 'Gamma', recommendKgrid(info.lengths, 20), 20)
        : null,
    });
  };

  const handleCopyPoscar = (sourceTaskId: string, task?: Task | null) => {
    const t = task ?? selectedTask;
    if (!t) return;
    const source = projects
      .flatMap((p) => p.tasks)
      .find((t) => t.task_id === sourceTaskId);
    if (!source) return;
    const content =
      workspaces[sourceTaskId]?.poscarContent ?? buildInputFiles(source.model_name).POSCAR;
    void handleImportPoscar(content, t);
  };

  const handleGenerateKpoints = async (content: string, task?: Task | null) => {
    const t = task ?? selectedTask;
    if (!t) return;
    patchWorkspace(t.task_id, { kpointsContent: content });
    try {
      const r = await saveTaskFile(t.task_id, 'KPOINTS', content);
      upsertLocalFile(t.task_id, 'KPOINTS', r.size);
      message.success(`KPOINTS 已保存：${r.path}`);
    } catch (err) {
      message.warning(
        err instanceof Error ? `KPOINTS 写入后端失败：${err.message}` : 'KPOINTS 写入后端失败',
      );
    }
  };

  /** 生成输入文件：真实写入 INCAR / POSCAR / KPOINTS（POTCAR 需后端拼伪势） */
  const handleGenerateInputs = async () => {
    if (!genTask) return;
    setGenerating(true);
    await new Promise((r) => window.setTimeout(r, 700));
    const base = workspaces[genTask.task_id] ?? makeWorkspace(genTask);
    const poscar = base.poscarContent ?? buildInputFiles(genTask.model_name).POSCAR;
    const incarText = buildIncarText(base.incarParams);
    const info = parsePoscar(poscar);
    const kpoints =
      base.kpointsContent ??
      (info
        ? buildKpoints(genTask.model_name, 'Gamma', recommendKgrid(info.lengths, 20), 20)
        : null);

    const writes: Promise<{ name: string; size: number } | Error>[] = [
      saveTaskFile(genTask.task_id, 'INCAR', incarText),
      saveTaskFile(genTask.task_id, 'POSCAR', poscar),
    ];
    if (kpoints) {
      writes.push(saveTaskFile(genTask.task_id, 'KPOINTS', kpoints));
    }
    const results = await Promise.all(writes.map((p) => p.catch((e: unknown) => e)));
    const failed = results.filter((r): r is Error => r instanceof Error);
    if (failed.length > 0) {
      message.warning(`${failed.length} 个文件写入后端失败，已在会话内更新`);
    }
    for (const r of results) {
      if (r && !(r instanceof Error) && typeof r === 'object' && 'name' in r && 'size' in r) {
        upsertLocalFile(genTask.task_id, String(r.name), Number(r.size));
      }
    }
    const ws: JobWorkspace = {
      ...base,
      poscarContent: poscar,
      poscarPath: base.poscarPath ?? `${genTask.local_dir}/files/POSCAR`,
      kpointsContent: kpoints,
      files: { ...base.files, INCAR: true, POSCAR: true, KPOINTS: true },
    };
    setWorkspaces((prev) => ({ ...prev, [genTask.task_id]: ws }));
    setGenerating(false);
    setGenTask(null);
    message.success(`输入文件已生成：${genTask.model_name}`);
  };

  /** 远端文件写入/生成成功后：刷新该任务本地文件清单与就绪标记
   *（vasp.lsf / POSCAR / POTCAR 等由后端同步到本地镜像 files/） */
  const handleRemoteFilesChanged = async (task?: Task | null) => {
    const t = task ?? selectedTask;
    if (!t) return;
    try {
      const files = await fetchTaskFiles(t.task_id);
      setTaskFileList((prev) => ({ ...prev, [t.task_id]: files }));
      const names = new Set(files.map((f) => f.name));
      const base = workspaces[t.task_id] ?? makeWorkspace(t);
      patchWorkspace(t.task_id, {
        files: {
          ...base.files,
          INCAR: names.has('INCAR'),
          KPOINTS: names.has('KPOINTS'),
          POSCAR: names.has('POSCAR'),
          CONTCAR: names.has('CONTCAR'),
          POTCAR: names.has('POTCAR'),
          'vasp.lsf': names.has('vasp.lsf'),
          'submit.sh': names.has('submit.sh'),
        },
      });
      const entry = files.find((f) => f.name === 'vasp.lsf');
      if (entry) upsertLocalFile(t.task_id, 'vasp.lsf', entry.size);
    } catch (err) {
      message.warning(
        err instanceof Error ? `刷新本地文件清单失败：${err.message}` : '刷新本地文件清单失败',
      );
    }
  };

  /** 单个任务的详情标签页（概览/POSCAR/INCAR/KPOINTS/提交脚本） */
  const renderTaskDetail = (task: Task) => {
    const ws = workspaces[task.task_id] ?? makeWorkspace(task);
    // NEB 映像任务没有"单个输入结构"（结构是整条映像路径，见 NEB 组详情/巡检映像看板），
    // 因此不给它 POSCAR 标签页，避免显示无意义的空 POSCAR
    const showPoscar = task.task_type !== 'neb';
    return (
      <Tabs
        key={task.task_id}
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <TaskOverview
                task={task}
                workspace={ws}
                input={inputStates[task.task_id] ?? null}
                onGenerateInputs={() => setGenTask(task)}
                onContinuation={() => setContinuationTask(task)}
                onSubmitScript={() => setActiveTab('submit')}
                onSubmit={handleSubmitTask}
                submitting={submittingTaskId === task.task_id}
                onStop={handleStopTask}
                stopping={stoppingTaskId === task.task_id}
                onBuildEle={setEleBuildTask}
                onArchive={(t) => void handleArchiveTask(t)}
                onUnarchive={(t) => void handleUnarchiveTask(t)}
                onRename={(t) => {
                  setRenameTaskState(t);
                  setRenameName(t.model_name);
                }}
                onDelete={(t) => void handleDeleteTask(t)}
              />
            ),
          },
          ...(showPoscar
            ? [
                {
                  key: 'poscar',
                  label: 'POSCAR',
                  children: (
                    <div className="job-panel">
                      <InputSourceBanner
                        input={inputStates[task.task_id] ?? null}
                        syncing={inputSyncing === task.task_id}
                        onSync={() => void handleSyncInput(task)}
                        onRevertChange={(c) => void handleRevertChange(task, c)}
                        onRevertFiles={(files) => void handleRevertDraft(task, files)}
                      />
                      <PoscarPanel
                        key={task.task_id}
                        taskId={task.task_id}
                        poscarContent={ws.poscarContent}
                        poscarPath={ws.poscarPath}
                        copyTargets={copyTargets}
                        copyDefaultProjectId={selectedProjectId ?? undefined}
                        input={inputStates[task.task_id] ?? null}
                        onRemoteChanged={() => void handleRemoteFilesChanged(task)}
                        onStatePushed={(state) => applyInputState(task, state)}
                        onPoscarGenerated={(text, state) => {
                          patchWorkspace(task.task_id, { poscarContent: text });
                          applyInputState(task, state);
                          void handleRemoteFilesChanged(task);
                        }}
                        onImport={(c) => handleImportPoscar(c, task)}
                        onCopyFromTask={(sid) => handleCopyPoscar(sid, task)}
                      />
                    </div>
                  ),
                },
              ]
            : []),
          {
            key: 'incar',
            label: 'INCAR',
            children: (
              <div className="job-panel">
                <InputSourceBanner
                  input={inputStates[task.task_id] ?? null}
                  syncing={inputSyncing === task.task_id}
                  onSync={() => void handleSyncInput(task)}
                  onRevertChange={(c) => void handleRevertChange(task, c)}
                  onRevertFiles={(files) => void handleRevertDraft(task, files)}
                />
                <IncarEditor
                  key={task.task_id}
                  task={task}
                  workspace={ws}
                  presets={presets}
                  onParamsChange={(p, prec) => handleParamsChange(p, prec, task)}
                  onApplyPreset={(pr) => handleApplyPreset(pr, task)}
                  onSavePreset={(n) => handleSavePreset(n, task)}
                  onDeletePreset={handleDeletePreset}
                  onCopyToOthers={() => {
                    // 组页面（自由能结构 / NEB 组）里 selectedTask 是 null，来源作业必须显式记住
                    setCopyParamsSource(task);
                    setCopyParamsOpen(true);
                  }}
                  snapshotParams={ws.snapshotParams ?? {}}
                  pendingKeys={Object.keys(inputStates[task.task_id]?.draft?.INCAR ?? {})}
                  onConfirmParams={(p) => void handleConfirmParams(task, p)}
                  onResetToSnapshot={() => handleResetParams(task)}
                  onStatePushed={(state) => applyInputState(task, state)}
                />
              </div>
            ),
          },
          {
            key: 'kpoints',
            label: 'KPOINTS',
            children: (
              <div className="job-panel">
                <InputSourceBanner
                  input={inputStates[task.task_id] ?? null}
                  syncing={inputSyncing === task.task_id}
                  onSync={() => void handleSyncInput(task)}
                  onRevertChange={(c) => void handleRevertChange(task, c)}
                  onRevertFiles={(files) => void handleRevertDraft(task, files)}
                />
                <KpointsPanel
                  key={task.task_id}
                  taskId={task.task_id}
                  taskName={task.model_name}
                  poscarContent={ws.poscarContent}
                  kpointsContent={ws.kpointsContent}
                  input={inputStates[task.task_id] ?? null}
                  onGenerate={(c) => handleGenerateKpoints(c, task)}
                  onConfirmMesh={async (mesh) => {
                    try {
                      const state = await saveTaskInputDraft(task.task_id, {
                        file: 'KPOINTS',
                        mesh,
                      });
                      setInputStates((prev) => ({ ...prev, [task.task_id]: state }));
                      message.success(
                        `k 网格已记为待生效修改（${mesh.join(' × ')}），将在下次续算时应用`,
                      );
                    } catch (err) {
                      message.error(err instanceof Error ? err.message : '保存 k 网格修改失败');
                    }
                  }}
                  onStatePushed={(state) => applyInputState(task, state)}
                />
              </div>
            ),
          },
          {
            key: 'submit',
            label: '提交脚本',
            children: (
              <SubmitScriptPanel
                task={task}
                snapshot={clusterSnapshot}
                loading={snapshotLoading}
                onRefresh={() => void loadClusterSnapshot(true)}
                onWritten={() => void handleRemoteFilesChanged(task)}
              />
            ),
          },
        ]}
      />
    );
  };

  return (
    <PageTransition>
      <PageHeader
        title="作业管理"
        subtitle="管理项目子项、VASP 输入文件、续算流程与提交脚本生成"
        extra={
          <Space wrap>
            <Button
              icon={<ApartmentOutlined />}
              disabled={!selectedProject}
              onClick={() => setGroupWizardOpen(true)}
            >
              新建自由能组 / NEB 组
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!selectedProject}
              onClick={() => openNewTask(selectedProjectId)}
            >
              新建子项
            </Button>
          </Space>
        }
      />

      <div className="jobs-grid">
        <Card
          title="项目与子项"
          loading={loading}
          extra={
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setAddProjectOpen(true)}
            >
              新建项目
            </Button>
          }
        >
          {projects.length === 0 && !loading ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无项目数据"
            >
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => window.location.reload()}
              >
                重新加载
              </Button>
            </Empty>
          ) : (
            <JobsTree
              projects={projects}
              selectedProjectId={selectedProjectId}
              selectedTaskId={selectedTaskId}
              selectedStructureKey={selectedStructureKey}
              selectedNebGroupKey={selectedNebGroupKey}
              onSelectProject={selectProject}
              onSelectTask={handleSelectTask}
              onSelectStructure={handleSelectStructure}
              onSelectGroup={handleSelectGroup}
              onNewTask={(projectId, type) => openNewTask(projectId, type)}
              onNewGroup={(projectId, kind) => openNewGroup(projectId, kind)}
              onAddStructure={(projectId, groupId) => {
                setSelectedProjectId(projectId);
                setAddStructGroup(groupId);
              }}
            />
          )}
        </Card>

        <div>
          {selectedStructure ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 14 }}
                message={
                  <span>
                    自由能路径 · <strong>{formatStructureLabel(selectedStructure.label)}</strong>
                    <span className="preview-note" style={{ marginLeft: 12 }}>
                      {selectedStructure.projectName} · 结构优化 + 频率矫正合并页面
                    </span>
                  </span>
                }
              />
              <Card className="job-detail-card">
                <StructureDetail
                  structureLabel={formatStructureLabel(selectedStructure.label)}
                  optTask={selectedStructure.opt!}
                  fracTask={selectedStructure.frac}
                  renderTask={renderTaskDetail}
                  onCreateFrac={handleCreateFrac}
                  fracCreating={fracCreatingId === selectedStructure.opt!.task_id}
                />
              </Card>
            </>
          ) : selectedNebGroup ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 14 }}
                message={
                  <span>
                    NEB 流程组 · <strong>{selectedNebGroup.gid}</strong>
                    <span className="preview-note" style={{ marginLeft: 12 }}>
                      {selectedNebGroup.projectName} · 初态 / 末态 / NEB 映像合并页面
                    </span>
                  </span>
                }
              />
              <Card className="job-detail-card">
                <NebGroupDetail
                  groupName={selectedNebGroup.gid}
                  initialTask={selectedNebGroup.initial}
                  finalTask={selectedNebGroup.final}
                  nebTask={selectedNebGroup.neb}
                  renderTask={renderTaskDetail}
                  onCreateNebFiles={setNebBuildTask}
                  activeKey={nebActiveTab}
                  onActiveKeyChange={setNebActiveTab}
                />
              </Card>
            </>
          ) : selectedTask && selectedWorkspace ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 14 }}
                message={
                  <span>
                    当前子项：<strong>{selectedTask.model_name}</strong>
                    <span className="preview-note" style={{ marginLeft: 12 }}>
                      本地 {selectedTask.local_dir}/files · 远程 {selectedTask.remote_dir}
                    </span>
                  </span>
                }
              />
              <Card className="job-detail-card">
                {renderTaskDetail(selectedTask)}
              </Card>
            </>
          ) : (
            <Card>
              <Empty
                description={
                  selectedProject
                    ? '该项目下暂无子项，点击「新建子项」创建'
                    : '请选择左侧项目与子项'
                }
              />
            </Card>
          )}
        </div>
      </div>

      <NewTaskModal
        key={newTaskType}
        open={newTaskOpen}
        project={selectedProject}
        taskTypes={taskTypes}
        initialType={newTaskType}
        onCancel={closeNewTask}
        onCreate={handleCreateTask}
      />

      <AddProjectModal
        open={addProjectOpen}
        onCancel={() => setAddProjectOpen(false)}
        onCreated={() => void refreshProjects()}
      />

      <Modal
        title={`重命名子项 · ${renameTaskState?.model_name ?? ''}`}
        open={!!renameTaskState}
        onCancel={() => {
          setRenameTaskState(null);
          setRenameName('');
        }}
        onOk={() => void handleRenameTask()}
        okText="重命名"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginTop: 8 }}>
          <Input
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            placeholder="新的子项名称"
            onPressEnter={() => void handleRenameTask()}
          />
          <div className="preview-note" style={{ marginTop: 8 }}>
            重命名将同步更新本地目录、远程目录与数据库（仅独立任务支持）。
          </div>
        </div>
      </Modal>

      <Modal
        title="添加结构（自由能路径）"
        open={!!addStructGroup}
        onCancel={() => {
          setAddStructGroup(null);
          setAddStructCount(1);
        }}
        onOk={() => void handleAddStructure()}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginTop: 8 }}>
          <div className="preview-note" style={{ marginBottom: 8 }}>
            自动生成 结构N+1 的 结构优化(opt) + 频率矫正(frac) 任务与目录
          </div>
          <InputNumber
            min={1}
            max={20}
            value={addStructCount}
            onChange={(v) => setAddStructCount(v ?? 1)}
            addonAfter="个结构"
          />
        </div>
      </Modal>

      <GroupWizardModal
        key={groupWizardKind}
        open={groupWizardOpen}
        project={selectedProject}
        initialKind={groupWizardKind}
        onCancel={() => setGroupWizardOpen(false)}
        onCreated={() => void handleGroupCreated()}
      />

      <ContinuationModal
        open={!!continuationTask}
        task={continuationTask}
        onCancel={() => setContinuationTask(null)}
        onSameTypeCreated={(r) => void handleSameTypeCreated(r)}
      />

      <EleInputModal
        open={!!eleBuildTask}
        project={selectedProject}
        task={eleBuildTask}
        onCancel={() => setEleBuildTask(null)}
        onCreated={() => void refreshProjects()}
      />

      <NebFilesModal
        open={!!nebBuildTask}
        project={selectedProject}
        nebTask={nebBuildTask}
        onCancel={() => setNebBuildTask(null)}
        onCreated={() => void refreshProjects()}
      />

      <TaskPickerModal
        open={copyParamsOpen}
        mode="multiple"
        title="复制 INCAR 参数到其他作业"
        targets={copyTargets.filter((t) => t.taskId !== copyParamsSource?.task_id)}
        defaultExpandedIds={selectedProjectId ? [selectedProjectId] : []}
        hint={
          '只写"待生效修改"（不碰任何远端文件）：目标作业下次续算时写入，也可在目标作业上点「同步到远端」立即生效'
        }
        okText={(n) => `记为 ${n} 个作业的待生效修改`}
        onCancel={() => {
          setCopyParamsOpen(false);
          setCopyParamsSource(null);
        }}
        onConfirm={(ids) => {
          const picked = new Set(ids);
          void handleCopyParams(copyTargets.filter((t) => picked.has(t.taskId)));
        }}
      />

      <Modal
        title={`生成输入文件 · ${genTask?.model_name ?? ''}`}
        open={!!genTask}
        onCancel={() => !generating && setGenTask(null)}
        onOk={handleGenerateInputs}
        okText={generating ? '生成中…' : '生成'}
        cancelText="取消"
        confirmLoading={generating}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="文件写入本地任务目录"
          description="INCAR / POSCAR / KPOINTS 将真实写入本地 files/ 目录；POTCAR 需后端按 POSCAR 元素拼接伪势（待接入 pymatgen），不会在本次生成。"
        />
        <div className="file-gen-list">
          {INPUT_FILES.map((f) => (
            <div key={f} className="file-gen-item">
              <FileTextOutlined style={{ color: 'var(--color-primary)' }} />
              {f}
              <span>→ {genTask?.local_dir}/files/{f}</span>
            </div>
          ))}
        </div>
      </Modal>
    </PageTransition>
  );
}
