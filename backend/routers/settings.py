"""系统设置：项目根目录（本地 + 远端）配置。

路径以相对项目根目录存储；修改根目录即可整体重定位，无需改动任务路径。
对应关系固化在 data/config/path_mapping.json。
"""

from fastapi import APIRouter, Request, Request
from fastapi.responses import JSONResponse

from config import load_path_mapping
from envelope import fail, ok
import permissions
import permissions
from routers.paths import _atomic_write, _sync_servers_remote_base

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/root-paths")
def get_root_paths():
    try:
        m = load_path_mapping()
        return ok(
            "查询成功",
            {"local_root": m.get("local_root"), "remote_roots": m.get("remote_roots", {})},
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取根目录配置失败：{e}"))


@router.put("/root-paths")
def put_root_paths(payload: dict, request: Request):
    """修改本地/远端根目录；合并写入配置文件并同步 servers.json remote_base（**仅 admin**）。"""
    try:
        permissions.ensure_admin(getattr(request.state, "user", None), "只有管理员可以修改根目录配置")
        current = load_path_mapping()
        local_root = payload.get("local_root")
        remote_roots = payload.get("remote_roots")
        if local_root is not None and str(local_root).strip():
            current["local_root"] = str(local_root).strip()
        if remote_roots is not None:
            if not isinstance(remote_roots, dict):
                return JSONResponse(status_code=400, content=fail("remote_roots 必须是对象"))
            merged = dict(current.get("remote_roots", {}))
            merged.update({str(k): str(v).strip() for k, v in remote_roots.items() if v})
            current["remote_roots"] = merged
        _atomic_write(current)
        _sync_servers_remote_base(current.get("remote_roots", {}))
        return ok(
            "根目录配置已保存（任务路径保持相对，无需修改）",
            {
                "local_root": current["local_root"],
                "remote_roots": current.get("remote_roots", {}),
            },
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"保存根目录配置失败：{e}"))
