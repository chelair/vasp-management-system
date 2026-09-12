import { wait } from './client';
import type {
  CreateProjectPayload,
  CreateProjectResult,
  Project,
  ServerOption,
  TaskTypeOption,
} from '../types';

/**
 * 统一请求后端：返回统一信封 {success, message, data}。
 * 后端未启动时抛出友好错误（fetch 网络异常）。
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new Error('无法连接后端服务：请先在项目目录运行 npm run server（端口 3001）');
  }
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || body.success === false) {
    const detail: string[] | undefined = body?.data?.errors;
    const message = detail?.length
      ? detail.join('；')
      : (body?.message ?? `请求失败（HTTP ${res.status}）`);
    throw new Error(message);
  }
  return body.data as T;
}

/** 获取项目列表（数据以真实后端为准；后端不可用时返回空列表） */
export async function fetchProjects(): Promise<Project[]> {
  try {
    const data = await request<{ projects: Project[] }>('/projects');
    return data.projects;
  } catch (err) {
    console.warn('[api] 后端不可用，项目列表为空：', err);
    return [];
  }
}

/** 服务器下拉选项 */
export async function fetchServers(): Promise<ServerOption[]> {
  try {
    const data = await request<{ servers: ServerOption[] }>('/servers');
    return data.servers;
  } catch {
    await wait(250);
    return [
      {
        name: 'server1',
        host: 'hpc.xmu.edu.cn',
        port: 22,
        user: 'mdye',
        queue_system: 'lsf',
        home: '/data/gpfs03/mdye',
        remote_base: '/data/gpfs03/mdye/projects/test',
      },
    ];
  }
}

/** 任务类型下拉选项 */
export async function fetchTaskTypes(): Promise<TaskTypeOption[]> {
  try {
    const data = await request<{ task_types: TaskTypeOption[] }>('/task-types');
    return data.task_types;
  } catch {
    await wait(250);
    return [
      { type: 'opt', description: '结构优化', workload_weight: 1, subtypes: [], subtype_labels: {} },
      {
        type: 'frac',
        description: '频率矫正（自由能）',
        workload_weight: 1,
        subtypes: [],
        subtype_labels: {},
      },
      {
        type: 'neb',
        description: 'NEB 过渡态',
        workload_weight: 5,
        subtypes: [],
        subtype_labels: {},
      },
      {
        type: 'ele',
        description: '电子结构/后处理',
        workload_weight: 0.4,
        subtypes: ['pdos', 'bader', 'diff_charge', 'work_function'],
        subtype_labels: {
          pdos: 'PDOS',
          bader: 'Bader 分析',
          diff_charge: '差分电荷',
          work_function: '功函数',
        },
      },
    ];
  }
}

/** 新增项目（需要后端；错误信息直接透出后端校验结果） */
export async function createProject(
  payload: CreateProjectPayload,
): Promise<CreateProjectResult> {
  return request<CreateProjectResult>('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'add_project', project: payload }),
  });
}

/** 删除项目（本地目录移入回收站，远端目录不删除） */
export async function deleteProject(projectId: string): Promise<{
  project_id: string;
  project_name: string;
  local_trash: string | null;
}> {
  return request(`/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' });
}

/** 关闭项目：前提是项目下可见任务全部已关闭（归档） */
export async function closeProject(projectId: string): Promise<{
  project_id: string;
  project_name: string;
}> {
  return request(`/projects/${encodeURIComponent(projectId)}/close`, { method: 'POST' });
}

/** 重新打开项目（清除 closed 标记，任务状态不变） */
export async function reopenProject(projectId: string): Promise<{
  project_id: string;
  project_name: string;
}> {
  return request(`/projects/${encodeURIComponent(projectId)}/reopen`, { method: 'POST' });
}
