"""离线 HPC 夹具（阶段 0 测试基线）：Mock SSH + Mock LSF(bsub) + Mock VASP 输出。

适用场景：验证「提交 / 续算 / 超时 / 重复请求 / 重启恢复」这类有副作用的链路，
**不连真实集群、不碰生产 data/**。

原理（复用项目已有能力，不新造一套）：
- `backend/ssh.py` 在 `VASP_SSH_MOCK=1` 时把 `echo <b64> | base64 -d | bash`
  的远程脚本改成本地 bash 执行，并把 `<mock根>/_mock_bin` 放进 PATH；
- 本模块只在 `_mock_bin/` 里放一个 `bsub` 打桩脚本，用环境变量控制
  成功 / 拒绝 / 报错 / 挂起，并把每次调用记到日志里（用来断言"到底提交了几次"）；
- 远端目录按 `<mock根>/<远程绝对路径>` 映射，测试直接在那里建 POSCAR/INCAR/…。

约定：本文件只依赖标准库，不 import backend，方便任何测试或脚本单独使用。
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Dict, List, Optional

#: bsub 打桩脚本（被 backend/ssh.py 的 _mock_bin 机制放进 PATH）
_BSUB_STUB = r"""#!/usr/bin/env bash
# Mock bsub（阶段 0 夹具）：记录调用，按 MOCK_BSUB_MODE 输出
log="${MOCK_BSUB_LOG:-/dev/null}"
{
  printf 'call cwd=%s args=%s\n' "$(pwd)" "$*"
} >> "$log" 2>/dev/null

# 消费 stdin（真实 bsub 是 `bsub < vasp.lsf`）
if [ "${MOCK_CHANGE_SCRIPT_ON_BSUB:-0}" = 1 ]; then
  printf '#BSUB -n 240\n#BSUB -W 10:00\n#BSUB -q normal\n' > vasp.lsf
fi
cat > "${MOCK_BSUB_STDIN_FILE:-/dev/null}" 2>&1

case "${MOCK_BSUB_MODE:-ok}" in
  ok|lost)
    JOBNAME=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "-J" ]; then shift; JOBNAME="$1"; fi
      shift
    done
    if [ -n "${MOCK_JOBS_FILE:-}" ]; then
      printf '%s|%s|%s|%s\n' "${MOCK_BSUB_JOB_ID:-230001}" RUN "$(pwd)" "$JOBNAME" >> "$MOCK_JOBS_FILE"
    fi
    [ "${MOCK_BSUB_MODE}" = lost ] && exit 0
    echo "Job <${MOCK_BSUB_JOB_ID:-230001}> is submitted to default queue <normal>."
    ;;
  reject)
    echo "Job not submitted: RUNLIMIT for queue <normal> would be exceeded."
    exit 1
    ;;
  error)
    echo "bsub: command not found" >&2
    exit 127
    ;;
  hang)
    sleep "${MOCK_BSUB_SLEEP:-30}"
    echo "Job <${MOCK_BSUB_JOB_ID:-230001}> is submitted to default queue <normal>."
    ;;
  *)
    echo "mock bsub: unknown MOCK_BSUB_MODE=${MOCK_BSUB_MODE}" >&2
    exit 2
    ;;
