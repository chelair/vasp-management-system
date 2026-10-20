"""One request -> usable report, with human questions only for actual ambiguity."""
import copy
import html
import json
import re
import uuid
from dataclasses import asdict

import properties
import topic_reports as topics
from adsorption_minimum import ROLES,LABELS
from dates import now_iso
from property_science import digest
from storage import load_db
from task_paths import is_auxiliary_task

TYPES={'ele':'单点/电子结构','opt':'结构优化','neb':'NEB'}


def _pool(projects,name,*,complex_names=()):
    name=name.strip().casefold();names=[name]+[n.casefold() for n in complex_names]
    return [(p,t) for p in projects for t in p.get('tasks',[]) if not is_auxiliary_task(t) and
            any(str(t.get('model_name','')).casefold()==q or (complex_names and any(str(t.get('model_name','')).casefold().startswith(q+sep) for sep in ('_','-',' ','/','.'))) or t['task_id']==q for q in names)] if name else []


def create(user,conversation,question,request,*,run_id='',project_ids=None,previous=None,answers=None):
    from ai_chat_service import ensure_conversation
    ensure_conversation(user,conversation)
    if not isinstance(question,str) or not question.strip() or len(question)>16000:raise ValueError('请用一句话说明研究问题')
    allowed={'property_id','model_queries','adsorbate_query'}
    if not isinstance(request,dict) or set(request)-allowed:raise ValueError('请只提供研究性质、体系名称和吸附物名称')
    queries=request.get('model_queries') or []
    if not isinstance(queries,list) or not 1<=len(queries)<=4 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in queries):raise ValueError('请说明要研究的体系名称（最多四个）')
    ads=request.get('adsorbate_query','')
    if not isinstance(ads,str) or len(ads)>100:raise ValueError('请说明吸附物名称')
    db=load_db();projects=properties.authorized_projects(db,user,project_ids or [conversation['project_id']])
    if len(projects)>4:raise ValueError('一次最多查看四个项目')
    if request.get('property_id') not in ('adsorption.simple','adsorption.estimate'):
        return create_generic(user,conversation,question,request,run_id=run_id,project_ids=[p['project_id'] for p in projects])
    if run_id and not previous:
        prior=next((m for m in topics.list_for(user,conversation['id']) if m.get('run_id')==run_id),None)
        if prior:return topics.load(user,prior['topic_id'])
    values=copy.deepcopy((previous or {}).get('simple',{}).get('answers',{}));values.update(answers or {})
    if not ads and values.get('adsorbate_name'):ads=str(values['adsorbate_name']).strip();request={**request,'adsorbate_query':ads}
    questions=[];targets=[]
    if not ads:questions.append({'id':'adsorbate_name','title':'你想研究哪种吸附物？','options':[],'hint':'输入名称，例如 PMS、H2 或 CO。'})
    for index,query in enumerate(queries):
        target={'label':query}
        for role in ROLES:
            key=f'{index}.{role}'
            pool=_pool(projects,ads if role=='adsorbate' else query if role=='surface' else f'{ads}@{query}',
                       complex_names=(f'{query}_{ads}',f'{query}-{ads}',f'{query}@{ads}') if role=='complex' and ads else ()) if ads or role=='surface' else []
            chosen=None;answer=values.get(key)
            if answer:
                # Free answers resolve to actual authorized task names; text is never an energy or an executable instruction.
                matching=[(p,t) for p in projects for t in p.get('tasks',[]) if not is_auxiliary_task(t) and str(answer).casefold() in (t['task_id'].casefold(),str(t.get('model_name','')).casefold())]
                if not matching:
                    matching=[(p,t) for p,t in pool if str(t.get('model_name','')) and str(t['model_name']).casefold() in str(answer).casefold()]
                if len(matching)>1:
                    longest=max(len(str(t.get('model_name',''))) for _,t in matching);matching=[(p,t) for p,t in matching if len(str(t.get('model_name','')))==longest]
                if len(matching)>1 and any(word in str(answer) for word in ('单点','电子结构')):matching=[pair for pair in matching if pair[1].get('task_type')=='ele']
                if len(matching)>1 and '优化' in str(answer):matching=[pair for pair in matching if pair[1].get('task_type')=='opt']
                if len(matching)==1:chosen=matching[0]
            elif len(pool)==1:chosen=pool[0]
            if chosen:
                p,t=chosen;target[role]={'project_id':p['project_id'],'task_id':t['task_id']}
            elif ads or role=='surface':
                options=[{'value':t['task_id'],'label':f"{t.get('model_name')} · {TYPES.get(t.get('task_type'),t.get('task_type','计算'))}",
                          'description':p['name']} for p,t in pool[:3]]
                questions.append({'id':key,'title':f'{query}：{LABELS[role]}使用哪项计算？','options':options,
                                  'hint':('有多个候选，请选择，或输入其他构型名称。' if pool else '暂时没找到对应构型；可输入已有任务名称。尚未计算时，请先补齐这项计算。'),
                                  'error':f'没能唯一找到“{answer}”，请改用完整构型名称。' if answer else ''})
        targets.append(target)
    science=properties.evaluate(db,user,{'property_id':'adsorption.estimate','project_ids':[p['project_id'] for p in projects],'targets':targets})
    doc=copy.deepcopy(previous) if previous else {'schema_version':'topic.1.0.0','report_type':'topic','topic_id':'topic_'+uuid.uuid4().hex,
        'owner':topics._owner(user),'conversation_id':conversation['id'],'run_id':run_id,'original_question':question,'created_at':now_iso(),
        'hidden_block_ids':[],'deleted_block_ids':[],'narratives':{}}
    blocks=[];library={'blocks':[],'evidence':{}};warnings=list(science['warnings'])
    hero=topics._text_block('吸附能与计算方式','','results','property_fact',block_id=next((b['block_id'] for b in (previous or {}).get('blocks',[]) if b['origin']=='property_fact'),None));blocks.append(hero)
    by_project={p['project_id']:p for p in projects}
    for item in science['inputs']:
        project=by_project[item['project_id']];task=properties.task_for(project,item['task_id']);bid=None
        try:
            composition=topics.r2.build_composition(project,{'title':item['model_name'],'blocks':[{'type':'task.structure','task_id':task['task_id']}]},merged={task['task_id']:item['row']})
            block=composition['blocks'][0];block.update(title=item['role_label']+' · '+item['model_name'],section='sources',origin='r2',input_role=item['role'])
            # Three structures are core; keep compact CIF and one printable view instead of six full-resolution images.
            for ref in block['source_refs']:
                evidence=composition['evidence'][ref['evidence_id']];evidence['payload']['images']=evidence['payload'].get('images',[])[:1]
                evidence['version']='sha256:'+digest(evidence['payload']);ref['version']=evidence['version'];library['evidence'][ref['evidence_id']]=evidence
            bid=block['block_id']
            # Shared reference may appear in several comparisons; one physical structure card is enough.
            if any(b['block_id']==bid for b in blocks):continue
            blocks.append(block);library['blocks'].append(copy.deepcopy(block))
            if block['data_status']!='available':warnings.append(item['model_name']+'：暂时没有可显示的结构。能量计算不受影响；同步POSCAR或CONTCAR后可以补上。')
        except (ValueError,OSError,LookupError,KeyError):
            block=topics._text_block(item['role_label']+' · '+item['model_name'],'结构文件暂未找到；同步POSCAR或CONTCAR即可补上。','sources','input_summary');block['input_role']=item['role'];blocks.append(block)
    # Preserve text edits and user ordering when answering a question; evidence changes remain revisioned.
    if previous and previous.get('simple'):
        new_blocks={b['block_id']:b for b in blocks};old_ids=[b['block_id'] for b in previous['blocks']]
        blocks=[new_blocks[bid] for bid in old_ids if bid in new_blocks]+[b for b in blocks if b['block_id'] not in old_ids]
        doc['hidden_block_ids']=[bid for bid in doc['hidden_block_ids'] if bid in new_blocks];doc['deleted_block_ids']=[bid for bid in doc['deleted_block_ids'] if bid in new_blocks]
    title=f'{ads or "吸附物"} 在 {"、".join(queries)} 上的吸附能'
    generated_title=title
    if previous and previous.get('simple') and previous['title']!=previous['simple'].get('generated_title',previous['title']):title=previous['title']
    doc.update(title=title,project_ids=[p['project_id'] for p in projects],projects=[{'project_id':p['project_id'],'name':p['name']} for p in projects],
               property_ids=['adsorption.estimate'],request=copy.deepcopy(request),request_fingerprint=digest(request),
               sections=[{'section_id':'results','title':'吸附能'},{'section_id':'sources','title':'构型与计算数据'}],blocks=blocks,selections=[],
               stage='waiting' if questions else 'saved',simple={'version':'simple.1','generated_title':generated_title,'answers':values,'questions':questions,'warnings':list(dict.fromkeys(warnings)),
                    'notes':(previous or {}).get('simple',{}).get('notes','')},
               data={'science':science,'projects':[{'project_id':p['project_id'],'name':p['name']} for p in projects],'targets':targets,
                     'library':library,'candidates':[],'choices':[],'reference_candidates':[],'facts':[],
                     'gaps':science['gaps'],'preparation_status':'NEEDS_SELECTION' if questions else science['status'],'assumptions':[],'task_observations':[]})
    doc['evidence_fingerprint']=digest(doc['data'])
    return topics._commit(user,doc,(previous or {}).get('revision'))


