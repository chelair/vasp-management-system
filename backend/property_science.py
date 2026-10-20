"""R3 pure evidence validation. No LLM, filesystem writes, SSH or job actions."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re

from input_state import parse_incar_text
from batch_check import parse_poscar_layout

VERSION = 'r3.1.0'
NUMBER = r'[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?'


def number(value):
    if isinstance(value, bool):
        raise ValueError('布尔值不能作为科学数值')
    result = float(str(value).replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError('科学数值必须有限')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def check(name, status, detail):
    return {'check': name, 'status': status, 'detail': detail}


def structure(text):
    layout = parse_poscar_layout(text)
    if not layout or not layout['species'] or any(n <= 0 for n in layout['counts']):
        raise ValueError('需要完整VASP5结构及元素数目')
    if len(set(layout['species'])) != len(layout['species']):
        raise ValueError('首版不合并重复元素物种；需要每个赝势/U分组的独立身份')
    lines = text.splitlines()
    scale = number(lines[1])
    if scale <= 0:
        raise ValueError('首版只验证正的单一缩放因子')
    lattice = [[number(x)*scale for x in line.split()[:3]] for line in lines[2:5]]
    if any(len(v) != 3 for v in lattice):
        raise ValueError('晶格不完整')
    from structure_analysis import _det3
    det = _det3(lattice)
    if abs(det) < 1e-9:
        raise ValueError('晶胞退化')
    index = 7 + int(lines[7].strip().lower().startswith('s'))
    mode = lines[index].strip().lower()
    if mode[:1] not in ('d', 'c', 'k'):
        raise ValueError('坐标模式无效')
    coords = [[number(x) for x in line.split()[:3]] for line in lines[index+1:index+1+layout['n_atoms']]]
    if len(coords) != layout['n_atoms'] or any(len(c) != 3 for c in coords):
        raise ValueError('原子坐标不完整')
    if mode[0] != 'd':
        # inverse of lattice row basis: fractional = cartesian * inverse(lattice)
        a, b, c = lattice
        cross = lambda v,w: [v[1]*w[2]-v[2]*w[1], v[2]*w[0]-v[0]*w[2], v[0]*w[1]-v[1]*w[0]]
        reciprocal = [cross(b,c), cross(c,a), cross(a,b)]
        coords = [[sum(v[j]*scale*r[j] for j in range(3))/det for r in reciprocal] for v in coords]
    atoms = [el for el,n in zip(layout['species'], layout['counts']) for _ in range(n)]
    return {'lattice': lattice, 'composition': dict(Counter(atoms)), 'species': layout['species'],
            'counts': layout['counts'], 'atoms': atoms, 'fractional': coords, 'fixed': layout['fixed']}


def canonical(value):
    text = str(value).strip()
    if text.lower() in ('.true.', 'true', 't'): return True
    if text.lower() in ('.false.', 'false', 'f'): return False
    try: return number(text)
    except (ValueError, TypeError): return ' '.join(text.upper().split())


DEFAULTS = {'LDAU': False, 'LHFCALC': False, 'METAGGA': 'NONE', 'IVDW': 0,
            'ISPIN': 1, 'LSORBIT': False, 'LASPH': False, 'ISMEAR': 1, 'SIGMA': 0.2,
            'LDAUTYPE': 2, 'LMAXMIX': 2, 'AEXX': 0.25, 'HFSCREEN': 0,
            'AGGAX': 1, 'AGGAC': 1, 'ALDAC': 1, 'LUSE_VDW': False,
            'GGA_COMPAT': True, 'LNONCOLLINEAR': False, 'LREAL': False,
            'EFIELD': 0, 'LDIPOL': False, 'IDIPOL': 0} 
GLOBAL_KEYS = ('ENCUT', 'GGA', *DEFAULTS)
VECTOR_DEFAULTS = {'DIPOL':[0.5,0.5,0.5], 'SAXIS':[0,0,1], 'EFIELD_PEAD':[0,0,0]}


def normalize(evidence, row, *, neb_image=False):
    """Only consumes one raw observation. Never completes it from the task DB."""
    checks = []
    data = {'energy_ev': None, 'energy_definition': 'VASP.free_energy.TOTEN', 'structure': None,
            'settings': {}, 'potentials': {}, 'hubbard': {}, 'charge': None, 'kpoints': None}
    if evidence.get('schema_version') != 'r3.evidence.1':
        checks.append(check('evidence_schema','UNKNOWN','缺少R3科学快照或版本不支持'))
    files = evidence.get('files') or {}
    for name in ('POSCAR', 'INCAR', 'KPOINTS', 'OUTCAR', 'OSZICAR'):
        f = files.get(name) or {}
        state = 'MISSING' if f.get('missing') or not f else 'INVALID' if f.get('error') else 'INCOMPLETE' if not f.get('stable') else 'AVAILABLE'
        checks.append(check(name, state, f.get('error') or ('同一目录冻结采样' if state == 'AVAILABLE' else '文件缺失或采样不稳定')))
    if any(c['status'] != 'AVAILABLE' for c in checks):
        return data, checks
    try:
        pos = data['structure'] = structure(files['POSCAR']['text'])
        incar = parse_incar_text(files['INCAR']['text'])
        out = files['OUTCAR']['text']
        runtime = {m[1]: m[2].strip() for m in re.finditer(r'\b([A-Z][A-Z0-9_]*)\s*=\s*([^;\n]+)', out)}
        def scalar(key):
            values = (runtime.get(key) or '').split()
            return canonical(values[0]) if values else None
        pot = evidence.get('potcar') or {}
        datasets = pot.get('datasets') or []
        valid_pot = pot.get('stable') and len(datasets) == len(pos['species']) and all(d.get('sha256') and d.get('title') and d.get('zval') is not None for d in datasets)
        checks.append(check('POTCAR', 'AVAILABLE' if valid_pot else 'UNKNOWN', '逐元素赝势哈希、TITEL及ZVAL；缺失时不能验证兼容性'))
        if valid_pot:
            data['potentials'] = {el: d['sha256'] for el,d in zip(pos['species'], datasets)}
            pot_names = [re.search(r'\s([A-Z][a-z]?)(?:_|\s|$)', d['title']) for d in datasets]
            checks.append(check('potcar_elements', 'AVAILABLE' if all(m and m[1] == el for m,el in zip(pot_names,pos['species'])) else 'INVALID', '赝势元素顺序与结构一致'))
            neutral = sum(n*number(d['zval']) for n,d in zip(pos['counts'], datasets))
            nelect = scalar('NELECT')
            data['charge'] = round(neutral-nelect, 8) if type(nelect) in (int,float) else None
        checks.append(check('charge_state', 'UNKNOWN' if data['charge'] is None else 'AVAILABLE' if abs(data['charge']) < 1e-6 else 'INVALID',
                            'NELECT与POTCAR价电子数核对；带电缺陷需要电荷态、费米能级、带边、势对齐及有限尺寸修正'))
        for key in GLOBAL_KEYS:
            declared = canonical(incar[key]) if key in incar else DEFAULTS.get(key)
            actual = scalar(key)
            if key == 'GGA' and actual is None and valid_pot and all('PAW_PBE' in d['title'] for d in datasets):
                actual = 'PE'
            data['settings'][key] = actual if actual is not None else declared
            # Explicit method settings must be echoed by OUTCAR, defaults have named VASP semantics.
            if key in incar or key in ('ENCUT', 'GGA'):
                checks.append(check('runtime.'+key, 'UNKNOWN' if actual is None else 'INVALID' if declared is not None and actual != declared else 'AVAILABLE', '输入参数与OUTCAR运行时回显核对'))
        data['runtime_accuracy'] = {}
        for key in ('EDIFF','NELM','NSW','EDIFFG','IBRION','ISIF'):
            actual = scalar(key)
            data['runtime_accuracy'][key] = actual
            if key in incar:
                checks.append(check('runtime.'+key,'UNKNOWN' if actual is None else 'AVAILABLE' if actual == canonical(incar[key]) else 'INVALID','收敛/优化参数与运行时回显一致，不能把后写入输入当运行参数'))
        for key,default in VECTOR_DEFAULTS.items():
            actual = [number(v) for v in runtime[key].split()[:3]] if key in runtime else None
            declared = [number(v) for v in incar[key].split()] if key in incar else None
            data['settings'][key] = actual if actual is not None else default
            if declared is not None:
                checks.append(check('runtime.'+key,'AVAILABLE' if actual == declared and len(actual)==3 else 'UNKNOWN','完整三分量运行时参数核对'))
        if data['settings']['LDAU']:

            for key in ('LDAUL','LDAUU','LDAUJ'):
                def array(value):
                    parts = []
                    for token in str(value or '').split():
                        if '*' in token:
                            repeat, v = token.split('*',1)
                            if not repeat.isdigit() or not 1 <= int(repeat) <= 100: raise ValueError('U数组重复数无效')
                            parts.extend([number(v)]*int(repeat))
                        else: parts.append(number(token))
                    return parts
                expected = array(incar.get(key))
                actual = array(runtime.get(key))
                good = len(actual) == len(pos['species']) and actual == expected
                checks.append(check('runtime.'+key, 'AVAILABLE' if good else 'UNKNOWN', '逐元素完整U参数，不能只比较首值'))
                data['hubbard'][key] = dict(zip(pos['species'], actual))
        kp = files['KPOINTS']['text'].splitlines()
        if len(kp) < 5 or kp[1].strip() != '0' or kp[2].strip().lower()[:1] not in ('g','m'):
            raise ValueError('首版只验证自动Gamma/Monkhorst网格')
        mesh = [int(v) for v in kp[3].split()]
        shift = [number(v) for v in kp[4].split()]
        if len(mesh) != 3 or any(v <= 0 for v in mesh) or len(shift) != 3: raise ValueError('KPOINTS网格/位移无效')
        data['kpoints'] = {'mode': kp[2].strip().lower()[0], 'mesh': mesh, 'shift': shift}
        runtime_titles = [m.strip() for m in re.findall(r'POTCAR:\s*([^\n]+)', out)]
        checks.append(check('runtime.POTCAR', 'AVAILABLE' if valid_pot and runtime_titles[:len(datasets)] == [d['title'] for d in datasets] else 'UNKNOWN', '运行时POTCAR标题与捕获的赝势数据集一致；哈希覆盖输入数据集'))
        grid = re.search(r'generate k-points for:\s*(\d+)\s+(\d+)\s+(\d+)', out, re.I)
        shift_match = re.search(r'shift:\s*('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')', out, re.I)
        checks.append(check('runtime.kpoints_shift','AVAILABLE' if shift_match and all(abs(number(x)-v)<1e-8 for x,v in zip(shift_match.groups(),shift)) else 'UNKNOWN','运行时k点位移与输入核对'))
        checks.append(check('runtime.kpoints', 'AVAILABLE' if grid and list(map(int,grid.groups())) == mesh else 'UNKNOWN', 'OUTCAR生成网格与KPOINTS核对，保存完整网格模式/位移用于比较'))
        # All inputs must predate the observed output; later drafts cannot be used as run inputs.
        good_order = all(files[n]['mtime_ns'] <= files['OUTCAR']['mtime_ns'] for n in ('POSCAR','INCAR','KPOINTS')) and pot.get('mtime_ns', math.inf) <= files['OUTCAR']['mtime_ns']
        checks.append(check('input_output_order', 'AVAILABLE' if good_order else 'INVALID', '输入修改不得晚于输出；不把新草稿当已执行参数'))
        energies = re.findall(r'free\s+energy\s+TOTEN\s*=\s*('+NUMBER+')', out)
        data['energy_ev'] = number(energies[-1]) if energies else None
        osz = files['OSZICAR']['text'].split('@@R3_TAIL@@')[-1]
        ionic = list(re.finditer(r'^\s*(\d+)\s+F=\s*('+NUMBER+r').*?E0=\s*('+NUMBER+r')[^\n]*', osz, re.M))
        electronic = None
        if ionic:
            last = ionic[-1]
            segment = osz[ionic[-2].end():last.start()] if len(ionic)>1 else osz[:last.start()]
            scf = re.findall(r'^\s*(?:DAV|RMM|CG|DMP):\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)', segment, re.M)
            ediff, nelm = scalar('EDIFF'), scalar('NELM')
            if scf and type(ediff) in (int,float) and type(nelm) in (int,float):
                electronic = not osz[last.end():].strip() and int(scf[-1][0]) < nelm and abs(number(scf[-1][2])) < ediff and abs(number(scf[-1][3])) < ediff
            consistent = data['energy_ev'] is not None and abs(number(last[2])-data['energy_ev']) < 1e-5
        else: consistent = False
        checks.append(check('energy', 'MISSING' if data['energy_ev'] is None else 'AVAILABLE' if consistent else 'INVALID', 'OUTCAR最后TOTEN与OSZICAR最后完整离子步F一致；不混用E0'))
        observed = row.get('last_energy')
        if not neb_image and observed is not None:
            checks.append(check('observation_energy','AVAILABLE' if data['energy_ev'] is not None and abs(number(observed)-data['energy_ev'])<1e-5 else 'INVALID','观测总能量与同次输出采样一致'))
        checks.append(check('electronic_convergence', 'UNKNOWN' if electronic is None else 'AVAILABLE' if electronic else 'INCOMPLETE', '最后电子周期dE/dε小于EDIFF且未耗尽NELM'))
        ionic_ok = row.get('force_converged') is True and ('reached required accuracy' in out or neb_image)
        # Static total energies have no ionic minimization; record it as an unresolved geometry condition.
        data['geometry_state'] = 'ionic_converged' if ionic_ok else 'fixed_geometry_without_relaxation_verification'
        checks.append(check('ionic_convergence', 'AVAILABLE' if ionic_ok or scalar('NSW') == 0 and row.get('force_converged') is not False else 'INCOMPLETE' if row.get('force_converged') is False else 'UNKNOWN', '离子优化须明确收敛；NSW=0仅为给定固定几何的电子能，不证明结构已经弛豫'))
        checks.append(check('normal_exit', 'AVAILABLE' if 'General timing and accounting' in out else 'INCOMPLETE', 'VASP正常结束独立于科学收敛'))
        if any(marker in out for marker in ('VERY BAD NEWS','ZBRENT:','BRMIX:')):
            checks.append(check('fatal_errors','INVALID','OUTCAR存在严重错误'))
        if (row.get('precision') or {}).get('ok') is False:
            checks.append(check('numerical_precision', 'INVALID', '已有精度检查失败：'+str((row.get('precision') or {}).get('issues') or [])))
    except (ValueError, TypeError, KeyError, IndexError, StopIteration) as exc:
        checks.append(check('parse', 'INVALID', str(exc)))
    return data, checks


def compatibility(inputs, *, same_composition=False, same_cell=False):
    checks = []
    if len(inputs) < 2: return checks
    first = inputs[0]
    for other in inputs[1:]:
        for key in (*GLOBAL_KEYS,*VECTOR_DEFAULTS):
            a,b = first['settings'].get(key),other['settings'].get(key)
            checks.append(check('compatibility.'+key, 'UNKNOWN' if a is None or b is None else 'AVAILABLE' if a == b else 'INVALID', f'{key}: {a} / {b}'))
        checks.append(check('compatibility.energy_definition', 'AVAILABLE' if first['energy_definition'] == other['energy_definition'] else 'INVALID', '统一TOTEN自由能定义'))
        checks.append(check('compatibility.kpoints', 'UNKNOWN' if first['kpoints'] is None or other['kpoints'] is None else 'AVAILABLE' if first['kpoints'] == other['kpoints'] else 'INVALID', '首版要求相同网格、模式与位移；不推测网格等效性'))
        common = first['potentials'].keys() & other['potentials'].keys()
        checks.append(check('compatibility.POTCAR', 'UNKNOWN' if not common else 'AVAILABLE' if all(first['potentials'][el] == other['potentials'][el] for el in common) else 'INVALID', '按共同元素比较POTCAR数据集哈希'))
        for key in ('LDAUL','LDAUU','LDAUJ'):
            if first['settings'].get('LDAU'):
                a,b = first['hubbard'].get(key,{}),other['hubbard'].get(key,{})
                checks.append(check('compatibility.'+key, 'AVAILABLE' if all(el in a and el in b and a[el] == b[el] for el in common) else 'INVALID', '按元素核对U设置'))
        a,b = first.get('structure'),other.get('structure')
        if same_composition:
            checks.append(check('composition', 'UNKNOWN' if not a or not b else 'AVAILABLE' if a['composition'] == b['composition'] else 'INVALID', '相对总能量要求相同组成'))
        if same_cell:
            checks.append(check('cell', 'UNKNOWN' if not a or not b else 'AVAILABLE' if cell_equal(a,b) else 'INVALID', '晶胞各分量容差1e-5Å'))
    return checks


def cell_equal(a,b):
    return all(abs(x-y) <= 1e-5 for va,vb in zip(a['lattice'],b['lattice']) for x,y in zip(va,vb))


def vacancy(pristine, defect, removed_index=None):
    a,b = pristine.get('structure'),defect.get('structure')
    if not a or not b: return [check('single_oxygen_vacancy', 'UNKNOWN', '缺少绑定到能量观测的结构')], None
    delta = Counter(a['composition']); delta.subtract(b['composition'])
    if {el:n for el,n in delta.items() if n} != {'O':1}:
        return [check('single_oxygen_vacancy', 'INVALID', '组成差必须恰好只移除1个O')], None
    checks = compatibility([pristine,defect], same_cell=True)
    def same_atom(i,j):
        if a['atoms'][i] != b['atoms'][j] or a['fixed'][i] != b['fixed'][j]: return False
        d = [x-y-round(x-y) for x,y in zip(a['fractional'][i], b['fractional'][j])]
        cart = [sum(d[k]*a['lattice'][k][v] for k in range(3)) for v in range(3)]
        return math.sqrt(sum(v*v for v in cart)) <= 1e-4
    # Preserve atom order and verify every retained input atom; relaxation in CONTCAR is not used as an input correspondence.
    sites = [i+1 for i,el in enumerate(a['atoms']) if el == 'O' and
             all(same_atom(k,j) for j,k in enumerate(x for x in range(len(a['atoms'])) if x != i))]
    if removed_index is not None:
        sites = [i for i in sites if i == removed_index]
    state = 'AVAILABLE' if len(sites) == 1 else 'AMBIGUOUS' if len(sites)>1 else 'UNKNOWN'
    site = {'removed_oxygen_index':sites[0], 'fractional':a['fractional'][sites[0]-1]} if len(sites)==1 else None
    checks.append(check('vacancy_site', state, '输入结构按序逐原子核对，容差1e-4Å；候选位点：'+str(sites)+'。若重新排序/重建/预弛豫，需补可靠映射证据，名称不构成关系。'))
    return checks, site
