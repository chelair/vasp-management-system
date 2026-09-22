"""本地 NEB 分类目录大小写归一：`<项目>/NEB` → `<项目>/neb`（只动本地，不碰远端）。

背景：Windows 大小写不敏感时期，Ag_20260830 的 NEB 分支落成了大写目录 `NEB/`，后来在
Linux 上又补了一条软链接 `neb -> NEB` 兜着。代码（`task_paths.py`）生成的分类目录是**小写
`neb`**，于是本地出现"同一个分支两个名字"，`projects.json` 里 67 条任务的 `dir_path` 写的是大写。
本脚本把本地统一成小写：

1. 删掉指向 `NEB` 的软链接 `neb`（若有）；
2. 把真目录 `NEB` 改名为 `neb`（同目录 rename，瞬时完成，不动子目录内容）；
3. 把 `projects.json` 里 `dir_path` 的 `NEB` 段改成 `neb`（只改路径字段，`notes` 这种散文不动，
   `remote_dir` 等**远端**路径一律不动）。

**明确不做**：不连 SSH、不改任何远端目录/文件；不动同项目下的其它分类目录（free_energy / opt …）。

用法：
    .venv/bin/python scripts/migrate_neb_case.py                 # dry-run（默认）
    .venv/bin/python scripts/migrate_neb_case.py --apply         # 真改（写库前自动备份）
    .venv/bin/python scripts/migrate_neb_case.py --project Ag_20260830
    .venv/bin/python scripts/migrate_neb_case.py --data-dir /tmp/x --apply

> 用 `--data-dir` 做隔离测试时，记得把该目录 `config/path_mapping.json` 的 `local_root`
> 写成**绝对路径**，否则相对路径会按仓库根解析（见 process.md §11.2）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(SERVER_DIR))

parser = argparse.ArgumentParser(description="本地 NEB 目录大小写归一（NEB → neb）")
parser.add_argument("--data-dir", default=None, help="数据根目录（默认项目下 data/）")
parser.add_argument("--project", default=None, help="只处理指定项目（默认全部）")
parser.add_argument("--apply", action="store_true", help="真正执行（默认只预览）")
args = parser.parse_args()

if args.data_dir:
    os.environ["VASP_WEB_DATA_DIR"] = os.path.abspath(args.data_dir)

from paths import local_root, resolve_local_path  # noqa: E402
from storage import load_db, save_db  # noqa: E402

CATEGORY = "NEB"
TARGET = "neb"


def main() -> int:
    root = local_root()
    print(f"本地项目根目录：{root}")
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return 1

    renames = []
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if args.project and project_dir.name != args.project:
            continue
        upper = project_dir / CATEGORY
        if not upper.is_dir():
            continue
        lower = project_dir / TARGET
        symlink = lower if lower.is_symlink() else None
        blocked = ""
        if lower.exists() and symlink is None:
            blocked = f"`{TARGET}` 已是真实目录，需人工确认（不自动合并）"
        renames.append({"project": project_dir.name, "upper": upper, "lower": lower, "symlink": symlink, "blocked": blocked})

    db = load_db()
    rewrites = []
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            old = str(task.get("dir_path") or "")
            if CATEGORY not in old.split("/"):
                continue
            new = "/".join(TARGET if seg == CATEGORY else seg for seg in old.split("/"))
            rewrites.append({"project": project.get("name"), "task_id": task.get("task_id"), "old": old, "new": new})

    print()
    print(f"[目录改名] {len(renames)} 个：")
    for item in renames:
        print(f"  - {item['project']}：{item['upper'].name} → {item['lower'].name}"
              + (f"（先删软链接 {item['lower'].name} -> {os.readlink(item['symlink'])}）" if item["symlink"] else "")
              + (f"  ⚠️ {item['blocked']}" if item["blocked"] else ""))
    if not renames:
        print("  （没有需要改名的 NEB 目录）")

    print()
    print(f"[projects.json 路径] {len(rewrites)} 条 dir_path 需要把 `{CATEGORY}` 段改成 `{TARGET}`：")
    for item in rewrites[:5]:
        print(f"  - {item['task_id']}：{item['old']} → {item['new']}")
    if len(rewrites) > 5:
        print(f"  … 其余 {len(rewrites) - 5} 条同理")

    print()
    print("远端：**不涉及**（本脚本不连 SSH、不改任何远端目录）。")

    if not args.apply:
        print()
        print("这是预览。确认无误后加 --apply 执行（写库前会自动备份 projects.json）。")
        return 0

    # ---------------- 执行 ----------------
    changed_dirs = 0
    for item in renames:
        if item["blocked"]:
            print(f"[跳过] {item['project']}：{item['blocked']}")
            continue
        if item["symlink"] is not None:
            item["symlink"].unlink()
            print(f"[删除软链接] {item['symlink']}")
        if item["lower"].exists():
            print(f"[跳过] {item['project']}：{item['lower']} 已存在")
            continue
        item["upper"].rename(item["lower"])
        changed_dirs += 1
        print(f"[改名] {item['upper']} → {item['lower']}")

    if rewrites:
        for item in rewrites:
            for project in db.get("projects", []):
                for task in project.get("tasks", []):
                    if str(task.get("task_id")) == str(item["task_id"]):
                        task["dir_path"] = item["new"]
        save_db(db)
        print(f"[写库] 已更新 {len(rewrites)} 条 dir_path（save_db 自动备份到 data/backups/）")

    # ---------------- 复核 ----------------
    print()
    print("复核：")
    ok, logical, missing = [], [], []
    for item in rewrites:
        if resolve_local_path(item["new"]).is_dir():
            ok.append(item)
        elif re.search(r"/con\d+$", item["new"]):
            # 续算子任务是"逻辑路径"：只登记 dir_path，本地不建 conN 目录（见 core_continuation）
            logical.append(item)
        else:
            missing.append(item)
    print(
        f"  - 目录改名 {changed_dirs} 个；dir_path 校验：{len(ok)} 个指向存在的目录、"
        f"{len(logical)} 个是续算逻辑路径（本地不建 conN 目录，正常）、{len(missing)} 个异常"
    )
    for item in missing[:10]:
        print(f"    ⚠️ 目录不存在：{item['new']}")
    # 只看"项目/分类"这一层，别把 400M+ 的 free_energy/opt 全扫一遍
    left = [
        project_dir / CATEGORY
        for project_dir in sorted(p for p in root.iterdir() if p.is_dir())
        if (project_dir / CATEGORY).is_dir()
    ]
    print(f"  - 仍叫 `{CATEGORY}` 的目录：{len(left)} 个" + (f"（{', '.join(str(p) for p in left[:5])}）" if left else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
