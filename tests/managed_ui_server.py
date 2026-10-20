"""托管页浏览器验收夹具：隔离数据目录、真实 HTTP/鉴权、一个计划；不连接集群/模型。

打印一行 JSON（port/token/plan_id）后常驻，供 tests/browser/managed-plan.cjs 使用。
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_ROOT = Path(tempfile.mkdtemp(prefix="vasp-managed-ui-"))
os.environ["VASP_WEB_DATA_DIR"] = str(_ROOT / "data")
os.environ.pop("VASP_SSH_MOCK", None)
os.environ.pop("VASP_MOCK_REMOTE_ROOT", None)

import config  # noqa: E402

config.ensure_data_dirs()

import auth  # noqa: E402
import cluster_probe  # noqa: E402
import managed_plan  # noqa: E402
import storage  # noqa: E402

# 绝不采集真实集群：固定返回空采集，界面应按"模拟/缺数据"等待。
patch.object(
    cluster_probe,
    "probe",
    lambda *args, **kwargs: {
        "sections": {},
        "error": "浏览器验收夹具：不采集真实集群",
        "queriedAt": "2026-10-20T14:00:00+08:00",
        "cached": False,
        "stale": False,
        "cacheAgeSeconds": 0,
        "cacheTtlSeconds": 300,
    },
).start()

USER, _ = auth.create_user("tester", "MockPassword123!", role="user")
TOKEN, _ = auth.create_session(USER)
storage.save_db({"projects": [
    {"name": "P1", "server": "server1", "owner": "tester", "tasks": [
        {"task_id": "t1", "task_type": "opt", "status": "pending", "model_name": "model1", "remote_dir": "P1/T1"},
        {"task_id": "t2", "task_type": "opt", "status": "unconverged", "model_name": "model2", "remote_dir": "P1/T2"},
        {"task_id": "t3", "task_type": "opt", "status": "running", "model_name": "model3", "remote_dir": "P1/T3"},
    ]},
]}, backup=False)
PLAN = managed_plan.create(USER, {
    "project": "P1",
    "goal": {"text": "这个项目周五先交 model1 的阶段报告，把它放最高；有输入的任务帮我接着跑。",
             "summary": "周五交 model1 阶段报告，其余接着跑"},
    "stages": [
        {"title": "阶段报告", "task_ids": ["t1"], "due": "2026-10-23", "priority": 90,
         "source_quote": "周五先交 model1 的阶段报告"},
        {"title": "后续补算", "task_ids": ["t2"], "priority": 10},
    ],
    "resource_rules": {"queues_allowed": ["normal_2week"]},
})

import uvicorn  # noqa: E402
from main import app  # noqa: E402

_sock = socket.socket()
_sock.bind(("127.0.0.1", 0))
PORT = _sock.getsockname()[1]
_sock.close()
_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error", lifespan="on"))
threading.Thread(target=_server.run, daemon=True).start()

import urllib.error  # noqa: E402
from urllib.request import urlopen  # noqa: E402

_deadline = time.monotonic() + 20
while time.monotonic() < _deadline:
    try:
        urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1)
        break
    except OSError:
        time.sleep(0.05)
else:
    raise SystemExit("fixture server timeout")

print("MANAGED_FIXTURE " + json.dumps({"port": PORT, "token": TOKEN, "plan_id": PLAN["id"]}), flush=True)
while True:
    time.sleep(3600)
