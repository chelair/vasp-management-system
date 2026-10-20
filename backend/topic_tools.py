"""Restricted R4 tools in the existing AI workspace loop; no execution tools."""
from __future__ import annotations
import json

from property_tools import SELECTOR as CURRENT_SELECTOR
SELECTOR={'type':'object','properties':{**CURRENT_SELECTOR['properties'],'project_id':{'type':'string'}},'additionalProperties':False}
TARGET={'type':'object','properties':{'label':{'type':'string'},'removed_oxygen_index':{'type':'integer','minimum':1},
    **{key:SELECTOR for key in ('pristine','defect','reference','model','complex','surface','adsorbate','path')}},'additionalProperties':False}
SELECTION={'type':'object','properties':{'block_id':{'type':'string'},'reason':{'type':'string'},'section':{'type':'string'},
    'order':{'type':'integer','minimum':0,'maximum':39},'essential':{'type':'boolean'}},'required':['block_id','reason','section','order','essential'],'additionalProperties':False}
PARAGRAPH={'type':'object','properties':{'section':{'type':'string'},'title':{'type':'string'},'text':{'type':'string'},
    'kind':{'type':'string','enum':['analysis','discussion','hypothesis','limitations','conclusion']}},'required':['section','title','text','kind'],'additionalProperties':False}

def tool(name,description,properties,required=()):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TOOLS=[
    tool('create_topic_report','用户用一句话要求科研报告时优先且直接调用本工具，无需先查询和逐个计划元素。服务端自己查授权项目数据、使用注册配方与Python计算、选择现有报告元素并保存可读报告。吸附能有三个角色的能量就给初步结果；k点/未收敛等仅警告。仅多候选或无法确定角色时返回简短问题，界面自动给用户选择/自定义回答。不要求task_id，不先写文章再找数字。',
         {'property_id':{'type':'string'},'model_queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},'adsorbate_query':{'type':'string','maxLength':100},'project_ids':{'type':'array','items':{'type':'string'},'maxItems':4}},('property_id','model_queries')),
    tool('list_topic_projects','查找当前用户可访问项目，只读名称/ID/任务数。专题跨项目查询须逐项目鉴权，最多4项目。默认直接使用会话项目，不要求用户手工查已有数据。',
         {'query':{'type':'string','maxLength':100},'offset':{'type':'integer','minimum':0}}),
    tool('prepare_topic_report','专题流程第一步：解析问题后给property_id和model_queries，服务端自动找任务、验证唯一结构关系/当前快照，复用R3计算，再冻结相关R2候选。DOS比较用dos.comparison（仅已有图及能量参考，不新增派生公式）。吸附能用adsorption.simple，model_queries为各表面体系如[LMR,LIC@LMR]，adsorbate_query为明确吸附物如H2；先验证同晶胞表面原子映射及一个吸附物组成。孤立/气相分子才使用isolated_molecule参考（Gamma采样），不得把它当自由能。多位点不能随机选，缺数值也继续生成缺口报告。氧参考仅可复用已有人工参考报告；common_oxygen_reference仅表示待确认的共同参考条件。原始问题由运行记录提供，不能伪造。',
         {'property_id':{'type':'string'},'model_queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},
          'project_ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},'targets':{'type':'array','items':TARGET,'maxItems':4},
          'common_oxygen_reference':{'type':'boolean'},'reference_report_id':{'type':'string'},'surface_side':{'type':'string','enum':['start','end']},'reaction_correspondence':{'type':'string'},
          'adsorbate_query':{'type':'string','maxLength':100},'adsorbate_reference_type':{'type':'string','enum':['periodic','isolated_molecule']},'reference_conditions':{'type':'string','maxLength':2000}},
         ('property_id','model_queries')),
    tool('plan_topic_report','数据检查之后构建报告计划。只选prepare返回的现有block_id，每项写原因、章节、顺序及必要/补充标志；不加入无关进度/集群/全部路径。结构镜像只能补充证据。默认章节可通过sections调整；缺数据允许空元素列表。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'},'title':{'type':'string'},
          'selections':{'type':'array','items':SELECTION,'maxItems':24},
          'sections':{'type':'array','items':{'type':'object','properties':{'section_id':{'type':'string'},'title':{'type':'string'}},'required':['section_id','title'],'additionalProperties':False},'maxItems':12}},
         ('topic_id','expected_revision','selections')),
    tool('write_topic_draft','仅在数据检查和元素计划完成后组织科研文字。每段区分解释/假设/局限；数字必须写[[Fxx]]让Python按可信事实展开，或[Fxx]引用，不自行写数值/公式/HTML组件。无数据就写精确缺口。草案和计算数据分开存储，保留用户编辑。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'},'paragraphs':{'type':'array','items':PARAGRAPH,'minItems':1,'maxItems':10}},
         ('topic_id','expected_revision','paragraphs')),
    tool('save_topic_report','保存已生成的独立topic报告。不会覆盖project_full或其他专题，返回可从对话打开的报告ID。用户已要求生成报告时，完成草案后直接保存，不重复要求确认。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'}},('topic_id','expected_revision')),
    tool('get_topic_report','重新打开当前对话已有专题的冻结数据、文字和计划，供后续修改；上游变化不覆盖旧快照。',{'topic_id':{'type':'string'}},('topic_id',)),
]


