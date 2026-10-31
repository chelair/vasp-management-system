"""Frozen report facts → registered Python calculations → small report elements.

No live observations, model arithmetic, remote reads or scientific-data writes.
"""
import copy
from collections import Counter
from decimal import Decimal
import html
import re
from pathlib import Path

from property_science import check, structure, vacancy, canonical, digest
from properties import RECIPES, formation, subtract, adsorption

SUPPORTED = ('relative_energy', 'adsorption.estimate', 'oxygen_vacancy.neutral_single')
FORMULAS = {
    'relative_energy': 'ΔE = E_model − E_reference',
    'adsorption.estimate': 'E_ads = E_complex − E_surface − E_adsorbate',
    'oxygen_vacancy.neutral_single': 'E_f(V_O) = E_defect − E_pristine + ½ E_O₂',
}
CSS = Path(__file__).with_suffix('.css').read_text(encoding='utf-8')


def presentation(value):
    if not isinstance(value,dict) or set(value)-{'layout','accent','show_sources','show_warnings'}:
        raise ValueError('卡片展示设置无效')
    if 'layout' in value and value['layout'] not in ('cards','table','compact'):
        raise ValueError('卡片布局无效')
    if 'accent' in value and value['accent'] not in ('blue','teal','violet'):
        raise ValueError('卡片配色无效')
    if any(type(value[key]) is not bool for key in ('show_sources','show_warnings') if key in value):
        raise ValueError('卡片显示设置无效')
    return copy.deepcopy(value)


class MissingCalculation(ValueError):
    """A real missing input: preserve the report and ask one precise question."""


def blocks(node):
    import report_ai_notes as ai
    return [{'id': 'body_'+ai.digest([node['key'], i, text])[:20], 'type': 'original', 'text': text}
            for i, text in enumerate(re.split(r'(\n\s*\n)', node['body'])) if text.strip()]


def frozen_structure(doc, fact):
    path = fact['path'][:-1]
    row = doc['science']
    for part in path:
        row = row[part]
    saved = row.get('structure') or {}
    cif = saved.get('contcar_cif') or saved.get('poscar_cif') or row.get('cif')
    if not cif:
        raise MissingCalculation(f'“{fact["label"]}”缺少报告冻结结构，无法确认是否只移除一个 O；请补充对应结构。')
    from cif_reader import cif_to_poscar
    try:
        poscar, summary = cif_to_poscar(cif)
        # Fractional occupancy cannot be silently rounded into integer atoms.
        if summary.get('warnings'):
            raise ValueError('；'.join(summary['warnings']))
        parsed = structure(poscar)
    except ValueError as exc:
        raise MissingCalculation(f'“{fact["label"]}”的冻结结构无法核对：{exc}') from None
    return parsed, row


def structure_catalog(doc, values):
    result = {}
    for fid, fact in values.items():
        if fact['field'] not in ('final_energy_ev', 'dft_energy_ev'):
            continue
        try:
            parsed, _ = frozen_structure(doc, fact)
            result[fid] = {'composition': parsed['composition'], 'source': 'saved_report_structure'}
        except MissingCalculation as exc:
            result[fid] = {'missing': str(exc)}
    pairs = []
    for pristine, a in result.items():
        for defect, b in result.items():
            if 'composition' not in a or 'composition' not in b:
                continue
            delta = Counter(a['composition']); delta.subtract(b['composition'])
            if {el: n for el, n in delta.items() if n} == {'O': 1}:
                pairs.append({'pristine': pristine, 'defect': defect})
    return {'structures': result, 'single_oxygen_pairs': pairs,
            'note': '组成只验证少一个O；结合用户所指体系选择对应，不按名称假定中性或参数已验证。'}


