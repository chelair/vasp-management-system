"""报告后台工作复用 AI 会话、runs、取消及启动恢复；不另建队列或状态库。"""
import json
import threading
import time
from datetime import datetime

import ai_chat_store as chat
import report_store as reports
from dates import now_iso
import permissions

_START_LOCK = threading.Lock()
_CONTROLS = {}
PROMPT = '''这是完整项目报告的持续工作对话。用户可在关窗后继续后台生成，并在这里补充要求。
完整报告用get_full_project_report读取，生成用generate_full_project_report，注解用generate_project_report_notes，批注用process_project_report_comment。
不要把完整报告请求改成独立专题；注解草稿需用户预览保存，不自动覆盖人工文本。工具失败或需要补充时在对话明确说明，询问必要资料，不把问题写进客户报告。
用户补充批注要求时用reply_project_report_comment保存本轮用户原话，再处理该批注。不要重做已成功的步骤。'''


def prompt(scope):
    return PROMPT + '\n报告范围：' + scope


def is_report_conversation(value):
    return value.startswith(PROMPT + '\n报告范围：')


def model_prompt(value):
    # Stored prompt identifies existing report conversations; keep it unchanged.
    if is_report_conversation(value):
        return value + '\n最新报告规则优先：生成完整报告仅整理已有数据，不生成AI注解。AI只处理用户已经保存的批注及回复，调用process_project_report_comment修改该批注范围。不得调用generate_project_report_notes或补写其他模块；没有批注时请用户先添加批注。'
    return value


def project_ids(user, scope):
    from ai_chat_service import project_for
    from storage import load_db
    if scope != 'all':
        return [project_for(user, scope)['project_id']]
    return [p['project_id'] for p in permissions.visible_projects(load_db(), user) if not p.get('closed')]


def conversation(user, scope, connection_id=None, *, create=False):
    project_ids(user, scope)
    owner = str(user['user_id'])
    with _START_LOCK:
        with chat.database() as db:
            row = db.execute('SELECT * FROM conversations WHERE owner=? AND prompt=? ORDER BY updated_at DESC LIMIT 1',
                             (owner, prompt(scope))).fetchone()
        if not row and create:
            row = chat.create_conversation(owner, '全部项目报告' if scope == 'all' else '完整报告对话', None,
                                           connection_id, None if scope == 'all' else scope)
            with chat.database() as db:
                db.execute('UPDATE conversations SET prompt=? WHERE id=?', (prompt(scope), row['id']))
                row = chat.owned(db, 'conversations', row['id'], owner)
    if row:
        from ai_chat_service import ensure_conversation
        ensure_conversation(user, dict(row))
    return dict(row) if row else None


def ensure_scope(user, conversation):
    """批量报告会话也逐项目重新鉴权，不能用通用会话绕过撤权。"""
    if conversation.get('prompt') != prompt('all'):
        return
    from ai_chat_service import project_for
    with chat.database() as db:
        snapshots = [json.loads(r[0]) for r in db.execute('SELECT snapshot FROM runs WHERE conversation_id=?', (conversation['id'],))]
    for pid in {pid for s in snapshots for pid in s.get('report_job', {}).get('project_ids', [])}:
        project_for(user, pid)


def state(user, scope):
    convo = conversation(user, scope)
    if not convo:
        return {'conversation': None, 'drafts': []}
    return {'conversation': chat.detail(str(user['user_id']), convo['id']),
            'drafts': [d for d in stored_drafts(convo['id']).values() if not d.get('discarded')]}


def stored_drafts(conversation_id):
    drafts = {}
    with chat.database() as db:
        rows = db.execute('SELECT id,snapshot FROM runs WHERE conversation_id=? ORDER BY rowid DESC', (conversation_id,)).fetchall()
    for row in rows:
        for item in json.loads(row['snapshot']).get('report_drafts', {}).values():
            identity = (item['report_id'], item['draft']['key'])
            if identity in drafts:
                continue
            drafts[identity] = {**item, 'run_id': row['id']}
    return drafts


