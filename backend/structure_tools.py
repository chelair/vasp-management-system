"""AI structure tools: project-authorized, bounded read-only geometry evidence."""
import math

import permissions
from storage import load_db
import structure_geometry as geometry
from structure_sources import load_many, load_check_evidence, selector
import structure_check

SELECTOR = {'type':'object','properties':{
    'task_id':{'type':'string','maxLength':200}, 'file':{'type':'string','enum':['POSCAR','CONTCAR'],'default':'CONTCAR'},
    'source':{'type':'string','enum':['local','remote'],'default':'local'},
    'directory':{'type':'string','description':'仅remote支持：CURRENT、MAIN或conN；本地仅有镜像'},
    'image':{'type':'string','description':'NEB必填00/01等映像号'},
    'expected_sha256':{'type':'string','description':'沿用概览返回的selector指纹；结构变化则拒绝混用'}},
    'required':['task_id'],'additionalProperties':False}
PBC = {'type':'array','items':{'type':'boolean'},'minItems':3,'maxItems':3,
       'description':'晶格a/b/c方向的周期边界，默认全true；孤立分子可显式设false'}
INDEX = {'type':'integer','minimum':1,'maximum':geometry.MAX_ATOMS}
ELEMENTS = {'type':'array','items':{'type':'string','maxLength':3},'minItems':1,'maxItems':12}


def tool(name,description,properties,required):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}


TOOLS = [
    tool('get_project_research_context',
        '读取当前项目的计算目标、预期、说明与NEB端点关联。分析先以目标为判断标准，不能根据任务名猜反应；预期为空不代表计算内容没有目标。', {}, []),
    tool('analyze_reaction_path',
        '评估NEB/断键能垒能否继续、路径是否只包含目标反应时优先调用，而不是只看收敛。一次核对IS/FS的目标候选键、研究片段内部形变（排除刚体平移/转动）、O与片段外Li等接触变化、约束和同目录INCAR/KPOINTS，再看已有路径能量。默认B/F和BCOF片段仅适合相应体系，其余按目标显式指定；片段若与基底共用元素需fragment_indices。返回Python距离与固定来源selector，不把近邻当成键、不把位移当形变能、不猜目标键。需要确认目标键时在报告选择卡提问。当前结构选remote；生成报告沿用initial/final指纹，不混合重读后的结构。',
        {'path_task_id':{'type':'string'},'initial':SELECTOR,'final':SELECTOR,
         'source':{'type':'string','enum':['local','remote'],'default':'local'},'bond_elements':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':2},
         'fragment_elements':ELEMENTS,'fragment_indices':{'type':'array','items':INDEX,'minItems':2,'maxItems':96},'contact_elements':ELEMENTS,
         'contact_cutoff':{'type':'number','minimum':.5,'maximum':4},'pbc':PBC}, ['path_task_id']),
    tool('check_structure',
        '检查模型合理性或结构优化问题时优先调用。按影响从整体结构合理性/优化重构迹象、局部配位与界面、最后计算参数输出Python筛查证据；不自动判定物相/变性。元素赝势对应仅基础核对，不作为默认最高优先级。自动只读目标目录INCAR/POTCAR摘要及OUTCAR头部，缺失标未知。reference可显式选真正初始结构；省略时CONTCAR尝试同任务POSCAR（remote尝试MAIN，local仅镜像），不是完整续算历史。当前/指定con用remote。返回来源指纹，沿用selector细查。',
        {'structure':SELECTOR,'reference':SELECTOR,'pbc':PBC},['structure']),
    tool('get_structure_summary',
        '读取当前项目POSCAR/CONTCAR结构概览：组成、晶格、逐方向固定约束、几何分层/平面间隙和原子坐标分页（每页24，后续页仅坐标）。先find_project_tasks定位。层内composition和atom_indices可定位候选片段，不必逐页抄全结构。默认本地镜像，不保证最新；用户问最新/指定con时可按需source=remote只读固定文件。远端缺文件不跨目录回退，NEB指定image。后续查询沿用返回的source.selector锁定文件指纹。几何层/间隙不是材料相或真空的验证结论。',
        {'structure':SELECTOR,'pbc':PBC,'axis':{'type':'string','enum':['a','b','c'],'default':'c'},
         'atom_offset':{'type':'integer','minimum':0,'maximum':geometry.MAX_ATOMS},
         'layer_gap_angstrom':{'type':'number','minimum':.1,'maximum':3,'default':.75}},['structure']),
    tool('get_structure_environment',
        '按真实坐标和斜晶胞周期映像查询局部原子环境、距离/几何邻居数和最近6邻居的夹角。沿用概览的结构selector；原子编号从1开始。atom_indices最多6个，或用elements选择元素的前6个原子（截断会明确返回，后续按编号分批）。cutoff默认3Å，返回判据；邻居不等于化学键/价态。neighbor_elements可筛邻居元素。',
        {'structure':SELECTOR,'pbc':PBC,'atom_indices':{'type':'array','items':INDEX,'minItems':1,'maxItems':6},
         'elements':ELEMENTS,'neighbor_elements':ELEMENTS,'cutoff_angstrom':{'type':'number','minimum':.1,'maximum':6,'default':3}},['structure']),
    tool('compare_structures',
        '由Python比较两份结构的组成/晶格、原子位移与指定原子对距离变化。优化前后通常选同任务POSCAR与CONTCAR，逐一使用已读取的selector指纹。同任务同映像同元素顺序仅按原编号对应，须说明未验证同元素重排。跨任务不猜原子映射，只返回组成/晶胞；变胞不输出含混逐原子位移。pairs可指定最多8对1起原子编号。',
        {'reference':SELECTOR,'target':SELECTOR,'pbc':PBC,
         'pairs':{'type':'array','items':{'type':'array','items':INDEX,'minItems':2,'maxItems':2},'maxItems':8}},['reference','target']),
]


