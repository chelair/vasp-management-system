"""Shared report text: edit once, render once, read back the saved presentation."""
import hashlib
from html.parser import HTMLParser
import html
import re
import json


def validate_assessment(value):
    if not isinstance(value, dict) or set(value)-{'conclusion','recommendation'} or any(not isinstance(v,str) or len(v)>1800 for v in value.values()):
        raise ValueError('分析结论只接受简短的定性结论和建议')
    if any(re.search(r'\d+(?:\.\d+)?\s*(?:eV|Å|埃|电子伏)|<[^>]+>',v) for v in value.values()):
        raise ValueError('数值由Python证据块提供；结论只写定性解释，不接受自填数值或HTML')
    return value


def assessment(doc):
    return {**doc['data'].get('assessment', {}), **doc.get('assessment_edits', {})}


def assessment_html(doc):
    value = assessment(doc)
    return ''.join('<section class="card"><h2>'+title+'</h2><p style="white-space:pre-wrap">'+
        html.escape(value[key])+'</p></section>' for key, title in
        (('conclusion', '关键结论'), ('recommendation', '建议先做什么')) if value.get(key))


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
