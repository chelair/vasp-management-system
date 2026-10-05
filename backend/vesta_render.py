"""VESTA 结构渲染（供巡检详情结构分析使用，适配 web 系统）。

按 a/b/c 晶轴渲染 POSCAR/CONTCAR 的 PNG 对比图；VESTA 缺失/执行异常
仅记录警告并返回 skipped，不影响巡检主流程。渲染结果缓存到任务
reports/structure/ 目录，重复打开详情不再重新渲染。
"""

from __future__ import annotations

import os
import re
import signal
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config import load_settings
from task_paths import task_files_dir

#: 三个视图的 LORIENT 向量：**想调方向就只改这张表**（各写 3 个分量，可写小数/负数）。
#: 格式 `(水平向量 v1, 视线向量 v2)`：
#:   - 第 1 行 v1 = **屏幕水平方向**（画面里朝右的那个方向）
#:   - 第 2 行 v2 = **视线方向**（指向屏幕外，也就是"沿哪个方向看"）
#: 这两行会被写进 .vesta 的 LORIENT 段（每行 6 个数 = 3 旋转 + 3 视图中心偏移；
#: **偏移沿用原文件的值，不要清零** —— 清零会让 VESTA 段错误、导出无效图）。
#: 下面这组是脚本最初的取值；正交晶胞里 "a"=ab 面、"b"=ab 面(b 水平)、"c"=ac 面。
AXIS_VECTORS: Dict[str, tuple] = {
    "a": ((1, 0, 0), (0, 0, 1)),
    "b": ((0, 1, 0), (0, 0, 1)),
    "c": ((0, 0, 1), (0, 1, 0)),
}


RENDER_WAIT = 12  # 秒：等待 VESTA 输出文件的最长时间
MIN_IONIC_STEPS = 5
DEFAULT_STEPS_FALLBACK = 99


def _vesta_exe() -> str:
    settings = load_settings()
    return str(settings.get("vesta_path") or "vesta")


#: 本进程启动过的 VESTA 子进程：(Popen, 进程组 id)。
#: **pgid 必须在启动瞬间记下** —— VESTA 启动器会 fork 出 `sh -c → VESTA-gui` 后自己退出，
#: 之后再 `os.getpgid(pid)` 会因"进程已不存在"失败，导致 GUI 残留（2026-10-06 实测踩到）。
_VESTA_PROCS: list = []


def _vesta_zoom() -> float:
    settings = load_settings()
    try:
        return float(settings.get("vesta_zoom", 1.7))
    except (TypeError, ValueError):
        return 1.7


def _apply_axis_settings(template_text: str, axis: str, zoom: float) -> str:
    """替换 .vesta 中的 PROJT 缩放比例与 LORIENT 视角矩阵。

    只替换 LORIENT 的**前三列（旋转）**，后三列（视图中心/平移）必须原样保留
    ——清零会让 VESTA 直接段错误、导不出图（2026-10-06 在 Linux 上实测，
    Windows 上一直没暴露：`Segmentation fault (core dumped)` + `invalid image`）。
    """
    text = re.sub(
        r"(?m)^PROJT\s+0\s+[-+\d.eE]+\s*$",
        f"PROJT 0  {zoom:.3f}",
        template_text,
    )
    if "PROJT" not in text:
        text += f"\nPROJT 0  {zoom:.3f}\n"

    v1, v2 = AXIS_VECTORS.get(axis, AXIS_VECTORS["a"])

    lines = text.splitlines(keepends=True)
    lorient_idx = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n").strip() == "LORIENT"),
        None,
    )
    if lorient_idx is not None and lorient_idx + 4 <= len(lines):
        def _offset(row_index: int) -> str:
            """沿用原行的视图中心（后三列）；原行不成 6 列时退回全 0。"""
            parts = lines[row_index].split()
            values = parts[3:6] if len(parts) >= 6 else ["0.000000"] * 3
            return "  " + "  ".join(values)

        row1 = f" {v1[0]:.6f}  {v1[1]:.6f}  {v1[2]:.6f}{_offset(lorient_idx + 2)}\n"
        row2 = f" {v2[0]:.6f}  {v2[1]:.6f}  {v2[2]:.6f}{_offset(lorient_idx + 3)}\n"
        new_text = (
            "".join(lines[: lorient_idx + 2]) + row1 + row2 + "".join(lines[lorient_idx + 4 :])
        )
    else:
        row1 = f" {v1[0]:.6f}  {v1[1]:.6f}  {v1[2]:.6f}  0.000000  0.000000  0.000000\n"
        row2 = f" {v2[0]:.6f}  {v2[1]:.6f}  {v2[2]:.6f}  0.000000  0.000000  0.000000\n"
        new_text = (
            text
            + f"\nLORIENT\n 1.000000  0.000000  0.000000  0.000000  0.000000  0.000000\n{row1}{row2}"
        )
    return new_text


