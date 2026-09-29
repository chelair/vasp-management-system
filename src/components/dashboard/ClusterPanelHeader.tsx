import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

/**
 * 集群类面板（bjobs / blimits / bhosts）的统一「刷新 + 上次更新」小控件（v0.9.33）。
 *
 * 集群查询走 SSH，可能慢或失败；这几块**单独加载、单独刷新**，
 * 不再和整页共用一次请求。控件里显示"更新于 xx:xx:xx"，刷新中显示 loading。
 */
export interface ClusterPanelHeaderProps {
  /** 手动刷新（会重新查集群） */
  onRefresh?: () => void;
  refreshingRef?: { current: boolean };
  /** 集群快照的采集时间（ISO 串） */
  lastUpdated?: string | null;
  /** 自动刷新间隔（毫秒），默认 5 分钟 */
  autoRefresh?: number;
  /** 集群查询失败/超时的原因（有值时面板显示提示 + 重试，而不是一直转圈） */
  error?: string | null;
  /** 重试（一般直接传 onRefresh） */
  onRetry?: () => void;
}

/** 给集群面板用：300ms 防抖的"刷新中"状态 + 可选自动刷新 */
export function useClusterRefresh(props: ClusterPanelHeaderProps) {
  const { onRefresh, refreshingRef, autoRefresh = 5 * 60 * 1000 } = props;
  const [busy, setBusy] = useState(false);
  const onRefreshRef = useRef(onRefresh);
  onRefreshRef.current = onRefresh;

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      if (refreshingRef?.current) return;
      onRefreshRef.current?.();
    }, autoRefresh);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshingRef]);

  const trigger = () => {
    if (refreshingRef?.current) return;
    setBusy(true);
    onRefreshRef.current?.();
    window.setTimeout(() => setBusy(false), 500);
  };

  return { busy, trigger, disabled: refreshingRef?.current ?? false };
}

function formatUpdated(value?: string | null) {
  if (!value) return '尚未更新';
  const time = value.replace('T', ' ').slice(11, 19);
  return time ? `更新于 ${time}` : '尚未更新';
}

export default function ClusterPanelHeader({
  onRefresh,
  refreshingRef,
  lastUpdated,
  autoRefresh,
}: ClusterPanelHeaderProps) {
  const { busy, trigger, disabled } = useClusterRefresh({ onRefresh, refreshingRef, autoRefresh });
  return (
    <span className="cluster-panel-header">
      <span className="preview-note">{formatUpdated(lastUpdated)}</span>
      {onRefresh && (
        <Tooltip title="重新查询集群（bjobs / blimits / bhosts）">
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            loading={busy || disabled}
            onClick={trigger}
            aria-label="刷新集群数据"
          />
        </Tooltip>
      )}
    </span>
  );
}

/**
 * 集群面板的失败态：**不要把"查询失败"表现成一直在加载**（用户 2026-09-27 反馈）。
 * 显示原因 + 重试按钮，点重试只重查集群这几块。
 */
export function ClusterPanelError({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <Alert
      type="warning"
      showIcon
      message="集群数据查询失败"
      description={error}
      action={
        onRetry ? (
          <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  );
}
