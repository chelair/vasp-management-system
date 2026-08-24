import { wait } from './client';
import { mockServerConfigs } from '../data/mock/servers';
import type { ConnectionTestResult, ServerConfig } from '../types';

/**
 * SSH 服务器配置数据访问层。
 * - 配置（含"项目远程根目录"）读写后端 data/config/servers.json（GET/PUT /api/ssh/config）
 * - 连接/延迟等 UI 状态保存在 localStorage
 * - 后端不可用时回退到本地缓存 / Mock（仅预览，配置变更不持久化到后端）
 */
const UI_STORAGE_KEY = 'vasp.ssh.servers.v1';

/** 后端 servers.json 条目（字段与 config/servers.json 对齐） */
interface BackendServerEntry {
  name: string;
  host: string;
  port?: number;
  user: string;
  auth_type?: 'key' | 'password';
  key_path?: string | null;
  password?: string | null;
  home?: string | null;
  queue_system?: string | null;
  remote_base?: string | null;
}

function fromBackend(entry: BackendServerEntry): ServerConfig {
  return {
    id: entry.name,
    name: entry.name,
    host: entry.host,
    port: entry.port ?? 22,
    user: entry.user,
    authType: entry.key_path ? 'key' : 'password',
    keyPath: entry.key_path ?? undefined,
    password: entry.password ?? undefined,
    home: entry.home ?? undefined,
    queueSystem: entry.queue_system ?? 'lsf',
    remoteBase: entry.remote_base ?? undefined,
    connected: false,
    latencyMs: null,
    lastTestAt: null,
  };
}

function toBackend(cfg: ServerConfig): BackendServerEntry {
  return {
    name: cfg.name,
    host: cfg.host,
    port: cfg.port,
    user: cfg.user,
    auth_type: cfg.authType,
    key_path: cfg.authType === 'key' ? (cfg.keyPath ?? null) : null,
    password: cfg.authType === 'password' ? (cfg.password ?? null) : null,
    home: cfg.home ?? null,
    queue_system: cfg.queueSystem,
    remote_base: cfg.remoteBase ?? null,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new Error('无法连接后端服务');
  }
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || body.success === false) {
    throw new Error(body?.message ?? `请求失败（HTTP ${res.status}）`);
  }
  return body.data as T;
}

/** 读取本地 UI 状态缓存（连接/延迟/测试时间） */
export function readUICache(): ServerConfig[] | null {
  try {
    const raw = localStorage.getItem(UI_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ServerConfig[];
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {
    // 缓存损坏时忽略
  }
  return null;
}

/** 保存本地 UI 状态缓存 */
export function persistUICache(servers: ServerConfig[]): void {
  try {
    localStorage.setItem(UI_STORAGE_KEY, JSON.stringify(servers));
  } catch {
    // localStorage 不可用时静默失败
  }
}

export interface ServerConfigsResult {
  servers: ServerConfig[];
  source: 'backend' | 'local';
}

/** 获取服务器配置：优先后端，失败回退本地缓存/Mock */
export async function fetchServerConfigs(): Promise<ServerConfigsResult> {
  try {
    const data = await request<{ servers: BackendServerEntry[] }>('/ssh/config');
    return { servers: data.servers.map(fromBackend), source: 'backend' };
  } catch {
    await wait(300);
    return { servers: readUICache() ?? mockServerConfigs, source: 'local' };
  }
}

/** 将服务器配置同步到后端 data/config/servers.json（仅配置字段，不含连接状态） */
export async function syncServerConfigs(servers: ServerConfig[]): Promise<void> {
  try {
    await request('/ssh/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ servers: servers.map(toBackend) }),
    });
  } catch (err) {
    console.warn('[api] SSH 配置同步到后端失败（保持本地模式）：', err);
  }
}

/**
 * 测试 SSH 连接（演示：模拟握手）。
 * 正式版替换为后端 /api/ssh/test，由后端使用 Paramiko 发起真实连接。
 */
export async function testRemoteConnection(
  cfg: Pick<
    ServerConfig,
    'host' | 'port' | 'user' | 'authType' | 'keyPath' | 'password'
  >,
): Promise<ConnectionTestResult> {
  if (cfg.authType === 'key' && !cfg.keyPath?.trim()) {
    return { ok: false, latencyMs: 0, message: '认证方式为密钥文件，但私钥路径为空' };
  }
  if (cfg.authType === 'password' && !cfg.password?.trim()) {
    return { ok: false, latencyMs: 0, message: '认证方式为密码，但密码为空' };
  }
  await wait(1100);
  const latencyMs = Math.round(60 + Math.random() * 180);
  return {
    ok: true,
    latencyMs,
    message: `SSH 握手成功：${cfg.user}@${cfg.host}:${cfg.port}（演示）`,
  };
}
