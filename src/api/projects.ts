import { wait } from './client';
import { mockDashboardMeta, mockWeeklyTrend } from '../data/mock/projects';
import type {
  CreateProjectPayload,
  CreateProjectResult,
  DashboardMeta,
  Project,
  ServerOption,
  TaskTypeOption,
  TrendPoint,
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
      { type: 'structure_opt', description: '结构优化', workload_weight: 1 },
      { type: 'electronic_structure', description: '电子结构计算', workload_weight: 0.4 },
      { type: 'free_energy', description: '自由能计算', workload_weight: 1.2 },
      { type: 'frequency', description: '频率计算', workload_weight: 1 },
      { type: 'neb', description: '反应路径/过渡态搜索 (NEB)', workload_weight: 5 },
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

/** 获取仪表盘汇总信息（Mock） */
export async function fetchDashboardMeta(): Promise<DashboardMeta> {
  await wait(500);
  return mockDashboardMeta;
}

/** 获取近 7 天运行任务趋势（Mock） */
export async function fetchWeeklyTrend(): Promise<TrendPoint[]> {
  await wait(450);
  return mockWeeklyTrend;
}
