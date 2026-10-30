"""Customer-facing path diagnosis using frozen geometry and existing R2 topics.

Questions and operational warnings belong to chat, never the report body.
"""
import copy
import html
import json
import math
import re
import uuid

import ai_chat_store
from dates import now_iso
from property_science import digest
import properties
import reaction_review as review
import topic_reports as topics
from storage import load_db
from topic_content import validate_assessment, assessment_html, BRIEF_CSS

VERSION = 'reaction.topic.1'
esc = lambda value: html.escape(str(value), quote=True)


def _questions(reviews, answers, statements):
    questions = []
    if answers.get('scope') not in ('isolate_bond','full_reaction'):
        explicit = next((s for s in reversed(statements) if re.search(r'(仅|单独|尽量|只).{0,30}(断键|B.?F)', s)), None)
        if explicit:
            answers['scope'] = 'isolate_bond'
        else:
            questions.append({'id':'scope','title':'这次希望比较哪一种断键过程？','options':[
                {'value':'isolate_bond','label':'尽量只比较目标断键','description':'两端尽量保持相同的吸附方式和非反应骨架'},
                {'value':'full_reaction','label':'比较完整的吸附态反应','description':'允许形变、迁移和脱配位与断键耦合'}]})
    for item in reviews:
        key = 'bond.' + item['path_task_id']
        if answers.get(key) not in {r['label'] for r in item['candidate_reaction_bonds']} and item['candidate_reaction_bonds']:
            questions.append({'id':key,'title':item['path_name']+'：要研究图中哪一条反应键？',
                'options':[{'value':r['label'],'label':r['label']+' · '+r['elements'][0]+str(r['atoms'][0])+'–'+r['elements'][1]+str(r['atoms'][1]),
                            'description':f"初态 {r['initial_angstrom']:.3f} Å → 末态 {r['final_angstrom']:.3f} Å"} for r in item['candidate_reaction_bonds']],
                'hint':'可查看已有结构标注后选择；也可描述你的反应意图，不必手工查任务编号。'})
    return questions


def _findings(item, answers):
    findings = []
    extra = [r for r in item['interface_contacts'] if r['state'] != 'both']
    if extra:
        findings.append({'title':'两端的 O–Li 近邻关系发生变化',
            'problem':'二聚体中部分 O 与片段外 Li 的近邻关系在初、末态之间改变。',
            'impact':'这条路径可能同时包含脱配位、重新吸附或局部重排，得到的能垒便不能只归因于目标断键。',
            'solution':('围绕目标键构造吸附拓扑和非反应骨架相近的两端，先检查是否存在可分段的稳定中间态；若只能靠约束保持构型，应将结果解释为受限断键路径。' if answers.get('scope')=='isolate_bond' else '保留真实反应中的吸附重排，按完整过程解释；检查是否存在稳定中间态，再判断能否分段研究。')})
    rms = item['framework_shape']['pair_distance_rms_change_angstrom']
    if rms is not None and rms > .15:
        findings.append({'title':'二聚体骨架形状发生了变化',
            'problem':'排除刚体平移和转动后，两端片段内部距离仍存在差异。',
            'impact':'路径可能混入骨架形变，改变反应起点和过渡态位置；不能把两端总能差直接当成形变能。',
            'solution':'优先统一非反应骨架和吸附方式，再检查目标键。如果要量化形变代价，应另比较同一片段、相同电荷、自旋、晶胞和理论设置下的固定几何单点能。'})
    selected = next((r for r in item['candidate_reaction_bonds'] if r['label'] == answers.get('bond.'+item['path_task_id'])), None)
    if selected and selected['initial_angstrom'] > 2.2:
        findings.insert(0, {'title':'所选反应键在初态已明显拉长',
            'problem':'当前初态并非该键处于常见短距离的起点。',
            'impact':'直接继续这组端点，可能无法描述你要研究的完整断键过程。',
            'solution':'回到真正的反应物构型确认该键，并在相同吸附方式下重新定义初、末态；不能仅靠延长运行时间解决。'})
    changed = item['constraints']['changed_atom_indices']
    if changed:
        findings.append({'title':'两端的固定方式不一致',
            'problem':'初、末态的固定约束有差异，涉及原子：'+ '、'.join(map(str,changed))+'。',
            'impact':'路径可能比较不同约束条件下的结构，而不是同一反应的连续变化。',
            'solution':'统一反应中心和基底的约束定义，再重新确认两端及映像；保留实现研究目标所需的自由度。'})
    differences = [p for p in item['parameters'] if p['status'] == 'different']
    if differences:
        findings.append({'title':'两端计算输入存在差异', 'problem':'已自动核对到差异的项目：'+'、'.join(p['name'] for p in differences)+'。',
            'impact':'不同输入可能影响路径能量的可比性。', 'solution':'按同一研究方案统一这些输入，并核实相应运行记录；先处理结构差异，再安排续算。'})
    return findings


