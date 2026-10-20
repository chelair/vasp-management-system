import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Drawer, Empty, Input, Select, Space, Spin, Tag } from 'antd';
import { ApiError } from '../../api/client';
import { checkComposition, compositionHtml, fetchCandidates, fetchComposition, fetchCompositions, previewComposition, saveComposition,
  type BlockCandidate, type CompositionDraft, type CompositionMeta, type ReportBlock } from '../../api/reportCompositions';
import './ReportCompositionEditor.css';
import { mapLegacyHiddenBlocks } from '../../utils/reportHidden';

const blank = (): CompositionDraft => ({ title: '专题报告', blocks: [], groups: [], hidden_block_ids: [], deleted_block_ids: [] });
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
const statusLabel: Record<string, string> = { available: '可用', missing: '无本地数据', unparsed: '待解析', unknown: '来源未知',
  shown: '正文展示', omitted_limit: '超出正文上限', omitted_unconverged: '未收敛，正文省略', omitted_no_history: '无曲线，正文省略' };

export default function ReportCompositionEditor({projectRef, projectName, legacyHidden = [], onClose}: {projectRef: string; projectName: string; legacyHidden?: string[]; onClose: () => void}) {
  const {message, modal} = App.useApp();
  const [candidates, setCandidates] = useState<BlockCandidate[]>([]);
  const [items, setItems] = useState<CompositionMeta[]>([]);
  const [draft, setDraft] = useState<CompositionDraft>(blank);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [html, setHtml] = useState('');
  const [previewDirty, setPreviewDirty] = useState(true);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<string>();
  const [query, setQuery] = useState('');
  const [newGroup, setNewGroup] = useState('');
  const [stale, setStale] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setBusy(true);
    Promise.all([fetchCandidates(projectRef), fetchCompositions(projectRef)])
      .then(([catalog, list]) => { if (alive.current) { setCandidates(catalog.candidates); setItems(list.items); } })
      .catch(e => { if (alive.current) setError(e.message); })
      .finally(() => { if (alive.current) setBusy(false); });
    return () => { alive.current = false; };
  }, [projectRef]);
  const edit = (next: CompositionDraft) => { setDraft(next); setDirty(true); setPreviewDirty(true); };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await fn(); } catch (e) {
      if (alive.current) {
        setError(e instanceof Error ? e.message : String(e));
        if (e instanceof ApiError && e.data?.code === 'evidence_stale') setStale(true);
      }
    } finally { if (alive.current) setBusy(false); }
  };
  const confirmDiscard = (fn: () => void) => {
    if (!dirty) return fn();
    modal.confirm({title: '有未保存修改，是否放弃？', okText: '放弃修改', cancelText: '继续编辑', onOk: fn});
  };
  const showPreview = async (value: CompositionDraft) => {
    const result = await previewComposition(projectRef, value);
    if (!alive.current) return;
    // Unsaved preview has no persisted composition identity.
    setDraft({...result.document, composition_id: value.composition_id, revision: value.revision});
    setHtml(result.html); setPreviewDirty(false);
  };
  const open = (id: string) => confirmDiscard(() => { void run(async () => {
    const value = await fetchComposition(projectRef, id);
    if (!alive.current) return;
    setDraft(value); setDirty(false); setStale(false); setHtml('');
    await showPreview(value);
    const checked = await checkComposition(projectRef, id);
    if (alive.current) setStale(Boolean(checked.changes.length));
  }); });
  const add = (block: ReportBlock) => {
    const existing = draft.blocks.find(b => b.block_id === block.block_id);
    if (existing) {
      edit({...draft, deleted_block_ids: draft.deleted_block_ids.filter(id => id !== existing.block_id), hidden_block_ids: draft.hidden_block_ids.filter(id => id !== existing.block_id)});
      return;
    }
    if (draft.blocks.length >= 40) { void message.warning('每份报告最多40个元素，包含暂时删除的元素'); return; }
    edit({...draft, blocks: [...draft.blocks, block]});
  };
  const patch = (id: string, value: Partial<ReportBlock>) => edit({...draft, blocks: draft.blocks.map(b => b.block_id === id ? {...b, ...value} : b)});
  const move = (id: string, delta: number) => {
    const blocks = [...draft.blocks]; const index = blocks.findIndex(b => b.block_id === id);
    const target = index + delta;
    if (target >= 0 && target < blocks.length) { [blocks[index], blocks[target]] = [blocks[target], blocks[index]]; edit({...draft, blocks}); }
  };
  const save = (refresh = false) => { void run(async () => {
    const saved = await saveComposition(projectRef, draft, refresh);
    if (!alive.current) return;
    setDraft(saved); setDirty(false); if (refresh) setStale(false);
    const list = await fetchCompositions(projectRef);
    if (!alive.current) return;
    setItems(list.items);
    await showPreview(saved);
    void message.success(refresh ? '计算数据已刷新并保存' : '报告已保存');
  }); };
  const exportFile = (print = false) => { void run(async () => {
    if (!draft.composition_id || dirty) return;
    const url = await compositionHtml(projectRef, draft.composition_id, print);
    if (print) {
      const frame = document.createElement('iframe'); frame.style.display = 'none';
      frame.setAttribute('sandbox', 'allow-scripts allow-modals allow-same-origin');
      frame.src = url; document.body.appendChild(frame);
      // Keep alive while the browser print dialog is open.
      setTimeout(() => { frame.remove(); URL.revokeObjectURL(url); }, 300000);
    } else {
      const a = document.createElement('a'); a.href = url; a.download = `${draft.title}.html`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
  }); };
  const models = candidates.filter(c => c.type === 'task.summary');
  const shown = candidates.filter(c => (!selectedModels.length || !c.task_id || selectedModels.includes(c.task_id)) &&
    `${c.title} ${c.type_label} ${c.task_id} ${c.group_id}`.toLowerCase().includes(query.toLowerCase()));
  const canExport = Boolean(draft.composition_id && !dirty && !busy);
  return <Drawer open title={`${projectName} · 专题报告`} width="96vw" onClose={() => confirmDiscard(onClose)} maskClosable={false}>
    <Spin spinning={busy}>
      <Space wrap className="rb-editor-toolbar">
        <Select aria-label="已保存专题报告" placeholder="打开已保存报告" style={{width: 220}} value={draft.composition_id}
          options={items.map(i => ({value: i.composition_id, label: i.title}))} onChange={open} disabled={busy}/>
        <Button disabled={busy} onClick={() => confirmDiscard(() => {setDraft(blank()); setDirty(false); setHtml(''); setStale(false); setPreviewDirty(true);})}>新建专题报告</Button>
        <Button disabled={busy || !draft.blocks.length} onClick={() => void run(() => showPreview(draft))}>更新预览</Button>
        <Button disabled={busy || !legacyHidden.length || !draft.blocks.length} onClick={() => {
          const ids = mapLegacyHiddenBlocks(draft.blocks.map(b => b.block_id), candidates, legacyHidden);
          edit({...draft, hidden_block_ids: [...new Set([...draft.hidden_block_ids, ...ids])]});
          void message.info(`已匹配${ids.length}个元素；旧图序号或同名任务不自动映射，请单独核对。`);
        }}>沿用完整报告隐藏</Button>
        <Button type="primary" disabled={busy || !draft.blocks.length} onClick={() => save()}>保存专题报告</Button>
        <Button disabled={!canExport} onClick={() => exportFile()}>导出 HTML</Button>
        <Button disabled={!canExport} onClick={() => exportFile(true)}>打印 / PDF</Button>
        <Button disabled={busy || !draft.composition_id} onClick={() => void run(async () => {
          const checked = await checkComposition(projectRef, draft.composition_id!);
          setStale(Boolean(checked.changes.length));
          void message.info(checked.changes.length ? '计算数据有更新，当前报告仍保留原数据' : '计算数据未发生变化');
        })}>检查数据更新</Button>
        <Button disabled={busy || !draft.blocks.length} onClick={() => modal.confirm({title: '用最新计算数据刷新并保存这份报告？',
          content: '元素顺序、标题与人工文字会保留，计算证据会替换为当前版本。', okText: '刷新并保存', onOk: () => save(true)})}>刷新计算数据</Button>
      </Space>
      {error && <Alert type="error" message={error} showIcon/>}
      {stale && <Alert type="warning" showIcon message="计算数据可能已更新。当前报告保留原证据，可明确刷新计算数据后重新核对。"/>}
      <div className="rb-editor-grid">
        <div className="rb-editor-controls">
          <Input aria-label="专题报告标题" value={draft.title} maxLength={200} onChange={e => edit({...draft, title: e.target.value})} disabled={busy}/>
          <Card size="small" title="添加报告元素">
            <Select mode="multiple" showSearch optionFilterProp="label" aria-label="选择模型" placeholder="筛选模型（可多选）" value={selectedModels} onChange={setSelectedModels}
              options={models.map(c => ({value: c.task_id!, label: `${c.title} · ${c.task_id}`}))} style={{width: '100%'}} disabled={busy}/>
            <Input.Search placeholder="搜索任务或元素类型" value={query} onChange={e => setQuery(e.target.value)}/>
            <Select aria-label="选择报告元素" showSearch optionFilterProp="label" placeholder="选择已有结果" value={selectedCandidate} onChange={setSelectedCandidate}
              style={{width: '100%'}} disabled={busy} options={shown.map(c => ({value: c.block_id,
                label: `${c.title} · ${c.type_label} · ${statusLabel[c.availability] || c.availability}`, disabled: !c.resolvable}))}/>
            {selectedCandidate && (() => {const c = candidates.find(item => item.block_id === selectedCandidate); return c &&
              <div className="rb-editor-hint">{c.summary} · {statusLabel[c.full_report_visibility] || c.full_report_visibility} · {c.validation.status}<br/>{c.detail} {c.freshness.basis}</div>;})()}
            <Space wrap>
              <Button disabled={busy || !selectedCandidate} onClick={() => {const c = candidates.find(item => item.block_id === selectedCandidate); if (c) add({...c, title: `${c.title} · ${c.type_label}`});}}>添加元素</Button>
              <Button disabled={busy || selectedModels.length < 2 || selectedModels.length > 12} onClick={() => {
                const ids = [...selectedModels].sort(); const variant = 'params:' + ids.join(',');
                if (draft.blocks.some(b => b.variant === variant)) {void message.info('已添加这组参数对照'); return;}
                add({block_id: 'draft_' + newId(), type: 'project.comparison', title: '所选模型参数对照', task_ids: ids, variant});
              }}>添加参数对照</Button>
              <Button disabled={busy} onClick={() => add({block_id: 'blk_txt_' + newId(), type: 'text.analysis', title: '分析文本', text: '在此填写分析内容。'})}>添加文字</Button>
            </Space>
          </Card>
          <Space.Compact style={{width: '100%'}}>
            <Input aria-label="新分组标题" placeholder="新分组名称" value={newGroup} maxLength={200} onChange={e => setNewGroup(e.target.value)} disabled={busy}/>
            <Button disabled={busy || !newGroup.trim()} onClick={() => {edit({...draft, groups: [...draft.groups, {group_id: newId(), title: newGroup.trim(), block_ids: []}]}); setNewGroup('');}}>添加分组</Button>
          </Space.Compact>
          {draft.groups.map(g => <Space.Compact key={g.group_id} style={{width: '100%'}}>
            <Input aria-label="分组标题" value={g.title} maxLength={200} disabled={busy} onChange={e => edit({...draft, groups: draft.groups.map(x => x.group_id === g.group_id ? {...x, title: e.target.value} : x)})}/>
            <Button disabled={busy} onClick={() => edit({...draft, groups: draft.groups.filter(x => x.group_id !== g.group_id)})}>移除分组</Button>
          </Space.Compact>)}
          {draft.blocks.length === 0 && <Empty description="从上方添加已有计算结果或文字"/>}
          {draft.blocks.map((b, index) => {
            const deleted = draft.deleted_block_ids.includes(b.block_id), hidden = draft.hidden_block_ids.includes(b.block_id);
            return <Card size="small" key={b.block_id} className={deleted ? 'rb-editor-deleted' : ''} data-block-id={b.block_id} title={<Space>{index + 1}. {b.type_label || b.type}{hidden && <Tag>已隐藏</Tag>}{deleted && <Tag>已删除</Tag>}</Space>}>
              <Input aria-label="元素标题" value={b.title} maxLength={200} disabled={busy || deleted} onChange={e => patch(b.block_id, {title: e.target.value})}/>
              {b.type === 'text.analysis' && <Input.TextArea aria-label="分析文本" rows={4} value={b.text} maxLength={4000} disabled={busy || deleted} onChange={e => patch(b.block_id, {text: e.target.value})}/>}
              <Select aria-label="元素分组" placeholder="不分组" allowClear value={draft.groups.find(g => g.block_ids.includes(b.block_id))?.group_id}
                style={{width: '100%'}} disabled={busy || deleted} options={draft.groups.map(g => ({value: g.group_id, label: g.title}))}
                onChange={id => edit({...draft, groups: draft.groups.map(g => ({...g, block_ids: [...g.block_ids.filter(x => x !== b.block_id), ...(g.group_id === id ? [b.block_id] : [])]}))})}/>
              <Space wrap>
                <Button size="small" disabled={busy || deleted || index === 0} onClick={() => move(b.block_id, -1)}>上移</Button>
                <Button size="small" disabled={busy || deleted || index === draft.blocks.length - 1} onClick={() => move(b.block_id, 1)}>下移</Button>
                <Button size="small" disabled={busy || deleted} onClick={() => edit({...draft, hidden_block_ids: hidden ? draft.hidden_block_ids.filter(id => id !== b.block_id) : [...draft.hidden_block_ids, b.block_id]})}>{hidden ? '取消隐藏' : '隐藏'}</Button>
                <Button size="small" disabled={busy} onClick={() => edit({...draft, deleted_block_ids: deleted ? draft.deleted_block_ids.filter(id => id !== b.block_id) : [...draft.deleted_block_ids, b.block_id]})}>{deleted ? '恢复元素' : '删除元素'}</Button>
              </Space>
            </Card>;
          })}
        </div>
        <div className="rb-editor-preview">
          {previewDirty && <Alert type="info" message="预览尚未更新；保存或点击更新预览后显示当前内容。导出前请保存。"/>}
          {html ? <iframe title="专题报告预览" srcDoc={html} sandbox="allow-scripts" referrerPolicy="no-referrer"/> : <Empty description="添加元素后点击更新预览"/>}
        </div>
      </div>
    </Spin>
  </Drawer>;
}