def bound_facts(values, bindings, roles):
    if (not isinstance(bindings, dict) or set(bindings) != set(roles)
            or any(not isinstance(ref, str) or ref not in values for ref in bindings.values())):
        raise MissingCalculation('缺少计算所需的报告能量或用户参考能量，请补充缺失的那一项。')
    facts = {role: copy.deepcopy(values[ref]) for role, ref in bindings.items()}
    if any(f['field'] not in ('final_energy_ev', 'dft_energy_ev', 'last_energy_ev', 'energy_ev', 'provided_energy_ev') for f in facts.values()):
        raise ValueError('该配方要求电子总能量，不能混用自由能、能垒或矫正项')
    return facts


def calculate(doc, values, action):
    pid = action.get('property_id')
    if pid not in SUPPORTED:
        raise MissingCalculation('UNSUPPORTED：该计算配方尚未接入报告批注。')
    if set(action) - {'kind', 'target', 'property_id', 'inputs', 'targets', 'presentation'}:
        raise ValueError('计算动作字段无效，不接受模型提供的公式或结果')
    settings=presentation(action.get('presentation',{}))
    if pid != 'oxygen_vacancy.neutral_single':
        if 'targets' in action:
            raise ValueError('该配方使用 inputs 绑定能量')
        roles = ('reference', 'model') if pid == 'relative_energy' else ('complex', 'surface', 'adsorbate')
        inputs = bound_facts(values, action.get('inputs'), roles)
        value = subtract(inputs['model']['value'], inputs['reference']['value']) if pid == 'relative_energy' else adsorption(*(inputs[r]['value'] for r in roles))
        return {'type': 'calculation', 'property_id': pid, 'version': RECIPES[pid].version,
                'title': '相对能量' if pid == 'relative_energy' else '初步吸附能', 'formula': FORMULAS[pid],
                'validation_status': 'PRELIMINARY', 'value_ev': value, 'inputs': inputs,
                'results': [{'label': '计算结果', 'value_ev': value, 'inputs': inputs}],
                'warnings': ['初步结果；组成、电荷态、收敛及计算条件尚需核实。'],'presentation':settings}
    reference = bound_facts(values, action.get('inputs'), ('oxygen',))['oxygen']
    given = [f for f in values.values() if f['field'] == 'provided_energy_ev' and f.get('reference_kind') in ('O2', 'mu_O')]
    if given:
        # New user replies override an older model binding. Multiple different
        # oxygen references in one statement require clarification.
        latest = [f for f in given if f['source']['statement'] == given[-1]['source']['statement']]
        chemical_potentials = {Decimal(str(f['value'])) / (2 if f['reference_kind'] == 'O2' else 1) for f in latest}
        if len(chemical_potentials) > 1:
            raise MissingCalculation('这条回复包含不同的氧参考值，请明确本次采用哪一个。')
        reference = copy.deepcopy(latest[-1])
    elif reference['field'] != 'provided_energy_ev':
        parsed, _ = frozen_structure(doc, reference)
        if parsed['composition'] != {'O': 2}:
            raise MissingCalculation('所选氧气参考的实际组成不是 O₂，请核对参考记录。')
        reference['reference_kind'] = 'O2'
    if reference.get('reference_kind') not in ('O2', 'mu_O'):
        raise MissingCalculation('请明确氧气分子能量 E(O₂) 或每个氧原子的化学势 μ_O。')
    mu = float(Decimal(str(reference['value'])) / (2 if reference['reference_kind'] == 'O2' else 1))
    targets = action.get('targets')
    if not isinstance(targets, list) or not 1 <= len(targets) <= 8:
        raise MissingCalculation('请明确要计算的完整结构和氧空位结构。')
    results, gaps = [], []
    for target in targets:
        if not isinstance(target, dict) or set(target) - {'label', 'pristine', 'defect'}:
            raise ValueError('氧空位体系字段无效')
        label = target.get('label', '氧空位体系')
        if not isinstance(label, str) or not label.strip() or len(label) > 200 or re.search(r'[<>\n|]', label):
            raise ValueError('体系名称无效')
        try:
            inputs = bound_facts(values, {r: target.get(r) for r in ('pristine', 'defect')}, ('pristine', 'defect'))
            a, pristine = frozen_structure(doc, inputs['pristine'])
            b, defect = frozen_structure(doc, inputs['defect'])
            # Reuse the registered vacancy check. Relaxed coordinates are allowed
            # for preliminary values; integer single-O composition is required.
            def data(parsed, fact):
                source = fact['source']
                return {'structure': parsed, 'settings': {k: canonical(v) for k,v in (source.get('incar_snapshot') or {}).items()},
                        'potentials': {}, 'hubbard': {}, 'kpoints': source.get('kpoints_snapshot'),
                        'energy_definition': 'report_frozen_total_energy'}
            checks, site = vacancy(data(a, inputs['pristine']), data(b, inputs['defect']))
            delta = Counter(a['composition']); delta.subtract(b['composition'])
            if {el: n for el, n in delta.items() if n} != {'O': 1}:
                raise MissingCalculation(f'{label}：组成差不是恰好移除一个 O（{a["composition"]} → {b["composition"]}），请核对配对。')
            # A known charged model cannot use the neutral recipe. Missing charge
            # evidence stays explicitly UNKNOWN in the preliminary card.
            charge = [r.get('charge_state') for r in (pristine, defect)]
            if any(type(q) in (int, float) and q != 0 for q in charge):
                raise MissingCalculation(f'{label}：已知为带电模型，不能使用中性氧空位公式。')
            checks += [check('single_oxygen_vacancy', 'AVAILABLE', f'{a["composition"]} → {b["composition"]}；恰好移除一个O'),
                       check('charge_state', 'AVAILABLE' if charge == [0, 0] else 'UNKNOWN', '报告冻结电荷态；未知时仅作为中性假设下的初步值')]
            if pristine.get('converged') is False or defect.get('converged') is False:
                checks.append(check('ionic_convergence', 'INCOMPLETE', '至少一份报告结构尚未离子收敛'))
            result = {'label': label, 'value_ev': formation(inputs['defect']['value'], inputs['pristine']['value'], mu),
                      'inputs': inputs, 'checks': checks, 'site': site,
                      'structure_evidence': {'pristine_sha256': digest(a), 'defect_sha256': digest(b),
                                             'scope': 'saved_report_CIF_not_live_input'},
                      'compositions': {'pristine': a['composition'], 'defect': b['composition']}}
            results.append(result)
        except MissingCalculation as exc:
            gaps.append(str(exc))
    if not results:
        raise MissingCalculation(gaps[0])
    warnings = ['中性模型假设下的初步结果；电荷态、位点对应、晶胞与计算条件仍需核实。']
    warnings += [r['label']+'：'+c['check']+'，'+c['detail'] for r in results for c in r['checks'] if c['status'] in ('INVALID','INCOMPLETE')]
    if any(r['value_ev'] < 0 for r in results):
        warnings.append('存在负形成能，请核对氧参考态、结构配平及计算一致性。')
    return {'type': 'calculation', 'title': '氧空位形成能', 'property_id': pid, 'version': RECIPES[pid].version,
            'formula': FORMULAS[pid] if reference['reference_kind'] == 'O2' else 'E_f(V_O) = E_defect − E_pristine + μ_O',
            'validation_status': 'PRELIMINARY', 'reference': reference, 'mu_O_ev': mu,
            'results': results, 'warnings': warnings, 'gaps': gaps,'presentation':settings}