def real(value,low,high,label):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}须为{low}至{high}之间的有限数')
    return value


def indices(value,maximum):
    if not isinstance(value,list) or not 1 <= len(value) <= maximum or any(type(x) is not int or not 1 <= x <= geometry.MAX_ATOMS for x in value) or len(set(value)) != len(value):
        raise ValueError(f'请提供1至{maximum}个不重复的原子编号（从1开始）')
    return value


def elements(value):
    if not isinstance(value,list) or not 1 <= len(value) <= 12 or any(not isinstance(x,str) or not 1 <= len(x) <= 3 or not x.isalpha() for x in value):
        raise ValueError('元素筛选须为1至12个元素符号')
    return value


def dispatch(project,user,name,arguments):
    allowed = {
        'get_project_research_context':set(),
        'analyze_reaction_path':{'path_task_id','initial','final','source','bond_elements','fragment_indices','fragment_elements','contact_elements','contact_cutoff','pbc'},
        'check_structure':{'structure','reference','pbc'},
        'get_structure_summary':{'structure','pbc','axis','atom_offset','layer_gap_angstrom'},
        'get_structure_environment':{'structure','pbc','atom_indices','elements','neighbor_elements','cutoff_angstrom'},
        'compare_structures':{'reference','target','pbc','pairs'},
    }
    if name not in allowed or not isinstance(arguments,dict) or set(arguments)-allowed[name]:
        raise ValueError('结构工具不接受任意路径、命令、公式或未知参数')
    # Recheck the trusted conversation project and task membership on every call.
    current = next((p for p in load_db().get('projects',[]) if p.get('project_id') == project.get('project_id')),None)
    permissions.ensure_project_owner(current,user)
    if current is None:
        raise ValueError('当前项目不存在')
    if name == 'get_project_research_context':
        from reaction_review import research_context, paths
        return {**research_context(current), 'paths':[{'task_id':t['task_id'],'name':t.get('model_name'),'group':t.get('group')} for t in paths(current)]}
    if name == 'analyze_reaction_path':
        from reaction_review import analyze
        return analyze(current,user,arguments)
    pbc = arguments.get('pbc',[True,True,True])
    if not isinstance(pbc,list) or len(pbc)!=3 or any(type(x) is not bool for x in pbc):
        raise ValueError('周期边界须是a/b/c方向的三个布尔值')
    if name == 'check_structure':
        text, source = load_many(current,[arguments.get('structure')])[0]
        target = geometry.parse(text)
        reference_selection = selector(arguments['reference']) if 'reference' in arguments else None
        reference_source, reference, reference_error = None, None, None
        if reference_selection is None and source['file'] == 'CONTCAR':
            reference_selection = {k:v for k,v in source['selector'].items() if k != 'expected_sha256'}
            reference_selection['file'] = 'POSCAR'
            if source['kind'] == 'remote':
                reference_selection['directory'] = 'MAIN'
        if reference_selection is not None:
            # Validate before optional missing-file handling; never swallow explicit selectors.
            selector(reference_selection)
            try:
                before, reference_source = load_many(current,[reference_selection])[0]
                reference = geometry.parse(before)
            except ValueError as exc:
                if 'reference' in arguments:
                    raise
                reference_error = str(exc)
        evidence = load_check_evidence(current,source)
        same_task = bool(reference_source and reference_source['task_id']==source['task_id'] and reference_source['image']==source['image'])
        result = structure_check.check(target,reference,evidence,pbc,same_task)
        return {**result,'source':source,'reference_source':reference_source,'reference_unavailable':reference_error,
                'reference_scope':'显式reference' if 'reference' in arguments else '默认MAIN/POSCAR候选起点（本地仅镜像），需核对是否真正初始构型'}
    if name == 'compare_structures':
        pairs = arguments.get('pairs',[])
        if not isinstance(pairs,list) or len(pairs)>8:
            raise ValueError('最多比较8个原子对')
        for pair in pairs:
            indices(pair,2)
            if len(pair)!=2:
                raise ValueError('每个原子对必须有两个不同编号')
        sources = load_many(current,[arguments.get('reference'),arguments.get('target')])
        (before,source_a),(after,source_b) = sources
        result = geometry.compare(geometry.parse(before),geometry.parse(after),
            same_task=source_a['task_id']==source_b['task_id'] and source_a['image']==source_b['image'], pbc=pbc,pairs=pairs)
        return {**result,'reference_source':source_a,'target_source':source_b}
    if name == 'get_structure_summary':
        axis = arguments.get('axis','c')
        offset = arguments.get('atom_offset',0)
        gap = real(arguments.get('layer_gap_angstrom',.75),.1,3,'分层间隙阈值')
        if axis not in ('a','b','c') or type(offset) is not int or not 0 <= offset <= geometry.MAX_ATOMS:
            raise ValueError('分层方向或原子分页无效')
    else:
        cutoff = real(arguments.get('cutoff_angstrom',3),.1,6,'邻居截断半径')
        if 'atom_indices' in arguments:
            indices(arguments['atom_indices'],6)
        if 'elements' in arguments:
            elements(arguments['elements'])
        if 'neighbor_elements' in arguments:
            elements(arguments['neighbor_elements'])
        if 'elements' in arguments and 'atom_indices' in arguments:
            raise ValueError('中心原子请选择编号或元素之一')
    text,source = load_many(current,[arguments.get('structure')])[0]
    parsed = geometry.parse(text)
    if name == 'get_structure_summary':
        return {**geometry.summary(parsed,atom_offset=offset,axis=axis,layer_gap_angstrom=gap,pbc=pbc),'source':source}
    for field in ('elements','neighbor_elements'):
        if field in arguments and set(arguments[field])-set(parsed['atoms']):
            raise ValueError('元素筛选包含当前结构不存在的元素')
    candidates = arguments.get('atom_indices') or [i+1 for i,el in enumerate(parsed['atoms']) if 'elements' not in arguments or el in arguments['elements']]
    result = geometry.environment(parsed,candidates[:6],cutoff,pbc,arguments.get('neighbor_elements'))
    return {**result,'source':source,'selection':{'atom_indices':candidates[:6], 'matching_atom_count':len(candidates),
        'truncated':len(candidates)>6,'note':'中心原子按原文件顺序选取；超出6个时请按编号分批，不代表其余原子没有邻居。'}}