def dismiss(user, scope, run_id, key):
    convo = conversation(user, scope)
    if not convo:
        raise ValueError('报告对话不存在')
    with chat.database() as db:
        db.execute('BEGIN IMMEDIATE')
        run = chat.owned(db, 'runs', run_id, str(user['user_id']))
        if run['conversation_id'] != convo['id']:
            raise permissions.PermissionDenied('草稿不属于当前报告对话')
        snapshot = json.loads(run['snapshot'])
        item = snapshot.get('report_drafts', {}).get(key)
        if not item:
            raise ValueError('草稿不存在')
        item['discarded'] = True
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot, ensure_ascii=False), run_id))


def start(user, scope, payload):
    from ai_chat_service import _generate, start_run
    pids = project_ids(user, scope)
    if not pids:
        raise ValueError('没有可生成报告的项目')
    owner = str(user['user_id'])
    cid = payload.get('connection_id')
    if cid:
        with chat.database() as db:
            chat.owned(db, 'connections', cid, owner)
    action = payload['action']
    if action in ('notes', 'comment', 'chat') and not cid:
        raise ValueError('请先选择自己的模型连接')
    convo = conversation(user, scope, cid, create=True)
    with chat.database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM runs WHERE owner=? AND request_id=?', (owner, payload['request_id'])).fetchone()
        if old:
            if old['conversation_id'] != convo['id']:
                raise ValueError('请求编号已用于其他对话')
            return chat.public_run(old)
        if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')", (convo['id'],)).fetchone():
            raise ValueError('后台正在处理，请等待完成或停止后补充')
        if db.execute("SELECT count(*) FROM runs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 3:
            raise ValueError('当前账号最多同时运行3项工作')
        if cid != convo['connection_id']:
            db.execute('UPDATE conversations SET connection_id=? WHERE id=?', (cid, convo['id']))
    if action == 'chat':
        if scope == 'all':
            raise ValueError('请选择具体项目，继续该项目的报告对话')
        return start_run(user, owner, convo['id'], payload['content'], False, payload['request_id'])[0]
    labels = {'generate': '后台生成完整报告', 'notes': '后台生成报告注解草稿', 'comment': '后台处理报告批注'}
    job = {k: v for k, v in payload.items() if k not in ('request_id', 'content')}
    job['project_ids'] = pids
    text = payload.get('content') or labels[action]
    run_id, message_id, now = chat.uid(), chat.uid(), now_iso()
    with chat.database() as db:
        db.execute('BEGIN IMMEDIATE')
        # admission 和插入在同一事务内；前端重试不重复付费或生成。
        old = db.execute('SELECT * FROM runs WHERE owner=? AND request_id=?', (owner, payload['request_id'])).fetchone()
        if old:
            return chat.public_run(old)
        if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')", (convo['id'],)).fetchone():
            raise ValueError('后台正在处理，请等待完成或停止后补充')
        if db.execute("SELECT count(*) FROM runs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 3:
            raise ValueError('当前账号最多同时运行3项工作')
        connection = chat.owned(db, 'connections', cid, owner) if cid else {'model': 'Python', 'name': '报告生成'}
        for mid, role, content, status in [(chat.uid(), 'user', text, 'completed'), (message_id, 'assistant', '', 'queued')]:
            db.execute('INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (?,?,?,?,?,?)',
                       (mid, convo['id'], role, content, status, now))
        db.execute('''INSERT INTO runs(id,owner,conversation_id,message_id,request_id,status,model,connection_name,prompt_version,snapshot,created_at)
                      VALUES (?,?,?,?,?,'queued',?,?,?,?,?)''',
                   (run_id, owner, convo['id'], message_id, payload['request_id'], connection['model'], connection['name'],
                    convo['prompt_version'], json.dumps({'report_job': job}, ensure_ascii=False), now))
        db.execute('UPDATE conversations SET updated_at=? WHERE id=?', (now, convo['id']))
        run = chat.public_run(chat.owned(db, 'runs', run_id, owner))
    threading.Thread(target=_generate, args=(run_id, {}, '', [], user), kwargs={'report_job': job}, daemon=True).start()
    return run


class WorkControl:
    def __init__(self, run_id, user):
        self.run_id, self.user = run_id, user
        self.started = time.monotonic()
        self.current = None
        with chat.database() as db:
            run = chat.owned(db, 'runs', run_id, str(user['user_id']))
        self.project_ids = json.loads(run['snapshot']).get('report_job', {}).get('project_ids', [])

    def check(self):
        from ai_chat_service import _cancelled
        if _cancelled(self.run_id):
            raise ValueError('后台工作已停止')
        if time.monotonic() - self.started > 600:
            raise ValueError('本轮后台工作已达10分钟，已完成部分保留，请继续处理剩余项')
    def authorize(self):
        from ai_chat_service import project_for
        for pid in self.project_ids:
            project_for(self.user, pid)

    def progress(self, done, total, label):
        self.check()
        self.authorize()
        with chat.database() as db:
            db.execute('BEGIN IMMEDIATE')
            run = chat.owned(db, 'runs', self.run_id, str(self.user['user_id']))
            snapshot = json.loads(run['snapshot'])
            snapshot['report_progress'] = {'done': done, 'total': total, 'label': label}
            db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot, ensure_ascii=False), self.run_id))

    def model(self):
        from ai_chat_service import TextGenerationControl
        parent = self
        class Control(TextGenerationControl):
            def check(self):
                super().check()
                parent.check()
        self.current = Control()
        return self.current


