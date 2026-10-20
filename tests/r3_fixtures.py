"""Synthetic scientific models, not real LMR predictions. All paths under a temp root."""
import json
from pathlib import Path
from dates import now_iso
from batch_check import capture_property_evidence

POT = {el:f'TITEL = PAW_PBE {el} 01Jan2001\n ZVAL = {z}\nEnd of Dataset\n' for el,z in [('Li',1),('Mn',7),('Cl',7),('O',6),('H',1)]}


def poscar(interface=False,defect=False,site=4):
    species = ['Li','Mn']+(['Cl'] if interface else [])+['O']
    atoms = [('Li',[0,0,0]),('Mn',[.5,.5,.5])]+([('Cl',[.2,.2,.2])] if interface else [])+[('O',[.25,.25,.25]),('O',[.75,.75,.75])]
    if defect: atoms.pop(site-1)
    counts = [sum(el == a[0] for a in atoms) for el in species]
    return 'fixture\n1\n5 0 0\n0 5 0\n0 0 5\n'+' '.join(species)+'\n'+' '.join(map(str,counts))+'\nDirect\n'+'\n'.join(' '.join(map(str,c)) for el,c in atoms)+'\n'


def write_run(root,text,energy,charge=0,encut=500,scf=True,ionic=True):
    from property_science import structure
    root.mkdir(parents=True,exist_ok=True)
    p = structure(text)
    root.joinpath('POSCAR').write_text(text)
    root.joinpath('INCAR').write_text(f'ENCUT = {encut}\nGGA = PE\nEDIFF = 1E-6\nNELM = 60\nNSW = 100\n')
    root.joinpath('KPOINTS').write_text('fixture\n0\nGamma\n2 2 1\n0 0 0\n')
    root.joinpath('POTCAR').write_text(''.join(POT[el] for el in p['species']))
    electrons = sum(n*int(POT[el].split('ZVAL = ')[1].split()[0]) for el,n in p['composition'].items())-charge
    out = '\n'.join('POTCAR: '+POT[el].split('TITEL = ')[1].splitlines()[0] for el in p['species'])
    out += f'\nENCUT = {encut}; GGA = PE; EDIFF = 1E-6; NELM = 60; NSW = 100; NELECT = {electrons}\n'
    out += 'generate k-points for: 2 2 1\nshift: 0 0 0\n'
    out += f'free energy TOTEN = {energy:.8f} eV\n'
    if ionic: out += 'reached required accuracy\n'
    out += 'General timing and accounting\n'
    root.joinpath('OSZICAR').write_text(f'DAV: {3 if scf else 60} {energy} {"1E-8" if scf else "1E-2"} 1E-9\n 1 F= {energy:.8f} E0= {energy:.8f}\n')
    root.joinpath('OUTCAR').write_text(out)
    return capture_property_evidence(str(root))


def seed(root):
    tasks,rows = [],[]
    for tid,interface,defect,energy in [('a_p',False,False,-100),('a_d',False,True,-92),('b_p',True,False,-150),('b_d',True,True,-141)]:
        run = root/'runs'/tid/'con1'
        evidence = write_run(run,poscar(interface,defect,5 if interface else 4),energy)
        tasks.append({'task_id':tid,'task_type':'opt','model_name':('LIC@LMR' if interface else 'LMR')+('_vac' if defect else ''),
                      'status':'completed','job_id':tid,'remote_dir':str(run.parent), 'dir_path':f'R3P/opt/{tid}',
                      'current_output':{'latest_dir':'con1'}})
        rows.append({'task_id':tid,'project_name':'R3P','task_type':'opt','remote_dir':str(run.parent),'job_id':tid,
                     'checked_at':now_iso(),'status':'completed','force_converged':True,'last_energy':energy,
                     'incar':{'ENCUT':500},'kpoints':{'mesh':[2,2,1]},'current_output':{'latest_dir':'con1','dir':str(run)},
                     'property_evidence':evidence})
    project = {'project_id':'r3p','name':'R3P','owner':'tester','server':'fixture','tasks':tasks}
    root.joinpath('checks').mkdir(parents=True,exist_ok=True)
    root.joinpath('checks/check_results_r3.json').write_text(json.dumps(rows))
    root.joinpath('projects.json').write_text(json.dumps({'projects':[project]}))
    return project,rows


def request():
    return {'property_id':'oxygen_vacancy.neutral_single','project_ids':['r3p'],
            'targets':[{'label':'LMR','pristine':{'task_id':'a_p'},'defect':{'task_id':'a_d'}},
                       {'label':'LIC@LMR','pristine':{'task_id':'b_p'},'defect':{'task_id':'b_d'}}],
            'mu_O':{'value_ev':-5,'source':'explicit synthetic reference','conditions':'synthetic zero-temperature electronic reference'}}
