"""Synthetic adsorption energies and captured VASP outputs; never real predictions."""
import copy
import json
from pathlib import Path
from dates import now_iso
from batch_check import capture_property_evidence
from r3_fixtures import poscar,write_run


def with_adsorbate(text,site=1,count=2):
    lines=text.splitlines();lines[5]+=' H';lines[6]+=' '+str(count)
    coords=['.1 .2 .4','.1 .2 .55'] if site==1 else ['.3 .4 .5','.3 .4 .65']
    return '\n'.join(lines+coords[:count])+'\n'


def seed(root,pid='ads',*,missing_reference=False,multiple=False,isolated=False):
    root=Path(root);tasks=[];rows=[]
    p={'project_id':pid,'name':'Adsorption_'+pid,'owner':'tester','server':'fixture','tasks':tasks}
    specs=[('a_s','LMR',poscar(),-100),('a_c','LMR_H2',with_adsorbate(poscar()),-105),
           ('b_s','LIC@LMR',poscar(True),-150),('b_c','LIC@LMR_H2',with_adsorbate(poscar(True)),-156)]
    if multiple:specs.append(('a_c2','LMR_H2_site2',with_adsorbate(poscar(),2),-104))
    if not missing_reference:
        side=10 if isolated else 5
        specs.append(('mol','H2',f'molecule\n1\n{side} 0 0\n0 {side} 0\n0 0 {side}\nH\n2\nDirect\n.5 .5 .45\n.5 .5 .55\n',-3))
    for tid,name,text,energy in specs:
        task_id=pid+'_'+tid;run=root/'runs'/task_id/'con1'
        evidence=write_run(run,text,energy)
        if isolated and tid=='mol':
            (run/'KPOINTS').write_text('molecule\n0\nGamma\n1 1 1\n0 0 0\n')
            (run/'OUTCAR').write_text((run/'OUTCAR').read_text().replace('generate k-points for: 2 2 1','generate k-points for: 1 1 1'))
            evidence=capture_property_evidence(str(run))
        tasks.append({'task_id':task_id,'task_type':'opt','model_name':name,'status':'completed','job_id':task_id,
                      'remote_dir':str(run.parent),'dir_path':p['name']+'/opt/'+name,'current_output':{'latest_dir':'con1'}})
        rows.append({'task_id':task_id,'project_name':p['name'],'task_type':'opt','remote_dir':str(run.parent),'job_id':task_id,
                     'checked_at':now_iso(),'status':'completed','force_converged':True,'last_energy':energy,
                     'incar':{'ENCUT':500},'kpoints':{'mesh':[1,1,1] if isolated and tid=='mol' else [2,2,1]},
                     'current_output':{'latest_dir':'con1','dir':str(run)},'property_evidence':evidence})
    return p,rows


def request(pid='ads',reference_type='periodic'):
    return {'property_id':'adsorption.simple','project_ids':[pid],'adsorbate_reference_type':reference_type,
            'targets':[{'label':name,'complex':{'task_id':pid+'_'+code+'_c'},'surface':{'task_id':pid+'_'+code+'_s'},'adsorbate':{'task_id':pid+'_mol'}} for code,name in [('a','LMR'),('b','LIC@LMR')]]}
