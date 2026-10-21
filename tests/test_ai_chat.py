"""AI 工作台端到端：真实 HTTP/SSE + 模拟模型，隔离数据，不触碰生产账号/SSH。"""
import copy
from contextlib import closing
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_DATA = tempfile.TemporaryDirectory(prefix="vasp-ai-test-")
os.environ.setdefault("VASP_WEB_DATA_DIR", _DATA.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import ai_chat_service as service
import ai_chat_store as store
import ai_workspace as workspace
import checks_store
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from middleware.auth import install
import permissions
from routers import ai_chat
import uvicorn

KEY = "test-private-key-never-in-client-123456789"
USERS = {name: {"user_id": name, "username": name, "role": "user"} for name in ("alice", "bob")}
PROJECTS = {"projects": [{"project_id": name, "name": name, "owner": name,
    "tasks": [{"task_id": f"task-{name}", "model_name": f"Model-{name}", "task_type": "neb", "status": "completed",
               "current_output": {"latest_dir": "con4"}, "last_analysis_dir": "con4"}]} for name in USERS]}
PROJECTS["projects"][0]["tasks"].extend([
    {"task_id": "task-alice-extra", "model_name": "Model-alice-extra", "task_type": "opt", "status": "unconverged"},
    {"task_id": "task-alice-aux", "model_name": "hidden", "task_type": "opt", "dir_path": "alice/opt/model/con1", "status": "completed"},
])
REQUESTS = []


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b'{"data":[{"id":"mock-model"}]}')

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(payload)
        if payload["model"] == "error-model":
            self.send_response(401); self.end_headers(); self.wfile.write(KEY.encode()); return
        if payload["model"] == "redirect-model":
            self.send_response(307); self.send_header("Location", "/stolen"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        if payload['model']=='deepseek-workspace':
            self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE_TOOL_REASONING"}}]}\n\n')
        if payload["model"] in ("deepseek-workspace","workspace-model", "workspace-loop", "workspace-blocked", "inspection-model", "parameter-model"):
            count = sum(m.get("role") == "tool" for m in payload["messages"])
            if count < (4 if payload["model"] == "inspection-model" else 3) or payload["model"] == "workspace-loop":
                choices = [
                    ("list_workspace", {"path": "project"}),
                    ("read_workspace", {"path": "project/neb/Model-alice/files/CONTCAR"}),
                    ("write_workspace", {"path": "work/CONTCAR.v1", "content": "candidate structure draft"}),
                ]
                name, args = choices[min(count, 2)]
                if payload["model"] == "inspection-model":
                    previous = [json.loads(m["content"]) for m in payload["messages"] if m.get("role") == "tool"]
                    inspection_choices = [
                        ("find_project_tasks", {"query": "Model-alice"}),
                        ("get_task_inspections", {"task_id": "task-alice"}),
                        ("get_inspection_evidence", {"task_id": "task-alice", "observation_id": previous[1]["observations"][0]["observation_id"] if count >= 2 else "", "kind": "curves"}),
                        ("write_workspace", {"path": "work/inspection-plan.md", "content": "基于三个目录最新结果分阶段分析；仅保存计划草稿，未执行计算"}),
                    ]
                    name, args = inspection_choices[count]
                if payload['model'] == 'parameter-model':
                    previous = [json.loads(m['content']) for m in payload['messages'] if m.get('role') == 'tool']
                    name, args = [
                        ('get_task_inspections',{'task_id':'task-alice'}),
                        ('get_task_parameter_history',{'task_id':'task-alice'}),
                        ('get_remote_task_evidence',{'task_id':'task-alice','evidence_token':previous[0]['evidence_token'] if previous else '', 'reason':'stale_evidence'}),
                    ][count]
                if payload["model"] == "workspace-blocked":
                    name, args = "read_workspace", {"path": "project/../bob/private.txt"}
                arguments = json.dumps(args)
                fragments = [{"index": 0, "id": f"call_{count}", "type": "function", "function": {"name": name, "arguments": arguments[:5]}},
                             {"index": 0, "function": {"arguments": arguments[5:]}}]
                for fragment in fragments:
                    self.wfile.write(("data: "+json.dumps({"choices": [{"delta": {"tool_calls": [fragment]}, "finish_reason": None}]})+"\n\n").encode())
                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"total_tokens":7}}\n\ndata: [DONE]\n\n')
                self.wfile.flush(); return
        if payload["model"].startswith("deepseek-"):
            self.wfile.write(b': keep-alive\n\ndata: {"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING_TEST"},"finish_reason":null}]}\n\n')
        text = "模拟回答：已有结果符合本地快照；仍需核对预期。" + KEY
        if payload["model"] == "inspection-model":
            evidence = [json.loads(m["content"]) for m in payload["messages"] if m.get("role") == "tool"][1]
            text = f"已按需查询{evidence['returned']}个目录的最新结果；最近目录{evidence['observations'][0]['output_dir']}，存在阶段切换，计划仅保存草稿。" + KEY
        if payload["model"] == "deepseek-only-thinking":
            text = ""
        if payload["model"] == "deepseek-thinking-retry":
            retried = any(m.get("role") == "system" and "直接给出最终回答" in str(m.get("content"))
                          for m in payload["messages"])
            text = "直接回答：结构没问题，建议先补齐收敛证据。" if retried else ""
        if payload["model"] == "malformed-tools":
            text = '准备报告。<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="save_topic_report">伪造参数</｜｜DSML｜｜ invoke>'
        if payload["model"] == "slow-model":
            text *= 8
        try:
            for i in range(0, len(text), 5):
                data = {"choices": [{"delta": {"content": text[i:i+5]}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode()); self.wfile.flush()
                if payload["model"] == "slow-model": time.sleep(0.01)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":42}}\n\ndata: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class AIChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vasp-ai-http-")
        cls.patches = [patch.object(store, "AI_DIR", Path(cls.temp.name)/"ai"),
                       patch.object(checks_store, "CHECKS_DIR", Path(cls.temp.name)/"checks"),
                       patch.object(store, "KEY_PATH", Path(cls.temp.name)/"private/master.key"),
                       patch.object(service, "load_db", return_value=PROJECTS),
                       patch.object(ai_chat, "load_db", return_value=PROJECTS),
                       patch.object(service, "merged_results", return_value={
                           "task-alice": {"checked_at": "2026-10-18T20:00:00", "status": "completed", "last_energy": -1.0, "current_output": {"latest_dir": "con4"}},
                           "task-bob": {"checked_at": "2026-10-18T20:00:00", "last_energy": -99.0},
                       }),
                       patch.object(service, "AUDIT_FILE", Path(cls.temp.name)/"actions.jsonl"),
                       patch.object(workspace, "DATA_DIR", Path(cls.temp.name)),
                       patch.object(workspace, "load_servers", return_value={"server1": {"queue_system": "lsf", "password": KEY}}),
                       patch("paths.load_path_mapping", return_value={"local_root": str(Path(cls.temp.name)/"projects"), "remote_roots": {"server1": "/remote/projects"}}),
                       patch("task_paths.PROJECTS_DIR", Path(cls.temp.name)/"projects"),
                       patch("auth.verify_token", side_effect=lambda token, **kwargs: ({}, USERS[token]) if token in USERS else None)]
        for p in cls.patches: p.start()
        app = FastAPI(); install(app); app.include_router(ai_chat.router, prefix="/api")
        @app.exception_handler(permissions.PermissionDenied)
        async def denied(_, exc):
            return JSONResponse(status_code=403, content={"success": False, "message": exc.message})
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.provider.daemon_threads = True
        cls.provider_thread = threading.Thread(target=cls.provider.serve_forever, daemon=True); cls.provider_thread.start()
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(20)
        cls.base = f"http://127.0.0.1:{sock.getsockname()[1]}/api/ai/chat"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [sock]}, daemon=True); cls.thread.start()
        deadline = time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline: time.sleep(0.01)
        assert cls.server.started

    @classmethod
    def tearDownClass(cls):
        time.sleep(1.5)  # 等模拟慢流退出；不会等待真实模型。
        cls.server.should_exit = True; cls.thread.join(5)
        cls.provider.shutdown(); cls.provider.server_close(); cls.provider_thread.join(2)
        for p in reversed(cls.patches): p.stop()
        cls.temp.cleanup()

    def api(self, path, method="GET", body=None, user="alice", raw=False):
        request = Request(self.base+path, data=json.dumps(body).encode() if body is not None else (b"" if method=="POST" else None),
                          method=method, headers={"Authorization": "Bearer "+user, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                data = response.read().decode()
                self.assertNotIn(KEY, data)
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                return response.status, data if raw else json.loads(data)["data"]
        except HTTPError as error:
            data = error.read().decode(); error.close(); self.assertNotIn(KEY, data)
            return error.code, json.loads(data)

    def connection(self, model="mock-model", user="alice"):
        status, result = self.api("/connections", "POST", {"name": "模拟模型", "base_url": f"http://127.0.0.1:{self.provider.server_port}/v1",
             "model": model, "api_key": KEY, "max_tokens": 128}, user)
        self.assertEqual(status, 200, result)
        return result

    def conversation(self, connection, task=None):
        status, result = self.api("/conversations", "POST", {"title": "test", "connection_id": connection["id"], "task_id": task})
        self.assertEqual(status, 200, result); return result

    def send(self, conversation, retry=False, request_id=None):
        return self.api(f"/conversations/{conversation['id']}/messages", "POST", {"content": "分析当前结果", "retry": retry, "request_id": request_id or store.uid()})

    def wait_run(self, run):
        for _ in range(150):
            _, result = self.api(f"/runs/{run['id']}")
            if result["status"] not in ("queued", "running"): return result
            time.sleep(0.02)
        self.fail("模拟运行未结束")

    def test_encryption_secret_roundtrip_and_owner_isolation(self):
        connection = self.connection()
        self.assertTrue(connection["key_configured"])
        self.assertNotIn("secret", connection); self.assertNotIn("api_key", connection)
        with store.database() as db:
            row = store.owned(db, "connections", connection["id"], "alice")
            self.assertNotEqual(row["secret"], KEY); self.assertEqual(store.decrypt(row["secret"]), KEY)
        self.assertEqual(store.KEY_PATH.stat().st_mode & 0o777, 0o600)
        _, own = self.api("/connections"); _, other = self.api("/connections", user="bob")
        self.assertTrue(any(x["id"]==connection["id"] for x in own["items"]))
        self.assertFalse(any(x["id"]==connection["id"] for x in other["items"]))
        self.assertEqual(self.api(f"/connections/{connection['id']}", "DELETE", user="bob")[0], 403)

    def test_connection_test_and_destination_change_requires_new_key(self):
        connection = self.connection()
        _, result = self.api(f"/connections/{connection['id']}/test", "POST")
        self.assertTrue(result["model_listed"])
        body = {"name": "renamed", "base_url": connection["base_url"], "model": "mock-model", "max_tokens": 128}
        self.assertEqual(self.api(f"/connections/{connection['id']}", "PUT", body)[0], 200)
        body["base_url"] = "https://other.example/v1"
        self.assertEqual(self.api(f"/connections/{connection['id']}", "PUT", body)[0], 400)

    def test_task_context_and_cross_user_conversation_access(self):
        connection = self.connection(); conversation = self.conversation(connection, "task-alice")
        self.assertEqual(self.api(f"/conversations/{conversation['id']}", user="bob")[0], 403)
        self.assertEqual(self.api("/conversations", "POST", {"title": "bad", "task_id": "task-bob"})[0], 403)
        _, targets = self.api("/targets"); self.assertEqual([p["name"] for p in targets["items"]], ["alice"])
        _, context = self.api(f"/conversations/{conversation['id']}/context")
        self.assertEqual(context["scope"], "project")
        self.assertEqual(context["project"]["project_id"], "alice")
        self.assertIn("task-alice", [t["task_id"] for t in context["tasks"]])
        self.assertNotIn("task-bob", [t["task_id"] for t in context["tasks"]])
        general = self.conversation(connection)
        _, context = self.api(f"/conversations/{general['id']}/context")
        self.assertEqual(context["scope"], "general"); self.assertNotIn("task", context)

    def test_multiturn_retry_snapshot_and_idempotent_send(self):
        connection = self.connection(); conversation = self.conversation(connection, "task-alice")
        code, run = self.send(conversation, request_id="same-request-123")
        self.assertEqual(code, 200, run)
        self.assertEqual(self.wait_run(run)["status"], "completed")
        _, duplicate = self.send(conversation, request_id="same-request-123")
        self.assertEqual(run["id"], duplicate["id"])
        _, before = self.api(f"/conversations/{conversation['id']}")
        self.assertEqual(len(before["messages"]), 2)
        self.assertIn("[已隐藏凭据]", before["messages"][-1]["content"])
        _, again = self.send(conversation)
        snapshot = self.wait_run(again)["snapshot"]
        self.assertEqual(snapshot["history_messages"], 2)
        self.assertEqual(snapshot["context"]["project"]["project_id"], "alice")
        _, retried = self.send(conversation, retry=True)
        self.assertEqual(self.wait_run(retried)["status"], "completed")
        _, after = self.api(f"/conversations/{conversation['id']}")
        self.assertEqual(sum(m["role"]=="user" for m in after["messages"]), 2)
        self.assertEqual(self.api(f"/runs/{run['id']}", user="bob")[0], 403)
        _, events = self.api(f"/runs/{run['id']}/events", raw=True)
        self.assertIn('"status": "completed"', events)
        self.assertEqual({t["function"]["name"] for t in REQUESTS[-1]["tools"]},
                         {"list_workspace", "read_workspace", "write_workspace", "find_project_tasks", "get_task_inspections", "get_inspection_evidence", "get_opt_runs", "get_task_parameter_history", "get_remote_task_evidence", "get_property_recipes", "discover_property_tasks", "evaluate_property", "list_topic_projects", "prepare_topic_report", "plan_topic_report", "write_topic_draft", "save_topic_report", "get_topic_report", "create_topic_report", "search_report_data", "update_topic_report", "get_managed_plans", "create_managed_plan", "update_managed_plan", "set_task_priority"})

    def test_stop_and_single_active_run(self):
        connection = self.connection("slow-model"); conversation = self.conversation(connection)
        _, run = self.send(conversation)
        self.assertEqual(self.send(conversation)[0], 400)
        self.assertEqual(self.api(f"/runs/{run['id']}/cancel", "POST")[0], 200)
        self.assertEqual(self.wait_run(run)["status"], "cancelled")

    def test_provider_error_and_redirect_do_not_leak_secrets(self):
        for model in ("error-model", "redirect-model"):
            with self.subTest(model=model):
                conversation = self.conversation(self.connection(model))
                _, run = self.send(conversation)
                result = self.wait_run(run)
                self.assertEqual(result["status"], "failed")
                self.assertNotIn(KEY, json.dumps(result))

    def test_prompt_version_and_recovery_keep_partial_message(self):
        connection = self.connection(); conversation = self.conversation(connection)
        _, updated = self.api(f"/conversations/{conversation['id']}", "PUT", {"title": "new", "connection_id": connection["id"], "prompt": "分析证据"})
        self.assertEqual(updated["prompt_version"], 2)
        _, run = self.send(conversation)
        self.assertEqual(self.wait_run(run)["prompt_version"], 2)
        with store.database() as db:
            db.execute("UPDATE runs SET status='running' WHERE id=?", (run["id"],))
            db.execute("UPDATE messages SET content='partial',status='running' WHERE id=?", (run["message_id"],))
        store.recover_runs()
        self.assertEqual(self.wait_run(run)["status"], "interrupted")
        _, after = self.api(f"/conversations/{conversation['id']}")
        self.assertEqual(after["messages"][-1]["content"], "partial")

    def test_url_and_credential_redaction(self):
        for bad in ("http://example.com/v1", "https://user:pass@example.com/v1", "https://example.com/v1?api_key=bad", "https://169.254.169.254/v1"):
            with self.subTest(url=bad), self.assertRaises(ValueError): service.normalize_url(bad)
        self.assertEqual(service.normalize_url("https://example.com/v1/chat/completions"), "https://example.com/v1")
        data = service.clean({"password": "secret", "text": f"Bearer abcdefghijkl api_key={KEY}"}, (KEY,))
        self.assertNotIn(KEY, json.dumps(data)); self.assertEqual(data["password"], "[已隐藏]")

    def test_remote_plain_http_cannot_save_keys_and_revoked_task_is_hidden(self):
        from starlette.requests import Request as StarletteRequest
        request = StarletteRequest({"type": "http", "method": "POST", "path": "/", "scheme": "http",
                                    "headers": [], "server": ("server", 3001), "client": ("203.0.113.20", 1234)})
        with self.assertRaises(ValueError): ai_chat.secure_key_transport(request)
        conversation = self.conversation(self.connection(), "task-alice")
        revoked = copy.deepcopy(PROJECTS); revoked["projects"][0]["owner"] = "bob"
        with patch.object(service, "load_db", return_value=revoked), patch.object(ai_chat, "load_db", return_value=revoked):
            self.assertEqual(self.api(f"/conversations/{conversation['id']}")[0], 403)
            _, listing = self.api("/conversations")
            self.assertFalse(any(c["id"]==conversation["id"] for c in listing["items"]))

    def test_context_budget_and_message_pagination_preserve_history(self):
        huge = {"project": {"name": "test"}, "task": {"task_id": "t"}, "files": {f"file{i}": "x"*20000 for i in range(50)}}
        bounded = service._context_budget(huge)
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False)), service.CONTEXT_CHARS)
        conversation = self.conversation(self.connection())
        with store.database() as db:
            for i in range(90):
                db.execute("INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (?,?, 'user',?,'completed','2026-10-18')",
                           (store.uid(), conversation["id"], str(i)))
        _, latest = self.api(f"/conversations/{conversation['id']}")
        self.assertEqual(len(latest["messages"]), 80); self.assertTrue(latest["has_more"])
        _, older = self.api(f"/conversations/{conversation['id']}?before={latest['messages'][0]['seq']}")
        self.assertEqual(len(older["messages"]), 10); self.assertFalse(older["has_more"])

    def test_deepseek_payload_modes_and_other_providers_unchanged(self):
        connection = {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash", "max_tokens": 8192, "thinking_mode": "disabled"}
        payload = service.completion_payload(connection, [{"role": "user", "content": "test"}])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertTrue(payload["stream_options"]["include_usage"])
        connection.update(model="deepseek-v4-pro", thinking_mode="enabled")
        self.assertEqual(service.completion_payload(connection, [])["thinking"], {"type": "enabled"})
        connection["thinking_mode"] = "default"
        self.assertNotIn("thinking", service.completion_payload(connection, []))
        connection.update(base_url="https://other.example/v1", thinking_mode="enabled")
        self.assertNotIn("thinking", service.completion_payload(connection, []))
        self.assertNotIn("stream_options", service.completion_payload(connection, []))
        connection["model"] = "gpt-6-astra"
        self.assertIn("max_completion_tokens", service.completion_payload(connection, []))
        connection.update(base_url="https://api.deepseek.com", model="deepseek-reasoner")
        self.assertNotIn("thinking", service.completion_payload(connection, []))

    def test_deepseek_reasoning_stream_and_multiturn_only_keep_answer(self):
        connection = self.connection("deepseek-flash")
        body = {"name": "DeepSeek mock", "base_url": connection["base_url"], "model": "deepseek-flash", "thinking_mode": "enabled", "max_tokens": 8192}
        _, updated = self.api(f"/connections/{connection['id']}", "PUT", body)
        self.assertEqual(updated["thinking_mode"], "enabled")
        conversation = self.conversation(updated)
        _, run = self.send(conversation)
        result = self.wait_run(run)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["snapshot"]["connection"]["thinking_mode"], "enabled")
        _, run = self.send(conversation)
        self.assertEqual(self.wait_run(run)["status"], "completed")
        _, detail = self.api(f"/conversations/{conversation['id']}")
        # 思考链路只用于「可选展示」：存进本次 run、绝不回到消息正文和历史请求。
        self.assertTrue(any("PRIVATE_REASONING_TEST" in (r.get("reasoning") or "") for r in detail["runs"]))
        self.assertTrue(all("PRIVATE_REASONING_TEST" not in m["content"] for m in detail["messages"]))
        self.assertNotIn("reasoning_content", json.dumps(REQUESTS[-1]))
        self.assertEqual(detail["runs"][0]["usage"]["total_tokens"], 42)

    def test_existing_connection_migration_preserves_encrypted_key(self):
        with tempfile.TemporaryDirectory() as root, patch.object(store, "AI_DIR", Path(root)):
            secret = store.encrypt(KEY)
            with closing(sqlite3.connect(Path(root)/"chat.sqlite3")) as db, db:
                db.execute("CREATE TABLE connections(id TEXT PRIMARY KEY,owner TEXT,name TEXT,base_url TEXT,model TEXT,secret TEXT,max_tokens INTEGER,is_default INTEGER,created_at TEXT,updated_at TEXT)")
                db.execute("INSERT INTO connections VALUES (?,?,?,?,?,?,?,?,?,?)", ("old", "alice", "old", "https://api.deepseek.com", "deepseek-flash", secret, 2048, 1, "old", "old"))
            migrated = store.connections("alice")[0]
            self.assertEqual(migrated["thinking_mode"], "default")
            self.assertEqual(migrated["reasoning_api"],"auto")
            self.assertEqual(migrated["reasoning_effort"],"default")
            with store.database() as db:
                row = store.owned(db, "connections", "old", "alice")
                self.assertEqual(row["secret"], secret)
                self.assertEqual(store.decrypt(row["secret"]), KEY)

    def test_reasoning_connection_save_request_snapshot_and_key_retention(self):
        connection=self.connection('gpt-5.2')
        body={k:connection[k] for k in ('name','base_url','model','max_tokens','is_default')}
        body.update(reasoning_api='openai',reasoning_effort='xhigh')
        status,updated=self.api('/connections/'+connection['id'],'PUT',body)
        self.assertEqual(status,200,updated);self.assertEqual(updated['reasoning_effort'],'xhigh')
        self.assertTrue(updated['key_configured'])
        _,run=self.send(self.conversation(updated));run=self.wait_run(run)
        self.assertEqual(run['status'],'completed',run)
        self.assertEqual(REQUESTS[-1]['reasoning_effort'],'xhigh')
        self.assertEqual(run['snapshot']['connection']['effective_reasoning_effort'],'xhigh')
        self.assertNotIn(KEY,json.dumps(updated))
        legacy={k:body[k] for k in ('name','base_url','model','max_tokens','is_default')}
        self.assertEqual(self.api('/connections/'+connection['id'],'PUT',legacy)[1]['reasoning_effort'],'xhigh')
        body['reasoning_effort']='max'
        self.assertEqual(self.api('/connections/'+connection['id'],'PUT',body)[0],400)
        self.assertEqual(next(c for c in self.api('/connections')[1]['items'] if c['id']==connection['id'])['reasoning_effort'],'xhigh')

    def test_deepseek_tools_honor_depth_and_reasoning_is_display_only(self):
        connection=self.connection('deepseek-workspace')
        body={k:connection[k] for k in ('name','base_url','model','max_tokens','is_default')}
        body.update(reasoning_api='deepseek',reasoning_effort='max')
        status,connection=self.api('/connections/'+connection['id'],'PUT',body)
        self.assertEqual(status,200)
        _,run=self.send(self.conversation(connection,'task-alice'));run=self.wait_run(run)
        self.assertEqual(run['status'],'completed',run)
        self.assertEqual(len(run['tool_events']),3)
        self.assertEqual(REQUESTS[-1]['reasoning_effort'],'max')
        self.assertEqual(REQUESTS[-1]['thinking'],{'type':'enabled'})
        assistants=[m for m in REQUESTS[-1]['messages'] if m.get('tool_calls')]
        self.assertTrue(all(m['reasoning_content']=='PRIVATE_TOOL_REASONING' for m in assistants))
        self.assertIn('PRIVATE_TOOL_REASONING', run.get('reasoning') or '')
        _,detail=self.api('/conversations/'+run['conversation_id'])
        # 展示用：只存在本次 run 里，不进入消息正文/历史请求。
        self.assertTrue(all('PRIVATE_TOOL_REASONING' not in m['content'] for m in detail['messages']))
        self.assertTrue(any('PRIVATE_TOOL_REASONING' in (r.get('reasoning') or '') for r in detail['runs']))

    def test_readonly_report_json_honors_depth_without_persisting_thoughts(self):
        import io
        connection=self.connection('deepseek-flash')
        body={k:connection[k] for k in ('name','base_url','model','max_tokens','is_default')}
        body.update(reasoning_api='deepseek',reasoning_effort='max')
        self.assertEqual(self.api('/connections/'+connection['id'],'PUT',body)[0],200)
        frames=[{'choices':[{'delta':{'reasoning_content':'PRIVATE_JSON_REASONING'}}]},
                {'choices':[{'delta':{'content':json.dumps({'text':'safe paragraph'})},'finish_reason':'stop'}]}]
        raw=(''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames)+'data: [DONE]\n\n').encode()
        with patch.object(service,'_open',return_value=io.BytesIO(raw)) as opened:
            result,model=service.readonly_json_completion('alice',connection['id'],[{'role':'user','content':'return JSON'}])
        self.assertEqual(result,{'text':'safe paragraph'})
        payload=opened.call_args.args[-1]
        self.assertEqual(payload['reasoning_effort'],'max');self.assertEqual(payload['thinking'],{'type':'enabled'})
        self.assertNotIn('tools',payload);self.assertNotIn('PRIVATE_JSON_REASONING',json.dumps(result))

    def test_capability_endpoint_and_unsupported_tool_combination(self):
        from urllib.parse import urlencode
        status,caps=self.api('/reasoning-capabilities?'+urlencode({'base_url':'https://api.deepseek.com','model':'deepseek-v4-pro'}))
        self.assertEqual(status,200);self.assertEqual([o['value'] for o in caps['options']],['default','none','low','high','max'])
        with self.assertRaises(ValueError):service.ai_reasoning.validate_tools({'base_url':'https://api.openai.com/v1','model':'gpt-6.1-sol'},True)
        with self.assertRaises(ValueError):service.ai_reasoning.validate_tools({'base_url':'https://api.openai.com/v1','model':'gpt-6-sol','reasoning_effort':'high'},True)
        service.ai_reasoning.validate_tools({'base_url':'https://api.openai.com/v1','model':'gpt-6-sol','reasoning_effort':'none'},True)
        connection=self.connection('gpt-6.1-sol')
        body={k:connection[k] for k in ('name','base_url','model','max_tokens','is_default')}
        body.update(reasoning_api='openai',reasoning_effort='high')
        _,connection=self.api('/connections/'+connection['id'],'PUT',body)
        conversation=self.conversation(connection,'task-alice')
        before=len(REQUESTS)
        status,run=self.api('/conversations/'+conversation['id']+'/messages','POST',{'content':'研究项目','request_id':store.uid()})
        # 工具是模型能力：不支持工具的型号降级为摘要回答，本轮不发送工具定义，而不是整次失败。
        self.assertEqual(status,200,run)
        result=self.wait_run(run)
        self.assertEqual(result['status'],'completed',result)
        self.assertFalse(result['snapshot']['workspace_enabled'])
        self.assertIn('tools_disabled_reason',result['snapshot'])
        self.assertNotIn('tools',REQUESTS[-1])
        self.assertEqual(len(REQUESTS),before+1)

    def test_deepseek_without_final_answer_explains_output_budget(self):
        conversation = self.conversation(self.connection("deepseek-only-thinking"))
        _, run = self.send(conversation)
        result = self.wait_run(run)
        self.assertEqual(result["status"], "failed")
        self.assertIn("输出额度", result["error"])
        self.assertIn("最大输出", result["error"])
        self.assertIn("PRIVATE_REASONING_TEST", result.get("reasoning") or "")

    def test_thinking_only_reply_retries_with_direct_answer(self):
        conversation = self.conversation(self.connection("deepseek-thinking-retry"))
        _, run = self.send(conversation)
        result = self.wait_run(run)
        # 只有思考没有正文时，自动补一次“直接回答”；思考仍保留可展示。
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("PRIVATE_REASONING_TEST", result.get("reasoning") or "")
        _, detail = self.api(f"/conversations/{conversation['id']}")
        self.assertIn("直接回答", detail["messages"][-1]["content"])

    def test_project_attachment_covers_members_and_filters_actions(self):
        connection = self.connection()
        code, conversation = self.api("/conversations", "POST", {"title": "project", "project_id": "alice", "connection_id": connection["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(conversation["project_id"], "alice")
        self.assertIsNone(conversation["task_id"])
        self.assertEqual(self.api("/conversations", "POST", {"title": "bad", "project_id": "bob"})[0], 403)
        service.AUDIT_FILE.write_text('\n'.join(json.dumps({"task_id": f"task-{name}", "command": "submit", "result": "ok", "username": name}) for name in ("alice", "bob")))
        _, context = self.api(f"/conversations/{conversation['id']}/context")
        self.assertEqual(context["summary"]["task_count"], 2)
        self.assertEqual({t["task_id"] for t in context["tasks"]}, {"task-alice", "task-alice-extra"})
        self.assertEqual([a["task_id"] for a in context["actions"]["recent"]], ["task-alice"])
        _, run = self.send(conversation)
        result = self.wait_run(run)
        self.assertEqual(result["snapshot"]["context"]["scope"], "project")
        self.assertEqual(len(result["snapshot"]["context"]["tasks"]), 2)

    def test_legacy_task_conversation_migrates_without_losing_messages(self):
        connection = self.connection()
        legacy = store.create_conversation("alice", "old task chat", "task-alice", connection["id"])
        orphan = store.create_conversation("alice", "orphan", "removed-task", connection["id"])
        with store.database() as db:
            db.execute("INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (?,?, 'user','keep history','completed','old')", (store.uid(), legacy["id"]))
        service.migrate_project_conversations()
        _, migrated = self.api(f"/conversations/{legacy['id']}")
        self.assertEqual(migrated["project_id"], "alice")
        self.assertEqual(migrated["task_id"], "task-alice")
        self.assertEqual(migrated["messages"][0]["content"], "keep history")
        self.assertEqual(migrated["title"], "old task chat")
        self.assertTrue(migrated["workspace_enabled"])
        self.assertEqual(self.api(f"/conversations/{orphan['id']}")[0], 403)
        _, listing = self.api("/conversations")
        self.assertFalse(any(c["id"]==orphan["id"] for c in listing["items"]))

    def test_workspace_map_and_file_isolation(self):
        connection = self.connection()
        conversation = self.conversation(connection, "task-alice")
        prefix = f"/conversations/{conversation['id']}/workspace"
        root = Path(self.temp.name)/"projects/alice"
        files = root/"neb/Model-alice/files"
        files.mkdir(parents=True, exist_ok=True)
        (files/"CONTCAR").write_text("fractional coordinates 0.4347 0.6692 0.4225")
        outside = Path(self.temp.name)/"outside-private.txt"
        outside.write_text("must never leave host")
        link = files/"outside.txt"
        if link.is_symlink(): link.unlink()
        link.symlink_to(outside)
        (root/"secret.pem").write_text("not a model file")
        _, result = self.api(prefix)
        self.assertTrue(result["enabled"])
        self.assertEqual(len(result["task_locations"]), 2)
        self.assertEqual(result["task_locations"][0]["path"], "project/neb/Model-alice")
        _, listing = self.api(prefix+"/files?path=project/neb/Model-alice/files")
        self.assertNotIn("outside.txt", [x["name"] for x in listing["items"]])
        status, result = self.api(prefix+"/file?path=project/neb/Model-alice/files/CONTCAR")
        self.assertEqual(status, 200, result)
        self.assertIn("0.4347", result["content"])
        self.assertEqual(result["hash_scope"], "returned_bytes")
        for path in ("project/../outside-private.txt", "/etc/passwd", "project/secret.pem", "project/.env", "evidence/history/task-bob.json", "users/users.json"):
            self.assertEqual(self.api(prefix+"/file?path="+path)[0], 400, path)
        self.assertNotEqual(self.api(prefix+"/file?path=project/neb/Model-alice/files/outside.txt")[0], 200)
        self.assertEqual(self.api(prefix, user="bob")[0], 403)
        other = self.conversation(connection, "task-alice")
        project = PROJECTS["projects"][0]
        with store.database() as db:
            row = store.owned(db, "conversations", conversation["id"], "alice")
        workspace.writing(project, row, "work/draft-unique.txt", "new draft")
        self.assertEqual(self.api(prefix+"/file?path=work/draft-unique.txt")[0], 200)
        self.assertNotEqual(self.api(f"/conversations/{other['id']}/workspace/file?path=work/draft-unique.txt")[0], 200)
        with self.assertRaises(ValueError): workspace.writing(project, row, "project/INCAR", "bad")
        with self.assertRaises(ValueError): workspace.writing(project, row, "work/draft-unique.txt", "replace")
        with self.assertRaises(ValueError): workspace.writing(project, row, "work/large.txt", "x"*(workspace.WRITE_LIMIT+1))
        with self.assertRaises(ValueError): workspace.dispatch(project, row, {}, "exec", {"path": "project"})
        with self.assertRaises(ValueError): workspace.dispatch(project, row, {}, "read_workspace", {"path": "project", "offset": -1})
        with self.assertRaises(ValueError): workspace.dispatch(project, row, {}, "read_workspace", {"path": "project", "host_path": "/etc/passwd"})
        work = workspace.roots(project, row)["work"]
        (work/"escape").symlink_to(outside.parent, target_is_directory=True)
        with self.assertRaises(ValueError): workspace.writing(project, row, "work/escape/unsafe.txt", "bad")
        self.assertFalse((outside.parent/"unsafe.txt").exists())
        # 文件分片有边界和真实字节哈希，尾部读取不读取整个大文件。
        (files/"large.txt").write_text("A"*(workspace.READ_LIMIT+7)+"END")
        piece = workspace.reading(project, row, {}, "project/neb/Model-alice/files/large.txt")
        self.assertEqual(piece["next_offset"], workspace.READ_LIMIT)
        self.assertTrue(workspace.reading(project, row, {}, "project/neb/Model-alice/files/large.txt", tail=True)["content"].endswith("END"))
        self.assertEqual((files/"CONTCAR").read_text(), "fractional coordinates 0.4347 0.6692 0.4225")
        revoked = copy.deepcopy(PROJECTS)
        revoked["projects"][0]["owner"] = "bob"
        with patch.object(service, "load_db", return_value=revoked):
            self.assertEqual(self.api(prefix)[0], 403)
            self.assertEqual(self.api(prefix+"/files?path=work")[0], 403)
        self.assertEqual(self.api(f"/conversations/{conversation['id']}", "DELETE")[0], 200)
        self.assertFalse(work.exists())
        self.assertTrue((files/"CONTCAR").is_file())

    def test_workspace_model_tools_stream_audit_and_draft(self):
        connection = self.connection("workspace-model")
        conversation = self.conversation(connection, "task-alice")
        files = Path(self.temp.name)/"projects/alice/neb/Model-alice/files"
        files.mkdir(parents=True, exist_ok=True)
        (files/"CONTCAR").write_text("real local structure")
        status, run = self.send(conversation)
        self.assertEqual(status, 200, run)
        result = self.wait_run(run)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([event["name"] for event in result["tool_events"]], ["list_workspace", "read_workspace", "write_workspace"])
        self.assertEqual(result["usage"]["total_tokens"], 63)
        self.assertIn("real local structure", result["tool_events"][1]["result"]["content"])
        self.assertFalse(result["tool_events"][2]["result"]["applied"])
        _, file = self.api(f"/conversations/{conversation['id']}/workspace/file?path=work/CONTCAR.v1")
        self.assertEqual(file["content"], "candidate structure draft")
        self.assertTrue(result["snapshot"]["workspace_enabled"])
        context = result["snapshot"]["context"]
        self.assertNotIn("directory_map", context)
        self.assertTrue(all("workspace_path" not in task for task in context["tasks"]))
        self.assertIn("evidence/directory-map.json", context["workspace_rules"]["map"])
        _, directory_map = self.api(f"/conversations/{conversation['id']}/workspace/file?path=evidence/directory-map.json")
        self.assertIn("task_locations", directory_map["content"])
        self.assertIn("project/neb/Model-alice", directory_map["content"])
        # 工具由模型按需选择，不再由会话开关控制：旧字段被忽略，下一轮仍提供工具定义。
        self.assertEqual(self.api(f"/conversations/{conversation['id']}", "PUT", {
            "title": "tools always on", "prompt": "", "connection_id": connection["id"],
            "workspace_enabled": False})[0], 200)
        _, changed = self.api(f"/conversations/{conversation['id']}")
        self.assertTrue(changed["workspace_enabled"])
        plain = self.connection()
        self.api(f"/conversations/{conversation['id']}", "PUT", {"title": "plain", "prompt": "", "connection_id": plain["id"]})
        _, next_run = self.send(conversation)
        self.assertEqual(self.wait_run(next_run)["status"], "completed")
        self.assertIn("tools", REQUESTS[-1])

    def test_tool_markup_in_text_is_noted_not_executed_or_shown(self):
        conversation=self.conversation(self.connection('malformed-tools'),'task-alice')
        _,run=self.send(conversation)
        result=self.wait_run(run)
        # 收尾不再把已完成的工作标成失败：保留正文 + 说明未执行的那一步。
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['tool_events'],[])
        _,detail=self.api(f"/conversations/{conversation['id']}")
        content=detail['messages'][-1]['content']
        self.assertNotIn('DSML',content)
        self.assertIn('准备报告',content)
        self.assertIn('没有按标准格式发出',content)

    def test_workspace_tool_loop_and_forbidden_read_are_bounded(self):
        conversation = self.conversation(self.connection("workspace-blocked"), "task-alice")
        _, run = self.send(conversation)
        result = self.wait_run(run)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(all(e["status"] == "failed" for e in result["tool_events"]))
        self.assertNotIn("must never leave host", json.dumps(result))
        looping = self.conversation(self.connection("workspace-loop"), "task-alice")
        _, run = self.send(looping)
        result = self.wait_run(run)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["tool_events"]), 8)
        self.assertIn("上限", result["error"])

    def test_model_queries_recent_inspections_then_evidence_and_plan_on_demand(self):
        task_id = "task-alice"
        for index in range(3):
            row = {"task_id": task_id, "task_type": "neb", "checked_at": f"2026-10-18T2{index}:00:00",
                   "status": "running", "remote_dir": "/remote/model", "job_id": "42" if index else "41",
                   "current_output": {"latest_dir": f"con{index+4}"},
                   "last_energy": -10-index, "incar": {"ENCUT": 500}, "kpoints": {"mesh": [2, 2, 1]},
                   "force_history": [{"step": index, "energy": -10-index, "max_force": 0.2-index*0.05}]}
            checks_store.archive_results([row], "mock", f"inspection{index}")
        connection = self.connection("inspection-model")
        conversation = self.conversation(connection, task_id)
        current = copy.deepcopy(PROJECTS)
        current["projects"][0]["tasks"][0].update(status="running", job_id="42", current_output={"latest_dir": "con6"})
        with patch.object(service, "load_db", return_value=current):
            status, run = self.send(conversation)
            self.assertEqual(status, 200, run)
            result = self.wait_run(run)
        self.assertEqual(result["status"], "completed", result)
        events = result["tool_events"]
        self.assertEqual([e["name"] for e in events], ["find_project_tasks", "get_task_inspections", "get_inspection_evidence", "write_workspace"])
        self.assertEqual(result["usage"]["total_tokens"], 70)
        evidence = events[1]["result"]
        self.assertEqual(evidence["returned"], 3)
        self.assertEqual([row["output_dir"] for row in evidence["observations"]], ["con6", "con5", "con4"])
        self.assertEqual(evidence["retention_unit"], "calculation_directory")
        self.assertFalse(evidence["comparisons"][0]["same_observed_stage"])
        self.assertIsNone(evidence["comparisons"][1]["energy_delta_ev"])
        self.assertFalse(evidence["evidence"]["inherited_fields"])
        self.assertEqual(events[2]["result"]["items"][0]["step"], 2)
        self.assertFalse(events[3]["result"]["applied"])
        self.assertNotIn("observations", result["snapshot"]["context"])
        self.assertIn("get_task_inspections", result["snapshot"]["context"]["workspace_rules"]["inspections"])
        _, detail = self.api(f"/conversations/{conversation['id']}")
        self.assertIn("按需查询3个目录", detail["messages"][-1]["content"])

    def test_model_checks_age_then_actual_parameters_then_readonly_current_state(self):
        import ai_inspections
        import ai_remote_evidence
        import parameter_history
        checks_patch=patch.object(checks_store,'CHECKS_DIR',Path(self.temp.name)/'parameter-checks')
        checks_patch.start()
        def cleanup_checks():
            checks_patch.stop()
            checks_store.invalidate_cache()
        self.addCleanup(cleanup_checks)
        current=copy.deepcopy(PROJECTS)
        project=current['projects'][0]
        project['server']='fixture'
        task=project['tasks'][0]
        task.update(status='running',job_id='42',remote_dir='/remote/model',current_output={'latest_dir':'con6'})
        task['input_state']=parameter_history.append({},event='upload',directory='/remote/model/con6',
            before={'INCAR':{'NSW':'100'}},after={'INCAR':{'NSW':'200'}})
        checks_store.archive_results([{'task_id':'task-alice','task_type':'neb','checked_at':(datetime.now()-timedelta(hours=5)).isoformat(),
            'status':'running','remote_dir':'/remote/model','job_id':'42','current_output':{'latest_dir':'con6'},
            'incar':{'NSW':'100'},'kpoints':{'mesh':[1,1,1]}}],'mock','stale-parameter-evidence')
        sample={'samples':[{'requested':'CURRENT','directory':'con6','files':{
            'INCAR':{'text':'NSW = 200\nMAGMOM = 2*1.0 3*0.0\n','stable':True,'truncated':False,'mtime':1},
            'KPOINTS':{'text':'grid\n0\nGamma\n1 1 1\n0 0 0\n','stable':True,'truncated':False,'mtime':1}},'images':[]}],
            'current_directory':'con6','sampled_epoch':1,'text_budget_bytes':24000,'remaining_bytes':23000}
        output=json.dumps(sample)+'\n@@@LSF_BEGIN\n42|RUN|/remote/model/con6|fixture-job\n@@@LSF_RC=0\n'
        connection=self.connection('parameter-model')
        conversation=self.conversation(connection,'task-alice')
        ai_remote_evidence._CACHE.clear()
        with patch.object(service,'load_db',return_value=current), \
             patch.object(ai_inspections,'load_settings',return_value={'auto_inspection_enabled':True}), \
             patch.object(ai_remote_evidence.unknown,'jobs_script',return_value='echo mock-lsf'), \
             patch.object(ai_remote_evidence.unknown,'remote',return_value=output) as remote:
            status,run=self.send(conversation)
            self.assertEqual(status,200,run)
            result=self.wait_run(run)
        self.assertEqual(result['status'],'completed',result)
        events=result['tool_events']
        self.assertEqual([e['name'] for e in events],['get_task_inspections','get_task_parameter_history','get_remote_task_evidence'])
        self.assertTrue(events[0]['result']['freshness']['stale_for_live_decision'])
        self.assertEqual(events[1]['result']['records'][0]['changes'][0]['after'],'200')
        self.assertEqual(events[2]['result']['current_state']['state'],'RUN')
        self.assertEqual(events[2]['result']['evidence']['samples'][0]['incar']['MAGMOM'],'2*1.0 3*0.0')
        self.assertFalse(events[2]['result']['intervention_authorized'])
        self.assertEqual(remote.call_count,1)

    def test_large_project_budget_never_silently_caps_at_twelve_tasks(self):
        context = {"scope": "project", "project": {"name": "test"}, "summary": {"task_count": 30},
                   "tasks": [{"task_id": f"t{i}", "task_name": "model"} for i in range(30)]}
        budget = service._context_budget(context)
        self.assertEqual(len(budget["tasks"]), 30)
        context["tasks"] = [{"task_id": f"t{i}", "task_name": "x"*120, "details": "x"*2000} for i in range(700)]
        context["summary"]["task_count"] = 700
        budget = service._context_budget(context)
        self.assertLessEqual(len(json.dumps(budget, ensure_ascii=False)), service.CONTEXT_CHARS)
        self.assertGreater(budget["summary"]["omitted_task_count"], 0)
        self.assertEqual(budget["summary"]["included_task_count"]+budget["summary"]["omitted_task_count"], 700)
        self.assertIn("不能视为已审阅", budget["budget_note"])


if __name__ == "__main__": unittest.main()