def markdown(element):
    def clean(value):
        return str(value).replace('|', '／').replace('\n', ' ')
    if element['type']=='layout':
        return '\n\n'.join(markdown(e) for e in element['items'])
    title = element.get('title', '')
    parts = [f'**{title}**'] if title else []
    if element['type'] in ('calculation', 'formula'):
        parts += ['计算公式：`'+element['formula']+'`']
    if element['type'] == 'calculation':
        reference = element.get('reference')
        if reference:
            name = '氧气分子能量' if reference['reference_kind'] == 'O2' else '氧原子化学势'
            parts += [f'{name}：{reference["value"]} eV；μ_O = {element["mu_O_ev"]} eV。']
        oxygen = element['property_id'] == 'oxygen_vacancy.neutral_single'
        if oxygen:
            table = ['| 体系 | E_defect (eV) | E_pristine (eV) | E_f (eV) |', '|---|---:|---:|---:|']
            for row in element['results']:
                table += [f'| {clean(row["label"])} | {row["inputs"]["defect"]["value"]:.8f} | {row["inputs"]["pristine"]["value"]:.8f} | {row["value_ev"]:.8f} |']
            parts += ['\n'.join(table)]
        else:
            parts += [f'**初步计算结果**：{element["value_ev"]:+.8f} eV']
        sources = []
        role_names = {'pristine': '完整结构', 'defect': '氧空位结构', 'reference': '参考结构',
                      'model': '对比结构', 'complex': '完整构型', 'surface': '基底', 'adsorbate': '吸附质'}
        for row in element['results']:
            for role, fact in row['inputs'].items():
                sources += ['- '+clean(row['label'])+' · '+role_names[role]+'：'+source_text(fact)]
        if reference:
            sources += ['- '+source_text(reference)]
        settings=element.get('presentation') or {}
        if settings.get('show_sources',True):parts += ['数据来源：', '\n'.join(sources)]
        if settings.get('show_warnings',False):parts += ['\n'.join('- '+text for text in element.get('warnings', []))]
    if element['type'] == 'sources':
        parts += ['\n'.join('- '+source_text(fact) for fact in element['sources'])]
    if element.get('text'):
        parts += [element['text']]
    return '\n\n'.join(parts)


