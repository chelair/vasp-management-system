"""一次性修复：自由能主任务已归档、但频率矫正（frac）子任务未归档。

背景：v0.6.4 之前"关闭（归档）"只作用于单个任务，因此存在
"主任务已归档、同结构的 frac 还是 completed/unconverged" 的不一致状态
（这类项目因为 frac 未归档而无法关闭）。

用法（默认 dry-run，只打印不改动）：

    python scripts/repair_frac_archive.py            # 预览
    python scripts/repair_frac_archive.py --apply    # 实际写入（自动备份）

数据目录默认取 `data/`，可用环境变量 VASP_WEB_DATA_DIR 指向其他目录。
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))

from dates import now_iso  # noqa: E402
from storage import db_transaction, load_db  # noqa: E402
from task_paths import free_energy_frac_task  # noqa: E402


def collect(db) -> list:
    """返回 [(project_name, opt_task, frac_task)]：主任务已归档但 frac 未归档。"""
    pending = []
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if str(task.get("status")) != "archived":
                continue
            frac = free_energy_frac_task(project, task)
            if frac is None or str(frac.get("status")) == "archived":
                continue
            pending.append((str(project.get("name") or ""), task, frac))
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入（默认仅预览）")
    args = parser.parse_args()

    db = load_db()
    items = collect(db)
    if not items:
        print("没有需要修复的任务：主任务已归档的自由能结构，其频率矫正均已归档。")
        return 0

    print(f"发现 {len(items)} 处不一致（主任务 archived / 频率矫正未归档）：")
    for project_name, opt, frac in items:
        print(
            f"  [{project_name}] {opt.get('model_name')} (archived)"
            f" -> {frac.get('model_name')} ({frac.get('status')})"
        )

    if not args.apply:
        print("\n预览模式：未写入。确认后加 --apply 执行（写入前会自动备份 projects.json）。")
        return 0

    # 在同一事务里逐条归档 frac（幂等：写入前重新核验状态）
    with db_transaction() as fresh:
        fixed = 0
        for project in fresh.get("projects", []):
            for task in project.get("tasks", []):
                if str(task.get("status")) != "archived":
                    continue
                frac = free_energy_frac_task(project, task)
                if frac is None or str(frac.get("status")) == "archived":
                    continue
                previous = str(frac.get("status") or "")
                frac["status"] = "archived"
                frac["archived_at"] = now_iso()
                # 先取原状态再改，否则会把 "archived" 记成归档前状态（重开时恢复不回去）
                frac["archived_from"] = previous or "completed"
                fixed += 1
        print(f"\n已归档 {fixed} 个频率矫正任务（归档前状态记录在 archived_from）。")

    if os.environ.get("VASP_WEB_DATA_DIR"):
        print(f"数据目录：{os.environ['VASP_WEB_DATA_DIR']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
