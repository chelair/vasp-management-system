"""Minimum-data adsorption: deterministic arithmetic, quality issues are warnings."""
from dataclasses import asdict
import copy
import re

from dates import now_iso
from property_science import number, digest
from checks_store import collect_task_observations

ROLES=('surface','adsorbate','complex')
LABELS={'surface':'基底','adsorbate':'吸附质','complex':'吸附后完整构型'}


def read_energy(project, task, observation_id=None):
    """Select one recorded energy; never silently assemble a fictitious snapshot."""
    rows=collect_task_observations(task['task_id'],5)
    if observation_id:
        selected=next((o for o in rows if o['observation_id']==observation_id),None)
        if selected is None:raise ValueError('选中的结果已更新，请重新选择')
    else:
        latest=(task.get('current_output') or {}).get('latest_dir')
        selected=next((o for o in rows if latest and str((o['data'].get('current_output') or {}).get('latest_dir'))==str(latest)),None)
        selected=selected or (rows[0] if rows else None)
    row=selected['data'] if selected else {}
    value=row.get('last_energy')
    source={'task_id':task['task_id'],'project_id':project['project_id'],'kind':'inspection' if selected else 'task_record',
            'observed_at':row.get('checked_at') or task.get('updated_at'),
            'directory':((selected or {}).get('directory') or {}).get('path') or (row.get('current_output') or task.get('current_output') or {}).get('dir'),
            'observation_id':(selected or {}).get('observation_id'),'archive':(selected or {}).get('archive')}
    warnings=[]
    if value is None and not observation_id:
        value=task.get('last_energy')
        if value is not None:source['kind']='task_record';warnings.append('能量来自任务中保存的结果，未能追溯同次巡检。')
    if value is None:
        from task_paths import task_files_dir
        from report_block_science import checked_path
        from batch_check import extract_toten
        for name in ('OUTCAR','OSZICAR'):
            try:path=checked_path(project,task,task_files_dir(project['name'],task)/name)
            except ValueError:continue
            if not path.is_file():continue
            with path.open('rb') as f:
                f.seek(max(0,path.stat().st_size-256*1024));text=f.read().decode('utf-8',errors='replace')
            if name=='OUTCAR':value=extract_toten(text)
            else:
                matches=re.findall(r'\bF=\s*([-+\d.EeDd]+)',text)
                if matches:
                    try:value=float(matches[-1].replace('D','E').replace('d','e'))
                    except ValueError:pass
            if value is not None:
                source.update(kind='local_output',file=str(path),sha256=digest(text));warnings.append('能量来自本地输出文件；尚未确认它与当前巡检是否为同一次计算。');break
    try:value=number(value)
    except (TypeError,ValueError):value=None
    state=row.get('status') or task.get('status')
    force=row.get('force_converged')
    if force is False or state=='unconverged':convergence='未收敛';warnings.append('计算尚未收敛，当前能量仍可用于初步计算，建议收敛后更新。')
    elif state in ('running','queued','pending','zombied'):convergence='计算尚未完成';warnings.append('使用的是当前已有能量，计算完成后结果可能变化。')
    elif force is True:convergence='已收敛（巡检记录）'
    else:convergence='尚无收敛记录'
    if not (row.get('property_evidence') or {}).get('schema_version'):warnings.append('旧记录缺少完整计算快照，结构与参数仅作参考。')
    return {'task_id':task['task_id'],'model_name':task.get('model_name') or task['task_id'],'project_id':project['project_id'],
            'energy_ev':value,'energy_definition':'VASP.free_energy.TOTEN' if source['kind'] in ('inspection','local_output') else 'recorded_total_energy',
            'convergence':convergence,'source':source,'warnings':warnings,'row':copy.deepcopy(row)}



def provided_energy(selector,user,project,task=None):
    import properties
    raw=selector.get('energy_ev') if selector.get('energy_ev') is not None else selector.get('energy_value')
    value=number(raw);unit='eV' if selector.get('energy_ev') is not None else str(selector.get('energy_unit','eV'))
    factors={'ev':1.0,'ha':27.211386245988,'hartree':27.211386245988,'ry':13.605693122994,'kj/mol':1/96.4853321233}
    factor=factors.get(unit.strip().casefold())
    if factor is None:raise ValueError('请说明参考能量单位，可使用eV、Ha、Ry或kJ/mol')
    value=number(value*factor)
    kind=selector.get('_source_kind','provided_energy')
    labels={'user_provided':'用户提供','ai_interpretation':'AI按用户描述解释','ai_assumption':'AI假设值','provided_energy':'手工给定'}
    quote=str(selector.get('source_quote') or selector.get('note') or '')[:2000]
    name=selector.get('label') or (task or {}).get('model_name') or '给定能量'
    original=read_energy(project,task) if task else None
    source={'kind':kind,'label':labels.get(kind,'手工给定'),'statement':quote,'original_value':number(raw),'original_unit':unit,
            'provided_by':properties.permissions.username_of(user),'verified_against_calculation':False,
            'quote_found_in_user_history':bool(selector.get('_quote_verified'))}
    if original:source['linked_task_source']=original['source'];source['task_record_energy_ev']=original['energy_ev']
    return {'task_id':(task or {}).get('task_id'),'model_name':str(name),'project_id':project['project_id'],
            'energy_ev':value,'energy_definition':'provided_reference_energy','convergence':'给定能量，未自动核验收敛',
            'source':source,'warnings':[labels.get(kind,'手工给定')+'的参考能量未与原计算自动核验。'+('请特别核对AI的理解。' if kind in ('ai_assumption','ai_interpretation') else '')],
            'row':(original or {}).get('row',{})}


