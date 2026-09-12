import { useMemo } from 'react';
import { Card, Empty, Skeleton } from 'antd';
import type { DashboardCoresUsage } from '../../types';
import useEcharts, { DASHBOARD_PALETTE } from './useEcharts';

interface Props {
  usage: DashboardCoresUsage | null;
  loading?: boolean;
}

/** 阈值配色：正常按项目着色，≥90% 橙色，≥100% 红色（配合 CSS 闪烁） */
function sliceColor(index: number, level: string): string {
  if (level === 'critical') {
    return ['#E4572E', '#F0714B', '#D9482C', '#F08A63'][index % 4];
  }
  if (level === 'warning') {
    return ['#E8963C', '#F0AC5E', '#D9822B', '#F5C177'][index % 4];
  }
  return DASHBOARD_PALETTE[index % DASHBOARD_PALETTE.length];
}

export default function CoresUsagePanel({ usage, loading }: Props) {
  const option = useMemo(() => {
    const projects = usage?.byProject ?? [];
    const total = usage?.totalCores ?? null;
    const used = usage?.usedCores ?? 0;
    const remaining = total != null ? Math.max(0, total - used) : null;
    const level = usage?.level ?? 'normal';
    const data = projects.map((p, i) => ({
      name: p.project_name,
      value: p.cores,
      itemStyle: { color: sliceColor(i, level) },
    }));
    if (remaining != null && remaining > 0) {
      data.push({
        name: '剩余可用',
        value: remaining,
        itemStyle: { color: '#E9EEF6' },
      });
    }
    const percent = usage?.usedPercent;
    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: { name: string; value: number; percent: number }) =>
          `${params.name}<br/>${params.value} 核（${params.percent}%）`,
      },
      title: {
        text: total != null ? `${used} / ${total}` : `${used}`,
        subtext:
          percent != null
            ? `剩余 ${remaining ?? 0} 核 · 使用率 ${percent}%`
            : '未取到核数上限（blimits）',
        left: 'center',
        top: '38%',
        textStyle: { fontSize: 22, fontWeight: 700, color: '#233043' },
        subtextStyle: { fontSize: 12, color: '#8A98AC' },
      },
      series: [
        {
          type: 'pie',
          radius: ['62%', '82%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 6 },
          data,
          animationDuration: 700,
        },
      ],
    };
  }, [usage]);

  const chartRef = useEcharts(option, [option]);
  const level = usage?.level ?? 'normal';

  return (
    <Card
      title="核数占用"
      className="dashboard-card"
      extra={
        <span className={`cores-badge cores-badge--${level}`}>
          {level === 'critical'
            ? '已超配额'
            : level === 'warning'
              ? '接近配额'
              : '配额充足'}
        </span>
      }
    >
      {loading && !usage ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : !usage || (usage.byProject.length === 0 && usage.usedCores === 0) ? (
        <Empty description="当前没有占用核数的作业" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div
            ref={chartRef}
            className={`cores-donut${level === 'critical' ? ' cores-donut--critical' : ''}`}
          />
          <div className="cores-legend">
            {(usage.byProject ?? []).map((p, i) => (
              <div key={p.project_name} className="cores-legend__row">
                <span
                  className="cores-legend__dot"
                  style={{ background: sliceColor(i, usage.level) }}
                />
                <span className="cores-legend__name" title={p.project_name}>
                  {p.project_name}
                </span>
                <span className="cores-legend__value">{p.cores} 核</span>
              </div>
            ))}
          </div>
          <div className="dashboard-note">
            上限来源：
            {usage.limitSource === 'blimits'
              ? 'blimits 配额'
              : usage.limitSource === 'manual'
                ? '系统配置手动指定（dashboard_total_cores）'
                : '未取到，仅统计 bjobs 汇总'}
            {usage.queues.length > 0 && `（队列 ${usage.queues.join(' / ')}）`}
          </div>
        </>
      )}
    </Card>
  );
}
