"""报告页后台流程浏览器夹具：真实本机API/Mock模型、构建器与SSH。"""
import copy
import io
import json
import time
from unittest.mock import patch

from test_report_background import ReportBackgroundTests
import test_report_ai_notes as fixture
import report_review
import report_store

ReportBackgroundTests.setUpClass()
case = ReportBackgroundTests('test_comment_model_question_and_reply_use_same_report_and_source')
case.setUp()
target = next(m for m in report_review.view(case.case.doc)['modules'] if m['title'] == 'Model')


def result(value):
    text = value['comment']['text']
    if '等待取消' in text:
        time.sleep(2)
    elif '后台验证' in text:
        time.sleep(1.5)
    if '补充参考' in text:
        return {'reply': '请在对话中补充氧气参考能量。', 'status': 'blocked', 'actions': []}
    return {'reply': '后台已完成。<script>window.REVIEW_XSS=1</script>', 'status': 'done',
            'actions': [{'kind': 'text', 'target': target['key'], 'text': '后台完成的报告解释。'}]}


fixture.REVIEW_RESULT = result
original = fixture.Provider.do_POST


def respond(handler):
    data = handler.rfile.read(int(handler.headers['Content-Length']))
    body = json.loads(data)
    handler.rfile = io.BytesIO(data)
    if 'tools' not in body:
        return original(handler)
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.end_headers()
    content = '收到你的补充，可以继续处理原报告。'
    handler.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': content}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode())


def build(pid, *, progress):
    progress(0, 2, '整理已有项目数据')
    time.sleep(.8)
    progress(1, 2, '准备保存完整报告')
    return {'report': copy.deepcopy(case.case.doc), 'markdown': 'background browser', 'charts': {'g_step.svg': '<svg/>'}}


with patch.object(fixture.Provider, 'do_POST', respond), patch('report_builder.build_report', side_effect=build):
    print(json.dumps({'base': case.client.base, 'connection': case.case.connection['id']}), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        case.tearDown();case.doCleanups();ReportBackgroundTests.tearDownClass()
