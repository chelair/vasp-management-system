import type { DashboardMeta, TrendPoint } from '../../types';

export const mockDashboardMeta: DashboardMeta = {
  todayCompleted: 8,
  anomalyCount: 3,
};

export const mockWeeklyTrend: TrendPoint[] = [
  { date: '08-18', value: 5 },
  { date: '08-19', value: 7 },
  { date: '08-20', value: 6 },
  { date: '08-21', value: 9 },
  { date: '08-22', value: 8 },
  { date: '08-23', value: 11 },
  { date: '08-24', value: 10 },
];
