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
#: 结构 3D 用的 3Dmol（本地已有一份，报告导出时原样内联 —— 全局脚本，离线可用）
MOL_PATH = PROJECT_ROOT / "public" / "3dmol" / "3Dmol-min.js"
MOL_MAX_BYTES = 4 * 1024 * 1024

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


def mol_js() -> str:
    """读本地 3Dmol 源码（结构 3D 视图用）。读不到返回空串 → 导出里 3D 挂点自动跳过。"""
    try:
        stat = MOL_PATH.stat()
        if stat.st_size <= 0 or stat.st_size > MOL_MAX_BYTES:
            return ""
        return MOL_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        LOGGER.warning("读取 3Dmol 失败：%s", exc)
        return ""


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
    payload: Dict[str, Any] = {
        "pdos": {},
        "work_function": {},
        "structure": {},
        "bader": {},
        "free_energy": {},
    }
    project_name = str(((doc.get("metadata") or {}).get("project_name")) or "")
    # 结构 3D（v0.9.72）：结构优化任务的 POSCAR/CONTCAR CIF 就在结构化数据里（无需读盘）
    for opt in ((doc.get("science") or {}).get("opt") or []):
        if not isinstance(opt, dict):
            continue
        task_id = str(opt.get("task_id") or "")
        structure = opt.get("structure") or {}
        if task_id and (structure.get("poscar_cif") or structure.get("contcar_cif")):
            payload["structure"][task_id] = {
                "task_name": opt.get("task_name"),
                "poscar_cif": structure.get("poscar_cif"),
                "contcar_cif": structure.get("contcar_cif"),
            }
    # 自由能路径的中间体（v0.9.73）：正文里 3D 视图 + 表格「结构 N」切换
    for path in ((doc.get("science") or {}).get("free_energy") or []):
        if not isinstance(path, dict):
            continue
        group_id = str(path.get("group_id") or "")
        items = [
            {"structure_label": s.get("structure_label"), "cif": s.get("cif")}
            for s in (path.get("structures") or [])
            if s.get("cif")
        ]
        if group_id and items:
            payload["free_energy"][group_id] = items
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
        # Bader：3D 结构（CIF）+ 逐原子读数（着色/读数在前端算）
        summary = item.get("bader_summary") or {}
        if summary.get("cif") and summary.get("atoms"):
            payload["bader"][task_id] = {
                "task_name": item.get("task_name"),
                "cif": summary.get("cif"),
                "atoms": summary.get("atoms"),
            }
    return payload


def has_payload(payload: Optional[Dict[str, Any]]) -> bool:
    if not payload:
        return False
    return bool(
        (payload.get("pdos") or {})
        or (payload.get("work_function") or {})
        or (payload.get("structure") or {})
        or (payload.get("bader") or {})
        or (payload.get("free_energy") or {})
    )


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
        "报告交互版：运行时 %.0f KB · PDOS %d · 功函数 %d · 结构 3D %d · Bader 3D %d",
        len(runtime) / 1024,
        len(payload.get("pdos") or {}),
        len(payload.get("work_function") or {}),
        len(payload.get("structure") or {}),
        len(payload.get("bader") or {}),
    )
    # 结构 3D 需要 3Dmol：有结构/Bader 3D 挂点时才内联（约 512 KB）
    need_mol = bool(
        (payload.get("structure") or {})
        or (payload.get("bader") or {})
        or (payload.get("free_energy") or {})
    )
    mol = mol_js() if need_mol else ""
    return {"interactive_js": runtime, "interactive_data": payload, "mol_js": mol}
