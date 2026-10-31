"""现有 AI 工具轮中的完整报告操作；共享原报告与注解业务核心。"""
import ai_chat_store as chat
import report_background as work
import report_review
import report_store
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError


class ToolBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    report_id: str | None = Field(default=None, min_length=1, max_length=160)
    comment_id: str | None = Field(default=None, min_length=1, max_length=64)
    keys: list[StrictStr] | None = Field(default=None, min_length=1)
    offset: int = Field(default=0, ge=0)


def tool(name, description, properties, required=()):
    return {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}}}


RID = {'type': 'string', 'minLength': 1, 'maxLength': 160}
CID = {'type': 'string', 'minLength': 1, 'maxLength': 64}
TOOLS = [
    tool('get_full_project_report', '读取当前项目完整报告的正文、批注和注解位置；offset分页正文，不是独立专题。',
         {'report_id': RID, 'offset': {'type': 'integer', 'minimum': 0}}),
    tool('generate_full_project_report', '仅用已有数据、图表和结构生成完整报告，不调用AI撰写其他模块；已有批注保留，旧版展示修改停止套用。不生成独立专题。', {}),
    tool('generate_project_report_notes', '后台生成完整报告注解草稿，草稿保存于当前私有运行，用户预览保存后才进入报告；省略keys时仅生成缺失注解，跳过人工内容。问题在对话说明。',
         {'report_id': RID, 'keys': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}, 'minItems': 1}}),
    tool('process_project_report_comment', '用当前模型按批注和用户回复修改当前项目完整报告，返回实际回复、完成或需要补充状态。已完成项不重复调用。',
         {'report_id': RID, 'comment_id': CID}, ['comment_id']),
    tool('reply_project_report_comment', '将本轮用户原话完整保存为指定批注的回复；用于用户补充能量或回答AI问题后继续处理，不保存AI自己编造的补充。',
         {'report_id': RID, 'comment_id': CID}, ['comment_id']),
]


def dispatch(project, conversation, user, name, arguments, run_id):
    spec = next(t['function']['parameters'] for t in TOOLS if t['function']['name'] == name)
    try:
        if set(arguments) - set(spec['properties']) or not set(spec['required']) <= set(arguments):
            raise ValueError('完整报告工具参数不符合合同')
        arguments = ToolBody.model_validate(arguments).model_dump(exclude_unset=True)
    except ValidationError:
        raise ValueError('完整报告工具参数不符合合同') from None
    if not run_id:
        raise ValueError('报告操作必须属于当前AI运行')
    with chat.database() as db:
        run = chat.owned(db, 'runs', run_id, str(user['user_id']))
    if run['conversation_id'] != conversation['id']:
        raise ValueError('运行不属于当前对话')
    if name == 'generate_project_report_notes' and work.is_report_conversation(conversation.get('prompt') or ''):
        raise ValueError('完整报告的AI只处理你提交的批注，请在对应模块添加批注后处理。')
    control = work.WorkControl(run_id, user)
    work._CONTROLS[run_id] = control
    try:
        control.check()
        pid = project['project_id']
        if name == 'generate_full_project_report':
            return work.generate(control, pid)
        doc = work.report_for(user, pid, arguments.get('report_id'))
        rid = doc['metadata']['report_id']
        state = report_review.view(doc)
        if name == 'get_full_project_report':
            import report_ai_notes
            shown = report_review.effective(doc, report_store.read_edits(rid))
            from report_review_elements import export_markdown
            text = export_markdown(shown)
            offset = arguments.get('offset', 0)
            return {'report_id': rid, 'generated_at': doc['metadata']['generated_at'],
                    'content': text[offset:offset+12000], 'next_offset': offset+12000 if len(text) > offset+12000 else None,
                    'comments': state['comments'], 'modules': state['modules'],
                    'note_targets': report_ai_notes.status(doc, user)['targets']}
        if name == 'generate_project_report_notes':
            return work.notes(control, pid, conversation['connection_id'], arguments.get('keys'), rid)
        if name == 'reply_project_report_comment':
            with chat.database() as db:
                message = db.execute('''SELECT content FROM messages WHERE conversation_id=? AND role='user'
                    AND seq<(SELECT seq FROM messages WHERE id=?) ORDER BY seq DESC LIMIT 1''',
                    (conversation['id'], run['message_id'])).fetchone()
            report_review.update(rid, user, {'operation': 'reply', 'comment_id': arguments['comment_id'],
                                           'text': message['content'], 'revision': state['revision']})
            return {'report_id': rid, 'message': '本轮用户原话已保存到批注，可继续处理'}
        return work.comment(control, pid, conversation['connection_id'], arguments['comment_id'], rid)
    finally:
        work._CONTROLS.pop(run_id, None)
