"""Project-scoped R3 tools. No formula, energy or chemical-potential override."""
SELECTOR = {'type':'object','properties':{k:{'type':'string'} for k in ('task_id','query','task_type','observation_id')},'additionalProperties':False}
TARGET = {'type':'object','properties':{
    'label':{'type':'string'}, 'removed_oxygen_index':{'type':'integer','minimum':1},
    **{r:SELECTOR for r in ('pristine','defect','reference','model','complex','surface','adsorbate','path')}},'additionalProperties':False}
TOOLS = [
    {'type':'function','function':{'name':'get_property_recipes','description':'查询科学性质定义、固定公式和数据需求；未支持性质为UNSUPPORTED。数值由Python工具计算，禁止自行编造公式或结果。',
        'parameters':{'type':'object','properties':{},'additionalProperties':False}}},
    {'type':'function','function':{'name':'discover_property_tasks','description':'在当前项目只读查找科学性质的候选任务。名称不能证明缺陷、位点或参考态；用task_id精确绑定，多个conN需选择观测。',
        'parameters':{'type':'object','properties':{'query':{'type':'string','maxLength':200},'task_type':{'type':'string','enum':['opt','ele','neb','frac']},'task_id':{'type':'string'}},'additionalProperties':False}}},
    {'type':'function','function':{'name':'evaluate_property','description':'按注册配方只读验证精确任务/观测，并由Python计算及保存数据需求报告。禁止自行算最终数值。氧参考缺失仅在明确共同参考条件成立时给差值；绝对mu_O必须由用户在面板明确设置。缺口、未验证条件及候选必须呈现。工具不创建/提交作业。',
        'parameters':{'type':'object','properties':{'property_id':{'type':'string'},'targets':{'type':'array','items':TARGET,'minItems':1,'maxItems':8},
            'common_oxygen_reference':{'type':'boolean'},'reference_conditions':{'type':'string'},'surface_side':{'type':'string','enum':['start','end']},'reaction_correspondence':{'type':'string'}},
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
    properties.authorized_projects(db,user,[project['project_id']])
    if name == 'discover_property_tasks':
        if set(arguments)-{'query','task_type','task_id'}: raise ValueError('不支持的任务发现参数')
        return properties.discover(db,user,[project['project_id']],**arguments)
    if name != 'evaluate_property' or set(arguments)-{'property_id','targets','common_oxygen_reference','reference_conditions','surface_side','reaction_correspondence'}:
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