def create_generic(user,conversation,question,request,**kwargs):
    """Existing registered recipes/blocks; a useful report does not require LLM planning rounds."""
    doc=topics.prepare(user,conversation,question,request,**kwargs)
    core={'ele.pdos','ele.work_function','group.neb','task.structure','task.energy_force'}
    selections=[{'block_id':c['block_id'],'reason':'与本次研究问题有关的已有结果','section':'sources','order':i,'essential':False}
                for i,c in enumerate(doc['data']['candidates']) if c['type'] in core]
    doc=topics.plan(user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'科研报告','selections':selections})
    doc['simple']={'version':'simple.1','questions':[],'warnings':list(dict.fromkeys(g['detail'] for g in doc['data']['gaps'])),'notes':''}
    doc['stage']='saved'
    return topics._commit(user,doc,doc['revision'])


def answer(user,topic_id,payload):
    import ai_chat_store
    doc=topics.load(user,topic_id)
    if set(payload)-{'expected_revision','answers'} or payload.get('expected_revision')!=doc['revision']:raise topics.RevisionConflict(doc['revision'])
    values=payload.get('answers') or {};allowed={q['id'] for q in doc.get('simple',{}).get('questions',[])}
    if not isinstance(values,dict) or set(values)-allowed or any(not isinstance(v,str) or not v.strip() or len(v)>300 for v in values.values()):raise ValueError('请选择候选，或填写简短回答')
    with ai_chat_store.database() as db:conversation=ai_chat_store.owned(db,'conversations',doc['conversation_id'],topics._owner(user))
    return create(user,conversation,doc['original_question'],doc['request'],project_ids=doc['project_ids'],previous=doc,answers=values)


