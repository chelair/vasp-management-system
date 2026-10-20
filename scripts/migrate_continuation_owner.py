"""把续算子任务上的活跃作业号迁回主任务（2026-10-21 用户口径）。

历史原因：自动化提交 conN 时把 job_id 登记在续算子任务上；用户要求“续算目录的
作业号登记在主任务下”。本脚本只处理**活跃**（queued/running）的续算子任务：
把 job_id/状态移到父任务，子任务回到 pending 并清空作业号。终态历史不动。

用法：
  .venv/bin/python scripts/migrate_continuation_owner.py            # 只预览
  .venv/bin/python scripts/migrate_continuation_owner.py --apply    # 实际写入（自动备份 projects.json）
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from task_paths import is_continuation_task  # noqa: E402


def migrate(db):
    moves = []
    for project in db.get("projects", []):
        tasks = {str(t.get("task_id")): t for t in project.get("tasks", [])}
        for task in project.get("tasks", []):
            if not is_continuation_task(task):
                continue
            job_id = str(task.get("job_id") or "").strip()
            status = str(task.get("status") or "")
            if not job_id or status not in ("queued", "running"):
                continue
            parent = tasks.get(str(task.get("parent_task_id") or ""))
            if parent is None:
                moves.append((project.get("name"), task.get("model_name"), job_id, "父任务不存在，跳过"))
                continue
            parent_status = str(parent.get("status") or "")
            if parent.get("job_id") and str(parent["job_id"]) != job_id and parent_status in ("queued", "running"):
                moves.append((project.get("name"), task.get("model_name"), job_id, "父任务已有其它活跃作业，跳过"))
                continue
            moves.append((project.get("name"), task.get("model_name"), job_id,
                          f"{parent.get('model_name')}：{parent_status} → {status}（清空 conN 作业号）"))
            parent["job_id"] = job_id
            parent["status"] = status
            parent["last_check_time"] = task.get("last_check_time") or parent.get("last_check_time")
            task["job_id"] = None
            task["status"] = "pending"
    return moves


def main():
    parser = argparse.ArgumentParser(description="把续算子任务的活跃作业号迁回主任务")
    parser.add_argument("--apply", action="store_true", help="实际写入项目库（默认只预览）")
    args = parser.parse_args()

    from storage import load_db, save_db

    db = load_db()
    moves = migrate(db)
    if not moves:
        print("没有需要迁移的活跃续算作业")
        return 0
    for project, name, job_id, detail in moves:
        print(f"[{project}] {name} · job {job_id} → {detail}")
    if not args.apply:
        print(f"\n共 {len(moves)} 条；确认后加 --apply 写入")
        return 0
    if any("跳过" in detail for _, _, _, detail in moves):
        print("\n存在跳过项，未写入；请先人工处理冲突")
        return 1
    save_db(db)
    print(f"\n已写入 {len(moves)} 条，projects.json 已自动备份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
