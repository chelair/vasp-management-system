"""远程操作封装（Paramiko）：执行命令 / 上传 / 下载 / 递归建目录。

支持本地模拟模式（环境变量 VASP_SSH_MOCK=1，模拟根目录 VASP_MOCK_REMOTE_ROOT，
默认 data/mock_remote）：远程路径按原样映射到模拟根目录下的本地文件，
`python3 <script> <in> <out>` 命令改为本地 Python 执行，便于离线测试巡检流程。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from config import DATA_DIR, load_servers


def _mock_enabled() -> bool:
    return os.environ.get("VASP_SSH_MOCK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _mock_root() -> Path:
    return Path(
        os.environ.get("VASP_MOCK_REMOTE_ROOT", str(DATA_DIR / "mock_remote"))
    )


def _local_path(remote_path: str) -> Path:
    """模拟模式下把远程绝对路径映射为本地路径。"""
    return _mock_root() / str(remote_path).lstrip("/")


def _get_client(server_name: str):
    """建立 Paramiko SSH 连接（密钥认证优先，配置了 password 则用密码）。"""
    servers = load_servers()
    cfg = servers.get(server_name)
    if cfg is None:
        raise ValueError(f"服务器 '{server_name}' 未在 servers.json 中配置")
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("缺少依赖 paramiko，请运行：pip install -r requirements.txt")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = dict(
        hostname=cfg["host"],
        port=int(cfg.get("port", 22)),
        username=cfg["user"],
        timeout=10,
        banner_timeout=10,
    )
    if cfg.get("password"):
        connect_kwargs["password"] = str(cfg["password"])
    else:
        connect_kwargs["key_filename"] = os.path.expanduser(
            cfg.get("key_path", "~/.ssh/id_rsa")
        )
    client.connect(**connect_kwargs)
    return client


def run_remote(server_name: str, command: str, timeout: int = 30) -> Dict[str, object]:
    """在指定服务器执行命令，返回 {stdout, stderr, exit_code}。"""
    if _mock_enabled():
        parts = command.strip().split()
        if parts and parts[0] in ("python3", "python"):
            script = _local_path(parts[1])
            args = [_local_path(part) for part in parts[2:]]
            try:
                proc = subprocess.run(
                    [sys.executable, str(script), *[str(a) for a in args]],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return {"stdout": "", "stderr": f"mock timeout（{timeout}s）", "exit_code": 1}
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            }
        return {"stdout": "", "stderr": "mock: 不支持的远程命令", "exit_code": 1}

    client = _get_client(server_name)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": exit_code,
        }
    finally:
        client.close()


def upload_file(
    server_name: str, local_path: str, remote_path: str, timeout: int = 60
) -> bool:
    """上传本地文件到远程路径，失败时抛出异常。"""
    local = Path(local_path)
    if not local.is_file():
        raise FileNotFoundError(f"本地文件不存在：{local_path}")
    if _mock_enabled():
        target = _local_path(remote_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, target)
        return True

    client = _get_client(server_name)
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(local), remote_path)
        finally:
            sftp.close()
    finally:
        client.close()
    return True


def download_file(
    server_name: str, remote_path: str, local_path: str, timeout: int = 60
) -> bool:
    """下载远程文件到本地；远程不存在/为空或失败时返回 False。"""
    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    if _mock_enabled():
        src = _local_path(remote_path)
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, local)
            return True
        return False

    client = _get_client(server_name)
    try:
        sftp = client.open_sftp()
        try:
            stat = sftp.stat(remote_path)
            if stat.st_size <= 0:
                return False
            sftp.get(remote_path, str(local))
            return True
        except FileNotFoundError:
            return False
        finally:
            sftp.close()
    finally:
        client.close()


def mkdir_remote(server_name: str, remote_path: str, timeout: int = 30) -> None:
    """在远程服务器递归创建目录（mkdir -p），失败时抛出异常。"""
    if _mock_enabled():
        _local_path(remote_path).mkdir(parents=True, exist_ok=True)
        return

    client = _get_client(server_name)
    try:
        _stdin, stdout, stderr = client.exec_command(
            f"mkdir -p '{remote_path}'", timeout=timeout
        )
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            detail = (
                stderr.read().decode("utf-8", errors="replace")
                or stdout.read().decode("utf-8", errors="replace")
            ).strip()
            raise RuntimeError(
                f"远程创建目录失败 {remote_path}：{detail or f'退出码 {exit_code}'}"
            )
    finally:
        client.close()
