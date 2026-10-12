"""项目报告接口：生成 / 列表 / 详情 / 结构化数据 / Markdown / HTML 导出 / 图表 / 删除。

路径统一挂在 `/api/reports/project/...` 下，避免与既有的 `/api/reports/groups`
（巡检详情里的自由能 / NEB 看板）冲突。
"""

from pathlib import Path

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from envelope import fail, ok
import permissions
from report_builder import build_report
from report_export import render_html
from report_schema import schema_manifest
from report_store import (
    delete_report,
    list_reports,
    load_report,
    read_chart,
    read_edits,
    read_image_data_uri,
    read_notes,
    report_dir,
    save_edits,
    save_note,
    save_report,
)
from storage import load_db

router = APIRouter(prefix="/reports/project", tags=["project-reports"])


def _project_refs(db, payload: dict) -> list:
    """解析生成范围：project_ids / all。"""
    ids = payload.get("project_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    if payload.get("all"):
        return [str(p.get("project_id")) for p in db.get("projects", [])]
    if payload.get("project_id"):
        return [str(payload["project_id"])]
    return []


def _report_project(db, report_id: str):
    """按报告 ID 找到所属项目（报告索引里带 project_id / project_name）。"""
    entry = next(
        (i for i in list_reports() if str(i.get("report_id")) == str(report_id)), None
    )
    if entry is None:
        return None
    ref = str(entry.get("project_id") or entry.get("project_name") or "")
    return next(
        (
            p
            for p in db.get("projects", [])
            if ref in (str(p.get("project_id")), str(p.get("name")))
        ),
        None,
    )


def _ensure_report_access(report_id: str, request: Request) -> None:
    """单报告越权 → 403（校验顺序：先定位项目，再校验归属）。"""
    db = load_db()
    project = _report_project(db, report_id)
    if project is None:
        # 索引里找不到（可能是历史报告）：只允许 admin 访问
        permissions.ensure_admin(
            getattr(request.state, "user", None), "无权访问该报告"
        )
        return
    permissions.ensure_project_owner(project, getattr(request.state, "user", None))


@router.get("/schema")
def project_report_schema():
    """报告 schema 清单：版本、枚举、单位、章节（供大模型/前端声明支持版本）。"""
    return ok("查询成功", schema_manifest())


@router.post("/generate")
def generate_project_report(
    request: Request,
    payload: dict = Body(default={}),
    refresh_cluster: bool = Query(default=False, description="true 时强制刷新集群快照"),
):
    """生成项目报告（单个或批量）。批量时每个项目独立生成，互不影响。"""
    try:
        db = load_db()
        refs = _project_refs(db, payload)
        user = getattr(request.state, "user", None)
        allowed_ids = {str(p.get("project_id")) for p in permissions.visible_projects(db, user)}
        if not permissions.is_admin(user):
            # 非 admin：只能给自己可见的项目生成（显式指定了别人的项目 → 403）
            explicit = payload.get("project_ids") or (
                [payload["project_id"]] if payload.get("project_id") else []
            )
            for ref in explicit:
                target = next(
                    (
                        p
                        for p in db.get("projects", [])
                        if str(ref) in (str(p.get("project_id")), str(p.get("name")))
                    ),
                    None,
                )
                permissions.ensure_project_owner(target, user)
            refs = [r for r in refs if str(r) in allowed_ids]
        if not refs:
            return JSONResponse(
                status_code=400,
                content=fail("请提供 project_id / project_ids，或设置 all=true 批量生成"),
            )
        window_days = int(payload.get("window_days") or 7)
        created = []
        failed = []
        for ref in refs:
            try:
                result = build_report(
                    ref, window_days=window_days, refresh_cluster=refresh_cluster
                )
                entry = save_report(
                    result["report"], result["markdown"], result["charts"]
                )
                created.append(entry)
            except permissions.PermissionDenied:
                raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
            except Exception as e:  # noqa: BLE001 - 单个项目失败不影响其他项目
                failed.append({"project": ref, "error": str(e)})
        message = f"已生成 {len(created)} 份报告" + (f"，失败 {len(failed)} 份" if failed else "")
        return ok(message, {"reports": created, "failed": failed})
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"生成报告失败：{e}"))


