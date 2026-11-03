"""Versioned manual layout, independent of scientific facts and AI review edits."""
import html
import json
import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WIDTH = 960
KINDS = Literal['text', 'rectangle', 'rounded', 'square', 'circle', 'ellipse', 'triangle', 'diamond', 'line', 'arrow', 'double-arrow']


class Style(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    fill: str = '#ffffff'
    fill_opacity: float = Field(default=0.85, ge=0, le=1)
    stroke: str = '#3f6fe0'
    stroke_width: float = Field(default=2, ge=0, le=16)
    stroke_opacity: float = Field(default=1, ge=0, le=1)
    dash: Literal['solid', 'dashed', 'dotted'] = 'solid'
    arrow_start: bool = False
    arrow_end: bool = True
    color: str = '#233043'
    font_size: float = Field(default=24, ge=8, le=96)
    font_weight: Literal[400, 500, 600, 700, 800] = 400
    italic: bool = False
    align: Literal['left', 'center', 'right'] = 'left'
    vertical: Literal['start', 'center', 'end'] = 'center'
    padding: float = Field(default=12, ge=0, le=40)

    @field_validator('fill', 'stroke', 'color')
    @classmethod
    def color_value(cls, value):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError('颜色须为六位十六进制色值')
        return value


class LayoutObject(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    report_id: str
    region: str = Field(min_length=1, max_length=200)
    anchor: str = Field(default='', pattern=r'^(heading|a_[0-9a-f]{8}_[0-9]+)?$')
    kind: KINDS
    x: float = Field(ge=-1000000, le=1000000)
    y: float = Field(ge=-1000000, le=1000000)
    width: float = Field(ge=0, le=9600)
    height: float = Field(ge=0, le=9600)
    rotation: float = Field(default=0, ge=-180, le=180)
    # Signed endpoint offsets allow arrows in all directions.
    dx: float = Field(default=180, ge=-9600, le=9600)
    dy: float = Field(default=0, ge=-9600, le=9600)
    text: str = Field(default='', max_length=4000)
    z: int = Field(default=0, ge=0, le=500)
    style: Style = Field(default_factory=Style)
    created_at: str = ''
    updated_at: str = ''

    @model_validator(mode='after')
    def bounds(self):
        if self.kind in ('line', 'arrow', 'double-arrow'):
            self.rotation = 0
        else:
            if min(self.width, self.height) < 24:
                raise ValueError('对象尺寸至少为24')
            if self.kind in ('square', 'circle') and abs(self.width - self.height) > .01:
                raise ValueError('正方形和圆形须保持宽高比')
        return self


class Layout(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0, strict=True)
    objects: list[LayoutObject] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def unique(self):
        if len({o.id for o in self.objects}) != len(self.objects):
            raise ValueError('对象ID不能重复')
        return self


def shape_markup(o):
    """Only validated attributes and escaped plain text enter the exported SVG."""
    s = o['style']; w, h = o['width'], o['height']
    line = o['kind'] in ('line', 'arrow', 'double-arrow')
    dash = {'solid': '', 'dashed': '10 6', 'dotted': '2 5'}[s['dash']]
    attrs = f'fill="{s["fill"] if not line else "none"}" fill-opacity="{s["fill_opacity"]}" stroke="{s["stroke"]}" stroke-width="{s["stroke_width"]}" stroke-opacity="{s["stroke_opacity"]}" stroke-dasharray="{dash}"'
    if line:
        # Explicit triangles work in Chromium PDF and do not depend on marker scaling.
        dx, dy = o['dx'], o['dy']; length = math.hypot(dx, dy) or 1
        ux, uy = dx / length, dy / length
        arrow = max(10, s['stroke_width'] * 3)
        parts = [f'<path d="M0 0 L{dx} {dy}" {attrs}/>']
        for end, enabled in [(False, s['arrow_start']), (True, s['arrow_end'])]:
            if not enabled or o['kind'] == 'line': continue
            px, py, sign = (dx, dy, 1) if end else (0, 0, -1)
            bx, by = px - sign * ux * arrow, py - sign * uy * arrow
            points = f'{px},{py} {bx-uy*arrow/2},{by+ux*arrow/2} {bx+uy*arrow/2},{by-ux*arrow/2}'
            parts.append(f'<polygon points="{points}" fill="{s["stroke"]}" fill-opacity="{s["stroke_opacity"]}"/>')
        return ''.join(parts)
    if o['kind'] in ('circle', 'ellipse'):
        shape = f'<ellipse cx="{w/2}" cy="{h/2}" rx="{w/2-s["stroke_width"]/2}" ry="{h/2-s["stroke_width"]/2}" {attrs}/>'
    elif o['kind'] in ('triangle', 'diamond'):
        points = f'{w/2},0 {w},{h} 0,{h}' if o['kind'] == 'triangle' else f'{w/2},0 {w},{h/2} {w/2},{h} 0,{h/2}'
        shape = f'<polygon points="{points}" {attrs}/>'
    else:
        inset = s['stroke_width']/2
        shape = f'<rect x="{inset}" y="{inset}" width="{w-2*inset}" height="{h-2*inset}" rx="{18 if o["kind"] == "rounded" else 0}" {attrs}/>'
    text_style = f'box-sizing:border-box;width:100%;height:100%;display:flex;flex-direction:column;justify-content:{s["vertical"]};padding:{s["padding"]}px;color:{s["color"]};font: {"italic" if s["italic"] else "normal"} {s["font_weight"]} {s["font_size"]}px/1.35 Arial,"Microsoft YaHei",sans-serif;text-align:{s["align"]};white-space:pre-wrap;overflow-wrap:anywhere;overflow:visible;'
    return shape + f'<foreignObject width="{w}" height="{h}"><div xmlns="http://www.w3.org/1999/xhtml" style=\'{text_style}\'><div>{html.escape(o["text"])}</div></div></foreignObject>'



def state(report_id):
    from report_store import read_edits
    return read_edits(report_id).get('layout') or Layout().model_dump()


def save(report_id, layout):
    import report_store as store
    with store._notes_lock:
        doc, _, _ = store.load_report(report_id)
        previous = state(report_id)
        if layout.revision != previous['revision']:
            raise ValueError('排版已在其他窗口修改，请刷新后核对；当前修改未保存')
        old = {o['id']: o for o in previous['objects']}
        from report_review import effective
        displayed = effective(doc)
        regions = {s['key'] for s in displayed.get('markdown_sections', [])}
        anchors = {s['key']: set(anchor_ids(s.get('markdown', ''), s['key'])) | {'heading'}
                   for s in displayed.get('markdown_sections', [])}
        stamp = datetime.now().isoformat(timespec='seconds')
        for o in layout.objects:
            if o.report_id != report_id:
                raise TypeError('对象必须属于当前报告')
            if o.region not in regions and old.get(o.id, {}).get('region') != o.region:
                raise TypeError('对象所属章节不存在')
            if o.anchor and o.anchor not in anchors.get(o.region, set()):
                before = old.get(o.id, {})
                if before.get('region') != o.region or before.get('anchor') != o.anchor:
                    raise TypeError('原文位置已变化，请在报告中重新放置对象')
            o.created_at = old.get(o.id, {}).get('created_at') or stamp
            before = old.get(o.id, {})
            changed = any(before.get(k) != v for k, v in o.model_dump().items() if k not in ('created_at', 'updated_at'))
            o.updated_at = stamp if changed else before.get('updated_at', stamp)
        result = layout.model_dump(); result['revision'] += 1
        store.save_layout(report_id, result)
        return result



def anchor_ids(markdown, section):
    counts, headings, result = {}, [], []
    for raw in markdown.split('\n'):
        line = raw.strip()
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            while headings and headings[-1][0] >= len(heading[1]): headings.pop()
            headings.append((len(heading[1]), heading[2]))
        identity = json.dumps([section, [h[1] for h in headings], line], ensure_ascii=False, separators=(',', ':'))
        value = 2166136261
        for byte in identity.encode('utf-8'): value = ((value ^ byte) * 16777619) & 0xffffffff
        key = f'{value:08x}'
        occurrence = counts.get(key, 0)
        counts[key] = occurrence + 1
        result.append(f'a_{key}_{occurrence}')
    return result


def object_bounds(o):
    if o['kind'] in ('line', 'arrow', 'double-arrow'):
        x, y = min(o['x'], o['x']+o['dx']), min(o['y'], o['y']+o['dy'])
        w, h = abs(o['dx']), abs(o['dy'])
    else:
        angle = math.radians(o['rotation'])
        w = abs(o['width']*math.cos(angle))+abs(o['height']*math.sin(angle))
        h = abs(o['width']*math.sin(angle))+abs(o['height']*math.cos(angle))
        x, y = o['x']+(o['width']-w)/2, o['y']+(o['height']-h)/2
    pad = max(14, o['style']['stroke_width']*3)
    return x-pad, y-pad, w+2*pad, h+2*pad


def render_floating(layout, chosen, available):
    parts = []
    for o in sorted(layout.get('objects', []), key=lambda o: o['z']):
        anchor = o.get('anchor') or 'heading'
        if o['region'] not in chosen or (anchor, o['region']) not in available: continue
        x, y, w, h = object_bounds(o)
        style = (f'position:absolute;display:block;overflow:visible;max-width:none;max-height:none;pointer-events:none;visibility:hidden;'
                 f'left:{x/9.6}cqw;top:{y/9.6}cqw;width:{w/9.6}cqw;height:{h/9.6}cqw;'
                 f'z-index:{100+o["z"]};break-inside:avoid;print-color-adjust:exact;-webkit-print-color-adjust:exact')
        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" class="report-layout-floating report-manual-object" '
                     f'data-layout-region="{html.escape(o["region"], quote=True)}" data-layout-anchor-ref="{anchor}" '
                     f'viewBox="{x} {y} {w} {h}" style="{style}">'
                     f'<g data-layout-object="{o["id"]}" transform="translate({o["x"]} {o["y"]}) rotate({o["rotation"]} {o["width"]/2} {o["height"]/2})">{shape_markup(o)}</g></svg>')
    if not parts: return ''
    return ''.join(parts) + '<script>' + FLOATING_SCRIPT + '</script>'


FLOATING_SCRIPT = r"""
(function(){
  var objects=Array.from(document.querySelectorAll('.report-layout-floating'));
  var anchors=Array.from(document.querySelectorAll('[data-layout-anchor]'));
  function mount(printing){
    objects.forEach(function(svg){
      var anchor=anchors.find(function(a){return a.getAttribute('data-layout-anchor')===svg.getAttribute('data-layout-anchor-ref')&&a.getAttribute('data-layout-section')===svg.getAttribute('data-layout-region');});
      if(!anchor){svg.style.visibility='hidden';return;}
      if(printing && anchor.hasAttribute('data-report-widget')){
        var prev=anchor.previousElementSibling,next=anchor.nextElementSibling;
        if(prev && prev.tagName==='FIGURE') anchor=prev;
        else if(next && (next.tagName==='FIGURE'||next.classList.contains('img-row')))anchor=next;
      }
      if(printing && getComputedStyle(anchor).display==='none'){
        var nearby=anchor.previousElementSibling;
        while(nearby && (nearby.tagName==='STYLE'||getComputedStyle(nearby).display==='none'))nearby=nearby.previousElementSibling;
        anchor=nearby||anchors.find(function(a){return a.getAttribute('data-layout-anchor')==='heading'&&a.getAttribute('data-layout-section')===svg.getAttribute('data-layout-region');})||anchor;
      }
      if(getComputedStyle(anchor).position==='static')anchor.style.position='relative';
      var host=anchor.tagName==='TABLE'?anchor.querySelector('th,td'):anchor.tagName==='UL'?anchor.querySelector('li'):anchor;
      if(!host){svg.style.visibility='hidden';return;}
      host.appendChild(svg);svg.style.visibility='visible';
    });
  }
  mount(false);
  window.addEventListener('beforeprint',function(){mount(true);});
  window.addEventListener('afterprint',function(){mount(false);});
})();
"""
