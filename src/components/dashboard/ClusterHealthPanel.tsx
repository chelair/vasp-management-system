import { Card, Skeleton, Tooltip } from 'antd';
import type { DashboardClusterHealth } from '../../types';

interface Props {
  health: DashboardClusterHealth | null;
  loading?: boolean;
}

const NODE_ITEMS = [
  { key: 'ok', label: '正常', className: 'ok' },
  { key: 'full', label: '满载', className: 'full' },
  { key: 'closed', label: '关闭', className: 'closed' },
  { key: 'down', label: '宕机', className: 'down' },
] as const;

export default function ClusterHealthPanel({ health, loading }: Props) {
  if (loading && !health) {
    return (
      <Card title="集群健康与资源" className="dashboard-card">
        <Skeleton active paragraph={{ rows: 5 }} />
      </Card>
    );
  }

  const nodes = health?.nodes ?? null;
  const storage = health?.storage ?? null;
  const queues = health?.queues ?? [];
  const queueTotals = health?.queueTotals;
  const corePercent =
    nodes && nodes.totalCores > 0
      ? Math.round((nodes.runningCores / nodes.totalCores) * 100)
      : null;

  return (
    <Card
      title="集群健康与资源"
      className="dashboard-card"
      extra={
        health?.error ? (
          <Tooltip title={health.error}>
            <span className="dashboard-badge dashboard-badge--error">查询异常</span>
          </Tooltip>
        ) : (
          <span className="dashboard-sub">
            {health?.source === 'real' ? '实时' : '缓存'}
            {typeof health?.cacheAgeSeconds === 'number' && health.cacheAgeSeconds > 0
              ? ` · ${Math.round(health.cacheAgeSeconds)}s 前`
              : ''}
          </span>
        )
      }
    >
      {!nodes ? (
        <div className="dashboard-muted">未取到节点状态（bhosts）</div>
      ) : (
        <>
          <div className="health-block">
            <div className="health-block__title">
              节点状态
              <span className="dashboard-sub">
                共 {nodes.total} 节点 · {nodes.totalCores} 核
              </span>
            </div>
            <div className="node-lights">
              {NODE_ITEMS.map((item) => (
                <div key={item.key} className={`node-light node-light--${item.className}`}>
                  <span className={`node-light__dot node-light__dot--${item.className}`} />
                  <span className="node-light__label">{item.label}</span>
                  <span className="node-light__value">{nodes[item.key]}</span>
                </div>
              ))}
            </div>
            {corePercent != null && (
              <div className="health-cores">
                <div className="health-cores__head">
                  <span>全体节点核数占用</span>
                  <span className="health-cores__value">
                    {nodes.runningCores} / {nodes.totalCores}（{corePercent}%）
                  </span>
                </div>
                <div className="progress-track">
                  <div
                    className={`progress-fill${corePercent >= 90 ? ' progress-fill--warn' : ''}`}
                    style={{ width: `${corePercent}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="health-block">
            <div className="health-block__title">
              队列拥堵
              {queueTotals && (
                <span className="dashboard-sub">
                  排队 {queueTotals.pending} · 运行 {queueTotals.running}
                </span>
              )}
            </div>
            {queues.length === 0 ? (
              <div className="dashboard-muted">未取到队列状态（bqueues）</div>
            ) : (
              <div className="queue-list">
                {queues.map((q) => {
                  const total = q.pending + q.running;
                  const pendRatio = total > 0 ? Math.round((q.pending / total) * 100) : 0;
                  return (
                    <div key={q.queue} className="queue-row">
                      <span className="queue-row__name" title={q.queue}>
                        {q.queue}
                      </span>
                      <div className="queue-row__bar">
                        <div className="queue-row__bar-inner" style={{ width: `${pendRatio}%` }} />
                      </div>
                      <span className="queue-row__stat">
                        排队 {q.pending} · 运行 {q.running}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="health-block">
            <div className="health-block__title">
              存储容量
              {storage && (
                <span className="dashboard-sub">
                  {storage.mountedOn}（{storage.filesystem}）
                </span>
              )}
            </div>
            {!storage ? (
              <div className="dashboard-muted">未取到存储信息（df -h）</div>
            ) : (
              <>
                <div className="progress-wrap">
                  <div className="progress-track">
                    <div
                      className={`progress-fill${storage.warning ? ' progress-fill--danger' : ''}`}
                      style={{ width: `${Math.min(100, storage.usedPercent)}%` }}
                    />
                  </div>
                  <span className="progress-text">{storage.usedPercent}%</span>
                </div>
                <div className={`dashboard-note${storage.warning ? ' dashboard-note--danger' : ''}`}>
                  {storage.warning
                    ? `存储空间不足，请及时清理：剩余 ${storage.available} / ${storage.size}`
                    : `已用 ${storage.used} / ${storage.size}，剩余 ${storage.available}`}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
