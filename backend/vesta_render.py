"""VESTA 结构渲染：按 a/b/c 晶轴出 POSCAR/CONTCAR 的 PNG（供报告/详情用）。

入口 `render_task(project, task)`：读 `<任务目录>/files/{POSCAR,CONTCAR}`，
图写到**与 files/ 同级**的 `<任务目录>/images/{poscar,contcar}_{a,b,c}.png`，
同名覆盖、不产生副本（详见函数 docstring）。VESTA 缺失/执行异常只记 warning，
不影响主流程。也可以在命令行用 scripts/vesta_view.py 手动看/导图。

调用方注意：VESTA 是 GTK 程序，必须在 Xvfb + 软件 GL 里跑（DEPENDENCIES.md §3b）。
"""

from __future__ import annotations

import ctypes
import os
import re
import signal
import math
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import DATA_DIR, load_settings
from task_paths import task_dir, task_files_dir

#: 三视图口径：**想调朝向只改这张表**。
#:   view  = 视线方向 —— 写哪根晶轴，哪根轴就指向屏幕外（"沿这根轴看"）
#:   up    = 屏幕竖直向上（写另一根晶轴；会自动对视线方向正交化）
#:   right = 屏幕水平向右（留 None = 用 right = up × view 自动算，保证右手系、不出镜像）
#: 值可以写 'a'/'b'/'c'，也可以直接写 3 个分量的晶格向量 (x, y, z)。
#: 用户口径（2026-10-06 用他手点 VESTA 存下的 .vesta 逐一对过）：
#:   a 视图 = 沿 a 看、c 朝上（b 在画面里偏右）；b 视图 = 沿 b 看、c 朝上；c 视图 = 沿 c 看、a 朝右。
AXIS_VIEW: Dict[str, Dict[str, Any]] = {
    "a": {"view": "a", "up": "c", "right": None},
    "b": {"view": "b", "up": "c", "right": None},
    "c": {"view": "c", "up": None, "right": "a"},
}

#: **渲染口径版本**：视角定义（AXIS_VIEW）/缩放/导出倍数（vesta_image_scale）变了就 +1。
#: 渲染前会比对 <任务目录>/images/.view_version，对不上就整批重画 ——
#: 以前改了视角要手动删 PNG 才会更新（缓存只看"文件比结构新"）。
#: v3：导出倍数改成 2（`-export_img ... scale=2`，2026-10-06）。
VIEW_VERSION = 3

RENDER_WAIT = 12  # 秒：等待 VESTA 输出文件的最长时间
#: 体积数据（CHGCAR_diff / LOCPOT 之类，百 MB 级）加载慢得多，等待时间单独放宽
#: （2026-10-14 实测：130MB 的 CHGCAR_diff 打开 3.6s、单轴导出 2.4s，留足余量）
VOLUME_RENDER_WAIT = 300
#: **体积图渲染口径版本**：出图方式改了就 +1 —— 渲染前比对
#: `<image_dir>/.volume_version`，对不上就把旧图作废重画。
#: v1（2026-10-14）：从"存模板再重开"（等值面层级不对，分子那侧没瓣）
#: 改成"直接打开体积文件 + `-rotate_*` 转到目标轴向"。
VOLUME_RENDER_VERSION = 1
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


def _vesta_image_scale() -> int:
    """导出图片的放大倍数（= "图像质量"）：VESTA CLI 的 `-export_img <file> scale=N`。

    实测（2026-10-06）：`scale=2` 把 1126×649 的导出图变成 2252×1298 ——
    缩放到同样显示尺寸时线条/球体明显更锐利。用户口径：**默认 2**。
    想调就改 `data/config/settings.json` 的 `vesta_image_scale`（1 = 与画布同尺寸）。
    """
    settings = load_settings()
    try:
        return max(1, int(float(settings.get("vesta_image_scale", 2))))
    except (TypeError, ValueError):
        return 2


# ---------------------------------------------------------------------------
# 跨进程 VESTA 串行锁
#
# VESTA 渲染有两条独立路径：巡检/归档的结构图（`structure_images` 的后台 xvfb 子进程）
# 与差分电荷的体积图（`charge_diff` 的后台 xvfb 子进程）。两者跑在**不同进程**里，
# Python 线程锁串不起来；而 CHGCAR_diff 这类百 MB 体积数据一次渲染要吃几百 MB 内存，
# 两个 VESTA 同时开着最容易把生产机拖卡（2026-10-14 用户要求"尽量避免系统卡死"）。
# 这里用 `data/locks/vesta_render.lock` 的 fcntl 文件锁把两边串起来（退出即释放）。
# ---------------------------------------------------------------------------
_VESTA_THREAD_LOCK = threading.Lock()


def _vesta_lock_path() -> Path:
    return DATA_DIR / "locks" / "vesta_render.lock"


