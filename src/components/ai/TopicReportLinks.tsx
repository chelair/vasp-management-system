import {useEffect,useState} from 'react';
import {Alert,Button,Card,Empty,Input,Radio,Space,Typography} from 'antd';
import {answerTopic,listTopics} from '../../api/topicReports';
import type {TopicMeta,TopicQuestion} from '../../api/topicReports';
import type {AIRun} from '../../api/aiChat';

export function ReportQuestions({item,onDone,disabled=false}:{item:{topic_id:string;revision:number;questions:TopicQuestion[]};onDone:()=>void;disabled?:boolean}) {
  const [answers,setAnswers]=useState<Record<string,string>>({});const [custom,setCustom]=useState<Record<string,string>>({});const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const questions=item.questions.slice(0,3);
  const submit=async()=>{setBusy(true);setError('');try{const values=Object.fromEntries(questions.map(q=>[q.id,answers[q.id]==='__custom'?custom[q.id]:answers[q.id]]).filter(([,v])=>v?.trim()));if(!Object.keys(values).length){setError('请选择一项，或填写你的回答。');return;}const updated=await answerTopic(item.topic_id,item.revision,values);window.dispatchEvent(new CustomEvent('vasp:topic-updated',{detail:{conversationId:updated.conversation_id,error:updated.continuation_error}}));setAnswers({});setCustom({});onDone();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <Card size="small" style={{margin:'12px 0',maxWidth:680}} title="确认一下，就可以继续">
    {error&&<Alert type="error" message={error}/>}
    {questions.map(q=><div key={q.id} style={{marginBottom:18}}><Typography.Paragraph strong>{q.title}</Typography.Paragraph>
      {q.error&&<Typography.Paragraph type="danger">{q.error}</Typography.Paragraph>}
      <Radio.Group value={answers[q.id]} onChange={e=>setAnswers(old=>({...old,[q.id]:e.target.value}))} disabled={busy||disabled}><Space direction="vertical">
        {q.options.map(option=><Radio key={option.value} value={option.value}>{option.label}{option.description&&<span style={{color:'#8a94a3',marginLeft:8}}>{option.description}</span>}</Radio>)}
        <Radio value="__custom">自己填写</Radio>
      </Space></Radio.Group>
      {(answers[q.id]==='__custom'||!q.options.length)&&<Input.TextArea aria-label={`${q.title}-自定义回答`} value={custom[q.id]||''} onFocus={()=>setAnswers(old=>({...old,[q.id]:'__custom'}))} onChange={e=>{setAnswers(old=>({...old,[q.id]:'__custom'}));setCustom(old=>({...old,[q.id]:e.target.value}));}} placeholder={'可直接描述你的研究意图、反应位置或选择'} autoSize={{minRows:1,maxRows:3}} maxLength={300} style={{marginTop:10}}/>}
      {q.options.length>0&&<div style={{color:'#8a94a3',fontSize:12,marginTop:8}}>{q.hint}</div>}
    </div>)}
    <Button type="primary" loading={busy} disabled={disabled} onClick={()=>void submit()}>按我的回答继续</Button>
  </Card>;
}

export default function TopicReportLinks({conversationId,runs,onOpen,revision=0,inline=false}: {conversationId:string;runs:AIRun[];onOpen:(id:string)=>void;revision?:number;inline?:boolean}) {
  const [items,setItems]=useState<TopicMeta[]>([]);const [error,setError]=useState('');const [refresh,setRefresh]=useState(0);
  useEffect(()=>{const update=()=>setRefresh(v=>v+1);window.addEventListener('vasp:topic-updated',update);return()=>window.removeEventListener('vasp:topic-updated',update);},[]);
  const changes=runs.map(r=>r.id+':'+r.status+':'+r.tool_events.length).join('|');
  useEffect(()=>{let active=true;listTopics(conversationId).then(result=>{if(active){setItems(result.items);setError('');}}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[conversationId,changes,revision,refresh]);
  const shown=inline?items.filter(i=>i.simple).slice(0,1):items;
  if(inline&&!shown.length)return null;
  const running=runs.some(r=>['queued','running'].includes(r.status));
  return <div>{error&&<Alert type="error" message={error}/>}{!shown.length?<Empty description="输入一句话，告诉 AI 你想研究什么。"/>:shown.map(item=><div key={item.topic_id} className="ai-record" style={inline?{padding:16,marginTop:12,border:'1px solid #dce6f3',borderRadius:12}:undefined}>
    <strong>{item.title}</strong>
    {item.questions?.length?(inline?<ReportQuestions item={{...item,questions:item.questions}} disabled={running} onDone={()=>undefined}/>:<span style={{color:'#667085'}}>需要你确认一项选择，请在对话中回答。</span>):<span style={{color:'#667085'}}>{item.result_summary|| (item.simple?'已整理为报告，可直接查看。':['prepared','planned'].includes(item.stage)?'旧版草案，可按新方式重新生成。':'已保存')}</span>}
    <Button onClick={()=>onOpen(item.topic_id)}>{item.questions?.length?'查看已有内容':'查看报告'}</Button>
  </div>)}</div>;
}
