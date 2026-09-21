"""CIF → POSCAR 命令行工具（零依赖，逻辑复用 backend/cif_reader.py）。

用法：
    python scripts/cif2poscar.py struct.cif              # 打印 POSCAR 到终端
    python scripts/cif2poscar.py struct.cif -o POSCAR    # 写到文件
    python scripts/cif2poscar.py struct.cif --info       # 只打印摘要（元素/原子数/晶胞/提示）

页面里的「导入 / 复制 POSCAR」选 .cif 走的是同一个转换函数（`POST /api/tools/cif-to-poscar`），
命令行这份是给"直接准备 POSCAR 文件"用的。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(SERVER_DIR))

from cif_reader import CifError, cif_to_poscar  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="CIF → POSCAR 转换")
    parser.add_argument("cif", help="输入 CIF 文件")
    parser.add_argument("-o", "--out", default=None, help="输出 POSCAR 路径（默认打印到终端）")
    parser.add_argument("--comment", default=None, help="POSCAR 第一行注释（默认取化学式/数据块名）")
    parser.add_argument("--info", action="store_true", help="只打印摘要，不输出 POSCAR")
    args = parser.parse_args()

    source = Path(args.cif)
    if not source.is_file():
        print(f"找不到文件：{source}")
        return 1
    try:
        poscar, info = cif_to_poscar(source.read_text(encoding="utf-8", errors="replace"), args.comment)
    except CifError as e:
        print(f"转换失败：{e}")
        return 1

    if args.info:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if args.out:
        Path(args.out).write_text(poscar, encoding="utf-8")
        print(
            f"已写出 {args.out}：{info['atoms']} 个原子（{''.join(f'{el}{n}' for el, n in zip(info['elements'], info['counts']))}）"
        )
        for warning in info["warnings"]:
            print(f"  注意：{warning}")
    else:
        print(poscar, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
