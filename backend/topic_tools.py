"""Restricted R4 tools in the existing AI workspace loop; no execution tools."""
from __future__ import annotations
import json

from topic_content import ASSESSMENT_SCHEMA

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

INPUT={'type':'object','properties':{
    'task_id':{'type':'string'},'project_id':{'type':'string'},'observation_id':{'type':'string'},'query':{'type':'string'},'label':{'type':'string'},
    'energy_ev':{'type':'number'},'energy_value':{'type':'number'},'energy_unit':{'type':'string','enum':['eV','Ha','Hartree','Ry','kJ/mol']},
    'source_quote':{'type':'string','maxLength':2000},'note':{'type':'string','maxLength':2000}},'additionalProperties':False}
INTERPRETED_TARGET={'type':'object','properties':{'label':{'type':'string'},'reason':{'type':'string'},**{role:INPUT for role in ('surface','adsorbate','complex')}},'additionalProperties':False}
REPORT_TARGET={**TARGET,'properties':{**TARGET['properties'],**{role:INPUT for role in ('surface','adsorbate','complex')}}}

TOOLS=[
    tool('list_topic_reports','查找当前对话已有报告，返回编号、标题、保存时间和当前修订。用户说继续、修改或查看已有报告时先查询并读取原报告，不因同名重新创建。',
         {'query':{'type':'string','maxLength':200},'offset':{'type':'integer','minimum':0}}),
    tool('create_topic_report','用户要求科研报告时直接用本工具。开头用assessment.background/problem/impact各一句话写背景、问题和影响；确需选择才写decision一句话。explanation在后面解释为什么，不复述摘要。NEB/断键诊断先analyze_reaction_path核对目标与端点，再以neb.barrier及路径名生成问题—影响—解决办法和带标注结构对照；assessment按上述摘要与解释分开写，不把报错/缺口/警告写成notes。必要选择返回对话卡，非必要警告在对话总结。无需逐个计划元素。服务端自己查授权项目数据、使用注册配方与Python计算、选择现有报告元素并保存可读报告。吸附能有三个角色的能量就给初步结果；k点/未收敛等仅警告。仅多候选或无法确定角色时返回简短问题，界面自动给用户选择/自定义回答。你是用户与报告间的翻译官：可以理解口语/别名，先search_report_data查实际任务，再自行传targets绑定角色；不需要用户给task_id。用户在本轮或历史对话给过的能量可直接作为对应角色的energy_ev，或energy_value+energy_unit，并用source_quote引用用户原话；不需要存在分子任务。推断/假设须在note说明，不能伪装为计算事实。用户的标题和分析重点可直接传入，警告只在对话总结。不先写文章再找数字。',
         {'property_id':{'type':'string'},'model_queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},'adsorbate_query':{'type':'string','maxLength':100},'project_ids':{'type':'array','items':{'type':'string'},'maxItems':4},'targets':{'type':'array','items':REPORT_TARGET,'maxItems':4},'title':{'type':'string','maxLength':200},'notes':{'type':'string','maxLength':8000},'show_warnings':{'type':'boolean'},'objective':{'type':'string','maxLength':1000},'assessment':ASSESSMENT_SCHEMA,'bond_elements':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':2},'fragment_elements':{'type':'array','items':{'type':'string'},'maxItems':12},'contact_elements':{'type':'array','items':{'type':'string'},'maxItems':12}},('property_id','model_queries')),
    tool('search_report_data','按用户的别名/口语寻找可用任务和当前对话中的用户给定数据。可留空query先看任务目录，再由你理解并用task_id绑定报告角色；名称不必与用户输入完全相同。返回用户原话供取数，最新要求优先。只读授权项目，不执行计算作业。',
         {'query':{'type':'string','maxLength':200},'project_ids':{'type':'array','items':{'type':'string'},'maxItems':4},'offset':{'type':'integer','minimum':0}}),
    tool('update_topic_report','修改同一报告的标题、分析重点objective和assessment（各类简明报告共用）：background/problem/impact各一句话，decision有待决策项才写，explanation随后解释为什么；不要把长篇背景塞进objective。也可调整内容顺序；返回实际展示正文，保存后核对。notes只是内部备注，不进正文。不会改底层能量和计算结果。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'},'title':{'type':'string'},'objective':{'type':'string','maxLength':1000},'notes':{'type':'string'},'show_warnings':{'type':'boolean'},'assessment':ASSESSMENT_SCHEMA,'blocks':{'type':'array','items':{'type':'string'}},'deleted_block_ids':{'type':'array','items':{'type':'string'}}},('topic_id','expected_revision')),
    tool('list_topic_projects','查找当前用户可访问项目，只读名称/ID/任务数。专题跨项目查询须逐项目鉴权，最多4项目。默认直接使用会话项目，不要求用户手工查已有数据。',
         {'query':{'type':'string','maxLength':100},'offset':{'type':'integer','minimum':0}}),
    tool('prepare_topic_report','专题流程第一步：解析问题后给property_id和model_queries，服务端自动找任务、验证唯一结构关系/当前快照，复用R3计算，再冻结相关R2候选。DOS比较用dos.comparison（仅已有图及能量参考，不新增派生公式）。吸附能用adsorption.simple，model_queries为各表面体系如[LMR,LIC@LMR]，adsorbate_query为明确吸附物如H2；采用最小数据模式：可由AI匹配角色，也可直接使用用户给定参考能量；质量问题仅提示。不要把电子吸附能当自由能。多位点不能随机选，必要数值缺失应在对话中直接询问，不生成缺口报告。氧参考仅可复用已有人工参考报告；common_oxygen_reference仅表示待确认的共同参考条件。原始问题由运行记录提供，不能伪造。',
         {'property_id':{'type':'string'},'model_queries':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},
          'project_ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':4},'targets':{'type':'array','items':REPORT_TARGET,'maxItems':4},
          'common_oxygen_reference':{'type':'boolean'},'reference_report_id':{'type':'string'},'surface_side':{'type':'string','enum':['start','end']},'reaction_correspondence':{'type':'string'},
          'adsorbate_query':{'type':'string','maxLength':100},'adsorbate_reference_type':{'type':'string','enum':['periodic','isolated_molecule']},'reference_conditions':{'type':'string','maxLength':2000}},
         ('property_id','model_queries')),
    tool('plan_topic_report','数据检查之后构建报告计划。只选prepare返回的现有block_id，每项写原因、章节、顺序及必要/补充标志；不加入无关进度/集群/全部路径。结构镜像只能补充证据。默认章节可通过sections调整；缺数据允许空元素列表。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'},'title':{'type':'string'},
          'selections':{'type':'array','items':SELECTION,'maxItems':24},
          'sections':{'type':'array','items':{'type':'object','properties':{'section_id':{'type':'string'},'title':{'type':'string'}},'required':['section_id','title'],'additionalProperties':False},'maxItems':12}},
         ('topic_id','expected_revision','selections')),
    tool('write_topic_draft','仅在数据检查和元素计划完成后组织科研文字。每段区分解释/假设/局限；数字必须写[[Fxx]]让Python按可信事实展开，或[Fxx]引用，不自行写数值/公式/HTML组件。必要数据缺失在对话提问，报错和警告不要写入报告。草案和计算数据分开存储，保留用户编辑。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'},'paragraphs':{'type':'array','items':PARAGRAPH,'minItems':1,'maxItems':10}},
         ('topic_id','expected_revision','paragraphs')),
    tool('save_topic_report','保存已生成的独立topic报告。不会覆盖project_full或其他专题，返回可从对话打开的报告ID。用户已要求生成报告时，完成草案后直接保存，不重复要求确认。',
         {'topic_id':{'type':'string'},'expected_revision':{'type':'integer'}},('topic_id','expected_revision')),
    tool('get_topic_report','读取报告实际正文、有效结论与建议和科学结果。需要DOS等图表的冻结曲线/数据时传evidence_index中的block_id。分页继续读时指定返回的revision和next_offset。notes不进正文。',
         {'topic_id':{'type':'string'},'revision':{'type':'integer','minimum':1},'block_id':{'type':'string'},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1000,'maximum':12000}},('topic_id',)),
]


