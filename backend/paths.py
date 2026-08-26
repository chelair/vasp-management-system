"""路径解析中心：任务元数据中的路径一律为相对项目根目录的相对路径。

约定：
- 本地相对路径相对 local_root（默认 data/projects）；
- 远端相对路径相对对应服务器的 remote_root（默认 servers.json remote_base）；
- 禁止在元数据中存储绝对路径或 ~；
- 解析时：resolve_local_path / resolve_remote_path 负责拼接根目录。
"""

from pathlib import Path
from typing import Optional

from config import PROJECT_ROOT, PROJECTS_DIR, load_path_mapping, load_servers


def local_root() -> Path:
    """本地项目根目录（绝对路径）。"""
    mapping = load_path_mapping()
    raw = str(mapping.get("local_root") or PROJECTS_DIR)
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    return (PROJECT_ROOT / p).resolve()


def remote_root(server: str) -> str:
    """服务器远程项目根目录（绝对路径）。"""
    mapping = load_path_mapping()
    root = str(mapping.get("remote_roots", {}).get(server, "") or "").rstrip("/")
    if not root:
        root = str(load_servers().get(server, {}).get("remote_base", "") or "").rstrip("/")
    return root


def is_relative(path: Optional[str]) -> bool:
    if not path:
        return True
    p = path.strip()
    # Windows 下 Path('/x') 不是绝对路径，需显式识别 POSIX 绝对形式
    if p.startswith("/") or p.startswith("\\"):
        return False
    return not Path(p).is_absolute() and not p.startswith("~")


def resolve_local_path(rel: Optional[str]) -> Path:
    """相对本地路径 -> 绝对路径（兼容绝对/~/旧格式）。"""
    if not rel:
        return local_root()
    p = Path(str(rel).strip())
    if p.is_absolute() or str(rel).startswith("~"):
        return p.expanduser()
    return local_root() / p


def resolve_remote_path(server: str, rel: Optional[str]) -> str:
    """相对远端路径 -> 绝对路径（兼容绝对/旧格式）。"""
    if not rel:
        return remote_root(server)
    r = str(rel).strip()
    if r.startswith(("/", "~")) or Path(r).is_absolute():
        return r
    root = remote_root(server)
    if not root:
        raise ValueError(f"服务器 {server} 未配置远程根目录，请检查设置")
    return f"{root}/{r.lstrip('/')}"


def to_local_rel(path: Optional[str]) -> str:
    """绝对本地路径 -> 相对 local_root；不匹配前缀则原样返回（标记异常）。"""
    if not path or is_relative(path):
        return str(path or "")
    try:
        return str(Path(path).resolve().relative_to(local_root())).replace("\\", "/")
    except ValueError:
        return str(path)


def to_remote_rel(server: str, path: Optional[str]) -> str:
    """绝对远端路径 -> 相对 remote_root；不匹配前缀则原样返回（标记异常）。"""
    if not path or is_relative(path):
        return str(path or "")
    root = remote_root(server)
    if root and str(path).startswith(root):
        return str(path)[len(root):].lstrip("/")
    return str(path)
