"""托管计划（M0）：隔离数据目录、确定性函数，不连接 SSH、不调用模型、不提交作业。"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend")]

_TEMP = tempfile.TemporaryDirectory(prefix="vasp-managed-")
os.environ["VASP_WEB_DATA_DIR"] = str(Path(_TEMP.name) / "data")
os.environ.pop("VASP_SSH_MOCK", None)

import config  # noqa: E402

if config.DATA_DIR.resolve() != (Path(_TEMP.name) / "data").resolve():
    raise unittest.SkipTest("需独立进程运行 tests/test_managed_plan.py")

import auth  # noqa: E402
import managed_plan  # noqa: E402
import managed_schedule  # noqa: E402
import permissions  # noqa: E402
import storage  # noqa: E402
from automation import audit  # noqa: E402
from routers import managed as managed_router  # noqa: E402

NOW = datetime(2026, 10, 20, 14, 0, tzinfo=timezone(timedelta(hours=8)))


def _snapshot(source="real", queried_at=None, stale=False):
    return {
        "source": source,
        "queriedAt": (queried_at or NOW).isoformat(timespec="seconds"),
        "stale": stale,
        "cacheTtlSeconds": 300,
        "queues": [
            {"queue": "normal_2week", "nodeCount": 14, "idleCores": 600, "bqueues": {"pending": 5}},
            {"queue": "ocean_530_1day", "nodeCount": 28, "idleCores": 300, "bqueues": {"pending": 1}},
            {"queue": "paid_q", "nodeCount": 4, "idleCores": 100, "bqueues": {"pending": 0}},
            {"queue": "empty_q", "nodeCount": 0, "idleCores": 0, "bqueues": {"pending": 0}},
        ],
    }


SERVER_CFG = {
    "node_groups": [
        {"queue": "normal_2week", "cores_per_node": 48, "walltime_days": 14, "paid": False,
         "suspend_risk": "low", "start": 1, "end": 14},
        {"queue": "ocean_530_1day", "cores_per_node": 24, "walltime_days": 1, "paid": False,
         "suspend_risk": "high", "start": 1, "end": 28},
        {"queue": "paid_q", "cores_per_node": 32, "walltime_days": 1, "paid": True,
         "suspend_risk": "low", "start": 1, "end": 4},
        {"queue": "empty_q", "cores_per_node": 24, "walltime_days": 1, "paid": False,
         "suspend_risk": "low", "start": 1, "end": 1},
    ]
}

RULES = {
    "queues_allowed": ["normal_2week", "ocean_530_1day", "paid_q", "empty_q"],
    "queues_denied": [],
    "paid_allowed": False,
    "max_nodes": 2,
    "max_cores": 96,
    "cores_per_node": 48,
    "max_walltime_hours": 24,
    "max_core_hours": 5000,
}


class ManagedPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.ensure_data_dirs()
        cls.alice, _ = auth.create_user("alice", "MockPassword123!", role="user")
        cls.bob, _ = auth.create_user("bob", "MockPassword123!", role="user")
        db = {
            "projects": [
                {"name": "P1", "server": "server1", "owner": "alice", "tasks": [
                    {"task_id": "t1", "task_type": "opt", "status": "pending", "model_name": "m1", "remote_dir": "P1/T1"},
                    {"task_id": "t2", "task_type": "opt", "status": "unconverged", "model_name": "m2", "remote_dir": "P1/T2"},
                    {"task_id": "t3", "task_type": "opt", "status": "running", "model_name": "m3", "remote_dir": "P1/T3"},
                    {"task_id": "t4", "task_type": "opt", "status": "completed", "model_name": "m4", "remote_dir": "P1/T4"},
                    {"task_id": "t5", "task_type": "opt", "status": "archived", "model_name": "m5", "remote_dir": "P1/T5"},
                ]},
                {"name": "P2", "server": "server1", "owner": "bob", "tasks": [
                    {"task_id": "b1", "task_type": "opt", "status": "pending", "model_name": "bm", "remote_dir": "P2/B1"},
                ]},
            ]
        }
        storage.save_db(db, backup=False)

    def setUp(self):
        managed_plan.FILE.unlink(missing_ok=True)
        audit.AUDIT_FILE.unlink(missing_ok=True)
        self.plan = managed_plan.create(self.alice, {
            "project": "P1",
            "goal": {"text": "这个项目周五先交 model1 的阶段报告", "summary": "周五交 model1 阶段报告"},
            "stages": [
                {"title": "阶段报告", "task_ids": ["t1"], "due": "2026-10-23", "priority": 90,
                 "source_quote": "周五先交 model1 的阶段报告"},
                {"title": "后续补算", "task_ids": ["t2"], "priority": 10},
            ],
            "resource_rules": RULES,
        })

    # ---------------------------------------------------------- 计划落库

    def test_plan_is_written_under_isolated_data_dir(self):
        self.assertEqual(managed_plan.FILE.parent, config.DATA_DIR)
        doc = json.loads(managed_plan.FILE.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], managed_plan.SCHEMA)
        self.assertEqual(self.plan["status"], "active")
        self.assertEqual(self.plan["revision"], 1)
        self.assertEqual(self.plan["goal"]["text"], "这个项目周五先交 model1 的阶段报告")
        self.assertEqual(len(self.plan["stages"]), 2)

    def test_foreign_project_and_task_are_rejected(self):
        with self.assertRaises(permissions.PermissionDenied):
            managed_plan.create(self.alice, {"project": "P2", "goal": {"text": "x"}})
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.create(self.alice, {"project": "P1", "goal": {"text": "x"},
                                             "stages": [{"title": "s", "task_ids": ["b1"]}]})

    def test_invalid_due_queue_and_unknown_field_are_rejected(self):
        base = {"project": "P1", "goal": {"text": "x"}}
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.create(self.alice, {**base, "stages": [{"title": "s", "task_ids": ["t1"], "due": "周五"}]})
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.create(self.alice, {**base, "resource_rules": {"queues_allowed": ["bad queue"]}})
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.create(self.alice, {**base, "deploy": True})

    def test_audit_records_plan_changes(self):
        managed_plan.patch(self.plan["id"], self.alice, 1, {"status": "paused"}, source="human")
        rows = [json.loads(line) for line in audit.AUDIT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
        actions = [r.get("action") for r in rows]
        self.assertIn("managed.plan.create", actions)
        self.assertIn("managed.plan.patch", actions)
        self.assertTrue(all(r.get("trigger") == "managed" for r in rows))

    # ---------------------------------------------------------- 版本与锁定

    def test_revision_conflict_prevents_lost_update(self):
        first = managed_plan.patch(self.plan["id"], self.alice, 1, {"goal_summary": "A"}, source="human")
        self.assertEqual(first["revision"], 2)
        with self.assertRaises(managed_plan.ManagedError) as ctx:
            managed_plan.patch(self.plan["id"], self.alice, 1, {"goal_summary": "B"}, source="human")
        self.assertEqual(ctx.exception.code, 409)

    def test_human_lock_blocks_ai_override_but_not_human(self):
        locked = managed_plan.patch(self.plan["id"], self.alice, 1, {
            "task_overrides": [{"task_id": "t1", "priority": 80, "locked": True}]}, source="human")
        self.assertEqual(locked["revision"], 2)
        with self.assertRaises(managed_plan.ManagedError) as ctx:
            managed_plan.patch(locked["id"], self.alice, 2, {
                "task_overrides": [{"task_id": "t1", "priority": 5}]}, source="ai")
        self.assertEqual(ctx.exception.code, 409)
        unlocked = managed_plan.patch(locked["id"], self.alice, 2, {
            "task_overrides": [{"task_id": "t1", "priority": 5, "locked": False}]}, source="human")
        self.assertEqual(unlocked["task_overrides"]["t1"]["priority"], 5)

    def test_ai_cannot_end_plan(self):
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.patch(self.plan["id"], self.alice, 1, {"status": "ended"}, source="ai")

        ended = managed_plan.set_status(self.plan["id"], self.alice, "ended")
        self.assertEqual(ended["status"], "ended")
        with self.assertRaises(managed_plan.ManagedError):
            managed_plan.patch(ended["id"], self.alice, ended["revision"], {"goal_summary": "x"}, source="human")

    # ---------------------------------------------------------- 候选排序

    def test_candidates_order_by_priority_then_due(self):
        project = storage.load_db()["projects"][0]
        summary = managed_schedule.summary(self.plan, project)
        actionable = [r for r in summary["candidates"] if r["action"]]
        self.assertEqual([r["task_id"] for r in actionable], ["t1", "t2"])
        self.assertEqual(summary["next"]["task_id"], "t1")
        self.assertEqual(summary["next"]["action"], "task.submit")
        self.assertEqual(summary["counts"], {"ready": 1, "continuation": 1, "in_flight": 1})
        self.assertEqual(summary["waiting"][0]["task_id"], "t2")
        self.assertEqual(summary["waiting"][0]["action"], "task.continuation")
        # 在跑任务保留在列表里解释，但不排进可推进动作；completed / archived 不出现。
        self.assertIn("t3", [r["task_id"] for r in summary["candidates"]])
        self.assertNotIn("t4", [r["task_id"] for r in summary["candidates"]])
        self.assertNotIn("t5", [r["task_id"] for r in summary["candidates"]])
        self.assertTrue(summary["next"]["locked"] is False)

    def test_task_override_beats_stage_priority(self):
        updated = managed_plan.patch(self.plan["id"], self.alice, 1, {
            "task_overrides": [{"task_id": "t2", "priority": 100}]}, source="human")
        summary = managed_schedule.summary(updated, storage.load_db()["projects"][0])
        self.assertEqual(summary["next"]["task_id"], "t2")
        self.assertEqual(summary["next"]["priority_source"], "override")

    def test_paused_plan_reports_needs_user(self):
        paused = managed_plan.patch(self.plan["id"], self.alice, 1, {"status": "paused"}, source="human")
        summary = managed_schedule.summary(paused, storage.load_db()["projects"][0])
        self.assertIn("计划已暂停：不会自动推进", summary["needs_user"])

    # ---------------------------------------------------------- 资源评分

    def test_resource_plan_filters_paid_and_empty_queues(self):
        result = managed_schedule.resource_plan(self.plan, SERVER_CFG, _snapshot(), now=NOW)
        self.assertEqual(result["state"], "ok", result["reason"])
        reasons = {row["queue"]: row["reason"] for row in result["filtered"]}
        self.assertIn("付费队列", reasons.get("paid_q", ""))
        self.assertIn("没有节点", reasons.get("empty_q", ""))
        self.assertTrue(all(c["queue"] != "paid_q" for c in result["candidates"]))
        for candidate in result["candidates"]:
            self.assertEqual(candidate["cores"], candidate["nodes"] * candidate["cores_per_node"])
            self.assertIsInstance(candidate["score"], float)
            self.assertTrue(candidate["explain"])

    def test_resource_plan_is_deterministic(self):
        first = managed_schedule.resource_plan(self.plan, SERVER_CFG, _snapshot(), now=NOW)
        second = managed_schedule.resource_plan(self.plan, SERVER_CFG, _snapshot(), now=NOW)
        self.assertEqual(first, second)

    def test_mock_or_stale_snapshot_blocks_auto_choice(self):
        mock = managed_schedule.resource_plan(self.plan, SERVER_CFG, _snapshot(source="mock"), now=NOW)
        self.assertEqual(mock["state"], "blocked")
        self.assertIn("模拟", mock["reason"])
        stale = managed_schedule.resource_plan(
            self.plan, SERVER_CFG, _snapshot(queried_at=NOW - timedelta(hours=2)), now=NOW)
        self.assertEqual(stale["state"], "blocked")
        self.assertIn("未更新", stale["reason"])
        missing = managed_schedule.resource_plan(self.plan, SERVER_CFG, None, now=NOW)
        self.assertEqual(missing["state"], "blocked")

    def test_resource_plan_without_allowed_queues_waits(self):
        plan = managed_plan.patch(self.plan["id"], self.alice, 1, {"resource_rules": {"queues_allowed": []}},
                                  source="human")
        result = managed_schedule.resource_plan(plan, SERVER_CFG, _snapshot(), now=NOW)
        self.assertEqual(result["state"], "waiting")
        self.assertIn("未声明可用队列", result["reason"])

    def test_resource_plan_respects_max_nodes_and_core_hours(self):
        plan = managed_plan.patch(self.plan["id"], self.alice, 1, {
            "resource_rules": {"max_nodes": 1, "max_core_hours": 100, "max_walltime_hours": 2}}, source="human")
        result = managed_schedule.resource_plan(plan, SERVER_CFG, _snapshot(), now=NOW)
        self.assertTrue(all(c["nodes"] == 1 for c in result["candidates"]))
        self.assertTrue(all(c["core_hours"] <= 100 for c in result["candidates"]))
        self.assertTrue(result["candidates"], result["filtered"])

    # ---------------------------------------------------------- 工具合同

    def test_tool_rejects_unknown_fields_and_foreign_plan(self):
        from managed_tools import dispatch

        project = storage.load_db()["projects"][0]
        with self.assertRaises(ValueError):
            dispatch(project, self.alice, "get_managed_plans", {"plan_id": self.plan["id"], "extra": 1})
        with self.assertRaises(permissions.PermissionDenied):
            dispatch(project, self.bob, "get_managed_plans", {"plan_id": self.plan["id"]})

    def test_tool_create_and_read_plan_with_ai_source(self):
        from managed_tools import dispatch

        project = storage.load_db()["projects"][0]
        created = dispatch(project, self.alice, "create_managed_plan", {
            "goal": {"text": "把 model2 排到后面，先把 model1 跑完"},
            "resource_rules": {"queues_allowed": ["normal_2week"]},
        })
        self.assertEqual(created["summary"]["next"]["task_id"], "t1")
        listed = dispatch(project, self.alice, "get_managed_plans", {})
        self.assertEqual(len(listed["plans"]), 2)
        updated = dispatch(project, self.alice, "set_task_priority", {
            "plan_id": created["plan"]["id"], "revision": 1, "task_id": "t2", "priority": 70, "reason": "用户说后做"})
        self.assertEqual(updated["plan"]["task_overrides"]["t2"]["source"], "ai")

    def test_router_exposes_read_only_endpoints(self):
        paths = {route.path for route in managed_router.router.routes}
        for expected in ("/managed", "/managed/plans", "/managed/plans/{plan_id}",
                         "/managed/plans/{plan_id}/candidates", "/managed/plans/{plan_id}/resource-plan"):
            self.assertIn(expected, paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
