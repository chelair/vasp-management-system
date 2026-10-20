"""Isolated R3 API/auth server; no production startup or HPC access."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='vasp-r3-browser-') as directory:
    os.environ['VASP_WEB_DATA_DIR'] = directory
    os.environ['VASP_AI_KEY_FILE'] = str(Path(directory)/'ai.key')
    sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
    import auth
    import config
    import permissions
    import r3_fixtures
    import uvicorn
    import ssh
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from middleware.auth import install
    from routers.properties import router
    config.ensure_data_dirs()
    project,rows = r3_fixtures.seed(Path(directory))
    user,_ = auth.create_user('tester'); token,_ = auth.create_session(user)
    def forbid(*args,**kwargs): raise AssertionError('R3 does not access HPC')
    ssh._get_client = forbid
    app = FastAPI(); install(app); app.include_router(router,prefix='/api')
    @app.exception_handler(permissions.PermissionDenied)
    async def denied(request,exc): return JSONResponse(status_code=403,content={'success':False,'message':str(exc)})
    sock = socket.socket(); sock.bind(('127.0.0.1',0))
    print(json.dumps({'port':sock.getsockname()[1],'token':token}),flush=True)
    uvicorn.Server(uvicorn.Config(app,log_level='error')).run(sockets=[sock])
