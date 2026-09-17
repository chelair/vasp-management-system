"""迁移辅助：把 data/ 下 JSON 里的**绝对路径**归一化成相对路径。

背景：任务元数据（projects.json）里的路径一直是相对的（v0.5.0 起），
但有两处历史遗留会存绝对路径：

1. `data/aux_molecules.json` 的 `dir / opt_dir / frac_dir`；
2. `data/reports/index.json` 的 `directory`。

换机器（尤其 Windows → Linux）后这些绝对路径会失效。运行时会做兜底解析，
但**扫描/归一化一次**可以让数据文件本身保持可移植（推荐迁移前在旧机跑，
或迁移后在目标机跑一次 `--apply`）。

用法：
    python scripts/migrate_paths.py                # 只扫描（dry-run）
    python scripts/migrate_paths.py --apply        # 就地改写（先备份到 data/backups/migration_<时间>/）
    python scripts/migrate_paths.py --data-dir <数据根目录>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _backup(data_dir: Path, paths) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = data_dir / "backups" / f"migration_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if p.is_file():
            shutil.copyfile(p, dest / p.name)
    return dest


def normalize_aux(data_dir: Path, apply: bool) -> list[str]:
    """aux_molecules.json：dir/opt_dir/frac_dir 改成相对数据根。"""
    path = data_dir / "aux_molecules.json"
    if not path.is_file():
        return []
    data = load_json(path)
    changed: list[str] = []
    for molecule in data.get("molecules", []):
        label = str(molecule.get("label") or "")
        if not label:
            continue
        targets = {
            "dir": f"aux_molecules/{label}",
            "opt_dir": f"aux_molecules/{label}/opt",
            "frac_dir": f"aux_molecules/{label}/frac",
        }
        for key, value in targets.items():
            current = str(molecule.get(key) or "")
            if current != value and (not current or DRIVE_RE.match(current) or current.startswith("/") or current != value):
                changed.append(f"aux_molecules.json[{label}].{key}: {current} -> {value}")
                molecule[key] = value
    if apply and changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def normalize_reports_index(data_dir: Path, apply: bool) -> list[str]:
    """reports/index.json：directory 改成相对 data/reports。"""
    path = data_dir / "reports" / "index.json"
    if not path.is_file():
        return []
    data = load_json(path)
    changed: list[str] = []
    for item in data if isinstance(data, list) else []:
        project = str(item.get("project_name") or "")
        report_id = str(item.get("report_id") or "")
        if not project or not report_id:
            continue
        value = f"{project}/{report_id}"
        current = str(item.get("directory") or "")
        if current != value:
            changed.append(f"reports/index.json[{report_id}].directory: {current} -> {value}")
            item["directory"] = value
    if apply and changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def scan_absolute_paths(data_dir: Path) -> list[str]:
    """扫描其它数据文件里的绝对路径（只报告，不自动改）。"""

    def walk(node, prefix: str, hits: list[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}", hits)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]", hits)
        elif isinstance(node, str):
            if DRIVE_RE.match(node) or (node.startswith("/") and "/" in node[1:]):
                # 远端路径（/data/gpfs03/...）是正常的，排除掉
                if not node.startswith(("/data", "/home", "/opt", "/work", "/scratch", "/gpfs")):
                    hits.append(f"{prefix}: {node[:120]}")

    report: list[str] = []
    for name in ("projects.json", "aux_molecules.json"):
        path = data_dir / name
        if path.is_file():
            hits: list[str] = []
            walk(load_json(path), name, hits)
            report.extend(hits)
    runs = data_dir / "checks" / "runs.json"
    if runs.is_file():
        hits = []
        walk(load_json(runs), "checks/runs.json", hits)
        report.extend(hits)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="把 data/ 下 JSON 的绝对路径归一化为相对路径")
    parser.add_argument("--apply", action="store_true", help="就地改写（默认只扫描）")
    parser.add_argument("--data-dir", default=None, help="数据根目录（默认仓库下 data/）")
    args = parser.parse_args()

    root = Path(args.data_dir).expanduser().resolve() if args.data_dir else (
        Path(__file__).resolve().parent.parent / "data"
    )
    if not root.is_dir():
        print(f"数据目录不存在：{root}", file=sys.stderr)
        return 2

    print(f"数据根目录：{root}")
    changed = normalize_aux(root, args.apply) + normalize_reports_index(root, args.apply)
    if changed:
        print(f"\n需要归一化的路径 {len(changed)} 处：")
        for line in changed:
            print("  ", line)
        if args.apply:
            backup = _backup(root, [root / "aux_molecules.json", root / "reports" / "index.json"])
            print(f"\n已改写，原文件备份在：{backup}")
        else:
            print("\n（dry-run：加 --apply 才会写入）")
    else:
        print("这两处已经是相对路径，无需处理。")

    remaining = scan_absolute_paths(root)
    if remaining:
        print(f"\n其它文件里仍有 {len(remaining)} 处绝对路径（需人工确认，未自动修改）：")
        for line in remaining[:20]:
            print("  ", line)
    else:
        print("\n其它数据文件未发现本机绝对路径。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
