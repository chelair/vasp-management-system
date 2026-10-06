#!/usr/bin/env python3
"""给项目的任务批量出结构三视图（VESTA）：巡检/归档之后的补课工具。

用法（仓库根目录）：
    .venv/bin/python scripts/render_structure_images.py Ag_20260830            # 该项目全部符合条件的任务
    .venv/bin/python scripts/render_structure_images.py Ag_20260830 --limit 3  # 只画前 3 个
    .venv/bin/python scripts/render_structure_images.py --all                  # 所有项目

筛选口径（与巡检自动调度一致）：opt/ele 已收敛(completed)或已归档、NEB 已完成/已归档；
自由能频率矫正（frac）不画。图落在 `<任务目录>/images/`（opt = poscar/contcar 的 a/b/c，
NEB = images/<映像号>/a|b|c.png），同名覆盖，已是最新则秒过。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import structure_images  # noqa: E402
from storage import load_db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="批量渲染结构三视图（VESTA）")
    ap.add_argument("project", nargs="?", help="项目名；省略时配合 --all 使用")
    ap.add_argument("--all", action="store_true", help="所有项目")
    ap.add_argument("--limit", type=int, default=0, help="每个项目最多画几个任务（0=不限）")
    args = ap.parse_args()

    if args.all:
        names = [p.get("name") for p in load_db().get("projects", [])]
    elif args.project:
        names = [args.project]
    else:
        raise SystemExit("用法：render_structure_images.py <项目名> [--limit N] | --all")

    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
    db = load_db()
    total = 0
    for name in names:
        project = next((p for p in db.get("projects", []) if p.get("name") == name), None)
        if project is None:
            print(f"[skip] 项目不存在：{name}")
            continue
        tasks = [t for t in project.get("tasks", []) if structure_images.should_render(t)]
        if args.limit:
            tasks = tasks[: args.limit]
        print(f"[{name}] 待渲染 {len(tasks)} 个任务")
        for task in tasks:
            t0 = time.time()
            try:
                result = structure_images.render_now(name, task)
                images = result.get("images") or {}
                print(
                    f"   {task.get('model_name'):24s} {task.get('task_type'):4s} "
                    f"{task.get('status'):9s} {time.time() - t0:5.1f}s 图组={len(images)}"
                    + (f" ⚠ {'; '.join(result.get('warnings') or [])}" if result.get("warnings") else "")
                )
            except Exception as e:  # noqa: BLE001
                print(f"   {task.get('model_name')} 失败：{e}")
            total += 1
    print(f"完成，共处理 {total} 个任务")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
