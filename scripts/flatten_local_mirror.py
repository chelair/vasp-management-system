#!/usr/bin/env python
"""本地镜像扁平化迁移（v0.8.7）。

做两件事：

1. **`<任务>/inputs/` → `<任务>/files/`**：旧版本把远端快照写在独立的 `inputs/`，
   v0.8.7 起本地每个任务只有一份文件镜像，所以把 `inputs/` 里的文件合并进 `files/`
   后删除 `inputs/`；有未生效草稿（`input_state.changes` 里 `applied_at` 为空）的文件
   不合并，原样备份到 `data/backups/`。
2. **删除空的 `conN` 骨架目录**：旧版本创建续算子任务时会在本地建
   `<任务目录>/conN/{files,images,reports,continuation}` 四个空目录，v0.8.7 起不再创建；
   这里把**确认不含任何文件**的 conN 目录删掉，非空的保留并打印交人工判断。

默认 dry-run 只打印计划，`--apply` 才真正改动；被覆盖/被跳过的文件先备份到
`data/backups/local_mirror_<时间戳>/`。

用法：
    python scripts/flatten_local_mirror.py                 # 预览
    python scripts/flatten_local_mirror.py --apply          # 执行
    python scripts/flatten_local_mirror.py --data-dir <目录> --apply
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
CONTINUATION_RE = re.compile(r"/con\d+$")


def normalize_dir(rel: str) -> str:
    """续算子任务（.../conN）归并到任务族根目录（与 backend/task_paths.py 同规则）。"""
    return CONTINUATION_RE.sub("", str(rel or "").strip("/"))


def protected_files(db: Dict) -> Dict[str, Set[str]]:
    """{归一化任务相对目录: 有未生效草稿的文件名集合}。"""
    result: Dict[str, Set[str]] = {}
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            rel = str(task.get("dir_path") or "").strip("/")
            if not rel:
                continue
            changes = (task.get("input_state") or {}).get("changes") or []
            pending = {str(c.get("file")) for c in changes if not c.get("applied_at")}
            if pending:
                result.setdefault(normalize_dir(rel), set()).update(pending)
    return result


def _backup(path: Path, backup_root: Path, projects_dir: Path, label: str) -> None:
    target = backup_root / label / path.relative_to(projects_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def merge_inputs_dirs(
    projects_dir: Path,
    backup_root: Path,
    protected: Dict[str, Set[str]],
    apply: bool,
) -> Tuple[List[str], List[str]]:
    """`<任务>/inputs/` → 同级 `files/`；返回 (合并日志, 因草稿跳过日志)。"""
    merged: List[str] = []
    protected_notes: List[str] = []
    for inputs_dir in sorted(p for p in projects_dir.rglob("inputs") if p.is_dir()):
        task_rel = inputs_dir.parent.relative_to(projects_dir).as_posix()
        keep = protected.get(normalize_dir(task_rel), set())
        target_dir = inputs_dir.parent / "files"
        copied: List[str] = []
        kept: List[str] = []
        for src in sorted(inputs_dir.rglob("*")):
            if not src.is_file():
                continue
            rel_name = src.relative_to(inputs_dir).as_posix()
            if src.name in keep:
                kept.append(rel_name)
                if apply:
                    _backup(src, backup_root, projects_dir, "protected")
                continue
            copied.append(rel_name)
            if apply:
                dst = target_dir / rel_name
                if dst.is_file():
                    _backup(dst, backup_root, projects_dir, "replaced")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        if apply:
            shutil.rmtree(inputs_dir)
        merged.append(
            f"{task_rel}: 合并 {len(copied)} 个文件"
            + (f"（{', '.join(copied)}）" if copied else "")
        )
        if kept:
            protected_notes.append(
                f"{task_rel}: 未合并（有未生效草稿，已备份）{', '.join(kept)}"
            )
    return merged, protected_notes


def find_con_skeletons(projects_dir: Path) -> Tuple[List[Path], List[Path]]:
    """返回 (空 conN 目录, 仍有文件的 conN 目录)。"""
    empty: List[Path] = []
    nonempty: List[Path] = []
    for path in sorted(projects_dir.rglob("con[0-9]*")):
        if not path.is_dir():
            continue
        has_file = any(child.is_file() for child in path.rglob("*"))
        (nonempty if has_file else empty).append(path)
    return empty, nonempty


def main() -> int:
    parser = argparse.ArgumentParser(description="本地镜像扁平化迁移（inputs→files、删空 conN）")
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="数据根目录")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只预览）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    projects_dir = data_dir / "projects"
    db_path = data_dir / "projects.json"
    if not projects_dir.is_dir() or not db_path.is_file():
        print(f"✗ 数据目录不完整：{data_dir}", file=sys.stderr)
        return 2

    db = json.loads(db_path.read_text(encoding="utf-8"))
    protected = protected_files(db)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_root = data_dir / "backups" / f"local_mirror_{stamp}"

    merged, protected_notes = merge_inputs_dirs(
        projects_dir, backup_root, protected, args.apply
    )
    empty_con, nonempty_con = find_con_skeletons(projects_dir)

    print(f"== 本地镜像扁平化 [{'APPLY' if args.apply else 'DRY-RUN'}] · {data_dir}")
    print(f"\n[1] inputs/ → files/：{len(merged)} 个任务目录")
    for line in merged[:200]:
        print(f"    {line}")
    if len(merged) > 200:
        print(f"    …另有 {len(merged) - 200} 条")
    if protected_notes:
        print(f"\n[1b] 因未生效草稿未合并：{len(protected_notes)} 条")
        for line in protected_notes:
            print(f"    {line}")

    print(
        f"\n[2] 空的 conN 骨架目录：{len(empty_con)} 个"
        f"（{'已删除' if args.apply else '待删除'}）"
    )
    for path in empty_con[:20]:
        print(f"    {path.relative_to(projects_dir)}")
    if len(empty_con) > 20:
        print(f"    …另有 {len(empty_con) - 20} 个")

    print(f"\n[3] 仍有文件的 conN 目录：{len(nonempty_con)} 个（保留）")
    for path in nonempty_con:
        print(f"    {path.relative_to(projects_dir)}")

    if args.apply:
        for path in empty_con:
            shutil.rmtree(path)
        print(f"\n备份目录：{backup_root}")
        print("✓ 已完成")
    else:
        print("\n（预览模式：加 --apply 才会真正改动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