@contextmanager
def vesta_render_lock(timeout: float = 1800.0):
    """独占"本机 VESTA 渲染"：同一时刻只允许一个 VESTA 在跑（**跨进程**）。

    等不到锁也不阻断渲染（超时后照常继续）—— 宁可多开一个 VESTA，也不要让整条
    链路卡死在等锁上。非 POSIX 平台退化成进程内线程锁。
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - 非 POSIX
        with _VESTA_THREAD_LOCK:
            yield
        return
    handle = None
    try:
        path = _vesta_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+")
        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    break
                time.sleep(0.5)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001 - 解锁失败无伤
                pass
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass


def _unit(v) -> Optional[tuple]:
    if v is None:
        return None
    norm = math.sqrt(sum(float(x) * float(x) for x in v))
    if norm < 1e-9:
        return None
    return tuple(float(x) / norm for x in v)


def _cross(u, v) -> tuple:
    return (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )


def _dot(u, v) -> float:
    return sum(float(a) * float(b) for a, b in zip(u, v))


def _orthogonal(v, ref) -> Optional[tuple]:
    """把 v 对 ref 正交化（Gram-Schmidt）；退化成 0 时返回 None。"""
    if v is None or ref is None:
        return None
    k = _dot(v, ref)
    return _unit(tuple(float(v[i]) - k * float(ref[i]) for i in range(3)))


def _parse_cellp(text: str) -> Optional[tuple]:
    """从 .vesta 模板里读 CELLP：a, b, c, alpha, beta, gamma。"""
    m = re.search(
        r"(?m)^CELLP[^\n]*\n\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)"
        r"\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)",
        text,
    )
    if not m:
        return None
    try:
        return tuple(float(g) for g in m.groups())
    except ValueError:
        return None


def _lattice_vectors(cell: tuple) -> Optional[Dict[str, tuple]]:
    """由晶胞参数算三根晶格向量的笛卡尔分量（VESTA 口径：a 沿 x、b 落 xy 面内）。"""
    if not cell:
        return None
    a, b, c, alpha, beta, gamma = cell
    al, be, ga = (math.radians(x) for x in (alpha, beta, gamma))
    sa, sb, sg = math.sin(al), math.sin(be), math.sin(ga)
    ca, cb, cg = math.cos(al), math.cos(be), math.cos(ga)
    if abs(sg) < 1e-6:
        return None
    cy = c * (ca - cb * cg) / sg
    cz2 = c * c - (c * cb) ** 2 - cy * cy
    if cz2 <= 0:
        return None
    return {
        "a": (a, 0.0, 0.0),
        "b": (b * cg, b * sg, 0.0),
        "c": (c * cb, cy, math.sqrt(cz2)),
    }


def axis_view_matrix(cell: Optional[tuple], axis: str, spec: Optional[dict] = None):
    """算某个视图的"场景矩阵" M：三个行向量 = 屏幕的 x（右）/ y（上）/ z（视线，指向屏幕外）。

    **VESTA 里实际生效的视角 = SCENE · LMATRIX**（2026-10-06 逐项实测：
    单改 LMATRIX 完全不影响画面、单改 LORIENT 只是把默认的 a*/b*/c* 换一个、
    只有 SCENE 与 LMATRIX 的乘积决定视角）。LORIENT 只是 VESTA 自己记的备注，
    所以这里不碰它 —— 写它既不改视角，动错列还会让 VESTA 段错误。
    """
    vecs = _lattice_vectors(cell) if cell else None
    if not vecs:
        return None
    spec = spec or AXIS_VIEW.get(axis) or AXIS_VIEW["a"]

    def _pick(key: str) -> Optional[tuple]:
        raw = spec.get(key)
        if raw is None:
            return None
        if isinstance(raw, str):
            return vecs.get(raw.strip().lower())
        return tuple(float(x) for x in raw)

    view = _unit(_pick("view"))
    if view is None:
        return None
    right, up = _pick("right"), _pick("up")
    if right is not None:
        # 斜晶胞里 "向右" 那根轴未必⊥视线（例如 c 视图、β≠90°）→ 先对视线正交化
        right = _orthogonal(_unit(right), view)
        up = _unit(_cross(view, right)) if right else None
    elif up is not None:
        up = _orthogonal(_unit(up), view)
        right = _unit(_cross(up, view)) if up else None
    else:
        return None
    if right is None or up is None:
        return None
    return [right, up, view]


def _parse_lmatrix(text: str) -> Optional[list]:
    """读 .vesta 的 LMATRIX 前三行（绕某个轴的旋转）；非正交矩阵就返回 None。"""
    m = re.search(
        r"(?m)^LMATRIX[^\n]*\n((?:[^\n]*\n){3})",
        text,
    )
    if not m:
        return None
    try:
        rows = [[float(x) for x in line.split()[:3]] for line in m.group(1).splitlines()]
    except (ValueError, IndexError):
        return None
    if len(rows) != 3 or any(len(r) != 3 for r in rows):
        return None
    # 只接受正交矩阵（VESTA 正常情况下写的就是单位阵）：否则不敢拿它换算
    for i in range(3):
        if abs(_dot(rows[i], rows[i]) - 1.0) > 1e-3:
            return None
    return rows


def _apply_axis_settings(
    template_text: str, axis: str, zoom: float, spec: Optional[dict] = None
) -> str:
    """改写 .vesta 模板：PROJT 缩放 + SCENE 视角（让某根晶轴指向屏幕外）。

    只替换 SCENE 的**前三行（旋转）**，第 4 行与后面 3 行小参数原样保留
    ——（2026-10-06 实测）LORIENT 段的视图中心清零会让 VESTA 段错误 / 导不出图。
    """
    text = re.sub(
        r"(?m)^PROJT\s+0\s+[-+\d.eE]+\s*$",
        f"PROJT 0  {zoom:.3f}",
        template_text,
    )
    if "PROJT" not in text:
        text += f"\nPROJT 0  {zoom:.3f}\n"

    view = axis_view_matrix(_parse_cellp(text), axis, spec)
    if view is None:
        return text  # 晶胞读不出来就保持 VESTA 默认视角，别把图搞崩

    lmat = _parse_lmatrix(text)
    if lmat is None:
        scene = view
    else:
        # SCENE = M_target · LMATRIX^T（LMATRIX 正交，转置即逆）
        scene = [
            [sum(view[i][k] * lmat[j][k] for k in range(3)) for j in range(3)]
            for i in range(3)
        ]

    lines = text.splitlines(keepends=True)
    idx = next((i for i, line in enumerate(lines) if line.rstrip("\n").strip() == "SCENE"), None)
    if idx is None or idx + 3 >= len(lines):
        return text
    rows = [
        " " + "  ".join(f"{v:.6f}" for v in scene[i]) + "  0.000000\n" for i in range(3)
    ]
    return "".join(lines[: idx + 1]) + "".join(rows) + "".join(lines[idx + 4 :])


#: 兼容旧名字（外部若还 import AXIS_VECTORS 不至于直接 ImportError）
AXIS_VECTORS = AXIS_VIEW


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


def vesta_pids_for_marker(marker: str) -> list:
    """找出"命令行里同时含 marker 和 VESTA 可执行文件"的进程（= 我们自己起的 VESTA）。

    marker 一律用**唯一的 .vesta 路径**：用户自己开的 VESTA（别的文件）不会被命中。

    两个必要条件（否则会把调用者自己杀掉 —— 2026-10-06 实测踩到：模板路径写在命令行里时
    `pgrep -f <路径>` 会匹配到本进程，SIGKILL 后主程序直接 exit 137）：
      ① 跳过本进程与父进程；② 该进程的命令行里必须出现 VESTA 可执行文件路径。
    """
    if not marker:
        return []
    try:
        out = subprocess.run(
            ["pgrep", "-f", marker], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:  # noqa: BLE001 - 没有 pgrep 就算了，不影响主流程
        return []
    self_pids = {os.getpid(), os.getppid()}
    exe = _vesta_exe()
    pids = []
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
        pids.append(pid)
    return pids


def _sweep_by_marker(marker: str) -> None:
    """兜底清理：按命令行里的**唯一标记**结束 VESTA 进程。

    VESTA 启动器会 double-fork 出 GUI 并**逃出我们的进程组**（新会话），只按 pgid kill
    会漏掉它。这里用"本次生成的临时 .vesta 路径"做标记精确匹配（路径唯一），
    **不会误伤用户自己开的 VESTA**。
    """
    for pid in vesta_pids_for_marker(marker):
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass


def _png_complete(path: Path) -> bool:
    """PNG 是否写完：末尾必须能找到 IEND 块。

    VESTA 是**边渲染边写**：文件刚出现时还是半截，太早 kill 就会留下**打不开的截断 PNG**
    （2026-10-06 实测：`images/poscar_a.png` 只写了半张，`zlib: incomplete or truncated stream`）。
    """
    try:
        if path.stat().st_size < 128:
            return False
        with open(path, "rb") as fh:
            fh.seek(-64, os.SEEK_END)
            return b"IEND" in fh.read()
    except OSError:
        return False


def _output_ready(path: Path) -> bool:
    """输出文件是否已经写完（PNG 看 IEND；其它格式只看非空）。"""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
    except OSError:
        return False
    if path.suffix.lower() == ".png":
        return _png_complete(path)
    return True


def _run_vesta_cli(
    command, expected_path: Path, wait_seconds: int = RENDER_WAIT, marker: str = ""
) -> bool:
    """后台启动 VESTA CLI，**等输出文件写完**再收尾，超时/结束后强制清理进程。

    判定"写完" = 大小连续两次没变 **且** `_output_ready()`（PNG 要有 IEND）——
    只看"文件存在且非空"会在 VESTA 还在写的时候就把它杀掉，留下截断的图。
    """
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
    last_size = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = expected_path.stat().st_size if expected_path.is_file() else 0
        except OSError:
            size = 0
        if size > 0 and size == last_size:
            stable += 1
            if stable >= 2 and _output_ready(expected_path):
                break
        else:
            stable = 0
        last_size = size
        time.sleep(0.4)
    _kill_vesta()
    _sweep_by_marker(marker)
    return _output_ready(expected_path)


# ---------------------------------------------------------------------------
# X11 窗口辅助：只给"打开窗口看结构"的模式用（渲染路径跑在 Xvfb 里，用不到）
#
# 为什么不用杀进程的方式关窗口（2026-10-06 实测踩到）：VESTA 是**单实例多窗口**——
# 后开的文件会被转发进已经在跑的那个进程，于是"杀进程"会连**用户自己开的窗口一起杀掉**；
# 而 VESTA 的 `-close <文件>` 只关文档、窗口本身留着（变成一个空白 VESTA 窗口，越关越多）。
# 正确做法是给那个窗口发 WM_DELETE_WINDOW（等价于点窗口右上角的 ×）。
# 这里用 ctypes 直接调 libX11，**不引入任何新依赖**（不需要 xdotool / python-xlib）。
# ---------------------------------------------------------------------------


class _XClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
        ("_pad", ctypes.c_long * 12),  # 撑到 XEvent 的大小
    ]


_X11_LIB = None


def _x11():
    """加载 libX11（失败返回 None，调用方按"没有 X 环境"处理）。"""
    global _X11_LIB
    if _X11_LIB is not None:
        return _X11_LIB or None
    try:
        import ctypes.util

        lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XFetchName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.POINTER(_XClientMessage),
        ]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _X11_LIB = lib
    except Exception:  # noqa: BLE001 - 没装/加载不了就当没有
        _X11_LIB = False
    return _X11_LIB or None


def _x11_children(dpy, win) -> list:
    lib = _x11()
    root_ret, parent_ret = ctypes.c_ulong(), ctypes.c_ulong()
    kids = ctypes.POINTER(ctypes.c_ulong)()
    n = ctypes.c_uint()
    if not lib.XQueryTree(dpy, win, ctypes.byref(root_ret), ctypes.byref(parent_ret),
                          ctypes.byref(kids), ctypes.byref(n)):
        return []
    try:
        return [kids[i] for i in range(n.value)]
    finally:
        if kids:
            lib.XFree(kids)


def _x11_title(dpy, win) -> str:
    lib = _x11()
    name = ctypes.c_char_p()
    if lib.XFetchName(dpy, win, ctypes.byref(name)) and name.value:
        title = name.value.decode("utf-8", "replace")
        lib.XFree(name)
        return title
    return ""


def list_x_windows(titles: Optional[set] = None) -> list:
    """列出当前 DISPLAY 上的窗口 (window_id, 标题)；给了 titles 就只返回标题命中的。"""
    lib = _x11()
    if lib is None:
        return []
    dpy = lib.XOpenDisplay(None)
    if not dpy:
        return []
    found, stack = [], [lib.XDefaultRootWindow(dpy)]
    try:
        while stack:
            win = stack.pop()
            title = _x11_title(dpy, win)
            if title and (titles is None or title in titles):
                found.append((win, title))
            stack.extend(_x11_children(dpy, win))
    finally:
        lib.XCloseDisplay(ctypes.c_void_p(dpy))
    return found


def close_x_windows(titles: set) -> list:
    """给标题命中的窗口发 WM_DELETE_WINDOW（= 点右上角 ×），返回 (window_id, 标题) 列表。

    只关这些窗口，**不动 VESTA 进程**，所以同一个 VESTA 进程里用户自己开的窗口不受影响。
    """
    lib = _x11()
    if lib is None or not titles:
        return []
    dpy = lib.XOpenDisplay(None)
    if not dpy:
        return []
    wm_protocols = lib.XInternAtom(dpy, b"WM_PROTOCOLS", 0)
    wm_delete = lib.XInternAtom(dpy, b"WM_DELETE_WINDOW", 0)
    closed = []
    try:
        for win, title in list_x_windows(titles):
            ev = _XClientMessage()
            ev.type = 33  # ClientMessage
            ev.send_event = 1
            ev.display = ctypes.c_void_p(dpy)
            ev.window = win
            ev.message_type = wm_protocols
            ev.format = 32
            ev.data[0] = wm_delete
            ev.data[1] = 0  # CurrentTime
            lib.XSendEvent(dpy, win, 0, 0, ctypes.byref(ev))
            closed.append((win, title))
        lib.XFlush(dpy)
    finally:
        lib.XCloseDisplay(ctypes.c_void_p(dpy))
    return closed


def vesta_window_titles(vesta_paths) -> set:
    """我们生成的 .vesta 在 VESTA 窗口标题里的样子：`<文件名> - VESTA`。"""
    return {f"{Path(p).name} - VESTA" for p in vesta_paths}


def _build_vesta_template(
    structure_path: Path, work_dir: Path, wait_seconds: int = RENDER_WAIT
) -> Optional[Path]:
    """调用 VESTA 由结构文件生成基础 .vesta 模板；失败返回 None。

    `wait_seconds` 可放宽：体积文件（CHGCAR_diff）比 POSCAR 大几个数量级，加载更慢。
    """
    template_path = work_dir / f"_temp_{structure_path.stem}.vesta"
    ok = _run_vesta_cli(
        [_vesta_exe(), "-open", str(structure_path), "-save", str(template_path), "-close", ""],
        template_path,
        wait_seconds=wait_seconds,
        marker=str(template_path),
    )
    return template_path if ok else None


def _render_axis(
    work_dir: Path,
    template_text: str,
    axis: str,
    zoom: float,
    png_path: Path,
    wait_seconds: int = RENDER_WAIT,
) -> bool:
    """修改 SCENE/PROJT 后用 VESTA 导出单轴 PNG（默认 2 倍分辨率，见 `_vesta_image_scale`）。"""
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
            f"scale={_vesta_image_scale()}",
            "-close",
            str(custom_vesta),
        ],
        png_path,
        wait_seconds=wait_seconds,
        marker=str(custom_vesta),
    )
    if not ok:
        png_path.unlink(missing_ok=True)
    return ok


def structure_image_dir(project: Dict[str, Any], task: Dict[str, Any]) -> Path:
    """结构图输出目录：**与任务目录里的 files/ 同级**的 images/。

    即 `<任务目录>/images/`（不是 reports/ 下面）：和 `files/` 平级，报告生成直接取这里的图。
    用 `task_dir` 而不是 `task_files_dir` 拼 —— 后者在没有 files/ 的老任务上会退化成任务目录本身。
    """
    return task_dir(project["name"], task) / "images"


def _cache_version_file(image_dir: Path) -> Path:
    return image_dir / ".view_version"


def _cache_is_current(image_dir: Path) -> bool:
    """缓存是否由当前视角定义（VIEW_VERSION）画出。"""
    try:
        return _cache_version_file(image_dir).read_text(encoding="utf-8").strip() == str(
            VIEW_VERSION
        )
    except OSError:
        return False


def _mark_cache(image_dir: Path) -> None:
    try:
        _cache_version_file(image_dir).write_text(f"{VIEW_VERSION}\n", encoding="utf-8")
    except OSError:
        pass


def _volume_version_file(image_dir: Path) -> Path:
    return image_dir / ".volume_version"


def _volume_cache_is_current(image_dir: Path) -> bool:
    """体积图是不是用当前口径画出来的（口径变了就整批重画，避免复用旧格式的图）。"""
    try:
        return _volume_version_file(image_dir).read_text(encoding="utf-8").strip() == str(
            VOLUME_RENDER_VERSION
        )
    except OSError:
        return False


def _mark_volume_cache(image_dir: Path) -> None:
    try:
        _volume_version_file(image_dir).write_text(
            f"{VOLUME_RENDER_VERSION}\n", encoding="utf-8"
        )
    except OSError:
        pass


#: NEB 映像图存放：`<任务目录>/images/<映像号>/{a,b,c}.png`
NEB_IMAGE_SUBDIR = "[0-9]*"


def neb_image_dir(image_dir: Path, label: str) -> Path:
    return image_dir / str(label)


def neb_image_paths(image_dir: Path, label: str) -> Dict[str, Path]:
    return {axis: neb_image_dir(image_dir, label) / f"{axis}.png" for axis in ("a", "b", "c")}


def volume_image_paths(
    image_dir: Path, label: str, axes: Sequence[str] = ("a", "b", "c")
) -> Dict[str, Path]:
    """体积图（差分电荷等）路径：`<image_dir>/<label>_{a,b,c}.png`。"""
    return {axis: image_dir / f"{label}_{axis}.png" for axis in axes}


def _cell_params_from_volume(
    path: Path,
) -> Optional[Tuple[float, float, float, float, float, float]]:
    """从 VASP 体积文件（CHGCAR / CHG / LOCPOT…）头部读晶胞参数 (a,b,c,α,β,γ)。

    体积文件与 POSCAR 共用头部（标题 / 缩放系数 / 3 条晶格向量 / 元素行…），
    **只读前 5 行**（文件 200MB+，不能整读）。
    为什么不先让 VESTA 存一份模板再读 CELLP：模板路径会走 `IMPORT_DENSITY`，
    密度归一化与直接打开不同、等值面层级对不上（见 `render_volume_axes`）。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = [fh.readline() for _ in range(5)]
    except OSError:
        return None
    if len(head) < 5:
        return None
    try:
        scale = float(head[1].split()[0])
        vecs = [[float(x) * scale for x in head[i].split()[:3]] for i in (2, 3, 4)]
    except (IndexError, ValueError):
        return None
    if any(len(v) != 3 for v in vecs):
        return None
    va, vb, vc = vecs

    def _norm(v) -> float:
        return math.sqrt(sum(x * x for x in v))

    la, lb, lc = _norm(va), _norm(vb), _norm(vc)
    if min(la, lb, lc) <= 0:
        return None

    def _angle(u, v) -> float:
        cos = sum(x * y for x, y in zip(u, v)) / (_norm(u) * _norm(v))
        return math.degrees(math.acos(max(-1.0, min(1.0, cos))))

    return (la, lb, lc, _angle(vb, vc), _angle(va, vc), _angle(va, vb))


