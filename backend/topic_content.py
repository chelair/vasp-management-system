"""Shared report text: edit once, render once, read back the saved presentation."""
import hashlib
from html.parser import HTMLParser
import html
import re
import json

ASSESSMENT_FIELDS = ('background', 'problem', 'impact', 'decision', 'explanation', 'conclusion', 'recommendation')
ASSESSMENT_SCHEMA = {'type': 'object', 'properties': {
    key: {'type': 'string', 'maxLength': 1800, 'description': description}
    for key, description in zip(ASSESSMENT_FIELDS, (
        '一句话说明研究背景，不铺陈项目清单。', '一句话指出最重要的问题或判断。',
        '一句话说明对结论、交付或下一步的影响。', '确需用户选择时用一句话说明；没有则省略。',
        '摘要之后解释为什么，只写支持重点的依据，避免复述摘要和逐项罗列。',
        '兼容旧报告的详细结论；新报告使用背景、问题、影响和解释。', '兼容旧报告的处理建议。'))},
    'additionalProperties': False}
BRIEF_CSS = '.report-brief{background:#edf5fa!important;border-left:4px solid #2c6c94!important}.report-brief h2{margin-bottom:14px}.report-brief p{display:grid;grid-template-columns:5.5em 1fr;gap:12px;margin:10px 0}.report-brief b{color:#285675}.report-brief span{white-space:pre-wrap}.report-why{margin:28px 0 12px}@media print{.report-brief{print-color-adjust:exact}}'


def validate_assessment(value):
    if not isinstance(value, dict) or set(value)-set(ASSESSMENT_FIELDS) or any(not isinstance(v,str) or len(v)>1800 for v in value.values()):
        raise ValueError('报告文字只接受背景、问题、影响、待决策项和解释；兼容旧结论与建议')
    if any(re.search(r'\d+(?:\.\d+)?\s*(?:eV|Å|埃|电子伏)|<[^>]+>',v) for v in value.values()):
        raise ValueError('数值由Python证据块提供；结论只写定性解释，不接受自填数值或HTML')
    return value


def assessment(doc):
    return {**doc['data'].get('assessment', {}), **doc.get('assessment_edits', {})}


def assessment_html(doc, defaults=None):
    value = assessment(doc)
    objective = doc['request'].get('objective', '')
    fallback = {'background': objective, 'problem': doc.get('original_question', ''),
                'impact': value.get('conclusion', ''), **(defaults or {})}
    labels = (('background', '背景'), ('problem', '问题'), ('impact', '影响'), ('decision', '待决策项'))
    # Old narrative stays intact below; only its first complete sentence is reused in the brief.
    brief = {key: value[key].strip() if key in value else re.split(r'(?<=[。！？])|\n', fallback.get(key, '').strip())[0]
             for key, _ in labels}
    rows = ''.join('<p><b>'+label+'</b><span>'+html.escape(brief[key])+'</span></p>' for key, label in labels if brief[key])
    opening = '<section class="card report-brief"><h2>报告重点</h2>'+rows+'</section>' if rows else ''
    details = [('判断依据', value['explanation'])] if 'explanation' in value else [
        ('研究目标', objective if objective != brief['background'] else ''),
        ('关键结论', value.get('conclusion', '')), ('建议先做什么', value.get('recommendation', ''))]
    body = ''.join('<section class="card"><h3>'+label+'</h3><p style="white-space:pre-wrap">'+html.escape(text)+
                   '</p></section>' for label, text in details if text)
    return opening+'<h2 class="report-why">为什么</h2>'+body


class _ReportText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        skip = tag in ('script', 'style', 'svg', 'canvas', 'head') or 'report-widget' in attrs.get('class', '').split()
        if tag not in ('br', 'img', 'input', 'meta', 'link', 'hr', 'wbr', 'source'):
            self.stack.append((tag, skip or any(row[1] for row in self.stack)))
        if not any(row[1] for row in self.stack) and tag in ('h1','h2','h3','h4','p','tr','li','section','br'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if not any(row[1] for row in self.stack) and tag in ('td','th'):
            self.parts.append(' | ')
        if not any(row[1] for row in self.stack) and tag in ('h1','h2','h3','h4','p','tr','li','section'):
            self.parts.append('\n')
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not any(row[1] for row in self.stack):
            self.parts.append(data)


def readback(doc, *, offset=0, limit=8000, block_id=None):
    """Text comes from the same HTML renderer used by preview and export, never from notes."""
    import topic_reports as topics
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1000 <= limit <= 12000:
        raise ValueError('正文分页范围无效')
    if block_id is not None:
        block=next((b for b in doc['blocks'] if b['block_id']==block_id),None)
        if block is None:raise ValueError('请使用报告返回的图表block_id')
        items=[]
        for ref in block.get('source_refs',[]):
            evidence=doc['data']['library']['evidence'][ref['evidence_id']]
            payload={k:v for k,v in evidence.get('payload',{}).items() if k not in ('images','charts','cif','poscar_cif','contcar_cif')}
            items.append({'evidence_id':ref['evidence_id'],'version':ref['version'],'source':evidence.get('source'),
                          'provenance':evidence.get('provenance'),'data':payload})
        raw=json.dumps(items,ensure_ascii=False)
        end=min(offset+limit,len(raw))
        return {'topic_id':doc['topic_id'],'revision':doc['revision'],'evidence':{'block_id':block_id,
            'title':block['title'],'json':raw[offset:end],'offset':offset,'total_chars':len(raw),
            'next_offset':end if end<len(raw) else None},'note':'图表的冻结科学数据；只省略图片/结构文件与脚本，曲线数值未重采样。'}
    parser = _ReportText()
    parser.feed(topics.render_html(doc))
    body = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
    end = min(offset+limit, len(body))
    science = doc['data']['science']
    return {'topic_id': doc['topic_id'], 'revision': doc['revision'],
        'content': {'text': body[offset:end], 'offset': offset, 'total_chars': len(body),
                    'next_offset': end if end < len(body) else None,
                    'sha256': hashlib.sha256(body.encode()).hexdigest()},
        'editable_content': {'objective': doc['request'].get('objective', ''), 'assessment': assessment(doc)},
        'evidence_index': [{'block_id':b['block_id'],'type':b['type'],'title':b['title']} for b in doc['blocks'] if b.get('source_refs')],
        'notes_visibility': 'notes仅保留在对话备注，不显示在报告正文；正文结论和建议使用assessment。',
        'science': {'property_id': science.get('property_id'), 'status': science.get('status'),
                    'definition': science.get('recipe'), 'results': science.get('results', []),
                    'facts': doc['data'].get('facts', []),
                    'requirements': doc['data'].get('requirements', [])},
        'note': '这是本修订实际预览/导出的文字（图形以冻结证据为准）。正文未读完时使用next_offset并指定同一revision。'}
