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


def poscar(coords, cell=((10,0,0),(0,10,0),(0,0,10)), *, selective=None, mode='Direct'):
    text = 'fixture\n1\n'+'\n'.join(' '.join(map(str,row)) for row in cell)+'\nH\n'+str(len(coords))+'\n'
    if selective is not None:text += 'Selective dynamics\n'
    text += mode+'\n'
    text += '\n'.join(' '.join(map(str,row))+(' '+' '.join(selective[i]) if selective else '') for i,row in enumerate(coords))+'\n'
    return text


class GeometryTests(unittest.TestCase):
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
        env = self.call('get_structure_environment',{'structure':pinned,'atom_indices':[1],'cutoff_angstrom':3})
        self.assertEqual(env['environments'][0]['neighbors'][0]['distance_angstrom'],2)
        compare = self.call('compare_structures',{'reference':{'task_id':'t','file':'POSCAR'},'target':pinned,'pairs':[[1,2]]})
        self.assertEqual(compare['displacements']['max_angstrom'],.2)
        self.assertEqual((self.files/'CONTCAR').read_bytes(),raw)
        (self.files/'CONTCAR').write_text(self.before)
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.call('get_structure_environment',{'structure':pinned,'atom_indices':[1]})

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
        self.assertEqual(args[2],sources._REMOTE_READ)
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
            self.assertEqual(remote.call_count,1,'two same-task structures must share one fixed remote call')
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
