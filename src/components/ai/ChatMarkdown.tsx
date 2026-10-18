import { Button } from 'antd';
import { renderMarkdown } from '../../utils/markdown';

export default function ChatMarkdown({ text }: { text: string }) {
  // 不自动加载模型提供的外部图片；原始 HTML 由现有渲染器转义。
  const parts = text.split(/```([^\n`]*)\n([\s\S]*?)(?:```|$)/g);
  return <div className="ai-markdown">{parts.map((part, i) => {
    if (i % 3 === 1) return null;
    if (i % 3 === 2) return <div className="ai-code" key={i}>
      <div><span>{parts[i - 1] || '代码'}</span><Button type="text" size="small" onClick={() => { void navigator.clipboard?.writeText(part); }}>复制</Button></div>
      <pre><code>{part}</code></pre>
    </div>;
    return <div key={i} dangerouslySetInnerHTML={{ __html: renderMarkdown(part.replace(/!\[([^\]]*)\]\([^)]+\)/g, '〔图片：$1，未自动加载〕')) }} />;
  })}</div>;
}
