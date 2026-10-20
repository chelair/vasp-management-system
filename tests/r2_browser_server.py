"""Ephemeral R2 browser fixture server. Not part of production startup."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="vasp-r2-browser-") as directory:
    os.environ["VASP_WEB_DATA_DIR"] = directory
    os.environ["VASP_AI_KEY_FILE"] = str(Path(directory)/"ai.key")
    sys.path[:0] = [str(Path(__file__).resolve().parents[1]/"backend"), str(Path(__file__).resolve().parent)]
    import auth
    import config
    import permissions
    import report_interactive
    import r2_fixtures
    import storage
    import uvicorn
    import ssh
    from r2_science_fixtures import seed_science
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from middleware.auth import install
    from routers.report_compositions import router
    config.ensure_data_dirs()
    project = r2_fixtures.seed(Path(directory))
    seed_science(Path(directory), project)
    storage.save_db({"projects": [project]})
    user, _ = auth.create_user("tester")
    token, _ = auth.create_session(user)
    def forbid_ssh(*args, **kwargs):
        raise AssertionError("R2 browser fixture must not use SSH")
    ssh._get_client = forbid_ssh
    if len(sys.argv) > 1: report_interactive.RUNTIME_PATH = Path(sys.argv[1])
    app = FastAPI(); install(app); app.include_router(router, prefix="/api")
    @app.exception_handler(permissions.PermissionDenied)
    async def denied(request, exc):
        return JSONResponse(status_code=403, content={"success": False, "message": str(exc)})
    @app.post("/__test/mutate")
    def mutate():
        r2_fixtures.rewrite_checks(Path(directory), lambda entries: [e.update({"force_max": 7.77}) for e in entries if e["task_id"] == "task_opt_01"])
        return {"ok": True}
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    print(json.dumps({"port": sock.getsockname()[1], "token": token}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error")).run(sockets=[sock])
