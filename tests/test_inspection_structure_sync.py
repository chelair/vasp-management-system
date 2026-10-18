"""最终结构同步回归；隔离数据目录，所有 SSH 均为 mock。"""
import base64
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix="vasp-inspection-test-")
os.environ.setdefault("VASP_WEB_DATA_DIR", _DATA.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import inspection_runner as runner


class FinalStructureSyncTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "task_id": "t", "task_type": "neb", "status": "running", "job_id": "123",
            "last_analysis_dir": "con4", "last_analysis_bucket": 0,
            "current_output": {"latest_dir": "con4"},
        }
        self.project = {"name": "test", "server": "mock", "tasks": [self.task]}
        self.db = {"projects": [self.project]}
        self.result = {"status": "completed", "neb_band_steps": 23,
                       "current_output": {"latest_dir": "con4"}}

    def apply(self):
        return runner._apply_result(self.db, self.project, self.task, copy.deepcopy(self.result))

    def test_finish_below_25_steps_syncs_once_for_opt_and_neb(self):
        for kind in ("opt", "neb"):
            with self.subTest(kind=kind):
                self.setUp()
                self.task["task_type"] = kind
                self.result["force_history"] = [{}] * 23
                helper = "_sync_neb_image_structures" if kind == "neb" else "_sync_and_convert_structure"
                with patch.object(runner, helper, return_value=(["synced"], True)) as sync:
                    first = self.apply()
                    self.assertTrue(first["structure_synced"])
                    self.assertEqual(self.task["last_structure_completion"]["steps"], 23)
                    self.assertFalse(self.apply()["structure_synced"])
                    sync.assert_called_once()

    def test_failed_final_sync_retries_after_status_already_completed(self):
        for failure in (RuntimeError("SSH failed"), (["conversion failed"], False)):
            with self.subTest(failure=str(failure)):
                self.setUp()
                self.task["last_analysis_bucket"] = 1
                self.result["neb_band_steps"] = 51
                with patch.object(runner, "_sync_neb_image_structures", side_effect=[failure, ([], True)]) as sync:
                    self.assertFalse(self.apply()["structure_synced"])
                    self.assertEqual(self.task["status"], "completed")
                    self.assertIsNone(self.task.get("last_structure_completion"))
                    self.assertEqual(self.task["last_analysis_bucket"], 1)
                    self.assertTrue(self.apply()["structure_synced"])
                    self.assertEqual(sync.call_count, 2)

    def test_historical_completed_and_low_precision_tasks_get_final_sync(self):
        for old, new in (("completed", "completed"), ("running", "low_precision")):
            with self.subTest(old=old, new=new):
                self.setUp()
                self.task["status"] = old
                self.result["status"] = new
                with patch.object(runner, "_sync_neb_image_structures", return_value=([], True)):
                    self.assertTrue(self.apply()["structure_synced"])
                    self.assertEqual(self.task["status"], "completed")
                    self.assertFalse(self.apply()["structure_synced"])

    def test_previous_completion_marker_cannot_mask_failed_sync_after_reopen(self):
        self.task["last_structure_completion"] = {"dir": "con4", "job_id": "123", "steps": 23}
        with patch.object(runner, "_sync_neb_image_structures", side_effect=[([], False), ([], True)]):
            self.assertFalse(self.apply()["structure_synced"])
            self.assertIsNone(self.task["last_structure_completion"])
            self.assertTrue(self.apply()["structure_synced"])

    def test_running_throttle_directory_changes_and_retry_are_preserved(self):
        self.result["status"] = "running"
        with patch.object(runner, "_sync_neb_image_structures", return_value=([], True)) as sync:
            self.assertFalse(self.apply()["structure_synced"])
            self.result["neb_band_steps"] = 25
            self.assertTrue(self.apply()["structure_synced"])
            self.result["neb_band_steps"] = 49
            self.assertFalse(self.apply()["structure_synced"])
            self.result["current_output"]["latest_dir"] = "con5"
            self.result["neb_band_steps"] = 1
            sync.return_value = ([], False)
            self.assertFalse(self.apply()["structure_synced"])
            self.assertEqual(self.task["last_analysis_dir"], "con4")
            sync.return_value = ([], True)
            self.assertTrue(self.apply()["structure_synced"])
            self.assertEqual(self.task["last_analysis_dir"], "con5")

    def test_resumed_run_invalidates_final_sync_and_new_output_resyncs(self):
        with patch.object(runner, "_sync_neb_image_structures", return_value=([], True)):
            self.apply()
            self.result["status"] = "running"
            self.apply()
            self.assertIsNone(self.task["last_structure_completion"])
            self.result["status"] = "completed"
            self.assertTrue(self.apply()["structure_synced"])
            self.result["neb_band_steps"] = 24
            self.assertTrue(self.apply()["structure_synced"])
            self.result["job_id"] = "124"
            self.assertTrue(self.apply()["structure_synced"])

    def test_other_task_types_do_not_sync_structures(self):
        for kind in ("frac", "ele"):
            self.task["task_type"] = kind
            with patch.object(runner, "_sync_neb_image_structures") as neb, patch.object(runner, "_sync_and_convert_structure") as opt:
                self.assertFalse(self.apply()["structure_synced"])
                neb.assert_not_called()
                opt.assert_not_called()


class StructureTransferTests(unittest.TestCase):
    def test_neb_missing_image_or_conversion_failure_is_not_success(self):
        payload = base64.b64encode(b"new structure\n").decode()
        for missing, converts in ((False, True), (True, True), (False, False)):
            with self.subTest(missing=missing, converts=converts), tempfile.TemporaryDirectory() as root:
                lines = ["@@@EXPECTED:00", "@@@IMG:00:POSCAR", payload, "@@@EXPECTED:01"]
                if not missing:
                    lines.extend(["@@@IMG:01:CONTCAR", payload])
                remote = {"exit_code": 0, "stdout": "\n".join(lines)}
                with patch.object(runner.ssh, "run_remote", return_value=remote), \
                     patch.object(runner, "task_remote_dir", return_value="/test"), \
                     patch.object(runner, "task_dir", return_value=Path(root)), \
                     patch.object(runner, "convert_structure_to_cif", return_value=converts):
                    markers, success = runner._sync_neb_image_structures({"name": "test", "server": "mock"}, {})
                self.assertEqual(success, not missing and converts)
                if not success:
                    self.assertTrue(any("下次巡检重试" in m for m in markers))

    def test_opt_old_local_files_cannot_mask_download_failure(self):
        with tempfile.TemporaryDirectory() as root:
            files = Path(root) / "files"
            files.mkdir()
            for name in ("POSCAR", "CONTCAR"):
                (files / name).write_text("old structure")
            def convert(src, out, **kwargs):
                out.write_text("converted")
                return True
            with patch.object(runner.ssh, "download_file", return_value=False), \
                 patch.object(runner, "local_files_dir", return_value=files), \
                 patch.object(runner, "task_remote_dir", return_value="/test"), \
                 patch.object(runner, "convert_structure_to_cif", side_effect=convert):
                _, success = runner._sync_and_convert_structure({"name": "test", "server": "mock"}, {})
            self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
