import {useEffect,useState} from 'react';
import {App,Alert,Button,Card,Collapse,Drawer,Input,Modal,Select,Space,Switch,Tabs,Tag} from 'antd';
import {request} from '../../api/client';
import type {AIConnection} from '../../api/aiChat';

interface Memory {id:string;title:string;body:string;confirmed:boolean;disabled:boolean;created_at:string;sources:Record<string,unknown>[]}
interface Data {settings:{enabled:boolean;connection_id:string|null;status:string;error:string;updated_at:string};items:Memory[];operations:Record<string,unknown>[];document:string;note:string}
const root='/ai/chat/work-experience';

export default function WorkExperience({open,close,connections}:{open:boolean;close:()=>void;connections:AIConnection[]}) {
  const {message}=App.useApp();
  const [data,setData]=useState<Data>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [editing,setEditing]=useState<Memory>();
  const reload=async()=>{try{setData(await request<Data>(root));setError('');}catch(e){setError(String(e));}};
  useEffect(()=>{if(open)void reload();},[open]);
  const settings=async(enabled:boolean,connection_id:string|null)=>{
    setBusy(true);
    try {await request(root+'/settings',{method:'PUT',body:JSON.stringify({enabled,connection_id})});await reload();}
    catch(e){message.error(String(e));}finally{setBusy(false);}
  };
  const update=async(item:Memory,values:Partial<Memory>)=>{
    try{await request(root+'/'+item.id,{method:'PUT',body:JSON.stringify(values)});await reload();return true;}
    catch(e){message.error(String(e));return false;}
  };
  const download=()=>{
    const url=URL.createObjectURL(new Blob([data?.document??''],{type:'text/markdown;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='个人操作经验.md';link.click();URL.revokeObjectURL(url);
  };
  return <Drawer title="个人操作经验" width={760} open={open} onClose={close}>
    {error&&<Alert type="warning" message={error}/>}
    <p>每周从本人的近期操作中整理经验，供模型按需检索。提交成功不等于计算收敛；自动整理的内容先作为待核实参考。</p>
    <Space wrap style={{marginBottom:16}}>
      <span>每周整理</span><Switch checked={!!data?.settings.enabled} disabled={busy||!data} onChange={v=>void settings(v,data?.settings.connection_id??connections.find(c=>c.is_default)?.id??null)}/>
      <Select style={{width:220}} placeholder="选择整理模型" value={data?.settings.connection_id??undefined} disabled={busy}
        options={connections.map(c=>({value:c.id,label:c.name+' · '+c.model}))}
        onChange={v=>void settings(!!data?.settings.enabled,v)}/>
      <Button loading={busy} disabled={!data?.settings.connection_id} onClick={async()=>{
        setBusy(true);
        try{const r=await request<{added:number}>(root+'/learn',{method:'POST'});message.success(`已整理 ${r.added} 条经验`);}
        catch(e){message.error(String(e));}finally{setBusy(false);await reload();}
      }}>立即整理</Button>
      <Button onClick={()=>void reload()}>刷新</Button>
    </Space>
    {data?.settings.error&&<Alert type="warning" showIcon message={data.settings.error} style={{marginBottom:12}}/>}
    {data?.settings.status==='running'&&<Tag color="processing">正在整理</Tag>}
    <p style={{color:'#888'}}>每次最多40条操作、16000字符输入、2048输出token；每周自动一次，可手动补试一次。{data?.settings.updated_at&&` 最近处理：${data.settings.updated_at}`}</p>
    <Tabs items={[
      {key:'memory',label:'经验',children:<>
        <Button onClick={download} disabled={!data?.items.length} style={{marginBottom:12}}>下载知识文档</Button>
        {!data?.items.length&&<p>暂时没有经验。正常操作会自动记入日志，整理后出现在这里。</p>}
        {data?.items.map(item=><Card size="small" key={item.id} title={item.title} style={{marginBottom:12,opacity:item.disabled ? 0.6 : 1}}
          extra={<Space><Tag>{item.disabled?'已停用':item.confirmed?'已确认':'待核实'}</Tag><Button size="small" onClick={()=>setEditing({...item})}>修改</Button>
            <Button size="small" onClick={()=>void update(item,{confirmed:!item.confirmed})}>{item.confirmed?'取消确认':'确认经验'}</Button>
            <Button size="small" onClick={()=>void update(item,{disabled:!item.disabled})}>{item.disabled?'恢复参考':'不再参考'}</Button></Space>}>
          <p style={{whiteSpace:'pre-wrap'}}>{item.body}</p>
          <Collapse size="small" items={[{key:'sources',label:`操作来源 ${item.sources.length} 条 · ${item.created_at}`,children:<pre style={{whiteSpace:'pre-wrap',maxHeight:300,overflow:'auto'}}>{JSON.stringify(item.sources,null,2)}</pre>}]}/>
        </Card>)}
      </>},
      {key:'operations',label:'近期操作',children:<><p>最近7天本人在可访问项目中的关键任务操作，最多显示100条。</p>
        {data?.operations.map((row,i)=><Card key={String(row.id??i)} size="small" style={{marginBottom:8}}>
          <b>{String(row.task??'')} · {String(row.action??'')}</b><p>{String(row.at??'')} · {String(row.result??'')}</p>
          <Collapse size="small" items={[{key:'detail',label:'操作详情',children:<pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(row,null,2)}</pre>}]}/>
        </Card>)}
      </>}
    ]}/>
    <Modal title="修改经验" open={!!editing} onCancel={()=>setEditing(undefined)} onOk={async()=>{
      if(editing&&await update(editing,{title:editing.title,body:editing.body,confirmed:true}))setEditing(undefined);
    }}>
      <Input maxLength={120} value={editing?.title} onChange={e=>setEditing(v=>v&&({...v,title:e.target.value}))}/>
      <Input.TextArea rows={8} maxLength={3000} value={editing?.body} onChange={e=>setEditing(v=>v&&({...v,body:e.target.value}))} style={{marginTop:12}}/>
    </Modal>
  </Drawer>;
}
