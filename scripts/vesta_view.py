#!/usr/bin/env python3
"""按 a / b / c 视图快速查看结构（VESTA），用于核对与调整方向。

用法：
  # ① 直接开 VESTA 窗口（在桌面终端里跑；三个视图各开一个窗口，可自由旋转）
  python scripts/vesta_view.py data/projects/temp/CONTCAR
  python scripts/vesta_view.py data/projects/temp/CONTCAR a        # 只看 a 视图

  # ② 不开窗口：离屏导出 PNG（无桌面/在服务器上也能用）
  python scripts/vesta_view.py data/projects/temp/CONTCAR all --png --out /tmp/vesta_view

  # ③ 临时试一组向量（不改进代码）：--vectors "水平x,水平y,水平z;视线x,视线y,视线z"
  python scripts/vesta_view.py data/projects/temp/CONTCAR a --vectors "0,1,0;1,0,0"

说明：向量表在 backend/vesta_render.py 的 AXIS_VECTORS（第 1 行=屏幕水平方向，
第 2 行=视线方向）；写入 .vesta 时后三列（视图中心偏移）沿用原文件，**不能清零**
（Linux VESTA 3.90.9a 清零会直接段错误 / invalid image）。
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from vesta_render import (  # noqa: E402
    AXIS_VECTORS,
    _apply_axis_settings,
    _run_vesta_cli,
    _vesta_exe,
    _vesta_zoom,
)


def ensure_display() -> None:
    """没设置 DISPLAY/XAUTHORITY 时，从当前会话里猜一个（桌面终端里通常已经有）。"""
    if not os.environ.get("DISPLAY"):
        sockets = sorted(glob.glob("/tmp/.X11-unix/X*"))
        if sockets:
            os.environ["DISPLAY"] = ":" + Path(sockets[0]).name[1:]
    if not os.environ.get("XAUTHORITY"):
        cookies = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"))
        if cookies:
            os.environ["XAUTHORITY"] = cookies[0]


def parse_vectors(text: str) -> tuple:
    """`"hx,hy,hz;vx,vy,vz"` → ((hx,hy,hz),(vx,vy,vz))。"""
    try:
        head, tail = text.split(";")
        row1 = tuple(float(x) for x in head.split(","))
        row2 = tuple(float(x) for x in tail.split(","))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"--vectors 格式应为 \"h1,h2,h3;v1,v2,v3\"：{exc}") from None
    if len(row1) != 3 or len(row2) != 3:
        raise SystemExit("--vectors 每行需要 3 个分量")
    return row1, row2


def build_template(exe: str, structure: Path, work: Path) -> Path:
    """用 VESTA CLI 把结构转成 .vesta 模板（这一步会临时起一次 VESTA 并自动收尾）。"""
    template = work / "_template.vesta"
    ok = _run_vesta_cli(
        [exe, "-open", str(structure), "-save", str(template), "-close", ""],
        template,
        marker=str(template),
    )
    if not ok or not template.is_file():
        raise SystemExit(
            "生成 .vesta 模板失败：检查 vesta_path（settings.json）、DISPLAY/XAUTHORITY，"
            "以及结构文件是否可读"
        )
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description="按 a/b/c 视图用 VESTA 打开或导出结构")
    parser.add_argument("structure", help="结构文件（POSCAR / CONTCAR / .vesta / .cif 等）")
    parser.add_argument("axis", nargs="?", default="all", choices=["a", "b", "c", "all"])
    parser.add_argument("--png", action="store_true", help="不开窗口，离屏导出 PNG（会自动用 xvfb-run）")
    parser.add_argument("--out", default="", help="--png 的输出目录（默认 /tmp/vesta_view）")
    parser.add_argument(
        "--vectors",
        default="",
        help='临时覆盖向量："水平x,水平y,水平z;视线x,视线y,视线z"',
    )
    args = parser.parse_args()

    structure = Path(args.structure).expanduser().resolve()
    if not structure.is_file():
        raise SystemExit(f"结构文件不存在：{structure}")
    axes = ["a", "b", "c"] if args.axis == "all" else [args.axis]
    override = parse_vectors(args.vectors) if args.vectors else None

    # 导出 PNG：必须在 Xvfb + 软件 GL 下跑（借桌面 DISPLAY 时 GL 画布出不了图，
    # 会报 image.cpp invalid image）——所以自动用 xvfb-run 重新执行自己一次。
    if args.png and os.environ.get("VESTA_VIEW_XVFB") != "1":
        env = dict(os.environ, VESTA_VIEW_XVFB="1", LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe")
        os.execvpe(
            "xvfb-run",
            ["xvfb-run", "-a", "-s", "-screen 0 1400x1000x24", sys.executable, __file__, *sys.argv[1:]],
            env,
        )

    ensure_display()
    exe = _vesta_exe()
    zoom = _vesta_zoom()

    work = Path(tempfile.mkdtemp(prefix="vesta_view_"))
    try:
        template = build_template(exe, structure, work)
        text = template.read_text(encoding="utf-8")
        out_dir = Path(args.out).expanduser() if args.out else Path("/tmp/vesta_view")

        for axis in axes:
            row1, row2 = override or AXIS_VECTORS.get(axis, AXIS_VECTORS["a"])
            target = work / f"{structure.stem}_{axis}.vesta"
            patched = _apply_axis_settings(text, axis, zoom)
            if override:
                # 直接替换前两行的前三列，保留后三列偏移
                lines = patched.splitlines(keepends=True)
                index = next(
                    i for i, line in enumerate(lines) if line.rstrip("\n").strip() == "LORIENT"
                )
                for row, line_index in ((row1, index + 2), (row2, index + 3)):
                    offset = lines[line_index].split()[3:6]
                    lines[line_index] = (
                        " " + "  ".join(f"{v:.6f}" for v in row) + "  " + "  ".join(offset) + "\n"
                    )
                patched = "".join(lines)
            target.write_text(patched, encoding="utf-8")

            print(f"[{axis}] 水平={row1}  视线={row2}")
            print(f"     .vesta: {target}")
            if args.png:
                out_dir.mkdir(parents=True, exist_ok=True)
                png = out_dir / f"{structure.stem}_{axis}.png"
                png.unlink(missing_ok=True)
                ok = _run_vesta_cli(
                    [exe, "-open", str(target), "-export_img", str(png), "-close", str(target)],
                    png,
                    marker=str(target),
                )
                print(f"     PNG: {'OK ' if ok else '失败 '}{png if ok else ''}")
            else:
                # 开窗口给用户看（不等待、不自动关）
                subprocess.Popen(
                    [exe, "-open", str(target)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        if not args.png:
            print("已在 VESTA 里打开（可自由旋转）；关掉窗口即可。")
        return 0
    finally:
        # 窗口模式下别删掉 .vesta（VESTA 还在用）；这里只在导出模式清理
        if args.png:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
