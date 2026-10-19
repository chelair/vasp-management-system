"""项目报告接口：生成 / 列表 / 详情 / 结构化数据 / Markdown / HTML 导出 / 图表 / 删除。

路径统一挂在 `/api/reports/project/...` 下，避免与既有的 `/api/reports/groups`
（巡检详情里的自由能 / NEB 看板）冲突。
"""

from pathlib import Path
import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from envelope import fail, ok
import permissions
from report_builder import build_report
from report_export import render_html
from report_interactive import interactive_kwargs
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
    save_report,
)
from storage import load_db
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/reports/project", tags=["project-reports"])


def _project_refs(db, payload: dict) -> list:
    """解析生成范围：project_ids / all。

    `all=true`（「生成所有项目」/ 每日自动报告）**排除已关闭项目**（2026-10-13 用户要求）——
    项目关闭后不再有新数据，重算只是白跑；单个项目仍可显式生成（`project_id`）。
    """
    ids = payload.get("project_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    if payload.get("all"):
        return [
            str(p.get("project_id"))
            for p in db.get("projects", [])
            if not p.get("closed")
        ]
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
            if payload.get("all"):
                # 请求了 all，但可见项目要么都已关闭、要么被权限过滤光了 —— 不算参数错误
                return ok(
                    "没有需要生成报告的项目（已关闭项目不计入「全部」）",
                    {"reports": [], "failed": []},
                )
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
        # 注解（结果分析 / 论文参考）取**当前**文件内容：生成后新填/改的注解刷新即可见
        try:
            from report_builder import attach_report_notes

            attach_report_notes(doc, report_id)
        except Exception:  # noqa: BLE001 - 注解失败不影响报告详情
            pass
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
        doc, markdown, _ = load_report(report_id)
        # 与 HTML 下载同一口径：人类可读文件名 + ASCII 回退
        project_name = str(((doc.get("metadata") or {}).get("project_name")) or report_id)
        generated = str((doc.get("metadata") or {}).get("generated_at") or "")[:10]
        pretty = f"{project_name}_项目报告{f'_{generated}' if generated else ''}.md"
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"{report_id}.md\"; "
                    f"filename*=UTF-8''{quote(pretty)}"
                )
            },
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
    interactive: bool = Query(
        default=True,
        description="是否内联 ECharts 运行时让 PDOS/功函数图可交互（体积 +约 0.6MB 运行时 + PDOS 数据）",
    ),
    download: bool = Query(
        default=False,
        description="true 时按附件返回（浏览器直接下载成文件）；默认 inline，在标签页里打开",
    ),
):
    """导出**自包含 HTML**：可按章节范围导出（如取消风险分析），图表内联 SVG。

    - `?sections=risks,actions` 只导出指定章节；
    - `?print=1` 打开后自动调起浏览器打印对话框 → 直接「另存为 PDF」。
    - `?download=1` → `Content-Disposition: attachment`（**下载按钮**走这个；
      文件名用「项目名_项目报告_日期.html」，并同时给 ASCII 回退名）。
    """
    try:
        _ensure_report_access(report_id, request)
        doc, _, _ = load_report(report_id)
        # 导出前刷新注解：生成报告后新填写的「结果分析与论文参考」也要进 HTML
        try:
            from report_builder import attach_report_notes

            attach_report_notes(doc, report_id)
        except Exception:  # noqa: BLE001 - 注解失败不影响导出
            pass
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
            **interactive_kwargs(doc, interactive=interactive),
        )
        # 文件名：优先给人类可读的「项目名_项目报告_日期.html」，同时保留 ASCII 回退
        project_name = str(((doc.get("metadata") or {}).get("project_name")) or report_id)
        generated = str((doc.get("metadata") or {}).get("generated_at") or "")[:10]
        pretty = f"{project_name}_项目报告{f'_{generated}' if generated else ''}.html"
        disposition = "attachment" if download else "inline"
        filename = (
            f"{disposition}; filename=\"{report_id}.html\"; filename*=UTF-8''{quote(pretty)}"
        )
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": filename},
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
        from report_ai_notes import annotate_staleness
        doc, _, _ = load_report(report_id)
        notes = read_notes(report_id)
        annotate_staleness(doc, notes)
        return ok("查询成功", {"notes": notes})
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
        from report_ai_notes import save_reviewed, annotate_staleness
        notes = save_reviewed(report_id, getattr(request.state, "user", None) or {}, payload)
        doc, _, _ = load_report(report_id)
        annotate_staleness(doc, notes)
        return ok("已保存", {"notes": notes})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"保存报告注解失败：{e}"))


class NoteGenerationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=200)
    connection_id: str = Field(min_length=1, max_length=64)


@router.get("/{report_id}/notes/ai-status")
def project_report_note_ai_status(report_id: str, request: Request):
    from routers.ai_chat import actor, guard
    from report_ai_notes import status

    @guard
    def read():
        user, _ = actor(request)
        _ensure_report_access(report_id, request)
        doc, _, _ = load_report(report_id)
        return ok("查询成功", status(doc, user))
    result = read()
    if isinstance(result, dict):
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    return result


@router.post("/{report_id}/notes/ai-preview")
async def project_report_note_ai_preview(report_id: str, request: Request, body: NoteGenerationBody):
    """独立于普通报告生成；单条预览，批量由前端逐条调用并保留部分成功结果。"""
    from routers.ai_chat import actor
    from ai_chat_service import TextGenerationControl
    from report_ai_notes import preview

    control = TextGenerationControl()
    worker = None
    disconnected = None
    headers = {"Cache-Control": "no-store"}
    try:
        user, _ = actor(request)
        _ensure_report_access(report_id, request)
        worker = asyncio.create_task(asyncio.to_thread(preview, report_id, body.key, user, body.connection_id, control))
        async def wait_disconnect():
            # 已解析 JSON body 后监听真正的 disconnect；BaseHTTPMiddleware 下
            # is_disconnected 的即时探测可能漏掉队列中的断开事件。
            while (await request.receive())["type"] != "http.disconnect":
                pass
        disconnected = asyncio.create_task(wait_disconnect())
        done, _ = await asyncio.wait({worker, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        if disconnected in done:
            control.cancel()
            worker.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            return JSONResponse(status_code=499, content=fail("生成已取消，原注解未改动"), headers=headers)
        return JSONResponse(ok("草稿已生成，尚未保存", await worker), headers=headers)
    except permissions.PermissionDenied:
        raise
    except FileNotFoundError:
        return JSONResponse(status_code=404, content=fail("报告不存在或已重新生成，请刷新"), headers=headers)
    except ValueError as exc:
        return JSONResponse(status_code=400, content=fail(str(exc)), headers=headers)
    except asyncio.CancelledError:
        control.cancel()
        if worker:
            worker.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        raise
    except Exception:
        return JSONResponse(status_code=503, content=fail("AI 草稿生成失败；普通报告和原注解不受影响"), headers=headers)
    finally:
        if disconnected:
            disconnected.cancel()


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
