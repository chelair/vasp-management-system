"""NEB 完成/力收敛判定；仅临时计算目录，无 SSH/生产数据。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import batch_check as check

POSCAR = "H\n1\n5 0 0\n0 5 0\n0 0 5\nH\n2\nSelective dynamics\nDirect\n0 0 0 T T T\n0 0 0 F F F\n"


class NebConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vasp-neb-check-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.band(self.root)

    def band(self, root, ediffg="-0.04"):
        root.mkdir(exist_ok=True)
        (root / "INCAR").write_text("IMAGES = 2\nEDIFFG = " + ediffg + "\n")
        for image in ("00", "01", "02", "03"):
            (root / image).mkdir(exist_ok=True)
            (root / image / "POSCAR").write_text(POSCAR)
            self.output(root, image, .01)

    def output(self, root, image, force, *, finished=True, summary=""):
        (root / image / "OUTCAR").write_text(
            " POSITION TOTAL-FORCE (eV/Angst)\n -----------\n"
            f" 0 0 0 {force} 0 0\n 0 0 0 9 0 0\n -----------\n"
            " free energy TOTEN = -10 eV\n" + summary + "\n" +
            (" General timing and accounting informations for this job\n" if finished else ""))

    def analyze(self):
        result = check._new_result({"task_id": "neb", "task_type": "neb"})
        check._analyze_neb_status(result, str(self.root))
        return result

    def test_all_middle_images_and_same_opt_rms_rule(self):
        self.output(self.root, "00", 8)  # endpoints never gate NEB convergence
        self.assertEqual(self.analyze()["status"], "completed")
        self.output(self.root, "02", .038)  # max < .04, RMS > .02
        result = self.analyze()
        self.assertEqual(result["status"], "unconverged")
        self.assertFalse(result["force_converged"])
        self.assertIn("02", " ".join(result["error_messages"]))

    def test_actual_con_directory_threshold_not_parent_or_registry(self):
        self.band(self.root / "con1", "-0.01")
        result = self.analyze()
        self.assertEqual(result["status"], "unconverged")
        self.assertEqual(result["force_thresholds"]["max_force_threshold"], .01)
        self.assertEqual(result["parameter_sources"]["INCAR"], str(self.root / "con1"))

    def test_missing_or_energy_ediffg_cannot_be_completed(self):
        for value in ("0.01", "NaN", "0", "bad"):
            with self.subTest(value=value):
                (self.root / "INCAR").write_text("IMAGES=2\nEDIFFG=" + value)
                result = self.analyze()
                self.assertEqual(result["status"], "unconverged")
                self.assertIsNone(result["force_converged"])
        (self.root / "INCAR").unlink()
        self.assertEqual(self.analyze()["status"], "unconverged")

    def test_missing_force_or_image_and_abnormal_end(self):
        (self.root / "02" / "OUTCAR").write_text("General timing and accounting informations for this job\n")
        self.assertEqual(self.analyze()["status"], "unconverged")
        self.output(self.root, "02", .01, finished=False)
        self.assertEqual(self.analyze()["status"], "zombied")
        (self.root / "02" / "OUTCAR").unlink()
        self.assertEqual(self.analyze()["status"], "zombied")

    def test_neb_projected_force_summary_takes_precedence(self):
        self.output(self.root, "01", .5, summary="FORCES: max atom, RMS 0.01 0.005")
        result = self.analyze()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["neb_force_checks"][0]["force_max"], .01)

    def test_check_task_keeps_running_and_selects_neb_input_directory(self):
        self.band(self.root / "con1", "-0.1")
        task = {"task_id": "neb", "task_type": "neb", "remote_dir": str(self.root), "job_id": "123"}
        with patch.object(check, "run_bjobs", return_value="RUN"), \
             patch.object(check, "match_job_id_by_cwd", return_value=("123", True)), \
             patch.object(check.subprocess, "run", side_effect=OSError("no nebef")):
            result = check.check_task(task, check.DEFAULT_THRESHOLDS)
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["current_output"]["dir"], str(self.root / "con1"))
        self.assertEqual(result["incar"]["EDIFFG"], "-0.1")
        self.assertEqual(result["force_thresholds"]["max_force_threshold"], .1)
        with patch.object(check, "run_bjobs", return_value="DONE"), \
             patch.object(check, "match_job_id_by_cwd", return_value=("", True)), \
             patch.object(check.subprocess, "run", side_effect=OSError("no nebef")):
            result = check.check_task(task, check.DEFAULT_THRESHOLDS)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["force_converged"])


if __name__ == "__main__":
    unittest.main()
