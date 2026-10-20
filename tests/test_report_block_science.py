"""R2 C/D: real local adapters, frozen exports, real HTTP auth; isolated process."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

_DATA = tempfile.TemporaryDirectory(prefix="vasp-r2-science-")
os.environ["VASP_WEB_DATA_DIR"] = _DATA.name
os.environ["VASP_AI_KEY_FILE"] = str(Path(_DATA.name) / "ai.key")
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend"), str(Path(__file__).resolve().parent)]


class BlockScienceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        if config.DATA_DIR.resolve() != Path(_DATA.name).resolve():
            raise unittest.SkipTest("R2 science needs independent process / isolated DATA_DIR")
        import report_blocks as blocks
        import report_compositions as compositions
        import r2_fixtures
        from r2_science_fixtures import seed_science
        config.ensure_data_dirs()
        cls.blocks, cls.compositions = blocks, compositions
        cls.project = r2_fixtures.seed(Path(_DATA.name))
        cls.ele = seed_science(Path(_DATA.name), cls.project)
        import storage
        storage.save_db({"projects": [cls.project]})

    def setUp(self):
        self.no_ssh = patch("ssh._get_client", side_effect=AssertionError("R2 must not connect SSH"))
        self.no_ssh.start()
        self.addCleanup(self.no_ssh.stop)

    def test_real_electronic_adapters_freeze_payload_and_charts(self):
        for kind in ("ele.pdos", "ele.bader", "ele.work_function", "ele.charge_diff"):
            with self.subTest(kind=kind):
                ev = self.blocks.resolve_evidence(self.project, kind, task_id="t_ele")
                self.assertEqual(ev["availability"], "available", ev["payload"])
                self.assertTrue(ev["provenance"][0]["files"])
                self.assertNotEqual(ev["validation"]["status"], "PASS")
        doc = self.compositions.save(self.project, {"title": "科学结果", "blocks": [{"type": kind, "task_id": "t_ele"} for kind in
            ("ele.pdos", "ele.bader", "ele.work_function", "ele.charge_diff")]})
        with patch("pdos.load_view", side_effect=AssertionError("export must not re-read PDOS")):
            output = self.compositions.render_html(doc)
        self.assertIn("<svg", output)
        self.assertTrue("data:image/png;base64," in output)
        self.assertIn("data-block-id", output)
        self.assertIn("__VASP_REPORT_DATA__", output)
        self.assertIn("0.8", output)

    def test_structure_conversion_writes_only_temporary_output(self):
        from task_paths import task_dir
        root = task_dir(self.project["name"], self.project["tasks"][0])
        before = {str(p) for p in root.rglob("*")}
        ev = self.blocks.resolve_evidence(self.project, "task.structure", task_id="task_opt_01")
        self.assertIn("data_", ev["payload"]["poscar_cif"])
        self.assertEqual(before, {str(p) for p in root.rglob("*")})
        self.assertEqual(ev["validation"]["status"], "NOT_TESTED")

    def test_corrupt_pdos_remains_unparsed_and_does_not_break_other_blocks(self):
        import pdos
        path = pdos.data_path(self.project["name"], self.ele)
        original = path.read_bytes()
        try:
            path.write_text("not json")
            doc = self.compositions.save(self.project, {"title": "隔离", "blocks": [
                {"type": "ele.pdos", "task_id": "t_ele"}, {"type": "task.energy_force", "task_id": "task_opt_01"}]})
            self.assertEqual(doc["blocks"][0]["data_status"], "unparsed")
            self.assertIn("最终能量", self.compositions.render_html(doc))
        finally:
            path.write_bytes(original)

    def test_integrated_electronic_candidates_no_subtype_omissions(self):
        catalog = self.blocks.list_candidates(self.project)
        types = {c["type"] for c in catalog["candidates"] if c.get("task_id") == "t_ele"}
        self.assertTrue({"ele.pdos", "ele.bader", "ele.work_function", "ele.charge_diff"}.issubset(types))

    def test_group_sources_and_missing_neb_image_values(self):
        project = deepcopy(self.project)
        for i, task in enumerate(project["tasks"][:2]):
            task["group"] = {"group_id": "fe", "group_type": "free_energy", "group_role": "main_structure", "structure_label": str(i+1), "name": "路径"}
        for i in range(2):
            project["tasks"].append({"task_id": "frac"+str(i), "model_name": "freq", "task_type": "frac", "status": "completed", "correction": .2,
                "group": {"group_id": "fe", "group_type": "free_energy", "structure_label": str(i+1)}})
        ev = self.blocks.resolve_evidence(project, "group.free_energy", group_id="fe")
        self.assertEqual(len(ev["provenance"]), 4)
        self.assertTrue(ev["payload"]["charts"])
        candidate = next(c for c in self.blocks.list_candidates(project)["candidates"] if c["type"] == "group.free_energy")
        doc = self.compositions.save(project, {"title": "路径", "blocks": [candidate]})
        self.assertIn("<svg", self.compositions.render_html(doc))
        project["tasks"].append({"task_id": "neb", "model_name": "NEB", "task_type": "neb", "status": "completed"})
        merged = {"neb": {"neb_barrier": {"images": [{"label": "00", "relative": None}, {"label": "01", "relative": .8}, {"label": "02", "relative": .2}]}}}
        ev = self.blocks.resolve_evidence(project, "group.neb", task_id="neb", merged=merged)
        self.assertEqual(ev["payload"]["items"][0]["transition_state_image"], "01")
        self.assertEqual(ev["payload"]["items"][0]["converged_images"], [])

    def test_time_policy_and_summary_version(self):
        now = datetime.now().astimezone()
        task = self.project["tasks"][0]
        self.assertEqual(self.blocks._freshness((now-timedelta(hours=5)).isoformat(), now, self.project, task)["state"], "stale")
        self.assertEqual(self.blocks._freshness((now+timedelta(hours=1)).isoformat(), now)["state"], "unknown")
        self.assertEqual(self.blocks._freshness((now-timedelta(hours=5)).isoformat(), now, self.project, {**task, "status": "archived"})["state"], "unknown")
        first = self.blocks.resolve_evidence(self.project, "task.summary", task_id="task_opt_01")
        changed = deepcopy(first["payload"]); changed["inspection_checked_at"] = "2020-01-01"; changed["runtime_hours"] = 888
        self.assertEqual(first["version"], self.blocks.payload_version(first["kind"], changed, first["provenance"]))

    def test_symlink_and_project_escape_not_read(self):
        from report_block_science import checked_path
        path = Path(_DATA.name)/"projects"/self.project["name"] / "link"
        with tempfile.NamedTemporaryFile() as external:
            path.symlink_to(external.name)
            try:
                with self.assertRaises(ValueError): checked_path(self.project, self.ele, path)
            finally:
                path.unlink()
        with self.assertRaises(ValueError): checked_path(self.project, self.ele, Path(_DATA.name)/"users.json")

    def test_http_auth_conflicts_preview_and_export(self):
        import auth
        import permissions
        import uvicorn
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from middleware.auth import install
        from routers.report_compositions import router
        app = FastAPI(); install(app); app.include_router(router, prefix="/api")
        @app.exception_handler(permissions.PermissionDenied)
        async def denied(request, exc):
            return JSONResponse(status_code=403, content={"success": False, "message": str(exc)})
        tokens = {}
        for name in ("tester", "other", "bot"):
            user = auth.find_user(name)
            if user is None: user, _ = auth.create_user(name, role="agent" if name == "bot" else "user", delegate_to="tester" if name == "bot" else None)
            tokens[name], _ = auth.create_session(user, scope=["read", "write"] if name == "bot" else None)
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True); thread.start()
        try:
            deadline = time.monotonic()+5
            while not server.started and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(server.started)
            def call(path, method="GET", payload=None, user="tester"):
                headers = {"Content-Type": "application/json"}
                if user: headers["Authorization"] = "Bearer " + tokens[user]
                req = Request(f"http://127.0.0.1:{port}/api/reports/blocks/p_r2/"+path, method=method, headers=headers,
                              data=json.dumps(payload).encode() if payload is not None else None)
                try:
                    with urlopen(req) as res: return res.status, res.read()
                except HTTPError as exc:
                    with exc: return exc.code, exc.read()
            self.assertEqual(call("candidates", user=None)[0], 401)
            self.assertEqual(call("candidates", user="other")[0], 403)
            self.assertEqual(call("preview", "POST", {}, user="bot")[0], 403)
            self.assertEqual(call("evidence", "POST", {"type": "ele.pdos", "task_id": "task_opt_01"})[0], 400)
            payload = {"title": "HTTP", "blocks": [{"type": "task.energy_force", "task_id": "task_opt_01"}]}
            status, data = call("preview", "POST", payload); self.assertEqual(status, 200, data)
            self.assertIn("<table", json.loads(data)["data"]["html"])
            status, data = call("compositions", "POST", payload); self.assertEqual(status, 200, data)
            doc = json.loads(data)["data"]; cid = doc["composition_id"]
            self.assertEqual(call("compositions/"+cid, user="other")[0], 403)
            self.assertEqual(call("compositions/"+cid+"/export.html", user="other")[0], 403)
            self.assertEqual(call("compositions/"+cid, "PUT", doc)[0], 400)
            self.assertEqual(call("compositions/"+cid, "PUT", {**doc, "expected_revision": 99})[0], 409)
            status, data = call("compositions/"+cid+"/export.html"); self.assertEqual(status, 200); self.assertIn(b"Content-Security-Policy", data)
        finally:
            server.should_exit = True; thread.join(5)


if __name__ == "__main__": unittest.main()