def stop(run_id):
    work = _CONTROLS.get(run_id)
    if work and work.current:
        work.current.cancel()


def report_for(user, pid, report_id=None):
    from ai_chat_service import project_for
    project = project_for(user, pid)
    rid = report_id or 'rpt_' + pid
    doc, _, _ = reports.load_report(rid)
    if doc['metadata']['project_id'] != project['project_id']:
        raise permissions.PermissionDenied('报告不属于当前项目')
    return doc


def save_draft(work, report_id, draft, title):
    work.check()
    work.authorize()
    with chat.database() as db:
        db.execute('BEGIN IMMEDIATE')
        run = chat.owned(db, 'runs', work.run_id, str(work.user['user_id']))
        snapshot = json.loads(run['snapshot'])
        snapshot.setdefault('report_drafts', {})[report_id + ':' + draft['key']] = {'report_id': report_id, 'title': title, 'draft': draft}
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps(snapshot, ensure_ascii=False), work.run_id))


def notes(work, pid, connection_id, keys=None, report_id=None):
    import report_ai_notes as ai
    doc = report_for(work.user, pid, report_id)
    report_id = doc['metadata']['report_id']
    status = ai.status(doc, work.user)
    if not status['enabled']:
        raise ValueError('项目未开启AI报告撰写；完整报告仍可生成')
    targets = status['targets']
    if keys is not None:
        if any(k not in {t['key'] for t in targets} for k in keys):
            raise ValueError('报告中没有该注解位置')
        targets = [t for t in targets if t['key'] in keys]
    count, skipped, failures = 0, 0, []
    with chat.database() as db:
        run = chat.owned(db, 'runs', work.run_id, str(work.user['user_id']))
    prior = stored_drafts(run['conversation_id'])
    for i, target in enumerate(targets):
        work.progress(i, len(targets), '撰写：' + target['title'])
        current = reports.read_notes(report_id).get(target['key']) or {}
        if keys is None and (current.get('analysis_note', '').strip() or current.get('paper_note', '').strip()):
            skipped += 1
            continue
        previous = prior.get((report_id, target['key']))
        if keys is None and previous and not previous.get('discarded'):
            draft = previous['draft']
            if (draft['input_fingerprint'] == ai.digest(ai.evidence(doc, ai.project_for(doc, work.user), target['key']))
                    and draft['base_revision'] == reports.note_revision(current or None)
                    and time.time() - datetime.fromisoformat(draft['generated_at']).timestamp() < 7200):
                skipped += 1
                continue
        try:
            draft = ai.preview(report_id, target['key'], work.user, connection_id, work.model())
            save_draft(work, report_id, draft, target['title'])
            count += 1
        except (ValueError, FileNotFoundError) as exc:
            work.check()
            failures.append({'title': target['title'], 'error': str(exc)})
            chat.update_answer(work.run_id, '需要处理的问题：\n\n' + '\n'.join(f"- {f['title']}：{f['error']}" for f in failures))
    work.progress(len(targets), len(targets), '注解草稿处理结束')
    return {'draft_count': count, 'skipped': skipped, 'failures': failures,
            'message': f'生成{count}份草稿，跳过{skipped}项已有注解或待审草稿。请在草稿中预览、编辑并保存。'}


