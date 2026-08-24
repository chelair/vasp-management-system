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
