"""任务文件摘要：把本地镜像里的"重文件"压成小片段，供 AI 任务上下文使用。

2026-10-13 新增（只加不改）：
- OUTCAR 动辄 30–57MB，不能塞进上下文 → 只留**尾部 4KB**（错误/收敛信息都在尾部）；
- `result`（vaspkit/后处理摘要，几十 KB）同样只留尾部；
- 落盘位置：`<任务目录>/reports/outcar_tail.txt`、`reports/result_tail.txt`，
  NEB 每个映像另存 `reports/outcar_tail_<映像号>.txt`；
- 生成时机：**归档文件同步完成后**（那时本地已有 OUTCAR/result，不额外走 SSH）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from task_paths import task_dir, task_files_dir

#: 尾部保留字节数（错误行、收敛判定、timing 都在末尾）
TAIL_BYTES = 4096


def _tail(path: Path, size: int = TAIL_BYTES) -> Optional[str]:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            length = fh.tell()
            fh.seek(max(0, length - size))
            text = fh.read().decode("utf-8", "replace")
        return text
    except OSError:
        return None


def _write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def refresh_task_file_summaries(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """从本地镜像生成摘要片段（**不发 SSH**）；返回写了哪些文件。

    结构目录：`<任务目录>/files/`（普通任务）；NEB 另含 `files/<映像号>/`（或 `files/neb_images/<映像号>/`）。
    """
    files_dir = task_files_dir(str(project.get("name") or ""), task)
    reports = task_dir(str(project.get("name") or ""), task) / "reports"
    written: List[str] = []

    outcar = _tail(files_dir / "OUTCAR")
    if outcar:
        _write(reports / "outcar_tail.txt", outcar)
        written.append("outcar_tail.txt")
    result = _tail(files_dir / "result")
    if result:
        _write(reports / "result_tail.txt", result)
        written.append("result_tail.txt")

    # NEB：每个映像目录各留一份
    for label in ("[0-9]*", "neb_images/[0-9]*"):
        for sub in sorted(files_dir.glob(label)):
            if not sub.is_dir():
                continue
            text = _tail(sub / "OUTCAR")
            if text:
                name = f"outcar_tail_{sub.name}.txt"
                _write(reports / name, text)
                written.append(name)
    return {"task_id": task.get("task_id"), "written": written}


def read_task_file_summaries(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """读回摘要（供任务上下文用）：`{outcar_tail, result_tail, image_tails:{0x: text}}`。"""
    root = task_dir(project_name, task)
    reports = root / "reports"
    image_tails: Dict[str, str] = {}
    for path in sorted(reports.glob("outcar_tail_*.txt")):
        label = path.stem.replace("outcar_tail_", "")
        image_tails[label] = path.read_text(encoding="utf-8", errors="replace") or ""
    files_dir = task_files_dir(project_name, task)
    present = sorted(
        p.name for p in files_dir.glob("*") if p.is_file() and not p.name.endswith(".cif")
    ) if files_dir.is_dir() else []
    return {
        "present": present,
        "outcar_tail": (reports / "outcar_tail.txt").read_text(encoding="utf-8", errors="replace")
        if (reports / "outcar_tail.txt").is_file()
        else None,
        "result_tail": (reports / "result_tail.txt").read_text(encoding="utf-8", errors="replace")
        if (reports / "result_tail.txt").is_file()
        else None,
        "image_tails": image_tails,
    }
