import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Alert, Button, Drawer, Input, Select, Tag, message } from 'antd';
import { request } from '../../api/client';
import { listAIConnections, type AIConnection } from '../../api/aiChat';
import { renderMarkdown } from '../../utils/markdown';
import './ReportReview.css';
import { useReportWork } from './ReportWorkContext';
import ReportRunActivity from './ReportRunActivity';
import { CommentOutlined, ArrowUpOutlined, AimOutlined } from '@ant-design/icons';

interface Module { key: string; title: string; section: string; level: number; parent: string | null }
interface Comment {
  id: string; target: string; text: string; status: 'open' | 'blocked' | 'done'; source: string; created_at: string;
  replies: { text: string; author: string; model?: string; created_at: string }[];
}
interface Review { revision: string; source: string; stale: boolean; modules: Module[]; comments: Comment[] }
const Context = createContext<{ open: (target?: string) => void; count: number } | null>(null);

export function ReportReviewControls() {
  const review = useContext(Context);
  return review ? <Button type="primary" ghost icon={<CommentOutlined aria-hidden />} onClick={() => review.open()}>报告批注{review.count ? `（${review.count}条待处理）` : ''}</Button> : null;
}

export function ReportReviewProvider({ reportId, contentRef, version, connectionId, onConnectionChange, enabled = true, children }: {
  reportId: string; contentRef: RefObject<HTMLDivElement>; version: unknown;
  connectionId: string; onConnectionChange: (id: string) => void; enabled?: boolean; children: ReactNode;
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
  const [filter, setFilter] = useState<'all' | 'pending' | 'done'>('all');
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
  const finishedComment = work?.run?.report_activity?.slice().reverse().find(s => s.comment_id && (s.state === 'completed' || s.state === 'blocked'))?.comment_id;
  useEffect(() => {
    if (finishedRun || finishedComment) void load().catch(e => setError(e.message));
  }, [finishedRun, finishedComment, load]);
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
    if (!review || busy || work?.busy) return false;
    setBusy(key);
    try { setReview(await request<Review>(base, { method: 'POST', body: JSON.stringify({ revision: review.revision, ...payload }) })); setError(''); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '保存失败'); await load().catch(() => {}); return false; }
    finally { setBusy(''); }
  };
  const process = async (id: string) => {
    if (!review || busy) return;
    if (!model) { message.info('请先选择自己的模型连接'); return; }
    setBusy(id); setError('');
    try {
      await work?.start({ action: 'comment', report_id: reportId, comment_id: id }, undefined, false);
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : '处理失败，原批注保留');
    } finally { if (active.current) setBusy(''); }
  };
  const sendReply = async (id: string) => {
    if (!await mutate({ operation: 'reply', comment_id: id, text: reply[id] }, id)) return;
    setReply(old => ({ ...old, [id]: '' }));
    if (model && enabled) await work?.start({ action: 'comment', report_id: reportId, comment_id: id }, undefined, false);
    else message.info('补充已保存，开启 AI 并选择模型后即可继续处理');
  };
  const locate = (key: string) => {
    const heading = anchors.find(anchor => anchor.key === key)?.el.parentElement;
    if (!heading) return;
    setOpened(false);
    heading.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' });
    heading.classList.add('report-review-highlight');
    window.setTimeout(() => heading.classList.remove('report-review-highlight'), 1800);
  };
  const pending = review?.comments.filter(c => c.status !== 'done').length ?? 0;
  const scoped = review?.comments.filter(c => !target || c.target === target) ?? [];
  const shown = scoped.filter(c => filter === 'all' || (filter === 'done' ? c.status === 'done' : c.status !== 'done'));
  return <Context.Provider value={{ open, count: pending }}>
    {children}
    {anchors.map(anchor => contentRef.current?.contains(anchor.el) ? createPortal(<Button size="small" type="link" onClick={() => open(anchor.key)}>
      批注{review?.comments.some(c => c.target === anchor.key && c.status !== 'done') ? ' · 待处理' : ''}
    </Button>, anchor.el, anchor.key) : null)}
    <Drawer rootClassName="report-review-drawer" title="报告批注" open={opened} width={660} onClose={() => setOpened(false)}>
      <div className="report-review-intro"><strong>在对应模块提出修改，进展和回复都留在这里。</strong><p>AI 只修改批注范围。批注不进入导出，处理后的结果会进入报告。</p></div>
      {error && <Alert type="warning" showIcon message={error} action={<Button size="small" onClick={() => void load().catch(() => {})}>刷新</Button>} />}
      {work?.error && <Alert type="warning" showIcon message={work.error} action={<Button size="small" onClick={work.reconnect}>恢复连接</Button>} />}
      {!enabled && <Alert type="info" message="AI 批注处理未开启。可先记录要求，再开启报告上方的 AI 开关。" />}
      {review?.stale && <Alert type="info" message="报告已重新生成，旧批注保留供追溯；在当前模块添加新批注即可继续。" />}
      <div className="report-review-settings">
        <label><span>查看模块</span><Select aria-label="批注所在模块" placeholder="全部模块" value={target} allowClear showSearch optionFilterProp="label" onChange={setTarget} style={{ width: '100%' }}
          options={review?.modules.map(m => ({ value: m.key, label: `${m.level === 2 ? '' : m.level === 3 ? '　' : '　　'}${m.title}` }))} />
        </label>
        <label><span>处理模型</span><Select aria-label="批注处理模型" placeholder="选择自己的模型" value={model || undefined} onChange={onConnectionChange} disabled={Boolean(busy) || work?.busy} style={{ width: '100%' }} options={models.map(m => ({ value: m.id, label: `${m.name} · ${m.model}` }))} /></label>
      </div>
      <section className="report-review-compose">
        <div className="report-review-section-head"><strong>新批注</strong><span>{target ? review?.modules.find(m => m.key === target)?.title : '先选择要修改的模块'}</span></div>
        <Input.TextArea aria-label="新的报告批注" value={text} maxLength={8000} autoSize={{ minRows: 2, maxRows: 5 }} onChange={e => setText(e.target.value)} placeholder="说说你想怎样修改，例如：对比这几项结果，用卡片突出形成能。" />
        <div className="report-review-compose-footer"><small>保存后可单独处理，也可随报告生成一起处理</small><Button type="primary" disabled={!target || !text.trim() || Boolean(busy) || work?.busy} onClick={async () => { if (await mutate({ operation: 'add', target, text }, 'add')) { setText(''); setFilter('all'); } }}>保存批注</Button></div>
      </section>
      <div className="report-review-list-header"><div className="report-review-filters" aria-label="批注状态筛选">
        {(['all', 'pending', 'done'] as const).map(value => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value === 'all' ? '全部' : value === 'pending' ? '待处理' : '已完成'}<span>{scoped.filter(c => value === 'all' || (value === 'done' ? c.status === 'done' : c.status !== 'done')).length}</span></button>)}
      </div><Button type="link" size="small" onClick={() => { setOpened(false); work?.open(); }}>项目对话</Button></div>
      <div className="report-review-list">
      {!shown.length && <div className="report-review-empty">这里还没有{filter === 'done' ? '已完成的' : filter === 'pending' ? '待处理的' : ''}批注。</div>}
      {shown.map(comment => {
        const task = work?.runs.find(r => r.report_job?.comment_id === comment.id && r.report_job.report_id === reportId
          || r.report_activity?.some(step => step.comment_id === comment.id && step.report_id === reportId));
        const processing = Boolean(work?.busy && task && task.id === work.run?.id && (task.report_job?.comment_id === comment.id
          || task.report_activity?.slice(-1)[0]?.comment_id === comment.id));
        const failedStep = task?.report_activity?.filter(s => s.comment_id === comment.id && s.report_id === reportId).slice(-1)[0];
        const renderReply = (item: Comment['replies'][number], i: number) => <div className={`report-review-reply${item.author === 'AI' ? ' is-ai' : ''}`} key={i}>
          <div className="report-review-reply-meta"><strong>{item.author === 'AI' ? 'AI' : '你'}</strong><time title={item.created_at}>{item.created_at.slice(11, 16)}</time></div>
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(item.text, { allowImages: false }) }} /></div>;
        return <article className={`report-review-comment${processing ? ' is-processing' : ''}`} key={comment.id} data-comment-id={comment.id}>
        <div className="report-review-comment-head"><strong>{review?.modules.find(m => m.key === comment.target)?.title || '旧版模块'}</strong>
          <Tag color={processing ? 'processing' : comment.status === 'done' ? 'green' : comment.status === 'blocked' ? 'orange' : 'default'}>{processing ? '处理中' : comment.status === 'done' ? '已完成' : comment.status === 'blocked' ? '需要补充' : '待处理'}</Tag>
          <time title={comment.created_at}>{comment.created_at.slice(5, 16).replace('T', ' ')}</time>
        </div>
        <p className="report-review-user">{comment.text}</p>
        {comment.source !== review?.source && <Tag>旧版批注</Tag>}
        {task && <ReportRunActivity key={task.id} run={task} reportId={reportId} commentId={comment.id} />}
        {(task?.error || failedStep?.state === 'failed') && <Alert type="warning" message={task?.error || failedStep?.label} />}
        {comment.replies.length > 1 && <details className="report-review-history"><summary>查看之前的 {comment.replies.length - 1} 条交流</summary>{comment.replies.slice(0, -1).map(renderReply)}</details>}
        {comment.replies.slice(-1).map(renderReply)}
        <div className="report-review-comment-actions">
          {processing ? <Button danger size="small" onClick={work?.stop}>停止</Button> : comment.status !== 'done' && <Button type="primary" size="small" disabled={Boolean(busy) || work?.busy || !model || !enabled || comment.source !== review?.source} loading={busy === comment.id} onClick={() => void process(comment.id)}>让AI处理</Button>}
          <Button type="text" size="small" disabled={Boolean(busy) || work?.busy} onClick={() => void mutate({ operation: 'status', comment_id: comment.id, status: comment.status === 'done' ? 'open' : 'done' }, comment.id)}>{comment.status === 'done' ? '重新打开' : '标记完成'}</Button>
          <Button type="text" size="small" icon={<AimOutlined aria-hidden />} onClick={() => locate(comment.target)}>查看报告</Button>
        </div>
        {comment.status !== 'done' && <div className="report-review-reply-composer">
          <Input.TextArea aria-label={`回复批注 ${comment.id}`} value={reply[comment.id] || ''} onChange={e => setReply(old => ({ ...old, [comment.id]: e.target.value }))} autoSize={{ minRows: 1, maxRows: 5 }} maxLength={8000} placeholder={comment.status === 'blocked' ? '在这里补充，AI 会接着处理这条批注…' : '补充要求或回复 AI…'} />
          <Button type="primary" size="small" icon={<ArrowUpOutlined aria-hidden />} disabled={Boolean(busy) || work?.busy || !reply[comment.id]?.trim()} onClick={() => void sendReply(comment.id)}>回复并继续</Button>
        </div>}
      </article>;
      })}
      </div>
    </Drawer>
  </Context.Provider>;
}
