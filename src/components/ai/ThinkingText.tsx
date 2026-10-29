import { useEffect, useRef, useState } from 'react';
import ChatMarkdown from './ChatMarkdown';

/**
 * 思考链路的打字机效果：只平滑显示后端已收到的文本，内容与运行状态仍以后端为准。
 * 与 `StreamingAnswer` 同一套追赶算法（大批量到达时加速，避免拖太久），
 * 复用正文的安全排版，流式到达的段落、列表和代码保持可读。
 */
export default function ThinkingText({
  text,
  active,
  fresh,
}: {
  text: string;
  active: boolean;
  fresh?: boolean;
}) {
  const [shown, setShown] = useState(() => (fresh ? '' : text));
  const visible = useRef(shown);

  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    let credit = 0;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const publish = (value: string) => {
      visible.current = value;
      setShown(value);
    };
    // 非生成中、文本不是延续（例如切换会话/重进）、系统要求减少动效时，直接显示完整文本。
    const immediate =
      !active ||
      !text.startsWith(visible.current) ||
      document.hidden ||
      reduced.matches;
    if (immediate) {
      publish(text);
      return;
    }
    const tick = (now: number) => {
      const elapsed = now - last;
      if (elapsed >= 30) {
        last = now;
        const remaining = text.length - visible.current.length;
        credit += (Math.max(45, remaining * 3) * Math.min(elapsed, 100)) / 1000;
        let end = Math.min(text.length, visible.current.length + Math.floor(credit));
        if (end > 0 && end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end++;
        if (end > visible.current.length) {
          credit = Math.max(0, credit - (end - visible.current.length));
          publish(text.slice(0, end));
        }
      }
      if (visible.current.length < text.length) frame = requestAnimationFrame(tick);
    };
    if (visible.current.length < text.length) frame = requestAnimationFrame(tick);
    const flush = () => {
      if (document.hidden || reduced.matches) {
        cancelAnimationFrame(frame);
        publish(text);
      }
    };
    document.addEventListener('visibilitychange', flush);
    reduced.addEventListener('change', flush);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', flush);
      reduced.removeEventListener('change', flush);
    };
  }, [text, active]);

  return (
    <div className="ai-reasoning__text">
      <ChatMarkdown text={shown} />
      {shown.length < text.length && <span className="ai-typing-cursor" aria-hidden="true" />}
    </div>
  );
}
