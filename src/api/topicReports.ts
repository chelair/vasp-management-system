import {request,requestBlobUrl} from './client';
export interface TopicBlock {block_id:string;title:string;section:string;origin:'r2'|'question'|'property_fact'|'ai_text';type:string;text:string;data_status:string;source_refs:{evidence_id:string;version:string}[]}
export interface TopicCandidate {block_id:string;title:string;type:string;task_id:string;project_id:string;availability:string}
export interface TopicFact {fact_id:string;label:string;value:number;units:string;validation_status:string}
export interface TopicMeta {topic_id:string;report_type:'topic';title:string;revision:number;stage:string;updated_at:string;conversation_id:string}
export interface TopicReport extends TopicMeta {
  original_question:string;created_at:string;project_ids:string[];
  sections:{section_id:string;title:string}[];
  blocks:TopicBlock[];hidden_block_ids:string[];deleted_block_ids:string[];
  narratives:Record<string,{ai_text:string;user_text:string|null;kind:string;model:string}>;
  request:{property_id:string;model_queries:string[]};
  data:{facts:TopicFact[];gaps:{check:string;status:string;detail:string}[];targets:Record<string,unknown>[];
    candidates:TopicCandidate[];library:{blocks:TopicBlock[]};preparation_status:string;
    choices:{label:string;role?:string;relations?:{pristine:Record<string,string>;defect:Record<string,string>;removed_oxygen_index:number;site:{fractional:number[]}}[];tasks?:{task_id:string;model_name:string;selector:Record<string,string>}[]}[];
    reference_candidates:{report_id:string;reference:{value_ev_per_O:number;source:string;conditions:string}}[];
  };
  freshness?:{stale:boolean;changes:unknown[]};
}
export interface TopicEdit {expected_revision:number;title:string;sections:TopicReport['sections'];blocks:{block_id:string;title:string;section:string;text?:string}[];hidden_block_ids:string[];deleted_block_ids:string[]}
const root='/reports/topic';
export const listTopics=(conversationId:string)=>request<{items:TopicMeta[]}>(`${root}?conversation_id=${encodeURIComponent(conversationId)}`);
export const fetchTopic=(id:string)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}`);
export const editTopic=(id:string,body:TopicEdit)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify(body)});
export const saveTopic=(id:string,revision:number)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/save`,{method:'POST',body:JSON.stringify({expected_revision:revision})});
export const previewTopic=(id:string)=>request<{html:string}>(`${root}/${encodeURIComponent(id)}/preview`,{method:'POST',body:'{}'});
export const exportTopic=(id:string,print=false)=>requestBlobUrl(`${root}/${encodeURIComponent(id)}/export.html?print=${print}`);
export const resolveTopic=(id:string,body:unknown)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/resolve`,{method:'POST',body:JSON.stringify(body)});
export const regenerateTopicParagraph=(id:string,block:string,revision:number,connection:string)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/regenerate`,{method:'POST',body:JSON.stringify({block_id:block,expected_revision:revision,connection_id:connection})});
