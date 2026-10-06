#!/usr/bin/env python3
"""按 a / b / c 视图用 VESTA 打开结构（或 --png 导出），用于快速核对方向。

用法（在仓库根目录执行即可；脚本被复制到别处也能用，会自动找仓库根）：
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR          # a/b/c 各开一个窗口
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR b        # 只开 b 视图
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR all --png # 离屏导 PNG
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR c --view c --right a
    .venv/bin/python scripts/vesta_view.py data/projects/temp/CONTCAR --close  # 关掉这个结构的窗口
    .venv/bin/python scripts/vesta_view.py --close-all                          # 关掉脚本开过的所有窗口
    .venv/bin/python scripts/vesta_view.py --close-blank                        # 清掉空白 VESTA 窗口
    .venv/bin/python scripts/vesta_view.py --list                               # 看看现在开着哪些

朝向表在 backend/vesta_render.py 的 `AXIS_VIEW`（view=视线方向、up=屏幕向上、right=屏幕向右），
命令行 --view/--up/--right 可以临时覆盖某一项（值写 a/b/c 或 x,y,z）而不改文件。
生成的 .vesta 会打印出绝对路径（默认 <结构文件所在目录>/vesta_view/ 下）。

**窗口不会越开越多**：同一个 .vesta 再开之前会先把上次那个窗口关掉；每开一个都登记在
`~/.cache/vasp-manager/vesta-windows.json`，用 `--close` / `--close-all` 精确关掉自己开的那些
（给窗口发 WM_DELETE_WINDOW，等价于点 ×；**不杀 VESTA 进程**，所以不会误伤用户自己开的窗口）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
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
    _vesta_image_scale,
    _vesta_zoom,
    axis_view_matrix,
    close_x_windows,
    list_x_windows,
    vesta_window_titles,
)


#: 登记"脚本自己开过哪些 VESTA 窗口"的状态文件（跨次调用有效，用来精确关闭、不误伤用户窗口）
WINDOW_STATE = Path.home() / ".cache" / "vasp-manager" / "vesta-windows.json"


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


def load_window_state() -> list:
    try:
        data = json.loads(WINDOW_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("vesta")]


def save_window_state(items: list) -> None:
    try:
        WINDOW_STATE.parent.mkdir(parents=True, exist_ok=True)
        WINDOW_STATE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def close_windows(only: set | None = None, quiet: bool = False) -> int:
    """关掉（脚本自己开过的）VESTA 窗口，返回关闭数；顺便清理状态文件里的死条目。

    关法是给窗口发 WM_DELETE_WINDOW（= 点 ×），只关"登记过的 .vesta 对应的那些窗口"，
    **不杀 VESTA 进程** —— 用户自己开的窗口即使在同一个进程里也不会被误伤。
    """
    items = load_window_state()
    kept, closed = [], 0
    # 一次收集所有要关的标题，同一批发完再统一确认
    targets = []
    for item in items:
        vesta = str(item["vesta"])
        if only is not None and vesta not in only:
            # 不在这次范围内：如果窗口已经没了就把记录丢掉
            if not list_x_windows(vesta_window_titles([vesta])):
                continue
            kept.append(item)
            continue
        titles = vesta_window_titles([vesta])
        if not list_x_windows(titles):
            continue  # 用户已经自己关掉了 → 记录作废
        targets.append((vesta, titles))

    if targets:
        all_titles = set().union(*(t for _, t in targets))
        close_x_windows(all_titles)
        for _ in range(20):  # 最多等 4 s 让窗口真的消失
            time.sleep(0.2)
            if not list_x_windows(all_titles):
                break
        for vesta, titles in targets:
            if list_x_windows(titles):
                print(f"  ⚠ 关不掉（窗口还在）：{vesta}")
                kept.append({"vesta": vesta, "opened": int(time.time())})
                continue
            closed += 1
            if not quiet:
                print(f"  已关闭窗口：{vesta}")
    save_window_state(kept)
    return closed


def present_targets(targets: list) -> list:
    """筛出"窗口已经真的开出来"的 .vesta（VESTA 单实例转发有丢窗口的可能，必须确认）。"""
    seen = {t for _, t in list_x_windows(vesta_window_titles(targets))}
    return [t for t in targets if f"{t.name} - VESTA" in seen]


def open_windows(targets: list, exe: str, wait: float = 12.0, attempts: int = 3) -> list:
    """打开若干 .vesta 窗口，**确认窗口真的出现**（少了就重试），返回登记条目。

    为什么必须确认：VESTA 是单实例，后开的文件由启动器转给已经在跑的实例；
    紧接着关掉再开（或连开一串）时偶尔会丢一个 —— 只 Popen 不检查就会
    "以为开了 3 个、其实只有 2 个"，反复调用就会越攒越少/越乱。
    """
    missing = list(targets)
    for _ in range(max(1, attempts)):
        if not missing:
            break
        for target in missing:
            subprocess.Popen(
                # 位置参数：用 `-open` 时 VESTA 会额外开一个空白窗口（2026-10-06 实测）
                [exe, str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(1.0)  # 单实例转发要时间，太密会丢窗口
        deadline = time.time() + wait
        while time.time() < deadline and len(present_targets(missing)) < len(missing):
            time.sleep(0.5)
        done = present_targets(missing)
        missing = [t for t in missing if t not in done]
    return [{"vesta": str(t), "opened": int(time.time())} for t in present_targets(targets)]


def main() -> int:
    ap = argparse.ArgumentParser(description="按 a/b/c 视图用 VESTA 打开/导出结构")
    ap.add_argument("structure", nargs="?", help="结构文件（POSCAR/CONTCAR/任意 VASP 结构）")
    ap.add_argument("axis", nargs="?", default="all", choices=["a", "b", "c", "all"])
    ap.add_argument("--png", action="store_true", help="离屏导出 PNG（自动用 xvfb + 软件 GL）")
    ap.add_argument("--out", default="/tmp/vesta_view", help="--png 输出目录")
    ap.add_argument("--view", default="", help="临时改视线方向（a/b/c 或 x,y,z）")
    ap.add_argument("--up", default="", help="临时改屏幕向上方向")
    ap.add_argument("--right", default="", help="临时改屏幕向右方向")
    ap.add_argument("--out-dir", default="", help=".vesta 输出目录（默认 <结构目录>/vesta_view）")
    ap.add_argument("--close", action="store_true", help="关掉这个结构（a/b/c）已开的窗口")
    ap.add_argument("--close-all", action="store_true", help="关掉本脚本开过的所有 VESTA 窗口")
    ap.add_argument("--close-blank", action="store_true", help="关掉没用上的空白 VESTA 窗口")
    ap.add_argument("--list", action="store_true", help="列出脚本登记在案的窗口")
    ap.add_argument("--_make-template", metavar="OUT", help=argparse.SUPPRESS)  # 内部：只生成模板
    args = ap.parse_args()

    ensure_display()  # 关窗口/列窗口也要知道桌面 DISPLAY

    if args.list:
        alive = [i for i in load_window_state() if present_targets([Path(str(i["vesta"]))])]
        for item in alive:
            print(item["vesta"])
        save_window_state(alive)
        blank = [t for _, t in list_x_windows({"VESTA"})]
        print(
            f"脚本开的窗口：{len(alive)} 个；另有空白 VESTA 窗口 {len(blank)} 个"
            f"（--close-blank 可清）；状态文件 {WINDOW_STATE}"
        )
        return 0

    if args.close_all:
        closed = close_windows()
        print(f"已关闭 {closed} 个窗口（脚本自己开的；用户自己开的 VESTA 不受影响）")
        return 0

    if args.close_blank:
        n = len(close_x_windows({"VESTA"}))
        print(f"已关闭 {n} 个空白 VESTA 窗口")
        return 0

    if not args.structure:
        raise SystemExit("用法：vesta_view.py <结构文件> [a|b|c|all] [--png|--close|--close-all|--list]")

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
    if args.close:
        # 关窗口不需要生成模板：目标 .vesta 名字和打开时一致即可
        closed = close_windows(only={str(work / f"{structure.stem}_{ax}.vesta") for ax in axes})
        print(f"已关闭 {closed} 个窗口（{structure.name} 的 {'/'.join(axes)}）")
        return 0
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

    targets = []
    for axis in axes:
        spec = override_spec(axis, args.view, args.up, args.right)
        matrix = axis_view_matrix(cell, axis, spec)
        target = work / f"{structure.stem}_{axis}.vesta"
        patched = _apply_axis_settings(text, axis, zoom, spec)
        target.write_text(patched, encoding="utf-8")
        targets.append(target)
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
                [
                    exe,
                    "-open",
                    str(target),
                    "-export_img",
                    str(png),
                    f"scale={_vesta_image_scale()}",  # 默认 2 倍分辨率（settings.json: vesta_image_scale）
                    "-close",
                    str(target),
                ],
                png,
                marker=str(target),
            )
            print(f"     PNG: {'OK' if ok else '失败'} {png if ok else ''}")

    if args.png:
        return 0

    # 窗口模式：先关掉"同一个 .vesta 上次开的那个窗口"，再开新的 —— 反复调用也不会越开越多
    target_paths = {str(t) for t in targets}
    stale = close_windows(only=target_paths, quiet=True)
    if stale:
        print(f"（先关掉了这组视图上次开的 {stale} 个旧窗口）")
    items = open_windows(targets, exe)
    merged = {str(i["vesta"]): i for i in load_window_state()}
    merged.update({str(i["vesta"]): i for i in items})
    save_window_state(list(merged.values()))
    print(
        f"已在 VESTA 打开 {len(items)}/{len(targets)} 个窗口（可自由旋转）；"
        "关窗口用 --close，全部关掉用 --close-all。"
    )
    if len(items) < len(targets):
        missing = [str(t) for t in targets if t not in {Path(i["vesta"]) for i in items}]
        print("⚠ 下面这些没开出来（VESTA 单实例转发偶尔丢窗口，重跑一次即可）：")
        for m in missing:
            print(f"   {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
