"""Goal-led endpoint evidence. Fixed geometry/readers only; never run calculations.

Distances are screening evidence, not bond orders, reaction energies or phases.
The compact tool result and the illustrated report use this same calculation.
"""
from itertools import combinations
import math

import permissions
from storage import load_db
from checks_store import merged_results
from task_paths import is_auxiliary_task
from structure_sources import load_many, load_check_evidence
import structure_geometry as g


class MissingEndpointEvidence(ValueError):
    """Geometry diagnosis is unavailable; an existing energy profile may suffice."""


VERSION = 'reaction.review.1'
KEYS = {'path_task_id', 'initial', 'final', 'source', 'bond_elements', 'fragment_indices', 'fragment_elements', 'contact_elements', 'contact_cutoff', 'pbc'}


def research_context(project):
    from project_requirements import summary
    return {'project_id': project['project_id'], 'project_name': project['name'],
            'calculation_goal': project.get('calc_description') or '',
            'requirements': summary(project),
            'expected_results': project.get('expected_results') or '',
            'description': project.get('description') or '',
            'rule': '最新用户目标优先；预期用于定义要检验的过程，不预设结论。名称不是反应身份的证据。'}


def paths(project):
    return [t for t in project.get('tasks', []) if not is_auxiliary_task(t) and t.get('task_type') == 'neb']


def distance(parsed, i, j, pbc):
    d, vector, _ = g.minimum_image([parsed['fractional'][j-1][k] - parsed['fractional'][i-1][k] for k in range(3)], parsed['lattice'], parsed['reciprocal'], pbc)
    start = g.cartesian(parsed['fractional'][i-1], parsed['lattice'])
    return round(d, 6), [start, [start[k] + vector[k] for k in range(3)]]


def _elements(values, maximum=12):
    if not isinstance(values, list) or not 1 <= len(values) <= maximum or any(not isinstance(x, str) or not x.isalpha() or len(x) > 3 for x in values):
        raise ValueError('请提供有界的元素符号列表')
    return values


def _cif(parsed):
    cell = g.cell_summary(parsed['lattice'])
    rows = ['data_frozen_structure']
    rows += [f'_cell_length_{axis} {value:.10f}' for axis, value in zip('abc', cell['lengths_angstrom'])]
    rows += [f'_cell_angle_{axis} {value:.10f}' for axis, value in zip(('alpha','beta','gamma'), cell['angles_degrees'])]
    rows += ["_symmetry_space_group_name_H-M 'P 1'", 'loop_', '_atom_site_label', '_atom_site_type_symbol', '_atom_site_fract_x', '_atom_site_fract_y', '_atom_site_fract_z']
    rows += [f'{el}{i+1} {el} ' + ' '.join(f'{v:.10f}' for v in pos) for i, (el, pos) in enumerate(zip(parsed['atoms'], parsed['fractional']))]
    return '\n'.join(rows) + '\n'


