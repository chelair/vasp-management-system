"""R4 independent topic documents backed by R2 blocks and frozen R3 science.

No full-project report generation, remote access, input writes or job execution.
Narratives are separate from immutable facts, with optimistic revisions and history.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import threading
import uuid

import ai_chat_store
from config import DATA_DIR
from dates import now_iso
import permissions
import properties
from property_science import digest
import report_compositions as r2
from report_blocks import new_text_block_id
from storage import load_db
import topic_discovery

TOPICS_DIR = DATA_DIR/'reports'/'topics'
_ID = re.compile(r'^topic_[0-9a-f]{32}$')
_LOCK = threading.RLock()
_REGEN_LOCK = threading.Lock()
_REGEN_BUSY = set()
MAX_REPORT_BYTES = 12*1024*1024
SECTIONS = [('question','研究问题'),('methods','方法及性质定义'),('sources','模型与计算数据来源'),('results','关键计算结果'),
            ('analysis','对比分析'),('discussion','讨论'),('gaps','数据缺口与局限性'),('conclusion','结论')]


class RevisionConflict(ValueError):
    def __init__(self,current):
        self.current=current
        super().__init__(f'专题报告已修改（当前版本{current}），请重新打开后编辑')


def _owner(user):
    if not user or not user.get('user_id') or user.get('role')=='agent':
        raise permissions.PermissionDenied('专题报告只供已登录用户使用')
    return str(user['user_id'])


def _directory(user):
    return TOPICS_DIR/hashlib.sha256(_owner(user).encode()).hexdigest()[:32]


def _path(user,topic_id):
    if not _ID.fullmatch(str(topic_id)):raise LookupError('专题报告不存在')
    return _directory(user)/(topic_id+'.json')


@contextmanager
def _locked(user):
    with _LOCK:
        folder=_directory(user);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (folder/'.topics.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)


def _atomic(path,doc):
    raw=json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False).encode()
    if len(raw)>MAX_REPORT_BYTES:raise ValueError('专题证据超过12MiB，请减少模型或元素')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.parent/('.'+uuid.uuid4().hex+'.tmp')
    try:
        with os.fdopen(os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def _authorize(user,doc):
    if doc.get('owner')!=_owner(user):raise permissions.PermissionDenied('无权访问此专题报告')
    properties.authorized_projects(load_db(),user,doc['project_ids'])


def load(user,topic_id,*,revision=None):
    path=_path(user,topic_id)
    if revision is not None:
        if type(revision) is not int or revision<1:raise ValueError('报告版本无效')
        current=load(user,topic_id)
        if revision==current['revision']:return current
        path=path.parent/'history'/topic_id/f'revision_{revision:06}.json'
    if not path.is_file():raise LookupError('专题报告不存在')
    doc=json.loads(path.read_text())
    _authorize(user,doc)
    return doc


def _commit(user,doc,expected=None):
    with _locked(user):
        path=_path(user,doc['topic_id'])
        if path.exists():
            current=load(user,doc['topic_id'])
            if type(expected) is not int or current['revision']!=expected:raise RevisionConflict(current['revision'])
            _atomic(path.parent/'history'/doc['topic_id']/f"revision_{current['revision']:06}.json",current)
            doc['revision']=current['revision']+1
        else:
            if expected is not None:raise LookupError('专题报告不存在')
            if len(list(path.parent.glob('topic_*.json')))>=200:raise ValueError('当前用户最多保存200份专题报告')
            doc['revision']=1
        _authorize(user,doc)
        doc['updated_at']=now_iso()
        _atomic(path,doc)
    return doc


def list_for(user,conversation_id=None):
    _owner(user)
    if conversation_id:
        with ai_chat_store.database() as db:
            conversation=ai_chat_store.owned(db,'conversations',conversation_id,_owner(user))
        from ai_chat_service import ensure_conversation
        ensure_conversation(user,conversation)
    result=[]
    for path in _directory(user).glob('topic_*.json'):
        try:
            doc=json.loads(path.read_text())
            if conversation_id and doc.get('conversation_id')!=conversation_id:continue
            _authorize(user,doc)
            result.append({k:doc.get(k) for k in ('topic_id','report_type','title','revision','stage','created_at','updated_at','conversation_id','original_question','project_ids')})
        except (LookupError,ValueError,OSError,permissions.PermissionDenied):continue
    return sorted(result,key=lambda d:d['updated_at'],reverse=True)[:100]


def _text_block(title,text,section,origin='ai_text',block_id=None):
    return {'block_id':block_id or new_text_block_id(),'type':'text.analysis','renderer':'text','type_label':'专题文字',
            'title':title,'text':text,'section':section,'origin':origin,'source_refs':[], 'options':{},
            'data_status':'available','validation_status':'NOT_TESTED','task_id':'','group_id':''}


def _facts_text(data):
    recipe=data['science'].get('recipe') or {}
    text='**性质定义**：'+str(recipe.get('definition') or '当前性质未支持')+'\n\n'
    text+=str(recipe.get('formula') or '未注册计算公式，不产生派生数值')+'\n\n'+str(recipe.get('scope') or '')+'\n\n'
    labels='、'.join(str(t.get('label','')) for t in data.get('targets',[]))
    required={
        'oxygen_vacancy.neutral_single':'每个目标体系的完整模型、中性单O缺陷模型及可验证删除位点；绝对形成能还需明确来源和条件的每O化学势；所有输入需收敛且理论设置可比。',
        'relative_energy':'相同组成的参考模型和目标模型能量、收敛证据及可比理论设置。',
        'adsorption.simple':'复合体系、表面、一个中性吸附物的能量与组成平衡、参考条件和收敛证据。',
        'neb.barrier':'已有完整NEB路径的映像能量、初末态、收敛和来源证据；路径差值另需明确反应对应关系。',
        'work_function.difference':'两个表面的已有功函数、真空方向/表面侧/可靠平台、收敛及理论设置。',
        'dos.comparison':'已有DOS/PDOS曲线、费米能级/能量零点和对应计算条件；未注册的派生指标不计算。',
    }.get(data['science'].get('property_id'),'需先有支持该性质的注册配方。')
    text+='**目标体系**：'+labels+'\n\n**所需输入**：'+required+'\n\n'
    for item in data['science'].get('inputs',[]):
        task=item.get('task') or {};source=item.get('source') or {}
        text+='- '+str(item.get('role'))+'：'+str(task.get('task_id') or '未绑定')+'；'+str(item.get('status'))+'；观测 '+str(source.get('observation_id') or '缺失')+'\n'
    if data['science'].get('not_calculable'):text+='\n**尚不能计算**：'+'；'.join(data['science']['not_calculable'])+'\n'
    suggestions=list(dict.fromkeys(s['advice'] for s in data['science'].get('supplemental_suggestions',[])))
    if suggestions:text+='\n**必要补充建议（仅建议，不自动执行）**：\n\n'+'\n'.join('- '+s for s in suggestions)+'\n\n'
    if data['facts']:
        text+='| 引用 | 已有数据或确定性计算结果 | 数值 | 单位 | 验证状态 |\n|---|---|---:|---|---|\n'
        for fact in data['facts']:
            label=str(fact['label']).replace('|',' / ').replace('\n',' ')
            text+=f"| {fact['fact_id']} | {label} | {fact['value']} | {fact['units']} | {fact['validation_status']} |\n"
    else:text+='当前没有满足条件的性质数值；不能填充缺失数据。\n'
    for assumption in data.get('assumptions',[]):text+='\n**待确认条件**：'+assumption+'\n'
    for result in data['science'].get('results',[]):
        text+='\n**结果条件**：'+'；'.join(result.get('conditions',[])+result.get('unverified_conditions',[]))+'\n'
    return text


def prepare(user,conversation,question,request,*,run_id='',project_ids=None):
    _owner(user)
    from ai_chat_service import ensure_conversation
    ensure_conversation(user,conversation)
    if not isinstance(question,str) or not question.strip() or len(question)>16000:raise ValueError('研究问题必须是1至16000字符')
    refs=project_ids or [conversation.get('project_id')]
    fingerprint=digest({'request':request,'projects':refs,'question':question})
    if run_id:
        for meta in list_for(user,conversation['id']):
            old=load(user,meta['topic_id'])
            if old.get('run_id')==run_id and old.get('request_fingerprint')==fingerprint:return old
    data=topic_discovery.prepare(user,refs,request)
    question_block=_text_block('研究问题',question,'question','question')
    fact_block=_text_block('性质定义与关键数据',_facts_text(data),'results','property_fact')
    doc={'schema_version':'topic.1.0.0','report_type':'topic','topic_id':'topic_'+uuid.uuid4().hex,
         'owner':_owner(user),'conversation_id':conversation['id'],'run_id':run_id,
         'original_question':question,'title':question[:120],'created_at':now_iso(),
         'project_ids':[p['project_id'] for p in data['projects']],'projects':data['projects'],
         'property_ids':[request['property_id']], 'request':copy.deepcopy(request),'request_fingerprint':fingerprint,
         'data':data, 'evidence_fingerprint':digest(data),'stage':'prepared',
         'sections':[{'section_id':key,'title':label} for key,label in SECTIONS],
         'selections':[], 'narratives':{}, 'blocks':[question_block,fact_block],
         'hidden_block_ids':[],'deleted_block_ids':[]}
    return _commit(user,doc)


def _sections(values):
    if not isinstance(values,list) or not 1<=len(values)<=12:raise ValueError('报告需要1至12个章节')
    result=[];seen=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'section_id','title'}:raise ValueError('章节只接受section_id和title')
        key=value['section_id'];title=value['title']
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',key) or key in seen:raise ValueError('章节ID无效或重复')
        if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError('章节标题无效')
        result.append({'section_id':key,'title':title});seen.add(key)
    return result


def plan(user,topic_id,payload):
    doc=load(user,topic_id)
    if not isinstance(payload,dict) or set(payload)-{'expected_revision','title','sections','selections'}:raise ValueError('报告计划字段无效')
    sections=_sections(payload.get('sections',doc['sections']));keys={s['section_id'] for s in sections}
    chosen=payload.get('selections',[])
    if not isinstance(chosen,list) or len(chosen)>24:raise ValueError('最多选择24个现有R2元素')
    catalog={c['block_id']:c for c in doc['data']['candidates']}
    library={b['block_id']:b for b in doc['data']['library']['blocks']}
    selected=[];seen=set()
    for item in chosen:
        if not isinstance(item,dict) or set(item)!={'block_id','reason','section','order','essential'}:raise ValueError('每个选择必须包含元素ID、原因、章节、顺序和必要标记')
        bid=item['block_id'];c=catalog.get(bid)
        if not c or bid not in library or bid in seen:raise ValueError('元素不存在、重复或与当前研究无关')
        if c['project_id'] not in doc['project_ids'] or c['availability']!='available':raise ValueError('元素不属于授权项目或数据不可用')
        if item['section'] not in keys or type(item['order']) is not int or not 0<=item['order']<40 or type(item['essential']) is not bool:raise ValueError('元素章节/顺序/必要标记无效')
        if not isinstance(item['reason'],str) or not item['reason'].strip() or len(item['reason'])>500:raise ValueError('请选择元素的具体原因')
        # Local mirror structures are useful supplemental illustrations, never
        # essential proof of a historical pristine/defect relationship.
        if c.get('science_status') not in ('AVAILABLE','VISUAL_ONLY') and c['type']=='task.energy_force' and item['essential']:raise ValueError('未通过R3校验的原始能量只能作补充证据，不能标记为正式必要数值')
        if c['type']=='task.structure' and item['essential']:raise ValueError('当前镜像结构只能作为补充；缺陷关系以R3冻结输入核对为准')
        seen.add(bid);selected.append(copy.deepcopy(item))
    selected.sort(key=lambda i:i['order'])
    old={b['block_id']:b for b in doc['blocks']}
    blocks=[b for b in doc['blocks'] if b['origin']!='r2']
    for selection in selected:
        b=copy.deepcopy(old.get(selection['block_id']) or library[selection['block_id']]);b['section']=selection['section'];blocks.append(b)
    # Keep immutable metadata visible even if the model uses a custom template.
    for required in ('question','results'):
        if required not in keys:sections.append({'section_id':required,'title':dict(SECTIONS)[required]})
    rank={s['section_id']:i for i,s in enumerate(sections)}
    order={s['block_id']:s['order'] for s in selected}
    blocks.sort(key=lambda b:(rank.get(b['section'],100),order.get(b['block_id'],-1)))
    title=payload.get('title',doc['title'])
    if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('专题标题无效')
    retained={b['block_id'] for b in blocks}
    for key in ('hidden_block_ids','deleted_block_ids'):doc[key]=[bid for bid in doc[key] if bid in retained]
    validate_text(title,doc)
    for section in sections:validate_text(section['title'],doc)
    doc.update(title=title,sections=sections,selections=selected,blocks=blocks,stage='planned')
    return _commit(user,doc,payload.get('expected_revision'))


def validate_text(text,doc):
    if not isinstance(text,str) or not text.strip() or len(text)>4000:raise ValueError('单段文字必须是1至4000字符')
    facts={f['fact_id']:f for f in doc['data']['facts']}
    cited=re.findall(r'\[\[?(F\d+)\]?\]',text)
    if any(key not in facts for key in cited):raise ValueError('文字引用了不存在的可信数值')
    if any(facts[key]['validation_status'] not in ('AVAILABLE','CONDITIONAL') for key in cited):raise ValueError('未通过校验的原始数值仅可在来源表追溯，不能作为科研段落的数值结论')
    remainder=re.sub(r'\[\[?F\d+\]?\]','',text)
    # Model names/chemical formulas and orbital labels are identifiers, not
    # numerical results. Quantities must use [[Fxx]], expanded only by Python.
    for target in doc['request']['model_queries']:remainder=remainder.replace(target,'')
    remainder=re.sub(r'\b[1-7][spdf]\b','',remainder)
    if re.search(r'(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?',remainder) or re.search(r'[零一二三四五六七八九十百千万点]+\s*(?:eV|电子伏|伏特|埃|Å)',remainder):
        raise ValueError('文字不能自行填写数值，请使用事实引用[[Fxx]]；最终数字由服务端展开')
    if re.search(r'(?:E_f|E_ads|delta_E|ΔE|E_a|μ_O)\s*=',remainder):raise ValueError('性质公式由注册配方提供，文字不得自定义替代公式')
    return text


def _expanded(text,doc):
    facts={f['fact_id']:f for f in doc['data']['facts']}
    def replace(match):
        fact=facts.get(match[1])
        if not fact:return '〔失效的事实引用〕'
        return f"{fact['label']}：{fact['value']} {fact['units']}〔{fact['validation_status']}〕 [{fact['fact_id']}]"
    return re.sub(r'\[\[(F\d+)\]\]',replace,text)


def write_draft(user,topic_id,payload,*,model='AI工作台'):
    doc=load(user,topic_id)
    if set(payload)-{'expected_revision','paragraphs'}:raise ValueError('草案不接受科学结果、HTML组件或其他字段')
    if doc['stage']=='prepared':raise ValueError('先构建并验证报告元素计划，再生成文字')
    paragraphs=payload.get('paragraphs')
    if not isinstance(paragraphs,list) or not 1<=len(paragraphs)<=10:raise ValueError('每份草案需要1至10段文字')
    section_ids={s['section_id'] for s in doc['sections']};seen=set()
    for paragraph in paragraphs:
        if not isinstance(paragraph,dict) or set(paragraph)!={'section','title','text','kind'}:raise ValueError('每段只接受章节、标题、文字和解释/假设类型')
        section=paragraph['section']
        if section not in section_ids or section in seen:raise ValueError('草案章节不在计划内或重复')
        if paragraph['kind'] not in ('analysis','discussion','hypothesis','limitations','conclusion'):raise ValueError('文字必须区分解释、假设或局限')
        text=validate_text(paragraph['text'],doc)
        title=paragraph['title']
        if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError('段落标题无效')
        validate_text(title,doc)
        existing=next((b for b in doc['blocks'] if b['origin']=='ai_text' and b['section']==section),None)
        block=existing or _text_block(title,'',section)
        note=doc['narratives'].get(block['block_id'],{})
        note.update(ai_text=text,kind=paragraph['kind'],model=model,generated_at=now_iso(),evidence_fingerprint=doc['evidence_fingerprint'])
        note.setdefault('user_text',None)
        doc['narratives'][block['block_id']]=note
        block['title']=title
        if not existing:doc['blocks'].append(block)
        seen.add(section)
    rank={s['section_id']:i for i,s in enumerate(doc['sections'])}
    doc['blocks'].sort(key=lambda b:rank.get(b['section'],100))
    if len(doc['blocks'])>40:raise ValueError('专题最多40个元素')
    doc['stage']='draft'
    return _commit(user,doc,payload.get('expected_revision'))


def save(user,topic_id,expected_revision):
    doc=load(user,topic_id)
    if doc['stage'] not in ('draft','saved'):raise ValueError('先完成报告草案，再保存专题报告')
    if doc['stage']=='saved' and expected_revision==doc['revision']:return doc
    doc['stage']='saved'
    return _commit(user,doc,expected_revision)


def edit(user,topic_id,payload):
    doc=load(user,topic_id)
    if not isinstance(payload,dict) or set(payload)-{'expected_revision','title','blocks','sections','hidden_block_ids','deleted_block_ids'}:raise ValueError('编辑不接受科学数据、证据或模型生成来源字段')
    original={b['block_id']:b for b in doc['blocks']}
    library={b['block_id']:b for b in doc['data']['library']['blocks']}
    blocks=payload.get('blocks',[{k:b[k] for k in ('block_id','title','section')} for b in doc['blocks']])
    if not isinstance(blocks,list) or not 1<=len(blocks)<=40:raise ValueError('报告需1至40个元素')
    sections=_sections(payload.get('sections',doc['sections']));section_ids={s['section_id'] for s in sections}
    result=[];seen=set();aliases={}
    for item in blocks:
        if not isinstance(item,dict) or set(item)-{'block_id','title','section','text'}:raise ValueError('元素编辑只接受ID、标题、章节与文字')
        bid=item.get('block_id')
        if not isinstance(bid,str) or bid in seen:raise ValueError('元素ID无效或重复')
        if bid in original or bid in library:b=copy.deepcopy(original.get(bid) or library[bid])
        elif re.fullmatch(r'draft_txt_[0-9a-f]{32}',bid):b=_text_block('补充文字','','discussion',block_id=new_text_block_id())
        else:raise ValueError('元素不在相关证据目录中')
        title=item.get('title',b['title']);section=item.get('section',b.get('section','sources'))
        if not isinstance(title,str) or not title.strip() or len(title)>200 or section not in section_ids:raise ValueError('标题或章节无效')
        b.update(title=title,section=section)
        if 'text' in item:
            if b['origin']!='ai_text':raise ValueError('文字编辑不能改变底层计算数据/原始问题')
            text=validate_text(item['text'],doc)
            note=doc['narratives'].setdefault(b['block_id'],{'ai_text':'','kind':'discussion','model':'','generated_at':None,'evidence_fingerprint':doc['evidence_fingerprint']})
            previous=note.get('user_text') if note.get('user_text') is not None else note.get('ai_text','')
            if text!=previous:
                note['user_text']=text;note['edited_at']=now_iso()
        seen.add(bid);aliases[bid]=b['block_id'];result.append(b)
    for key in ('hidden_block_ids','deleted_block_ids'):
        values=payload.get(key,doc[key])
        if not isinstance(values,list) or len(values)!=len(set(values)) or not set(values)<=seen:raise ValueError('隐藏/删除元素ID无效')
        doc[key]=[aliases.get(value,value) for value in values]
    title=payload.get('title',doc['title'])
    if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('标题无效')
    doc.update(title=title,blocks=result,sections=sections)
    if doc['stage'] in ('prepared','planned') and any(b['origin']=='ai_text' for b in result):doc['stage']='draft'
    return _commit(user,doc,payload.get('expected_revision'))


def resolve(user,topic_id,payload):
    doc=load(user,topic_id)
    if set(payload)-{'expected_revision','targets','reference_report_id','common_oxygen_reference','adsorbate_reference_type'}:raise ValueError('仅可选择已发现任务或明确参考报告')
    request=copy.deepcopy(doc['request'])
    if 'targets' in payload:request['targets']=payload['targets']
    for key in ('reference_report_id','common_oxygen_reference','adsorbate_reference_type'):
        if key in payload:request[key]=payload[key]
    data=topic_discovery.prepare(user,doc['project_ids'],request)
    doc.update(request=request,data=data,evidence_fingerprint=digest(data),stage='prepared',selections=[],narratives={},hidden_block_ids=[],deleted_block_ids=[])
    doc['blocks']=[_text_block('研究问题',doc['original_question'],'question','question'),_text_block('性质定义与关键数据',_facts_text(data),'results','property_fact')]
    return _commit(user,doc,payload.get('expected_revision'))


def freshness(user,doc):
    _authorize(user,doc)
    from ai_inspections import query_inspections
    from checks_store import collect_task_observations
    projects={p['project_id']:p for p in properties.authorized_projects(load_db(),user,doc['project_ids'])}
    changes=[]
    for item in doc['data']['science'].get('inputs',[]):
        source=item.get('source') or {};task=item.get('task') or {}
        if not source.get('observation_id') or not task:continue
        project=projects.get(source.get('project_id') or task.get('project_id'))
        if project is None:project=next((p for p in projects.values() if any(t['task_id']==task['task_id'] for t in p.get('tasks',[]))),None)
        try:
            history=query_inspections(project,task['task_id'],5) if project else None
        except (ValueError,LookupError,properties.permissions.PermissionDenied):history=None
        rows=history['observations'] if history else []
        if not rows or rows[0]['observation_id']!=source['observation_id']:
            changes.append({'task_id':task['task_id'],'reason':'计算观测已更新或淘汰；报告保留原始快照'})
        elif history['freshness']['source_mismatch'] or history['freshness']['stale_for_live_decision']:
            changes.append({'task_id':task['task_id'],'reason':'当前任务/输入已变化或巡检超过新鲜度期限；报告保留原始快照'})
    # R2 selected local analysis hashes also matter (DOS/WF have independent files).
    from report_blocks import resolve_evidence
    projects={p['project_id']:p for p in properties.authorized_projects(load_db(),user,doc['project_ids'])}
    candidates={c['block_id']:c for c in doc['data']['candidates']}
    for selection in doc['selections']:
        c=candidates[selection['block_id']]
        try:
            original=projects[c['project_id']]
            task_ids={b.get('task_id') for b in doc['data']['library']['blocks']}
            project={**original,'tasks':[t for t in original.get('tasks',[]) if t['task_id'] in task_ids]}
            raw={t['task_id']:rows[0]['data'] for t in project.get('tasks',[]) if (rows:=collect_task_observations(t['task_id'],5))}
            current=resolve_evidence(topic_discovery.r2_observation_project(project,raw),c['type'],task_id=c.get('task_id') or '',group_id=c.get('group_id') or '',merged=raw,submit_times={},force=True)
            block=next(b for b in doc['data']['library']['blocks'] if b['block_id']==c['block_id'])
            if any(r['version']!=current['version'] for r in block['source_refs']):changes.append({'block_id':c['block_id'],'reason':'上游元素证据已变化；未重写报告'})
        except (ValueError,LookupError,KeyError,OSError):changes.append({'block_id':c['block_id'],'reason':'上游证据当前不可确认'})
    return {'stale':bool(changes),'changes':changes,'evidence_snapshot_preserved':True}


def composition(doc):
    blocks=copy.deepcopy(doc['blocks'])
    for block in blocks:
        if block['origin']=='ai_text':
            note=doc['narratives'].get(block['block_id'],{})
            text=note.get('user_text') if note.get('user_text') is not None else note.get('ai_text','')
            block['text']=('**假设（未验证）**：\n\n' if note.get('kind')=='hypothesis' else '')+_expanded(text,doc)
    groups=[{'group_id':s['section_id'],'title':s['title'],'block_ids':[b['block_id'] for b in blocks if b['section']==s['section_id']]} for s in doc['sections']]
    return {'title':doc['title'],'project_name':' / '.join(p['name'] for p in doc['projects']),
            'composition_id':doc['topic_id'],'revision':doc['revision'],'created_at':doc['created_at'],'updated_at':doc['updated_at'],
            'blocks':blocks,'evidence':doc['data']['library']['evidence'],'groups':groups,
            'hidden_block_ids':doc['hidden_block_ids'],'deleted_block_ids':doc['deleted_block_ids']}


def render_html(doc,*,auto_print=False,stale=False):
    output=r2.render_html(composition(doc),auto_print=auto_print)
    esc=lambda value:html.escape(str(value),quote=True)
    notes=[]
    for gap in doc['data']['gaps']:notes.append(f"<li>{esc(gap.get('status'))}：{esc(gap.get('detail'))}</li>")
    for value in doc['data'].get('assumptions',[]):notes.append('<li>待确认假设：'+esc(value)+'</li>')
    for result in doc['data']['science'].get('results',[]):
        for value in result.get('conditions',[])+result.get('unverified_conditions',[]):notes.append('<li>'+esc(value)+'</li>')
    footer="<section class='rb-block'><h2>科学校验与局限</h2><p>性质数值来自确定性程序；AI解释和用户文字不改变原始科学数据。没有充分验证的条件不能用于正式结论。</p><ul>"+''.join(notes)+'</ul></section>'
    if stale:footer="<aside class='rb-note'>上游数据可能过期；本报告保留生成时冻结证据。</aside>"+footer
    return output.replace('</body>',footer+'</body>')


def summary(doc):
    data=doc['data']
    return {k:doc[k] for k in ('topic_id','report_type','title','revision','stage','conversation_id','original_question','project_ids','sections')} | {
        'preparation_status':data['preparation_status'],'property_definition':data['science'].get('recipe'),
        'currently_calculable':data['science'].get('currently_calculable',[]),'not_calculable':data['science'].get('not_calculable',[]),
        'supplemental_suggestions':data['science'].get('supplemental_suggestions',[])[:20],
        'request':doc['request'],
        'facts':data['facts'],'gaps':data['gaps'][:30],'gaps_truncated':len(data['gaps'])>30,
        'choices':[{**c, **{k:c[k][:12] for k in ('relations','adsorption_relations','tasks') if k in c},'truncated':any(len(c.get(k,[]))>12 for k in ('relations','adsorption_relations','tasks'))} for c in data['choices']],'reference_candidates':data['reference_candidates'],'candidates':data['candidates'],
        'assumptions':data['assumptions'],'selected_blocks':doc['selections'],
        'narratives':doc['narratives'],'note':'先数据后文字。用[[Fxx]]插入可信数值，[Fxx]引用来源；不能自行填写数字或计算公式。'}


def regenerate(user,topic_id,block_id,expected_revision,connection_id,control=None):
    doc=load(user,topic_id)
    if expected_revision!=doc['revision']:raise RevisionConflict(doc['revision'])
    block=next((b for b in doc['blocks'] if b['block_id']==block_id and b['origin']=='ai_text'),None)
    if not block:raise ValueError('只能重新生成AI文字段落，不能生成或覆盖科学结果')
    owner=_owner(user)
    with _REGEN_LOCK:
        if owner in _REGEN_BUSY or len(_REGEN_BUSY)>=2:raise ValueError('已有段落正在生成，请稍后重试')
        _REGEN_BUSY.add(owner)
    try:
        from ai_chat_service import readonly_json_completion
        prompt='你是科研报告编辑。仅返回JSON {"text":"..."}。仅基于冻结事实和缺口重写一个段落。数字只能用[[Fxx]]引用，禁止直接写数字、补公式或未提供结论；假设标为假设。不得调用工具或生成HTML组件。'
        result,model=readonly_json_completion(owner,connection_id,[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'question':doc['original_question'],'section':block['title'],'facts':doc['data']['facts'],'gaps':doc['data']['gaps'][:30],'previous':doc['narratives'][block_id]},ensure_ascii=False)}],control)
        if not isinstance(result,dict) or set(result)!={'text'}:raise ValueError('模型段落格式无效；原草案保持不变')
        text=validate_text(result['text'],doc)
        # Recheck revision and project rights after the model call; failure is atomic.
        current=load(user,topic_id)
        if current['revision']!=expected_revision:raise RevisionConflict(current['revision'])
        note=current['narratives'][block_id]
        note.update(ai_text=text,user_text=None,model=model,generated_at=now_iso(),evidence_fingerprint=doc['evidence_fingerprint'])
        return _commit(user,current,expected_revision)
    finally:
        with _REGEN_LOCK:_REGEN_BUSY.discard(owner)
