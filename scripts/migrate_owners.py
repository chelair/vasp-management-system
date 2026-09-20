"""把现有项目一次性归给指定用户（账号体系第 3 步：归属字段与迁移）。

用法：

    python scripts/migrate_owners.py --owner zouyuxi                 # dry-run（默认，只打印）
    python scripts/migrate_owners.py --owner zouyuxi --apply         # 真写（先备份 projects.json.bak.<时间戳>）
    python scripts/migrate_owners.py --owner zouyuxi --apply --data-dir <数据根目录>

行为：

- **幂等**：已经有 `owner` 的项目一律跳过、不覆盖；
- 缺失 `created_at` 的项目补一个（已有的不动）；
- `--apply` 前把 `projects.json` 备份成 `projects.json.bak.YYYYmmdd_HHMMSS`（不覆盖旧备份），
  再走 storage 的原子写 + 文件锁落盘；
- 归属用户名统一小写归一；若 `users.json` 里没有该用户会直接报错（避免写错名字导致将来"谁都看不到"），
  确认要写可加 `--force`。

本步只加字段，**不做任何可见性过滤**（过滤在第 4 步）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

parser = argparse.ArgumentParser(description="把现有项目归给指定用户（幂等、可干跑）")
parser.add_argument("--owner", required=True, help="归属用户名（统一小写归一）")
parser.add_argument("--apply", action="store_true", help="真正写入（默认只 dry-run）")
parser.add_argument("--data-dir", help="数据根目录（默认项目下 data/，用于测试隔离）")
parser.add_argument("--force", action="store_true", help="即使 users.json 里没有该用户也写入")
args = parser.parse_args()

if args.data_dir:
    os.environ["VASP_WEB_DATA_DIR"] = os.path.abspath(args.data_dir)

sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402
from config import DATA_DIR  # noqa: E402
from dates import now_iso  # noqa: E402
from storage import load_db, save_db  # noqa: E402

PROJECTS_FILE = DATA_DIR / "projects.json"


def _check_owner_exists(owner: str) -> None:
    """users.json 存在时校验归属用户是否已建号（避免拼错名字写成"孤儿项目"）。"""
    if args.force:
        return
    users = auth.list_users()
    if not users:
        print("提示：users.json 里还没有任何用户（先跑一次服务或用 set_password.py 建号），本次先不校验。")
        return
    if auth.find_user(owner) is None:
        print(
            f"错误：users.json 里没有用户 '{owner}'。"
            f"\n      先建号：python scripts/set_password.py {owner}"
            f"\n      或确认要写：--force"
        )
        sys.exit(1)


def main() -> int:
    owner = auth.normalize_username(args.owner)
    if not owner:
        print("错误：--owner 不能为空")
        return 1
    if not PROJECTS_FILE.is_file():
        print(f"错误：找不到 {PROJECTS_FILE}（可用 --data-dir 指定数据目录）")
        return 1

    _check_owner_exists(owner)
    db = load_db()
    projects = db.get("projects", [])

    todo = [p for p in projects if not str(p.get("owner") or "").strip()]
    skipped = [p for p in projects if str(p.get("owner") or "").strip()]

    print(f"数据目录：{DATA_DIR}")
    print(f"项目总数：{len(projects)} · 待归属：{len(todo)} · 已有 owner（跳过）：{len(skipped)}")
    if skipped:
        detail = "、".join(f"{p.get('name')}({p.get('owner')})" for p in skipped[:6])
        print(f"  跳过：{detail}{' …' if len(skipped) > 6 else ''}")

    if not todo:
        print("无需修改：所有项目都已有 owner（幂等，未写文件、未备份）。")
        return 0

    ids = ", ".join(str(p.get("project_id") or p.get("name")) for p in todo)
    names = "、".join(str(p.get("name")) for p in todo)

    if not args.apply:
        print(f"[DRY-RUN] {len(todo)} 个项目将被设为 owner={owner}：{ids}")
        print(f"[DRY-RUN] 项目名：{names}")
        print("[DRY-RUN] 未写文件；确认无误后加 --apply 执行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = PROJECTS_FILE.with_name(f"{PROJECTS_FILE.name}.bak.{stamp}")
    if backup.exists():  # 理论上同一秒重跑才会撞上，仍然不覆盖
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = PROJECTS_FILE.with_name(f"{PROJECTS_FILE.name}.bak.{stamp}")
    shutil.copy2(PROJECTS_FILE, backup)

    for project in todo:
        project["owner"] = owner
        if not str(project.get("created_at") or "").strip():
            project["created_at"] = now_iso()

    save_db(db)  # 原有原子写 + 文件锁（内部还会在 data/backups/ 留一份）
    print(f"已更新 {len(todo)} 个项目，owner={owner}，备份在 {backup.name}")
    print(f"  项目：{names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
