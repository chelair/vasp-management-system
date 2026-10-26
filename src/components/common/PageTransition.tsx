import type { ReactNode } from 'react';

/** 页面进入只做一次透明度/位移动画，不参与逐帧 React 更新。 */
export default function PageTransition({ children }: { children: ReactNode }) {
  return (
    <div className="page-transition">
      {children}
    </div>
  );
}
