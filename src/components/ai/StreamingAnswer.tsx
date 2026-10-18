import { useEffect, useRef, useState } from 'react';
import ChatMarkdown from './ChatMarkdown';

/** 仅平滑显示已收到的文字，完整回答和运行状态仍由后端维护。 */
export default function StreamingAnswer({ text, status, fresh, onProgress }: {
  text: string; status: string; fresh: boolean; onProgress: () => void;
}) {
  const active = status === 'queued' || status === 'running';
  const animate = useRef(fresh || active);
  const [shown, setShown] = useState(() => fresh ? '' : text);
  const visible = useRef(shown);
  const progress = useRef(onProgress); progress.current = onProgress;

  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    let credit = 0;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const publish = (value: string) => { visible.current = value; setShown(value); };
    const flush = () => {
      if (document.hidden || reduced.matches) { cancelAnimationFrame(frame); publish(text); }
    };
    const immediate = !animate.current || ['cancelled', 'failed', 'interrupted'].includes(status)
      || !text.startsWith(visible.current) || document.hidden || reduced.matches;
    if (immediate) { publish(text); return; }
    const tick = (now: number) => {
      const elapsed = now - last;
      if (elapsed >= 30) {
        last = now;
        const remaining = text.length - visible.current.length;
        // 小片段逐字显示，大批量到达时加速追赶，避免回答结束后仍长时间等待。
        credit += Math.max(45, remaining * 3) * Math.min(elapsed, 100) / 1000;
        let end = Math.min(text.length, visible.current.length + Math.floor(credit));
        if (end > 0 && end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end++;
        if (end > visible.current.length) { credit = Math.max(0, credit - (end - visible.current.length)); publish(text.slice(0, end)); }
      }
      if (visible.current.length < text.length) frame = requestAnimationFrame(tick);
    };
    if (visible.current.length < text.length) frame = requestAnimationFrame(tick);
    document.addEventListener('visibilitychange', flush);
    reduced.addEventListener('change', flush);
    return () => { cancelAnimationFrame(frame); document.removeEventListener('visibilitychange', flush); reduced.removeEventListener('change', flush); };
  }, [text, status]);

  useEffect(() => { progress.current(); }, [shown]);
  const typing = active || shown.length < text.length;
  return <div className="ai-streaming-answer" aria-busy={typing}>
    {shown ? <ChatMarkdown text={shown} /> : <span className="ai-muted">{text ? '正在显示回答…' : active ? '正在等待模型回答…' : '本次未生成文字'}</span>}
    {typing && <span className="ai-typing-cursor" aria-hidden="true" />}
  </div>;
}
