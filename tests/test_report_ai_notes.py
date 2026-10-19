"""R1：隔离报告/项目/私有连接 + 本机 Mock 模型；独立进程运行本文件。"""
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import sys
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request as URLRequest, urlopen

_DATA = tempfile.TemporaryDirectory(prefix="vasp-report-ai-")
os.environ.setdefault("VASP_WEB_DATA_DIR", _DATA.name)
os.environ.setdefault("VASP_AI_KEY_FILE", str(Path(_DATA.name) / "ai.key"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import config
import ai_chat_service as service
import ai_chat_store as connections
import report_ai_notes as ai
import report_store as store
import storage
import permissions
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from models import ProjectIn
from routers import project_reports, projects
from report_export import _notes_body

KEY = "mock-report-private-key-not-for-context-123456"
REQUESTS = []
SEEN = threading.Event()
RELEASE = threading.Event()
STREAM_READY = threading.Event()


class Client:
    """与既有 AI 测试一样走真实本机 HTTP，避免新增测试依赖。"""
    def __init__(self, port): self.base = f"http://127.0.0.1:{port}"
    def request(self, method, path, json=None, headers=None):
        import json as serializer
        req = URLRequest(self.base + path, method=method,
            data=serializer.dumps(json).encode() if json is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            text = response.read().decode()
            return type("Result", (), {"status_code": response.status, "text": text,
                "json": lambda self: serializer.loads(text)})()
    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def put(self, path, **kwargs): return self.request("PUT", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(body)
        mode = body["model"]
        SEEN.set()
        if mode == "slow":
            RELEASE.wait(3)
        if mode == "error":
            self.send_response(401); self.end_headers(); self.wfile.write(KEY.encode()); return
        value = json.loads(body["messages"][1]["content"])
        case = value["description_case"]
        text = {"analysis_note": "实际能量 -10.0 eV；离子尚未收敛，精度未验证。" +
                    {"A": "只陈述事实。", "B": "围绕计算内容组织结果，预期未提供。",
                     "C": "预期仅为关注点，不能作为证据。", "D": "实际未收敛，与预期收敛矛盾。"}[case],
                "paper_note": "**Results（事实）**：能量 -10.0 eV；未收敛。\n**Discussion（需证据）**：证据不足，不能确认机制。"}
        if mode == "schema": text = {"analysis_note": "x"}
        if mode == "sections": text["paper_note"] = "假定可靠"
        if mode == "sections-inline": text["paper_note"] = "提及 Results 和 Discussion，但没有事实/解释分段。"
        if mode == "reversed": text["paper_note"] = "**Discussion**：不确定。\n**Results**：结果。"
        if mode == "empty": text["analysis_note"] = ""
        if mode == "leak": text["analysis_note"] += KEY
        raw = "invalid {" if mode == "json" else json.dumps(text, ensure_ascii=False)
        delta = {"content": raw}
        if mode == "tool": delta = {"tool_calls": [{"function": {"name": "ssh"}}]}
        reason = "length" if mode == "truncated" else "stop"
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        try:
            # 与 DeepSeek 相同的 reasoning_content 不进入正文。
            self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING"}}]}\n\n')
            if mode == "hanging":
                self.wfile.flush(); STREAM_READY.set(); RELEASE.wait(3)
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": reason}]}) + "\n\n").encode())
            self.wfile.write(b'data: [DONE]\n\n')
        except (BrokenPipeError, ConnectionResetError):
            pass


def report():
    return {"schema_version": "1", "metadata": {"report_id": "rpt_p", "project_id": "p", "project_name": "ReportFixture",
        "generated_at": "2026-10-19T08:00:00", "units": {"energy": "eV", "force": "eV/A"}, "data_sources": ["mock inspection"]},
        "science": {"opt": [{"task_id": "t", "task_name": "Model", "final_energy_ev": -10.0,
                               "converged": False, "force_max_ev_per_a": 0.03}],
                    "neb": [{"task_id": "n", "task_name": "NEB", "barrier_ev": 0.5}],
                    "free_energy": [{"group_id": "g", "group_name": "Path", "structures": [
                        {"opt_task_id": "f", "structure_label": "A", "dft_energy_ev": -10.0, "correction_ev": None}]}],
                    "ele": {"tasks": [{"task_id": "e", "task_name": "PDOS", "efermi": -1.0}]}},
        "tasks": {"groups": [{"task_type": "opt", "tasks": [
            {"task_id": "t", "task_type": "opt", "job_id": "42", "latest_output_dir": "con6",
             "incar_snapshot": {"ENCUT": 400, "MAGMOM": "2*1.0 3*0.0"}, "precision": {"ok": False},
             "last_check_time": "2026-10-19T07:00:00"},
            {"task_id": "unrelated", "task_type": "opt", "last_energy_ev": -999.0},
            {"task_id": "f", "task_type": "opt", "group": {"group_id": "g"}},
            {"task_id": "freq", "task_type": "frac", "group": {"group_id": "g"}}]}]},
        "markdown_sections": [{"key": "science", "title": "科学结果", "markdown": "### 结构优化\n#### Model\n结果 -10.0 eV"}]}


class ReportAINotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if config.DATA_DIR.resolve() != Path(_DATA.name).resolve() or connections.KEY_PATH.resolve() != (Path(_DATA.name) / "ai.key").resolve():
            raise unittest.SkipTest("R1 测试必须独立进程运行，以隔离 DATA_DIR 和主密钥")
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.thread = threading.Thread(target=cls.provider.serve_forever, daemon=True); cls.thread.start()
        app = FastAPI()
        @app.middleware("http")
        async def identity(request: Request, call_next):
            name = request.headers.get("x-test-user", "alice")
            request.state.user = {"user_id": name, "username": name, "role": "agent" if name == "agent" else "user"}
            return await call_next(request)
        @app.exception_handler(permissions.PermissionDenied)
        async def forbidden(request, exc):
            return JSONResponse(status_code=403, content={"success": False, "message": str(exc)})
        app.include_router(project_reports.router, prefix="/api")
        app.include_router(projects.router, prefix="/api")
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        cls.web_thread = threading.Thread(target=lambda: cls.server.run(sockets=[sock]), daemon=True)
        cls.web_thread.start()
        deadline = time.monotonic() + 5
        while not cls.server.started and time.monotonic() < deadline: time.sleep(0.01)
        if not cls.server.started: raise RuntimeError("Mock 报告 API 启动失败")
        cls.client = Client(port)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True; cls.web_thread.join(5)
        cls.provider.shutdown(); cls.provider.server_close(); cls.thread.join(3)

    def setUp(self):
        self.user = {"user_id": "alice", "username": "alice", "role": "user"}
        self.project = {"project_id": "p", "name": "ReportFixture", "owner": "alice", "ai_report_notes_enabled": True,
            "calc_description": "", "expected_results": "", "tasks": []}
        storage.save_db({"projects": [self.project, {"project_id": "q", "name": "Off", "owner": "alice", "tasks": []}]})
        self.doc = report(); store.save_report(self.doc, "ordinary report", {})
        store._notes_path("rpt_p").unlink(missing_ok=True)
        REQUESTS.clear(); SEEN.clear(); RELEASE.clear(); STREAM_READY.clear()
        self.connection = connections.save_connection("alice", {
            "name": "My model", "base_url": f"http://127.0.0.1:{self.provider.server_port}", "model": "mock",
            "api_key": KEY, "max_tokens": 2048, "is_default": True, "thinking_mode": "default"})
        self.ssh = patch("ssh._get_client", side_effect=AssertionError("R1 must not use SSH"))
        self.ssh.start(); self.addCleanup(self.ssh.stop)

    def mode(self, name):
        with connections.database() as db:
            db.execute("UPDATE connections SET model=? WHERE id=?", (name, self.connection["id"]))

    def change_project(self, **values):
        with storage.db_transaction() as db:
            db["projects"][0].update(values)
        self.project.update(values)

    def generate(self, key="t", **payload):
        return self.client.post("/api/reports/project/rpt_p/notes/ai-preview", json={
            "key": key, "connection_id": self.connection["id"], **payload})

    def save(self, draft, **changes):
        return self.client.put("/api/reports/project/rpt_p/notes", json={
            "key": draft["key"], "analysis_note": draft["analysis_note"], "paper_note": draft["paper_note"],
            "draft_token": draft["draft_token"], **changes})

    def test_project_switch_default_and_independent_existing_edit_route(self):
        self.assertFalse(ProjectIn(name="Fixture", deadline="2026-12-01", server="mock").ai_report_notes_enabled)
        for pid, enabled in (("p", True), ("q", False), ("p", False), ("q", True)):
            result = self.client.put("/api/projects/" + pid, json={"ai_report_notes_enabled": enabled})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIs(result.json()["data"]["project"]["ai_report_notes_enabled"], enabled)
        denied = self.client.put("/api/projects/p", json={"ai_report_notes_enabled": True}, headers={"x-test-user": "bob"})
        self.assertEqual(denied.status_code, 403)

    def test_four_description_cases_actual_result_wins_over_expectations(self):
        for calc, expected, case in (("", "", "A"), ("OPT", "", "B"), ("", "应收敛", "C"), ("OPT", "应收敛", "D")):
            with self.subTest(case=case):
                self.change_project(calc_description=calc, expected_results=expected)
                response = self.generate(); self.assertEqual(response.status_code, 200, response.text)
                draft = response.json()["data"]
                self.assertIn("-10.0 eV", draft["analysis_note"])
                if case == "D": self.assertIn("与预期收敛矛盾", draft["analysis_note"])
                payload = REQUESTS[-1]
                value = json.loads(payload["messages"][1]["content"])
                self.assertEqual(value["description_case"], case)
                self.assertFalse(any(k in payload for k in ("tools", "functions")))
                self.assertEqual(value["tasks"][0]["latest_output_dir"], "con6")
                self.assertEqual(value["tasks"][0]["incar_snapshot"]["MAGMOM"], "2*1.0 3*0.0")
                self.assertNotIn("unrelated", json.dumps(value))
                self.assertNotIn(KEY, json.dumps(payload)); self.assertNotIn("PRIVATE_REASONING", response.text)
                self.assertEqual(store.read_notes("rpt_p"), {})

    def test_task_group_type_targets_scope_and_missing_evidence(self):
        self.assertEqual(set(ai.targets(self.doc)), {"type_opt", "t", "type_neb", "n", "type_free_energy", "path:g", "f", "type_ele"})
        value = ai.evidence(self.doc, self.project, "path:g")
        self.assertEqual({t["task_id"] for t in value["tasks"]}, {"f", "freq"})
        self.assertIn("UNKNOWN/NOT_TESTED", ai.PROMPT)
        self.assertIn("参考态/配平/温度", ai.PROMPT)
        self.assertEqual(self.generate("nonexistent").status_code, 400)

    def test_private_connection_and_project_permissions_including_admin(self):
        bob = connections.save_connection("bob", {"name": "Bob", "base_url": "http://localhost:1", "model": "mock",
            "api_key": KEY, "max_tokens": 1000, "is_default": True})
        self.assertEqual(self.generate(connection_id=bob["id"]).status_code, 403)
        self.assertEqual(self.client.post("/api/reports/project/rpt_p/notes/ai-preview", json={
            "key": "t", "connection_id": self.connection["id"]}, headers={"x-test-user": "bob"}).status_code, 403)
        self.assertEqual(self.client.post("/api/reports/project/rpt_p/notes/ai-preview", json={
            "key": "t", "connection_id": self.connection["id"]}, headers={"x-test-user": "agent"}).status_code, 403)
        with self.assertRaises((permissions.PermissionDenied, ValueError)):
            service.readonly_json_completion("admin", self.connection["id"], [])
        self.assertEqual(REQUESTS, [])

    def test_off_prevents_requests_keeps_manual_and_ai_notes(self):
        store.save_note("rpt_p", "t", "人工", "参考")
        draft = self.generate().json()["data"]
        self.change_project(ai_report_notes_enabled=False)
        before = len(REQUESTS)
        self.assertEqual(self.generate().status_code, 400)
        self.assertEqual(self.save(draft).status_code, 400)
        self.assertEqual(len(REQUESTS), before)
        saved = self.client.put("/api/reports/project/rpt_p/notes", json={"key": "t", "analysis_note": "人工编辑"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(store.read_notes("rpt_p")["t"]["analysis_note"], "人工编辑")
        long_manual = "长人工注解" * 5000
        saved = self.client.put("/api/reports/project/rpt_p/notes", json={"key": "t", "analysis_note": long_manual})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(store.read_notes("rpt_p")["t"]["analysis_note"], long_manual)

    def test_no_configured_model_clear_status_report_still_available(self):
        response = self.generate(connection_id="not-configured")
        self.assertEqual(response.status_code, 403)
        self.assertIn("无权访问", response.json()["message"])
        self.assertEqual(self.client.get("/api/reports/project/rpt_p").status_code, 200)
        with connections.database() as db:
            db.execute("DELETE FROM connections WHERE owner='alice'")
        response = self.generate()
        self.assertEqual(response.status_code, 400)
        self.assertIn("尚未配置自己的模型连接", response.json()["message"])
        self.assertEqual(self.client.get("/api/reports/project/rpt_p/export.html?interactive=0").status_code, 200)

    def test_preview_save_manual_edit_and_single_restore_slot(self):
        store.save_note("rpt_p", "t", "原人工分析", "原人工参考")
        draft = self.generate().json()["data"]
        self.assertEqual(store.read_notes("rpt_p")["t"]["analysis_note"], "原人工分析")
        saved = self.save(draft)
        self.assertEqual(saved.status_code, 200, saved.text)
        note = store.read_notes("rpt_p")["t"]
        self.assertEqual(note["source"], "ai"); self.assertEqual(note["model"], "mock")
        self.assertEqual(note["previous_note"]["analysis_note"], "原人工分析")
        self.assertNotIn("draft_token", json.dumps(note))
        restored = self.client.put("/api/reports/project/rpt_p/notes", json={"key": "t", "restore_previous": True,
            "expected_revision": note["revision"]})
        self.assertEqual(restored.status_code, 200)
        note = store.read_notes("rpt_p")["t"]
        self.assertEqual(note["source"], "manual"); self.assertEqual(note["analysis_note"], "原人工分析")
        self.assertNotIn("previous_note", note)
        draft = self.generate().json()["data"]
        self.assertEqual(self.save(draft, analysis_note="人工修订 AI").status_code, 200)
        note = store.read_notes("rpt_p")["t"]
        self.assertEqual(note["source"], "manual"); self.assertTrue(note["ai_origin"])

    def test_concurrent_manual_change_cannot_be_overwritten_by_old_draft(self):
        draft = self.generate().json()["data"]
        store.save_note("rpt_p", "t", "新人工文本", "")
        response = self.save(draft)
        self.assertEqual(response.status_code, 400); self.assertIn("已被其他操作修改", response.text)
        self.assertEqual(store.read_notes("rpt_p")["t"]["analysis_note"], "新人工文本")
        self.assertEqual(self.client.put("/api/reports/project/rpt_p/notes", json={"key": "t",
            "analysis_note": "旧窗口文本", "expected_revision": draft["base_revision"]}).status_code, 400)

    def test_data_changes_before_save_and_stale_after_regeneration(self):
        draft = self.generate().json()["data"]
        self.assertEqual(self.save(draft).status_code, 200)
        self.doc["metadata"]["generated_at"] = "2026-10-19T09:00:00"
        store.save_report(self.doc, "new report timestamp", {})
        notes = self.client.get("/api/reports/project/rpt_p/notes").json()["data"]["notes"]
        self.assertFalse(notes["t"]["stale"])
        draft2 = self.generate().json()["data"]
        self.doc["science"]["opt"][0]["force_max_ev_per_a"] = 0.01
        store.save_report(self.doc, "changed result", {})
        self.assertEqual(self.save(draft2).status_code, 400)
        detail = self.client.get("/api/reports/project/rpt_p").json()["data"]
        self.assertTrue(detail["notes"]["t"]["stale"])
        html = self.client.get("/api/reports/project/rpt_p/export.html?print=1&interactive=0").text
        self.assertIn("分析可能过期", html); self.assertIn("Results", html)
        self.assertIn("window.print", html)
        self.assertEqual(self.client.get("/api/reports/project/rpt_p/markdown").status_code, 200)

    def test_description_change_marks_ai_origin_manual_stale(self):
        draft = self.generate().json()["data"]
        self.save(draft, analysis_note="人工润色")
        self.change_project(expected_results="新的预期")
        self.assertTrue(self.client.get("/api/reports/project/rpt_p/notes").json()["data"]["notes"]["t"]["stale"])

    def test_provider_failures_isolated_and_errors_do_not_expose_key(self):
        store.save_note("rpt_p", "t", "人工不变", "")
        for mode in ("error", "json", "schema", "sections", "sections-inline", "reversed", "empty", "truncated", "tool"):
            self.mode(mode)
            response = self.generate()
            self.assertEqual(response.status_code, 400, response.text)
            self.assertNotIn(KEY, response.text)
            self.assertEqual(store.read_notes("rpt_p")["t"]["analysis_note"], "人工不变")
            self.assertEqual(self.client.get("/api/reports/project/rpt_p").status_code, 200)
        self.assertEqual(self.client.get("/api/reports/project/rpt_p/export.html?interactive=0").status_code, 200)
        self.mode("leak")
        response = self.generate()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(KEY, response.text)

    def test_timeout_and_connection_failure_keep_report(self):
        for exc in (TimeoutError(), OSError("sensitive error " + KEY)):
            with patch.object(service, "_open", side_effect=exc):
                response = self.generate()
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(KEY, response.text)
            self.assertEqual(self.client.get("/api/reports/project/rpt_p").status_code, 200)

    def test_cancel_and_mid_generation_changes_discard_no_save(self):
        self.mode("slow")
        control = service.TextGenerationControl()
        with __import__('concurrent.futures').futures.ThreadPoolExecutor() as pool:
            job = pool.submit(ai.preview, "rpt_p", "t", self.user, self.connection["id"], control)
            self.assertTrue(SEEN.wait(2)); control.cancel(); RELEASE.set()
            with self.assertRaisesRegex(ValueError, "取消"):
                job.result(3)
        self.assertEqual(store.read_notes("rpt_p"), {})
        SEEN.clear(); RELEASE.clear()
        with __import__('concurrent.futures').futures.ThreadPoolExecutor() as pool:
            job = pool.submit(ai.preview, "rpt_p", "t", self.user, self.connection["id"], service.TextGenerationControl())
            self.assertTrue(SEEN.wait(2))
            self.change_project(calc_description="生成期间修改")
            RELEASE.set()
            with self.assertRaisesRegex(ValueError, "变化"):
                job.result(3)

    def test_http_disconnect_cancels_upstream_and_report_remains_responsive(self):
        self.mode("hanging")
        from urllib.parse import urlsplit
        conn = HTTPConnection("127.0.0.1", urlsplit(self.client.base).port, timeout=5)
        conn.request("POST", "/api/reports/project/rpt_p/notes/ai-preview", json.dumps({
            "key": "t", "connection_id": self.connection["id"]}), {"Content-Type": "application/json"})
        try:
            self.assertTrue(STREAM_READY.wait(2))
            started = time.monotonic()
            self.assertEqual(self.client.get("/api/reports/project/rpt_p").status_code, 200)
            self.assertLess(time.monotonic() - started, 1, "模型等待不能阻塞普通报告读取")
            conn.close()
            deadline = time.monotonic() + 2
            while "alice" in ai._busy and time.monotonic() < deadline: time.sleep(0.01)
            self.assertNotIn("alice", ai._busy, "浏览器断开应中断模型读取并释放并发位")
            self.assertEqual(store.read_notes("rpt_p"), {})
        finally:
            conn.close(); RELEASE.set()

    def test_deepseek_uses_existing_payload_and_private_connection(self):
        with connections.database() as db:
            db.execute("UPDATE connections SET base_url=?,model=? WHERE id=?",
                       ("https://api.deepseek.com", "deepseek-flash", self.connection["id"]))
        original = service._open
        def mock_upstream(connection, key, path, payload):
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertNotIn("tools", payload)
            return original({**connection, "base_url": f"http://127.0.0.1:{self.provider.server_port}"}, key, path, payload)
        with patch.object(service, "_open", side_effect=mock_upstream):
            result = self.generate()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn("PRIVATE_REASONING", result.text)

    def test_complete_data_fingerprint_detects_omitted_tail_changes(self):
        self.doc["science"]["opt"][0]["details"] = list(range(100))
        before = ai.digest(ai.evidence(self.doc, self.project, "t"))
        self.doc["science"]["opt"][0]["details"][-1] = 101
        self.assertNotEqual(before, ai.digest(ai.evidence(self.doc, self.project, "t")))

    def test_busy_limit_released_after_cancel(self):
        ai._busy.add("alice")
        try:
            self.assertEqual(self.generate().status_code, 400)
        finally:
            ai._busy.discard("alice")
        self.assertEqual(self.generate().status_code, 200)

    def test_forged_or_replayed_draft_and_metadata_cannot_override_manual(self):
        draft = self.generate().json()["data"]
        self.assertEqual(self.save(draft, key="n").status_code, 400)
        self.assertEqual(self.save(draft, draft_token="forged").status_code, 400)
        self.assertEqual(self.save(draft).status_code, 200)
        self.assertEqual(self.save(draft).status_code, 400)
        response = self.client.put("/api/reports/project/rpt_p/notes", json={"key": "n", "analysis_note": "手工",
            "source": "ai", "model": "forged", "input_fingerprint": "forged"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(store.read_notes("rpt_p")["n"]["source"], "manual")
        self.assertNotIn("model", store.read_notes("rpt_p")["n"])

    def test_xss_export_escapes_html_links_and_protocols(self):
        class Tags(HTMLParser):
            def __init__(self): super().__init__(); self.tags = []
            def handle_starttag(self, tag, attrs): self.tags.append((tag, dict(attrs)))
        dangerous = '<script>alert(1)</script> [x](javascript:alert) [x](https://x/"onmouseover="alert) [x](data:text/html,x)'
        html = _notes_body(dangerous)
        parser = Tags(); parser.feed(html)
        self.assertFalse(any(tag == "script" or any(k.startswith("on") for k in attrs) for tag, attrs in parser.tags))
        self.assertFalse(any(attrs.get("href", "").startswith(("javascript:", "data:")) for _, attrs in parser.tags))
        self.assertIn("&lt;script&gt;", html)

    def test_ordinary_generation_never_calls_model(self):
        with patch.object(project_reports, "build_report", return_value={"report": self.doc, "markdown": "ordinary", "charts": {}}), \
             patch.object(service, "readonly_json_completion", side_effect=AssertionError("ordinary report must not call AI")):
            response = self.client.post("/api/reports/project/generate", json={"project_id": "p"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(REQUESTS, [])
        self.assertEqual(self.client.get("/api/reports/project/rpt_p/export.html?print=1&interactive=0").status_code, 200)


if __name__ == "__main__":
    unittest.main()
