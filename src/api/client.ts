/**
 * 统一数据访问层（演示阶段）。
 *
 * 当前所有接口返回 Mock 数据并模拟网络延迟；
 * 后续接入真实后端（Express / FastAPI）时，只需把各 api/*.ts
 * 内部实现替换为 fetch('/api/...')，页面代码无需改动。
 */
export const MOCK_DELAY = 600;

export function wait(ms: number = MOCK_DELAY): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * 统一请求后端：返回统一信封 {success, message, data}。
 * 后端未启动时抛出友好错误（fetch 网络异常）。
 */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