def create(user, conversation, question, request, *, project_ids=None, run_id='', user_statements=None, previous=None, answers=None, refresh=False, rebuild_sources=None):
    for key, maximum in (('objective',6000),('title',200),('notes',8000)):
        if key in request and (not isinstance(request[key],str) or len(request[key])>maximum):
            raise ValueError('研究目标、标题和说明需要使用简短文字')
    assessment = validate_assessment(request.get('assessment') or {})
    projects = properties.authorized_projects(load_db(), user, project_ids or [conversation['project_id']])
    if len(projects) != 1:
        raise ValueError('路径诊断一次使用当前一个项目；跨项目比较请分别明确路径')
    project = projects[0]
    queries = request.get('model_queries') or []
    if not isinstance(queries, list) or not 1 <= len(queries) <= 4 or any(not isinstance(q,str) or not q.strip() or len(q)>100 for q in queries):
        raise ValueError('请提供最多四条路径的名称')
    if previous and not refresh:
        reviews = copy.deepcopy(previous['data']['reaction_reviews'])
    else:
        chosen = []
        targets = request.get('targets') or []
        if not isinstance(targets,list) or len(targets)>4 or any(not isinstance(t,dict) or not isinstance(t.get('path',{}),dict) for t in targets):
            raise ValueError('请按路径提供明确的任务选择')
        for i, query in enumerate(queries):
            bound = (targets[i].get('path') or {}).get('task_id') if i < len(targets) else None
            candidates = [t for t in review.paths(project) if (t['task_id'] == bound if bound else query.casefold() in (str(t.get('model_name',''))+' '+str((t.get('group') or {}).get('name',''))).casefold())]
            if len(candidates) != 1:
                raise ValueError('路径名称未能唯一对应，请先用项目研究上下文工具定位路径，再让用户确认真正的歧义')
            if candidates[0]['task_id'] not in {t['task_id'] for t in chosen}:
                chosen.append(candidates[0])
        reviews = []
        events = []
        if run_id:
            with ai_chat_store.database() as db:
                run = ai_chat_store.owned(db,'runs',run_id,topics._owner(user))
                if run['conversation_id'] != conversation['id']:
                    raise ValueError('运行与对话不一致')
                events = json.loads(run['tool_events'])
        for path in chosen:
            args = {'path_task_id':path['task_id']}
            for name,source in (rebuild_sources or {}).get(path['task_id'],{}).items():
                # Explicit rebuild uses the same source kind, with a fresh current remote directory.
                args[name] = {k:v for k,v in source['selector'].items() if k not in ('expected_sha256','directory')}
                if args[name].get('source')=='remote':args[name]['directory']='CURRENT'
            recent = next((e for e in reversed(events) if e['name']=='analyze_reaction_path' and e['status']=='completed' and e.get('arguments',{}).get('path_task_id')==path['task_id'] and e.get('result',{}).get('sources')), None)
            if recent:
                args.update(recent['arguments'])
                args.update({name:src['selector'] for name,src in recent['result']['sources'].items()})
            args.update({k:request[k] for k in ('bond_elements','fragment_elements','contact_elements') if k in request})
            try:
                reviews.append(review.analyze(project,user,args,illustrations=True))
            except review.MissingEndpointEvidence:
                from topic_simple import create_generic
                numeric_request={k:v for k,v in request.items() if k not in ('bond_elements','fragment_elements','contact_elements')}
                numeric_request['targets']=[{'label':p.get('model_name') or p['task_id'],'path':{'task_id':p['task_id']}} for p in chosen]
                return create_generic(user,conversation,question,numeric_request,run_id=run_id,project_ids=[project['project_id']],
                    conversation_notes=['部分路径缺少可用端点结构，先展示已有离散映像的初步能垒；无法据此判断断键机制、过渡态或是否适合续算。'])
    statements = list(user_statements or (previous or {}).get('simple',{}).get('user_statements',[]))[-40:]
    values = {**(previous or {}).get('simple',{}).get('answers',{}), **(answers or {})}
    questions = _questions(reviews, values, statements)
    blocks, evidence = [], {}
    for item in reviews:
        for name, payload in item['structures'].items():
            source = item['sources'][name]
            bid = 'blk_'+digest({'path':item['path_task_id'],'endpoint':name})[:20]
            eid = 'ev_'+digest(source)[:20]
            version = digest(payload)
            evidence[eid] = {'evidence_id':eid,'version':version,'availability':'available','payload':payload,'source':source,
                             'validation':{'status':'CONDITIONAL'},'provenance':[source]}
            blocks.append({'block_id':bid,'type':'task.structure','renderer':'structure','origin':'r2','title':item['path_name']+' · '+('初态' if name=='initial' else '末态'),
                           'section':'structures','source_refs':[{'evidence_id':eid,'version':version}],'options':{},'task_id':source['task_id'],'data_status':'available','review_path':item['path_task_id'],'endpoint':name})
    from report_neb import append_review_blocks
    append_review_blocks(project, reviews, blocks, evidence, previous if previous and not refresh else None)
    doc = copy.deepcopy(previous) if previous else {'schema_version':'topic.1.0.0','report_type':'topic','topic_id':'topic_'+uuid.uuid4().hex,
          'owner':topics._owner(user),'conversation_id':conversation['id'],'run_id':run_id,'original_question':question,'created_at':now_iso(),
          'hidden_block_ids':[],'deleted_block_ids':[],'narratives':{},'selections':[]}
    chat_notes = []
    for item in reviews:
        if any(s['kind']=='local' for s in item['sources'].values()):
            chat_notes.append(item['path_name']+'使用本地保存的结构；不冒充刚读取的远端状态。')
        if any(p['status']=='unknown' for p in item['parameters']):
            chat_notes.append(item['path_name']+'部分运行参数尚未核实；已能读取的INCAR/KPOINTS已自动核对，不要求用户手工查文件。')
        chat_notes.append(item['path_name']+'：'+item['deformation_energy']['reason'])
    doc.update(title=str(request.get('title') or '断键路径诊断：问题、影响与解决方案')[:200], project_ids=[project['project_id']],
        projects=[{'project_id':project['project_id'],'name':project['name']}],property_ids=['neb.barrier'],request=copy.deepcopy(request),
        request_fingerprint=digest(request),sections=[{'section_id':'structures','title':'端点对照'}],blocks=blocks,
        stage='waiting' if questions else 'saved',simple={'version':VERSION,'questions':questions,'answers':values,'notes':str(request.get('notes',''))[:8000],
            'warnings':chat_notes,'show_warnings':False,'user_statements':statements},
        data={'research_context':review.research_context(project),'reaction_reviews':reviews,'assessment':assessment,
              'science':{'property_id':'neb.barrier','results':[],'inputs':[],'gaps':[],'status':'DIAGNOSIS'},'library':{'evidence':evidence,'blocks':blocks},
              'facts':[],'gaps':[],'candidates':[],'targets':[],'choices':[],'reference_candidates':[],'task_observations':[],
              'preparation_status':'NEEDS_SELECTION' if questions else 'DIAGNOSIS'})
    doc['evidence_fingerprint'] = digest(doc['data'])
    return topics._commit(user,doc,(previous or {}).get('revision'))


