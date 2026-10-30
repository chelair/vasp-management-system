import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Alert, Button, Drawer, Input, Select, Space, Tag, message } from 'antd';
import { request } from '../../api/client';
import { listAIConnections, type AIConnection } from '../../api/aiChat';
import { renderMarkdown } from '../../utils/markdown';
import './ReportReview.css';
import { useReportWork } from './ReportWorkContext';

interface Module { key: string; title: string; section: string; level: number; parent: string | null }
interface Comment {
  id: string; target: string; text: string; status: 'open' | 'blocked' | 'done'; source: string;
  replies: { text: string; author: string; model?: string; created_at: string }[];
}
interface Review { revision: string; source: string; stale: boolean; modules: Module[]; comments: Comment[] }
const Context = createContext<{ open: (target?: string) => void; count: number } | null>(null);

export function ReportReviewControls() {
  const review = useContext(Context);
  return review ? <Button onClick={() => review.open()}>报告批注{review.count ? `（${review.count}条待处理）` : ''}</Button> : null;
}

export function ReportReviewProvider({ reportId, contentRef, version, connectionId, onConnectionChange, children }: {
  reportId: string; contentRef: RefObject<HTMLDivElement>; version: unknown;
  connectionId: string; onConnectionChange: (id: string) => void; children: ReactNode;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const work = useReportWork();
  const [target, setTarget] = useState<string>();
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState('');
  const [reply, setReply] = useState<Record<string, string>>({});
  const [models, setModels] = useState<AIConnection[]>([]);
  const model = connectionId;
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [anchors, setAnchors] = useState<{ key: string; el: HTMLElement }[]>([]);
  const active = useRef(true);
  const base = `/reports/project/${encodeURIComponent(reportId)}/review`;
  const load = useCallback(async () => {
    if (!reportId) return;
    const result = await request<Review>(`/reports/project/${encodeURIComponent(reportId)}/review`);
    if (active.current) setReview(result);
  }, [reportId]);
  useEffect(() => {
    active.current = true;
    setReview(null); setOpened(false); setText(''); setAnchors([]);
    void load().catch(e => { if (active.current) setError(e.message || '无法加载批注'); });
    return () => { active.current = false; };
  }, [load]);
  const finishedRun = work?.run && !work.busy ? work.run.id : '';
  useEffect(() => {
    if (finishedRun) void load().catch(e => setError(e.message));
  }, [finishedRun, load]);
  useEffect(() => {
    if (!opened) return;
    let alive = true;
    void listAIConnections().then(result => { if (alive) setModels(result.items); }).catch(() => { if (alive) setModels([]); });
    return () => { alive = false; };
  }, [opened]);
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !review) return;
    const hosts: { key: string; el: HTMLElement }[] = [];
    const headingText = (heading: Element) => {
      const clone = heading.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('.report-hide-btn,.report-review-anchor').forEach(el => el.remove());
      return clone.textContent?.trim();
    };
    root.querySelectorAll<HTMLElement>('section[data-report-section]').forEach(section => {
      const modules = review.modules.filter(m => m.section === section.dataset.reportSection);
      const headings = [...section.querySelectorAll<HTMLElement>('.report-section-title,.report-markdown > h5,.report-markdown > h6')];
      const remaining = [...headings];
      modules.forEach(module => {
        const index = remaining.findIndex(h => (module.level === 2 ? h.classList.contains('report-section-title') : h.tagName === (module.level === 3 ? 'H5' : 'H6')) && headingText(h) === module.title);
        if (index < 0) return;
        const heading = remaining.splice(index, 1)[0];
        let host = heading.querySelector<HTMLElement>(':scope > .report-review-anchor');
        if (!host) { host = document.createElement('span'); host.className = 'report-review-anchor'; heading.append(host); }
        hosts.push({ key: module.key, el: host });
      });
    });
    setAnchors(hosts);
  }, [contentRef, review, version]);

  const open = (key?: string) => { setTarget(key); setOpened(true); setError(''); };
  const mutate = async (payload: object, key: string) => {
    if (!review || busy) return false;
    setBusy(key);
    try { setReview(await request<Review>(base, { method: 'POST', body: JSON.stringify({ revision: review.revision, ...payload }) })); setError(''); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '保存失败'); await load().catch(() => {}); return false; }
    finally { setBusy(''); }
  };
  const process = async (id: string) => {
    if (!review || busy) return;
    if (!model) { message.info('请先选择自己的模型连接'); return; }
    setBusy(id); setError(''); setOpened(false);
    try {
      await work?.start({ action: 'comment', report_id: reportId, comment_id: id });
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : '处理失败，原批注保留');
    } finally { if (active.current) setBusy(''); }
  };
  const pending = review?.comments.filter(c => c.status !== 'done').length ?? 0;
  const shown = review?.comments.filter(c => !target || c.target === target) ?? [];
  return <Context.Provider value={{ open, count: pending }}>
    {children}
    {anchors.map(anchor => contentRef.current?.contains(anchor.el) ? createPortal(<Button size="small" type="link" onClick={() => open(anchor.key)}>
      批注{review?.comments.some(c => c.target === anchor.key && c.status !== 'done') ? ' · 待处理' : ''}
    </Button>, anchor.el, anchor.key) : null)}
    <Drawer rootClassName="report-review-drawer" title="报告批注" open={opened} width={540} onClose={() => setOpened(false)}>
      <p>批注只在系统内保留，不进入 HTML、Markdown 或 PDF。AI修改后的正文和原有交互会进入报告。</p>
      {error && <Alert type="warning" showIcon message={error} action={<Button size="small" onClick={() => void load().catch(() => {})}>刷新</Button>} />}
      {review?.stale && <Alert type="info" message="报告已重新生成，旧批注保留供追溯；在当前模块添加新批注即可继续。" />}
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select aria-label="批注所在模块" placeholder="选择章节或模块" value={target} allowClear onChange={setTarget} style={{ width: '100%' }}
          options={review?.modules.map(m => ({ value: m.key, label: `${m.level === 2 ? '' : m.level === 3 ? '　' : '　　'}${m.title}` }))} />
        <Input.TextArea aria-label="新的报告批注" value={text} maxLength={8000} rows={3} onChange={e => setText(e.target.value)} placeholder="例如：先展示这几项结构对比，再解释能量差；请保留原来的交互图。" />
        <Button type="primary" disabled={!target || !text.trim() || Boolean(busy)} onClick={async () => { if (await mutate({ operation: 'add', target, text }, 'add')) setText(''); }}>保存批注</Button>
        <Select aria-label="批注处理模型" placeholder="选择自己的模型连接" value={model || undefined} onChange={onConnectionChange} disabled={Boolean(busy)} style={{ width: '100%' }} options={models.map(m => ({ value: m.id, label: `${m.name} · ${m.model}` }))} />
        <Button onClick={() => { setOpened(false); work?.open(); }}>查看后台进度与对话</Button>
      </Space>
      {shown.map(comment => <article className="report-review-comment" key={comment.id}>
        <Space wrap><strong>{review?.modules.find(m => m.key === comment.target)?.title || '旧版模块'}</strong>
          <Tag color={comment.status === 'done' ? 'green' : comment.status === 'blocked' ? 'orange' : 'blue'}>{comment.status === 'done' ? '已完成' : comment.status === 'blocked' ? '需要补充' : '待处理'}</Tag>
          {comment.source !== review?.source && <Tag>旧版批注</Tag>}
        </Space>
        <p className="report-review-user">{comment.text}</p>
        {comment.replies.map((item, i) => <div className="report-review-reply" key={i}><small>{item.author === 'AI' ? `AI · ${item.model || ''}` : '回复'} · {item.created_at}</small>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(item.text, { allowImages: false }) }} /></div>)}
        <Space wrap>
          <Button disabled={Boolean(busy) || work?.busy || !model || comment.status === 'done' || comment.source !== review?.source} loading={busy === comment.id} onClick={() => void process(comment.id)}>让AI处理</Button>
          <Button disabled={Boolean(busy)} onClick={() => void mutate({ operation: 'status', comment_id: comment.id, status: comment.status === 'done' ? 'open' : 'done' }, comment.id)}>{comment.status === 'done' ? '重新打开' : '标记完成'}</Button>
        </Space>
        <Input.TextArea aria-label={`回复批注 ${comment.id}`} value={reply[comment.id] || ''} onChange={e => setReply(old => ({ ...old, [comment.id]: e.target.value }))} rows={2} maxLength={8000} placeholder="补充说明或回复AI，无需重新输入原批注" />
        <Button size="small" disabled={Boolean(busy) || !reply[comment.id]?.trim()} onClick={async () => { if (await mutate({ operation: 'reply', comment_id: comment.id, text: reply[comment.id] }, comment.id)) setReply(old => ({ ...old, [comment.id]: '' })); }}>发送回复</Button>
      </article>)}
    </Drawer>
  </Context.Provider>;
}
