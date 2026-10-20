import {useEffect,useState} from 'react';
import {Alert,App,Button,Card,Drawer,Empty,Input,Space,Spin,Typography} from 'antd';
import {ArrowDownOutlined,ArrowUpOutlined,DeleteOutlined,EditOutlined} from '@ant-design/icons';
import {exportTopic,fetchTopic,previewTopic,rebuildTopic,updateTopicContent} from '../../api/topicReports';
import type {TopicReport} from '../../api/topicReports';
import {ReportQuestions} from '../ai/TopicReportLinks';

export default function TopicReportEditor({topicId,onClose,onSaved}: {topicId:string;connectionId?:string|null;onClose:()=>void;onSaved?:()=>void}) {
  const {message,modal}=App.useApp();const [id,setId]=useState(topicId);const [doc,setDoc]=useState<TopicReport>();const [html,setHtml]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [editing,setEditing]=useState(false);const [dirty,setDirty]=useState(false);const [title,setTitle]=useState('');const [notes,setNotes]=useState('');const [order,setOrder]=useState<string[]>([]);const [deleted,setDeleted]=useState<string[]>([]);
  const accept=async(value:TopicReport)=>{setDoc(value);setTitle(value.title);setNotes(value.simple?.notes||'');setOrder(value.blocks.map(b=>b.block_id));setDeleted(value.deleted_block_ids);setDirty(false);if(value.simple)setHtml((await previewTopic(value.topic_id)).html);};
  useEffect(()=>{let active=true;setBusy(true);setHtml('');fetchTopic(id).then(async value=>{if(active)await accept(value);}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};},[id]);
  const run=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  const save=()=>doc&&run(async()=>{await accept(await updateTopicContent(id,{expected_revision:doc.revision,title,notes,blocks:order,deleted_block_ids:deleted}));onSaved?.();setEditing(false);message.success('报告已保存');});
  const rebuild=()=>run(async()=>{const value=await rebuildTopic(id);await accept(value);setId(value.topic_id);onSaved?.();});
  const download=(print=false)=>run(async()=>{const url=await exportTopic(id,print);if(print){const f=document.createElement('iframe');f.style.display='none';f.src=url;document.body.appendChild(f);setTimeout(()=>{f.remove();URL.revokeObjectURL(url);},60000);}else{const a=document.createElement('a');a.href=url;a.download=(doc?.title||'科研报告')+'.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}});
  const move=(index:number,offset:number)=>{const next=[...order];[next[index],next[index+offset]]=[next[index+offset],next[index]];setOrder(next);setDirty(true);};
  const close=()=>dirty?modal.confirm({title:'有未保存的修改，要放弃吗？',okText:'放弃修改',cancelText:'继续编辑',onOk:onClose}):onClose();
  return <Drawer open title="科研报告" width="min(1120px, 96vw)" onClose={close} destroyOnClose>
    {error&&<Alert type="error" message={error} showIcon style={{marginBottom:12}}/>}
    {!doc?<Spin/>:!doc.simple?<Empty description="这是一份旧版草案。按新方式整理后，可以直接查看结果、构型和需要注意的问题。"><Button type="primary" loading={busy} onClick={()=>void rebuild()}>重新生成简明报告</Button></Empty>:<>
      <Space wrap style={{marginBottom:16}}>
        <Button aria-label="编辑报告" icon={<EditOutlined/>} disabled={busy} onClick={()=>setEditing(v=>!v)}>{editing?'收起编辑':'编辑报告'}</Button>
        <Button disabled={busy||dirty} onClick={()=>void download()}>下载 HTML</Button><Button disabled={busy||dirty} onClick={()=>void download(true)}>导出 PDF</Button>
        <Button disabled={busy||dirty} onClick={()=>void rebuild()}>用最新结果重新生成</Button>
      </Space>
      {!!doc.simple.questions.length&&<ReportQuestions item={{topic_id:id,revision:doc.revision,questions:doc.simple.questions}} onDone={()=>void run(async()=>{await accept(await fetchTopic(id));onSaved?.();})}/>}
      {editing&&<Card size="small" style={{marginBottom:16}}>
        <Typography.Paragraph type="secondary">可修改标题、补充文字、删除或调整内容顺序。底层能量和计算结果会保留。</Typography.Paragraph>
        <Input aria-label="报告标题" value={title} maxLength={200} onChange={e=>{setTitle(e.target.value);setDirty(true);}} style={{marginBottom:12}}/>
        <Input.TextArea aria-label="补充说明" placeholder="写下你的解释或补充说明" value={notes} maxLength={8000} autoSize={{minRows:3,maxRows:10}} onChange={e=>{setNotes(e.target.value);setDirty(true);}}/>
        {order.map((bid,index)=>{const b=doc.blocks.find(b=>b.block_id===bid)!;const removed=deleted.includes(bid);return <div key={bid} style={{display:'flex',gap:8,alignItems:'center',marginTop:12,opacity:removed?.5:1}}><span style={{flex:1}}>{b.title}</span><Button aria-label={`上移-${b.title}`} size="small" icon={<ArrowUpOutlined/>} disabled={!index} onClick={()=>move(index,-1)}/><Button aria-label={`下移-${b.title}`} size="small" icon={<ArrowDownOutlined/>} disabled={index===order.length-1} onClick={()=>move(index,1)}/><Button aria-label={`${removed?'恢复':'删除'}-${b.title}`} size="small" icon={<DeleteOutlined/>} onClick={()=>{setDeleted(removed?deleted.filter(x=>x!==bid):[...deleted,bid]);setDirty(true);}}>{removed?'恢复':'删除'}</Button></div>;})}
        <Button type="primary" disabled={!dirty||busy} loading={busy} onClick={()=>void save()} style={{marginTop:16}}>保存修改</Button>
      </Card>}
      {doc.freshness?.stale&&<Alert type="warning" message="有新的计算结果。这份报告仍保留生成时的数据，可点击“用最新结果重新生成”更新。"/>}
      {!html?<Spin tip="正在整理展示…"/>:<iframe title="科研报告预览" sandbox="allow-scripts allow-modals" srcDoc={html} style={{width:'100%',height:'calc(100vh - 180px)',border:0,borderRadius:12,background:'#f7f8fa'}}/>}
    </>}
  </Drawer>;
}
