import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Collapse, Empty, Input, Modal, Spin, Tag } from 'antd';
import { FileTextOutlined, FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons';
import { getAIWorkspace, listAIWorkspace, readAIWorkspace } from '../../api/aiChat';
import type { AIRun, AIWorkspaceFile, AIWorkspaceListing, AIWorkspaceMap } from '../../api/aiChat';

const errorText = (error: unknown) => error instanceof Error ? error.message : '读取失败';
const TOOL_NAMES: Record<string, string> = { search_work_experience: '检索个人操作经验', list_workspace: '浏览目录', read_workspace: '读取文件', write_workspace: '创建草稿', find_project_tasks: '定位任务', get_task_inspections: '查询最近巡检', get_inspection_evidence: '读取巡检数值证据', get_opt_runs: '查询OPT自主处置', get_task_parameter_history: '查询实际参数记录', get_remote_task_evidence: '远端只读补证', check_structure: '检查结构合理性与变化', get_structure_summary: '读取结构概览', get_structure_environment: '分析原子环境', compare_structures: '对比模型结构' };

export default function WorkspacePanel({ conversationId, runs, enabled }: { conversationId: string; runs: AIRun[]; enabled: boolean }) {
  const [map, setMap] = useState<AIWorkspaceMap | null>(null);
  const [listing, setListing] = useState<AIWorkspaceListing | null>(null);
  const [path, setPath] = useState('');
  const [file, setFile] = useState<AIWorkspaceFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const alive = useRef(true);
  const requestSeq = useRef(0);
  useEffect(() => {
    alive.current = true;
    void getAIWorkspace(conversationId).then((value) => { if (alive.current) setMap(value); }).catch((e) => { if (alive.current) setError(errorText(e)); });
    return () => { alive.current = false; requestSeq.current++; };
  }, [conversationId]);
  const browse = async (directory: string, offset = 0) => {
    const seq = ++requestSeq.current;
    setBusy(true); setError('');
    try {
      const value = await listAIWorkspace(conversationId, directory, offset);
      if (alive.current && seq === requestSeq.current) { setListing(value); setPath(directory); }
    } catch (e) { if (alive.current && seq === requestSeq.current) setError(errorText(e)); }
    finally { if (alive.current && seq === requestSeq.current) setBusy(false); }
  };
  const read = async (name: string, offset = 0, tail = false) => {
    const seq = ++requestSeq.current;
    setBusy(true); setError('');
    try { const value = await readAIWorkspace(conversationId, name, offset, tail); if (alive.current && seq === requestSeq.current) setFile(value); }
    catch (e) { if (alive.current && seq === requestSeq.current) setError(errorText(e)); }
    finally { if (alive.current && seq === requestSeq.current) setBusy(false); }
  };
  const events = runs.flatMap((run) => (run.tool_events ?? []).map((event) => ({ ...event, runId: run.id }))).slice(0, 36);
  return <div className="ai-file-panel">
    {error && <Alert type="warning" showIcon message={error} />}
    {map ? <>
      <p className="ai-muted">{enabled ? '模型可读取结构、分析原子环境与结构变化，查询巡检和实际参数记录，必要时远端只读补证，读取文件、创建草稿。' : '模型工具未启用，可在会话设置中开启工作区。'}正式数据只读，草稿不会自动应用。</p>
      <h4>目录地图</h4>
      {map.roots.map((root) => <button className="ai-run-row" key={root.path} onClick={() => { void browse(root.path.replace(/\/$/, '')); }}>
        <strong><FolderOpenOutlined /> {root.path}<Tag style={{ marginLeft: 8 }}>{root.access === 'read_write' ? '可写草稿' : '只读'}</Tag></strong><span>{root.purpose}</span>
      </button>)}
      <Collapse ghost size="small" items={[
        { key: 'rules', label: '目录与来源规则', children: <ul className="ai-context-hints">{map.rules.map((rule) => <li key={rule}>{rule}</li>)}</ul> },
        { key: 'locations', label: `任务位置（${map.task_locations.length}）`, children: map.task_locations.map((task) => <div className="ai-record" key={task.task_id}>
          <strong>{task.name}</strong>{task.path ? <Button type="link" size="small" onClick={() => { void browse(task.path!); }}>{task.path}</Button> : <span>本地路径未映射</span>}
          <span>远端：{task.remote_dir || '未登记'}</span><span>输出：{task.output_dir || '主目录'} · 结构来源：{task.structure_source_dir || '未记录'}</span>
        </div>) },
      ]} />
    </> : <Spin size="small" />}
    <h4>浏览文件</h4>
    <Input.Search aria-label="工作区相对路径" value={path} placeholder="例如 project/opt 或 work" onChange={(e) => setPath(e.target.value)} onSearch={(value) => { void browse(value); }} enterButton="浏览" />
    <div className="ai-actions" style={{ marginTop: 8 }}><Button size="small" onClick={() => { void browse(''); }}>根目录</Button>
      <Button size="small" disabled={!listing?.path} onClick={() => { void browse(listing!.path.replace(/\/$/, '').split('/').slice(0, -1).join('/')); }}>上一级</Button>
      <Button size="small" icon={<ReloadOutlined />} onClick={() => { void browse(listing?.path ?? path); }}>刷新</Button></div>
    {busy && <Spin size="small" />}
    {listing && <><p className="ai-muted">{listing.path || '根目录'} · {listing.total} 项{listing.missing ? ' · 本地目录尚未生成' : ''}</p>
      {listing.items.map((item) => <button className="ai-file-row" key={item.path} onClick={() => { void (item.type === 'directory' ? browse(item.path) : read(item.path)); }}>
        {item.type === 'directory' ? <FolderOpenOutlined /> : <FileTextOutlined />}<span>{item.name}</span><small>{item.bytes == null || item.type === 'directory' ? '' : `${(item.bytes / 1024).toFixed(1)} KiB`}</small>
      </button>)}
      {listing.next_offset != null && <Button size="small" onClick={() => { void browse(listing.path, listing.next_offset!); }}>下一页</Button>}
      {!listing.items.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件" />}
    </>}
    <h4>模型工具记录</h4>
    {events.length ? events.map((event, index) => <div className="ai-record" key={`${event.runId}-${event.id}-${index}`}>
      <strong>{TOOL_NAMES[event.name] ?? event.name} · {event.status === 'completed' ? '成功' : event.status === 'running' ? '执行中' : event.status === 'interrupted' ? '已中断' : '失败'}</strong>
      <span>{String(event.arguments?.path ?? event.arguments?.query ?? event.arguments?.task_id ?? '')}</span><span>{event.at.replace('T', ' ')}</span>
      {event.name === 'get_task_inspections' && event.status === 'completed' && <span>{event.result.retention_unit === 'calculation_directory' ? `已读取 ${String(event.result.returned ?? 0)} 个目录的最新结果` : `已读取 ${String(event.result.returned ?? 0)} 次巡检`}</span>}
      {event.name === 'get_remote_task_evidence' && event.status === 'completed' && <span>
        {event.result.status === 'collected' ? event.result.cache_hit ? '复用近期远端只读证据' : '已按需采集远端只读证据' : '沿用本地证据，未查询远端'}
        {typeof event.result.collected_at === 'string' ? ` · ${event.result.collected_at.replace('T', ' ')}` : ''}
        {event.result.current_state ? ` · 状态 ${String((event.result.current_state as Record<string, unknown>).state ?? 'UNKNOWN')}` : ''}
      </span>}
      {event.result?.error != null && <span className="ai-run-error">{String(event.result.error)}</span>}
      {event.name === 'write_workspace' && event.status === 'completed' && <Button size="small" onClick={() => { void read(String(event.result.path)); }}>查看草稿</Button>}
    </div>) : <p className="ai-muted">暂无工具调用。可让模型分析某任务最近三个计算目录的最新结果，需要时再读取实际文件。</p>}
    <Modal title={file?.path ?? '文件内容'} open={!!file} onCancel={() => setFile(null)} footer={null} width={900}>
      {file && <><p className="ai-muted">本地文件 · {file.bytes} 字节 · 当前从字节 {file.offset} 开始；{file.next_offset == null ? '已到文件末尾' : '还有后续内容'}。未实时核对远端。</p>
        <pre className="ai-json">{file.content}</pre><div className="ai-actions">
          <Button disabled={busy || file.offset === 0} onClick={() => { void read(file.path); }}>文件开头</Button>
          <Button disabled={busy || file.next_offset == null} onClick={() => { void read(file.path, file.next_offset!); }}>下一段</Button>
          <Button disabled={busy} onClick={() => { void read(file.path, 0, true); }}>文件尾部</Button>
        </div><p className="ai-muted">SHA256（{file.hash_scope === 'full_virtual_file' ? '完整证据文件' : '当前字节片段'}）：{file.sha256}</p></>}
    </Modal>
  </div>;
}