def analyze(project, user, arguments, *, illustrations=False):
    if not isinstance(arguments, dict) or set(arguments) - KEYS:
        raise ValueError('路径诊断仅接受当前项目路径、结构选择及几何筛选，不接受命令或任意文件')
    current = next((p for p in load_db().get('projects', []) if p.get('project_id') == project.get('project_id')), None)
    permissions.ensure_project_owner(current, user)
    if not current:
        raise ValueError('项目不存在')
    path = next((t for t in paths(current) if t['task_id'] == arguments.get('path_task_id')), None)
    if not path:
        raise ValueError('请先选择当前项目的NEB路径任务')
    gid = (path.get('group') or {}).get('group_id')
    endpoints = {}
    for role, name in (('initial_opt', 'initial'), ('final_opt', 'final')):
        matches = [t for t in current['tasks'] if not is_auxiliary_task(t) and gid and (t.get('group') or {}).get('group_id') == gid and (t.get('group') or {}).get('group_role') == role]
        if len(matches) != 1:
            raise MissingEndpointEvidence('该路径无法唯一定位两端结构，请先确认端点关联')
        endpoints[name] = matches[0]
    source_kind = arguments.get('source', 'local')
    if source_kind not in ('local', 'remote'):
        raise ValueError('来源只支持local或remote')
    pbc = arguments.get('pbc', [True, True, True])
    if not isinstance(pbc, list) or len(pbc) != 3 or any(type(x) is not bool for x in pbc):
        raise ValueError('周期边界需要三个布尔值')
    selectors = []
    for name, task in endpoints.items():
        selection = arguments.get(name) or {'task_id': task['task_id'], 'source': source_kind, 'file': 'CONTCAR', **({'directory': 'CURRENT'} if source_kind == 'remote' else {})}
        if not isinstance(selection, dict) or selection.get('task_id') != task['task_id']:
            raise ValueError('结构选择必须属于这条路径的对应端点')
        selectors.append(selection)
    try:
        loaded = load_many(current, selectors)
    except ValueError as exc:
        if str(exc).startswith('本地结构不存在'):
            raise MissingEndpointEvidence(str(exc)) from exc
        raise
    parsed = [g.parse(text) for text, _ in loaded]
    if parsed[0]['atoms'] != parsed[1]['atoms']:
        raise ValueError('两端元素顺序或原子数量不同，不能猜测原子映射；请先核对端点')
    a, b = parsed
    bond = _elements(arguments.get('bond_elements', ['B', 'F']), 2)
    if len(bond) != 2 or any(el not in a['atoms'] for el in bond):
        raise ValueError('请按研究目标提供结构中存在的两个反应元素')
    fragment_elements = _elements(arguments.get('fragment_elements', ['B', 'C', 'O', 'F']))
    fragment = arguments.get('fragment_indices') or [i+1 for i, el in enumerate(a['atoms']) if el in fragment_elements]
    if not isinstance(fragment, list) or not 2 <= len(fragment) <= 96 or len(set(fragment)) != len(fragment) or any(type(i) is not int or not 1 <= i <= len(a['atoms']) for i in fragment):
        raise ValueError('需要明确2至96个研究片段原子；较大片段或与基底共用元素时请按编号指定，不猜测片段归属')
    contact_elements = _elements(arguments.get('contact_elements', ['Li']))
    cutoff = arguments.get('contact_cutoff', 2.6)
    if type(cutoff) not in (int, float) or not math.isfinite(cutoff) or not .5 <= cutoff <= 4:
        raise ValueError('接触筛查距离须在0.5至4Å之间')
    outside = [i+1 for i, el in enumerate(a['atoms']) if i+1 not in fragment and el in contact_elements]
    centers = [i for i in fragment if a['atoms'][i-1] == 'O']
    if len(centers) * len(outside) > 10000:
        raise ValueError('界面筛查范围过大，请缩小研究片段和接触元素')
    candidates = set()
    for structure in parsed:
        for i in fragment:
            if structure['atoms'][i-1] != bond[0]:
                continue
            near = sorted((distance(structure, i, j, pbc)[0], j) for j in fragment if j != i and structure['atoms'][j-1] == bond[1])
            candidates.update((i, j) for _, j in near[:2])
    if len(candidates) > 12:
        raise ValueError('候选反应键超过12对，请缩小研究片段，不抽取前几个原子代替整体')
    bonds = [{'atoms': list(pair), 'label': chr(65+k), 'elements': bond,
              'initial_angstrom': distance(a, *pair, pbc)[0], 'final_angstrom': distance(b, *pair, pbc)[0]}
             for k, pair in enumerate(sorted(candidates))]
    contacts = []
    for i in centers:
        for j in outside:
            da, db = distance(a, i, j, pbc)[0], distance(b, i, j, pbc)[0]
            if min(da, db) <= cutoff:
                contacts.append({'atoms': [i,j], 'elements': [a['atoms'][i-1], a['atoms'][j-1]],
                                 'initial_angstrom': da, 'final_angstrom': db,
                                 'state': 'initial_only' if da <= cutoff < db else 'final_only' if db <= cutoff < da else 'both'})
    contacts.sort(key=lambda r: (r['state'] == 'both', -abs(r['final_angstrom'] - r['initial_angstrom'])))
    # Pair distances remove rigid translations/rotations; omit the leaving element
    # so the intended bond extension does not itself become "framework deformation".
    core = [i for i in fragment if a['atoms'][i-1] != bond[1]]
    shape = [{'atoms': [i,j], 'change_angstrom': round(distance(b,i,j,pbc)[0] - distance(a,i,j,pbc)[0],6)} for i,j in combinations(core, 2)]
    shape_rms = math.sqrt(sum(r['change_angstrom']**2 for r in shape)/len(shape)) if shape else None
    constraints = [i+1 for i, (fa,fb) in enumerate(zip(a['fixed_axes'],b['fixed_axes'])) if fa != fb]
    companion = []
    for _, src in loaded:
        try:
            companion.append(load_check_evidence(current, src))
        except ValueError as exc:
            companion.append({'files': {}, 'note': str(exc), 'co_run_verified': False})
    keys = ('ENCUT','GGA','IVDW','ISPIN','NELECT','LDIPOL','IDIPOL','DIPOL','EDIFF','EDIFFG','LDAU','LSORBIT')
    parameter_rows = []
    for key in keys:
        values = [c['files'].get('INCAR', {}).get('settings', {}).get(key) for c in companion]
        parameter_rows.append({'name':key, 'initial':values[0], 'final':values[1], 'status':'unknown' if None in values else 'same' if values[0] == values[1] else 'different'})
    kp = [c['files'].get('KPOINTS', {}).get('grid') for c in companion]
    parameter_rows.append({'name':'KPOINTS', 'initial':kp[0], 'final':kp[1], 'status':'unknown' if None in kp else 'same' if kp[0] == kp[1] else 'different'})
    observations = merged_results()
    neb = observations.get(path['task_id']) or {}
    energy_rows = (neb.get('neb_barrier') or {}).get('images') or []
    energies = [r.get('energy') for r in energy_rows]
    finite = bool(energies) and all(type(v) in (int,float) and math.isfinite(v) for v in energies)
    from properties import subtract
    profile = {'images': energy_rows, 'sampled_max_difference_ev': subtract(max(energies), energies[0]) if finite else None,
               'interior_peak_observed': any(v > max(energies[0],energies[-1]) for v in energies[1:-1]) if finite else None,
               'kind': 'local_latest_inspection', 'observed_at': neb.get('checked_at'),
               'note':'离散采样诊断，不是已收敛反应能垒；结构、输入与能量未证明来自同次运行。'}
    result = {'schema_version': VERSION, 'research_context':research_context(current),
              'path_task_id': path['task_id'], 'path_name': (path.get('group') or {}).get('name') or path.get('model_name'),
              'sources': {name: source for name, (_,source) in zip(endpoints, loaded)},
              'fragment': {'atom_indices':fragment, 'selection':'explicit' if arguments.get('fragment_indices') else 'element_based_candidate',
                           'note':'元素筛选仅候选研究片段；片段外Li可能属于基底或反离子，不能一律当成表面Li。'},
              'mapping': '同元素同顺序的候选对应；未证明同元素原子没有重排',
              'candidate_reaction_bonds': bonds, 'interface_contacts': contacts[:24], 'contacts_truncated':len(contacts)>24,
              'contact_criteria': {'cutoff_angstrom':cutoff, 'note':'距离近邻，不是化学键/键级/电荷转移的证明；阈值附近应复核。'},
              'framework_shape': {'pair_distance_rms_change_angstrom':round(shape_rms,6) if shape_rms is not None else None,
                                  'atoms':core, 'largest_changes': sorted(shape,key=lambda r:-abs(r['change_angstrom']))[:6],
                                  'note':'不含离去元素的片段内距离矩阵变化；剔除刚体平移/转动，不能换算形变能。'},
              'constraints': {'changed_atom_indices': constraints, 'reaction_center_constraints': [
                  {'index':i, 'initial':a['fixed_axes'][i-1], 'final':b['fixed_axes'][i-1]} for i in sorted({i for r in bonds for i in r['atoms']})]},
              'parameters':parameter_rows, 'parameter_sources':companion,
              'energy_profile':profile,
              'deformation_energy': {'value_ev':None, 'reason':'缺同一片段/电荷/自旋/晶胞与理论条件下的固定几何单点参考；不能从两端总能或位移拆出形变能和Li–O脱配位能。'},
              'limitations':['几何筛查不能自动判成键、价态、变性或证明反应机理。', '两端差异可能是实际反应耦合，也可能偏离限定断键的研究目标；先确认目标和候选反应键。']}
    if illustrations:
        for name, structure in zip(endpoints, parsed):
            annotations = []
            for row in bonds + [r for r in contacts if r['state'] != 'both'][:5]:
                d, points = distance(structure, *row['atoms'], pbc)
                annotations.append({'atoms':row['atoms'], 'points':points, 'label':row.get('label','O–'+structure['atoms'][row['atoms'][1]-1]),
                                    'distance_angstrom':d, 'kind':'reaction' if row in bonds else 'contact'})
            result.setdefault('structures', {})[name] = {'cif':_cif(structure), 'annotations':annotations,
                'focus_atom_indices':sorted(set(fragment+[i for row in annotations for i in row['atoms']])),
                'atoms': [g.atom_record(structure,i) for i in range(len(structure['atoms']))]}
    return result
