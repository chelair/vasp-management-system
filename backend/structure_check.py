"""Ordered structure review: geometry first, local changes next, settings last.

Thresholds are screening heuristics, not a phase classifier or a bonding model.
"""
from collections import Counter, defaultdict
import math
import re
from statistics import median

import structure_geometry as g

# Single-bond covalent radii (Å), Cordero et al., Dalton Trans. 2008, 2832.
# Deliberately limited: unknown elements are reported, never silently assigned.
RADII = dict(H=.31, Li=1.28, B=.84, C=.76, N=.71, O=.66, F=.57,
             Na=1.66, Mg=1.41, Al=1.21, Si=1.11, P=1.07, S=1.05, Cl=1.02,
             K=2.03, Ca=1.76, Ti=1.60, V=1.53, Cr=1.39, Mn=1.39, Fe=1.32,
             Co=1.26, Ni=1.24, Cu=1.32, Zn=1.22, Ga=1.22, Ge=1.20, In=1.42, Sn=1.39)


def scan(parsed, pbc):
    n = len(parsed['atoms'])
    contacts, minima, graph = [], {}, [Counter() for _ in range(n)]
    suspect_count = severe_count = 0
    budget = [2000000]
    for i in range(n):
        for j in range(i, n):
            a, b = parsed['atoms'][i], parsed['atoms'][j]
            radii = RADII.get(a, 0) + RADII.get(b, 0) if a in RADII and b in RADII else None
            cutoff = 1.25 * radii if radii else .5
            delta = [parsed['fractional'][j][k] - parsed['fractional'][i][k] for k in range(3)]
            for distance, _, shift in g.image_vectors(delta, parsed['lattice'], parsed['reciprocal'], cutoff, pbc, budget):
                if i == j and tuple(shift) <= (0, 0, 0):
                    continue
                key = '-'.join(sorted((a, b)))
                if key not in minima or distance < minima[key]['distance_angstrom']:
                    minima[key] = {'elements':key, 'atom_indices':[i+1, j+1], 'distance_angstrom':distance}
                graph[i][j] += 1
                graph[j][i] += 1
                severe = distance < .5 or (radii is not None and distance < .5 * radii)
                suspect = severe or (radii is not None and distance < .8 * radii)
                if suspect:
                    suspect_count += 1
                    severe_count += int(severe)
                    contacts.append({'atom_indices':[i+1, j+1], 'elements':[a, b],
                                     'distance_angstrom':round(distance, 6), 'image_shift':shift,
                                     'screening_limit_angstrom':round(max(.5, .8*radii) if radii else .5, 6),
                                     'severity':'severe_overlap' if severe else 'short_contact_to_review'})
                    contacts = sorted(contacts, key=lambda x:x['distance_angstrom'])[:16]
    layering = g.layers(parsed, 'c', .75, pbc)
    pair_minima = sorted(minima.values(),key=lambda row:row['distance_angstrom'])
    result = {'atom_count_scanned':n, 'suspect_contact_count':suspect_count, 'severe_overlap_count':severe_count,
              'short_contacts':contacts, 'contacts_truncated':suspect_count > 16,
              'pair_minima_within_screening_radius':[{**row, 'distance_angstrom':round(row['distance_angstrom'],6)} for row in pair_minima[:32]],
              'pair_minima_truncated':len(pair_minima)>32,
              'constraints':{'partially_or_fully_fixed_atoms':sum(any(f) for f in parsed['fixed_axes']),
                             'fully_fixed_atoms':sum(all(f) for f in parsed['fixed_axes'])},
              'c_normal_geometry':{key:layering[key] for key in ('axis','plane_repeat_distance_angstrom','largest_atom_plane_gap','note')},
              'unsupported_radius_elements':sorted(set(parsed['atoms'])-RADII.keys()),
              'criteria':{'short_contact':'d < 0.8*(r_cov_i+r_cov_j)',
                          'severe_overlap':'d < 0.5 Å or d < 0.5*(r_cov_i+r_cov_j)',
                          'geometric_neighbor':'d <= 1.25*(r_cov_i+r_cov_j)',
                          'radii_source':'Cordero et al. Dalton Trans. 2008, 2832; single-bond covalent radii',
                          'note':'离子晶体/金属/特殊化学环境需具体复核；不是通用键长标准。未知半径只检查0.5Å极短接触，不能判为合理。'},
              'cell':g.cell_summary(parsed['lattice'])}
    return result, graph


