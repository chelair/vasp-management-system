"""任务文件摘要：把本地镜像里的"重文件"压成小片段，供 AI 任务上下文使用。

2026-10-13 新增（只加不改）：
- OUTCAR 动辄 30–57MB，不能塞进上下文 → 只留**尾部 4KB**（错误/收敛信息都在尾部）；
- `result`（vaspkit/后处理摘要，几十 KB）同样只留尾部；
- 落盘位置：`<任务目录>/reports/outcar_tail.txt`、`reports/result_tail.txt`，
  NEB 每个映像另存 `reports/outcar_tail_<映像号>.txt`；
- 生成时机：**归档文件同步完成后**（那时本地已有 OUTCAR/result，不额外走 SSH）。
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import ssh
from task_paths import task_dir, task_files_dir

#: 尾部保留字节数（错误行、收敛判定、timing 都在末尾）
TAIL_BYTES = 4096

#: 远端兜底取尾部的行数（读很少，crashed 的大 OUTCAR 也很快）
REMOTE_TAIL_LINES = 60


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


# --------------------------------------------------------------------------
# OUTCAR 尾部：本地优先，本地没有就远端取一次（异常结束的任务通常没同步过 OUTCAR）


def _remote_tail_script(remote_dir: str, image: Optional[str], lines: int) -> str:
    """远端脚本：定位 OUTCAR → `tail -n N` → base64 回传（顺带回传目录）。"""
    img = json_quote(image) if image else ""
    return "\n".join(
        [
            "set -u",
            f'RD="{remote_dir}"',
            f'IMG={img}',
            'F=""',
            'if [ -n "$IMG" ]; then',
            '  for c in $(ls -d "$RD"/con[0-9]* 2>/dev/null | sort -V -r); do',
            '    [ -s "$c/$IMG/OUTCAR" ] && { F="$c/$IMG/OUTCAR"; break; }',
            "  done",
            '  [ -n "$F" ] || [ -s "$RD/$IMG/OUTCAR" ] && [ -z "$F" ] && F="$RD/$IMG/OUTCAR"',
            "else",
            '  for c in $(ls -d "$RD"/con[0-9]* 2>/dev/null | sort -V -r); do',
            '    [ -s "$c/OUTCAR" ] && { F="$c/OUTCAR"; break; }',
            # NEB：顶层没有 OUTCAR 时，取该 conN 下**最近修改**的映像 OUTCAR
            # （异常结束的往往是它；按名字取第一个会拿到端点 00 的复制品）
            '    CAND=$(find "$c" -maxdepth 2 -name OUTCAR -size +0 -printf "%T@ %p\\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-)',
            '    [ -n "$CAND" ] && { F="$CAND"; break; }',
            "  done",
            '  [ -n "$F" ] || [ -s "$RD/OUTCAR" ] && [ -z "$F" ] && F="$RD/OUTCAR"',
            '  if [ -z "$F" ]; then',
            '    for d in "$RD"/[0-9]*; do',
            '      [ -s "$d/OUTCAR" ] && { F="$d/OUTCAR"; break; }',
            "    done",
            "  fi",
            "fi",
            '[ -n "$F" ] || { echo "@@@NOOUTCAR"; exit 4; }',
            'echo "@@@FILE"',
            'echo "$F"',
            'echo "@@@TAIL"',
            f'tail -n {max(1, lines)} "$F" | base64 | tr -d "\\n"',
            "echo",
            'echo "@@@END"',
        ]
    )


def json_quote(value: Any) -> str:
    """给远端脚本用的最小引号（仅允许字母数字与 _ - .）。"""
    text = str(value or "")
    return '"' + re.sub(r'[^A-Za-z0-9_.-]', "", text) + '"'


def fetch_remote_outcar_tail(
    server: str, remote_dir: str, *, image: Optional[str] = None, lines: int = REMOTE_TAIL_LINES
) -> Dict[str, Any]:
    """远端取 OUTCAR 尾部（异常结束、本地没有镜像时的兜底）。"""
    script = base64.b64encode(_remote_tail_script(remote_dir, image, lines).encode()).decode()
    result = ssh.run_remote(server, f"echo {script} | base64 -d | bash", timeout=120)
    out = str(result.get("stdout") or "")
    if "@@@NOOUTCAR" in out:
        raise FileNotFoundError("远端没找到 OUTCAR")
    if result.get("exit_code") != 0 and "@@@END" not in out:
        raise RuntimeError((result.get("stderr") or out).strip()[:200] or "读取远端 OUTCAR 失败")
    file_path = ""
    if "@@@FILE\n" in out:
        file_path = out.split("@@@FILE\n", 1)[1].split("\n", 1)[0].strip()
    payload = out.split("@@@TAIL\n", 1)[1].split("@@@END", 1)[0].strip() if "@@@TAIL\n" in out else ""
    try:
        text = base64.b64decode(payload).decode("utf-8", "replace") if payload else ""
    except Exception:  # noqa: BLE001 - 解码失败当空
        text = ""
    return {"text": text, "remote_path": file_path, "lines": lines}


def outcar_tail_for_task(
    project: Dict[str, Any],
    task: Dict[str, Any],
    *,
    lines: int = 40,
    image: Optional[str] = None,
) -> Dict[str, Any]:
    """给前端"看 OUTCAR 尾部"用：本地摘要 → 本地镜像 → 远端，三级兜底。

    返回 `{text, source, dir, lines}`；`source` ∈ `reports-tail` / `local-mirror` / `remote`。
    """
    from paths import resolve_remote_path

    project_name = str(project.get("name") or "")
    root = task_dir(project_name, task)
    files_dir = task_files_dir(project_name, task)

    # ① 归档/同步时切好的 4KB 摘要（NEB 指定映像就用映像那份）
    if image:
        tail_file = root / "reports" / f"outcar_tail_{image}.txt"
    else:
        tail_file = root / "reports" / "outcar_tail.txt"
    if tail_file.is_file():
        text = tail_file.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return {
                "text": _last_lines(text, lines),
                "source": "reports-tail",
                "dir": str(tail_file),
                "lines": lines,
            }

    # ② 本地镜像里的 OUTCAR（NEB 在 files/<映像号>/）
    local_outcar = files_dir / (f"{image}/OUTCAR" if image else "OUTCAR")
    if local_outcar.is_file() and local_outcar.stat().st_size > 0:
        text = _tail(local_outcar, 200_000) or ""
        if text.strip():
            return {
                "text": _last_lines(text, lines),
                "source": "local-mirror",
                "dir": str(local_outcar),
                "lines": lines,
            }

    # ③ 远端取一次（异常结束的任务通常从没同步过 OUTCAR）
    remote_dir = resolve_remote_path(str(project.get("server") or ""), str(task.get("remote_dir") or "")).rstrip("/")
    if not remote_dir:
        raise FileNotFoundError("任务缺少远程目录")
    got = fetch_remote_outcar_tail(
        str(project.get("server") or ""), remote_dir, image=image, lines=lines
    )
    return {
        "text": got["text"],
        "source": "remote",
        "dir": got.get("remote_path") or remote_dir,
        "lines": lines,
    }


def _last_lines(text: str, lines: int) -> str:
    parts = text.splitlines()
    if lines > 0 and len(parts) > lines:
        return "\n".join(parts[-lines:]) + "\n"
    return text
