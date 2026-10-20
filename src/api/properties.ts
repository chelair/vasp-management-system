import { request } from './client';
export interface PropertyRecipe {
  property_id: string; definition: string; scope: string; required_inputs: string[];
  optional_inputs: string[]; required_checks: string[]; formula: string; version: string;
}
export interface PropertyTask { project_id: string; task_id: string; model_name: string; task_type: string; status: string }
export interface PropertySelector { project_id?: string; task_id?: string; query?: string; observation_id?: string }
export interface PropertyTarget { label: string; [key: string]: string | number | PropertySelector }
export interface PropertyInput {
  role: string; status: string; task?: PropertyTask;
  source?: { observation_id: string; checked_at: string; directory?: {path?: string} };
  checks: { check: string; status: string; detail: string }[];
  observations?: {observation_id: string; directory?: {path?: string}; archive: string}[];
  candidates: PropertyTask[];
  data: {energy_ev?: number; charge?: number};
}
export interface PropertyReport {
  report_id: string; property_id: string; status: string; generated_at: string; evidence_sha256: string;
  recipe: PropertyRecipe; inputs: PropertyInput[];
  targets: {label: string; status: string; site?: {removed_oxygen_index: number; fractional: number[]}}[];
  results: {key: string; label: string; value: number; units: string; formula: string; validation_status: string;
    conditions: string[]; unverified_conditions: string[]; reference_state?: unknown}[];
  gaps: {role?: string; check: string; status: string; detail: string}[];
  supplemental_suggestions: {role?: string; check: string; advice: string}[];
  recommendations: string[]; not_calculable: string[]; report_elements: {type: string; note?: string; task_id?: string; status?: string}[];
}
export const fetchPropertyRecipes = () => request<{recipes: PropertyRecipe[]}>('/properties/recipes');
export const discoverPropertyTasks = (projects: string[], query = '') => request<{matches: PropertyTask[]; total: number; truncated: boolean}>(
  '/properties/discover?'+projects.map(id => 'project_ids='+encodeURIComponent(id)).join('&')+'&query='+encodeURIComponent(query));
export const evaluateProperty = (payload: unknown) => request<PropertyReport>('/properties/evaluate',{method:'POST',body:JSON.stringify(payload)});
