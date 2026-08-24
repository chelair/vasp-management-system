"""统一响应信封 {success, message, data}（与参考实现 common.py 一致）。"""

from typing import Any, Dict, Optional


def ok(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": True, "message": message, "data": data or {}}


def fail(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": False, "message": message, "data": data or {}}