def generate(work, pid):
    from ai_chat_service import project_for
    from report_builder import build_report
    project = project_for(work.user, pid)
    result = build_report(pid, progress=lambda done, total, label: work.progress(done, total, project['name']+'：'+label))
    work.check()
    project_for(work.user, pid)
    with reports._notes_lock:
        work.check()
        entry = reports.save_report(result['report'], result['markdown'], result['charts'])
    work.progress(1, 1, '完整报告已保存')
    return {'report_id': entry['report_id'], 'project_name': project['name'], 'message': '完整报告已生成'}


def comment(work, pid, connection_id, comment_id, report_id=None):
    import report_review
    doc = report_for(work.user, pid, report_id)
    rid = doc['metadata']['report_id']
    work.progress(0, 1, 'AI正在处理批注')
    result = report_review.process(rid, work.user, comment_id, report_review.view(doc)['revision'], connection_id, work.model())
    item = next(c for c in result['comments'] if c['id'] == comment_id)
    work.progress(1, 1, '需要你补充' if item['status'] == 'blocked' else '批注处理结束')
    return {'report_id': rid, 'comment_id': comment_id, 'status': item['status'],
            'message': item['replies'][-1]['text'] if item['replies'] else '这条批注已完成，无需重复处理。'}


def execute(run_id, user, job):
    from ai_chat_service import _cancelled
    work = WorkControl(run_id, user)
    _CONTROLS[run_id] = work
    answers = []
    try:
        work.check()
        chat.update_answer(run_id, '后台已开始，关闭窗口或离开页面后仍会继续。')
        for i, pid in enumerate(job['project_ids']):
            work.check()
            try:
                if job['action'] == 'generate':
                    value = generate(work, pid)
                    answers.append(value['project_name'] + '：完整报告已生成。')
                elif job['action'] == 'notes':
                    value = notes(work, pid, job['connection_id'], job.get('keys'), job.get('report_id'))
                    answers.append(value['message'])
                    answers.extend(f"- {f['title']}：{f['error']}" for f in value['failures'])
                else:
                    value = comment(work, pid, job['connection_id'], job['comment_id'], job.get('report_id'))
                    answers.append(value['message'])
            except (ValueError, FileNotFoundError) as exc:
                work.check()
                answers.append('需要处理的问题：' + str(exc))
            chat.update_answer(run_id, '\n\n'.join(answers))
        work.progress(len(job['project_ids']), len(job['project_ids']), '本轮处理结束，可在下方继续对话')
        chat.update_answer(run_id, '\n\n'.join(answers), status='completed')
    except Exception as exc:
        error = str(exc) if isinstance(exc, (ValueError, permissions.PermissionDenied, FileNotFoundError)) else '后台处理失败，请核对模型连接或稍后重试'
        chat.update_answer(run_id, '\n\n'.join(answers + [error]), status='cancelled' if _cancelled(run_id) else 'failed', error=error)
    finally:
        _CONTROLS.pop(run_id, None)