def evaluate(db,user,payload):
    import properties
    projects=properties.authorized_projects(db,user,payload.get('project_ids'))
    pmap={p['project_id']:p for p in projects};targets=payload.get('targets') or []
    if not isinstance(targets,list) or not 1<=len(targets)<=4:raise ValueError('请选择一至四个待计算体系')
    recipe=asdict(properties.RECIPES['adsorption.estimate']);inputs=[];results=[];gaps=[];warnings=[]
    for index,target in enumerate(targets):
        bound={}
        for role in ROLES:
            selector=target.get(role) or {}
            project=pmap.get(selector.get('project_id') or projects[0]['project_id'])
            if project is None:raise properties.permissions.PermissionDenied('任务不属于本次授权项目')
            task_id=selector.get('task_id')
            manual=selector.get('energy_ev') is not None or selector.get('energy_value') is not None
            if not task_id and not manual:
                gaps.append({'role':f'{index}.{role}','detail':f'还需要确认{LABELS[role]}使用哪份能量。','action':'可选择任务，也可以直接告诉AI你知道的能量。'});continue
            task=properties.task_for(project,task_id) if task_id else None
            item=provided_energy(selector,user,project,task) if manual else read_energy(project,task,selector.get('observation_id'))
            item.update(role=f'{index}.{role}',role_label=LABELS[role]);bound[role]=item;inputs.append(item)
            if item['energy_ev'] is None:gaps.append({'role':item['role'],'detail':f'没有找到{LABELS[role]}“{item["model_name"]}”的能量。','action':'在任务详情同步计算结果（OUTCAR或OSZICAR）；尚未计算时再安排计算。'})
            for text in item['warnings']:warnings.append(f'{item["model_name"]}：{text}')
        settings=[i['row'].get('incar') or {} for i in bound.values()]
        for key,label in [('ENCUT','截断能'),('GGA','泛函'),('LDAU','U设置'),('ISPIN','自旋设置')]:
            values={str(s[key]) for s in settings if key in s}
            if len(values)>1:warnings.append(label+'不一致，能量差可能包含计算设置带来的影响。')
        meshes={str((i['row'].get('kpoints') or {}).get('mesh')) for i in bound.values() if (i['row'].get('kpoints') or {}).get('mesh')}
        if len(meshes)>1:warnings.append('这些构型的k点网格不同。分子与表面采用不同网格可能合理，但需检查能量是否已收敛。')
        if any(not i['row'].get('kpoints') for i in bound.values()):warnings.append('部分旧结果没有k点记录，建议后续核对计算条件。')
        if len(bound)==3 and all(i['energy_ev'] is not None for i in bound.values()):
            result=properties.adsorption(bound['complex']['energy_ev'],bound['surface']['energy_ev'],bound['adsorbate']['energy_ev'])
            results.append({'key':f'{index}.adsorption','label':target.get('label') or '吸附能','value':result,'units':'eV','formula':recipe['formula'],
                            'formula_version':recipe['version'],'validation_status':'PRELIMINARY','formal_conclusion_allowed':False,
                            'inputs':{r:{'value':i['energy_ev'],'source':i['source']} for r,i in bound.items()}})
    warnings+=['按所选构型直接计算电子吸附能，默认一份吸附质；电荷、组成与构型对应关系尚未全部核实。','未包含零点能、温熵、溶剂等修正，不等同于吸附自由能。']
    return {'schema_version':'minimum.1.0','property_id':'adsorption.estimate','recipe':recipe,'generated_at':now_iso(),
            'project_ids':list(pmap),'inputs':inputs,'results':results,'gaps':gaps,'warnings':list(dict.fromkeys(warnings)),
            'status':'AVAILABLE' if results and not gaps else 'PARTIAL' if results else 'MISSING',
            'evidence_sha256':digest({'inputs':inputs,'recipe':recipe}),'request':copy.deepcopy(payload)}
