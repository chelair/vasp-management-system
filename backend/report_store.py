"""项目报告存储：按项目分目录 + 索引文件。

目录结构：
    data/reports/index.json                      # 报告索引（列表查询用）
    data/reports/<项目名>/<报告ID>/report.json    # 结构化数据
                                   /report.md     # Markdown 全文
                                   /charts/*.svg  # 图表（纯 SVG）

写入使用「临时目录 + 原子替换」，索引更新加锁，避免并发生成互相覆盖。
"""

import base64
import json
import os
import shutil
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR
from report_export import render_html


def image_data_uri(path: Path) -> Optional[str]:
    """把 PNG 读成 `data:image/png;base64,...`（HTML 内联用）；读不到返回 None。"""
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None

REPORTS_DIR = DATA_DIR / "reports"
INDEX_FILE = REPORTS_DIR / "index.json"
#: 报告注解（结果分析描述 / 论文写作参考）：data/reports/notes/{report_id}.json
NOTES_DIR = REPORTS_DIR / "notes"
_lock = threading.Lock()
_notes_lock = threading.Lock()


def _notes_path(report_id: str) -> Path:
    return NOTES_DIR / f"{_safe_name(report_id)}.json"


#: 报告编辑（隐藏章节 / 元素）：data/reports/edits/{report_id}.json
EDITS_DIR = REPORTS_DIR / "edits"


def _edits_path(report_id: str) -> Path:
    return EDITS_DIR / f"{_safe_name(report_id)}.json"


