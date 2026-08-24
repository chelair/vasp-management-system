import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, App, Button, Card, Empty, Modal, Tabs } from 'antd';
import { FileTextOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { fetchProjects, fetchTaskTypes } from '../api/projects';
import {
  deleteIncarPreset,
  fetchClusterSnapshot,
  fetchTaskFile,
  fetchTaskFiles,
  loadIncarPresets,
  saveIncarPreset,
  saveTaskFile,
} from '../api/jobs';
import type { TaskFileEntry } from '../api/jobs';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';
import JobsTree from '../components/jobs/JobsTree';
import NewTaskModal from '../components/jobs/NewTaskModal';
import TaskOverview from '../components/jobs/TaskOverview';
import PoscarPanel from '../components/jobs/PoscarPanel';
import IncarEditor from '../components/jobs/IncarEditor';
import KpointsPanel from '../components/jobs/KpointsPanel';
import SubmitScriptPanel from '../components/jobs/SubmitScriptPanel';
import ContinuationModal from '../components/jobs/ContinuationModal';
import CopyParamsModal from '../components/jobs/CopyParamsModal';
import {
  buildDefaultParams,
  buildIncarText,
  parseIncarContent,
} from '../data/mock/incar';
import { buildInputFiles } from '../data/mock/vaspFiles';
import type {
  ContinuationPayload,
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

const INPUT_FILES = ['INCAR', 'POSCAR', 'KPOINTS', 'POTCAR'];

function defaultTaskFor(taskId: string): Task {
  return {
    task_id: taskId,
    task_type: 'structure_opt',
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
  const [clusterSnapshot, setClusterSnapshot] = useState<ClusterSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [presets, setPresets] = useState<IncarPreset[]>(() => loadIncarPresets());
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [continuationTask, setContinuationTask] = useState<Task | null>(null);
  const [copyParamsOpen, setCopyParamsOpen] = useState(false);
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

  /** 选中子项时，自动读取本地目录中已有的 POSCAR / INCAR / KPOINTS */
  useEffect(() => {
    if (!selectedTask) return;
    const taskId = selectedTask.task_id;
    if (loadedDisk[taskId]) return;
    const names = new Set((taskFileList[taskId] ?? []).map((f) => f.name));
    if (!names.has('POSCAR') && !names.has('INCAR') && !names.has('KPOINTS')) return;
    setLoadedDisk((prev) => ({ ...prev, [taskId]: true }));
    void (async () => {
      const patch: Partial<JobWorkspace> = {};
      if (names.has('POSCAR')) {
        try {
          const { content } = await fetchTaskFile(taskId, 'POSCAR');
          patch.poscarContent = content;
          patch.poscarPath = `${selectedTask.local_dir}/files/POSCAR`;
        } catch {
          // 读取失败时保持空状态，用户可手动导入
        }
      }
      if (names.has('KPOINTS')) {
        try {
          const { content } = await fetchTaskFile(taskId, 'KPOINTS');
          patch.kpointsContent = content;
        } catch {
          // 忽略
        }
      }
      if (names.has('INCAR')) {
        try {
          const { content } = await fetchTaskFile(taskId, 'INCAR');
          const parsed = parseIncarContent(content);
          const base = workspaces[taskId] ?? makeWorkspace(selectedTask);
          patch.incarParams = { ...base.incarParams, ...parsed };
          patch.precision = 'custom';
        } catch {
          // 忽略
        }
      }
      setWorkspaces((prev) => ({
        ...prev,
        [taskId]: { ...(prev[taskId] ?? makeWorkspace(selectedTask)), ...patch },
      }));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTask?.task_id, taskFileList]);

  const patchWorkspace = (taskId: string, patch: Partial<JobWorkspace>) => {
    setWorkspaces((prev) => ({
      ...prev,
      [taskId]: { ...(prev[taskId] ?? makeWorkspace(defaultTaskFor(taskId))), ...patch },
    }));
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
  };

  const openNewTask = (projectId: string | null) => {
    if (!projectId) {
      message.warning('请先选择项目');
      return;
    }
    setSelectedProjectId(projectId);
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
    const task: Task = {
      task_id: `${selectedProject.id}_${payload.modelName}_${Date.now().toString(36)}`,
      task_type: payload.taskType,
      model_name: payload.modelName,
      status: 'pending',
      last_energy: null,
      last_check_time: null,
      job_id: null,
      notes: '本会话新建（演示）',
      continuation_ready: false,
      continuation_dir: null,
      remote_dir: payload.remoteDir,
      local_dir: payload.localDir,
    };
    setProjects((prev) =>
      prev.map((p) =>
        p.id === selectedProject.id ? { ...p, tasks: [...p.tasks, task] } : p,
      ),
    );
    setWorkspaces((prev) => ({ ...prev, [task.task_id]: makeWorkspace(task) }));
    setTaskFileList((prev) => ({ ...prev, [task.task_id]: [] }));
    setSelectedTaskId(task.task_id);
    setNewTaskOpen(false);
    message.success(`子项已创建：${payload.modelName}`);
  };

  const handleCreateContinuation = (payload: ContinuationPayload) => {
    if (!selectedProject || !continuationTask) return;
    const task: Task = {
      task_id: `${selectedProject.id}_${payload.name}_${Date.now().toString(36)}`,
      task_type: payload.taskType,
      model_name: payload.name,
      status: 'pending',
      last_energy: null,
      last_check_time: null,
      job_id: null,
      notes: `由 ${continuationTask.model_name} 续算创建`,
      continuation_ready: false,
      continuation_dir: null,
      remote_dir: payload.remoteDir,
      local_dir: payload.localDir,
    };
    const sourceWs = workspaces[continuationTask.task_id] ?? makeWorkspace(continuationTask);
    const poscar = sourceWs.poscarContent ?? buildInputFiles(continuationTask.model_name).POSCAR;
    const info = parsePoscar(poscar);
    const ws: JobWorkspace = {
      incarParams: buildDefaultParams(payload.taskType),
      precision: 'custom',
      poscarContent: poscar,
      poscarPath: `${payload.localDir}/files/POSCAR`,
      kpointsContent:
        info && sourceWs.kpointsContent
          ? sourceWs.kpointsContent
          : info
            ? buildKpoints(payload.name, 'Gamma', recommendKgrid(info.lengths, 20), 20)
            : null,
      files: {
        INCAR: true,
        POSCAR: true,
        KPOINTS: true,
        POTCAR: false,
        'submit.sh': false,
        CONTCAR: false,
        WAVECAR: false,
      },
      scriptFormat: 'lsf',
    };
    setProjects((prev) =>
      prev.map((p) =>
        p.id === selectedProject.id ? { ...p, tasks: [...p.tasks, task] } : p,
      ),
    );
    setWorkspaces((prev) => ({ ...prev, [task.task_id]: ws }));
    setTaskFileList((prev) => ({ ...prev, [task.task_id]: [] }));
    setSelectedTaskId(task.task_id);
    setContinuationTask(null);
    message.success(`续算子项已创建：${payload.name}`);
  };

  const handleParamsChange = (params: Record<string, string>, precision: PrecisionMode) => {
    if (!selectedTask) return;
    patchWorkspace(selectedTask.task_id, { incarParams: params, precision });
  };

  const handleApplyPreset = (preset: IncarPreset) => {
    if (!selectedTask) return;
    patchWorkspace(selectedTask.task_id, {
      incarParams: { ...preset.params },
      precision: 'custom',
    });
  };

  const handleSavePreset = (name: string) => {
    if (!selectedTask || !selectedWorkspace) return;
    saveIncarPreset(name, selectedWorkspace.incarParams);
    setPresets(loadIncarPresets());
    message.success(`预设已保存：${name}`);
  };

  const handleDeletePreset = (id: string) => {
    setPresets(deleteIncarPreset(id));
    message.success('预设已删除');
  };

  const handleCopyParams = (targets: TaskRef[]) => {
    if (!selectedTask || !selectedWorkspace) return;
    const params = { ...selectedWorkspace.incarParams };
    setWorkspaces((prev) => {
      const next = { ...prev };
      for (const t of targets) {
        const real = projects
          .flatMap((p) => p.tasks)
          .find((x) => x.task_id === t.taskId);
        const base = next[t.taskId] ?? makeWorkspace(real ?? defaultTaskFor(t.taskId));
        next[t.taskId] = { ...base, incarParams: params, precision: 'custom' };
      }
      return next;
    });
    setCopyParamsOpen(false);
    message.success(`INCAR 参数已同步到 ${targets.length} 个作业（会话内）`);
  };

  /** 导入 POSCAR：写入本地任务目录 files/POSCAR，并同步会话状态 */
  const handleImportPoscar = async (content: string) => {
    if (!selectedTask) return;
    const info = parsePoscar(content);
    let path = `${selectedTask.local_dir}/files/POSCAR`;
    try {
      const r = await saveTaskFile(selectedTask.task_id, 'POSCAR', content);
      path = r.path;
      upsertLocalFile(selectedTask.task_id, 'POSCAR', r.size);
      message.success(`POSCAR 已保存：${r.path}`);
    } catch (err) {
      message.warning(
        err instanceof Error
          ? `后端写入失败，仅更新当前会话：${err.message}`
          : '后端写入失败，仅更新当前会话',
      );
    }
    patchWorkspace(selectedTask.task_id, {
      poscarContent: content,
      poscarPath: path,
      kpointsContent: info
        ? buildKpoints(selectedTask.model_name, 'Gamma', recommendKgrid(info.lengths, 20), 20)
        : null,
    });
  };

  const handleCopyPoscar = (sourceTaskId: string) => {
    if (!selectedTask) return;
    const source = projects
      .flatMap((p) => p.tasks)
      .find((t) => t.task_id === sourceTaskId);
    if (!source) return;
    const content =
      workspaces[sourceTaskId]?.poscarContent ?? buildInputFiles(source.model_name).POSCAR;
    void handleImportPoscar(content);
  };

  const handleGenerateKpoints = async (content: string) => {
    if (!selectedTask) return;
    patchWorkspace(selectedTask.task_id, { kpointsContent: content });
    try {
      const r = await saveTaskFile(selectedTask.task_id, 'KPOINTS', content);
      upsertLocalFile(selectedTask.task_id, 'KPOINTS', r.size);
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

  /** 保存提交脚本到本地任务目录 files/submit.sh */
  const handleScriptSaved = async (script: string) => {
    if (!selectedTask) return;
    try {
      const r = await saveTaskFile(selectedTask.task_id, 'submit.sh', script);
      upsertLocalFile(selectedTask.task_id, 'submit.sh', r.size);
    } catch (err) {
      message.warning(
        err instanceof Error ? `提交脚本写入后端失败：${err.message}` : '提交脚本写入后端失败',
      );
    }
    const base = workspaces[selectedTask.task_id] ?? makeWorkspace(selectedTask);
    patchWorkspace(selectedTask.task_id, {
      files: { ...base.files, 'submit.sh': true },
    });
  };

  const tabItems = selectedTask && selectedWorkspace
    ? [
        {
          key: 'overview',
          label: '概览',
          children: (
            <TaskOverview
              task={selectedTask}
              workspace={selectedWorkspace}
              onGenerateInputs={() => setGenTask(selectedTask)}
              onContinuation={() => setContinuationTask(selectedTask)}
              onSubmitScript={() => setActiveTab('submit')}
            />
          ),
        },
        {
          key: 'poscar',
          label: 'POSCAR',
          children: (
            <PoscarPanel
              poscarContent={selectedWorkspace.poscarContent}
              poscarPath={selectedWorkspace.poscarPath}
              copyTargets={copyTargets}
              onImport={handleImportPoscar}
              onCopyFromTask={handleCopyPoscar}
            />
          ),
        },
        {
          key: 'incar',
          label: 'INCAR',
          children: (
            <IncarEditor
              task={selectedTask}
              workspace={selectedWorkspace}
              presets={presets}
              onParamsChange={handleParamsChange}
              onApplyPreset={handleApplyPreset}
              onSavePreset={handleSavePreset}
              onDeletePreset={handleDeletePreset}
              onCopyToOthers={() => setCopyParamsOpen(true)}
            />
          ),
        },
        {
          key: 'kpoints',
          label: 'KPOINTS',
          children: (
            <KpointsPanel
              taskName={selectedTask.model_name}
              poscarContent={selectedWorkspace.poscarContent}
              kpointsContent={selectedWorkspace.kpointsContent}
              onGenerate={handleGenerateKpoints}
            />
          ),
        },
        {
          key: 'submit',
          label: '提交脚本',
          children: (
            <SubmitScriptPanel
              task={selectedTask}
              workspace={selectedWorkspace}
              snapshot={clusterSnapshot}
              loading={snapshotLoading}
              onRefresh={() => void loadClusterSnapshot(true)}
              onSaved={handleScriptSaved}
            />
          ),
        },
      ]
    : [];

  return (
    <PageTransition>
      <PageHeader
        title="作业管理"
        subtitle="管理项目子项、VASP 输入文件、续算流程与提交脚本生成"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!selectedProject}
            onClick={() => openNewTask(selectedProjectId)}
          >
            新建子项
          </Button>
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
              disabled={!selectedProject}
              onClick={() => openNewTask(selectedProjectId)}
            >
              新建
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
              onSelectProject={selectProject}
              onSelectTask={setSelectedTaskId}
              onNewTask={(projectId) => openNewTask(projectId)}
            />
          )}
        </Card>

        <div>
          {selectedTask && selectedWorkspace ? (
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
                <Tabs
                  key={selectedTask.task_id}
                  activeKey={activeTab}
                  onChange={setActiveTab}
                  items={tabItems}
                />
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
        open={newTaskOpen}
        project={selectedProject}
        taskTypes={taskTypes}
        onCancel={closeNewTask}
        onCreate={handleCreateTask}
      />

      <ContinuationModal
        open={!!continuationTask}
        task={continuationTask}
        project={selectedProject}
        taskTypes={taskTypes}
        onCancel={() => setContinuationTask(null)}
        onConfirm={handleCreateContinuation}
      />

      <CopyParamsModal
        open={copyParamsOpen}
        targets={copyTargets}
        onCancel={() => setCopyParamsOpen(false)}
        onConfirm={handleCopyParams}
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
