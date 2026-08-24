import { useEffect, useState } from 'react';

export interface ClockValue {
  now: Date;
  date: string;
  time: string;
}

/** 顶部状态栏时钟：每秒刷新 */
export function useClock(intervalMs = 1000): ClockValue {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);

  return {
    now,
    date: now.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'short',
    }),
    time: now.toLocaleTimeString('zh-CN', { hour12: false }),
  };
}
