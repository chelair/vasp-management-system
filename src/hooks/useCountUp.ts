import { useEffect, useRef, useState } from 'react';

/** 数字滚动动画：值变化时在 duration 毫秒内缓动到新值（首次挂载直接显示） */
export default function useCountUp(value: number, duration = 700): number {
  const [display, setDisplay] = useState(value);
  const currentRef = useRef(value);

  useEffect(() => {
    const from = currentRef.current;
    if (from === value) return undefined;
    const start = performance.now();
    let raf = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = Math.round(from + (value - from) * eased);
      currentRef.current = next;
      setDisplay(next);
      if (t < 1) raf = requestAnimationFrame(tick);
      return undefined;
    });
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return display;
}
