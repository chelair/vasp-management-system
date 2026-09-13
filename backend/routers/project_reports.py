"""项目报告接口：生成 / 列表 / 详情 / 结构化数据 / Markdown / HTML 导出 / 图表 / 删除。

路径统一挂在 `/api/reports/project/...` 下，避免与既有的 `/api/reports/groups`
（巡检详情里的自由能 / NEB 看板）冲突。
"""

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from envelope import fail, ok
from report_builder import build_report
from report_export import render_html
from report_schema import schema_manifest
from report_store import (
    delete_report,
    list_reports,
    load_report,
    read_chart,
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


@router.get("/schema")
def project_report_schema():
    """报告 schema 清单：版本、枚举、单位、章节（供大模型/前端声明支持版本）。"""
    return ok("查询成功", schema_manifest())


@router.post("/generate")
def generate_project_report(
    payload: dict = Body(default={}),
    refresh_cluster: bool = Query(default=False, description="true 时强制刷新集群快照"),
):
    """生成项目报告（单个或批量）。批量时每个项目独立生成，互不影响。"""
    try:
        db = load_db()
        refs = _project_refs(db, payload)
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
            except Exception as e:  # noqa: BLE001 - 单个项目失败不影响其他项目
                failed.append({"project": ref, "error": str(e)})
        message = f"已生成 {len(created)} 份报告" + (f"，失败 {len(failed)} 份" if failed else "")
        return ok(message, {"reports": created, "failed": failed})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"生成报告失败：{e}"))


@router.get("/list")
def project_report_list(project: str | None = Query(default=None)):
    """报告列表（可按项目 ID / 名称过滤）。"""
    try:
        return ok("查询成功", {"reports": list_reports(project)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取报告列表失败：{e}"))


@router.get("/{report_id}")
def project_report_detail(report_id: str):
    """报告详情：索引元数据 + 章节 Markdown + 结构化数据。"""
    try:
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
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取报告失败：{e}"))


@router.get("/{report_id}/structured")
def project_report_structured(report_id: str):
    """仅结构化数据（作为大模型输入的标准格式）。"""
    try:
        doc, _, _ = load_report(report_id)
        return ok("查询成功", doc)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取结构化数据失败：{e}"))


@router.get("/{report_id}/markdown")
def project_report_markdown(report_id: str):
    """Markdown 全文（下载用）。"""
    try:
        _, markdown, _ = load_report(report_id)
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.md"'},
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取 Markdown 失败：{e}"))


@router.get("/{report_id}/export.html")
def project_report_html(
    report_id: str,
    sections: str | None = Query(
        default=None, description="逗号分隔的章节 key；为空导出全部章节"
    ),
    inline: bool = Query(default=True, description="是否把图表内联进 HTML"),
    print: bool = Query(default=False, description="true 时打开即调起打印（导出 PDF 用）"),
):
    """导出**自包含 HTML**：可按章节范围导出（如取消风险分析），图表内联 SVG。

    - `?sections=risks,actions` 只导出指定章节；
    - `?print=1` 打开后自动调起浏览器打印对话框 → 直接「另存为 PDF」。
    """
    try:
        doc, _, _ = load_report(report_id)
        chosen = (
            [s.strip() for s in sections.split(",") if s.strip()] if sections else None
        )
        html = render_html(
            doc,
            doc.get("markdown_sections") or [],
            sections=chosen,
            chart_loader=(lambda name: read_chart(report_id, name)) if inline else None,
            auto_print=print,
        )
        filename = f"{report_id}.html"
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"导出 HTML 失败：{e}"))


@router.get("/{report_id}/files/{name}")
def project_report_chart(report_id: str, name: str):
    """图表文件（SVG）。"""
    svg = read_chart(report_id, name)
    if svg is None:
        return JSONResponse(status_code=404, content=fail("图表不存在"))
    return Response(content=svg, media_type="image/svg+xml")


@router.delete("/{report_id}")
def project_report_delete(report_id: str):
    try:
        if not delete_report(report_id):
            return JSONResponse(status_code=404, content=fail("报告不存在"))
        return ok("报告已删除", {"report_id": report_id})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"删除报告失败：{e}"))
