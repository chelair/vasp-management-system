import type { ReportRecord } from '../../types';

export const mockReports: ReportRecord[] = [
  {
    id: 'r-20260823-210000',
    title: '周报 · 2026-08-17 ~ 2026-08-23',
    generated_at: '2026-08-23 21:00',
    status: 'completed',
    summary:
      '本周共 5 个项目、11 个子任务。2 个任务完成并归档，3 个任务运行中；巡检发现 2 项警告、2 项错误。Ag_20260830 的 Al2O3_Ag 结构优化异常退出，建议优先恢复；其余项目总体按计划推进。',
    risks: [
      {
        level: 'high',
        content:
          'Ag_20260830 / Al2O3_Ag 作业 777173 异常退出，距离截止日期 6 天，存在延期风险，建议今日内恢复并续算。',
      },
      {
        level: 'high',
        content:
          'Topo_Surf_20260905 表面态能带 SCF 连续振荡未收敛，持续占用节点资源。',
      },
      {
        level: 'medium',
        content: '服务器磁盘使用率达 82%，一周内可能影响新任务文件写入。',
      },
      {
        level: 'low',
        content: 'LiSi_20260910 的 NEB 任务排队超 6 小时，平均等待时间偏长。',
      },
    ],
    suggestions: [
      '对异常退出任务执行续算流程（CONTCAR -> POSCAR 后重新提交），并在恢复后开启完成通知',
      '为 SCF 未收敛任务调整 EDIFF/SIGMA 并切换到 ICHARG=1 初值后重新提交',
      '清理已完成项目的 WAVECAR/CHGCAR 中间文件，释放至少 50GB 磁盘空间',
      '调整排队 NEB 任务的作业优先级，缩短等待时间',
    ],
  },
  {
    id: 'r-20260820-143000',
    title: '专题报告 · Ag 催化剂界面项目进展',
    generated_at: '2026-08-20 14:30',
    status: 'completed',
    summary:
      'Ag_20260830 项目包含 3 个结构优化子任务与后续电子结构计算。当前 1 个任务异常退出、2 个任务待提交；已完成模型的基态能量提取正常，建议先恢复异常任务再批量推进其余构型。',
    risks: [
      {
        level: 'medium',
        content: '项目整体进度落后计划约 15%，若异常任务今日未恢复，剩余工作量当量将超过阈值。',
      },
      {
        level: 'low',
        content: 'P1_I2 已完成，但下游电子结构任务尚未创建，存在衔接空档。',
      },
    ],
    suggestions: [
      '优先恢复 Al2O3_Ag 结构优化（预计耗时 8h），避免阻塞后续任务',
      '批量提交 P1_I1 至 P1_I5 的输入文件生成，缩短串行等待',
      '核对 deadline 与工作量当量，必要时向服务器申请更高优先级',
    ],
  },
];
