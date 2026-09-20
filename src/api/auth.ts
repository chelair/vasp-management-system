/**
 * 认证接口封装（v0.9.0 第 2 步）。
 *
 * 登录返回的 token 由 `client.ts` 统一注入到后续请求头；这里只管接口本身。
 */
import { request } from './client';

export interface AuthUser {
  user_id: string;
  username: string;
  role: 'admin' | 'user' | 'agent' | string;
  enabled: boolean;
  created_at?: string;
}

export interface AuthSessionInfo {
  session_id: string;
  name?: string | null;
  kind?: 'session' | 'token' | string;
  created_at?: string;
  last_seen?: string;
  /** null = 永不过期（长期 token） */
  expires_at?: string | null;
}

export interface LoginResult {
  token: string;
  expires_at: string | null;
  user: AuthUser;
  session: AuthSessionInfo;
}

export interface MeResult {
  user: AuthUser;
  session: AuthSessionInfo;
  is_admin: boolean;
}

export interface TokenRow extends AuthSessionInfo {
  user_id: string;
  username: string;
  role?: string;
  created_by?: string | null;
  token_hash?: string;
  current?: boolean;
}

/** 登录：用户名 + 密码换 token（后端失败限速 5 次 / 15 分钟） */
export function login(username: string, password: string, name = 'web'): Promise<LoginResult> {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, name }),
  });
}

/** 退出登录：删除当前会话（旧 token 立即失效） */
export function logout(): Promise<{ revoked: boolean }> {
  return request('/auth/logout', { method: 'POST' });
}

/** 当前用户（前端启动时校验登录态） */
export function fetchMe(): Promise<MeResult> {
  return request('/auth/me');
}

/** 签发长期 token（仅 admin）：给脚本 / 智能体用 */
export function createToken(payload: {
  username?: string;
  user_id?: string;
  name?: string;
  /** 有效天数；不传 = 长期有效（可随时吊销） */
  expires_days?: number;
}): Promise<{ token: string; user: AuthUser; session: AuthSessionInfo; expires_at: string | null }> {
  return request('/auth/tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/** 列出 token / 会话：admin 看全部，其他用户只看自己的 */
export function listTokens(): Promise<{ tokens: TokenRow[]; is_admin: boolean }> {
  return request('/auth/tokens');
}

/** 吊销指定 token */
export function deleteToken(tokenId: string): Promise<{ revoked: boolean; session_id: string }> {
  return request(`/auth/tokens/${encodeURIComponent(tokenId)}`, { method: 'DELETE' });
}
