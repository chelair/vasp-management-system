import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useReducedMotion } from '../../context/AppearanceContext';

/** 只延后展示内容的卸载；折叠时立即退出键盘与无障碍导航，不延后业务操作。 */
export default function AnimatedCollapse({ open, children }: { open: boolean; children: ReactNode }) {
  const reduced = useReducedMotion();
  const [present, setPresent] = useState(open);
  useEffect(() => {
    if (open || reduced) { setPresent(open); return; }
    // 后台标签页可能没有 transitionend，保留一个卸载兜底。
    const timer = window.setTimeout(() => setPresent(false), 300);
    return () => window.clearTimeout(timer);
  }, [open, reduced]);

  return <div className={`animated-collapse${open ? ' animated-collapse--open' : ''}`}
    aria-hidden={!open} {...(!open ? { inert: '' } : {})}
    onTransitionEnd={event => {
      if (!open && event.target === event.currentTarget && event.propertyName === 'grid-template-rows') setPresent(false);
    }}>
    <div className="animated-collapse__inner">{(open || (!reduced && present)) && children}</div>
  </div>;
}
