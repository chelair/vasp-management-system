#!/usr/bin/env python3
"""按 a / b / c 视图用 VESTA 打开结构（或 --png 导出），用于快速核对方向。

用法（在仓库根目录执行即可；脚本被复制到别处也能用，会自动找仓库根）：
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR          # a/b/c 各开一个窗口
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR b        # 只开 b 视图
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR all --png # 离屏导 PNG
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR c --view c --right a

朝向表在 backend/vesta_render.py 的 `AXIS_VIEW`（view=视线方向、up=屏幕向上、right=屏幕向右），
命令行 --view/--up/--right 可以临时覆盖某一项（值写 a/b/c 或 x,y,z）而不改文件。
生成的 .vesta 会打印出绝对路径（默认 <结构文件所在目录>/vesta_view/ 下）。
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
    AXIS_VIEW,
    _apply_axis_settings,
    _parse_cellp,
    _run_vesta_cli,
    _vesta_exe,
    _vesta_zoom,
    axis_view_matrix,
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


def override_spec(axis: str, view: str, up: str, right: str):
    """把 --view/--up/--right 拼成 AXIS_VIEW 那样的 spec；没给就返回 None。"""
    if not (view or up or right):
        return None
    base = dict(AXIS_VIEW.get(axis) or AXIS_VIEW["a"])
    if view:
        base["view"] = view
    if up or right:
        # 命令行一旦给了 up/right，就以命令行为准（另一个没给 = 自动算）
        base["up"] = up or None
        base["right"] = right or None
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description="按 a/b/c 视图用 VESTA 打开/导出结构")
    ap.add_argument("structure")
    ap.add_argument("axis", nargs="?", default="all", choices=["a", "b", "c", "all"])
    ap.add_argument("--png", action="store_true", help="离屏导出 PNG（自动用 xvfb + 软件 GL）")
    ap.add_argument("--out", default="/tmp/vesta_view", help="--png 输出目录")
    ap.add_argument("--view", default="", help="临时改视线方向（a/b/c 或 x,y,z）")
    ap.add_argument("--up", default="", help="临时改屏幕向上方向")
    ap.add_argument("--right", default="", help="临时改屏幕向右方向")
    ap.add_argument("--out-dir", default="", help=".vesta 输出目录（默认 <结构目录>/vesta_view）")
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

    ensure_display()
    exe = _vesta_exe()
    zoom = _vesta_zoom()
    # 输出目录固定、可预期（用户要能自己找到 .vesta 手改）：<结构目录>/vesta_view/
    if args.out_dir:
        work = Path(args.out_dir).expanduser()
    elif os.access(structure.parent, os.W_OK):
        work = structure.parent / "vesta_view"
    else:
        work = Path(tempfile.mkdtemp(prefix="vesta_view_"))
    work.mkdir(parents=True, exist_ok=True)
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
    cell = _parse_cellp(text)

    for axis in axes:
        spec = override_spec(axis, args.view, args.up, args.right)
        matrix = axis_view_matrix(cell, axis, spec)
        target = work / f"{structure.stem}_{axis}.vesta"
        patched = _apply_axis_settings(text, axis, zoom, spec)
        target.write_text(patched, encoding="utf-8")
        shown = spec or AXIS_VIEW.get(axis) or AXIS_VIEW["a"]
        print(
            f"[{axis}] 视线={shown.get('view')} 向上={shown.get('up')} 向右={shown.get('right')}"
        )
        if matrix:
            for row_name, row in zip(("屏幕x", "屏幕y", "屏幕z"), matrix):
                print(f"     {row_name} = ({row[0]: .6f}, {row[1]: .6f}, {row[2]: .6f})")
        print(f"     .vesta: {target}")
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
                # 直接给"位置参数"：用 `-open` 时 VESTA 会额外开一个空白窗口（2026-10-06 实测）
                [exe, str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    if not args.png:
        print("已在 VESTA 打开（可自由旋转），关掉窗口即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
