import { request } from './client';

export interface RootPaths {
  local_root: string;
  remote_roots: Record<string, string>;
}

/** 读取本地/远端项目根目录配置 */
export async function fetchRootPaths(): Promise<RootPaths> {
  return request('/settings/root-paths');
}

/** 修改项目根目录（任务路径保持相对，无需改动） */
export async function saveRootPaths(payload: {
  local_root?: string;
  remote_roots?: Record<string, string>;
}): Promise<RootPaths> {
  return request('/settings/root-paths', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
