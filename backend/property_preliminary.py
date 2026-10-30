"""Minimum report inputs; formal property verification stays in properties."""
from property_science import check, structure


def calculable(checks, preliminary=False):
    if not preliminary:
        return all(c['status'] == 'AVAILABLE' for c in checks)
    hard = {'composition', 'single_oxygen_vacancy', 'stoichiometry', 'charge_state', 'task_type',
            'potcar_elements', 'structure_safety', 'source_identity', 'direction',
            'reference_side', 'energy', 'observation_energy', 'image_completeness',
            'common_oxygen_reference', 'common_adsorbate_reference'}
    return not any(c['check'] in hard and c['status'] != 'AVAILABLE'
                   and (c['status'] == 'INVALID' or c['check'] in
                        ('image_completeness', 'common_oxygen_reference', 'common_adsorbate_reference'))
                   for c in checks)


def structure_checks(row):
    """Screen only captured geometry, using the existing bounded contact check."""
    evidence = row.get('property_evidence') or {}
    directory = (row.get('current_output') or {}).get('dir')
    if directory and evidence.get('directory') and evidence['directory'] != directory:
        return None, [check('source_identity', 'INVALID', '结构快照与能量的计算目录明确不对应，请重新核对来源。')]
    text = ((evidence.get('files') or {}).get('POSCAR') or {}).get('text')
    if not text:
        return None, []
    try:
        parsed = structure(text)
    except (ValueError, IndexError) as exc:
        severe = str(exc) in ('晶胞退化', '晶格不完整', '原子坐标不完整', '科学数值必须有限')
        return None, [check('structure_safety', 'INVALID' if severe else 'UNKNOWN', str(exc))]
    from structure_geometry import parse
    from structure_check import scan
    try:
        screening, _ = scan(parse(text), [True, True, True])
        bad = screening['severe_overlap_count']
        checks = [check('structure_safety', 'INVALID' if bad else 'AVAILABLE',
                        f'已有结构几何筛查：发现{bad}处严重原子重叠；筛查不等同结构优化验证')]
    except ValueError as exc:
        checks = [check('structure_safety', 'UNKNOWN', '几何筛查未完成：'+str(exc))]
    return parsed, checks


def input_data(result, project, task, selector, *, needs_energy=True):
    from adsorption_minimum import read_energy
    # An unresolved binding or expired explicit observation must not fall back.
    if result['status'] == 'AMBIGUOUS' or not result.get('task') or (
            selector.get('observation_id') and not result.get('frozen_observation')):
        return result
    item = read_energy(project, task, selector.get('observation_id'))
    data = result['data']
    for key, value in {'settings':{}, 'potentials':{}, 'hubbard':{}, 'kpoints':None,
                       'structure':None, 'charge':None}.items():
        data.setdefault(key, value)
    if data.get('energy_ev') is None:
        data.update(energy_ev=item['energy_ev'], energy_definition=item['energy_definition'])
    result['source'] = {'project_id':project['project_id'], 'task_id':task['task_id'],
                        **result.get('source', {}), 'energy_source':item['source']}
    result['source'].setdefault('directory', {'path':item['source'].get('directory')})
    result['source'].setdefault('checked_at', item['source'].get('observed_at'))
    result['checks'] += [check('record_quality', 'UNKNOWN', text) for text in item['warnings']]
    parsed, checks = structure_checks(item['row'])
    if task.get('task_type') == 'neb':
        for image in (item['row'].get('property_evidence') or {}).get('neb_images',[]):
            _, image_checks = structure_checks({'property_evidence':image.get('evidence') or {}})
            checks += [{**c,'detail':f'映像{image.get("label")}：'+c['detail']} for c in image_checks]
    if parsed and data['structure'] is None:
        data['structure'] = parsed
    result['checks'] += checks
    if needs_energy and data.get('energy_ev') is None:
        result['checks'].append(check('required_energy', 'MISSING',
                                      f'没有找到“{item["model_name"]}”的有限总能量，请同步结果或补充对应能量。'))
    result['preliminary_ready'] = (not needs_energy or data.get('energy_ev') is not None) and calculable(result['checks'], True)
    return result