esac
"""

DEFAULT_REMOTE_BASE = "/data/gpfs03/mdye/projects/HS"

#: 任务目录必备输入文件（core_submit 的 preflight 会逐个判非空）
REQUIRED_FILES: Dict[str, str] = {
    "POSCAR": "P1\n1.0\n1.0 0.0 0.0\n0.0 1.0 0.0\n0.0 0.0 1.0\nSi\n1\nDirect\n0.0 0.0 0.0\n",
    "INCAR": "ISTART = 0\nNSW = 100\nENCUT = 450\n",
    "KPOINTS": "K-Points\n0\nGamma\n1 1 1\n0.0 0.0 0.0\n",
    "POTCAR": "PAW_PBE Si 05Jan2001\n",
    "vasp.lsf": '#!/bin/bash\n#BSUB -n 24\n#BSUB -W 24:00\nmpirun vasp_std\n',
}


class MockHpc:
    """一个隔离的"假集群"：临时 mock 远端树 + bsub 打桩。"""

    def __init__(
        self,
        mock_root: Path,
        remote_base: str = DEFAULT_REMOTE_BASE,
    ) -> None:
        self.root = Path(mock_root)
        self.remote_base = str(remote_base).rstrip("/")
        self.bin_dir = self.root / "_mock_bin"
        self.log_path = self.root / "_mock_bsub.log"

    # ---------------------------------------------------------------- 生命周期

    def reset(self) -> None:
        """清空 mock 远端树（每个测试用例开始前调用）。"""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.touch()
        self.install_bsub()
        self.install_bjobs()

    def install_bsub(self, mode: str = "ok", job_id: str = "230001") -> None:
        """写入 bsub 打桩并设置模式：ok / reject / error / hang。"""
        os.environ["MOCK_BSUB_MODE"] = str(mode)
        os.environ["MOCK_BSUB_JOB_ID"] = str(job_id)
        os.environ["MOCK_BSUB_LOG"] = str(self.log_path)
        os.environ["MOCK_BSUB_STDIN_FILE"] = str(self.root / "_mock_bsub_stdin")
        script = self.bin_dir / "bsub"
        script.write_text(_BSUB_STUB, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # ---------------------------------------------------------------- 远端树

    def remote_path(self, remote_rel: str) -> Path:
        """任务相对路径 -> 本地 mock 路径（= <mock根>/<远程绝对路径>）。"""
        absolute = f"{self.remote_base}/{str(remote_rel).lstrip('/')}"
        return self.root / absolute.lstrip("/")

    def write_inputs(
        self,
        remote_rel: str,
        overrides: Optional[Dict[str, str]] = None,
    ) -> Path:
        """在 mock 远端目录写一套齐全的 VASP 输入文件，返回该目录。"""
        target = self.remote_path(remote_rel)
        target.mkdir(parents=True, exist_ok=True)
        files = dict(REQUIRED_FILES)
        files.update(overrides or {})
        for name, content in files.items():
            (target / name).write_text(content, encoding="utf-8")
        return target

    # ---------------------------------------------------------------- 调用记录

    def calls(self) -> List[str]:
        """bsub 调用日志（每行一次调用）。"""
        if not self.log_path.is_file():
            return []
        return [line for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def submit_count(self) -> int:
        return len(self.calls())

    def install_bjobs(self):
        """bjobs状态直接来自可编辑夹具文件；空文件=明确没有作业。"""
        self.jobs_path = self.root / '_mock_jobs.txt'
        self.jobs_path.write_text('')
        os.environ['MOCK_JOBS_FILE'] = str(self.jobs_path)
        script = self.bin_dir / 'bjobs'
        script.write_text('''#!/bin/bash
[ "${MOCK_BJOBS_ERROR:-0}" = 1 ] && exit 2
if [ "${1:-}" = "-l" ]; then
  while IFS='|' read -r jobid state directory jobname; do
    if [ "$jobid" = "${2:-}" ]; then
      printf 'Job <%s>, Job Name <%s>, Status <%s>\\n' "$jobid" "$jobname" "$state"
      if [ "$jobid" = "${MOCK_LSF_REASON_JOB_ID:-}" ]; then
        printf '%s\\n' "${MOCK_LSF_REASON:-}"
      fi
    fi
  done < "$MOCK_JOBS_FILE"
else
  cat "$MOCK_JOBS_FILE"
fi
''')
        script.chmod(0o755)

    def set_jobs(self, rows):
        self.jobs_path.write_text(''.join('|'.join(map(str, row)) + '\n' for row in rows))


class ApplicationClient:
    """真实ASGI应用+lifespan，标准库HTTP客户端，无额外httpx测试依赖。"""
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        import socket
        import threading
        import time
        import uvicorn
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.base = 'http://127.0.0.1:' + str(self.socket.getsockname()[1])
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='error', lifespan='on'))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [self.socket]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.server.should_exit = True
                raise RuntimeError('隔离应用未能启动')
            time.sleep(.01)
        return self

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(5)
        self.socket.close()

    def request(self, method, path, headers=None, json=None):
        import json as json_module
        import urllib.request
        import urllib.error
        from types import SimpleNamespace
        body = json_module.dumps(json).encode() if json is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers={**(headers or {}), 'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            text = response.read().decode()
            return SimpleNamespace(status_code=response.status, text=text, json=lambda: json_module.loads(text))

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def post(self, path, **kwargs):
        return self.request('POST', path, **kwargs)
