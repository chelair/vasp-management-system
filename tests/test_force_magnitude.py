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
import batch_check as check
from batch_check import compute_force_stats


class ForceMagnitudeTests(unittest.TestCase):
    def test_opt_completion_uses_ediffg_max_force_without_extra_rms_gate(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "POSCAR").write_text(
                "H\n1\n5 0 0\n0 5 0\n0 0 5\nH\n2\nSelective dynamics\nDirect\n"
                "0 0 0 T T T\n0 0 0 F F F\n")
            (directory / "INCAR").write_text("EDIFFG=-0.02\nEDIFF=1E-6\n")
            (directory / "KPOINTS").write_text("test\n0\nGamma\n5 5 5\n0 0 0\n")
            task = {"task_id": "opt", "task_type": "opt", "remote_dir": root}
            for force, expected in ((.019, "completed"), (.02, "unconverged"), (.021, "unconverged")):
                with self.subTest(force=force):
                    (directory / "OUTCAR").write_text(
                        "TOTAL-FORCE (eV/Angst)\n--------\n"
                        f"0 0 0 {force} 0 0\n0 0 0 9 0 0\n--------\n"
                        "General timing and accounting informations for this job\n")
                    with patch.object(check, "match_job_id_by_cwd", return_value=("", True)):
                        result = check.check_task(task, check.DEFAULT_THRESHOLDS)
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["force_converged"], expected == "completed")
                    self.assertGreater(result["force_rms"], .01)
                    self.assertEqual(result["force_thresholds"]["max_force_threshold"], .02)

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

    def test_neb_endpoint_fallback_and_cache_preserve_actual_structure_source(self):
        structure = "H\n1\n5 0 0\n0 5 0\n0 0 5\nH\n2\nSelective dynamics\nDirect\n0 0 0 F F F\n0 0 0 T T T\n"
        outcar = "TOTAL-FORCE (eV/Angst)\n--------\n0 0 0 9 0 0\n0 0 0 .03 0 0\n--------\n free energy TOTEN = -1 eV\n"
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            for label in ("00", "01", "02", "03"):
                directory = base / label
                directory.mkdir()
                (directory / "OUTCAR").write_text(outcar)
                (directory / "POSCAR").write_text(structure)
            # 00 缺 CONTCAR，03 的 CONTCAR 为空；01 同时存在但固定标记不同，02 仅有插值 POSCAR。
            (base / "03" / "CONTCAR").write_text("")
            (base / "01" / "CONTCAR").write_text(structure.replace("F F F", "T T T"))

            def run_local(_server, encoded_script):
                script = atomic_forces.base64.b64decode(encoded_script).decode()
                return subprocess.run(["bash"], input=script, text=True,
                                      capture_output=True, check=True).stdout

            reports = base / "reports"
            with patch.object(atomic_forces, "_run", side_effect=run_local) as remote, \
                 patch.object(atomic_forces, "_thresholds", return_value=atomic_forces.DEFAULT_THRESHOLDS), \
                 patch.object(atomic_forces, "_deep_block") as deep:
                payloads, warnings = atomic_forces._fetch_all_images("test", root, [""], "neb", reports)
            self.assertEqual(remote.call_count, 1)
            deep.assert_not_called()
            self.assertEqual(warnings, [])
            self.assertEqual(set(payloads), {"00", "01", "03"})
            for label in ("00", "03"):
                payload = payloads[label]
                self.assertEqual(payload["structure"], "POSCAR")
                self.assertEqual(payload["fixed_source"], "POSCAR")
                self.assertEqual(payload["elements"], ["H", "H"])
                self.assertEqual(payload["atom_count"], 2)
                self.assertTrue(payload["atoms"][0]["fixed"])
                self.assertFalse(payload["atoms"][1]["fixed"])
                self.assertEqual(payload["force_max"], .03)
                self.assertEqual(atomic_forces._read_cache(reports, "neb", label)["structure"], "POSCAR")
            self.assertEqual(payloads["01"]["structure"], "CONTCAR")
            self.assertEqual(payloads["01"]["fixed_source"], "CONTCAR")
            self.assertFalse(payloads["01"]["atoms"][0]["fixed"])
            self.assertEqual(payloads["01"]["force_max"], 9)
            for label in ("00", "03"):
                (base / label / "POSCAR").unlink()
            output = subprocess.run(["bash"], input=atomic_forces._all_images_script(root, [""]),
                                    text=True, capture_output=True, check=True).stdout
            self.assertIn("@@@SKIP 00", output)
            self.assertIn("@@@SKIP 03", output)
            self.assertNotIn("@@@IMG 00", output)
            self.assertNotIn("@@@IMG 03", output)

    def test_opt_missing_contcar_does_not_fall_back_to_poscar(self):
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
