import { request, requestBlobUrl } from './client';

export interface ReportBlock {
  block_id: string;
  type: string;
  type_label?: string;
  title: string;
  task_id?: string;
  group_id?: string;
  task_ids?: string[];
  variant?: string;
  text?: string;
  source_refs?: { evidence_id: string; version: string }[];
  data_status?: string;
  validation_status?: string;
  options?: Record<string, unknown>;
}
export interface BlockCandidate extends ReportBlock {
  resolvable: boolean;
  availability: string;
  full_report_visibility: string;
  summary: string;
  detail: string;
  freshness: {state: string; basis: string};
  validation: {status: string};
  legacy_hidden_keys?: string[];
}
export interface CompositionGroup { group_id: string; title: string; block_ids: string[]; collapsed?: boolean }
export interface CompositionDraft {
  composition_id?: string;
  revision?: number;
  title: string;
  blocks: ReportBlock[];
  groups: CompositionGroup[];
  hidden_block_ids: string[];
  deleted_block_ids: string[];
}
export interface CompositionMeta { composition_id: string; title: string; revision: number; block_count: number }
const root = (project: string) => `/reports/blocks/${encodeURIComponent(project)}`;
export const fetchCandidates = (project: string) => request<{candidates: BlockCandidate[]; task_count: number}>(`${root(project)}/candidates`);
export const fetchCompositions = (project: string) => request<{items: CompositionMeta[]}>(`${root(project)}/compositions`);
export const fetchComposition = (project: string, id: string) => request<CompositionDraft>(`${root(project)}/compositions/${encodeURIComponent(id)}`);
const body = (draft: CompositionDraft, refresh = false) => JSON.stringify({ ...draft, expected_revision: draft.revision,
  refresh_evidence: refresh, blocks: draft.blocks.map(b => ({...b, client_id: b.block_id.startsWith('draft_') ? b.block_id : undefined,
    block_id: b.block_id.startsWith('draft_') ? undefined : b.block_id})) });
export const previewComposition = (project: string, draft: CompositionDraft) => request<{document: CompositionDraft; html: string}>(`${root(project)}/preview`, {method: 'POST', body: body(draft)});
export const saveComposition = (project: string, draft: CompositionDraft, refresh = false) => request<CompositionDraft>(
  `${root(project)}/compositions${draft.composition_id ? `/${encodeURIComponent(draft.composition_id)}` : ''}`,
  {method: draft.composition_id ? 'PUT' : 'POST', body: body(draft, refresh)});
export const checkComposition = (project: string, id: string) => request<{changes: unknown[]}>(`${root(project)}/compositions/${encodeURIComponent(id)}/check`, {method: 'POST'});
export const compositionHtml = (project: string, id: string, print = false) => requestBlobUrl(`${root(project)}/compositions/${encodeURIComponent(id)}/export.html?print=${print}`);
