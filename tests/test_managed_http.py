"""托管计划真实 HTTP 路径：鉴权、版本冲突、跨用户 403、只读资源/脚本预览。

隔离数据目录 + 本进程 uvicorn；没有 SSH/模型/真实 HPC 调用（服务器配置为空，
集群采集在读节点映射前就返回，不发起 SSH）。
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend")]

_TEMP = tempfile.TemporaryDirectory(prefix="vasp-managed-http-")
os.environ["VASP_WEB_DATA_DIR"] = str(Path(_TEMP.name) / "data")
os.environ.pop("VASP_SSH_MOCK", None)
os.environ.pop("VASP_MOCK_REMOTE_ROOT", None)

import config  # noqa: E402

if config.DATA_DIR.resolve() != (Path(_TEMP.name) / "data").resolve():
    raise unittest.SkipTest("需独立进程运行 tests/test_managed_http.py")

import auth  # noqa: E402
import storage  # noqa: E402
import cluster_probe  # noqa: E402
from unittest.mock import patch  # noqa: E402


class ManagedHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.ensure_data_dirs()
        # 测试绝不连接真实集群：集群采集固定返回空采集（界面按“模拟/缺数据”处理）。
        cls.probe = patch.object(
            cluster_probe, "probe",
            lambda *args, **kwargs: {"sections": {}, "error": "测试隔离：不采集真实集群",
                                     "queriedAt": "2026-10-20T14:00:00+08:00", "cached": False,
                                     "stale": False, "cacheAgeSeconds": 0, "cacheTtlSeconds": 300},
        )
        cls.probe.start()
        cls.alice, _ = auth.create_user("alice", "MockPassword123!", role="user")
        cls.bob, _ = auth.create_user("bob", "MockPassword123!", role="user")
        cls.alice_token, _ = auth.create_session(cls.alice)
        cls.bob_token, _ = auth.create_session(cls.bob)
        storage.save_db({"projects": [
            {"name": "P1", "server": "server1", "owner": "alice", "tasks": [
                {"task_id": "t1", "task_type": "opt", "status": "pending", "model_name": "m1", "remote_dir": "P1/T1"},
                {"task_id": "t2", "task_type": "opt", "status": "unconverged", "model_name": "m2", "remote_dir": "P1/T2"},
            ]},
        ]}, backup=False)

        import uvicorn
        from main import app

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port,
                                                   log_level="error", lifespan="on"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                urlopen(f"http://127.0.0.1:{cls.port}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("托管接口测试服务启动超时")
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.probe.stop()
        _TEMP.cleanup()

    @classmethod
    def api(cls, path, method="GET", body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(cls.base + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            payload = json.loads(response.read().decode())
            return response.status, payload

    def create_plan(self):
        status, payload = self.api("/api/managed/plans", "POST", {
            "project": "P1",
            "goal": {"text": "周五先交 model1 的阶段报告", "summary": "周五交 model1 阶段报告"},
            "stages": [{"title": "阶段报告", "task_ids": ["t1"], "due": "2026-10-23", "priority": 90}],
            "resource_rules": {"queues_allowed": ["normal_2week"]},
        }, token=self.alice_token)
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["success"])
        return payload["data"]

    def test_unauthorized_then_authorized(self):
        status, payload = self.api("/api/managed")
        self.assertEqual(status, 401, payload)
        self.assertFalse(payload["success"])
        status, payload = self.api("/api/managed", token=self.alice_token)
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["data"]["execution_enabled"])

    def test_create_list_and_cross_user_forbidden(self):
        data = self.create_plan()
        plan_id = data["plan"]["id"]
        self.assertEqual(data["summary"]["next"]["task_id"], "t1")
        status, payload = self.api("/api/managed", token=self.alice_token)
        self.assertEqual(status, 200)
        self.assertIn(plan_id, [item["plan"]["id"] for item in payload["data"]["plans"]])
        status, payload = self.api("/api/managed/plans/" + plan_id, token=self.bob_token)
        self.assertEqual(status, 403, payload)

    def test_revision_conflict_and_validation(self):
        plan_id = self.create_plan()["plan"]["id"]
        status, payload = self.api(f"/api/managed/plans/{plan_id}", "PATCH",
                                   {"revision": 1, "status": "paused"}, token=self.alice_token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["data"]["plan"]["revision"], 2)
        status, payload = self.api(f"/api/managed/plans/{plan_id}", "PATCH",
                                   {"revision": 1, "status": "active"}, token=self.alice_token)
        self.assertEqual(status, 409, payload)
        self.assertIn("已被更新", payload["message"])
        status, payload = self.api(f"/api/managed/plans/{plan_id}", "PATCH",
                                   {"revision": 2, "deploy": True}, token=self.alice_token)
        self.assertEqual(status, 400, payload)

    def test_read_only_resource_and_script_preview(self):
        plan_id = self.create_plan()["plan"]["id"]
        status, payload = self.api(f"/api/managed/plans/{plan_id}/resource-plan", token=self.alice_token)
        self.assertEqual(status, 200, payload)
        # 测试夹具不提供真实集群数据 → 必须等待，不能拿模拟数据自动选资源。
        self.assertEqual(payload["data"]["state"], "blocked")
        self.assertFalse(payload["data"].get("candidates"))
        status, payload = self.api(f"/api/managed/plans/{plan_id}/script-preview", token=self.alice_token)
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["data"]["written"])

    def test_end_plan_then_reject_changes(self):
        plan_id = self.create_plan()["plan"]["id"]
        status, payload = self.api(f"/api/managed/plans/{plan_id}/status", "POST",
                                   {"status": "ended"}, token=self.alice_token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["data"]["plan"]["status"], "ended")
        status, payload = self.api(f"/api/managed/plans/{plan_id}", "PATCH",
                                   {"revision": 2, "goal_summary": "x"}, token=self.alice_token)
        self.assertEqual(status, 409, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
