import {request,requestBlobUrl} from './client';
export interface TopicBlock {block_id:string;title:string;section:string;origin:'r2'|'question'|'property_fact'|'ai_text';type:string;text:string;data_status:string;source_refs:{evidence_id:string;version:string}[]}
export interface TopicCandidate {block_id:string;title:string;type:string;task_id:string;project_id:string;availability:string}
export interface TopicFact {fact_id:string;label:string;value:number;units:string;validation_status:string}
export interface TopicQuestion {id:string;title:string;options:{value:string;label:string;description?:string}[];hint?:string;error?:string}
export interface TopicMeta {simple?:boolean;questions?:TopicQuestion[];result_summary?:string;topic_id:string;report_type:'topic';title:string;revision:number;stage:string;updated_at:string;conversation_id:string}
export type TopicAssessment = Partial<Record<'background'|'problem'|'impact'|'decision'|'explanation'|'conclusion'|'recommendation',string>>;
export interface TopicReport extends Omit<TopicMeta,'simple'> {
  continuation_error?:string;
  assessment_edits?:TopicAssessment;
  simple?:{version:string;questions:TopicQuestion[];notes:string;warnings:string[];show_warnings?:boolean};
  original_question:string;created_at:string;project_ids:string[];
  sections:{section_id:string;title:string}[];
  blocks:TopicBlock[];hidden_block_ids:string[];deleted_block_ids:string[];
  narratives:Record<string,{ai_text:string;user_text:string|null;kind:string;model:string}>;
  request:{property_id:string;model_queries:string[];adsorbate_reference_type?:string;objective?:string};
  data:{assessment?:TopicAssessment;science?:{inputs:{role:string;task?:{task_id:string;model_name?:string};observations?:{observation_id:string;archive:string;directory:{path:string|null}}[]}[]};facts:TopicFact[];gaps:{check:string;status:string;detail:string}[];targets:Record<string,unknown>[];
    candidates:TopicCandidate[];library:{blocks:TopicBlock[]};preparation_status:string;
    choices:{label:string;target_label?:string;role?:string;adsorption_relations?:{complex:Record<string,string>;surface:Record<string,string>;adsorbate:Record<string,string>;site:{adsorbate_atom_indices:number[];fractional:number[][]}}[];relations?:{pristine:Record<string,string>;defect:Record<string,string>;removed_oxygen_index:number;site:{fractional:number[]}}[];tasks?:{task_id:string;model_name:string;selector:Record<string,string>}[]}[];
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

export const answerTopic=(id:string,revision:number,answers:Record<string,string>)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/questions`,{method:'POST',body:JSON.stringify({expected_revision:revision,answers,continue_analysis:true})});
export const rebuildTopic=(id:string)=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/rebuild`,{method:'POST',body:'{}'});
export const updateTopicContent=(id:string,body:{expected_revision:number;title:string;objective?:string;notes:string;show_warnings?:boolean;assessment?:TopicAssessment;blocks:string[];deleted_block_ids:string[]})=>request<TopicReport>(`${root}/${encodeURIComponent(id)}/content`,{method:'PUT',body:JSON.stringify(body)});
