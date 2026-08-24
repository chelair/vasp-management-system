import { wait } from './client';
import { mockReports } from '../data/mock/reports';
import type { ReportRecord } from '../types';
import { formatDateTime } from '../utils/format';

/** 获取报告历史记录 */
export async function fetchReports(): Promise<ReportRecord[]> {
  await wait(650);
  return mockReports;
}

/** 生成一份新的智能报告（演示：延迟后返回模拟内容） */
export async function generateReport(): Promise<ReportRecord> {
  await wait(1800);
  const now = new Date();
  return {
    id: `r-${Date.now()}`,
    title: `即时报告 · ${formatDateTime(now)}`,
    generated_at: formatDateTime(now),
    status: 'completed',
    summary:
      '本报告由演示数据自动生成：当前共 5 个项目、11 个子任务，其中 3 个运行中、2 个异常、2 个排队中。巡检共发现 2 项警告、2 项错误，建议优先处理异常退出的 Ag 项目任务。',
    risks: [
      {
        level: 'high',
        content:
          'Ag_20260830 / Al2O3_Ag 异常退出且距截止日期仅 6 天，若不恢复续算将影响整体交付。',
      },
      {
        level: 'medium',
        content: '服务器磁盘占用 82%，未来一周存在写入失败风险。',
      },
      {
        level: 'low',
        content: 'LiSi_20260910 的 NEB 任务排队时间较长，进度可能滞后。',
      },
    ],
    suggestions: [
      '执行续算流程恢复 Ag_20260830 / Al2O3_Ag 任务，并在完成后自动触发下游电子结构计算',
      '为 SCF 未收敛任务调整收敛参数后重新提交',
      '清理已完成项目的中间文件，释放至少 50GB 磁盘空间',
      '调整 NEB 任务优先级，缩短排队等待时间',
    ],
  };
}