def answer(user, doc, payload):
    if set(payload)-{'expected_revision','answers'}:
        raise ValueError('确认只接受修订号与回答')
    if payload.get('expected_revision') != doc['revision']:
        raise topics.RevisionConflict(doc['revision'])
    values = payload.get('answers') or {}
    allowed = {q['id'] for q in doc['simple']['questions']}
    if not isinstance(values,dict) or not values or set(values)-allowed or any(not isinstance(v,str) or not v.strip() or len(v)>300 for v in values.values()):
        raise ValueError('请选择研究目标或描述你的反应意图')
    with ai_chat_store.database() as db:
        conversation = ai_chat_store.owned(db,'conversations',doc['conversation_id'],topics._owner(user))
    # Answering only changes the interpretation of the frozen evidence, never reads new structures.
    return create(user,conversation,doc['original_question'],doc['request'],project_ids=doc['project_ids'],previous=doc,answers=values)


def _static_structure(payload):
    atoms = payload['atoms']
    focus=set(payload.get('focus_atom_indices') or [a['index'] for a in atoms])
    coords = [a['cartesian_angstrom'] for a in atoms if a['index'] in focus]
    xs, zs = [p[0] for p in coords], [p[2] for p in coords]
    scale = min(245/max(max(xs)-min(xs),1), 220/max(max(zs)-min(zs),1))
    project = lambda p: (20+(p[0]-min(xs))*scale, 280-(p[2]-min(zs))*scale)
    colors = {'Li':'#9770b6','O':'#e24c4b','F':'#60bd65','B':'#d489be','C':'#5f6772','Cl':'#65ab5c','In':'#a18075'}
    out = ["<svg viewBox='0 0 440 330' role='img' aria-label='带距离标注的结构侧视图'>"]
    for atom in sorted(atoms,key=lambda a:a['cartesian_angstrom'][1]):
        x,y = project(atom['cartesian_angstrom'])
        out.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4.6' fill='{colors.get(atom['element'],'#8694a4')}' stroke='white' stroke-width='.7'/>")
    for i,row in enumerate(payload['annotations']):
        p,q = [project(v) for v in row['points']]
        color = '#bd5036' if row['kind']=='contact' else '#2467a5'
        out.append(f"<path d='M{p[0]:.2f},{p[1]:.2f} L{q[0]:.2f},{q[1]:.2f}' stroke='{color}' stroke-width='1.8' stroke-dasharray='4 3'/>")
        mid=[(p[k]+q[k])/2 for k in (0,1)];label_y=30+i*25
        out.append(f"<path d='M{mid[0]:.2f},{mid[1]:.2f} L283,{label_y-4}' stroke='{color}' stroke-width='.6' opacity='.65'/><text x='288' y='{label_y}' font-size='10' fill='{color}'>{esc(row['label'])} · {row['distance_angstrom']:.2f} Å</text>")
    return ''.join(out)+'</svg>'


