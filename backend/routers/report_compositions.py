"""R2 报告元素接口：候选目录 / 证据解析 / 组合增删改查 / 自包含 HTML 导出。

路径统一挂在 `/api/reports/blocks/...` 下，与完整报告 `/api/reports/project/...`
分开，避免和"每项目一份最新完整报告"的索引/清理语义混在一起。

权限：所有接口都按**当前登录用户对项目的归属**校验（admin 全可见），
不接受前端传 project 以外的越权引用；组合读取/导出同样校验。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response

from envelope import fail, ok
import permissions
import report_compositions as compositions
from report_blocks import (
    BLOCK_TYPES,
    SCHEMA_VERSION,
    list_candidates,
    resolve_evidence,
)
from storage import load_db

router = APIRouter(prefix="/reports/blocks", tags=["report-blocks"])


def _project(ref: str):
    db = load_db()
    project = next(
        (
            item
            for item in db.get("projects", [])
            if ref in (str(item.get("project_id")), str(item.get("name")))
        ),
        None,
    )
    if project is None:
        raise LookupError(f"项目不存在：{ref}")
    return project


def _authorized(ref: str, request: Request):
    project = _project(ref)
    permissions.ensure_project_owner(project, getattr(request.state, "user", None))
    return project


@router.get("/schema")
def block_schema():
    """元素类型 / 渲染器 / 证据种类清单（供前端与自动化声明支持版本）。"""
    return ok(
        "查询成功",
        {
            "schema_version": SCHEMA_VERSION,
            "types": [
                {
                    "type": name,
                    "label": spec["label"],
                    "renderer": spec["renderer"],
                    "scope": spec["scope"],
                    "resolvable": spec["resolvable"],
                }
                for name, spec in BLOCK_TYPES.items()
            ],
            "limits": {
                "max_blocks": compositions.MAX_BLOCKS,
                "max_compositions_per_project": compositions.MAX_COMPOSITIONS_PER_PROJECT,
            },
        },
    )


@router.get("/{project_ref}/candidates")
def block_candidates(
    project_ref: str,
    request: Request,
    refresh: bool = Query(default=False, description="true 时跳过巡检合并结果缓存"),
):
    """全部授权任务的元素候选（轻量：不解析图像/DOS/结构）。"""
    try:
        project = _authorized(project_ref, request)
        data = list_candidates(project, force=refresh)
        return ok("查询成功", data)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取候选失败：{e}"))


@router.post("/{project_ref}/evidence")
def block_evidence(project_ref: str, request: Request, payload: dict = Body(default={})):
    """按（元素类型, 任务/组）解析一条 Evidence；不落盘。"""
    try:
        project = _authorized(project_ref, request)
        block_type = str((payload or {}).get("type") or "")
        task_id = str((payload or {}).get("task_id") or "")
        group_id = str((payload or {}).get("group_id") or "")
        data = resolve_evidence(project, block_type, task_id=task_id, group_id=group_id)
        return ok("解析成功", data)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except KeyError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"解析证据失败：{e}"))


@router.get("/{project_ref}/compositions")
def composition_list(project_ref: str, request: Request):
    try:
        project = _authorized(project_ref, request)
        return ok("查询成功", {"items": compositions.list_for(project)})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取组合失败：{e}"))


@router.post("/{project_ref}/preview")
def composition_preview(project_ref: str, request: Request, payload: dict = Body(default={})):
    try:
        project = _authorized(project_ref, request)
        doc = compositions.preview(project, payload)
        return ok("预览成功", {"document": doc, "html": compositions.render_html(doc)})
    except compositions.RevisionConflict as e:
        return JSONResponse(status_code=409, content=fail(str(e), {"code": "revision_conflict", "current_revision": e.current}))
    except compositions.EvidenceStale as e:
        return JSONResponse(status_code=409, content=fail(str(e), {"code": "evidence_stale", "changes": e.changes}))
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content=fail(str(e)))


@router.post("/{project_ref}/compositions/{composition_id}/check")
def composition_check(project_ref: str, composition_id: str, request: Request):
    try:
        project = _authorized(project_ref, request)
        return ok("检查完成", {"changes": compositions.check_updates(project, compositions.load(project, composition_id))})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))


@router.post("/{project_ref}/compositions")
def composition_create(project_ref: str, request: Request, payload: dict = Body(default={})):
    """新建组合：blocks 按提交顺序保存；科学数据由后端按 ID 解析后冻结。"""
    try:
        project = _authorized(project_ref, request)
        doc = compositions.save(project, payload or {})
        return ok("组合已保存", doc)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except compositions.EvidenceStale as e:
        return JSONResponse(
            status_code=409,
            content=fail("证据版本已变化，需要显式刷新", {"code": "evidence_stale",
                                                     "changes": e.changes}),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"保存组合失败：{e}"))


@router.get("/{project_ref}/compositions/{composition_id}")
def composition_detail(project_ref: str, composition_id: str, request: Request):
    try:
        project = _authorized(project_ref, request)
        return ok("查询成功", compositions.load(project, composition_id))
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取组合失败：{e}"))


@router.put("/{project_ref}/compositions/{composition_id}")
def composition_update(
    project_ref: str,
    composition_id: str,
    request: Request,
    payload: dict = Body(default={}),
):
    """整体替换（顺序/标题/隐藏/分组都按 block_id 保存）；乐观锁 revision。"""
    try:
        project = _authorized(project_ref, request)
        expected = (payload or {}).get("expected_revision")
        doc = compositions.save(
            project,
            payload or {},
            composition_id=composition_id,
            expected_revision=expected,
        )
        return ok("组合已更新", doc)
    except compositions.RevisionConflict as e:
        return JSONResponse(
            status_code=409,
            content=fail(str(e), {"code": "revision_conflict", "current_revision": e.current}),
        )
    except compositions.EvidenceStale as e:
        return JSONResponse(
            status_code=409,
            content=fail("证据版本已变化，需要显式刷新", {"code": "evidence_stale",
                                                     "changes": e.changes}),
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"更新组合失败：{e}"))


@router.delete("/{project_ref}/compositions/{composition_id}")
def composition_delete(project_ref: str, composition_id: str, request: Request):
    """软删除：保留文件与证据，不碰完整报告与原始计算。"""
    try:
        project = _authorized(project_ref, request)
        compositions.delete(project, composition_id)
        return ok("组合已删除", {"composition_id": composition_id})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"删除组合失败：{e}"))


@router.get("/{project_ref}/compositions/{composition_id}/export.html")
def composition_html(
    project_ref: str,
    composition_id: str,
    request: Request,
    download: bool = Query(default=False),
    print: bool = Query(default=False, description="打开后调起浏览器打印（导出 PDF）"),
):
    """用组合里冻结的 Evidence 导出自包含 HTML（不重新解析、不加载外部资源）。"""
    try:
        project = _authorized(project_ref, request)
        doc = compositions.load(project, composition_id)
        html_text = compositions.render_html(doc, auto_print=print)
        filename = f"{doc.get('title') or composition_id}"
        disposition = "attachment" if download else "inline"
        header = (
            f"{disposition}; filename=\"{composition_id}.html\"; "
            f"filename*=UTF-8''{quote(filename)}.html"
        )
        return Response(
            content=html_text,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": header},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"导出组合失败：{e}"))
