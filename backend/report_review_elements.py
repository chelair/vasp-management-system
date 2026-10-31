"""Frozen report facts → registered Python calculations → small report elements.

No live observations, model arithmetic, remote reads or scientific-data writes.
"""
import copy
from collections import Counter
from decimal import Decimal
import html
import re

from property_science import check, structure, vacancy, canonical, digest
from properties import RECIPES, formation, subtract, adsorption

SUPPORTED = ('relative_energy', 'adsorption.estimate', 'oxygen_vacancy.neutral_single')
FORMULAS = {
    'relative_energy': 'ΔE = E_model − E_reference',
    'adsorption.estimate': 'E_ads = E_complex − E_surface − E_adsorbate',
    'oxygen_vacancy.neutral_single': 'E_f(V_O) = E_defect − E_pristine + ½ E_O₂',
}


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
    if set(action) - {'kind', 'target', 'property_id', 'inputs', 'targets'}:
        raise ValueError('计算动作字段无效，不接受模型提供的公式或结果')
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
                'warnings': ['初步结果；组成、电荷态、收敛及计算条件尚需核实。']}
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
            'results': results, 'warnings': warnings, 'gaps': gaps}


def markdown(element):
    def clean(value):
        return str(value).replace('|', '／').replace('\n', ' ')
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
        parts += ['数据来源：', '\n'.join(sources)]
        parts += ['\n'.join('- '+text for text in element.get('warnings', []))]
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
    return ('<article class="report-review-element" data-review-element="'+html.escape(element['id'], quote=True)+'" '
            'style="border:1px solid #dce3ec;border-radius:8px;padding:16px;margin:14px 0;break-inside:avoid;overflow-wrap:anywhere">'
            +markdown_to_html(markdown(element))+'</article>')


def export_markdown(doc):
    elements = doc.get('review_elements') or {}
    text = '\n\n'.join('## '+s['title']+'\n\n'+s.get('markdown', '') for s in doc.get('markdown_sections') or [])
    return re.sub(r'@\[review-element:([^\]\s]+)\]', lambda m: markdown(elements[m[1]]) if m[1] in elements else '', text)