def _kill_vesta() -> None:
    """结束**本次渲染启动的** VESTA 进程，防止 GUI 卡死残留。

    Windows 用 taskkill；Linux/macOS 走 Popen 句柄 terminate→kill
    （之前只处理 Windows，Linux 上渲染完 VESTA 不退出、会越积越多 —— 2026-10-06 实测）。
    """
    while _VESTA_PROCS:
        proc, pgid = _VESTA_PROCS.pop()
        try:
            _terminate_tree(proc, pgid)
            if proc.poll() is None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    _kill_tree(proc, pgid)
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/IM", "VESTA.exe", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            pass


def _terminate_tree(proc, pgid: int) -> None:
    """结束整个进程组。

    VESTA 启动器会再 fork `sh -c … VESTA-gui`，只 terminate 启动器会留下
    孙进程（GUI 常驻不退出）——所以按**进程组**结束（Popen 时开了 start_new_session）。
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except Exception:  # noqa: BLE001 - 非 POSIX / 进程组已消失
        proc.terminate()


def _kill_tree(proc, pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except Exception:  # noqa: BLE001
        proc.kill()


def _sweep_by_marker(marker: str) -> None:
    """兜底清理：按命令行里的**唯一标记**结束 VESTA 进程。

    VESTA 启动器会 double-fork 出 GUI 并**逃出我们的进程组**（新会话），只按 pgid kill
    会漏掉它。这里用"本次生成的临时 .vesta 路径"做标记精确匹配（路径唯一），
    **不会误伤用户自己开的 VESTA**。

    两个必要条件（否则会把调用者自己杀掉 —— 2026-10-06 实测踩到：模板路径写在命令行里时
    `pgrep -f <路径>` 会匹配到本进程，SIGKILL 后主程序直接 exit 137）：
      ① 跳过本进程与父进程；② 该进程的命令行里必须出现 VESTA 可执行文件路径。
    """
    if not marker:
        return
    try:
        out = subprocess.run(
            ["pgrep", "-f", marker], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:  # noqa: BLE001 - 没有 pgrep 就算了，不影响主流程
        return
    self_pids = {os.getpid(), os.getppid()}
    exe = _vesta_exe()
    for text in out.split():
        if not text.strip().isdigit():
            continue
        pid = int(text)
        if pid in self_pids:
            continue
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace"
            )
        except OSError:
            continue
        if exe not in args:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass


def _run_vesta_cli(
    command, expected_path: Path, wait_seconds: int = RENDER_WAIT, marker: str = ""
) -> bool:
    """后台启动 VESTA CLI，轮询输出文件生成，超时/结束后强制清理进程。"""
    _kill_vesta()
    _sweep_by_marker(marker)
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # VESTA 是 GTK 程序：无 DISPLAY 时直接报"Unable to initialize GTK+"，
            # 由外部（桌面会话的 DISPLAY/XAUTHORITY 或 xvfb-run）提供显示环境
            # start_new_session：让 VESTA（及其 fork 出的 sh→VESTA-gui）自成一个进程组，
            # 收尾时可整组结束，避免 GUI 孙进程残留
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except Exception:  # noqa: BLE001 - 取不到就退回进程自身
            pgid = proc.pid
        _VESTA_PROCS.append((proc, pgid))
    except Exception:  # noqa: BLE001 - VESTA 不可用
        return False
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if expected_path.is_file() and expected_path.stat().st_size > 0:
            break
        time.sleep(0.5)
    _kill_vesta()
    _sweep_by_marker(marker)
    return expected_path.is_file() and expected_path.stat().st_size > 0


def _build_vesta_template(structure_path: Path, work_dir: Path) -> Optional[Path]:
    """调用 VESTA 由结构文件生成基础 .vesta 模板；失败返回 None。"""
    template_path = work_dir / f"_temp_{structure_path.stem}.vesta"
    ok = _run_vesta_cli(
        [_vesta_exe(), "-open", str(structure_path), "-save", str(template_path), "-close", ""],
        template_path,
        marker=str(template_path),
    )
    return template_path if ok else None


def _render_axis(work_dir: Path, template_text: str, axis: str, zoom: float, png_path: Path) -> bool:
    """修改 LORIENT/PROJT 后用 VESTA 导出单轴 PNG。"""
    custom_vesta = work_dir / f"_temp_{axis}.vesta"
    custom_vesta.write_text(
        _apply_axis_settings(template_text, axis, zoom), encoding="utf-8"
    )
    ok = _run_vesta_cli(
        [
            _vesta_exe(),
            "-open",
            str(custom_vesta),
            "-export_img",
            str(png_path),
            "-close",
            str(custom_vesta),
        ],
        png_path,
        marker=str(custom_vesta),
    )
    if not ok:
        png_path.unlink(missing_ok=True)
    return ok


def render_task(
    project: Dict[str, Any],
    task: Dict[str, Any],
    steps: Optional[int] = None,
) -> Dict[str, Any]:
    """渲染单个结构优化任务的 a/b/c 轴 POSCAR/CONTCAR 对比图（带缓存）。"""
    task_id = task["task_id"]
    files_dir = task_files_dir(project["name"], task)
    warnings: list = []
    poscar = files_dir / "POSCAR"
    contcar = files_dir / "CONTCAR"

    if not poscar.is_file() or not contcar.is_file():
        return {
            "task_id": task_id,
            "steps": None,
            "images": {"poscar": {}, "contcar": {}},
            "warnings": warnings,
            "skipped": "结构文件缺失（POSCAR/CONTCAR 未同步）",
        }

    if steps is None:
        steps = DEFAULT_STEPS_FALLBACK
    if steps < MIN_IONIC_STEPS:
        return {
            "task_id": task_id,
            "steps": steps,
            "images": {"poscar": {}, "contcar": {}},
            "warnings": warnings,
            "skipped": f"离子步数 {steps} < {MIN_IONIC_STEPS}，结构几乎未弛豫，跳过渲染",
        }

    reports_dir = files_dir.parent / "reports" / "structure"
    reports_dir.mkdir(parents=True, exist_ok=True)
    zoom = _vesta_zoom()
    images: Dict[str, Dict[str, str]] = {"poscar": {}, "contcar": {}}

    # 全量缓存命中：六张图都已生成则直接复用，避免再次启动 VESTA
    cached = all(
        (reports_dir / f"{label}_{axis}.png").is_file()
        and (reports_dir / f"{label}_{axis}.png").stat().st_size > 0
        for label in ("poscar", "contcar")
        for axis in ("a", "b", "c")
    )
    if cached:
        images = {
            label: {
                axis: str(reports_dir / f"{label}_{axis}.png")
                for axis in ("a", "b", "c")
            }
            for label in ("poscar", "contcar")
        }
        return {
            "task_id": task_id,
            "steps": steps,
            "images": images,
            "warnings": warnings,
            "skipped": None,
        }

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        for label, structure_path in (("poscar", poscar), ("contcar", contcar)):
            template = _build_vesta_template(structure_path, work_dir)
            if template is None:
                warnings.append(f"{label} VESTA 模板生成失败（检查 vesta_path 配置）")
                continue
            template_text = template.read_text(encoding="utf-8", errors="replace")
            for axis in ("a", "b", "c"):
                png_path = reports_dir / f"{label}_{axis}.png"
                if png_path.is_file() and png_path.stat().st_size > 0:
                    # 缓存命中：结构文件未变化时直接复用
                    images[label][axis] = str(png_path)
                    continue
                if _render_axis(work_dir, template_text, axis, zoom, png_path):
                    images[label][axis] = str(png_path)
                else:
                    warnings.append(f"{label} {axis} 轴渲染失败")

    if not any(images["poscar"].values()) and not any(images["contcar"].values()):
        return {
            "task_id": task_id,
            "steps": steps,
            "images": images,
            "warnings": warnings,
            "skipped": "全部渲染失败",
        }
    return {
        "task_id": task_id,
        "steps": steps,
        "images": images,
        "warnings": warnings,
        "skipped": None,
    }
