"""Independent geometry vectors, scoped source reads and AI dispatch; no real SSH/model."""
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-structure-tests-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name)/'ai.key')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import structure_geometry as geom
import structure_sources as sources
import structure_tools as tools
import ai_workspace as workspace
import permissions
import structure_check as review
import structure_check_evidence as probe


def poscar(coords, cell=((10,0,0),(0,10,0),(0,0,10)), *, selective=None, mode='Direct'):
    text = 'fixture\n1\n'+'\n'.join(' '.join(map(str,row)) for row in cell)+'\nH\n'+str(len(coords))+'\n'
    if selective is not None:text += 'Selective dynamics\n'
    text += mode+'\n'
    text += '\n'.join(' '.join(map(str,row))+(' '+' '.join(selective[i]) if selective else '') for i,row in enumerate(coords))+'\n'
    return text


class GeometryTests(unittest.TestCase):
    def test_review_translation_is_not_transformation_and_never_claims_phase(self):
        before = geom.parse(poscar([[.99,0,0],[.1,0,0]]))
        after = geom.parse(poscar([[.09,0,0],[.2,0,0]]))
        evidence = {'files':{}}
        result = review.check(after,before,evidence,[True]*3,True)
        comp = result['overall_structure']['comparison']
        self.assertEqual(comp['displacements']['max_angstrom'],1)
        self.assertEqual(comp['translation_adjusted_displacements']['max_angstrom'],0)
        self.assertEqual(comp['geometric_network_changes']['changed_atom_count'],0)
        self.assertEqual(result['overall_structure']['phase_or_denaturation_verdict'],'NOT_DETERMINED')
        self.assertEqual(result['interpretation_limits']['target_chemistry_interpretation'],'UNVERIFIED')

    def test_review_covers_all_atoms_and_distinguishes_initial_model_problem(self):
        before = geom.parse(poscar([[i*.08,0,0] for i in range(7)]+[[.48,.005,0]]))
        after = geom.parse(poscar([[i*.08,0,0] for i in range(7)]+[[.48,.2,0]]))
        result = review.check(after,before,{'files':{}},[True]*3,True)
        initial = result['overall_structure']['initial']
        self.assertEqual(initial['atom_count_scanned'],8)
        self.assertEqual(initial['short_contacts'][0]['atom_indices'],[7,8])
        self.assertEqual(initial['severe_overlap_count'],1)
        self.assertEqual(result['overall_structure']['target']['suspect_contact_count'],0)
        self.assertEqual(result['overall_structure']['status'],'REVIEW_REQUIRED')
        self.assertIn('初始建模',result['recommended_focus'][0])

    def test_normal_oh_bond_and_short_nominal_li_o_use_pair_specific_screen(self):
        text = poscar([[0,0,0],[.096,0,0]]).replace('\nH\n2\n','\nO H\n1 1\n')
        scanned,_ = review.scan(geom.parse(text),[True]*3)
        self.assertEqual(scanned['suspect_contact_count'],0)
        text = poscar([[0,0,0],[.137,0,0]]).replace('\nH\n2\n','\nLi O\n1 1\n')
        scanned,_ = review.scan(geom.parse(text),[True]*3)
        self.assertEqual(scanned['suspect_contact_count'],1)
        self.assertEqual(scanned['severe_overlap_count'],0)

    def test_review_changed_cell_composition_and_unknown_radii_are_not_passes(self):
        reference = geom.parse(poscar([[0,0,0]]))
        target = geom.parse(poscar([[0,0,0]],cell=((11,0,0),(0,10,0),(0,0,10))))
        result = review.check(target,reference,{'files':{}},[True]*3,True)
        self.assertEqual(result['overall_structure']['status'],'REVIEW_REQUIRED')
        self.assertFalse(result['overall_structure']['screening_complete'])
        self.assertIsNone(result['overall_structure']['comparison']['displacements'])
        target = geom.parse(poscar([[0,0,0]]).replace('\nH\n','\nHe\n'))
        result = review.check(target,reference,{'files':{}},[True]*3,True)
        self.assertEqual(result['overall_structure']['status'],'REVIEW_REQUIRED')
        self.assertEqual(result['overall_structure']['target']['unsupported_radius_elements'],['He'])
        self.assertFalse(result['overall_structure']['screening_complete'])

    def test_oblique_cartesian_basis_and_exact_minimum_image(self):
        cell = [[2,0,0],[1.8,2,0],[0,0,10]]
        parsed = geom.parse(poscar([[0,0,0],[.49,.49,0]],cell))
        self.assertEqual(geom.atom_record(parsed,1)['cartesian_angstrom'],[1.862,.98,0])
        env = geom.environment(parsed,[1],1,[True,True,False])['environments'][0]
        self.assertEqual(env['geometric_neighbor_count'],1)
        neighbor = env['neighbors'][0]
        self.assertEqual(neighbor['image_shift'],[-1,0,0])
        self.assertAlmostEqual(neighbor['distance_angstrom'],math.hypot(-.138,.98),places=6)
        cart = geom.parse(poscar([[1.862,.98,0]],cell,mode='Cartesian'))
        self.assertAlmostEqual(cart['fractional'][0][0],.49)
        self.assertAlmostEqual(cart['fractional'][0][1],.49)
        # Strongly skewed basis: nearest image is outside the naive [-1,1] cube.
        cell = [[1,0,0],[3,1,0],[0,0,10]]
        distance,_,shift = geom.minimum_image([.49,.49,0],cell,geom.reciprocal(cell),[True,True,False])
        self.assertEqual(shift,[-2,0,0])
        self.assertAlmostEqual(distance,math.hypot(-.04,.49),places=10)

    def test_self_images_angles_and_nonperiodic_case(self):
        parsed = geom.parse(poscar([[0,0,0]],[[2,0,0],[0,2,0],[0,0,2]]))
        env = geom.environment(parsed,[1],2.01,[True]*3)['environments'][0]
        self.assertEqual(env['geometric_neighbor_count'],6)
        self.assertEqual({a['angle_degrees'] for a in env['angles_nearest_six_neighbors']},{90,180})
        self.assertEqual(geom.environment(parsed,[1],2.01,[False]*3)['environments'][0]['geometric_neighbor_count'],0)

    def test_fixed_directions_layer_projection_and_atom_pagination(self):
        parsed = geom.parse(poscar([[0,0,.25],[0,0,.30],[0,0,.75],[0,0,.80]],
            [[10,0,0],[0,10,0],[3,0,20]],selective=[['F','T','F']]*4))
        value = geom.summary(parsed,layer_gap_angstrom=1.2)
        self.assertEqual(value['constraints']['fully_fixed_atoms'],0)
        self.assertEqual(value['constraints']['partially_or_fully_fixed_atoms'],4)
        self.assertEqual(value['atoms'][0]['fixed_fractional_axes'],[True,False,True])
        self.assertEqual(value['layering']['layer_count'],2)
        self.assertAlmostEqual(value['layering']['largest_atom_plane_gap']['width_angstrom'],9)
        many = geom.parse(poscar([[i/30,0,0] for i in range(27)]))
        self.assertEqual(geom.summary(many)['next_atom_offset'],24)
        self.assertEqual(len(geom.summary(many,atom_offset=24)['atoms']),3)

    def test_compare_periodic_displacements_pairs_and_mapping_limits(self):
        before = geom.parse(poscar([[.99,0,0],[.2,0,0]]))
        after = geom.parse(poscar([[.01,0,0],[.21,0,0]]))
        result = geom.compare(before,after,same_task=True,pbc=[True]*3,pairs=[[1,2]])
        self.assertEqual(result['status'],'AVAILABLE')
        self.assertEqual(result['displacements']['max_angstrom'],.2)
        self.assertEqual(result['displacements']['rms_angstrom'],.158114)
        self.assertEqual(result['pair_distances'][0]['change_angstrom'],-.1)
        self.assertFalse(result['atom_mapping']['verified'])
        different = geom.compare(before,after,same_task=False,pbc=[True]*3,pairs=[])
        self.assertIsNone(different['displacements'])
        after['lattice'][0][0] = 11
        changed = geom.compare(before,after,same_task=True,pbc=[True]*3,pairs=[])
        self.assertEqual(changed['status'],'PARTIAL')
        self.assertIsNone(changed['displacements'])

    def test_unsupported_formats_and_bounded_periodic_search(self):
        with self.assertRaises(ValueError):geom.parse(poscar([[0,0,0]]).replace('\n1\n','\n-1000\n',1))
        with self.assertRaises(ValueError):geom.parse('bad\n1\n1 0 0\n0 1 0\n0 0 1\nH\n999999999999999\nmissing coordinates\n')
        with self.assertRaises(ValueError):geom.parse(poscar([[0,0,0]],selective=[['F','T']]))
        cell = [[.001,0,0],[0,.001,0],[0,0,.001]]
        with self.assertRaises(ValueError):list(geom.image_vectors([0,0,0],cell,geom.reciprocal(cell),6,[True]*3))


class StructureToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vasp-structure-source-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = self.root/'projects/P/opt/model/files'
        self.files.mkdir(parents=True)
        self.before = poscar([[.99,0,0],[.2,0,0]])
        self.after = poscar([[.01,0,0],[.21,0,0]])
        (self.files/'POSCAR').write_text(self.before)
        (self.files/'CONTCAR').write_text(self.after)
        self.remote = self.root/'remote/with apostrophe \' and space'
        (self.remote/'con1').mkdir(parents=True)
        (self.remote/'con2').mkdir()
        for folder in (self.remote,self.remote/'con1',self.remote/'con2'):
            (folder/'POSCAR').write_text(self.before)
            (folder/'CONTCAR').write_text(self.after)
        self.task = {'task_id':'t','task_type':'opt','model_name':'Model','dir_path':'P/opt/model',
                     'remote_dir':str(self.remote),'last_structure_dirs':{'POSCAR':'con7','CONTCAR':'con8'}}
        self.project = {'project_id':'p','name':'P','owner':'alice','server':'fixture','tasks':[self.task]}
        self.user = {'user_id':'alice','username':'alice','role':'user'}
        self.patches = [patch.object(tools,'load_db',return_value={'projects':[self.project]}),
            patch('paths.load_path_mapping',return_value={'local_root':str(self.root/'projects'),'remote_roots':{}})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.ssh = patch('ssh.run_remote',side_effect=AssertionError('unexpected SSH'))
        self.ssh.start();self.addCleanup(self.ssh.stop)

    def call(self,name,arguments,user=None):
        return workspace.dispatch(self.project,{}, {},name,arguments,user=user or self.user)

    def test_local_summary_environment_compare_and_hash_change(self):
        raw = (self.files/'CONTCAR').read_bytes()
        value = self.call('get_structure_summary',{'structure':{'task_id':'t'}})
        self.assertEqual(value['source']['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['source']['recorded_structure_directory'],'con8')
        self.assertFalse(value['source']['remote_verified'])
        pinned = value['source']['selector']
        page = self.call('get_structure_summary',{'structure':pinned,'atom_offset':1})
        self.assertEqual(page['atoms'][0]['index'],2)
        self.assertNotIn('layering',page)
        env = self.call('get_structure_environment',{'structure':pinned,'atom_indices':[1],'cutoff_angstrom':3})
        self.assertEqual(env['environments'][0]['neighbors'][0]['distance_angstrom'],2)
        compare = self.call('compare_structures',{'reference':{'task_id':'t','file':'POSCAR'},'target':pinned,'pairs':[[1,2]]})
        self.assertEqual(compare['displacements']['max_angstrom'],.2)
        self.assertEqual((self.files/'CONTCAR').read_bytes(),raw)
        (self.files/'CONTCAR').write_text(self.before)
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.call('get_structure_environment',{'structure':pinned,'atom_indices':[1]})

    def test_bader_fragment_uses_analysis_order_and_charged_reference(self):
        folder = self.files.parent/'bader'
        folder.mkdir()
        # The analysis order differs from today's POSCAR; numbering belongs to ACF.
        (self.files/'POSCAR').write_text(self.before.replace('\nH\n2\n','\nH S\n1 1\n'))
        (folder/'meta.json').write_text(json.dumps({'charge_header':{'elements':['S','H'],'counts':[1,1]},
                                                  'zval':{'S':6,'H':1},'run_id':'frozen-analysis'}))
        (folder/'ACF.dat').write_text('# X Y Z CHARGE MIN DIST ATOMIC VOL\n---\n'
            '1 0 0 0 2.4 0.4 6\n2 1 0 0 0.3 0.1 2\n---\nNUMBER OF ELECTRONS: 2.7\n')
        with patch('storage.load_db',return_value={'projects':[self.project]}):
            response = self.call('get_bader_charges',{'targets':[
                {'task_id':'t','atom_indices':[1],'reference_charge':0},
                {'task_id':'t','atom_indices':[1],'reference_charge':-1}]})
        result=response['results']
        self.assertEqual(response['interpretation_limits']['mechanism'],'NOT_ESTABLISHED')
        self.assertEqual(result[0]['composition'],{'S':1})
        self.assertEqual(result[0]['net_charge_e'],3.6)
        self.assertEqual(result[0]['electron_gain_from_reference_e'],-3.6)
        self.assertEqual(result[1]['electron_gain_from_reference_e'],-4.6)
        self.assertEqual(result[1]['net_charge_difference_from_first_e'],0)
        self.assertEqual(result[0]['source']['element_source'],'charge-header')

    def test_similar_cross_task_structures_report_field_and_parameter_changes(self):
        other = self.root/'projects/P/opt/field/files'
        other.mkdir(parents=True)
        (other/'CONTCAR').write_text(self.after)
        self.project['tasks'].append({'task_id':'field','task_type':'opt','dir_path':'P/opt/field'})
        (self.files/'INCAR').write_text('ISPIN=2; IBRION=-1; NSW=0; LDAUTYPE=1\n')
        (other/'INCAR').write_text('ISPIN=2; IBRION=2; NSW=500; LDAUTYPE=1\nEFIELD=0.05\n')
        (self.files/'KPOINTS').write_text('auto\n0\nGamma\n2 3 1\n0 0 0\n')
        (other/'KPOINTS').write_text('auto\n0\nGamma\n3 3 1\n0 0 0\n')
        args = {'reference':{'task_id':'t'},'target':{'task_id':'field'}}
        result = self.call('compare_structures',args)
        self.assertEqual(result['reference_composition'],result['target_composition'])
        diff = result['parameter_comparison']
        changes = {r['key']:(r['before'],r['after']) for r in diff['incar_changes']}
        self.assertEqual(changes['EFIELD'],(None,'0.05'))
        self.assertEqual(changes['IBRION'],('-1','2'))
        self.assertNotIn('ISPIN',changes)
        self.assertEqual(diff['kpoints_change']['after']['mesh'],[3,3,1])
        self.assertEqual(set(diff['target_source']['files']),{'INCAR','KPOINTS'})
        (other/'INCAR').unlink()
        partial = self.call('compare_structures',args)
        self.assertEqual(partial['reference_composition'],partial['target_composition'])
        self.assertFalse(partial['parameter_comparison']['incar_available'])
        self.assertEqual(partial['parameter_comparison']['incar_changes'],[])

    def test_bader_missing_zval_partial_results_and_project_scope(self):
        folder = self.files.parent/'bader'
        folder.mkdir()
        (folder/'ACF.dat').write_text('# X Y Z CHARGE MIN DIST\n---\n'
            '1 0 0 0 0.8 0.1\n2 1 0 0 1.2 0.1\n---\nNUMBER OF ELECTRONS: 2\n')
        with patch('storage.load_db',return_value={'projects':[self.project]}):
            result = self.call('get_bader_charges',{'targets':[{'task_id':'t'},
                {'task_id':'t','atom_indices':[3]}]})['results']
            self.assertEqual(result[0]['bader_electrons'],2)
            self.assertIsNone(result[0]['net_charge_e'])
            self.assertIn('error',result[1])
            with self.assertRaises(permissions.PermissionDenied):
                self.call('get_bader_charges',{'targets':[{'task_id':'other-project-task'}]})
            with self.assertRaises(permissions.PermissionDenied):
                self.call('get_bader_charges',{'targets':[{'task_id':'t'}]},user={'username':'bob','role':'user'})

    def test_check_order_runtime_mismatch_and_read_only_missing_evidence(self):
        before = self.before.replace('\nH\n2\n','\nLi Mn\n1 1\n')
        after = self.after.replace('\nH\n2\n','\nLi Mn\n1 1\n')
        (self.files/'POSCAR').write_text(before)
        (self.files/'CONTCAR').write_text(after)
        (self.files/'INCAR').write_text('EDIFF=1E-5; ISPIN=2\nMAGMOM=1*3 1*0\n')
        (self.files/'POTCAR').write_text(' TITEL = PAW_PBE Mn 2000\n ZVAL = 7\n TITEL = PAW_PBE Li 2000\n ZVAL = 1\n')
        (self.files/'OUTCAR').write_text(' POTCAR: PAW_PBE Mn 2000\n POTCAR: PAW_PBE Li 2000\n'*2+' ions per type = 1 1\n NELECT = 8.0000\n')
        saved = {p.name:p.read_bytes() for p in self.files.iterdir()}
        result = self.call('check_structure',{'structure':{'task_id':'t'}})
        self.assertEqual(result['review_order'],['overall_structure_and_transformation','local_coordination_and_interface','calculation_settings'])
        self.assertEqual(result['basic_identity_cross_check']['priority'],'basic_cross_check')
        self.assertEqual(result['basic_identity_cross_check']['runtime_order_status'],'MISMATCH')
        self.assertEqual(result['interpretation_limits']['target_chemistry_interpretation'],'WITHHOLD')
        self.assertEqual(result['calculation_settings']['current_incar_settings']['EDIFF'],'1E-5')
        self.assertEqual(result['calculation_settings']['convergence_verdict'],'NOT_DETERMINED')
        self.assertEqual(saved,{p.name:p.read_bytes() for p in self.files.iterdir()})
        (self.files/'POTCAR').unlink()
        (self.files/'OUTCAR').unlink()
        (self.files/'POSCAR').unlink()
        result = self.call('check_structure',{'structure':{'task_id':'t'}})
        self.assertIsNone(result['overall_structure']['initial'])
        self.assertEqual(result['basic_identity_cross_check']['runtime_order_status'],'UNKNOWN')
        self.assertEqual(result['interpretation_limits']['target_chemistry_interpretation'],'UNVERIFIED')
        with self.assertRaises(ValueError):
            self.call('check_structure',{'structure':{'task_id':'t'},'reference':{'task_id':'t','file':'POSCAR'}})
        with self.assertRaises(permissions.PermissionDenied):
            self.call('check_structure',{'structure':{'task_id':'t'}},user={'username':'bob','role':'user'})

    def test_check_fixed_remote_companion_probe_hash_and_no_symlink(self):
        def remote(server,command,timeout):
            args = shlex.split(command)
            self.assertIn(args[2],(sources._REMOTE_READ,Path(probe.__file__).read_text()))
            response = subprocess.run(args,capture_output=True,text=True,timeout=timeout)
            return {'exit_code':response.returncode,'stdout':response.stdout,'stderr':response.stderr}
        (self.remote/'con2/OUTCAR').write_text(' POTCAR: PAW_PBE H 2000\n ions per type = 2\n')
        (self.remote/'con2/POTCAR').symlink_to(self.remote/'con2/OUTCAR')
        with patch('ssh.run_remote',side_effect=remote):
            result = self.call('check_structure',{'structure':{'task_id':'t','source':'remote'}})
            self.assertEqual(result['source']['selector']['directory'],'con2')
            self.assertEqual(result['reference_source']['selector']['directory'],'MAIN')
            self.assertEqual(result['basic_identity_cross_check']['runtime_order_status'],'CONSISTENT')
            self.assertEqual(result['companion_evidence']['files']['POTCAR']['status'],'UNKNOWN')
            source = result['source']
            (self.remote/'con2/CONTCAR').write_text(self.before)
            with self.assertRaisesRegex(ValueError,'补证失败'):
                sources.load_check_evidence(self.project,source)

    def test_permissions_and_nested_injection_before_read(self):
        with self.assertRaises(permissions.PermissionDenied):
            self.call('get_structure_summary',{'structure':{'task_id':'t'}},user={'username':'bob','role':'user'})
        with self.assertRaises(permissions.PermissionDenied):
            self.call('get_structure_summary',{'structure':{'task_id':'other-project-task'}})
        for arguments in ({'structure':{'task_id':'t','file':'../secret'}},
                          {'structure':{'task_id':'t','source':'remote','directory':'con1; touch hacked'}},
                          {'structure':{'task_id':'t','directory':'con8'}},
                          {'structure':{'task_id':'t','project_id':'other'}},
                          {'structure':{'task_id':'t'},'pbc':[1,1,1]}):
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):
                self.call('get_structure_summary',arguments)
        with self.assertRaises(ValueError):
            self.call('get_structure_environment',{'structure':{'task_id':'t'},'atom_indices':[True]})

    def test_missing_empty_symlink_and_unstable_files_are_not_fallbacks(self):
        path = self.files/'CONTCAR'
        path.unlink()
        with self.assertRaises(ValueError):self.call('get_structure_summary',{'structure':{'task_id':'t'}})
        path.write_text('')
        with self.assertRaises(ValueError):self.call('get_structure_summary',{'structure':{'task_id':'t'}})
        path.unlink();path.symlink_to(self.files/'POSCAR')
        with self.assertRaises(ValueError):self.call('get_structure_summary',{'structure':{'task_id':'t'}})
        path.unlink();path.write_text(self.after)
        real_stat = sources.os.stat
        def changed(*args,**kwargs):
            value = real_stat(*args,**kwargs)
            if args[0]=='CONTCAR' and 'dir_fd' in kwargs:
                class Different:
                    st_dev=value.st_dev;st_ino=value.st_ino;st_size=value.st_size;st_mtime_ns=value.st_mtime_ns+1
                return Different()
            return value
        with patch.object(sources.os,'stat',side_effect=changed),self.assertRaisesRegex(ValueError,'正在变化'):
            self.call('get_structure_summary',{'structure':{'task_id':'t'}})

    def remote_mock(self,server,command,timeout):
        self.assertEqual(server,'fixture')
        args = shlex.split(command)
        self.assertEqual(args[:2],['python3','-c'])
        self.assertIn(args[2],(sources._REMOTE_READ,Path(probe.__file__).read_text()))
        response = subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return {'exit_code':response.returncode,'stdout':response.stdout,'stderr':response.stderr}

    def test_fixed_remote_reader_current_pinning_batching_and_missing_no_fallback(self):
        with patch('ssh.run_remote',side_effect=self.remote_mock) as remote:
            value = self.call('get_structure_summary',{'structure':{'task_id':'t','source':'remote'}})
            self.assertTrue(value['source']['remote_verified'])
            self.assertEqual(value['source']['selector']['directory'],'con2')
            self.assertEqual(value['source']['remote_path'],str(self.remote/'con2/CONTCAR'))
            remote.reset_mock()
            reference = {'task_id':'t','source':'remote','directory':'CURRENT','file':'POSCAR'}
            self.call('compare_structures',{'reference':reference,'target':value['source']['selector']})
            self.assertEqual(remote.call_count,2,'one batched structure read and one shared directory parameter read')
            (self.remote/'con2/CONTCAR').unlink()
            with self.assertRaisesRegex(ValueError,'不自动回退'):
                self.call('get_structure_summary',{'structure':{'task_id':'t','source':'remote'}})
            (self.remote/'con3').symlink_to(self.remote/'con1',target_is_directory=True)
            with self.assertRaises(ValueError):
                self.call('get_structure_summary',{'structure':{'task_id':'t','source':'remote','directory':'con3'}})

    def test_neb_requires_image_and_local_new_image_layout(self):
        self.task['task_type']='neb'
        with self.assertRaises(ValueError):self.call('get_structure_summary',{'structure':{'task_id':'t'}})
        folder = self.files/'neb_images/01';folder.mkdir(parents=True)
        (folder/'CONTCAR').write_text(self.after)
        value = self.call('get_structure_summary',{'structure':{'task_id':'t','image':'01'}})
        self.assertEqual(value['source']['image'],'01')
        self.assertEqual(value['atom_count'],2)


if __name__=='__main__':unittest.main()