def _model_report(doc, **page):
    import topic_reports as topics
    from topic_content import readback
    return topics.summary(doc) | readback(doc, **page)


def dispatch(user,conversation,run_id,name,arguments):
    import ai_chat_store
    import topic_reports as topics
    from storage import load_db
    import permissions
    if not isinstance(arguments,dict):raise ValueError('工具参数必须为对象')
    spec=next(t['function']['parameters'] for t in TOOLS if t['function']['name']==name)
    if set(arguments)-set(spec['properties']) or set(spec['required'])-set(arguments):raise ValueError('专题工具参数不符合受限合同')
    if name=='list_topic_reports':
        query=arguments.get('query','');offset=arguments.get('offset',0)
        if not isinstance(query,str) or len(query)>200 or type(offset) is not int or offset<0:raise ValueError('报告查询范围无效')
        items=[r for r in topics.list_for(user,conversation['id']) if query.casefold() in r['title'].casefold()]
        return {'items':[{k:r[k] for k in ('topic_id','title','revision','stage','updated_at')} for r in items[offset:offset+20]],
                'total':len(items),'next_offset':offset+20 if len(items)>offset+20 else None}
    if name=='search_report_data':
        from properties import authorized_projects
        from task_paths import is_auxiliary_task
        projects=authorized_projects(load_db(),user,arguments.get('project_ids') or [conversation['project_id']])
        if len(projects)>4:raise ValueError('一次最多查询四个项目')
        query=arguments.get('query','');offset=arguments.get('offset',0)
        if not isinstance(query,str) or len(query)>200 or type(offset) is not int or not 0<=offset<=2000:raise ValueError('查询范围无效')
        matches=[{'project_id':p['project_id'],'project':p['name'],'task_id':t['task_id'],'name':t.get('model_name'),'type':t.get('task_type'),'energy_ev':t.get('last_energy'),'status':t.get('status')}
                 for p in projects for t in p.get('tasks',[]) if not is_auxiliary_task(t) and (not query or query.casefold() in (str(t.get('model_name',''))+' '+t['task_id']).casefold())]
        with ai_chat_store.database() as db:
            ai_chat_store.owned(db,'conversations',conversation['id'],str(user['user_id']))
            rows=db.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY seq DESC LIMIT 40",(conversation['id'],)).fetchall()
        history=[str(r['content'])[:1000] for r in reversed(rows) if any(word in str(r['content']).lower() for word in ('能量','气体','参考','energy','ev','hartree'))][-12:]
        return {'tasks':matches[offset:offset+60],'total':len(matches),'has_more':len(matches)>offset+60,'user_statements':history,'note':'由你根据用户意图绑定角色；用户提供的值可以直接用于初步计算，标明出处即可。'}
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
        snapshot=json.loads(run['snapshot'])
        continuation=snapshot.get('topic_continuation')
        if continuation:
            doc=topics.load(user,continuation['topic_id'])
            if doc['conversation_id']!=conversation['id']:raise permissions.PermissionDenied('专题不属于当前对话')
            if arguments['property_id']!=doc['request']['property_id']:
                raise ValueError('本轮是已确认报告的续写；如需其他性质的报告，请另发起请求')
            # Card continuation must never create a second topic or reload its scientific inputs.
            return _model_report(doc,limit=4000) | {'continuation_note':'用户回答已保存，已打开原报告，未新建。请使用此topic_id和revision调用update_topic_report继续分析，保留冻结证据和已确认答案。'}
        messages=snapshot['messages']
        if not messages or messages[-1]['role']!='user':raise ValueError('运行缺少原始用户问题')
        question=messages[-1]['content']
        if name=='create_topic_report' or arguments.get('property_id') in ('adsorption.simple','adsorption.estimate'):
            from topic_simple import create
            request={k:v for k,v in arguments.items() if k in ('property_id','model_queries','adsorbate_query','targets','title','notes','show_warnings','assessment','objective','bond_elements','fragment_elements','contact_elements')}
            with ai_chat_store.database() as db:
                seq=db.execute('SELECT seq FROM messages WHERE id=?',(run['message_id'],)).fetchone()['seq']
                rows=db.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user' AND seq<=? ORDER BY seq DESC LIMIT 60",(conversation['id'],seq)).fetchall()
            statements=[str(r['content'])[:2000] for r in reversed(rows)]
            return _model_report(create(user,conversation,question,request,run_id=run_id,project_ids=arguments.get('project_ids'),user_statements=statements),limit=4000)
        # The model may translate names and choose authorized roles; Python still validates the chosen scientific inputs.
        request={k:v for k,v in arguments.items() if k!='project_ids'}
        doc=topics.prepare(user,conversation,messages[-1]['content'],request,run_id=run_id,project_ids=arguments.get('project_ids'))
        return topics.summary(doc)
    doc=topics.load(user,arguments['topic_id'],**({'revision':arguments['revision']} if name=='get_topic_report' and 'revision' in arguments else {}))
    if doc['conversation_id']!=conversation['id']:raise permissions.PermissionDenied('专题不属于当前对话')
    if name=='get_topic_report':return _model_report(doc,offset=arguments.get('offset',0),limit=arguments.get('limit',8000),block_id=arguments.get('block_id'))
    if name=='update_topic_report':
        from topic_simple import update_content
        return _model_report(update_content(user,doc['topic_id'],{k:v for k,v in arguments.items() if k!='topic_id'}),limit=4000)
    if doc.get('simple'):return _model_report(doc,limit=4000)
    payload={k:v for k,v in arguments.items() if k!='topic_id'}
    if name=='plan_topic_report':doc=topics.plan(user,doc['topic_id'],payload)
    elif name=='write_topic_draft':doc=topics.write_draft(user,doc['topic_id'],payload)
    elif name=='save_topic_report':doc=topics.save(user,doc['topic_id'],payload['expected_revision'])
    else:raise ValueError('未知专题工具')
    return {k:doc[k] for k in ('topic_id','report_type','title','revision','stage','conversation_id','sections')} | {'selected_blocks':doc['selections'],'paragraph_count':len(doc['narratives']),'openable':True}
