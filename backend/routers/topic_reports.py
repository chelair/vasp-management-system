"""R4 topic reports: private documents using current chat identity and R2 export."""
from functools import wraps
from fastapi import APIRouter,Body,Request,Query,Depends
from fastapi.responses import JSONResponse,Response
from urllib.parse import quote
import ai_chat_store
from ai_chat_service import ensure_conversation
from envelope import ok,fail
import permissions
import topic_reports as topics

def private_response(response:Response):response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/reports/topic',tags=['topic-reports'],dependencies=[Depends(private_response)])

def actor(request):
    user=getattr(request.state,'user',None)
    topics._owner(user)
    return user


def guard(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except topics.RevisionConflict as exc:return JSONResponse(status_code=409,content=fail(str(exc),{'code':'revision_conflict','current_revision':exc.current}))
        except LookupError as exc:return JSONResponse(status_code=404,content=fail(str(exc)))
        except (ValueError,TypeError) as exc:return JSONResponse(status_code=400,content=fail(str(exc)))
    return wrapped


@router.get('')
@guard
def list_topics(request:Request,conversation_id:str|None=None):
    return ok('查询成功',{'items':topics.list_for(actor(request),conversation_id)})


@router.post('/prepare')
@guard
def prepare(request:Request,payload:dict=Body()):
    user=actor(request)
    if set(payload)-{'conversation_id','question','request','project_ids'}:raise ValueError('准备请求字段无效')
    with ai_chat_store.database() as db:
        conversation=ai_chat_store.owned(db,'conversations',payload.get('conversation_id',''),str(user['user_id']))
    ensure_conversation(user,conversation)
    doc=topics.prepare(user,conversation,payload.get('question',''),payload.get('request',{}),project_ids=payload.get('project_ids'))
    return ok('已检查数据',doc)


@router.post('/quick')
@guard
def quick(request:Request,payload:dict=Body()):
    from topic_simple import create
    user=actor(request)
    if set(payload)-{'conversation_id','question','request','project_ids'}:raise ValueError('请求字段无效')
    with ai_chat_store.database() as db:conversation=ai_chat_store.owned(db,'conversations',payload.get('conversation_id',''),str(user['user_id']))
    return ok('报告已整理',create(user,conversation,payload.get('question',''),payload.get('request',{}),project_ids=payload.get('project_ids')))


@router.post('/{topic_id}/questions')
@guard
def questions(topic_id:str,request:Request,payload:dict=Body()):
    from topic_simple import answer
    user=actor(request)
    old=topics.load(user,topic_id)
    continuation=payload.get('continue_analysis',False)
    if type(continuation) is not bool:raise ValueError('继续分析开关无效')
    doc=answer(user,topic_id,{k:v for k,v in payload.items() if k!='continue_analysis'})
    if continuation:
        from ai_chat_service import start_run
        supplied=payload.get('answers') or {}
        lines=[]
        for q in old.get('simple',{}).get('questions',[]):
            if q['id'] in supplied:
                option=next((o['label'] for o in q['options'] if o['value']==supplied[q['id']]), supplied[q['id']])
                lines.append(q['title']+'：'+option)
        try:
            run,_=start_run(user,str(user['user_id']),doc['conversation_id'],
                '我对报告“'+doc['title']+'”的确认：\n'+'\n'.join(lines)+'\n请继续同一报告的分析。必要缺项在对话中问我，其他警告在对话总结，不要放进报告。',
                False,'topic-answer-'+topic_id+'-'+str(old['revision']))
            doc={**doc,'continuation':run}
        except ValueError as exc:
            doc={**doc,'continuation_error':'回答已保存，但AI暂未继续：'+str(exc)}
    return ok('已按回答更新报告',doc)


@router.put('/{topic_id}/content')
@guard
def content(topic_id:str,request:Request,payload:dict=Body()):
    from topic_simple import update_content
    return ok('已保存',update_content(actor(request),topic_id,payload))


@router.post('/{topic_id}/rebuild')
@guard
def rebuild(topic_id:str,request:Request):
    from topic_simple import rebuild as rebuild_report
    return ok('已重新生成简明报告',rebuild_report(actor(request),topic_id))


@router.get('/{topic_id}')
@guard
def detail(topic_id:str,request:Request,revision:int|None=Query(default=None)):
    user=actor(request);doc=topics.load(user,topic_id,revision=revision)
    return ok('查询成功',{**doc,'freshness':topics.freshness(user,doc)})


@router.put('/{topic_id}')
@guard
def edit(topic_id:str,request:Request,payload:dict=Body()):
    return ok('已保存编辑',topics.edit(actor(request),topic_id,payload))


@router.post('/{topic_id}/plan')
@guard
def plan(topic_id:str,request:Request,payload:dict=Body()):return ok('已保存计划',topics.plan(actor(request),topic_id,payload))


@router.post('/{topic_id}/draft')
@guard
def draft(topic_id:str,request:Request,payload:dict=Body()):return ok('已保存草案',topics.write_draft(actor(request),topic_id,payload))


@router.post('/{topic_id}/save')
@guard
def save(topic_id:str,request:Request,payload:dict=Body()):
    if set(payload)!={'expected_revision'}:raise ValueError('保存必须带当前revision')
    return ok('专题报告已保存',topics.save(actor(request),topic_id,payload['expected_revision']))


@router.post('/{topic_id}/resolve')
@guard
def resolve(topic_id:str,request:Request,payload:dict=Body()):return ok('已更新明确选择，旧版本保留',topics.resolve(actor(request),topic_id,payload))


@router.post('/{topic_id}/regenerate')
@guard
def regenerate(topic_id:str,request:Request,payload:dict=Body()):
    if set(payload)!={'block_id','expected_revision','connection_id'}:raise ValueError('重写段落参数无效')
    return ok('已重新生成段落',topics.regenerate(actor(request),topic_id,payload['block_id'],payload['expected_revision'],payload['connection_id']))


@router.get('/{topic_id}/export.html')
@guard
def export(topic_id:str,request:Request,print:bool=False):
    user=actor(request);doc=topics.load(user,topic_id)
    stale=topics.freshness(user,doc)['stale']
    body=topics.render_html(doc,auto_print=print,stale=stale)
    disposition='inline' if print else 'attachment'
    return Response(body,media_type='text/html',headers={'Content-Disposition':f"{disposition}; filename*=UTF-8''{quote(doc['title']+'.html')}",'Cache-Control':'no-store'})


@router.post('/{topic_id}/preview')
@guard
def preview(topic_id:str,request:Request,payload:dict=Body(default={})):
    user=actor(request);doc=topics.load(user,topic_id)
    if payload:raise ValueError('预览使用保存的冻结版本；请先保存本次展示编辑')
    return ok('预览成功',{'html':topics.render_html(doc,stale=topics.freshness(user,doc)['stale'])})