def update_content(user,topic_id,payload):
    doc=topics.load(user,topic_id)
    if not doc.get('simple'):raise ValueError('请先重新生成简明报告')
    if set(payload)-{'expected_revision','title','notes','blocks','deleted_block_ids'}:raise ValueError('只可编辑标题、文字和展示顺序')
    title=payload.get('title',doc['title']);notes=payload.get('notes',doc['simple'].get('notes',''))
    if not isinstance(title,str) or not 1<=len(title.strip())<=200 or not isinstance(notes,str) or len(notes)>8000:raise ValueError('标题或文字过长')
    order=payload.get('blocks',[b['block_id'] for b in doc['blocks']]);original={b['block_id']:b for b in doc['blocks']};deleted=payload.get('deleted_block_ids',doc['deleted_block_ids'])
    if not isinstance(order,list) or len(order)!=len(original) or set(order)!=set(original) or not isinstance(deleted,list) or not set(deleted)<=set(original):raise ValueError('报告内容已更新，请重新打开')
    doc.update(title=title,blocks=[original[b] for b in order],deleted_block_ids=deleted);doc['simple']['notes']=notes
    return topics._commit(user,doc,payload.get('expected_revision'))


def rebuild(user,topic_id):
    import ai_chat_store
    old=topics.load(user,topic_id)
    with ai_chat_store.database() as db:conversation=ai_chat_store.owned(db,'conversations',old['conversation_id'],topics._owner(user))
    request={k:v for k,v in old['request'].items() if k in ('property_id','model_queries','adsorbate_query')}
    return create(user,conversation,old['original_question'],request,project_ids=old['project_ids'])


