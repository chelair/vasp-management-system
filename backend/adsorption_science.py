"""Neutral single-adsorbate electronic energies: pure checks, no file/HPC access.

A surface relationship is verified on captured *input* atoms. Relaxed/reordered
substrates need a future explicit mapping adapter; names never prove a relation.
"""
from collections import Counter
import math
from property_science import check,cell_equal,compatibility

VERSION='adsorption.1.1.0'


def relationship(complex_data,surface_data,adsorbate_data):
    a,b,m=[d.get('structure') for d in (complex_data,surface_data,adsorbate_data)]
    if not all((a,b,m)):return [check('adsorption_relation','UNKNOWN','需要复合体系、洁净表面、一个吸附物的同次输入结构')],None
    balanced=Counter(a['composition']) == Counter(b['composition'])+Counter(m['composition'])
    same_cell=cell_equal(a,b)
    checks=[check('stoichiometry','AVAILABLE' if balanced else 'INVALID','复合体系组成必须等于洁净表面加一个完整吸附物参考；不隐式使用分数分子或多个吸附物'),
            check('adsorption_cell','AVAILABLE' if same_cell else 'INVALID','复合体系与洁净表面晶胞各分量容差1e-5Å')]
    if not balanced or not same_cell:return checks,None
    if len(a['atoms'])>2000:return checks+[check('adsorption_relation','UNKNOWN','输入原子超过2000个的首版映射预算，需要专门映射证据')],None
    # A unique order-preserving embedding is required. Count paths capped at two;
    # duplicate coincident atoms must not be silently assigned to the substrate.
    def matches(i,j):
        if a['atoms'][i]!=b['atoms'][j] or a['fixed'][i]!=b['fixed'][j]:return False
        delta=[x-y-round(x-y) for x,y in zip(a['fractional'][i],b['fractional'][j])]
        return math.sqrt(sum(sum(delta[k]*a['lattice'][k][v] for k in range(3))**2 for v in range(3)))<=1e-4
    counts=[1]+[0]*len(b['atoms']);mapping=[None]*(len(b['atoms'])+1);mapping[0]=[]
    for i in range(len(a['atoms'])):
        for j in range(min(i,len(b['atoms'])-1),-1,-1):
            if counts[j] and matches(i,j):
                if counts[j+1]==0:mapping[j+1]=(mapping[j] or [])+[i]
                counts[j+1]=min(2,counts[j+1]+counts[j])
    state='AVAILABLE' if counts[-1]==1 else 'AMBIGUOUS' if counts[-1]>1 else 'UNKNOWN'
    checks.append(check('adsorption_relation',state,'输入表面原子按序核对元素、固定标志和周期坐标，容差1e-4Å；重排/预弛豫或多个映射不能按名称确认'))
    if state!='AVAILABLE':return checks,None
    kept=set(mapping[-1]);added=[i+1 for i in range(len(a['atoms'])) if i not in kept]
    return checks,{'surface_atom_indices':[i+1 for i in mapping[-1]],'adsorbate_atom_indices':added,
                  'fractional':[a['fractional'][i-1] for i in added],'reference_composition':m['composition']}


def validate(complex_data,surface_data,adsorbate_data,reference_type='periodic'):
    checks,site=relationship(complex_data,surface_data,adsorbate_data)
    checks+=compatibility([complex_data,surface_data],same_cell=True)
    ref_checks=compatibility([complex_data,adsorbate_data])
    if reference_type=='isolated_molecule':
        # Only k sampling/cell may differ. Functional, U, potentials, cutoffs,
        # energy convention and other Hamiltonian settings still must agree.
        ref_checks=[c for c in ref_checks if c['check']!='compatibility.kpoints']
        kp=adsorbate_data.get('kpoints') or {}
        gamma=kp.get('mode')=='g' and kp.get('mesh')==[1,1,1] and kp.get('shift')==[0,0,0]
        ref_checks.append(check('adsorbate_gamma','AVAILABLE' if gamma else 'INVALID','声明的孤立分子参考须为Gamma 1×1×1且无偏移；盒尺寸/自旋基态收敛仍需独立验证'))
    checks+=ref_checks
    checks.append(check('adsorbate_reference_type','AVAILABLE','声明参考类型：'+reference_type+'；参考能量来自绑定计算，不是LLM给定值'))
    return checks,site
