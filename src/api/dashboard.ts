import { request } from './client';
import type {
  DashboardClusterHealth,
  DashboardCoresUsage,
  DashboardOverview,
  DashboardRiskSummary,
  DashboardTrend,
} from '../types';

/**
 * 总览页数据接口。
 *
 * 后端 `GET /api/dashboard/overview` 一次返回整页数据（集群查询在服务端
 * 缓存 5 分钟），`refresh=1` 强制重新查询集群（SSH 约 2-4 秒）。
 * 其余接口用于局部刷新（核数 / 集群健康 / 风险 / 趋势）。
 */

/**
 * 总览数据。
 *
 * `cluster=false`（v0.9.33）时后端**完全不查 SSH**，只返回本地聚合（统计/风险/项目进度/
 * 最近任务/趋势），集群相关字段为空并带 `cluster.pending = true` —— 页面可以秒开，
 * 再用 `cluster=true` 单独加载 bjobs / blimits / bhosts 那部分。
 */
export async function fetchDashboardOverview(
  refresh = false,
  cluster = true,
): Promise<DashboardOverview> {
  const params = new URLSearchParams();
  if (refresh) params.set('refresh', '1');
  if (!cluster) params.set('cluster', '0');
  const query = params.toString();
  return request<DashboardOverview>(`/dashboard/overview${query ? `?${query}` : ''}`);
}

export async function fetchCoresUsage(refresh = false): Promise<DashboardCoresUsage> {
  return request<DashboardCoresUsage>(
    `/dashboard/cores-usage${refresh ? '?refresh=1' : ''}`,
  );
}

export async function fetchClusterHealth(
  refresh = false,
): Promise<DashboardClusterHealth> {
  return request<DashboardClusterHealth>(
    `/dashboard/cluster-health${refresh ? '?refresh=1' : ''}`,
  );
}

export async function fetchRiskAlerts(): Promise<DashboardRiskSummary> {
  return request<DashboardRiskSummary>('/dashboard/risk-alerts');
}

export async function fetchDashboardTrend(days = 7): Promise<DashboardTrend> {
  return request<DashboardTrend>(`/dashboard/trend?days=${days}`);
}
