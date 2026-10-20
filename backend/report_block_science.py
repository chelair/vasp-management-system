"""Local-only adapters for R2. No SSH, jobs, analysis execution, or source writes.

Reuse existing parsers and export charts, freeze both chart and interactive payload.
Unknown/failed sources remain visible as missing/unparsed evidence.
"""
from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path

import bader
import charge_diff
import pdos
import structure_images
import work_function
from cif_convert import convert_structure_to_cif
from paths import local_root
from task_paths import task_dir, task_files_dir

MAX_FILE_BYTES = 24 * 1024 * 1024


def checked_path(project, task, path):
    """Reject symlinks and project escapes before passing paths to legacy parsers."""
    path = Path(path)
    root = local_root() / str(project["name"])
    if not path.absolute().is_relative_to(root.absolute()) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("本地数据路径越出当前项目")
    current = path
    while current != root.parent and current != current.parent:
        if current.is_symlink():
            raise ValueError("报告数据不读取符号链接")
        current = current.parent
    if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("单个报告数据文件超过24MiB，请缩小结果数据")
    return path


def file_sources(project, task, paths):
    result = []
    for value in paths:
        path = checked_path(project, task, value)
        if not path.is_file():
            continue
        result.append({"file": str(path.relative_to(local_root())),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def structure(project, task):
    result = {"structure_source": "local_mirror", "note": "本地镜像快照，未验证与历史巡检/分析时结构一致", "images": []}
    paths = []
    with tempfile.TemporaryDirectory(prefix="vasp-report-cif-") as temporary:
        for label in ("POSCAR", "CONTCAR"):
            src = checked_path(project, task, task_files_dir(project["name"], task) / label)
            out = Path(temporary) / (label + ".cif")
            if src.is_file() and convert_structure_to_cif(src, out):
                result[label.lower() + "_cif"] = out.read_text(encoding="utf-8")
                paths.append(src)
    for label, views in structure_images.task_views(project["name"], task).items():
        for axis, value in views.items():
            path = checked_path(project, task, value)
            paths.append(path)
            result["images"].append({"title": label + " · " + axis, "data": png(path)})
    return result, paths


def png(path):
    raw = Path(path).read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("结构图片不是PNG")
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def source_paths(project, task, kind):
    name = project["name"]
    root = checked_path(project, task, task_dir(name, task))
    if kind == "ele.pdos":
        return [pdos.data_path(name, task), pdos.meta_path(name, task)]
    if kind == "ele.work_function":
        return [work_function.data_path(name, task), work_function.meta_path(name, task)]
    if kind == "ele.bader":
        return [bader.acf_path(name, task), bader.meta_path(name, task), bader.frozen_cif_path(name, task),
                task_files_dir(name, task) / "POSCAR"]
    if kind == "ele.charge_diff":
        return [charge_diff.meta_path(name, task), *charge_diff.image_paths(name, task).values()]
    return [root]


def electronic(project, task, kind):
    from report_builder import _pdos_report_data, _work_function_report_data
    paths = source_paths(project, task, kind)
    for path in paths:
        checked_path(project, task, path)
    name = project["name"]
    charts, errors = {}, []
    task = {**task, "task_name": task.get("task_name") or task.get("model_name") or task.get("task_id")}
    payload = {}
    if kind == "ele.pdos":
        summary = _pdos_report_data(name, task, charts, errors)
        if summary:
            payload = {"summary": summary, "view": pdos.load_view(name, task, refresh=True)}
    elif kind == "ele.work_function":
        summary = _work_function_report_data(name, task, charts, errors)
        if summary:
            payload = {"summary": summary}
    elif kind == "ele.bader":
        parsed = bader.load_data(name, task)
        # Never call report_cif(): legacy backfill writes into the task source tree.
        frozen = checked_path(project, task, bader.frozen_cif_path(name, task))
        payload = {"summary": parsed, "cif": frozen.read_text(encoding="utf-8") if frozen.is_file() else None,
                   "cif_source": "analysis_snapshot" if frozen.is_file() else "missing",
                   "note": "逐原子数据沿用Bader解析；没有分析时冻结CIF时不使用当前镜像冒充"}
    elif kind == "ele.charge_diff":
        images = charge_diff.local_images(name, task)
        payload = {"images": [{"title": "差分电荷 · " + axis, "data": png(checked_path(project, task, path))}
                              for axis, path in images.items()]}
        if not images:
            payload = {}
    payload["charts"] = list(charts.values())
    payload["errors"] = errors
    usable = bool(payload.get("view") or payload.get("summary") or payload.get("images"))
    return payload, paths, "available" if usable else "unparsed" if any(Path(p).is_file() for p in paths) else "missing"
