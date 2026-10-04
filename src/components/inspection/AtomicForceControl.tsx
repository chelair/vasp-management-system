import { useCallback, useEffect, useRef, useState } from 'react';
import { Switch, Tooltip } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { fetchAtomicForces, type AtomicForces } from '../../api/inspections';

export interface AtomicForceHook {
  enabled: boolean;
  loading: boolean;
  error: string | null;
  data: AtomicForces | null;
  toggle: () => void;
  refresh: () => void;
}

/**
 * 「查看原子受力」状态（巡检详情页专用）。
 *
 * 按任务（NEB 再按映像）缓存已取过的结果：切换映像再切回来不会重复请求；
 * 结果本身在后端会落到任务本地镜像 `reports/atomic_forces*.json`，任务已结束时直接读本地。
 */
export function useAtomicForces(taskId: string, image: string | null): AtomicForceHook {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AtomicForces | null>(null);
  const cacheRef = useRef<Map<string, AtomicForces>>(new Map());
  const genRef = useRef(0);
  const key = image ?? '_';

  const load = useCallback(
    async (force = false) => {
      const gen = ++genRef.current;
      const hit = cacheRef.current.get(key);
      if (!force && hit) {
        setData(hit);
        setError(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const res = await fetchAtomicForces(taskId, { image, refresh: force });
        if (gen !== genRef.current) return;
        cacheRef.current.set(key, res);
        setData(res);
      } catch (e) {
        if (gen !== genRef.current) return;
        setData(null);
        setError(e instanceof Error ? e.message : '读取原子受力失败');
      } finally {
        if (gen === genRef.current) setLoading(false);
      }
    },
    [taskId, image, key],
  );

  useEffect(() => {
    if (enabled) void load(false);
  }, [enabled, load]);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
    }
  }, [enabled]);

  return {
    enabled,
    loading,
    error,
    data,
    toggle: useCallback(() => setEnabled((v) => !v), []),
    refresh: useCallback(() => {
      void load(true);
    }, [load]),
  };
}

interface Props {
  state: AtomicForceHook;
  /** 传值时按钮禁用并显示原因（如「受力对应优化后的结构，请切到优化后」） */
  disabledReason?: string | null;
  /** 额外提示（如元素序列不一致） */
  note?: string | null;
}

/** 3D 工具栏里的「查看原子受力」按钮 + 图例（巡检详情页专用，作业管理不显示）。 */
export function AtomicForceControl({ state, disabledReason, note }: Props) {
  return (
    <span className="atomic-force">
      <Tooltip title={disabledReason ?? '按原子受力着色：达标为绿，受力越大越红'}>
        <span className="atomic-force__switch">
          <Switch
            size="small"
            checked={state.enabled}
            loading={state.loading}
            disabled={Boolean(disabledReason)}
            onChange={state.toggle}
          />
          <ThunderboltOutlined />
          查看原子受力
        </span>
      </Tooltip>
      {state.enabled && note && <span className="atomic-force__warn">{note}</span>}
      {state.enabled && state.error && <span className="atomic-force__warn">{state.error}</span>}
    </span>
  );
}
