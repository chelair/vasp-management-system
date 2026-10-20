"""R3 PropertyRecipe registry, authorized local discovery and deterministic evaluation.

Discovery never executes a scientific analyzer, inspection, SSH or HPC action.
Only derived reports are persisted, separately from original scientific evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
import copy
import json
import os
import re
import uuid

import adsorption_science
import permissions
from ai_inspections import query_inspections, task_for, _age, participation
from checks_store import collect_task_observations
from config import DATA_DIR
from dates import now_iso
from property_science import VERSION, check, compatibility, digest, normalize, number, vacancy
from task_paths import is_auxiliary_task

STATUSES = ('AVAILABLE','MISSING','INCOMPLETE','INVALID','STALE','AMBIGUOUS','UNKNOWN')
REPORT_DIR = DATA_DIR / 'reports' / 'properties'


def subtract(a,b): return float(Decimal(str(a))-Decimal(str(b)))
def formation(defect,pristine,mu): return float(Decimal(str(defect))-Decimal(str(pristine))+Decimal(str(mu)))
def adsorption(complex_energy,surface,adsorbate): return float(Decimal(str(complex_energy))-Decimal(str(surface))-Decimal(str(adsorbate)))
def barrier(values): return subtract(max(values),values[0])


@dataclass(frozen=True)
class PropertyRecipe:
    property_id: str
    definition: str
    scope: str
    required_inputs: tuple
    optional_inputs: tuple
    required_checks: tuple
    calculation_function: str
    formula: str
    output_units: str = 'eV'
    missing_data_policy: str = '保留逐项缺口；未验证数据不产生正式数值；可独立验证的部分单列'
    version: str = VERSION


RECIPES = {r.property_id:r for r in (
    PropertyRecipe('oxygen_vacancy.neutral_single', '中性单氧空位形成能及体系间差值', '相同晶胞、按输入原子顺序可验证只移除一个O的中性模型；不处理带电缺陷',
        ('targets[].pristine','targets[].defect','mu_O或明确共同参考的差值条件'), ('mu_O','common_oxygen_reference','targets[].removed_oxygen_index'),
        ('single_oxygen_vacancy','vacancy_site','charge_state','electronic_convergence','ionic_convergence','theory_compatibility','reference_conditions'),
        'formation / subtract', 'E_f(V_O) = E_defect - E_pristine + mu_O; delta = E_f(B) - E_f(A)'),
    PropertyRecipe('relative_energy', '相同组成模型的相对总能量', '首版为中性且相同组成/理论设置；不是不同组成的反应能或自由能',
        ('targets[].reference','targets[].model'), (), ('composition','charge_state','convergence','theory_compatibility'), 'subtract', 'delta_E = E_model - E_reference'),
    PropertyRecipe('adsorption.simple', '一个中性吸附物的简单电子吸附能', '每组一个完整中性吸附物；complex = surface + adsorbate，复合体系/表面同晶胞且输入表面原子按序对应；固定参考态，不含ZPE、温熵、电位、溶剂和BSSE修正',
        ('targets[].complex','targets[].surface','targets[].adsorbate'), ('reference_conditions','adsorbate_reference_type'),
        ('stoichiometry','adsorption_relation','adsorption_cell','charge_state','convergence','theory_compatibility','adsorbate_reference_type'), 'adsorption', 'E_ads = E_complex - E_surface - E_adsorbate',version=adsorption_science.VERSION),
    PropertyRecipe('neb.barrier', '读取已有NEB映像能量并比较正向能垒', '中性体系完整、收敛的既有NEB路径离散映像；不运行NEB或nebef，不等同热力学台阶',
        ('targets[].path',), (), ('image_completeness','neb_convergence','source_identity','reaction_correspondence'), 'barrier / subtract', 'E_a = max(E_images) - E_initial; delta = E_a(B) - E_a(A)'),
    PropertyRecipe('work_function.difference', '已有功函数之差', '相同真空方向、表面侧、可比理论条件与可靠真空平台的中性表面；不触发LOCPOT分析',
        ('targets[].reference','targets[].model'), ('surface_side',), ('vacuum_reference','direction','source_identity','convergence','theory_compatibility'),
        'subtract', 'delta_Phi = Phi_model - Phi_reference'),
)}


def schema():
    return {'schema_version':VERSION, 'recipes':[asdict(r) for r in RECIPES.values()], 'input_statuses':STATUSES,
            'unsupported_policy':'UNSUPPORTED；不执行模型提供的公式或数值',
            'selector_fields':['project_id','task_id','query','task_type','observation_id'],
            'note':'名称只返回候选；正式计算必须精确绑定task_id及必要的observation_id。'}


def authorized_projects(db,user,refs):
    if not isinstance(refs,list) or not 1 <= len(refs) <= 8 or any(not isinstance(r,str) or not r or len(r)>200 for r in refs):
        raise ValueError('请选择1至8个项目')
    selected = []
    for ref in refs:
        p = next((p for p in db.get('projects',[]) if ref in (p.get('project_id'),p.get('name'))),None)
        if p is None: raise LookupError('项目不存在')
        permissions.ensure_project_owner(p,user)
        if p not in selected: selected.append(p)
    return selected


def discover(db,user,project_ids,query='',task_type=None,task_id=None):
    projects = authorized_projects(db,user,project_ids)
    if not isinstance(query,str) or len(query)>200: raise ValueError('查询最多200字符')
    if task_type is not None and task_type not in ('opt','ele','neb','frac'): raise ValueError('计算类型无效')
    matches = []
    for p in projects:
        for task in p.get('tasks',[]):
            if is_auxiliary_task(task): continue
            if task_id and task.get('task_id') != task_id: continue
            if task_type and task.get('task_type') != task_type: continue
            if query.casefold() not in str(task.get('model_name') or '').casefold() and query.casefold() not in str(task.get('task_id') or '').casefold(): continue
            matches.append({'project_id':p['project_id'],'task_id':task['task_id'],'model_name':task.get('model_name'),
                            'task_type':task.get('task_type'),'status':task.get('status'),
                            'binding_status':'CANDIDATE','relation_verified':False})
    return {'matches':matches[:100], 'total':len(matches),'truncated':len(matches)>100,
            'note':'名称不是结构关系证据；同名/多位点候选不会自动绑定。'}


def _state(checks):
    for state in ('INVALID','AMBIGUOUS','STALE','MISSING','INCOMPLETE','UNKNOWN'):
        if any(c['status'] == state for c in checks): return state
    return 'AVAILABLE'


def _selector(value, default_project):
    if not isinstance(value,dict): raise ValueError('任务选择必须为对象')
    if set(value)-{'project_id','task_id','query','task_type','observation_id'}: raise ValueError('任务选择不接受公式、数值、文件或未定义字段')
    for k,v in value.items():
        if not isinstance(v,str) or not v or len(v)>200: raise ValueError('任务选择字段必须是1至200字符文本')
    return {**value,'project_id':value.get('project_id',default_project)}


def _input(db,user,projects,selector,role):
    ref = selector['project_id']
    if ref not in {p['project_id'] for p in projects} | {p['name'] for p in projects}:
        raise ValueError('绑定项目必须列在project_ids范围内')
    p = authorized_projects(db,user,[ref])[0]  # recheck every cross-project reference
    result = {'role':role,'selector':selector,'status':'MISSING','checks':[],'candidates':[], 'data':{}}
    if not selector.get('task_id'):
        found = discover(db,user,[ref],selector.get('query',''),selector.get('task_type'))
        result.update(candidates=found['matches'],status='AMBIGUOUS' if found['total'] else 'MISSING')
        result['checks'] = [check('task_binding',result['status'],'请选择精确task_id，名称匹配不自动确认关系')]
        return result
    task = task_for(p,selector['task_id'])
    result['task'] = {'project_id':p['project_id'],'task_id':task['task_id'],'model_name':task.get('model_name'),'type':task.get('task_type')}
    if selector.get('task_type') and task.get('task_type') != selector['task_type']:
        result.update(status='INVALID',checks=[check('task_type','INVALID','所选计算类型不符')]); return result
    rows = collect_task_observations(task['task_id'],limit=5)
    result['observations'] = [{k:o.get(k) for k in ('observation_id','archive','directory')} for o in rows]
    if selector.get('observation_id'):
        selected = next((o for o in rows if o['observation_id'] == selector['observation_id']),None)
        if selected is None:
            result.update(status='STALE',checks=[check('observation','STALE','观测已更新或淘汰，请重新选择')]); return result
    elif len(rows) == 1: selected = rows[0]
    elif len(rows) > 1:
        result.update(status='AMBIGUOUS',checks=[check('observation','AMBIGUOUS','存在多个conN快照，请选择observation_id；不拼接不同目录')]); return result
    else:
        result['checks']=[check('observation','MISSING','缺少原始巡检观测，不使用任务库合并能量替代')]; return result
    row = selected['data']
    result['source'] = {'project_id':p['project_id'],'task_id':task['task_id'],'observation_id':selected['observation_id'],
                        'archive':selected['archive'],'directory':selected.get('directory') or {'path':(row.get('current_output') or {}).get('dir')},'checked_at':row.get('checked_at'),
                        'job_id':row.get('job_id'),'row_sha256':digest(row)}
    result['frozen_observation'] = copy.deepcopy(row)
    evidence = row.get('property_evidence') or {}
    if task.get('task_type') == 'neb':
        images = evidence.get('neb_images') or []
        normalized, checks = [], []
        for image in images:
            item = copy.deepcopy(image.get('evidence') or {})
            for name in ('INCAR','KPOINTS'):
                item.setdefault('files',{})[name] = copy.deepcopy((evidence.get('files') or {}).get(name) or {})
            item['potcar'] = copy.deepcopy(evidence.get('potcar') or {})
            d, cs = normalize(item,row,neb_image=True)
            normalized.append({'label':image.get('label'),'data':d})
            checks += [{**c,'check':str(image.get('label'))+'.'+c['check']} for c in cs]
        if not normalized or evidence.get('images_truncated'):
            checks.append(check('neb_images','INCOMPLETE','NEB映像证据缺失或超出32映像上限'))
        if normalized: checks += compatibility([i['data'] for i in normalized],same_composition=True,same_cell=True)
        data = normalized[0]['data'] if normalized else {}
        result['neb_snapshots'] = normalized
    else:
        data, checks = normalize(evidence,row)
    result['data'] = data
    expected = (row.get('current_output') or {}).get('dir')
    checks.append(check('snapshot_directory','AVAILABLE' if expected and evidence.get('directory') == expected else 'UNKNOWN', '结构、参数、能量必须来自同一观测目录'))
    if not task.get('current_output'):
        checks.append(check('current_identity','UNKNOWN','任务缺少当前输出目录身份，不能确认这是当前快照'))
    if row.get('parameter_source_mismatch'):
        checks.append(check('parameter_source','INVALID','归档参数回退到其他目录'))
    current = query_inspections(p,task['task_id'],limit=1)
    fresh = current['freshness']
    age = _age(row.get('checked_at'))
    if age is None or age < -300:
        checks.append(check('freshness','UNKNOWN','观测时间缺失或无效'))
    elif participation(p,task)['included'] and age > 4*3600:
        checks.append(check('freshness','STALE','参与自动巡检任务的观测超过4小时'))
    if selected['observation_id'] != rows[0]['observation_id'] or fresh['source_mismatch'] or not current['observations'] or selected['observation_id'] != current['observations'][0]['observation_id']:
        checks.append(check('current_identity','STALE','所选观测不是当前执行快照；历史事实保留，不能冒充当前结论'))
    if row.get('status') in ('running','queued','pending','zombied','unconverged'):
        checks.append(check('run_state','INCOMPLETE','计算运行中、异常或未收敛'))
    result.update(checks=checks,status=_state(checks))
    result['source']['files'] = {name:{k:f.get(k) for k in ('sha256','hash_basis','size','mtime_ns','stable')} for name,f in (evidence.get('files') or {}).items()}
    result['source']['potcar'] = evidence.get('potcar')
    result['source']['snapshot_fingerprint'] = evidence.get('fingerprint')
    # Use already parsed NEB arrays from this observation, never nebef execution.
    result['neb'] = copy.deepcopy(row.get('neb_barrier'))
    if task.get('task_type') == 'neb':
        images = (row.get('neb_barrier') or {}).get('images') or []
        result['neb_incar'] = row.get('incar') or {}
        result['neb_converged'] = row.get('force_converged')
        result['neb_status'] = row.get('status')
        # A path has no root OUTCAR; individual image validation must be available.
    return result


def _result(key,label,value,formula,inputs,checks,reference=None,conditions=None,version=VERSION):
    value = number(value)
    unverified = ['ENCUT/k网格等数值收敛性、磁态/基态和模型物理适用性未由本次运算证明；结果为所选DFT模型下的值']
    if any(i.get('data',{}).get('geometry_state') == 'fixed_geometry_without_relaxation_verification' for i in inputs):
        unverified.append('含NSW=0的固定几何电子能；尚未证明这些几何已完成离子弛豫')
    return {'key':key,'label':label,'value':value,'units':'eV','formula':formula,'formula_version':version,
            'validation_status':'PASS','formal_conclusion_allowed':False, 'numerical_reliability':'NOT_TESTED', 'scientific_conclusion':'NOT_TESTED',
            'sources':[i.get('source') for i in inputs], 'checks':checks,
            'reference_state':reference, 'conditions':conditions or [],
            'unverified_conditions':unverified}


def evaluate(db,user,payload,*,persist=False,allow_user_reference=True):
    if not isinstance(payload,dict) or set(payload)-{'property_id','project_ids','targets','mu_O','common_oxygen_reference','reference_conditions','surface_side','reaction_correspondence','adsorbate_reference_type'}:
        raise ValueError('只接受注册性质及任务/参考态绑定，不接受自定义公式或替代数值')
    for key in ('reference_conditions','reaction_correspondence'):
        if key in payload and (not isinstance(payload[key],str) or not payload[key].strip() or len(payload[key])>2000):
            raise ValueError('参考条件与反应对应必须是明确文本')
    if 'surface_side' in payload and payload['surface_side'] not in ('start','end'):
        raise ValueError('表面侧必须是start或end')
    if payload.get('adsorbate_reference_type','periodic') not in ('periodic','isolated_molecule'):raise ValueError('吸附物参考类型必须为periodic或isolated_molecule')
    pid = payload.get('property_id')
    if not isinstance(pid,str) or len(pid)>100: raise ValueError('科学性质标识无效')
    if pid not in RECIPES: return {'schema_version':VERSION,'property_id':pid,'status':'UNSUPPORTED','results':[], 'reason':'未注册性质；禁止临时生成计算公式'}
    projects = authorized_projects(db,user,payload.get('project_ids'))
    recipe = RECIPES[pid]
    targets = payload.get('targets',[])
    if not isinstance(targets,list) or not 1 <= len(targets) <= 8: raise ValueError('请选择1至8个目标体系')
    if 'common_oxygen_reference' in payload and type(payload['common_oxygen_reference']) is not bool: raise ValueError('共同氧参考条件必须是布尔值')
    roles = {'oxygen_vacancy.neutral_single':('pristine','defect'), 'relative_energy':('reference','model'),
             'adsorption.simple':('complex','surface','adsorbate'), 'neb.barrier':('path',), 'work_function.difference':('reference','model')}[pid]
    inputs,groups,results,checks = [],[],[],[]
    # Preflight ALL referenced project permissions before reading any scientific evidence.
    for target in targets:
        if not isinstance(target,dict) or set(target)-set(roles)-{'label','removed_oxygen_index'}: raise ValueError('目标体系字段无效')
        for role in roles:
            selector = _selector(target.get(role,{}),projects[0]['project_id'])
            authorized_projects(db,user,[selector['project_id']])
    for index,target in enumerate(targets):
        label = target.get('label') or f'体系{index+1}'
        if not isinstance(label,str) or len(label)>200: raise ValueError('体系标签无效')
        if 'removed_oxygen_index' in target and (type(target['removed_oxygen_index']) is not int or target['removed_oxygen_index'] <= 0): raise ValueError('氧原子序号必须是正整数')
        bound = {role:_input(db,user,projects,_selector(target.get(role,{}),projects[0]['project_id']),f'{index}.{role}') for role in roles}
        inputs.extend(bound.values())
        group = {'label':label,'input_roles':list(bound),'checks':[],'status':'MISSING'}
        groups.append(group)
        if not all(i['status'] == 'AVAILABLE' for i in bound.values()):
            group['status'] = _state([check(i['role'],i['status'],'输入未通过') for i in bound.values()]); continue
        values = list(bound.values()); data = [i['data'] for i in values]
        if pid == 'oxygen_vacancy.neutral_single':
            group['checks'],group['site'] = vacancy(bound['pristine']['data'],bound['defect']['data'],target.get('removed_oxygen_index'))
            if _state(group['checks']) == 'AVAILABLE':
                group['energy_cost_without_reference_ev'] = subtract(bound['defect']['data']['energy_ev'],bound['pristine']['data']['energy_ev'])
        elif pid == 'relative_energy':
            group['checks'] = compatibility(data,same_composition=True)
            if _state(group['checks']) == 'AVAILABLE':
                results.append(_result(f'{index}.relative_energy',label,subtract(bound['model']['data']['energy_ev'],bound['reference']['data']['energy_ev']),recipe.formula,values,group['checks']))
        elif pid == 'adsorption.simple':
            reference_type=payload.get('adsorbate_reference_type','periodic')
            group['checks'],group['site']=adsorption_science.validate(*(bound[r]['data'] for r in roles),reference_type)
            if _state(group['checks']) == 'AVAILABLE':
                ref={'type':'adsorbate_calculation','reference_type':reference_type,'source':bound['adsorbate']['source'],
                     'composition':bound['adsorbate']['data']['structure']['composition'],'energy_ev':bound['adsorbate']['data']['energy_ev'],
                     'conditions':('参考条件声明（未验证）：'+payload['reference_conditions']) if payload.get('reference_conditions') else '仅电子能；参考盒尺寸与自旋基态仍需独立验证'}
                results.append(_result(f'{index}.adsorption',label,adsorption(*(bound[r]['data']['energy_ev'] for r in roles)),recipe.formula,values,group['checks'],ref,
                    conditions=[recipe.scope,ref['conditions'],'负值表示所选电子能参考下放热；不等同于吸附自由能。'],version=recipe.version))
        # NEB and work function are handled by dedicated source adapters below.
        elif pid in ('neb.barrier','work_function.difference'):
            try:
                _existing_analysis(pid,recipe,index,label,bound,group,results,payload,projects)
            except (ValueError,TypeError,KeyError,OSError) as exc:
                group['checks'].append(check('analysis_source','INVALID','已有分析证据无效：'+str(exc)))
        group['status'] = _state(group['checks'])
    mu = payload.get('mu_O')
    reference = None
    if pid == 'oxygen_vacancy.neutral_single':
        if mu is not None:
            if not allow_user_reference: raise ValueError('模型不能设置氧化学势数值；请用户在科学性质面板明确设置')
            if not isinstance(mu,dict) or set(mu) != {'value_ev','source','conditions'} or any(not isinstance(mu[k],str) or not mu[k].strip() or len(mu[k])>2000 for k in ('source','conditions')):
                raise ValueError('mu_O需要value_ev、明确来源source和适用条件conditions')
            mu_value = number(mu['value_ev'])
            reference = {'type':'user_explicit_oxygen_chemical_potential','value_ev_per_O':mu_value,'source':mu['source'],'conditions':mu['conditions'],'set_by':permissions.username_of(user)}
            checks.append(check('mu_O','AVAILABLE','用户明确设置；保存原始来源和适用条件，不由模型补造'))
        else:
            checks.append(check('mu_O','MISSING','绝对形成能需要每个O的化学势（例如明确条件下1/2 E(O2)，含所采用修正）；本轮不自动计算参考态'))
        valid = []
        for index,(group,target) in enumerate(zip(groups,targets)):
            if group['status'] != 'AVAILABLE': continue
            valid.append((index,group))
            if reference:
                cost = group['energy_cost_without_reference_ev']
                results.append(_result(f'{index}.formation_energy',group['label'],formation(cost,0,reference['value_ev_per_O']),
                    'E_f = E_defect - E_pristine + mu_O',[i for i in inputs if i['role'].startswith(str(index)+'.')],group['checks'],reference,[recipe.scope]))
        if len(valid)>1:
            base_index,base = valid[0]
            for index,other in valid[1:]:
                pair_inputs = [i for i in inputs if i['role'].split('.')[0] in (str(base_index),str(index))]
                pair_checks = compatibility([i['data'] for i in pair_inputs])
                shared = bool(reference or payload.get('common_oxygen_reference') is True)
                pair_checks.append(check('common_oxygen_reference','AVAILABLE' if shared else 'UNKNOWN','差值要求中性单O缺陷采用相同mu_O及适用条件；消去+mu_O - mu_O'))
                checks.extend(pair_checks)
                if _state(pair_checks) == 'AVAILABLE':
                    results.append(_result(f'{index}-{base_index}.formation_difference',other['label']+' − '+base['label'],
                        subtract(other['energy_cost_without_reference_ev'],base['energy_cost_without_reference_ev']),
                        'delta_E_f = (E_defect_B - E_pristine_B) - (E_defect_A - E_pristine_A)',pair_inputs,pair_checks,
                        reference or {'type':'shared_oxygen_reference_cancelled','value_required':False},
                        ['两体系中性且各移除一个O；相同氧化学势和条件，mu_O精确消去。','差值方向为后一个体系减第一个体系。']))
        # The intermediate E_def-E_pris is not an absolute vacancy formation energy.
        for g in groups: g.pop('energy_cost_without_reference_ev',None)
    if pid == 'adsorption.simple' and len(results)>1:
        original=list(results);base=original[0]
        for other in original[1:]:
            base_index,other_index=base['key'].split('.')[0],other['key'].split('.')[0]
            involved=[i for i in inputs if i['role'].split('.')[0] in (base_index,other_index)]
            ref_sources=[r['reference_state']['source'] for r in (base,other)]
            shared=all(ref_sources[0].get(k)==ref_sources[1].get(k) for k in ('project_id','task_id','observation_id','row_sha256'))
            pair_checks=compatibility([i['data'] for i in involved if not i['role'].endswith('.adsorbate')])
            pair_checks.append(check('common_adsorbate_reference','AVAILABLE' if shared else 'UNKNOWN','吸附能差值要求同一个吸附物参考任务及同一观测；不默认不同参考态等价'))
            checks+=pair_checks
            if _state(pair_checks)=='AVAILABLE':
                results.append(_result(other_index+'-'+base_index+'.adsorption_difference',other['label']+' − '+base['label'],subtract(other['value'],base['value']),
                    'delta_E_ads = (E_complex_B - E_surface_B) - (E_complex_A - E_surface_A)',involved,pair_checks,
                    {'type':'shared_adsorbate_reference_cancelled','source':ref_sources[0]},
                    ['同一个吸附物参考精确消去 −E_adsorbate + E_adsorbate；差值为后一个体系减第一个体系。','表面积、覆盖度、固定层和磁态的科学可比性仍需独立验证。',recipe.scope],version=recipe.version))
    if pid == 'neb.barrier' and len(results)>1:
        original = list(results)
        for r in original[1:]:
            involved = [i for i in inputs if i['role'].split('.')[0] in (r['key'].split('.')[0],original[0]['key'].split('.')[0])]
            comparison_checks = compatibility([i['data'] for i in involved])
            checks.extend(comparison_checks)
            if payload.get('reaction_correspondence') and _state(comparison_checks) == 'AVAILABLE':
                results.append(_result(r['key']+'-0.difference',r['label']+' − '+original[0]['label'],subtract(r['value'],original[0]['value']),
                    'delta_E_a = E_a(B) - E_a(A)',involved,comparison_checks+[check('reaction_correspondence','AVAILABLE',str(payload['reaction_correspondence']))],conditions=['用户明确的反应路径对应关系']))
            else: checks.append(check('reaction_correspondence','UNKNOWN','能垒差值需要明确反应、方向与初末态对应关系'))
    gaps = [{'role':i['role'],**c} for i in inputs for c in i['checks'] if c['status'] != 'AVAILABLE']
    gaps += [{'role':g['label'],**c} for g in groups for c in g['checks'] if c['status'] != 'AVAILABLE']
    gaps += [c for c in checks if c['status'] != 'AVAILABLE']
    suggestions = []
    for gap in gaps:
        name = gap['check']
        if gap['status'] == 'AMBIGUOUS': advice = '先选择具体任务/观测/位点；不要因名称相似直接补算或合并。'
        elif gap['status'] == 'STALE': advice = '先刷新只读证据并核对当前目录/作业；不据旧快照要求重算。'
        elif name in ('electronic_convergence','ionic_convergence','run_state'): advice = '人工核实收敛失败原因；确需续算时采用兼容理论设置，本报告仅给建议。'
        elif name.startswith('compatibility.'): advice = '先核对理论设置；若确实不兼容，建议用同一可比设置重新计算受影响模型。'
        elif name == 'mu_O': advice = '明确每个O的化学势来源和条件；需要时补充兼容的氧参考计算及修正，但不自动创建任务。'
        elif name == 'task_binding': advice = '先检索已有结果；确实缺少对应完整/缺陷/参考模型时，人工准备并计算所需模型。'
        else: advice = '补齐该项来源或验证证据后重新评估；缺证据不等于必须重算。'
        suggestions.append({'role':gap.get('role'),'check':name,'advice':advice,'automatic_execution':False})
    report = {'schema_version':VERSION,'property_id':pid,'recipe':asdict(recipe),'generated_at':now_iso(),
              'project_ids':[p['project_id'] for p in projects], 'created_by':permissions.username_of(user), 'request':copy.deepcopy(payload),
              'status':'PARTIAL' if results and gaps else 'AVAILABLE' if results else 'BLOCKED',
              'inputs':inputs,'targets':groups,'reference_state':reference,'checks':checks,'gaps':gaps,'results':results,
              'currently_calculable':[r['key'] for r in results],
              'not_calculable':(['absolute_formation_energy'] if pid == 'oxygen_vacancy.neutral_single' and reference is None else []) + (['adsorption_energy_difference'] if pid=='adsorption.simple' and any(c['check']=='common_adsorbate_reference' and c['status']!='AVAILABLE' for c in checks) else []) + [g['label'] for g in groups if g['status'] != 'AVAILABLE'],
              'recommendations':list(dict.fromkeys(c['detail'] for c in gaps)), 'supplemental_suggestions':suggestions,
              'report_elements':_report_elements(inputs,results,projects),
              'execution_policy':'只读发现与确定性运算；补算仅建议，不创建或提交作业。'}
    # Freeze the exact evidence used in every numerical result for audit/reproduction.
    report['evidence_sha256'] = digest({'inputs':inputs,'recipe':asdict(recipe),'reference':reference})
    if persist: _save(report)
    return report


def _report_elements(inputs,results,projects):
    from report_blocks import list_candidates
    items = []
    task_ids = {i['task']['task_id'] for i in inputs if i.get('task')}
    for project in projects:
        catalog = list_candidates(project)
        for candidate in catalog['candidates']:
            if candidate.get('task_id') in task_ids or set(candidate.get('task_ids') or []) & task_ids or candidate['type'] == 'method.source':
                items.append({k:candidate.get(k) for k in ('type','task_id','group_id','block_id','availability','title')})
    if results: items.append({'type':'derived_result_artifact','source':'frozen_property_report','format':'JSON','note':'R3面板与保存的JSON提供数值、公式和条件；不是已注册R2元素'})
    return items


def _save(report):
    REPORT_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
    report['report_id'] = 'prop_'+uuid.uuid4().hex
    path = REPORT_DIR / (report['report_id']+'.json')
    temp = REPORT_DIR / ('.'+report['report_id']+'.tmp')
    try:
        with os.fdopen(os.open(temp,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600),'w',encoding='utf-8') as handle:
            json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def read_report(db,user,report_id):
    if not re.fullmatch(r'prop_[0-9a-f]{32}',report_id): raise LookupError('性质报告不存在')
    path = REPORT_DIR / (report_id+'.json')
    if not path.is_file(): raise LookupError('性质报告不存在')
    report = json.loads(path.read_text())
    authorized_projects(db,user,report['project_ids'])
    return report


def _existing_analysis(pid,recipe,index,label,bound,group,results,payload,projects):
    """Safe existing-analysis adapters: no scientific recomputation or remote calls."""
    if pid == 'neb.barrier':
        source = bound['path']
        images = (source.get('neb') or {}).get('images') or []
        try:
            expected = int(source.get('neb_incar',{}).get('IMAGES',-1))+2
            energy = [number(i['energy']) for i in images]
            labels = [str(i.get('label',i.get('image',''))) for i in images]
            complete = len(energy) == expected and expected >= 3 and all(l.isdigit() for l in labels) and list(map(int,labels)) == list(range(expected))
        except (ValueError,TypeError,KeyError): energy,complete,expected = [],False,-1
        group['checks'] = [check('image_completeness','AVAILABLE' if complete else 'INCOMPLETE','需IMAGES+2个按00到末态连续排序的有限能量，包括初末态'),
                           check('neb_image_validation','AVAILABLE' if len(source.get('neb_snapshots',[])) == expected and [str(i['label']).lstrip('0') or '0' for i in source.get('neb_snapshots',[])] == [str(i) for i in range(expected)] and all(abs(i['data'].get('energy_ev',float('inf'))-v)<1e-5 for i,v in zip(source.get('neb_snapshots',[]),energy)) else 'UNKNOWN','每个映像快照能量与已有nebef能量核对，收敛/参数检查逐映像完成')]
        if _state(group['checks']) == 'AVAILABLE':
            results.append(_result(f'{index}.barrier',label,barrier(energy),recipe.formula,[source],group['checks'],conditions=['已有离散映像能垒；未证明过渡态唯一性或完成鞍点频率验证']))
    else:
        import work_function
        from report_block_science import checked_path
        data = []
        for source in bound.values():
            p = next(p for p in projects if p['project_id'] == source['task']['project_id'])
            task = task_for(p,source['task']['task_id'])
            path = checked_path(p,task,work_function.meta_path(p['name'],task))
            if not path.is_file():
                group['checks'].append(check('work_function','MISSING','缺少已有功函数分析')); continue
            meta = json.loads(path.read_text())
            summary = meta.get('result') or {}
            source['source']['work_function'] = {'sha256':digest(meta),'result':summary,'remote':meta.get('remote')}
            expected = source['data']
            good = meta.get('status') == 'done' and (meta.get('remote') or {}).get('remote_dir') == (source.get('source',{}).get('directory') or {}).get('path')
            raw_path = checked_path(p,task,work_function.data_path(p['name'],task))
            points = work_function.parse_planar_average(raw_path.read_text()) if raw_path.is_file() else []
            plateau = work_function._plateau(points)
            selected_side = payload.get('surface_side')
            try:
                good_plateau = bool(plateau and plateau['spread'] <= 0.05 and plateau['points'] >= 5
                                    and abs(number(plateau['value'])-number(summary['vacuum_level'])) <= 0.05
                                    and selected_side == plateau['side'])
                consistent_phi = abs(number(summary['vacuum_level'])-number(summary['efermi'])-number(summary['work_function'])) < 1e-3
            except (ValueError,TypeError,KeyError): good_plateau,consistent_phi = False,False
            source['source']['work_function']['curve_sha256'] = digest(points)
            source['source']['work_function']['plateau_check'] = plateau
            group['checks'].append(check('vacuum_reference','AVAILABLE' if good and good_plateau and consistent_phi else 'UNKNOWN','分析目录匹配；用户明确start/end表面侧；已有电位曲线至少5点平台极差≤0.05eV，参考能级一致'))
            analysis_age = _age(meta.get('finished_at'))
            observation_age = _age(source['source'].get('checked_at'))
            group['checks'].append(check('analysis_freshness','AVAILABLE' if analysis_age is not None and observation_age is not None and 0 <= analysis_age <= observation_age else 'STALE','分析不得早于所选计算快照或来自未来'))
            try: data.append((number(summary['work_function']),summary.get('axis'),selected_side))
            except (ValueError,TypeError,KeyError): group['checks'].append(check('work_function','INVALID','功函数数值缺失/非有限'))
        group['checks'] += compatibility([i['data'] for i in bound.values()])
        if len(data) == 2:
            group['checks'].append(check('direction','AVAILABLE' if data[0][1] and data[0][1:] == data[1][1:] else 'INVALID','真空方向和表面侧必须相同'))
            if _state(group['checks']) == 'AVAILABLE':
                results.append(_result(f'{index}.work_function_difference',label,subtract(data[1][0],data[0][0]),recipe.formula,list(bound.values()),group['checks']))
