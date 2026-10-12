#!/usr/bin/env python3
"""把一次人工处理的错误记进案例库（`data/knowledge/error_cases.jsonl`）。

用法（仓库根目录，纯标准库、不依赖 venv）：
    python3 scripts/log_error_case.py --project FS_Kaolin --task task_1789455573013_1 \
        --error E_ZBRENT --keywords "ZBRENT: fatal error" \
        --summary "POTIM 0.5→0.2 + IBRION=1 重跑" --changes "IBRION=2->1,POTIM=0.5->0.2" \
        --outcome resolved --note "续算后第 12 离子步达标"

省略 --outcar 时自动取 `<任务目录>/reports/outcar_tail.txt` 末尾若干行作为证据。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "knowledge" / "error_cases.jsonl"
LOCAL_TZ = timezone(timedelta(hours=8))


def _tail_from_task(task_id: str, lines: int = 20) -> str:
    """按 task_id 反查任务目录，取 reports/outcar_tail.txt 末尾若干行。"""
    try:
        db = json.loads((ROOT / "data" / "projects.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    for project in db.get("projects", []):
        for task in project.get("tasks", []) or []:
            if str(task.get("task_id")) != str(task_id):
                continue
            task_dir = ROOT / "data" / "projects" / str(task.get("dir_path") or "")
            tail = task_dir / "reports" / "outcar_tail.txt"
            if tail.is_file():
                text = tail.read_text(encoding="utf-8", errors="replace")
                return "\n".join(text.splitlines()[-lines:])
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="记录一条 VASP 错误处理案例")
    ap.add_argument("--project", default="")
    ap.add_argument("--task", default="", help="task_id（用它自动找 OUTCAR 尾部）")
    ap.add_argument("--task-name", default="")
    ap.add_argument("--task-type", default="")
    ap.add_argument("--error", required=True, help="错误类型/编号，如 E_ZBRENT 或自由文本")
    ap.add_argument("--keywords", default="", help="逗号分隔的关键词（能 grep 到的原文）")
    ap.add_argument("--outcar", default="", help="OUTCAR 片段（省略时自动取任务 reports 尾部）")
    ap.add_argument("--summary", required=True, help="处理方式一句话")
    ap.add_argument("--changed", default="", help="改了哪些文件（逗号分隔）")
    ap.add_argument("--changes", default="", help="改了哪些参数，如 NELM=60->120,POTIM=0.5->0.2")
    ap.add_argument("--outcome", default="unknown", choices=["resolved", "failed", "unknown"])
    ap.add_argument("--note", default="", help="结果备注")
    ap.add_argument("--logged-by", default="")
    args = ap.parse_args()

    changes: dict = {}
    for item in (args.changes or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, _, value = item.partition("=")
        if "->" in value:
            src, _, dst = value.partition("->")
            changes[key.strip()] = f"{src.strip()}->{dst.strip()}"
        else:
            changes[key.strip()] = value.strip()

    excerpt = args.outcar or _tail_from_task(args.task) if args.task else args.outcar
    case = {
        "case_id": f"case_{datetime.now(LOCAL_TZ).strftime('%Y%m%d%H%M%S')}",
        "at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "project": args.project,
        "task_id": args.task,
        "task_name": args.task_name,
        "task_type": args.task_type,
        "error_type": args.error,
        "features": {
            "keywords": [k.strip() for k in (args.keywords or "").split(",") if k.strip()],
            "outcar_excerpt": excerpt,
        },
        "handling": {
            "summary": args.summary,
            "changed_files": [f.strip() for f in (args.changed or "").split(",") if f.strip()],
            "changes": changes,
        },
        "outcome": args.outcome,
        "result_note": args.note,
        "logged_by": args.logged_by or "-",
        "source": "scripts/log_error_case.py",
    }
    CASES.parent.mkdir(parents=True, exist_ok=True)
    with open(CASES, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"已记录：{case['case_id']}（{args.error}，{args.outcome}）→ {CASES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
