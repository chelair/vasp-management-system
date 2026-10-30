"""Project-scoped R3 tools. No formula, energy or chemical-potential override."""
import math

SELECTOR = {'type':'object','properties':{k:{'type':'string'} for k in ('task_id','query','task_type','observation_id')},'additionalProperties':False}
TARGET = {'type':'object','properties':{
    'label':{'type':'string'}, 'removed_oxygen_index':{'type':'integer','minimum':1},
    **{r:SELECTOR for r in ('pristine','defect','reference','model','complex','surface','adsorbate','path')}},'additionalProperties':False}
TOOLS = [
    {'type':'function','function':{'name':'get_bader_charges',
        'description':'读取当前项目已完成的Bader分析，返回该次分析的元素、坐标和紧凑电荷表；atom_indices指定片段后由Python求和。可一次查询多个任务/片段，并计算相同组成片段相对首项的净电荷差。先查已有结构分层/本表定位片段；元素归属以分析时记录为准，不按当前结构盲套编号。不必先读目录地图、原始ACF或查询性质配方。有明确参考片段净电荷时传reference_charge（e），才计算得失电子数；中性参考为0，带电参考保留其电荷。不触发远端计算。',
        'parameters':{'type':'object','properties':{'targets':{'type':'array','minItems':1,'items':{'type':'object','properties':{
            'task_id':{'type':'string'},'atom_indices':{'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'integer','minimum':1}},
            'reference_charge':{'type':'number'}},'required':['task_id'],'additionalProperties':False}}},
            'required':['targets'],'additionalProperties':False}}},
    {'type':'function','function':{'name':'get_property_recipes','description':'查询科学性质定义、固定公式和数据需求；未支持性质为UNSUPPORTED。数值由Python工具计算，禁止自行编造公式或结果。',
        'parameters':{'type':'object','properties':{},'additionalProperties':False}}},
    {'type':'function','function':{'name':'discover_property_tasks','description':'在当前项目只读查找科学性质的候选任务。名称不能证明缺陷、位点或参考态；用task_id精确绑定，多个conN需选择观测。',
        'parameters':{'type':'object','properties':{'query':{'type':'string','maxLength':200},'task_type':{'type':'string','enum':['opt','ele','neb','frac']},'task_id':{'type':'string'}},'additionalProperties':False}}},
    {'type':'function','function':{'name':'evaluate_property','description':'按注册配方只读验证精确任务/观测，并由Python计算及保存数据需求报告。禁止自行算最终数值。氧参考缺失仅在明确共同参考条件成立时给差值；绝对mu_O必须由用户在面板明确设置。缺口、未验证条件及候选必须呈现。工具不创建/提交作业。',
        'parameters':{'type':'object','properties':{'property_id':{'type':'string'},'targets':{'type':'array','items':TARGET,'minItems':1,'maxItems':8},
            'common_oxygen_reference':{'type':'boolean'},'reference_conditions':{'type':'string'},'surface_side':{'type':'string','enum':['start','end']},'reaction_correspondence':{'type':'string'},'adsorbate_reference_type':{'type':'string','enum':['periodic','isolated_molecule']}},
            'required':['property_id','targets'],'additionalProperties':False}}},
]


def dispatch(project,user,name,arguments):
    import properties
    from storage import load_db
    if not isinstance(arguments,dict): raise ValueError('工具参数必须为对象')
    if name == 'get_property_recipes':
        if arguments: raise ValueError('性质注册表工具无参数')
        return properties.schema()
    db = load_db()
    # Current project is supplied by the trusted conversation, never by the model.
    current = properties.authorized_projects(db,user,[project['project_id']])[0]
    if name == 'get_bader_charges':
        import bader
        from ai_inspections import task_for
        if set(arguments) != {'targets'} or not isinstance(arguments['targets'],list) or not arguments['targets']:
            raise ValueError('请指定要统计的Bader任务/片段')
        targets = arguments['targets']
        tasks = []
        for target in targets:
            if (not isinstance(target,dict) or set(target)-{'task_id','atom_indices','reference_charge'}
                    or not isinstance(target.get('task_id'),str)):
                raise ValueError('请指定当前项目任务及可选的片段原子编号、参考净电荷')
            if 'atom_indices' in target:
                selected = target['atom_indices']
                if (not isinstance(selected,list) or not selected
                        or any(type(i) is not int or i < 1 for i in selected)
                        or len(set(selected)) != len(selected)):
                    raise ValueError('片段须使用不重复的原子编号（从1开始）')
            if 'reference_charge' in target:
                ref = target['reference_charge']
                if type(ref) not in (int,float) or not math.isfinite(ref):
                    raise ValueError('参考净电荷须为有限数，单位 e')
            tasks.append(task_for(current,target['task_id']))
        results = []
        for task,target in zip(tasks,targets):
            try:
                results.append(bader.charge_summary(current['name'],task,target.get('atom_indices'),target.get('reference_charge')))
            except (bader.BaderError,OSError,ValueError) as exc:
                results.append({'task_id':task['task_id'],'error':str(exc)})
        first = results[0]
        for result in results[1:]:
            if (first.get('net_charge_e') is not None and result.get('net_charge_e') is not None
                    and first['composition'] == result['composition']):
                result['net_charge_difference_from_first_e'] = round(result['net_charge_e']-first['net_charge_e'],6)
                result['bader_electrons_difference_from_first_e'] = round(result['bader_electrons']-first['bader_electrons'],6)
        return {'results':results,'comparison_reference':'targets[0]；差值仅比较相同组成，物理对应由研究目标确认',
                'interpretation_limits':{'numerical_convergence':'NOT_TESTED', 'mechanism':'NOT_ESTABLISHED',
                    'note':'差异小仅表示本次结果接近；未检验数值精度或控制变量，不能据此断言电荷转移饱和、机制成立或反证研究预期。'}}
    if name == 'discover_property_tasks':
        if set(arguments)-{'query','task_type','task_id'}: raise ValueError('不支持的任务发现参数')
        return properties.discover(db,user,[project['project_id']],**arguments)
    if name != 'evaluate_property' or set(arguments)-{'property_id','targets','common_oxygen_reference','reference_conditions','surface_side','reaction_correspondence','adsorbate_reference_type'}:
        raise ValueError('模型不能设置公式、能量、氧化学势或跨项目参数')
    # Reject nested project injection, even if that project would be authorized.
    for target in arguments.get('targets',[]):
        if not isinstance(target,dict): raise ValueError('目标必须为对象')
        for value in target.values():
            if isinstance(value,dict) and 'project_id' in value: raise ValueError('聊天科学工具限定当前项目')
    report = properties.evaluate(db,user,{**arguments,'project_ids':[project['project_id']]},persist=True,allow_user_reference=False)
    if report['status'] == 'UNSUPPORTED': return report
    # The complete immutable report stays on disk. Keep model evidence within the
    # existing per-round budget; large atom arrays and raw file text are unnecessary.
    compact = {k:report[k] for k in ('schema_version','report_id','property_id','status','recipe','generated_at','reference_state','currently_calculable','not_calculable','recommendations')}
    compact['inputs'] = [{k:i.get(k) for k in ('role','status','task','selector','candidates','observations')} |
        {'energy_ev':i['data'].get('energy_ev'), 'charge':i['data'].get('charge'),
         'source':{k:(i.get('source') or {}).get(k) for k in ('observation_id','directory','checked_at','row_sha256')},
         'failed_checks':[c for c in i['checks'] if c['status'] != 'AVAILABLE']} for i in report['inputs']]
    compact['results'] = [{k:r[k] for k in ('key','label','value','units','formula','formula_version','validation_status','formal_conclusion_allowed','reference_state','conditions','unverified_conditions')} for r in report['results']]
    compact['gaps'] = report['gaps'][:40]
    compact['gaps_truncated'] = len(report['gaps']) > 40
    compact['note'] = '完整冻结证据保存在性质报告；数值来自Python。正式科学结论仍需补齐报告所列未验证条件。'
    return compact
