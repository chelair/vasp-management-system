import {useEffect,useState} from 'react';
import {Alert,Button,Empty,Tag} from 'antd';
import {listTopics} from '../../api/topicReports';
import type {TopicMeta} from '../../api/topicReports';
import type {AIRun} from '../../api/aiChat';

export default function TopicReportLinks({conversationId,runs,onOpen,revision=0}: {conversationId:string;runs:AIRun[];onOpen:(id:string)=>void;revision?:number}) {
  const [items,setItems]=useState<TopicMeta[]>([]);const [error,setError]=useState('');
  const changes=runs.map(r=>r.id+':'+r.status+':'+r.tool_events.length).join('|');
  useEffect(()=>{
    let active=true;
    listTopics(conversationId).then(result=>{if(active){setItems(result.items);setError('');}}).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[conversationId,changes,revision]);
  return <div>{error&&<Alert type="error" message={error}/>}{!items.length?<Empty description="在对话中提出研究问题并要求生成专题报告，即可在这里重新打开。"/>:items.map(item=><div key={item.topic_id} className="ai-record">
    <strong>{item.title}</strong><span>{item.updated_at.replace('T',' ').slice(0,19)} <Tag>{item.stage==='saved'?'已保存':'草案'}</Tag></span>
    <Button onClick={()=>onOpen(item.topic_id)}>打开专题报告</Button>
  </div>)}</div>;
}