@router.get("/list")
def project_report_list(request: Request, project: str | None = Query(default=None)):
    """报告列表（可按项目 ID / 名称过滤）。"""
    try:
        db = load_db()
        names = permissions.visible_project_names(db, getattr(request.state, "user", None))
        rows = [
            r
            for r in list_reports(project)
            if str(r.get("project_name") or "") in names
        ]
        return ok("查询成功", {"reports": rows})
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取报告列表失败：{e}"))


@router.get("/{report_id}")
def project_report_detail(report_id: str, request: Request):
    """报告详情：索引元数据 + 章节 Markdown + 结构化数据。"""
    try:
        _ensure_report_access(report_id, request)
        doc, markdown, _ = load_report(report_id)
        entry = next(
            (i for i in list_reports() if i.get("report_id") == report_id), {}
        )
        return ok(
            "查询成功",
            {
                "meta": entry,
                "schema_version": doc.get("schema_version"),
                "markdown": markdown,
                "markdown_sections": doc.get("markdown_sections") or [],
                # 结构三视图弹窗规格（页面里点「结构 N / 映像 N」用同一个 <dialog>）
                "dialogs": doc.get("dialogs") or [],
                # 报告注解（结果分析 / 论文参考）：{key: {...}} 与按任务块聚合的 note_blocks
                "notes": doc.get("notes") or read_notes(report_id),
                "note_blocks": doc.get("note_blocks") or {},
                # 前端隐藏状态（章节/元素）：只影响展示与导出，不动报告本体
                "edits": read_edits(report_id),
                "sections": [
                    {"key": s["key"], "title": s["title"]}
                    for s in (doc.get("markdown_sections") or [])
                ],
                "charts": [
                    {"name": name, "path": f"charts/{name}"}
                    for name in (doc.get("appendix") or {}).get("charts", [])
                ]
                if isinstance((doc.get("appendix") or {}).get("charts"), list)
                else (doc.get("markdown_meta") or {}).get("chart_paths", []),
                "structured": doc,
            },
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取报告失败：{e}"))


@router.get("/{report_id}/ai")
def project_report_ai_view(report_id: str, request: Request):
    """**AI 消费视图**：键名/枚举/单位/时间统一后的报告数据（2026-10-12 新增）。

    - 键名一律 snake_case；状态字段带族名（task_status / check_status / output_state / queue_state）；
    - 能量 eV、力 eV/Å、时间本地带 `+08:00`；
    - `low_precision` 归并成 `task_status=completed` + `precision_ok=false`；
    - 老报告没有该字段时**即时计算**（纯函数，不改磁盘）。
    """
    try:
        _ensure_report_access(report_id, request)
        doc, _, _ = load_report(report_id)
        view = doc.get("ai_view")
        if not isinstance(view, dict) or not view:
            from ai_view import build_ai_view

            view = build_ai_view(doc)
        return ok("查询成功", view)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取 AI 视图失败：{e}"))


@router.get("/{report_id}/structured")
def project_report_structured(report_id: str, request: Request):
    """仅结构化数据（作为大模型输入的标准格式）。"""
    try:
        _ensure_report_access(report_id, request)
        doc, _, _ = load_report(report_id)
        return ok("查询成功", doc)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取结构化数据失败：{e}"))


@router.get("/{report_id}/markdown")
def project_report_markdown(report_id: str, request: Request):
    """Markdown 全文（下载用）。"""
    try:
        _ensure_report_access(report_id, request)
        _, markdown, _ = load_report(report_id)
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.md"'},
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取 Markdown 失败：{e}"))


@router.get("/{report_id}/export.html")
def project_report_html(
    report_id: str,
    request: Request,
    sections: str | None = Query(
        default=None, description="逗号分隔的章节 key；为空导出全部章节"
    ),
    inline: bool = Query(default=True, description="是否把图表内联进 HTML"),
    print: bool = Query(default=False, description="true 时打开即调起打印（导出 PDF 用）"),
    hide: str | None = Query(
        default=None, description="逗号分隔的隐藏元素 key（section:x / task:<章节>:<标题> / figure:<章节>:<序号>）"
    ),
):
    """导出**自包含 HTML**：可按章节范围导出（如取消风险分析），图表内联 SVG。

    - `?sections=risks,actions` 只导出指定章节；
    - `?print=1` 打开后自动调起浏览器打印对话框 → 直接「另存为 PDF」。
    """
    try:
        _ensure_report_access(report_id, request)
        doc, _, _ = load_report(report_id)
        chosen = (
            [s.strip() for s in sections.split(",") if s.strip()] if sections else None
        )
        html = render_html(
            doc,
            doc.get("markdown_sections") or [],
            sections=chosen,
            chart_loader=(lambda name: read_chart(report_id, name)) if inline else None,
            image_loader=(lambda rel: read_image_data_uri(report_id, rel)) if inline else None,
            auto_print=print,
            hidden=set(x.strip() for x in hide.split(",") if x.strip()) if hide else None,
        )
        filename = f"{report_id}.html"
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"导出 HTML 失败：{e}"))


