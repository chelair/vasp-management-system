"""项目报告存储：按项目分目录 + 索引文件。

目录结构：
    data/reports/index.json                      # 报告索引（列表查询用）
    data/reports/<项目名>/<报告ID>/report.json    # 结构化数据
                                   /report.md     # Markdown 全文
                                   /charts/*.svg  # 图表（纯 SVG）

写入使用「临时目录 + 原子替换」，索引更新加锁，避免并发生成互相覆盖。
"""

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR

REPORTS_DIR = DATA_DIR / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"
_lock = threading.Lock()


def _ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_index() -> List[Dict[str, Any]]:
    if not INDEX_FILE.is_file():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - 索引损坏时重建
        return []


def _write_index(items: List[Dict[str, Any]]) -> None:
    _ensure_dirs()
    tmp = INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX_FILE)


def _safe_name(value: str) -> str:
    keep = [c if (c.isalnum() or c in "-_@.") else "_" for c in str(value)]
    return "".join(keep) or "project"


def report_dir(report_id: str) -> Optional[Path]:
    """按索引定位报告目录（不信任外部传入的路径拼接）。"""
    for item in _read_index():
        if item.get("report_id") == report_id:
            return REPORTS_DIR / _safe_name(str(item.get("project_name"))) / report_id
    return None


def save_report(
    doc: Dict[str, Any], markdown: str, charts: Dict[str, str]
) -> Dict[str, Any]:
    """保存一份报告（结构化数据 + Markdown + 图表）并更新索引。"""
    meta = doc.get("metadata") or {}
    report_id = str(meta.get("report_id") or "")
    project_name = str(meta.get("project_name") or "")
    if not report_id:
        raise ValueError("报告缺少 metadata.report_id")
    target = REPORTS_DIR / _safe_name(project_name) / report_id
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "charts").mkdir(parents=True, exist_ok=True)
    (tmp / "report.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tmp / "report.md").write_text(markdown, encoding="utf-8")
    for name, svg in charts.items():
        (tmp / "charts" / name).write_text(svg, encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(target)

    entry = {
        "report_id": report_id,
        "project_id": str(meta.get("project_id") or ""),
        "project_name": project_name,
        "generated_at": str(meta.get("generated_at") or ""),
        "time_window": meta.get("time_window") or {},
        "schema_version": doc.get("schema_version"),
        "project_status": (doc.get("executive_summary") or {}).get("project_status"),
        "summary": (doc.get("executive_summary") or {}).get("summary_text", ""),
        "risk_summary": (doc.get("risks") or {}).get("summary") or {},
        "completion_percent": (
            (doc.get("executive_summary") or {}).get("task_stats") or {}
        ).get("completion_percent"),
        "chart_count": len(charts),
        "json_path": f"{_safe_name(project_name)}/{report_id}/report.json",
        "markdown_path": f"{_safe_name(project_name)}/{report_id}/report.md",
        "directory": str(target),
    }
    with _lock:
        # 同一个项目只保留最新一份报告：先清理该项目的历史报告目录
        keep = []
        for item in _read_index():
            same_project = str(item.get("project_name")) == project_name
            if same_project and item.get("report_id") != report_id:
                old_dir = REPORTS_DIR / _safe_name(project_name) / str(item.get("report_id"))
                if old_dir.exists() and old_dir != target:
                    shutil.rmtree(old_dir, ignore_errors=True)
                continue
            if item.get("report_id") != report_id:
                keep.append(item)
        keep.insert(0, entry)
        _write_index(keep)
    return entry


def list_reports(project: Optional[str] = None) -> List[Dict[str, Any]]:
    items = _read_index()
    if project:
        items = [
            i
            for i in items
            if project in (str(i.get("project_id")), str(i.get("project_name")))
        ]
    return sorted(items, key=lambda i: str(i.get("generated_at") or ""), reverse=True)


def load_report(report_id: str) -> Tuple[Dict[str, Any], str, Optional[Path]]:
    """返回 (结构化数据, Markdown 文本, 报告目录)。"""
    directory = report_dir(report_id)
    if directory is None or not (directory / "report.json").is_file():
        raise FileNotFoundError(f"报告不存在：{report_id}")
    doc = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    markdown = (
        (directory / "report.md").read_text(encoding="utf-8")
        if (directory / "report.md").is_file()
        else ""
    )
    return doc, markdown, directory


def read_chart(report_id: str, relative_path: str) -> Optional[str]:
    """读取图表文件（仅允许 charts/ 下的 .svg，防目录穿越）。"""
    directory = report_dir(report_id)
    if directory is None:
        return None
    name = Path(relative_path).name
    path = directory / "charts" / name
    if not name.endswith(".svg") or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def delete_report(report_id: str) -> bool:
    directory = report_dir(report_id)
    if directory is None:
        return False
    if directory.exists():
        shutil.rmtree(directory)
    with _lock:
        items = [i for i in _read_index() if i.get("report_id") != report_id]
        _write_index(items)
    return True