def dispatch(user,conversation,run_id,name,arguments):
    import ai_chat_store
    import topic_reports as topics
    from storage import load_db
    import permissions
    if not isinstance(arguments,dict):raise ValueError('工具参数必须为对象')
    spec=next(t['function']['parameters'] for t in TOOLS if t['function']['name']==name)
    if set(arguments)-set(spec['properties']) or set(spec['required'])-set(arguments):raise ValueError('专题工具参数不符合受限合同')
    if name=='list_topic_projects':
        query=arguments.get('query','');offset=arguments.get('offset',0)
        if not isinstance(query,str) or len(query)>100 or type(offset) is not int or not 0<=offset<=1000:raise ValueError('项目查询/分页无效')
        projects=[p for p in permissions.visible_projects(load_db(),user) if query.casefold() in p['name'].casefold()]
        return {'items':[{'project_id':p['project_id'],'name':p['name'],'task_count':len(p.get('tasks',[]))} for p in projects[offset:offset+20]],'total':len(projects),'has_more':len(projects)>offset+20}
    if name in ('prepare_topic_report','create_topic_report'):
        if not run_id:raise ValueError('专题工具必须绑定当前聊天运行')
        with ai_chat_store.database() as db:
            run=ai_chat_store.owned(db,'runs',run_id,str(user['user_id']))
        if run['conversation_id']!=conversation['id']:raise permissions.PermissionDenied('运行不属于当前对话')
        messages=json.loads(run['snapshot'])['messages']
        if not messages or messages[-1]['role']!='user':raise ValueError('运行缺少原始用户问题')
        question=messages[-1]['content']
        if name=='create_topic_report' or (arguments.get('property_id') in ('adsorption.simple','adsorption.estimate') and not arguments.get('targets')):
            from topic_simple import create
            request={k:v for k,v in arguments.items() if k in ('property_id','model_queries','adsorbate_query')}
            return topics.summary(create(user,conversation,question,request,run_id=run_id,project_ids=arguments.get('project_ids')))
        # Candidate IDs are observations, not authorization to choose a site or
        # reservoir. Exact bindings from the model need an explicit user ID.
        for target in arguments.get('targets',[]):
            if not isinstance(target,dict):raise ValueError('目标绑定必须是对象')
            for selector in target.values():
                if isinstance(selector,dict) and selector.get('task_id') and selector['task_id'] not in question and selector['task_id']!=conversation.get('task_id'):
                    raise ValueError('任务或位点须由用户明确选择；请先不带targets自动发现并返回候选，不得替用户随机绑定')
        if arguments.get('reference_report_id') and arguments['reference_report_id'] not in question:
            raise ValueError('多个氧参考须由用户明确选择；模型不能自行确认参考报告')
        if arguments.get('adsorbate_reference_type')=='isolated_molecule' and not any(word in question.casefold() for word in ('孤立','气相','分子','isolated','gas','molecular','molecule')):
            raise ValueError('孤立分子参考类型需用户明确说明或在报告中选择，不能由模型假定')
        request={k:v for k,v in arguments.items() if k!='project_ids'}
        doc=topics.prepare(user,conversation,messages[-1]['content'],request,run_id=run_id,project_ids=arguments.get('project_ids'))
        return topics.summary(doc)
    doc=topics.load(user,arguments['topic_id'])
    if doc['conversation_id']!=conversation['id']:raise permissions.PermissionDenied('专题不属于当前对话')
    if doc.get('simple'):return topics.summary(doc)
    payload={k:v for k,v in arguments.items() if k!='topic_id'}
    if name=='get_topic_report':return topics.summary(doc)
    if name=='plan_topic_report':doc=topics.plan(user,doc['topic_id'],payload)
    elif name=='write_topic_draft':doc=topics.write_draft(user,doc['topic_id'],payload)
    elif name=='save_topic_report':doc=topics.save(user,doc['topic_id'],payload['expected_revision'])
    else:raise ValueError('未知专题工具')
    return {k:doc[k] for k in ('topic_id','report_type','title','revision','stage','conversation_id','sections')} | {'selected_blocks':doc['selections'],'paragraph_count':len(doc['narratives']),'openable':True}
