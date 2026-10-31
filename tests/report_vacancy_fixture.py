"""Synthetic structures and requested regression energies; not scientific records."""

PAIRS = [('LMR', -325.69441924, -316.81409898, 4.73032026),
         ('LIC@LMR', -818.67692987, -816.27422684, -1.74729697),
         ('In₂O₃@LMR', -1144.16522448, -1136.91850842, 3.09671606)]


def cif(metals, oxygens):
    atoms = ['Li']*metals + ['O']*oxygens
    return '''data_synthetic
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
''' + '\n'.join(f'{el}{i+1} {el} {i*.12} .25 .25' for i, el in enumerate(atoms))+'\n'


def install(doc):
    for index, (label, pristine, defect, _) in enumerate(PAIRS):
        for role, energy, oxygen in [('pristine', pristine, 2), ('defect', defect, 1)]:
            doc['science']['opt'].append({'task_id':f'vac{index}_{role}', 'task_name':label+' '+role,
                'final_energy_ev':energy, 'converged':True,
                'structure':{'contcar_cif':cif(index+1,oxygen)}})


def action(values, target):
    refs = {f['value']:key for key,f in values.items() if f['field'] == 'final_energy_ev'}
    oxygen = next(key for key,f in reversed(list(values.items())) if f.get('reference_kind') in ('O2','mu_O'))
    return {'kind':'calculate','target':target,'property_id':'oxygen_vacancy.neutral_single',
            'inputs':{'oxygen':oxygen}, 'targets':[{'label':label,'pristine':refs[p],'defect':refs[d]} for label,p,d,_ in PAIRS]}
