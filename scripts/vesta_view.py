#!/usr/bin/env python3
"""按 a / b / c 视图用 VESTA 打开结构（或 --png 导出），用于快速核对方向。

用法（在仓库根目录执行即可；脚本被复制到别处也能用，会自动找仓库根）：
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR a
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR          # a/b/c 各开一个窗口
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR all --png # 离屏导 PNG
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR a --vectors "0,1,0;1,0,0"

向量表在 backend/vesta_render.py 的 `AXIS_VECTORS`：第 1 行 = 屏幕水平方向，第 2 行 = 视线方向
（指向屏幕外）；写回 .vesta 时后三列（视图中心偏移）沿用原文件，清零会让 VESTA 段错误。
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def backend_dir() -> Path:
    """找到仓库里的 backend/：环境变量 → 脚本所在位置的各级父目录 → 当前目录 → 本机已知路径。"""
    here = Path(__file__).resolve()
    for base in (
        os.environ.get("VASP_MANAGER_ROOT"),
        *[str(p) for p in here.parents[:6]],
        os.getcwd(),
        "/home/zouyuxi/projects/vasp-manager",
    ):
        if base and (Path(base) / "backend" / "vesta_render.py").is_file():
            return Path(base) / "backend"
    raise SystemExit("找不到 backend/vesta_render.py：设 VASP_MANAGER_ROOT，或在仓库根目录运行")


sys.path.insert(0, str(backend_dir()))

from vesta_render import (  # noqa: E402
    AXIS_VECTORS,
    _apply_axis_settings,
    _run_vesta_cli,
    _vesta_exe,
    _vesta_zoom,
)


def ensure_display() -> None:
    """窗口模式：没设 DISPLAY/XAUTHORITY 时从当前会话猜一个。"""
    if not os.environ.get("DISPLAY"):
        sockets = sorted(glob.glob("/tmp/.X11-unix/X*"))
        if sockets:
            os.environ["DISPLAY"] = ":" + Path(sockets[0]).name[1:]
    if not os.environ.get("XAUTHORITY"):
        cookies = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"))
        if cookies:
            os.environ["XAUTHORITY"] = cookies[0]


def with_override(patched: str, row1: tuple, row2: tuple) -> str:
    """把 LORIENT 前两行的前三列换成给定向量（后三列偏移原样保留）。"""
    lines = patched.splitlines(keepends=True)
    i = next(i for i, l in enumerate(lines) if l.rstrip("\n").strip() == "LORIENT")
    for row, k in ((row1, i + 2), (row2, i + 3)):
        offset = lines[k].split()[3:6]
        lines[k] = " " + "  ".join(f"{v:.6f}" for v in row) + "  " + "  ".join(offset) + "\n"
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="按 a/b/c 视图用 VESTA 打开/导出结构")
    ap.add_argument("structure")
    ap.add_argument("axis", nargs="?", default="all", choices=["a", "b", "c", "all"])
    ap.add_argument("--png", action="store_true", help="离屏导出 PNG（自动用 xvfb + 软件 GL）")
    ap.add_argument("--out", default="/tmp/vesta_view", help="--png 输出目录")
    ap.add_argument("--vectors", default="", help='"hx,hy,hz;vx,vy,vz" 临时覆盖向量')
    ap.add_argument("--_make-template", metavar="OUT", help=argparse.SUPPRESS)  # 内部：只生成模板
    args = ap.parse_args()

    # PNG 必须跑在 Xvfb + 软件 GL 下（借桌面 DISPLAY 出不了图，会报 invalid image）
    if args.png and os.environ.get("VESTA_VIEW_XVFB") != "1":
        env = dict(
            os.environ, VESTA_VIEW_XVFB="1", LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe"
        )
        os.execvpe(
            "xvfb-run",
            ["xvfb-run", "-a", "-s", "-screen 0 1400x1000x24", sys.executable, *sys.argv],
            env,
        )

    structure = Path(args.structure).expanduser().resolve()
    if not structure.is_file():
        raise SystemExit(f"结构文件不存在：{structure}")

    # 内部模式：只把结构转成 .vesta 模板（会被主流程放到 Xvfb 里执行，不弹窗口）
    if args._make_template:
        target = Path(args._make_template)
        exe = _vesta_exe()
        if not _run_vesta_cli(
            [exe, "-open", str(structure), "-save", str(target), "-close", ""],
            target,
            marker=str(target),
        ):
            raise SystemExit("生成 .vesta 模板失败")
        print(target)
        return 0

    axes = ["a", "b", "c"] if args.axis == "all" else [args.axis]
    override = None
    if args.vectors:
        h, v = args.vectors.split(";")
        override = (
            tuple(float(x) for x in h.split(",")),
            tuple(float(x) for x in v.split(",")),
        )

    ensure_display()
    exe = _vesta_exe()
    zoom = _vesta_zoom()
    work = Path(tempfile.mkdtemp(prefix="vesta_view_"))
    template = work / "_template.vesta"
    if structure.suffix.lower() == ".vesta":
        template = structure  # 已经是 .vesta 就直接用，省掉一次窗口
    elif args.png:
        # 已经在 Xvfb 里，直接生成即可（不可见）
        if not _run_vesta_cli(
            [exe, "-open", str(structure), "-save", str(template), "-close", ""],
            template,
            marker=str(template),
        ):
            raise SystemExit("生成 .vesta 模板失败：检查 settings.json 的 vesta_path")
    else:
        # 窗口模式：模板生成丢到 Xvfb 子进程里做，避免额外弹一个窗口
        env = dict(
            os.environ, LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe", VESTA_VIEW_XVFB="1"
        )
        done = subprocess.run(
            [
                "xvfb-run", "-a", "-s", "-screen 0 1200x900x24",
                sys.executable, str(Path(__file__).resolve()),
                str(structure), "--_make-template", str(template),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if done.returncode != 0 or not template.is_file():
            raise SystemExit(
                "生成 .vesta 模板失败：检查 settings.json 的 vesta_path\n"
                + (done.stderr or done.stdout or "")
            )
    if not template.is_file():
        raise SystemExit("生成 .vesta 模板失败：检查 settings.json 的 vesta_path")
    text = template.read_text(encoding="utf-8")

    for axis in axes:
        row1, row2 = override or AXIS_VECTORS.get(axis, AXIS_VECTORS["a"])
        target = work / f"{structure.stem}_{axis}.vesta"
        patched = with_override(_apply_axis_settings(text, axis, zoom), row1, row2)
        target.write_text(patched, encoding="utf-8")
        print(f"[{axis}] 水平={row1} 视线={row2}\n     .vesta: {target}")
        if args.png:
            out = Path(args.out).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            png = out / f"{structure.stem}_{axis}.png"
            png.unlink(missing_ok=True)
            ok = _run_vesta_cli(
                [exe, "-open", str(target), "-export_img", str(png), "-close", str(target)],
                png,
                marker=str(target),
            )
            print(f"     PNG: {'OK' if ok else '失败'} {png if ok else ''}")
        else:
            subprocess.Popen(
                [exe, "-open", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    if not args.png:
        print("已在 VESTA 打开（可自由旋转），关掉窗口即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