def compare(reference, target, ref_graph, target_graph, pbc, same_task):
    result = g.compare(reference, target, same_task=same_task, pbc=pbc, pairs=[])
    result['cell_volume_fraction_change'] = round(result['volume_change_angstrom3']/result['reference_cell']['volume_angstrom3'],6)
    result['cell_angle_changes_degrees'] = [round(b-a,6) for a,b in zip(result['reference_cell']['angles_degrees'],result['target_cell']['angles_degrees'])]
    if reference['atoms'] != target['atoms'] or not same_task:
        return result
    per_element = defaultdict(lambda: {'atoms':0, 'changed_neighbor_atoms':0, 'lost_neighbors':0, 'gained_neighbors':0})
    examples = []
    for i, element in enumerate(reference['atoms']):
        lost = sum((ref_graph[i]-target_graph[i]).values())
        gained = sum((target_graph[i]-ref_graph[i]).values())
        row = per_element[element]
        row['atoms'] += 1
        row['changed_neighbor_atoms'] += int(bool(lost or gained))
        row['lost_neighbors'] += lost
        row['gained_neighbors'] += gained
        if lost or gained:
            examples.append({'index':i+1, 'element':element, 'before_count':sum(ref_graph[i].values()),
                             'after_count':sum(target_graph[i].values()), 'lost':lost, 'gained':gained})
    result['geometric_network_changes'] = {'by_element':dict(per_element),
        'largest_changes':sorted(examples, key=lambda x:-(x['lost']+x['gained']))[:16],
        'changed_atom_count':len(examples), 'examples_truncated':len(examples)>16,
        'note':'覆盖全部原子；几何半径内邻居身份/数量变化，不等于断键、价态或相变。阈值附近的距离穿越可造成变化。'}
    if not result['displacements']:
        return result
    vectors = [g.minimum_image([b[k]-a[k] for k in range(3)], target['lattice'], target['reciprocal'], pbc)[1]
               for a,b in zip(reference['fractional'], target['fractional'])]
    translation = [median(v[k] for v in vectors) for k in range(3)]
    frac_shift = [sum(translation[k]*rec[k] for k in range(3)) for rec in target['reciprocal']]
    moved = []
    for i,(a,b) in enumerate(zip(reference['fractional'],target['fractional'])):
        distance = g.minimum_image([b[k]-a[k]-frac_shift[k] for k in range(3)],target['lattice'],target['reciprocal'],pbc)[0]
        moved.append({'index':i+1, 'element':target['atoms'][i], 'distance_angstrom':round(distance,6)})
    result['translation_adjusted_displacements'] = {
        'estimated_translation_angstrom':[round(x,6) for x in translation],
        'max_angstrom':max(row['distance_angstrom'] for row in moved),
        'atoms_over_1_angstrom':sum(row['distance_angstrom']>1 for row in moved),
        'by_element':{el:{'max_angstrom':max(row['distance_angstrom'] for row in moved if row['element']==el),
                          'mean_angstrom':round(sum(row['distance_angstrom'] for row in moved if row['element']==el)/target['atoms'].count(el),6)} for el in target['species']},
        'largest_movers':sorted(moved,key=lambda x:-x['distance_angstrom'])[:16],
        'note':'移除周期最短位移向量的逐分量中位整体平移估计；未做旋转/刚体配准。1Å仅筛查阈值，不能据此判变性。'}
    return result


def potential_elements(titles):
    elements = []
    for title in titles:
        parts = title.split()
        match = re.fullmatch(r'([A-Z][a-z]?)(?:_[A-Za-z0-9]+)*', parts[1]) if len(parts)>1 else None
        if not match:
            return None
        elements.append(match[1])
    return elements or None


def identity(parsed, evidence):
    files = evidence['files']
    pot = potential_elements(files.get('POTCAR',{}).get('titles',[]))
    out = files.get('OUTCAR',{})
    runtime = potential_elements(out.get('potential_titles',[]))
    counts = out.get('ions_per_type')
    n = len(parsed['species'])
    # VASP commonly echoes the whole POTCAR sequence twice in the header.
    if runtime and len(runtime) == 2*n and runtime[:n] == runtime[n:]:
        runtime = runtime[:n]
    def status(value, expected):
        return 'UNKNOWN' if value is None else 'CONSISTENT' if value == expected else 'MISMATCH'
    return {'priority':'basic_cross_check', 'declared_species':parsed['species'], 'declared_counts':parsed['counts'],
            'current_potcar_species':pot, 'potcar_order_status':status(pot,parsed['species']),
            'outcar_runtime_species':runtime, 'runtime_order_status':status(runtime,parsed['species']),
            'outcar_ions_per_type':counts, 'runtime_counts_status':status(counts,parsed['counts']),
            'outcar_nelect':out.get('nelect'),
            'note':'基础核对项，不是默认检查主线。发生不一致时，几何中的元素仅为结构文件标签，不能解释为目标体系的物理重构。相同不证明同次计算。'}