def render_html(doc, *, auto_print=False, stale=False):
    data, simple = doc['data'], doc['simple']
    deleted = set(doc.get('hidden_block_ids',[])+doc.get('deleted_block_ids',[]))
    parts = []
    for item in data['reaction_reviews']:
        findings = _findings(item,simple['answers'])
        body = ''.join('<article class="finding"><h3>'+esc(f['title'])+'</h3>'+''.join('<p><b>'+label+'</b>'+esc(f[key])+'</p>' for key,label in (('problem','问题'),('impact','影响'),('solution','解决办法')))+'</article>' for f in findings)
        if not findings:
            body = '<p>已整理两端结构对照。围绕选定的反应键确认端点，并核实路径是否包含目标以外的变化。</p>'
        views = []
        for block in doc['blocks']:
            if block['renderer'] != 'structure' or block.get('review_path')!=item['path_task_id'] or block['block_id'] in deleted:
                continue
            evidence = data['library']['evidence'][block['source_refs'][0]['evidence_id']]
            views.append('<figure><figcaption>'+esc(block['title'])+'</figcaption>'+topics.r2._widget(block,'structure-3d')+'<div class="static-structure">'+_static_structure(evidence['payload'])+'</div></figure>')
        rows = item['candidate_reaction_bonds']
        selected=simple['answers'].get('bond.'+item['path_task_id'])
        pairs = '<table><thead><tr><th>反应键标注</th><th>初态 / Å</th><th>末态 / Å</th></tr></thead><tbody>'+''.join(f"<tr{' style=\"font-weight:600;background:#e9f2f7\"' if r['label']==selected else ''}><td>{esc(r['label'])}{'（已选）' if r['label']==selected else ''} · {esc('–'.join(r['elements']))}（{r['atoms'][0]}–{r['atoms'][1]}）</td><td>{r['initial_angstrom']:.3f}</td><td>{r['final_angstrom']:.3f}</td></tr>" for r in rows)+'</tbody></table>'
        changed = [r for r in item['interface_contacts'] if r['state']!='both']
        if changed:
            pairs += '<h4>发生变化的 O–Li 近邻</h4><table><thead><tr><th>原子对</th><th>初态 / Å</th><th>末态 / Å</th></tr></thead><tbody>'+''.join(f"<tr><td>{esc(r['elements'][0])}{r['atoms'][0]}–{esc(r['elements'][1])}{r['atoms'][1]}</td><td>{r['initial_angstrom']:.3f}</td><td>{r['final_angstrom']:.3f}</td></tr>" for r in changed[:8])+'</tbody></table>'
        rms = item['framework_shape']['pair_distance_rms_change_angstrom']
        if rms is not None:
            excluded=rows[0]['elements'][1] if rows else '离去元素'
            pairs += f'<p class="caption">排除所有 {esc(excluded)} 的片段内部距离变化 RMS：<strong>{rms:.3f} Å</strong>（排除整体平移与转动）</p>'
        profile=item.get('energy_profile') or {};images=profile.get('images') or []
        from report_neb import review_html
        neb_html = review_html(doc, item['path_task_id'], deleted)
        if images:
            def number(v):return f'{v:.6f}' if type(v) in (int,float) and math.isfinite(v) else '—'
            table = '<h4>已有路径能量与受力</h4><table><thead><tr><th>映像</th><th>相对初态 / eV</th><th>最大力 / eV·Å⁻¹</th></tr></thead><tbody>'+''.join('<tr><td>'+esc(r['label'])+'</td><td>'+number(r.get('relative'))+'</td><td>'+number(r.get('max_force'))+'</td></tr>' for r in images)+'</tbody></table>'
            pairs += '<div class="report-neb-energy-table">'+table+'</div>' if neb_html else table
            energies=[r.get('energy') for r in images]
            if all(type(v) in (int,float) and math.isfinite(v) for v in energies):
                peak=max(range(len(images)),key=lambda i:energies[i])
                label='初态' if peak==0 else '末态' if peak==len(images)-1 else '内部映像 '+str(images[peak]['label'])
                pairs+='<p class="caption">当前采样最高点：'+esc(label)+'。'+('已采样到高于两端的内部点。' if profile.get('interior_peak_observed') else '尚未采样到高于两端的内部峰值。')+'</p>'
        pairs += neb_html
        sources = '<details class="sources"><summary>查看数据来源</summary>'+''.join('<p>'+esc(name)+' · '+esc(src.get('task_name'))+' · '+esc(src.get('remote_path') or src.get('local_path'))+'<br>SHA256 '+esc(src['sha256'])+'</p>' for name,src in item['sources'].items())+'</details>'
        parts.append('<section><h2>'+esc(item['path_name'])+'</h2>'+body+'<div class="views">'+''.join(views)+'</div>'+pairs+sources+'</section>')
    findings = [finding for item in data['reaction_reviews'] for finding in _findings(item,simple['answers'])]
    defaults = {'background':doc['request'].get('objective') or data['research_context']['calculation_goal'],
                'problem':findings[0]['problem'] if findings else '需要核对两端是否描述选定的目标反应。',
                'impact':findings[0]['impact'] if findings else '端点对应关系决定路径能垒能否用于目标结论。'}
    body = '<header><div class="eyebrow">结构与反应路径诊断</div><h1>'+esc(doc['title'])+'</h1></header>'+assessment_html(doc,defaults)+''.join(parts)
    body += '<details class="method"><summary>能垒的定义</summary><p>E<sub>a</sub> = max(E<sub>路径映像</sub>) − E<sub>IS</sub></p><p>先确认反应对应关系，再用一致条件下的完整路径识别目标过程的峰值。</p></details>'
    composition = {'blocks':[b for b in doc['blocks'] if b['block_id'] not in deleted], 'evidence':data['library']['evidence']}
    runtime = topics.r2._interactive(composition)
    css = """*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:#253347;font:15px/1.75 system-ui,'Microsoft Yahei',sans-serif}main{max-width:1080px;margin:auto;padding:36px 28px}h1{font-size:28px;line-height:1.4;margin:8px 0 24px}h2{font-size:21px;margin:0 0 22px}h3{font-size:17px;margin:0 0 10px}h4{margin-bottom:10px}.eyebrow,.caption,.sources,.method{font-size:12px;color:#68788c}.conclusion{padding:24px 28px;border-left:4px solid #2c6c94;border-radius:0 12px 12px 0;background:#e9f2f7;margin:24px 0}.conclusion span{display:block;font-size:12px;color:#526f84;margin-bottom:8px}.conclusion strong{font-size:22px;line-height:1.5}.goal{padding:8px 4px 18px}.goal p{margin:5px 0 10px}section{background:white;border:1px solid #e1e7ed;border-radius:16px;padding:28px;margin:22px 0}.finding{border-bottom:1px solid #edf0f4;padding:0 0 16px;margin-bottom:22px}.finding p{margin:7px 0}.finding b{display:inline-block;color:#526b82;margin-right:14px;min-width:4em}.views{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:24px 0}figure{margin:0;min-width:0}figcaption{font-weight:600;margin:0 0 10px}svg{width:100%;height:auto;background:#f8fafc;border-radius:10px}.static-structure{display:block}.report-widget:not(:empty)+.static-structure{display:none}.report-widget:empty{display:none}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e7edf2}th{color:#5f7187;background:#f7f9fb}details{margin-top:18px}details p{overflow-wrap:anywhere}.method{padding:8px 4px}summary{cursor:pointer}.report-widget{min-height:0}sub{font-size:.75em}@media(max-width:700px){main{padding:20px 14px}.views{grid-template-columns:1fr}section{padding:20px 16px}.conclusion{padding:20px}h1{font-size:23px}.conclusion strong{font-size:19px}}@media print{body{background:white}main{padding:0}.report-widget{display:none!important}.static-structure{display:block!important}.views{grid-template-columns:1fr 1fr}section{break-inside:avoid}.sources,.method{display:none}.conclusion{print-color-adjust:exact}}"""
    printer = '<script>window.addEventListener("load",()=>setTimeout(()=>window.print(),1500))</script>' if auto_print else ''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:; worker-src blob:; base-uri \'none\'"><title>'+esc(doc['title'])+'</title><style>'+css+BRIEF_CSS+'</style></head><body><main>'+body+'</main>'+runtime+printer+'</body></html>'
