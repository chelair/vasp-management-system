/**
 * 统一数据访问层：请求后端 `/api/**`，统一信封 `{success, message, data}`。
 *
 * 认证（v0.9.0 第 2 步）：
 * - 所有请求自动带 `Authorization: Bearer <token>`（token 存在 localStorage）；
 * - 收到 401 → 清 token 并跳转 `/login?from=...`（登录接口自身除外，避免死循环）。
 */
export const MOCK_DELAY = 600;

/** token 在 localStorage 中的键（前端唯一来源；后端只存 sha256） */
export const TOKEN_STORAGE_KEY = 'vasp.auth.token';

export function wait(ms: number = MOCK_DELAY): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // localStorage 不可用时仅当前会话有效
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // 忽略
  }
}

/** 跳转登录页（带上返回地址）；已在登录页时不动，避免循环 */
function redirectToLogin(): void {
  if (typeof window === 'undefined') return;
  const { pathname, search } = window.location;
  if (pathname === '/login') return;
  const from = encodeURIComponent(`${pathname}${search}`);
  window.location.assign(`/login?from=${from}`);
}

/**
 * 统一请求后端：返回统一信封 {success, message, data}。
 * 后端未启动时抛出友好错误（fetch 网络异常）。
 */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  const token = getToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (typeof init?.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new Error('无法连接后端服务：请先在项目目录运行 npm run server（端口 3001）');
  }
  const body = await res.json().catch(() => null);
  if (res.status === 401) {
    // 登录接口的 401 是"用户名或密码错误"：交给登录页提示，
    // **不动已有登录态**（否则已登录用户在登录页试错密码会被登出）
    if (!path.startsWith('/auth/login')) {
      clearToken();
      redirectToLogin();
    }
    throw new Error(body?.message ?? '未登录或登录已过期，请重新登录');
  }
  if (!res.ok || !body || body.success === false) {
    const detail: string[] | undefined = body?.data?.errors;
    const message = detail?.length
      ? detail.join('；')
      : (body?.message ?? `请求失败（HTTP ${res.status}）`);
    throw new Error(message);
  }
  return body.data as T;
}
