"""模型巡检证据契约：任务边界、阶段身份、时效、缺失与分页。"""
import copy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ai_inspections as inspections
import ai_workspace as workspace
from permissions import PermissionDenied


class InspectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.project = {"project_id": "p", "name": "project", "server":"fixture", "tasks": [
            {"task_id": "t", "model_name": "Ag24_neb", "task_type": "neb", "status": "running", "job_id": "42", "current_output": {"latest_dir": "con5"}},
            {"task_id": "t2", "model_name": "Ag24_opt", "task_type": "opt", "status": "completed"}]}
        self.rows = []
        for index in range(5):
            data = {"task_id": "t", "task_type": "neb", "checked_at": (datetime.now()-timedelta(minutes=index*10)).isoformat(),
                    "status": "running", "job_id": "42", "remote_dir": "/remote/task", "current_output": {"latest_dir": f"con{5-index}"},
                    "last_energy": -10+index, "force_max": 0.1+index*0.01, "neb_band_steps": 20-index,
                    "incar": {"ENCUT": 500}, "kpoints": {"mesh": [2, 2, 1]},
                    "force_history": [{"step": i, "energy": -i, "max_force": 0.1} for i in range(125)],
                    "neb_barrier": {"images": [{"label": "00", "energy": -10, "relative": 0, "max_force": 0.1}]}}
            self.rows.append({"observation_id": f"{index:024x}", "archive": f"check_results_{index}.json", "data": data})
        self.patches = [patch.object(inspections, "collect_task_observations", return_value=self.rows),
                        patch.object(inspections, "load_settings", return_value={"inspection_interval_hours": 2})]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def test_task_resolution_and_cross_project_boundary(self):
        result = inspections.find_tasks(self.project, "Ag24")
        self.assertEqual(result["total"], 2)
        self.assertEqual(inspections.find_tasks(self.project, "Ag24_neb")["matches"][0]["task_id"], "t")
        with self.assertRaises(PermissionDenied):
            workspace.dispatch(self.project, {}, {}, "get_task_inspections", {"task_id": "other-project"})
        for arguments in ({"task_id": "t", "limit": 6}, {"task_id": "t", "limit": True}, {"task_id": "t", "project_id": "foreign"}):
            with self.assertRaises(ValueError): workspace.dispatch(self.project, {}, {}, "get_task_inspections", arguments)

    def test_summary_default_three_and_stage_boundaries(self):
        result = workspace.dispatch(self.project, {}, {}, "get_task_inspections", {"task_id": "t"})
        self.assertEqual(result["returned"], 3)
        self.assertEqual(result["available"], 5)
        self.assertIsNone(result["comparisons"][0]["energy_delta_ev"])
        self.assertEqual(result["retention_unit"], "calculation_directory")
        self.assertFalse(result["freshness"]["stale_for_live_decision"])
        self.rows[1]["data"]["current_output"]["latest_dir"] = "con4"
        self.rows[2]["data"]["incar"]["ENCUT"] = 600
        changed = inspections.query_inspections(self.project, "t")
        self.assertIsNone(changed["comparisons"][0]["energy_delta_ev"])
        self.assertIn("output_dir", changed["comparisons"][0]["changed_identity_fields"])
        self.assertIn("parameters_sha256", changed["comparisons"][1]["changed_identity_fields"])

    def test_missing_observations_and_fields_are_not_filled_from_current_state(self):
        del self.rows[0]["data"]["force_max"]
        del self.rows[0]["data"]["job_id"]
        self.rows[:] = self.rows[:1]
        result = inspections.query_inspections(self.project, "t")
        self.assertEqual(result["returned"], 1)
        self.assertIsNone(result["observations"][0]["force_max_ev_per_a"])
        self.assertIsNone(result["observations"][0]["job_id"])
        self.assertTrue(any("只找到1个目录" in warning for warning in result["warnings"]))
        self.rows.clear()
        empty = inspections.query_inspections(self.project, "t")
        self.assertEqual(empty["returned"], 0)
        self.assertTrue(empty["freshness"]["stale_for_live_decision"])

    def test_stale_and_future_timestamps_are_explicit(self):
        self.rows[0]["data"]["checked_at"] = (datetime.now()-timedelta(days=1)).isoformat()
        self.assertTrue(inspections.query_inspections(self.project, "t")["freshness"]["stale_for_live_decision"])
        self.rows[0]["data"]["checked_at"] = (datetime.now()+timedelta(hours=1)).isoformat()
        self.assertTrue(inspections.query_inspections(self.project, "t")["freshness"]["stale_for_live_decision"])
        self.project["tasks"][0]["status"] = "archived"
        self.assertFalse(inspections.query_inspections(self.project, "t")["freshness"]["stale_for_live_decision"])

    def test_evidence_pagination_and_expired_observation(self):
        args = {"task_id": "t", "observation_id": self.rows[0]["observation_id"], "kind": "curves"}
        first = workspace.dispatch(self.project, {}, {}, "get_inspection_evidence", args)
        self.assertEqual(len(first["items"]), 60)
        self.assertEqual(first["next_offset"], 60)
        last = workspace.dispatch(self.project, {}, {}, "get_inspection_evidence", {**args, "offset": 120})
        self.assertEqual(len(last["items"]), 5)
        self.assertIsNone(last["next_offset"])
        neb = workspace.dispatch(self.project, {}, {}, "get_inspection_evidence", {**args, "kind": "neb"})
        self.assertEqual(neb["items"][0]["energy"], -10)
        self.assertFalse(neb["remote_verified"])
        self.rows.pop(0)
        with self.assertRaisesRegex(ValueError, "保留范围"):
            workspace.dispatch(self.project, {}, {}, "get_inspection_evidence", args)


if __name__ == "__main__": unittest.main()