def render_html(doc,*,auto_print=False,stale=False):
    esc=lambda x:html.escape(str(x),quote=True)
    science=doc['data']['science'];simple=doc['simple'];parts=[];inputs={i['role']:i for i in science.get('inputs',[])}
    hidden=set(doc.get('deleted_block_ids',[])+doc.get('hidden_block_ids',[]))
    for block in doc['blocks']:
        if block['block_id'] in hidden:continue
        if block['origin']=='property_fact' and science.get('property_id')=='adsorption.estimate':
            results=''
            for result in science['results']:
                values=result['inputs'];value=result['value']
                equation=f"({values['complex']['value']:.8f}) − ({values['surface']['value']:.8f}) − ({values['adsorbate']['value']:.8f})"
                results+=f"<div class='result'><small>{esc(result['label'])} · 初步吸附能</small><div class='value'>{value:+.6f}<span> eV</span></div><p>吸附能 = 完整构型能量 − 基底能量 − 吸附质能量</p><p class='equation'>{esc(equation)} = {value:+.8f} eV</p><small>负值表示按这一参考吸附后能量更低；正值表示更高。</small></div>"
            if not results:results="<div class='missing'><h2>还不能算出吸附能</h2><p>需要基底、吸附质、完整构型三份能量。已有内容仍保留在下面。</p></div>"
            parts.append(results)
        elif block.get('input_role'):
            item=inputs.get(block['input_role'],{});energy=item.get('energy_ev');metric='尚无能量' if energy is None else f'{energy:.8f} eV'
            refs=block.get('source_refs') or [];evidence=doc['data']['library']['evidence'].get(refs[0]['evidence_id'],{}) if refs else {}
            if block['origin']=='r2':
                payload=evidence.get('payload') or {}
                structure=topics.r2._widget(block,'structure-3d') if payload.get('poscar_cif') or payload.get('contcar_cif') else '<p>结构暂未同步。同步POSCAR或CONTCAR即可补上。</p>'
                structure+=topics.r2._images(payload)
            else:structure='<p>'+esc(block.get('text','结构暂未同步'))+'</p>'
            source=item.get('source') or {}
            parts.append(f"<section class='card' id='{esc(block['block_id'])}'><h2>{esc(block['title'])}</h2><div class='metrics'><strong>{esc(metric)}</strong><span>{esc(item.get('convergence','尚无收敛记录'))}</span></div>{structure}<details><summary>查看来源</summary><p>{esc(source.get('directory') or '任务中保存的结果')}<br>{esc(source.get('observed_at') or '')}</p></details></section>")
        elif block['origin']=='property_fact':
            # Legacy recipe facts remain available without internal status/version tables.
            recipe=science.get('recipe') or {};body='<p>'+esc(recipe.get('definition','这项性质暂未支持'))+'</p><p>'+esc(recipe.get('formula',''))+'</p>'
            for result in science.get('results',[]):body+='<div class="value">'+esc(result['value'])+' <span>'+esc(result['units'])+'</span></div><p>'+esc(result['label'])+'</p>'
            if not science.get('results'):body+='<p>目前还没有足够数据计算数值，已找到的内容和下一步建议见下方。</p>'
            parts.append('<section class="card"><h2>计算结果与方法</h2>'+body+'</section>')
        elif block['origin']=='r2':
            refs=block.get('source_refs') or [];evidence=doc['data']['library']['evidence'].get(refs[0]['evidence_id'],{}) if refs else {}
            parts.append('<section class="card"><h2>'+esc(block['title'])+'</h2>'+topics.r2._block_body(block,evidence)+'</section>')
    gaps=science.get('gaps',[])
    if gaps:parts.append('<section class="missing"><h2>还缺什么，接下来怎么做</h2>'+''.join('<p>'+esc(g['detail'])+'<br><span>'+esc(g.get('action','请确认对应计算，并同步已有结果。'))+'</span></p>' for g in gaps)+'</section>')
    warnings=simple.get('warnings',[])
    warnings=list(dict.fromkeys('部分旧记录缺少完整计算快照，结构与参数尚未全部核实。' if '旧记录缺少完整计算快照' in w else w for w in warnings))
    if warnings:parts.append('<section class="warnings"><h2>使用这个结果前，请留意</h2><ul>'+''.join('<li>'+esc(w)+'</li>' for w in warnings[:3])+'</ul>'+('<details><summary>更多说明</summary><ul>'+''.join('<li>'+esc(w)+'</li>' for w in warnings[3:])+'</ul></details>' if len(warnings)>3 else '')+'</section>')
    if simple.get('notes'):parts.append('<section class="card"><h2>补充说明</h2><p style="white-space:pre-wrap">'+esc(simple['notes'])+'</p></section>')
    composition=topics.composition(doc)
    composition['blocks']=[b for b in composition['blocks'] if b.get('renderer')!='structure' or any((composition['evidence'].get(r['evidence_id'],{}).get('payload') or {}).get(k) for r in b.get('source_refs',[]) for k in ('poscar_cif','contcar_cif'))]
    runtime=topics.r2._interactive(composition)
    script="<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),1800))</script>" if auto_print else ''
    css="""*{box-sizing:border-box}body{margin:0;background:#f7f8fa;color:#202838;font:15px/1.65 system-ui,'Microsoft Yahei',sans-serif}main{max-width:1040px;margin:auto;padding:32px 24px}h1{font-size:25px;margin:0 0 10px}h2{font-size:18px;margin:0 0 12px}.subtitle,small,details{color:#667085}.card,.result,.missing,.warnings{padding:24px;margin:20px 0;border-radius:16px;background:white;border:1px solid #e8ebef;break-inside:avoid}.result{background:#eef5ff;border-color:#c7dcff}.value{font-size:42px;font-weight:700;letter-spacing:-1px;color:#245cc5}.value span{font-size:20px}.equation{font-family:monospace;overflow-wrap:anywhere}.metrics{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:16px}.metrics strong{font-size:20px}.warnings{background:#fff8e8;border-color:#f3dfad}.missing{background:#fff1ee}.missing span{color:#667085}details{font-size:12px;margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%;max-height:400px}li{margin:8px 0}.rb-image{display:none}.report-widget{min-height:180px}@media print{body{background:white}main{padding:0}.rb-image{display:block}.report-widget{min-height:0}.report-static-taken-over{display:block!important}.card:has(figure) .report-widget{display:none!important}.card{page-break-inside:avoid}}"""
    status='初步结果 · 请结合下方提醒使用' if science.get('results') else '数据需求说明'
    stale_note='<p>上游结果已变化，这份报告保留生成时的数据；可重新生成更新。</p>' if stale else ''
    return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; worker-src blob:; base-uri 'none'\"><title>{esc(doc['title'])}</title><style>{css}</style></head><body><main><h1>{esc(doc['title'])}</h1><div class='subtitle'>{esc(status)} · {esc(doc['updated_at'])}</div>{stale_note}{''.join(parts)}</main>{runtime}{script}</body></html>"
