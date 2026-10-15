"""报告**交互版**导出（2026-10-15，v0.9.62）。

单文件 HTML 报告要支持"勾轨道 / 改范围 / 算带中心"这类运行时操作，就必须把
**ECharts 运行时 + 交互逻辑 + 数据**一起塞进 HTML —— 静态 SVG 做不到（它是画完的图）。

分工：

- 运行时 JS：前端打包产出 `dist/report/report-interactive.js`（`npm run build` 的最后一步，
  源码见 `src/interactive/reportRuntime.ts`）。读不到就**自动降级**为纯静态导出
  （报告里那张 SVG 就是兜底，正文数值照旧）；
- 数据：PDOS 读本地整合数据（`<任务>/pdos/dos.json`，与接口同一份）；
  功函数曲线不大，直接从报告结构化数据里取（`work_function_summary`）；
- 输出：`report_export.build_html(interactive_js=..., interactive_data=...)` 负责注入。

体积参考（真机 model2）：运行时 ~548 KB；PDOS 数据 3.0 MB（未压缩 JSON 内联）。
相对现在动辄 40 MB+ 的单文件报告（结构三视图 PNG base64 是大头）可以忽略。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from config import PROJECT_ROOT
from storage import load_db

LOGGER = logging.getLogger(__name__)

#: 打包出来的运行时（`npm run build` 的产物；缺失时导出降级为静态）
RUNTIME_PATH = PROJECT_ROOT / "dist" / "report" / "report-interactive.js"
#: 运行时合理上限（防止误读了别的文件把报告撑爆）
RUNTIME_MAX_BYTES = 4 * 1024 * 1024

_RUNTIME_CACHE: Dict[str, Any] = {"stamp": None, "text": ""}


def runtime_js() -> str:
    """读运行时 JS（按 mtime/size 缓存）。读不到返回空串 → 调用方走静态导出。"""
    try:
        stat = RUNTIME_PATH.stat()
    except OSError:
        return ""
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _RUNTIME_CACHE["stamp"] == stamp:
        return _RUNTIME_CACHE["text"]
    if stat.st_size <= 0 or stat.st_size > RUNTIME_MAX_BYTES:
        return ""
    try:
        text = RUNTIME_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - 读不到就当没有
        LOGGER.warning("读取报告交互运行时失败：%s", exc)
        return ""
    _RUNTIME_CACHE.update({"stamp": stamp, "text": text})
    return text


def _find_task(project_name: str, task_id: str) -> Optional[Dict[str, Any]]:
    """按任务 ID 在项目库里找任务对象（PDOS 本地路径解析要它）。"""
    try:
        db = load_db()
    except Exception as exc:  # noqa: BLE001 - 读不到库就退化成"没有交互数据"
        LOGGER.warning("读取任务库失败：%s", exc)
        return None
    for project in db.get("projects") or []:
        if str(project.get("name") or "") != project_name:
            continue
        for task in project.get("tasks") or []:
            if str(task.get("task_id") or "") == str(task_id):
                return task
    return None


def pdos_view(project_name: str, task_id: str) -> Optional[Dict[str, Any]]:
    """本地 PDOS 整合数据 → 与 `GET /api/jobs/tasks/{id}/pdos` 完全相同的视图对象。"""
    task = _find_task(project_name, task_id)
    if task is None:
        return None
    try:
        import pdos  # 延迟导入：避免模块加载顺序耦合

        if not pdos.data_path(project_name, task).is_file():
            return None
        return pdos.load_view(project_name, task)
    except Exception as exc:  # noqa: BLE001 - 单个任务失败不影响整份报告
        LOGGER.warning("读取 %s 的 PDOS 数据失败：%s", task_id, exc)
        return None


def interactive_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    """收集交互版需要的全部数据：`{pdos: {task_id: view}, work_function: {task_id: summary}}`。

    只收报告里**已有挂点**的任务（有 `pdos_summary` / `work_function_summary` 的那些）。
    """
    payload: Dict[str, Any] = {"pdos": {}, "work_function": {}}
    project_name = str(((doc.get("metadata") or {}).get("project_name")) or "")
    tasks = (((doc.get("science") or {}).get("ele") or {}).get("tasks")) or []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "")
        if not task_id:
            continue
        if item.get("pdos_summary"):
            view = pdos_view(project_name, task_id)
            if view:
                payload["pdos"][task_id] = view
        if item.get("work_function_summary"):
            payload["work_function"][task_id] = item["work_function_summary"]
    return payload


def has_payload(payload: Optional[Dict[str, Any]]) -> bool:
    if not payload:
        return False
    return bool((payload.get("pdos") or {}) or (payload.get("work_function") or {}))


def data_script(payload: Dict[str, Any]) -> str:
    """内联数据脚本（`<` 转义，避免 JSON 里出现 `</script`）。"""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c")


def interactive_kwargs(doc: Dict[str, Any], *, interactive: bool) -> Dict[str, Any]:
    """给 `report_export.render_html(...)` 的关键字参数（**交互版**）。

    `interactive=False`、运行时文件缺失、或这份报告根本没有 PDOS/功函数挂点时，
    返回空 kwargs —— 调用方不用关心细节，导出自然就是纯静态版。
    """
    if not interactive:
        return {}
    runtime = runtime_js()
    if not runtime:
        LOGGER.info("报告交互运行时不存在（先跑 npm run build），本次导出为静态版")
        return {}
    payload = interactive_payload(doc)
    if not has_payload(payload):
        return {}
    LOGGER.info(
        "报告交互版：运行时 %.0f KB · PDOS %d 个任务 · 功函数 %d 个任务",
        len(runtime) / 1024,
        len(payload.get("pdos") or {}),
        len(payload.get("work_function") or {}),
    )
    return {"interactive_js": runtime, "interactive_data": payload}
