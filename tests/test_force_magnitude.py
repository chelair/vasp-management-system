"""受力口径回归：合力模长、固定原子排除与旧缓存失效；不访问生产数据或 SSH。"""
import json
import os
from pathlib import Path
import sys
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
                probe={"tail": "test", "poscar": "test", "size": 100, "mtime": 1},
                thresholds={"max_force_threshold": 0.02, "rms_force_threshold": 0.01},
            )
        self.assertEqual(warnings, [])
        self.assertEqual(payload["atoms"][0]["fmax"], 0.05)
        self.assertEqual(payload["force_max"], 0.05)
        self.assertEqual(payload["force_rms"], 0.028868)
        self.assertTrue(payload["atoms"][1]["fixed"])
        self.assertEqual(payload["fixed_count"], 1)

    def test_old_component_force_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            path = atomic_forces._cache_path(base, "test", None)
            path.write_text(json.dumps({"schema": 4, "force_max": 0.04}))
            self.assertIsNone(atomic_forces._read_cache(base, "test", None))
            path.write_text(json.dumps({"schema": atomic_forces.CACHE_SCHEMA, "force_max": 0.05}))
            self.assertEqual(atomic_forces._read_cache(base, "test", None)["force_max"], 0.05)


if __name__ == "__main__":
    unittest.main()