@router.get("/{report_id}/files/{name}")
def project_report_chart(report_id: str, name: str, request: Request):
    """图表文件（SVG）。"""
    _ensure_report_access(report_id, request)
    svg = read_chart(report_id, name)
    if svg is None:
        return JSONResponse(status_code=404, content=fail("图表不存在"))
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{report_id}/images/{name}")
def project_report_image(report_id: str, name: str, request: Request):
    """结构三视图 PNG（报告页面在线查看用；单文件 HTML 里是 base64 内联）。"""
    _ensure_report_access(report_id, request)
    directory = report_dir(report_id)
    path = (directory / "images" / Path(name).name) if directory else None
    if path is None or not path.is_file():
        return JSONResponse(status_code=404, content=fail("图片不存在"))
    return Response(content=path.read_bytes(), media_type="image/png")


@router.get("/{report_id}/notes")
def project_report_notes(report_id: str, request: Request):
    """报告注解（结果分析描述 / 论文写作参考）：`{key: {analysis_note, paper_note, updated_at}}`。

    key = `task_id`（任务级）或 `section_<章节key>`（模块级）。
    """
    try:
        _ensure_report_access(report_id, request)
        return ok("查询成功", {"notes": read_notes(report_id)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取报告注解失败：{e}"))


@router.put("/{report_id}/notes")
def project_report_save_note(
    report_id: str,
    request: Request,
    payload: dict = Body(default={}),
):
    """写一条报告注解：body `{key, analysis_note, paper_note}`（两条都空 = 删除该条）。"""
    try:
        _ensure_report_access(report_id, request)
        key = str(payload.get("key") or "").strip()
        if not key:
            return JSONResponse(status_code=400, content=fail("缺少 key（task_id 或 section_xxx）"))
        notes = save_note(
            report_id,
            key,
            str(payload.get("analysis_note") or ""),
            str(payload.get("paper_note") or ""),
        )
        return ok("已保存", {"notes": notes})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"保存报告注解失败：{e}"))


@router.get("/{report_id}/edits")
def project_report_edits(report_id: str, request: Request):
    """报告的隐藏状态（章节 / 元素）：`{hidden_sections, hidden_elements}`。"""
    try:
        _ensure_report_access(report_id, request)
        return ok("查询成功", read_edits(report_id))
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取编辑状态失败：{e}"))


@router.put("/{report_id}/edits")
def project_report_save_edits(
    report_id: str,
    request: Request,
    payload: dict = Body(default={}),
):
    """保存隐藏状态：body `{hidden_sections: [...], hidden_elements: [...]}`（覆盖写）。"""
    try:
        _ensure_report_access(report_id, request)
        edits = save_edits(
            report_id,
            payload.get("hidden_sections") or [],
            payload.get("hidden_elements") or [],
        )
        return ok("已保存", edits)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"保存编辑状态失败：{e}"))


@router.delete("/{report_id}")
def project_report_delete(report_id: str, request: Request):
    try:
        _ensure_report_access(report_id, request)
        if not delete_report(report_id):
            return JSONResponse(status_code=404, content=fail("报告不存在"))
        return ok("报告已删除", {"report_id": report_id})
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"删除报告失败：{e}"))