def read_edits(report_id: str) -> Dict[str, List[str]]:
    """读报告的隐藏状态：`{"hidden_sections": [...], "hidden_elements": [...]}`。"""
    path = _edits_path(report_id)
    if not path.is_file():
        return {"hidden_sections": [], "hidden_elements": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 损坏当没有
        return {"hidden_sections": [], "hidden_elements": []}
    if not isinstance(data, dict):
        return {"hidden_sections": [], "hidden_elements": []}
    return {
        "hidden_sections": [str(x) for x in (data.get("hidden_sections") or [])][:200],
        "hidden_elements": [str(x) for x in (data.get("hidden_elements") or [])][:2000],
    }


def save_edits(
    report_id: str, hidden_sections: List[str], hidden_elements: List[str]
) -> Dict[str, List[str]]:
    """覆盖写报告的隐藏状态（只影响前端展示与导出，不动报告本体）。"""
    payload = {
        "hidden_sections": [str(x) for x in (hidden_sections or [])][:200],
        "hidden_elements": [str(x) for x in (hidden_elements or [])][:2000],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    EDITS_DIR.mkdir(parents=True, exist_ok=True)
    path = _edits_path(report_id)
    tmp = path.with_name(path.name + ".tmp")
    with _notes_lock:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return {
        "hidden_sections": payload["hidden_sections"],
        "hidden_elements": payload["hidden_elements"],
    }


def read_notes(report_id: str) -> Dict[str, Dict[str, str]]:
    """读一份报告的全部注解：`{key: {analysis_note, paper_note, updated_at}}`（缺文件=空）。

    key 是 `task_id`（任务级）或 `section_<章节key>`（模块级）。读坏当空，不抛错。
    """
    path = _notes_path(report_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 文件损坏当空
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        out[str(key)] = {
            "analysis_note": str(value.get("analysis_note") or ""),
            "paper_note": str(value.get("paper_note") or ""),
            "updated_at": str(value.get("updated_at") or ""),
        }
    return out


def save_note(
    report_id: str, key: str, analysis_note: str, paper_note: str
) -> Dict[str, Dict[str, str]]:
    """写一条注解（按 key 覆盖），返回整份注解。key 为空/超长直接拒绝。"""
    clean = str(key or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError("key 不能为空且长度不超过 200")
    notes = read_notes(report_id)
    entry = {
        "analysis_note": str(analysis_note or ""),
        "paper_note": str(paper_note or ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not entry["analysis_note"] and not entry["paper_note"]:
        notes.pop(clean, None)  # 两条都清空 = 删除该条
    else:
        notes[clean] = entry
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = _notes_path(report_id)
    tmp = path.with_name(path.name + ".tmp")
    with _notes_lock:
        tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return notes


def _ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_index() -> List[Dict[str, Any]]:
    if not INDEX_FILE.is_file():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - 索引损坏时重建
        return []
    # directory 统一成**相对 data/reports 的路径**：老索引里是绝对路径（含 Windows 盘符），
    # 换机器后会失效，这里读的时候就地归一化
    for item in items:
        if not isinstance(item, dict):
            continue
        directory = str(item.get("directory") or "")
        project = _safe_name(str(item.get("project_name") or ""))
        report_id = str(item.get("report_id") or "")
        if project and report_id:
            item["directory"] = f"{project}/{report_id}"
        elif directory:
            item["directory"] = directory.replace("\\", "/").rsplit("reports/", 1)[-1]
    return items


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
    (tmp / "images").mkdir(parents=True, exist_ok=True)
    (tmp / "report.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (tmp / "report.md").write_text(markdown, encoding="utf-8")
    for name, svg in charts.items():
        (tmp / "charts" / name).write_text(svg, encoding="utf-8")
    # 结构三视图 PNG 也存进报告目录（报告自包含：HTML 里是 base64，这里留原件备查）
    for name, src in (doc.get("images") or {}).items():
        try:
            shutil.copyfile(str(src), tmp / "images" / Path(str(name)).name)
        except OSError:
            continue
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(target)

    # 结构化数据副本（2026-10-13，§4.4）：`data/reports/structured/<report_id>.json`
    # 只落**规范化 AI 视图**（ai_view）+ 元信息，供后续向量化/RAG 检索；失败不影响报告本体
    try:
        view = (doc.get("ai_view") or {})
        if isinstance(view, dict) and view:
            structured_dir = REPORTS_DIR / "structured"
            structured_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "report_id": report_id,
                "project_name": project_name,
                "project_id": meta.get("project_id") or "",
                "generated_at": view.get("generated_at") or meta.get("generated_at"),
                "schema_version": doc.get("schema_version"),
                "ai_view": view,
            }
            (structured_dir / f"{_safe_name(report_id)}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    except Exception:  # noqa: BLE001 - 结构化副本失败不影响报告
        pass

    # 单文件自包含 HTML（命名带日期，放在项目报告目录下）：用户口径 2026-10-07
    html_path: Optional[Path] = None
    try:
        html_text = render_html(
            doc,
            doc.get("markdown_sections") or [],
            chart_loader=lambda name: (target / "charts" / name).read_text(
                encoding="utf-8", errors="replace"
            )
            if (target / "charts" / name).is_file()
            else None,
            image_loader=lambda rel: image_data_uri(target / rel),
        )
        html_path = target.parent / f"report_{date.today().isoformat()}.html"
        html_path.write_text(html_text, encoding="utf-8")
    except Exception:  # noqa: BLE001 - HTML 生成失败不影响报告本体
        html_path = None

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
        "html_path": (
            f"{_safe_name(project_name)}/{html_path.name}" if html_path else ""
        ),
        "html_bytes": html_path.stat().st_size if html_path else 0,
        # 目录用**相对 data/reports 的相对路径**（跨机器迁移后仍然有效）
        "directory": f"{_safe_name(project_name)}/{report_id}",
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


def read_image_data_uri(report_id: str, relative_path: str) -> Optional[str]:
    """报告目录里的结构三视图 → base64 data URI（HTML 导出内联用）。"""
    directory = report_dir(report_id)
    if directory is None:
        return None
    target = (directory / relative_path).resolve()
    try:
        target.relative_to(directory.resolve())  # 防目录穿越
    except ValueError:
        return None
    return image_data_uri(target)


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