def check(target, reference, evidence, pbc, same_task=False):
    current, graph = scan(target, pbc)
    original, comparison = None, None
    if reference is not None:
        original, ref_graph = scan(reference, pbc)
        comparison = compare(reference, target, ref_graph, graph, pbc, same_task)
    basic = identity(target, evidence)
    mismatch = any(basic[key]=='MISMATCH' for key in ('potcar_order_status','runtime_order_status','runtime_counts_status'))
    unknown = any(basic[key]=='UNKNOWN' for key in ('potcar_order_status','runtime_order_status','runtime_counts_status'))
    changed = (comparison or {}).get('geometric_network_changes',{}).get('changed_atom_count',0)
    motion = (comparison or {}).get('translation_adjusted_displacements',{}).get('atoms_over_1_angstrom',0)
    composition_changed = bool(reference and target['composition'] != reference['composition'])
    cell_changed = bool(comparison and (abs(comparison['cell_volume_fraction_change'])>.05 or
                        any(abs(x)>5 for x in comparison['cell_angle_changes_degrees'])))
    geometry_status = 'REVIEW_REQUIRED' if current['suspect_contact_count'] or (original or {}).get('suspect_contact_count') or changed or motion or composition_changed or cell_changed else 'NO_SCREENING_FLAG'
    settings = evidence['files'].get('INCAR',{}).get('settings',{})
    findings = []
    if composition_changed:
        findings.append('前后结构组成不同：先确认是否比较了同一优化体系，不能直接解释为优化位移或相变。')
    if cell_changed:
        findings.append('晶胞体积变化超过5%或晶格角变化超过5°（仅筛查阈值）；核对变胞设置和预期应变，不能仅凭阈值判结构损坏。')
    if (original or {}).get('suspect_contact_count'):
        findings.append('先复核初始建模中的短接触、位点占据、层间拼接和约束，区分建模问题与优化产生的变化。')
    if current['suspect_contact_count']:
        findings.append('复核目标结构的过短接触；结合成分和化学环境判断是否不合理。')
    if changed or motion:
        findings.append('优化前后出现几何邻接/内部位移变化；先定位发生变化的元素和区域，再判断是预期弛豫、界面重构还是非预期破坏。')
    if reference is None:
        findings.append('缺少明确的初始结构，无法检查累计重构/变性；续算目录POSCAR只能代表该段起点，累计变化需MAIN或真正初始构型。')
    if mismatch:
        findings.append('基础核对发现元素/赝势或运行原子计数不一致；在澄清来源前，不把几何变化解释为目标材料的物理行为。')
    return {'schema_version':'structure.check.1', 'review_order':['overall_structure_and_transformation','local_coordination_and_interface','calculation_settings'],
            'overall_structure':{'status':geometry_status, 'initial':original, 'target':current,
                'comparison':comparison, 'phase_or_denaturation_verdict':'NOT_DETERMINED',
                'review_questions':['是否符合目标材料/晶相和晶面，原子占位、层间拼接、应变、周期边界与固定层是否合理？',
                    '优化后主要骨架/配位多面体和界面是否保持，有无非预期穿层、溶出、解离或成团？这些变化是否符合研究目标？'],
                'not_automatically_verified':['目标物相/价态与化学稳定性','界面区域身份与层归属','完整续算过程中的变性发生阶段'],
                'screening_complete':reference is not None and not current['unsupported_radius_elements'] and
                    not (original or {}).get('unsupported_radius_elements') and bool(comparison and comparison.get('status')=='AVAILABLE'),
                'note':'筛查没有发现异常不等于结构合理或未变性。几何不自动判相；须结合预期构型、完整优化过程和电子态。'},
            'basic_identity_cross_check':basic,
            'interpretation_limits':{'target_chemistry_interpretation':'WITHHOLD' if mismatch else 'UNVERIFIED' if unknown else 'LABELS_CONSISTENT_ONLY',
                'co_run_verified':False, 'atom_mapping_verified':False,
                'notes':['未扫描完整续算历史，不能证明每一段的原子顺序连续。',
                         '元素标签/计数一致也不能排除同元素原子被重排。']},
            'local_review':{'priority':2, 'next_focus':['变化最大的配位骨架、界面原子和迁移/脱离的原子；覆盖全部原子的筛查结果，不能只抽每种元素第一个原子。',
                '结合项目目标检查局部配位/键角、界面接触和层间距；有无解离、非预期成团或跨层迁移。用局部环境工具声明半径后细查。',
                '若怀疑氧释放等反应，需专门核对对应原子对、环境和电子态，不能把位移或失配位直接称作反应。']},
            'calculation_settings':{'priority':3, 'current_incar_settings':settings,
                'convergence_verdict':'NOT_DETERMINED',
                'guidance':['结构主线判断之后，再核对真实电子/离子收敛、力和能量趋势、固定约束、优化算法与步长；正常结束/达到NSW不等于收敛。',
                    '按目标精度检查截断能、k点、EDIFF/EDIFFG；不凭单份INCAR建议盲目加大POTIM或放宽收敛。',
                    '外电场/偶极、磁性、DFT+U、SOC、电荷态若改变目标电子态或结构稳定性，应提升到物理模型层面处理；MAGMOM初值不等于最终磁矩。'],
                'evidence_gaps':['未读取KPOINTS或完整收敛曲线，未判定最终磁态；需要时用原参数/巡检工具补证。']},
            'recommended_focus':findings or ['结合预期结构和项目目标复核主要骨架/界面；当前筛查不足以断言结构合理或未变性。'],
            'pbc':list(pbc), 'companion_evidence':evidence}
