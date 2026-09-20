import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchMe,
  login as loginApi,
  logout as logoutApi,
  type AuthSessionInfo,
  type AuthUser,
} from '../api/auth';
import { clearToken, getToken, setToken } from '../api/client';

interface AuthContextValue {
  user: AuthUser | null;
  session: AuthSessionInfo | null;
  isAdmin: boolean;
  /** 启动时的登录态校验是否完成（未完成前不要渲染受保护页面） */
  ready: boolean;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth 必须在 <AuthProvider> 内使用');
  return ctx;
}

/**
 * 登录态（v0.9.0 第 2 步）。
 *
 * - token 存 localStorage（`client.ts` 负责注入请求头与 401 跳转）；
 * - 启动时若本地有 token 就调 `/auth/me` 校验一次，失效则清掉；
 * - 提供 `login` / `logout` / `refresh` 给登录页与顶栏用户菜单用。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [session, setSession] = useState<AuthSessionInfo | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setSession(null);
      setReady(true);
      return;
    }
    try {
      const me = await fetchMe();
      setUser(me.user);
      setSession(me.session);
    } catch {
      // token 失效 / 后端不可用：清掉本地凭据，回到登录页
      clearToken();
      setUser(null);
      setSession(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const result = await loginApi(username, password);
    setToken(result.token);
    setUser(result.user);
    setSession(result.session);
    setReady(true);
    return result.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } catch {
      // 退出失败也要清本地（后端会话可能已过期）
    }
    clearToken();
    setUser(null);
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      isAdmin: user?.role === 'admin',
      ready,
      login,
      logout,
      refresh,
    }),
    [user, session, ready, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
