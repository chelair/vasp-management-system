import { useMemo } from 'react';
import { Card, Skeleton } from 'antd';
import type { DashboardTrend } from '../../types';
import useEcharts from './useEcharts';

interface Props {
  trend: DashboardTrend | null;
  loading?: boolean;
}

/** 近 7 天：核数占用（左轴，面积线）+ 运行中任务（右轴，线）+ 每日提交作业数（右轴，柱） */
export default function TrendPanel({ trend, loading }: Props) {
  const option = useMemo(() => {
    const points = trend?.points ?? [];
    return {
      grid: { top: 44, right: 46, bottom: 28, left: 52 },
      legend: {
        top: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { fontSize: 11, color: '#6B7A90' },
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ seriesName: string; value: unknown; axisValue: string }>) => {
          const head = params[0]?.axisValue ?? '';
          const lines = params.map(
            (p) =>
              `${p.seriesName}：${p.value == null || p.value === '-' ? '无数据' : p.value}`,
          );
          return [`<b>${head}</b>`, ...lines].join('<br/>');
        },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLine: { lineStyle: { color: '#E3E9F2' } },
        axisLabel: { fontSize: 11, color: '#8A98AC' },
        axisTick: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '核数',
          nameTextStyle: { fontSize: 11, color: '#8A98AC' },
          splitLine: { lineStyle: { color: '#EEF2F8' } },
          axisLabel: { fontSize: 11, color: '#8A98AC' },
        },
        {
          type: 'value',
          name: '任务数',
          nameTextStyle: { fontSize: 11, color: '#8A98AC' },
          splitLine: { show: false },
          axisLabel: { fontSize: 11, color: '#8A98AC' },
        },
      ],
      series: [
        {
          name: '核数占用',
          type: 'line',
          // 折线（直线段连接各采样点），不做平滑：两点/三点时更贴近真实采样值
          smooth: false,
          symbolSize: 7,
          connectNulls: false,
          yAxisIndex: 0,
          itemStyle: { color: '#5B8DEF' },
          lineStyle: { width: 3 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(91,141,239,0.28)' },
                { offset: 1, color: 'rgba(91,141,239,0.02)' },
              ],
            },
          },
          data: points.map((p) => p.usedCores),
        },
        {
          name: '运行中任务',
          type: 'line',
          smooth: false,
          symbolSize: 6,
          connectNulls: false,
          yAxisIndex: 1,
          itemStyle: { color: '#67C6B0' },
          lineStyle: { width: 2 },
          data: points.map((p) => p.runningTasks),
        },
        {
          name: '提交作业数',
          type: 'bar',
          yAxisIndex: 1,
          barMaxWidth: 14,
          itemStyle: { color: 'rgba(167,139,250,0.55)', borderRadius: [4, 4, 0, 0] },
          data: points.map((p) => p.submissions),
        },
      ],
      animationDuration: 700,
    };
  }, [trend]);

  const chartRef = useEcharts(option, [option]);
  const hasSamples = (trend?.sampleCount ?? 0) > 0;

  return (
    <Card
      title="计算资源趋势（近 7 天）"
      className="dashboard-card"
      extra={<span className="dashboard-sub">{trend?.note ?? ''}</span>}
    >
      {loading && !trend ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : (
        <>
          <div ref={chartRef} className="trend-chart-echarts" />
          {!hasSamples && (
            <div className="dashboard-note">
              核数占用与运行中任务自本功能上线起逐步累积（每次打开总览或刷新集群状态采样一次）；
              「提交作业数」为历史真实数据，可直接参考提交时机。
            </div>
          )}
        </>
      )}
    </Card>
  );
}