def _rotation_angles(view: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    """把目标场景矩阵分解成 VESTA 的 `-rotate_x/-rotate_y/-rotate_z` 角度（度）。

    实测口径（2026-10-14，真机 VESTA 3.5.4 逐项对过）：
    - 直接 `-open <体积文件>` 后 SCENE = 单位阵（= 默认视角）；
    - `-rotate_x 90` → SCENE = [[1,0,0],[0,0,-1],[0,1,0]]（标准 Rx(90°)），y / z 同理；
    - 多个 `-rotate_*` 按命令行顺序**左乘** → R = Rz(c)·Ry(b)·Rx(a)。
    这里就按 R = Rz·Ry·Rx 反解，与命令里 x、y、z 的书写顺序一致。
    """
    r = [[float(view[i][j]) for j in range(3)] for i in range(3)]
    beta = math.asin(max(-1.0, min(1.0, -r[2][0])))
    if abs(math.cos(beta)) < 1e-8:
        alpha = 0.0
        gamma = math.atan2(-r[0][1], r[1][1])
    else:
        alpha = math.atan2(r[2][1], r[2][2])
        gamma = math.atan2(r[1][0], r[0][0])
    return (math.degrees(alpha), math.degrees(beta), math.degrees(gamma))


def render_volume_axes(
    structure_path: Path,
    image_dir: Path,
    label: str = "chgdiff",
    force: bool = False,
    axes: Sequence[str] = ("a", "b", "c"),
    wait_seconds: int = VOLUME_RENDER_WAIT,
) -> Dict[str, Any]:
    """用 VESTA 把**体积文件**（CHGCAR_diff 等）导出 a / b / c 三轴 PNG。

    **不走模板**（2026-10-14 修正，关键）：`-open <体积文件>` 时 VESTA 会按默认层级
    自动生成等值面；而"存模板 → 重开模板"会走 `IMPORT_DENSITY` 重新导入密度，
    归一化不同（VASP CHGCAR 的值要除以晶胞体积）→ 等值面层级对不上，
    分子那侧的瓣会整块消失（实测：只剩最靠近衬底的那层）。所以这里**直接打开体积文件**，
    再用 `-rotate_x/-rotate_y/-rotate_z` 把它转到 `AXIS_VIEW` 定义的目标轴向
    （角度由 `_rotation_angles` 反解），最后 `-export_img`。

    - 输出：`<image_dir>/<label>_{a,b,c}.png`，**同名覆盖**；
    - 缓存：`force=False` 时"图比源文件新且 PNG 完整（有 IEND）"就复用，连 VESTA 都不启动；
    - 取景：用 VESTA 默认缩放（与手动导入一致）；结构图那条路径仍用 `vesta_zoom`（1.7）；
    - 串行：整个渲染持有 `vesta_render_lock()`（**跨进程**）—— 百 MB 体积数据一次渲染
      要几百 MB 内存，禁止和结构图渲染同时开 VESTA（2026-10-14 用户要求避免卡死）。

    返回 `{"images": {axis: 路径}, "warnings": [...], "skipped": str|None}`。
    """
    warnings: List[str] = []
    if not structure_path.is_file() or structure_path.stat().st_size == 0:
        return {"images": {}, "warnings": warnings, "skipped": f"源文件不存在：{structure_path}"}
    cell = _cell_params_from_volume(structure_path)
    if cell is None:
        return {
            "images": {},
            "warnings": warnings + ["体积文件头部读不出晶胞参数（不是 VASP 体积文件？）"],
            "skipped": "晶胞参数读取失败",
        }
    image_dir.mkdir(parents=True, exist_ok=True)
    paths = volume_image_paths(image_dir, label, axes)
    images: Dict[str, str] = {}
    with vesta_render_lock():
        # 出图口径变过（如 v0.9.48 改了等值面渲染方式）→ 旧图整批作废，别让界面拿到旧格式
        if not _volume_cache_is_current(image_dir):
            for axis in axes:
                paths[axis].unlink(missing_ok=True)
            warnings.append(
                f"体积图渲染口径已更新（v{VOLUME_RENDER_VERSION}），旧图作废重画"
            )
        if (not force) and all(
            _image_is_fresh(paths[axis], structure_path) for axis in axes
        ):
            return {
                "images": {axis: str(paths[axis]) for axis in axes},
                "warnings": warnings,
                "skipped": None,
            }
        for axis in axes:
            png_path = paths[axis]
            if (not force) and _image_is_fresh(png_path, structure_path):
                images[axis] = str(png_path)
                continue
            view = axis_view_matrix(cell, axis)
            if view is None:
                warnings.append(f"{axis} 轴视角矩阵算不出来（晶胞退化？）")
                continue
            ax, ay, az = _rotation_angles(view)
            ok = _run_vesta_cli(
                [
                    _vesta_exe(),
                    "-open",
                    str(structure_path),
                    "-rotate_x",
                    f"{ax:.6f}",
                    "-rotate_y",
                    f"{ay:.6f}",
                    "-rotate_z",
                    f"{az:.6f}",
                    "-flush",
                    "-export_img",
                    str(png_path),
                    f"scale={_vesta_image_scale()}",
                    "-close",
                    str(structure_path),
                ],
                png_path,
                wait_seconds=wait_seconds,
                marker=str(structure_path),
            )
            if ok:
                images[axis] = str(png_path)
            else:
                warnings.append(f"{axis} 轴导出失败")
    if images:
        _mark_volume_cache(image_dir)
    return {
        "images": images,
        "warnings": warnings,
        "skipped": None if images else "全部导出失败",
    }


def render_neb_images(
    project: Dict[str, Any],
    task: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    """渲染 NEB 各映像三视图；实现见 `_render_neb_images_locked`（串行化，同上）。"""
    with vesta_render_lock():
        return _render_neb_images_locked(project, task, force=force)


def _render_neb_images_locked(
    project: Dict[str, Any],
    task: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    """渲染 NEB 各映像的 a/b/c 三视图 PNG（报告弹窗用）。

    结构取 `files/<映像号>/CONTCAR`，端点（最小/最大编号）没有 CONTCAR 时退回 POSCAR
    —— 和巡检同步 CIF 的口径一致（`inspection_runner._sync_neb_image_structures`）。
    图写到 `<任务目录>/images/<映像号>/{a,b,c}.png`，**同名覆盖**；
    默认"图比结构文件新就复用"，`force=True` 或 `VIEW_VERSION` 变了就重画。
    """
    task_id = task.get("task_id")
    files_dir = task_files_dir(project["name"], task)
    image_dir = structure_image_dir(project, task)
    image_dir.mkdir(parents=True, exist_ok=True)
    warnings: List[str] = []
    rendered: Dict[str, Dict[str, str]] = {}

    if force or not _cache_is_current(image_dir):
        for old in image_dir.glob(f"{NEB_IMAGE_SUBDIR}/[abc].png"):
            old.unlink(missing_ok=True)
        if not _cache_is_current(image_dir):
            warnings.append(f"视角定义已更新（v{VIEW_VERSION}），旧结构图作废重画")

    # 映像编号：优先 files/ 下的数字子目录（归档同步下来的），没有再翻 NEB 输入目录
    labels = sorted(
        {p.name for p in files_dir.glob(NEB_IMAGE_SUBDIR) if p.is_dir() and p.name.isdigit()},
        key=int,
    )
    if not labels:
        return {
            "task_id": task_id,
            "images": {},
            "warnings": warnings + ["没有找到 NEB 映像目录（files/<映像号>/）"],
        }
    first, last = labels[0], labels[-1]

    zoom = _vesta_zoom()
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        for label in labels:
            src_dir = files_dir / label
            structure = src_dir / "CONTCAR"
            if not structure.is_file() or structure.stat().st_size == 0:
                # 端点没有 CONTCAR（POSCAR 就是优化后的初/末态）；中间映像缺 CONTCAR 直接跳过
                if label in (first, last) and (src_dir / "POSCAR").is_file():
                    structure = src_dir / "POSCAR"
                else:
                    warnings.append(f"映像 {label} 缺 CONTCAR，跳过")
                    continue
            paths = neb_image_paths(image_dir, label)
            fresh = (not force) and all(
                _image_is_fresh(paths[axis], structure) for axis in ("a", "b", "c")
            )
            if fresh:
                rendered[label] = {axis: str(paths[axis]) for axis in ("a", "b", "c")}
                continue
            template = _build_vesta_template(structure, work_dir)
            if template is None:
                warnings.append(f"映像 {label} VESTA 模板生成失败（检查 vesta_path 配置）")
                continue
            template_text = template.read_text(encoding="utf-8", errors="replace")
            got: Dict[str, str] = {}
            for axis in ("a", "b", "c"):
                png_path = paths[axis]
                png_path.parent.mkdir(parents=True, exist_ok=True)
                if _image_is_fresh(png_path, structure) and not force:
                    got[axis] = str(png_path)
                    continue
                if _render_axis(work_dir, template_text, axis, zoom, png_path):
                    got[axis] = str(png_path)
                else:
                    warnings.append(f"映像 {label} {axis} 轴渲染失败")
            if got:
                rendered[label] = got

    _mark_cache(image_dir)
    return {"task_id": task_id, "images": rendered, "warnings": warnings}


def _drop_stale_cache(image_dir: Path) -> None:
    """视角定义变了：清掉旧图，否则只按"文件在不在"判断的缓存永远不会重画。"""
    for label in ("poscar", "contcar"):
        for axis in ("a", "b", "c"):
            (image_dir / f"{label}_{axis}.png").unlink(missing_ok=True)


def _image_is_fresh(png: Path, structure: Path) -> bool:
    """图已存在、比结构文件新、而且**是完整的图** → 可以直接用。"""
    try:
        return (
            png.is_file()
            and png.stat().st_size > 0
            and png.stat().st_mtime >= structure.stat().st_mtime
            and _output_ready(png)  # 截断的旧图（VESTA 被杀太早）要重画
        )
    except OSError:
        return False


def render_task(
    project: Dict[str, Any],
    task: Dict[str, Any],
    steps: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """渲染任务结构三视图（POSCAR/CONTCAR）；实现见 `_render_task_locked`。

    这里只多做一件事：**串行化**（`vesta_render_lock()`，跨进程）—— 与差分电荷体积图
    渲染互斥，避免两个 VESTA 同时吃内存把生产机拖卡。
    """
    with vesta_render_lock():
        return _render_task_locked(project, task, steps=steps, force=force)


def _render_task_locked(
    project: Dict[str, Any],
    task: Dict[str, Any],
    steps: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """渲染单个任务的 a/b/c 轴 POSCAR/CONTCAR 对比图，写进 `<任务目录>/images/`。

    - 结构读 `files/POSCAR`、`files/CONTCAR`（缺一个就直接跳过，不报错）；
    - 输出 `<任务目录>/images/{poscar,contcar}_{a,b,c}.png`，**同名覆盖**，不产生历史副本；
    - `force=False`（默认）时，图比结构文件新就直接复用（省 6 次 VESTA 启动）；
      结构更新过 / 视角定义变了（`VIEW_VERSION`）/ `force=True` 都会重新画并覆盖。

    返回 {"task_id", "steps", "images": {"poscar": {...}, "contcar": {...}}, "warnings", "skipped"}。
    报告生成以后直接调这个函数即可（调用方负责在 xvfb 里跑，见 DEPENDENCIES.md §3b）。
    """
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

    image_dir = structure_image_dir(project, task)
    image_dir.mkdir(parents=True, exist_ok=True)
    version_ok = _cache_is_current(image_dir)
    if force or not version_ok:
        _drop_stale_cache(image_dir)
    if not version_ok:
        warnings.append(f"视角定义已更新（v{VIEW_VERSION}），旧结构图作废重画")
    zoom = _vesta_zoom()
    images: Dict[str, Dict[str, str]] = {"poscar": {}, "contcar": {}}

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        for label, structure_path in (("poscar", poscar), ("contcar", contcar)):
            # 六张图都比结构文件新 → 整批跳过（连 VESTA 都不启动）
            if all(
                _image_is_fresh(image_dir / f"{label}_{axis}.png", structure_path)
                for axis in ("a", "b", "c")
            ):
                images[label] = {
                    axis: str(image_dir / f"{label}_{axis}.png") for axis in ("a", "b", "c")
                }
                continue
            template = _build_vesta_template(structure_path, work_dir)
            if template is None:
                warnings.append(f"{label} VESTA 模板生成失败（检查 vesta_path 配置）")
                continue
            template_text = template.read_text(encoding="utf-8", errors="replace")
            for axis in ("a", "b", "c"):
                png_path = image_dir / f"{label}_{axis}.png"
                if _image_is_fresh(png_path, structure_path):
                    # 结构没更新过 → 复用（否则每次报告都重画 6 张）
                    images[label][axis] = str(png_path)
                    continue
                if _render_axis(work_dir, template_text, axis, zoom, png_path):
                    images[label][axis] = str(png_path)
                else:
                    warnings.append(f"{label} {axis} 轴渲染失败")

    _mark_cache(image_dir)
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
