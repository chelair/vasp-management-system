import { useMemo } from 'react';
import { Button, Card, Popconfirm, Skeleton, Tooltip } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import type { DashboardProjectProgress } from '../../types';
import useEcharts, { DASHBOARD_PALETTE } from './useEcharts';

interface Props {
  projects: DashboardProjectProgress[];
  loading?: boolean;
  onDelete?: (project: DashboardProjectProgress) => void;
}

/** 四象限气泡图：横轴时间进度、纵轴完成度、气泡大小=任务数；对角线为“预期进度”基准 */
export default function ProjectProgressPanel({ projects, loading, onDelete }: Props) {
  const option = useMemo(() => {
    const data = projects.map((p, i) => {
      const behind = (p.timeRatio ?? 0) * 100 - p.progress;
      const color = p.overdue && p.progress < 100 ? '#E4572E' : behind > 20 ? '#E8963C' : DASHBOARD_PALETTE[i % DASHBOARD_PALETTE.length];
      return {
        name: p.project_name,
        value: [Math.round((p.timeRatio ?? 0) * 100), p.progress, p.visibleTasks],
        itemStyle: { color, opacity: 0.85 },
        label: {
          show: true,
          formatter: p.project_name,
          position: 'top' as const,
          fontSize: 11,
          color: '#5A6A80',
        },
      };
    });
    return {
      grid: { top: 26, right: 26, bottom: 34, left: 46 },
      tooltip: {
        formatter: (params: { data: { name: string; value: number[] } }) => {
          const [x, y, n] = params.data.value;
          return `${params.data.name}<br/>时间进度 ${x}% · 完成度 ${y}%<br/>任务数 ${n}`;
        },
      },
      xAxis: {
        type: 'value',
        min: 0,
        max: 100,
        name: '时间进度 %',
        nameTextStyle: { fontSize: 11, color: '#8A98AC' },
        axisLabel: { fontSize: 11, color: '#8A98AC' },
        splitLine: { lineStyle: { color: '#EEF2F8' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        name: '完成度 %',
        nameTextStyle: { fontSize: 11, color: '#8A98AC' },
        axisLabel: { fontSize: 11, color: '#8A98AC' },
        splitLine: { lineStyle: { color: '#EEF2F8' } },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: (val: number[]) => Math.min(46, 18 + (val[2] ?? 0) * 0.5),
          data,
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { type: 'dashed', color: '#C4CEDC' },
            label: { formatter: '预期进度', fontSize: 11, color: '#96A3B5' },
            data: [
              [{ coord: [0, 0] }, { coord: [100, 100] }],
            ],
          },
          animationDuration: 700,
        },
      ],
    };
  }, [projects]);

  const chartRef = useEcharts(option, [option]);

  return (
    <Card title="项目进度" className="dashboard-card">
      {loading && projects.length === 0 ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : (
        <>
          <div ref={chartRef} className="progress-quadrant" />
          <div className="project-progress-rows">
            {projects.map((p) => {
              const timePercent = Math.round((p.timeRatio ?? 0) * 100);
              const behind = timePercent - p.progress;
              return (
                <div key={p.project_id} className="project-row">
                  <div className="project-row__head">
                    <span className="project-row__name" title={p.project_name}>
                      {p.project_name}
                    </span>
                    {p.overdue ? (
                      <span className="dashboard-badge dashboard-badge--error">
                        已逾期 {Math.abs(p.daysLeft ?? 0)} 天
                      </span>
                    ) : (
                      <span className="dashboard-sub">剩余 {p.daysLeft} 天</span>
                    )}
                    {onDelete && (
                      <Popconfirm
                        title={`删除项目 ${p.project_name}？`}
                        description="本地目录将移入回收站，远端文件不受影响"
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                        onConfirm={() => onDelete(p)}
                      >
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={`删除项目 ${p.project_name}`}
                        />
                      </Popconfirm>
                    )}
                  </div>
                  <div className="project-row__bar">
                    <div className="progress-track">
                      <div
                        className={`progress-fill${p.overdue ? ' progress-fill--danger' : ''}`}
                        style={{ width: `${Math.min(100, p.progress)}%` }}
                      />
                    </div>
                    <span className="project-row__percent">{p.progress}%</span>
                  </div>
                  <div className="project-row__meta">
                    <span>
                      完成 {p.completed}/{p.visibleTasks}
                    </span>
                    {p.running > 0 && <span>运行 {p.running}</span>}
                    {p.queued > 0 && <span>排队 {p.queued}</span>}
                    {p.anomalies > 0 && (
                      <span className="project-row__meta--warn">异常 {p.anomalies}</span>
                    )}
                    {behind > 15 && !p.overdue && (
                      <span className="project-row__meta--warn">落后计划 {behind}%</span>
                    )}
                    {p.continuationTasks > 0 && (
                      <Tooltip title="续算目录（conN）为同一任务的分支，不计入完成度分母">
                        <span className="dashboard-sub">另 {p.continuationTasks} 个续算目录</span>
                      </Tooltip>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}
