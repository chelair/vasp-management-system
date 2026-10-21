"""Bounded, deterministic geometry evidence; no filesystem, SSH, LLM or writes."""
from collections import Counter
from itertools import product, combinations
import math

from property_science import structure
from structure_analysis import _det3, _norm, _angle_deg

VERSION = 'structure.geometry.1'
MAX_ATOMS = 2000
MAX_IMAGES = 4096


def cartesian(frac, cell):
    return [sum(frac[i] * cell[i][j] for i in range(3)) for j in range(3)]


def reciprocal(cell):
    def cross(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    det = _det3(cell)
    return [[v / det for v in cross(cell[i], cell[j])] for i, j in ((1,2),(2,0),(0,1))]


def parse(text):
    lines = text.splitlines()
    try:
        counts = [int(x) for x in lines[6].split('#',1)[0].split('!',1)[0].split()]
    except (IndexError,ValueError):
        raise ValueError('需要完整VASP5结构及元素计数') from None
    # Bound counts before the shared parser can allocate constraint arrays.
    if not counts or any(x<=0 for x in counts) or not 1 <= sum(counts) <= MAX_ATOMS:
        raise ValueError(f'结构读取支持1至{MAX_ATOMS}个原子')
    parsed = structure(text)
    if not 1 <= len(parsed['atoms']) <= MAX_ATOMS:
        raise ValueError(f'结构读取支持1至{MAX_ATOMS}个原子')
    if any(abs(x) > 1e6 for pos in parsed['fractional'] for x in pos):
        raise ValueError('原子分数坐标超出可分析范围')
    cell = parsed['lattice']
    if any(not 1e-4 < _norm(v) < 1e5 for v in cell):
        raise ValueError('晶格长度超出可分析范围')
    parsed['reciprocal'] = reciprocal(cell)
    if max(_norm(v) for v in cell) * max(_norm(v) for v in parsed['reciprocal']) > 1e8:
        raise ValueError('晶胞接近退化，无法可靠计算周期几何')
    # Preserve individual fractional-axis constraints; the shared layout's fixed
    # boolean means any direction constrained, not that all directions are fixed.
    lines = text.splitlines()
    selective = lines[7].strip().lower().startswith('s')
    start = 9 if selective else 8
    flags = [line.split()[3:6] for line in lines[start:start+len(parsed['atoms'])]]
    if selective and any(len(f) != 3 or any(x.upper() not in ('T','F') for x in f) for f in flags):
        raise ValueError('Selective dynamics约束不完整')
    parsed['fixed_axes'] = [[x.upper() == 'F' for x in f] if selective else [False]*3 for f in flags]
    return parsed


def image_vectors(delta, cell, rec, radius, pbc, budget=None):
    bounds = []
    for i in range(3):
        bound = radius * _norm(rec[i]) + 1e-10
        bounds.append((math.ceil(-delta[i]-bound),math.floor(-delta[i]+bound)) if pbc[i] else (0,0))
    count = math.prod(max(0,hi-lo+1) for lo,hi in bounds)
    if budget is not None:
        budget[0] -= count
        if budget[0] < 0:
            raise ValueError('几何查询超过搜索预算，请减少中心原子或缩小半径')
    if count > MAX_IMAGES:
        raise ValueError('晶胞过度倾斜或截断半径过大，周期映像搜索超出上限；请缩小半径')
    for shift in product(*(range(lo,hi+1) for lo,hi in bounds)):
        vector = cartesian([delta[i]+shift[i] for i in range(3)], cell)
        distance = _norm(vector)
        if distance <= radius + 1e-9:
            yield distance, vector, list(shift)


def minimum_image(delta, cell, rec, pbc, budget=None):
    shift = [-round(delta[i]) if pbc[i] else 0 for i in range(3)]
    vector = cartesian([delta[i]+shift[i] for i in range(3)], cell)
    best = (_norm(vector), vector, shift)
    for candidate in image_vectors(delta, cell, rec, best[0], pbc, budget):
        if candidate[0] < best[0] - 1e-12:
            best = candidate
    return best


def cell_summary(cell):
    return {'vectors_angstrom': cell, 'lengths_angstrom': [round(_norm(v),6) for v in cell],
            'angles_degrees': [round(_angle_deg(cell[i],cell[j]),6) for i,j in ((1,2),(2,0),(0,1))],
            'volume_angstrom3': round(abs(_det3(cell)),6), 'basis': 'lattice_vectors_are_rows'}


def atom_record(parsed, index):
    return {'index':index+1, 'element':parsed['atoms'][index],
            'fractional': [round(x,8) for x in parsed['fractional'][index]],
            'cartesian_angstrom':[round(x,6) for x in cartesian(parsed['fractional'][index], parsed['lattice'])],
            'fixed_fractional_axes': parsed['fixed_axes'][index]}


def layers(parsed, axis, gap, pbc):
    idx = 'abc'.index(axis)
    height = 1 / _norm(parsed['reciprocal'][idx])
    points = sorted((pos[idx] % 1 if pbc[idx] else pos[idx], i) for i,pos in enumerate(parsed['fractional']))
    largest = None
    if pbc[idx]:
        gaps = [(points[(i+1)%len(points)][0] + (1 if i == len(points)-1 else 0) - p[0], i) for i,p in enumerate(points)]
        width, before = max(gaps)
        origin = points[(before+1)%len(points)][0]
        largest = {'width_angstrom':round(width*height,6), 'between_atom_indices':[points[before][1]+1,points[(before+1)%len(points)][1]+1]}
        points = sorted(((pos-origin) % 1, i) for pos,i in points)
    else:
        origin = 0
    groups = []
    for pos,index in points:
        if not groups or (pos-groups[-1][-1][0])*height > gap:
            groups.append([])
        groups[-1].append((pos,index))
    values = [{'layer':n+1,'atom_count':len(g),'composition':dict(Counter(parsed['atoms'][i] for _,i in g)),
               'atom_indices':[i+1 for _,i in g][:40], 'indices_truncated':len(g)>40,
               'normal_height_range_angstrom':[round(g[0][0]*height,6),round(g[-1][0]*height,6)]} for n,g in enumerate(groups)]
    return {'axis':axis,'normal':'reciprocal_plane_normal','plane_repeat_distance_angstrom':round(height,6),
            'gap_threshold_angstrom':gap,'fractional_origin':origin,'layer_count':len(groups),'layers':values[:24],
            'layers_truncated':len(values)>24, 'largest_atom_plane_gap':largest,
            'note':'按投影间隙分组是几何启发式；最大原子平面间隙未扣原子半径，不证明真空厚度或材料相/界面身份。'}


def summary(parsed, *, atom_offset=0, axis='c', layer_gap_angstrom=.75, pbc=(True,True,True)):
    n = len(parsed['atoms'])
    page = [atom_record(parsed,i) for i in range(atom_offset,min(n,atom_offset+24))]
    return {'schema_version':VERSION,'atom_count':n,'composition':parsed['composition'],
            'cell':cell_summary(parsed['lattice']),
            'constraints':{'partially_or_fully_fixed_atoms':sum(any(f) for f in parsed['fixed_axes']),
                           'fully_fixed_atoms':sum(all(f) for f in parsed['fixed_axes']), 'axes':'fractional_lattice_axes'},
            'layering':layers(parsed,axis,layer_gap_angstrom,pbc),'atoms':page,'atom_offset':atom_offset,
            'next_atom_offset':atom_offset+len(page) if atom_offset+len(page)<n else None,'pbc':list(pbc)}


def environment(parsed, indices, cutoff, pbc, neighbor_elements=None):
    n = len(parsed['atoms'])
    if any(i > n for i in indices):
        raise ValueError(f'原子编号超出范围（当前结构共{n}个原子）')
    environments = []
    budget = [2000000]
    for index in indices:
        center = parsed['fractional'][index-1]
        found = []
        for j,pos in enumerate(parsed['fractional']):
            if neighbor_elements and parsed['atoms'][j] not in neighbor_elements:
                continue
            delta = [pos[k]-center[k] for k in range(3)]
            for distance,vector,shift in image_vectors(delta,parsed['lattice'],parsed['reciprocal'],cutoff,pbc,budget):
                if j == index-1 and shift == [0,0,0]:
                    continue
                found.append((distance,j,shift,vector))
                if len(found)>20000:
                    raise ValueError('邻居映像过多，请缩小截断半径')
        found.sort(key=lambda x:(x[0],x[1],x[2]))
        angles = []
        for a,b in combinations(found[:6],2):
            if a[0] > 1e-8 and b[0] > 1e-8:
                angles.append({'neighbor_a':{'index':a[1]+1,'image_shift':a[2]},
                               'neighbor_b':{'index':b[1]+1,'image_shift':b[2]},
                               'angle_degrees':round(_angle_deg(a[3],b[3]),4)})
        environments.append({'center':atom_record(parsed,index-1),'geometric_neighbor_count':len(found),
            'neighbor_composition':dict(Counter(parsed['atoms'][x[1]] for x in found)),
            'neighbors':[{'index':j+1,'element':parsed['atoms'][j],'image_shift':shift,
                          'distance_angstrom':round(distance,6)} for distance,j,shift,_ in found[:16]],
            'neighbors_truncated':len(found)>16,'angles_nearest_six_neighbors':angles,
            'overlapping_atom_images':sum(x[0]<1e-8 for x in found)})
    return {'schema_version':VERSION,'cutoff_angstrom':cutoff,'pbc':list(pbc),'neighbor_elements':neighbor_elements,
            'environments':environments,'note':'邻居按声明半径和周期边界计算，包含同原子的非零周期映像；这是几何邻居数，不是已验证化学键、价态或成键配位。角度只列最近6个邻居。'}


def compare(reference, target, *, same_task, pbc, pairs):
    before, after = cell_summary(reference['lattice']), cell_summary(target['lattice'])
    result = {'schema_version':VERSION,'reference_cell':before,'target_cell':after,
              'reference_composition':reference['composition'],'target_composition':target['composition'],
              'cell_length_changes_angstrom':[round(b-a,6) for a,b in zip(before['lengths_angstrom'],after['lengths_angstrom'])],
              'volume_change_angstrom3':round(after['volume_angstrom3']-before['volume_angstrom3'],6),
              'pbc':list(pbc),'displacements':None,'pair_distances':[],'status':'PARTIAL','warnings':[]}
    if not same_task or reference['atoms'] != target['atoms']:
        result['warnings'].append('原子对应关系未确定：首版仅对同任务、同映像、元素顺序一致的结构计算位移/原子对变化；跨任务只比较晶胞和组成。')
        return result
    result['atom_mapping'] = {'basis':'same_task_same_image_same_element_order','verified':False,
        'note':'按POSCAR原编号对应；若同元素原子被重新排序，这一对应不成立，需另行核对。'}
    for i,j in pairs:
        if max(i,j)>len(reference['atoms']):
            raise ValueError('原子对编号超出结构范围')
        distances = []
        for parsed in (reference,target):
            delta = [parsed['fractional'][j-1][k]-parsed['fractional'][i-1][k] for k in range(3)]
            distances.append(minimum_image(delta,parsed['lattice'],parsed['reciprocal'],pbc)[0])
        result['pair_distances'].append({'atom_indices':[i,j],'before_angstrom':round(distances[0],6),
            'after_angstrom':round(distances[1],6),'change_angstrom':round(distances[1]-distances[0],6)})
    if any(abs(a-b)>1e-6 for va,vb in zip(reference['lattice'],target['lattice']) for a,b in zip(va,vb)):
        result['warnings'].append('晶胞发生变化；逐原子位移需要区分晶胞形变和内部弛豫，首版仅返回晶胞与指定原子对距离变化。')
        return result
    moved = []
    distances = []
    budget = [2000000]
    for i,(a,b) in enumerate(zip(reference['fractional'],target['fractional'])):
        distance,vector,shift = minimum_image([b[k]-a[k] for k in range(3)],reference['lattice'],reference['reciprocal'],pbc,budget)
        distances.append(distance)
        moved.append({'index':i+1,'element':reference['atoms'][i],'distance_angstrom':round(distance,6),
                      'vector_angstrom':[round(x,6) for x in vector],'target_image_shift':shift})
    values = distances
    result.update(status='AVAILABLE',displacements={'max_angstrom':round(max(values),6),'mean_angstrom':round(sum(values)/len(values),6),
        'rms_angstrom':round(math.sqrt(sum(x*x for x in values)/len(values)),6),
        'largest_movers':sorted(moved,key=lambda x:-x['distance_angstrom'])[:16],
        'note':'按周期最短位移，未移除整体平移/旋转；同元素顺序对应属于假设，不能单独证明结构关系。'})
    return result