def source_text(fact):
    source = fact.get('source') or {}
    if source.get('kind') == 'user_provided':
        text = f'用户给定：{source["original_value"]} {source["original_unit"]}'
        if source['original_unit'].lower() != 'ev':
            text += f'（采用 {fact["value"]} eV）'
    else:
        text = f'{fact["label"].split(" · ")[0]} = {fact["value"]} eV（报告中的计算记录）'
    return text.replace('\n', ' ').replace('|', '／')


def render_html(element):
    from report_export import markdown_to_html
    esc=lambda value:html.escape(str(value),quote=True)
    settings=element.get('presentation') or {}
    accent=settings.get('accent','blue')
    if element['type']=='layout':
        return ('<div class="report-review-layout" style="--rr-columns:'+str(element['columns'])+'">'
                +''.join(render_html(e) for e in element['items'])+'</div>')
    shell=('<article class="report-review-element rr-'+esc(element['type'])+' rr-accent-'+esc(accent)
           +'" data-review-element="'+esc(element['id'])+'"><style>'+CSS+'</style>')
    if element['type'] not in ('calculation','callout'):
        return shell+markdown_to_html(markdown(element))+'</article>'
    icon='<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" stroke="currentColor" stroke-width="1.5"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9" stroke="currentColor" stroke-width="1.5"/></svg>'
    header=('<header class="rr-header"><span class="rr-icon">'+icon+'</span><div><span class="rr-eyebrow">'
            +('计算结果' if element['type']=='calculation' else '报告摘要')+'</span><h4 class="rr-title">'
            +esc(element.get('title',''))+'</h4></div></header>')
    if element['type']=='callout':
        return shell+header+'<div class="rr-copy">'+markdown_to_html(element['text'])+'</div></article>'
    rows=element['results'];layout=settings.get('layout','cards')
    def energy(value):return f'{value:.8f}'
    def formula():
        return {'relative_energy':'ΔE = E<sub>model</sub> − E<sub>reference</sub>',
                'adsorption.estimate':'E<sub>ads</sub> = E<sub>complex</sub> − E<sub>surface</sub> − E<sub>adsorbate</sub>',
                'oxygen_vacancy.neutral_single':'E<sub>f</sub>(V<sub>O</sub>) = E<sub>defect</sub> − E<sub>pristine</sub> + '
                    +('½ E<sub>O₂</sub>' if (element.get('reference') or {}).get('reference_kind')=='O2' else 'μ<sub>O</sub>')}.get(element['property_id'],esc(element['formula']))
    names={'pristine':'完整结构','defect':'氧空位结构','reference':'参考结构','model':'对比结构',
           'complex':'完整构型','surface':'基底','adsorbate':'吸附质'}
    tiles=[]
    maximum=max(abs(row['value_ev']) for row in rows) or 1
    for row in rows:
        inputs=''.join('<div class="rr-input"><dt>'+names[role]+'</dt><dd>'+energy(fact['value'])+'<small> eV</small></dd></div>' for role,fact in row['inputs'].items())
        bar=('<div class="rr-bar-track" aria-hidden="true"><span style="width:'+str(round(abs(row['value_ev'])/maximum*100,3))+'%"></span></div>') if len(rows)>1 else ''
        tiles.append('<section class="rr-result"><div class="rr-result-label">'+esc(row['label'])+'</div>'
                     +'<div class="rr-value">'+energy(row['value_ev'])+'<span>eV</span></div>'+bar
                     +'<dl class="rr-inputs">'+inputs+'</dl></section>')
    if layout=='table':
        table=['<div class="rr-table-wrap"><table class="rr-table"><thead><tr><th>体系</th><th>输入能量 / eV</th><th>计算结果 / eV</th></tr></thead><tbody>']
        for row in rows:
            inputs='<br>'.join(esc(names[role])+': '+energy(fact['value']) for role,fact in row['inputs'].items())
            table.append('<tr><td>'+esc(row['label'])+'</td><td>'+inputs+'</td><td class="rr-table-value">'+energy(row['value_ev'])+'</td></tr>')
        content=''.join(table)+'</tbody></table></div>'
    else:
        content='<div class="rr-results rr-results-'+layout+'">'+''.join(tiles)+'</div>'
    reference=element.get('reference');reference_html=''
    if reference:
        label='O₂ 分子能量' if reference['reference_kind']=='O2' else '氧原子化学势'
        reference_html=('<div class="rr-reference"><span>'+label+' <b>'+esc(reference['value'])+' eV</b></span>'
                        +'<span>μ<sub>O</sub> <b>'+esc(element['mu_O_ev'])+' eV</b></span></div>')
    sources=[]
    for row in rows:
        for fact in row['inputs'].values():
            text=source_text(fact)
            if text not in sources:sources.append(text)
    if reference:sources.append(source_text(reference))
    source_html=('<details class="rr-sources"><summary>数据来源<span>查看计算记录与参考能量</span></summary><ul>'
                 +''.join('<li>'+esc(text)+'</li>' for text in sources)+'</ul></details>') if settings.get('show_sources',True) else ''
    warnings=('<div class="rr-warnings">'+''.join('<p>'+esc(text)+'</p>' for text in element.get('warnings',[]))+'</div>') if settings.get('show_warnings',False) else ''
    note='<div class="rr-copy">'+markdown_to_html(element['text'])+'</div>' if element.get('text') else ''
    return shell+header+content+'<div class="rr-formula"><span>计算公式</span><div>'+formula()+'</div></div>'+reference_html+note+source_html+warnings+'</article>'


def export_markdown(doc):
    elements = doc.get('review_elements') or {}
    text = '\n\n'.join('## '+s['title']+'\n\n'+s.get('markdown', '') for s in doc.get('markdown_sections') or [])
    return re.sub(r'@\[review-element:([^\]\s]+)\]', lambda m: markdown(elements[m[1]]) if m[1] in elements else '', text)
