"""R4 bounded, local-only data preparation. R3 computes; R2 supplies real blocks.

Model names only scope candidates. Vacancy roles are bound automatically only
when exactly one structural single-O deletion relation can be demonstrated.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import properties
from ai_inspections import query_inspections
from checks_store import collect_task_observations
from property_science import digest, number, vacancy
from report_blocks import list_candidates
from report_compositions import build_composition
from storage import load_db

MAX_PROJECTS = 4
MAX_TASKS = 24
MAX_BLOCKS = 24
MAX_BYTES = 6 * 1024 * 1024
ROLES = {'oxygen_vacancy.neutral_single':('pristine','defect'), 'relative_energy':('reference','model'),
         'adsorption.simple':('complex','surface','adsorbate'), 'neb.barrier':('path',),
         'work_function.difference':('reference','model'), 'dos.comparison':('model',)}
ALLOWED = {
    'oxygen_vacancy.neutral_single':{'task.summary','task.params','task.energy_force','task.structure'},
    'relative_energy':{'task.summary','task.params','task.energy_force','task.structure','task.convergence_curve'},
    'adsorption.simple':{'task.summary','task.params','task.energy_force','task.structure'},
    'neb.barrier':{'task.summary','task.params','group.neb'},
    'work_function.difference':{'task.summary','task.params','ele.work_function','task.structure'},
    'dos.comparison':{'task.summary','task.params','ele.pdos'},
}


def _selector(project,task):
    selector = {'project_id':project['project_id'],'task_id':task['task_id']}
    history = query_inspections(project,task['task_id'],limit=5)
    # A unique known current directory is a reliable automatic choice, not an
    # arbitrary newest conN or a choice between different vacancy sites.
    if history['observations'] and not history['freshness']['source_mismatch']:
        selector['observation_id'] = history['observations'][0]['observation_id']
    return selector


def _matches(projects,query,property_id):
    result = []
    for project in projects:
        for task in project.get('tasks',[]):
            from task_paths import is_auxiliary_task
            if is_auxiliary_task(task): continue
            name = str(task.get('model_name') or '').casefold()
            q = query.casefold()
            # Prefix token matching keeps LMR distinct from LIC@LMR, but does not
            # establish a pristine/defect scientific relation.
            if not (name == q or any(name.startswith(q+sep) for sep in ('_','-',' ','/','.')) or task.get('task_id') == query): continue
            if property_id == 'dos.comparison' and task.get('task_type') != 'ele': continue
            if property_id == 'neb.barrier' and task.get('task_type') != 'neb': continue
            result.append((project,task))
    return result


def _candidate(project,task,selector):
    return {'project_id':project['project_id'],'project_name':project['name'],'task_id':task['task_id'],
            'model_name':task.get('model_name'),'task_type':task.get('task_type'),'selector':selector}


def _references(db,user,projects,science):
    """Only reuse an explicitly human-set reference with identical bound methods.

    Never guess mu_O from a model name, a model response or an unrelated report.
    """
    wanted = {(i.get('task') or {}).get('task_id'):i.get('data',{}) for i in science.get('inputs',[]) if i.get('task')}
    refs,seen = [],set()
    if not wanted: return refs
    paths = sorted(properties.REPORT_DIR.glob('prop_*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]
    for path in paths:
        try:
            doc = json.loads(path.read_text())
            if doc.get('property_id') != 'oxygen_vacancy.neutral_single': continue
            if set(doc.get('project_ids') or []) != {p['project_id'] for p in projects}: continue
            properties.authorized_projects(db,user,doc['project_ids'])
            reference = doc.get('reference_state') or {}
            if reference.get('type') != 'user_explicit_oxygen_chemical_potential': continue
            prior = {(i.get('task') or {}).get('task_id'):i.get('data',{}) for i in doc.get('inputs',[]) if i.get('task')}
            if set(prior) != set(wanted): continue
            compatible = all(all(prior[t].get(k) == wanted[t].get(k) for k in ('settings','potentials','hubbard','kpoints')) for t in wanted)
            if not compatible: continue
            key = digest({k:reference.get(k) for k in ('value_ev_per_O','source','conditions')})
            if key in seen: continue
            seen.add(key)
            refs.append({'report_id':doc['report_id'],'reference':reference,'auto_eligible':reference.get('set_by') == properties.permissions.username_of(user)})
        except (OSError,ValueError,KeyError,properties.permissions.PermissionDenied): continue
    return refs


def r2_observation_project(project,raw):
    """Adapt R2's legacy task energy field to one selected raw observation.

    R2 normally reads energy from the live task row. A frozen topic must never
    combine that row's energy with a different conN observation's parameters.
    """
    view=copy.deepcopy(project)
    for task in view.get('tasks',[]):
        observation=raw.get(task['task_id']) or {}
        task['last_energy']=observation.get('last_energy')
        for field in ('current_output','remote_dir','job_id','status'):
            if field in observation:task[field]=copy.deepcopy(observation[field])
    return view


def prepare(user,project_ids,request):
    if not isinstance(request,dict) or set(request)-{'property_id','model_queries','targets','common_oxygen_reference','reference_report_id','surface_side','reaction_correspondence','adsorbate_query','adsorbate_reference_type','reference_conditions'}:
        raise ValueError('专题数据请求只接受已注册性质、目标与受限参考，不接受公式、数值或文件路径')
    db = load_db()
    if len(project_ids)>MAX_PROJECTS: raise ValueError('每次专题最多检索4个项目')
    projects = properties.authorized_projects(db,user,project_ids)
    pid = request.get('property_id')
    if not isinstance(pid,str) or len(pid)>100: raise ValueError('科学性质标识无效')
    queries = request.get('model_queries')
    if not isinstance(queries,list) or not 1<=len(queries)<=4 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in queries):
        raise ValueError('请选择1至4个具体模型查询词')
    explicit = request.get('targets')
    if explicit is not None and (not isinstance(explicit,list) or len(explicit)>4): raise ValueError('目标绑定最多4组')
    # Preauthorize every explicit reference before reading scientific evidence.
    for target in explicit or []:
        if not isinstance(target,dict): raise ValueError('目标绑定必须为对象')
        for value in target.values():
            if isinstance(value,dict) and 'project_id' in value:
                properties.authorized_projects(db,user,[value['project_id']])
                if value['project_id'] not in {p['project_id'] for p in projects}: raise ValueError('绑定项目不在本轮范围')
    if pid not in ROLES:
        return {'projects':[{'project_id':p['project_id'],'name':p['name']} for p in projects],
                'science':properties.evaluate(db,user,{'property_id':pid}),'choices':[],
                'library':{'blocks':[],'evidence':{}},'candidates':[],'facts':[],
                'gaps':[{'check':'property_recipe','status':'UNSUPPORTED','detail':'性质未注册，不能临时编造公式或数值'}],
                'targets':[],'reference_candidates':[],'preparation_status':'UNSUPPORTED','assumptions':[]}
    pools = [_matches(projects,q.strip(),pid) for q in queries]
    adsorbate_query=request.get('adsorbate_query')
    if adsorbate_query is not None and (pid!='adsorption.simple' or not isinstance(adsorbate_query,str) or not adsorbate_query.strip() or len(adsorbate_query)>100):raise ValueError('吸附物查询只供吸附能配方使用，须为1至100字符名称或任务ID')
    reference_pool=_matches(projects,adsorbate_query.strip(),pid) if adsorbate_query else []
    all_pairs = {(p['project_id'],t['task_id']):(p,t) for pool in pools for p,t in pool}
    all_pairs.update({(p['project_id'],t['task_id']):(p,t) for p,t in reference_pool})
    if len(all_pairs)>MAX_TASKS: raise ValueError('匹配超过24个任务，请缩小模型查询或明确绑定')
    # Exact user bindings may point to a task whose name does not match the query.
    # It remains relevant only if the user explicitly bound the recipe role.
    for target in explicit or []:
        for role in ROLES[pid]:
            selector = target.get(role)
            if not selector: continue
            selector = properties._selector(selector,projects[0]['project_id'])
            p = next((p for p in projects if p['project_id'] == selector['project_id']),None)
            if p is None: raise ValueError('绑定项目不在本轮范围')
            task = properties.task_for(p,selector.get('task_id',''))
            all_pairs[(p['project_id'],task['task_id'])] = (p,task)
    if len(all_pairs)>MAX_TASKS: raise ValueError('本次最多24个任务')
    selectors,inspected = {},{}
    for key,(p,t) in all_pairs.items():
        selectors[key] = _selector(p,t)
        if pid != 'dos.comparison':
            inspected[key] = properties._input(db,user,projects,selectors[key],'candidate')
    choices,targets,gaps = [],[],[]
    def unique(pool,query):
        if len(pool)==1:
            p,t = pool[0]; return selectors[(p['project_id'],t['task_id'])]
        return {'query':query,'project_id':projects[0]['project_id']}
    if explicit:
        explicit_observations={}
        targets = copy.deepcopy(explicit)
        for target in targets:
            for role in ROLES[pid]:
                if not isinstance(target.get(role),dict) or not target[role].get('task_id'):continue
                selector=target[role]
                selector.setdefault('project_id',projects[0]['project_id'])
                known=selectors.get((selector['project_id'],selector['task_id'])) or {}
                if not selector.get('observation_id') and known.get('observation_id'):selector['observation_id']=known['observation_id']
                key=(selector['project_id'],selector['task_id'])
                if key in explicit_observations and explicit_observations[key].get('observation_id')!=selector.get('observation_id'):raise ValueError('同一专题中同一任务只能绑定一个计算观测；不同conN应分别报告')
                explicit_observations[key]=selector
                selectors[key]=copy.deepcopy(selector)
    elif pid == 'oxygen_vacancy.neutral_single':
        for query,pool in zip(queries,pools):
            relations = []
            for p,a in pool:
                for q,b in pool:
                    if (p['project_id'],a['task_id']) == (q['project_id'],b['task_id']): continue
                    pristine = inspected[(p['project_id'],a['task_id'])]['data']
                    defect = inspected[(q['project_id'],b['task_id'])]['data']
                    cs,site = vacancy(pristine,defect)
                    # Structural relation can be identified even when convergence
                    # or method compatibility is incomplete; R3 still blocks values.
                    site_check = next((c for c in cs if c['check']=='vacancy_site'),None)
                    if site_check and site_check['status']=='AVAILABLE' and any(c['check']=='cell' and c['status']=='AVAILABLE' for c in cs):
                        relations.append({'pristine':selectors[(p['project_id'],a['task_id'])],
                                          'defect':selectors[(q['project_id'],b['task_id'])],
                                          'removed_oxygen_index':site['removed_oxygen_index'],'site':site})
            choices.append({'label':query,'relations':relations,'tasks':[_candidate(p,t,selectors[(p['project_id'],t['task_id'])]) for p,t in pool]})
            if len(relations)==1:
                relation=relations[0];targets.append({'label':query,**{k:relation[k] for k in ('pristine','defect','removed_oxygen_index')}})
            else:
                targets.append({'label':query,'pristine':{'query':query,'project_id':projects[0]['project_id']},'defect':{'query':query,'project_id':projects[0]['project_id']}})
                gaps.append({'check':'vacancy_relation','status':'AMBIGUOUS' if relations else 'MISSING',
                             'detail':query+'：请选择具体完整/缺陷/氧位点；存在多种关系' if relations else query+'：缺少可验证的单O删除关系，需完整模型、缺陷模型及相同晶胞的输入结构证据'})
    elif pid in ('relative_energy','work_function.difference'):
        if len(pools)!=2: raise ValueError('差值比较需要两个模型查询词或明确角色绑定')
        targets=[{'label':queries[1]+' − '+queries[0],'reference':unique(pools[0],queries[0]),'model':unique(pools[1],queries[1])}]
    elif pid=='adsorption.simple':
        if adsorbate_query or len(pools)!=3:
            from adsorption_discovery import find
            targets,choices,ads_gaps=find(queries,pools,reference_pool,selectors,inspected,projects[0]['project_id'])
            gaps+=ads_gaps
            if not adsorbate_query:gaps.append({'check':'adsorbate_query','status':'MISSING','detail':'请明确吸附物名称/参考态；不给缺失的吸附物猜测公式或能量。'})
        else:
            targets=[{'label':'吸附能',**{r:unique(pool,q) for r,pool,q in zip(ROLES[pid],pools,queries)}}]
    elif pid=='neb.barrier':
        targets=[{'label':q,'path':unique(pool,q)} for q,pool in zip(queries,pools)]
    assumptions=[]
    refs=[]
    if pid=='dos.comparison':
        for query,pool in ([] if explicit else zip(queries,pools)):
            available=[]
            for p,t in pool:
                catalog=list_candidates({**p,'tasks':[t]})
                if any(c['type']=='ele.pdos' and c['availability'] in ('available','unparsed') for c in catalog['candidates']): available.append((p,t))
            if len(available)==1: targets.append({'label':query,'model':unique(available,query)})
            else:
                targets.append({'label':query,'model':{'query':query}})
                choices.append({'label':query,'role':'model','tasks':[_candidate(p,t,selectors[(p['project_id'],t['task_id'])]) for p,t in pool]})
                gaps.append({'check':'dos_binding','status':'AMBIGUOUS' if len(available)>1 else 'MISSING','detail':query+'：需要唯一的已有PDOS结果和能量参考；多个候选须选择'})
        science={'property_id':pid,'status':'VISUAL_ONLY','results':[],'inputs':[],
                 'recipe':{'definition':'已有DOS/PDOS曲线比较','scope':'只展示已有曲线、费米能级及计算条件；未注册的派生DOS指标不计算','formula':'无新增计算公式'},'gaps':[]}
    else:
        kwargs={k:request[k] for k in ('surface_side','reaction_correspondence','adsorbate_reference_type','reference_conditions') if k in request}
        payload={'property_id':pid,'project_ids':project_ids,'targets':targets,**kwargs}
        if pid=='oxygen_vacancy.neutral_single':
            # A comparison without a reservoir value may be stated conditionally;
            # a model declaration never becomes a verified user reference.
            payload['common_oxygen_reference']=request.get('common_oxygen_reference') is True
            if payload['common_oxygen_reference']:
                assumptions.append('共同氧化学势是差值成立的条件；没有明确用户参考时作为待确认假设，不代表已测得绝对形成能。')
        science=properties.evaluate(db,user,payload)
        if pid=='oxygen_vacancy.neutral_single':
            refs=_references(db,user,projects,science)
            selected=None
            if request.get('reference_report_id'):
                selected=next((r for r in refs if r['report_id']==request['reference_report_id']),None)
                if not selected: raise ValueError('氧参考报告不属于这些绑定及理论设置，不能借用')
            elif len(refs)==1 and refs[0]['auto_eligible']:
                selected=refs[0]
            if selected:
                ref=selected['reference'];payload['mu_O']={'value_ev':ref['value_ev_per_O'],'source':ref['source'],'conditions':ref['conditions']}
                science=properties.evaluate(db,user,payload)
                science['reference_state']['source_report_id']=selected['report_id']
                assumptions=[]
            elif len(refs)>1:
                gaps.append({'check':'oxygen_reference','status':'AMBIGUOUS','detail':'存在多个明确设置的氧参考，请确认所用参考态及适用条件；不随机选择。'})
        gaps+=science.get('gaps',[])
    # Relevant tasks are the bound recipe roles; unresolved choices remain candidate
    # evidence and cannot be mistaken for a scientific relation.
    chosen_ids={s['task_id'] for t in targets for s in t.values() if isinstance(s,dict) and s.get('task_id')}
    related_ids=chosen_ids or {t['task_id'] for _,t in all_pairs.values()}
    library={'blocks':[],'evidence':{}}
    candidates=[]
    budget=0
    for p in projects:
        subset={**p,'tasks':[t for t in p.get('tasks',[]) if t['task_id'] in related_ids]}
        # Raw per-directory observations only; do not inherit missing fields across conN.
        raw={}
        for task in subset['tasks']:
            key=(p['project_id'],task['task_id'])
            selector=selectors.get(key,{})
            observation=next((o for o in collect_task_observations(task['task_id'],5) if o['observation_id']==selector.get('observation_id')),None)
            if observation:raw[task['task_id']]=observation['data']
        subset=r2_observation_project(subset,raw)
        catalog=list_candidates(subset,merged=raw,submit_times={})
        relevant=[c for c in catalog['candidates'] if c['type'] in ALLOWED[pid] and c['availability'] in ('available','unparsed')]
        for missing in catalog['candidates']:
            if missing['type'] in ALLOWED[pid] and missing['type'] in ('task.params','ele.pdos','ele.work_function') and missing['availability']=='missing':
                gaps.append({'check':'report_element.'+missing['type'],'status':'MISSING','detail':missing['title']+' 缺少本地数据，不能作为已验证计算条件或结果。'})
        for c in relevant:
            if len(candidates)>=MAX_BLOCKS:
                if not any(g['check']=='element_budget' for g in gaps):gaps.append({'check':'element_budget','status':'INCOMPLETE','detail':'相关报告元素超过本轮24项预算，仅冻结已列出的元素；请缩小模型范围后生成补充报告。'})
                break
            try:
                composition=build_composition(subset,{'title':'专题证据','blocks':[{k:c[k] for k in ('block_id','type','task_id','group_id','variant') if k in c}]},merged=raw)
                block=composition['blocks'][0]
                if block['data_status']!='available':
                    gaps.append({'check':'report_element.'+c['type'],'status':'INCOMPLETE','detail':c['title']+' 有文件但未解析成可用证据。'});continue
                size=len(json.dumps(composition,ensure_ascii=False).encode())
                if budget+size>MAX_BYTES:
                    gaps.append({'check':'evidence_budget','status':'INCOMPLETE','detail':'部分相关元素超过本轮冻结数据预算，未载入；请缩小模型范围。'});continue
                budget+=size
                block['origin']='r2';library['blocks'].append(block);library['evidence'].update(composition['evidence'])
                candidates.append({k:c.get(k) for k in ('block_id','type','title','task_id','group_id','validation','freshness')} |
                                  {'project_id':p['project_id'],'availability':block['data_status'], 'science_status':next((i['status'] for i in science.get('inputs',[]) if (i.get('task') or {}).get('task_id')==c.get('task_id')),'UNKNOWN') if pid!='dos.comparison' else 'VISUAL_ONLY',
                                   'note':'模型名只界定候选范围；科学关系/结果以性质检查为准'})
            except (ValueError,LookupError,KeyError,OSError) as exc:
                gaps.append({'check':'report_element','status':'INCOMPLETE','detail':str(exc)[:300]})
    facts=[]
    def fact(label,value,units,source,status='AVAILABLE'):
        try:value=number(value)
        except (ValueError,TypeError):return
        facts.append({'fact_id':f'F{len(facts)+1:02}','label':label,'value':value,'units':units,'source':source,'validation_status':status})
        return facts[-1]['fact_id']
    for result in science.get('results',[]):
        fact(result['label']+' · '+result['key'],result['value'],result['units'],{'kind':'PropertyRecipe','key':result['key'],'formula':result['formula'],'version':result['formula_version']},'CONDITIONAL' if assumptions else 'AVAILABLE')
    for item in science.get('inputs',[]):
        if item.get('task'):
            fact(item['task'].get('model_name') or item['task']['task_id'],item['data'].get('energy_ev'),'eV',item.get('source'),item['status'])
    for block in library['blocks']:
        for ref in block['source_refs']:
            evidence=library['evidence'][ref['evidence_id']]
            payload=evidence.get('payload') or {}
            if block['type']=='ele.pdos':
                view=payload.get('view') or {};meta=view.get('meta') or view.get('metadata') or {}
                summary=payload.get('summary') or {}
                fermi=meta.get('efermi',view.get('efermi',summary.get('efermi')))
                added=fact(block['title']+' · 费米能级',fermi,'eV',{'kind':'R2','evidence_id':ref['evidence_id'],'version':ref['version']})
                if not added:gaps.append({'check':'dos_energy_reference','status':'UNKNOWN','detail':block['title']+' 缺少明确费米能级/能量参考，不进行无依据曲线对齐。'})
    if not candidates:
        gaps.append({'check':'report_elements','status':'MISSING','detail':'没有相关且可用的R2元素；报告仅说明数据需求，不添加无关图表。'})
    return {'projects':[{'project_id':p['project_id'],'name':p['name']} for p in projects], 'science':science,
            'task_observations':list(selectors.values()),'targets':targets,'choices':choices,'reference_candidates':refs,'library':library,'candidates':candidates,'facts':facts,
            'gaps':gaps,'preparation_status':'NEEDS_SELECTION' if any(g['status']=='AMBIGUOUS' for g in gaps) else 'PARTIAL' if gaps else 'AVAILABLE',
            'assumptions':assumptions,'retrieval_budget':{'tasks':len(all_pairs),'blocks':len(candidates),'frozen_bytes':budget}}
