"""受力口径回归：合力模长、固定原子排除与旧缓存失效；不访问生产数据或 SSH。"""
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix="vasp-force-test-")
os.environ.setdefault("VASP_WEB_DATA_DIR", _DATA.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import atomic_forces
from batch_check import compute_force_stats


class ForceMagnitudeTests(unittest.TestCase):
    def test_diagonal_force_and_fixed_atom_statistics(self):
        forces = [(0.03, -0.04, 0.0), (9.0, 0.0, 0.0)]
        self.assertEqual(compute_force_stats(forces, [False, True]), (0.05, 0.028868))
        self.assertIsNone(compute_force_stats(forces, [True, True]))
        self.assertIsNone(compute_force_stats([], None))

    def test_atom_readout_matches_summary_and_keeps_fixed_atom_flag(self):
        layout = {"n_atoms": 2, "species": ["H"], "counts": [2], "fixed": [False, True]}
        block = {"forces": [(0.03, -0.04, 0.0), (9.0, 0.0, 0.0)], "energy": -1.0}
        with patch.object(atomic_forces, "parse_total_force_blocks", return_value=[block]), \
             patch.object(atomic_forces, "parse_poscar_layout", return_value=layout):
            payload, warnings = atomic_forces._build_payload(
                task_id="test", task_type="opt", image=None, work_dir="/test",
                probe={"tail": "test", "contcar": "test", "size": 100, "mtime": 1},
                thresholds={"max_force_threshold": 0.02, "rms_force_threshold": 0.01},
            )
        self.assertEqual(warnings, [])
        self.assertEqual(payload["atoms"][0]["fmax"], 0.05)
        self.assertEqual(payload["force_max"], 0.05)
        self.assertEqual(payload["force_rms"], 0.028868)
        self.assertTrue(payload["atoms"][1]["fixed"])
        self.assertEqual(payload["fixed_count"], 1)

    def test_remote_probes_use_contcar_even_when_poscar_flags_disagree(self):
        structure = "H\n1\n5 0 0\n0 5 0\n0 0 5\nH\n2\nSelective dynamics\nDirect\n0 0 0 F F F\n0 0 0 T T T\n"
        outcar = "TOTAL-FORCE (eV/Angst)\n--------\n0 0 0 9 0 0\n0 0 0 .03 0 0\n--------\n free energy TOTEN = -1 eV\n"
        for neb in (False, True):
            with self.subTest(neb=neb), tempfile.TemporaryDirectory() as root:
                directory = Path(root) / "01" if neb else Path(root)
                directory.mkdir(exist_ok=True)
                (directory / "OUTCAR").write_text(outcar)
                (directory / "CONTCAR").write_text(structure)
                (directory / "POSCAR").write_text(structure.replace("F F F", "T T T"))
                script = (atomic_forces._all_images_script if neb else atomic_forces._single_script)(root, [""])
                output = subprocess.run(["bash"], input=script, text=True, capture_output=True, check=True).stdout
                probe = atomic_forces._probe_of(output)
                payload, warnings = atomic_forces._build_payload(
                    task_id="test", task_type="neb" if neb else "opt", image="01" if neb else None,
                    work_dir=str(directory), probe=probe, thresholds=atomic_forces.DEFAULT_THRESHOLDS)
                self.assertEqual(warnings, [])
                self.assertEqual(payload["fixed_source"], "CONTCAR")
                self.assertTrue(payload["atoms"][0]["fixed"])
                self.assertFalse(payload["atoms"][1]["fixed"])
                self.assertEqual(payload["fixed_count"], 1)
                self.assertEqual(payload["force_max"], .03)

    def test_missing_contcar_does_not_fall_back_to_poscar(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "OUTCAR").write_text("output")
            (Path(root) / "POSCAR").write_text("old flags")
            response = subprocess.run(["bash"], input=atomic_forces._single_script(root, [""]),
                                      text=True, capture_output=True)
            self.assertEqual(response.returncode, 5)
            with self.assertRaisesRegex(atomic_forces.AtomicForceError, "缺少 CONTCAR"):
                atomic_forces._raise_for_flags(response.stdout, root)

    def test_old_component_force_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            path = atomic_forces._cache_path(base, "test", None)
            for old_schema in (4, 5):
                path.write_text(json.dumps({"schema": old_schema, "force_max": 0.04}))
                self.assertIsNone(atomic_forces._read_cache(base, "test", None))
            path.write_text(json.dumps({"schema": atomic_forces.CACHE_SCHEMA, "force_max": 0.05}))
            self.assertEqual(atomic_forces._read_cache(base, "test", None)["force_max"], 0.05)


if __name__ == "__main__":
    unittest.main()
