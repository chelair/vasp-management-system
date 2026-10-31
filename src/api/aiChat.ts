import { clearToken, getToken, request } from './client';

const ROOT = '/ai/chat';
export type ReasoningEffort='default'|'none'|'minimal'|'low'|'medium'|'high'|'xhigh'|'max';
export interface ReasoningCapabilities {provider:string;verified:boolean;options:{value:ReasoningEffort;label:string}[];tool_policy:'supported'|'none_only'|'unsupported';note:string}
export interface AIConnection {
  id: string; name: string; base_url: string; model: string; max_tokens: number;
  is_default: boolean; key_configured: boolean; created_at: string; updated_at: string;
  thinking_mode: 'default' | 'enabled' | 'disabled';
  reasoning_api:'auto'|'openai'|'deepseek';reasoning_effort:ReasoningEffort;effective_reasoning_effort:ReasoningEffort;reasoning_capabilities:ReasoningCapabilities;
}
export interface AIConnectionInput {
  name: string; base_url: string; model: string; api_key?: string;
  max_tokens: number; is_default: boolean;
  thinking_mode?: 'default' | 'enabled' | 'disabled';
  reasoning_api?:'auto'|'openai'|'deepseek';reasoning_effort?:ReasoningEffort;
}
export interface AITarget {
  id: string; name: string; closed: boolean;
  tasks: { id: string; name: string; type: string; status: string; group: string }[];
}
export interface AIMessage {
  id: string; seq: number; conversation_id: string; role: 'user' | 'assistant';
  content: string; status: string; created_at: string;
}
export interface AIRun {
  id: string; conversation_id: string; message_id: string; status: string;
  model: string; connection_name: string; prompt_version: number;
  error: string; created_at: string; finished_at: string | null;
  usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
  snapshot?: Record<string, unknown>;
  tool_events: { id: string; name: string; arguments: Record<string, unknown>; result: Record<string, unknown>; status: string; at: string; reasoning_offset?: number }[];
  /** 可选展示：模型思考链路（服务商返回时才有，后端截断到 6 万字符） */
  reasoning?: string;
  report_progress?: { done: number; total: number; label: string };
  report_job?: { action: string; report_id?: string; comment_id?: string };
  report_activity?: { label: string; at: string; state: string; report_id?: string; comment_id?: string }[];
}
export interface AIConversation {
  id: string; task_id: string | null; title: string; connection_id: string | null;
  project_id: string | null;
  workspace_enabled: boolean | number;
  prompt: string; prompt_version: number; created_at: string; updated_at: string;
}
export interface AIConversationDetail extends AIConversation {
  messages: AIMessage[]; runs: AIRun[]; has_more: boolean;
}
export type AIContext = Record<string, unknown>;
export const listAIConnections = () => request<{ items: AIConnection[] }>(`${ROOT}/connections`);
export const saveAIConnection = (body: AIConnectionInput, id?: string) => request<AIConnection>(
  `${ROOT}/connections${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
export const deleteAIConnection = (id: string) => request(`${ROOT}/connections/${id}`, { method: 'DELETE' });
export const testAIConnection = (id: string) => request<{ models: string[]; model_listed: boolean; message: string }>(`${ROOT}/connections/${id}/test`, { method: 'POST' });
export const listAITargets = () => request<{ items: AITarget[] }>(`${ROOT}/targets`);
export const listAIConversations = () => request<{ items: AIConversation[] }>(`${ROOT}/conversations`);
export const createAIConversation = (body: { title: string; project_id?: string; connection_id?: string }) => request<AIConversation>(`${ROOT}/conversations`, { method: 'POST', body: JSON.stringify(body) });
export const getAIConversation = (id: string, before?: number) => request<AIConversationDetail>(`${ROOT}/conversations/${id}${before ? `?before=${before}` : ''}`);
export const updateAIConversation = (id: string, body: { title: string; connection_id: string | null; prompt: string; workspace_enabled?: boolean }) => request<AIConversationDetail>(`${ROOT}/conversations/${id}`, { method: 'PUT', body: JSON.stringify(body) });
export const deleteAIConversation = (id: string) => request(`${ROOT}/conversations/${id}`, { method: 'DELETE' });
export const getAIContext = (id: string) => request<AIContext>(`${ROOT}/conversations/${id}/context`);
export const getAIRun = (id: string) => request<AIRun>(`${ROOT}/runs/${id}`);
export interface AIWorkspaceMap {
  enabled: boolean; generated_at: string;
  roots: { path: string; access: string; purpose: string }[];
  rules: string[];
  task_locations: { task_id: string; name: string; path: string | null; remote_dir: string; output_dir: string | null; structure_source_dir: string | null }[];
}
export interface AIWorkspaceListing {
  path: string; items: { name: string; path: string; type: 'file' | 'directory'; bytes?: number; mtime?: number }[];
  total: number; next_offset?: number | null; missing?: boolean;
}
export interface AIWorkspaceFile {
  path: string; content: string; bytes: number; offset: number; next_offset: number | null;
  mtime: number | null; sha256: string; hash_scope: string; remote_verified: boolean;
}
export const getAIWorkspace = (id: string) => request<AIWorkspaceMap>(`${ROOT}/conversations/${id}/workspace`);
export const listAIWorkspace = (id: string, path = '', offset = 0) => request<AIWorkspaceListing>(`${ROOT}/conversations/${id}/workspace/files?${new URLSearchParams({ path, offset: String(offset) })}`);
export const readAIWorkspace = (id: string, path: string, offset = 0, tail = false) => request<AIWorkspaceFile>(`${ROOT}/conversations/${id}/workspace/file?${new URLSearchParams({ path, offset: String(offset), tail: String(tail) })}`);
export const stopAIRun = (id: string) => request(`${ROOT}/runs/${id}/cancel`, { method: 'POST' });
export const sendAIMessage = (id: string, content: string, retry = false) => request<AIRun>(`${ROOT}/conversations/${id}/messages`, {
  method: 'POST', body: JSON.stringify({ content, retry, request_id: `${Date.now()}_${Math.random().toString(36).slice(2)}` }),
});
export const isActiveRun = (run: AIRun) => run.status === 'queued' || run.status === 'running';

/** SSE 只订阅已存在的运行；断开订阅不会重新发起模型请求。 */
export async function watchAIRun(id: string, signal: AbortSignal, onUpdate: (data: { run: AIRun; message: AIMessage }) => void) {
  const response = await fetch(`/api${ROOT}/runs/${id}/events`, {
    headers: { Authorization: `Bearer ${getToken() ?? ''}` }, signal, cache: 'no-store',
  });
  if (!response.ok) {
    if (response.status === 401) { clearToken(); window.location.assign('/login?from=%2Fai'); }
    const error = await response.json().catch(() => null);
    throw new Error(error?.message ?? '无法订阅回答，请重新加载会话');
  }
  if (!response.body) throw new Error('浏览器不支持流式回答');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const event = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const data = event.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
        if (!data) continue;
        const parsed = JSON.parse(data);
        if (parsed.error) throw new Error(parsed.error);
        onUpdate(parsed);
        if (parsed.run && !isActiveRun(parsed.run)) finished = true;
      }
      if (done) break;
    }
    if (!finished && !signal.aborted) throw new Error('回答连接已断开');
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}

export const fetchReasoningCapabilities=(base:string,model:string,api='auto')=>request<ReasoningCapabilities>(`${ROOT}/reasoning-capabilities?${new URLSearchParams({base_url:base,model,reasoning_api:api})}`);
