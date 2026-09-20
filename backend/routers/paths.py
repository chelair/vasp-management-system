"""路径映射管理：本地根目录 ↔ 各服务器远端根目录 的一一对应关系。

对应关系固化在 data/config/path_mapping.json，可修改后通过 /rebase
批量重算所有任务的 remote_dir（dir_path 使用 local_root）。
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import CONFIG_DIR, PROJECT_ROOT, PROJECTS_DIR, load_path_mapping, load_servers
from envelope import fail, ok
import permissions
from storage import load_db, save_db

router = APIRouter(prefix="/path-mapping", tags=["path-mapping"])

MAPPING_PATH = CONFIG_DIR / "path_mapping.json"


def _atomic_write(data: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".path_mapping_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, MAPPING_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _sync_servers_remote_base(remote_roots: Dict[str, Any]) -> None:
    """把 path_mapping 的 remote_roots 同步到 servers.json 的 remote_base。"""
    servers = load_servers()
    changed = False
    for name, root in (remote_roots or {}).items():
        if name in servers and str(root or "").strip():
            servers[name]["remote_base"] = str(root).rstrip("/")
            changed = True
    if not changed:
        return
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_DIR), prefix=".servers_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(servers, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_DIR / "servers.json")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@router.get("")
def get_mapping():
    try:
        return ok("查询成功", load_path_mapping())
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取路径映射失败：{e}"))


@router.put("")
def put_mapping(payload: dict, request: Request):
    """保存路径映射；同步更新 servers.json 的 remote_base 保持一致（**仅 admin**）。"""
    try:
        permissions.ensure_admin(getattr(request.state, "user", None), "只有管理员可以修改路径映射")
        local_root = str(payload.get("local_root", "")).strip()
        remote_roots = payload.get("remote_roots")
        if not local_root:
            return JSONResponse(status_code=400, content=fail("local_root 不能为空"))
        if not isinstance(remote_roots, dict):
            return JSONResponse(status_code=400, content=fail("remote_roots 必须是对象"))
        _atomic_write({"local_root": local_root, "remote_roots": remote_roots})
        # 同步 servers.json remote_base（保持单一事实来源）
        _sync_servers_remote_base(remote_roots)
        return ok(
            "路径映射已保存",
            {"local_root": local_root, "remote_roots": remote_roots},
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"保存路径映射失败：{e}"))


@router.post("/rebase")
def rebase_paths(request: Request):
    """按当前映射批量重算所有任务的 remote_dir / dir_path（**仅 admin**）。"""
    try:
        permissions.ensure_admin(getattr(request.state, "user", None), "只有管理员可以批量重算路径")
        mapping = load_path_mapping()
        raw_root = str(mapping["local_root"])
        local_root = (
            Path(raw_root).resolve()
            if Path(raw_root).is_absolute()
            else (PROJECT_ROOT / raw_root).resolve()
        )
        remote_roots = mapping.get("remote_roots", {})
        db = load_db()
        updated = skipped = 0
        for project in db.get("projects", []):
            remote_root = str(remote_roots.get(project.get("server", ""), "") or "").rstrip("/")
            for task in project.get("tasks", []):
                dp = task.get("dir_path")
                if not dp:
                    continue
                try:
                    rel = Path(dp).resolve().relative_to(local_root)
                except ValueError:
                    skipped += 1
                    continue
                rel_str = rel.as_posix()
                # 一律保持相对路径（v0.5.0 规范：禁止绝对路径，改根目录才能自动重定位）
                task["dir_path"] = rel_str
                if remote_root:
                    task["remote_dir"] = rel_str
                updated += 1
        save_db(db)
        return ok(
            "路径已重算",
            {"updated": updated, "skipped": skipped, "mapping": mapping},
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"路径重算失败：{e}"))
