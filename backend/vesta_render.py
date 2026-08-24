"""VESTA 结构渲染（供巡检详情结构分析使用，适配 web 系统）。

按 a/b/c 晶轴渲染 POSCAR/CONTCAR 的 PNG 对比图；VESTA 缺失/执行异常
仅记录警告并返回 skipped，不影响巡检主流程。渲染结果缓存到任务
reports/structure/ 目录，重复打开详情不再重新渲染。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import PROJECTS_DIR, load_settings

#: 各晶轴视图向量：(水平向量 v1, 垂直向量 v2)
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


def _vesta_zoom() -> float:
    settings = load_settings()
    try:
        return float(settings.get("vesta_zoom", 1.7))
    except (TypeError, ValueError):
        return 1.7


def _apply_axis_settings(template_text: str, axis: str, zoom: float) -> str:
    """替换 .vesta 中的 PROJT 缩放比例与 LORIENT 视角矩阵。"""
    text = re.sub(
        r"(?m)^PROJT\s+0\s+[-+\d.eE]+\s*$",
        f"PROJT 0  {zoom:.3f}",
        template_text,
    )
    if "PROJT" not in text:
        text += f"\nPROJT 0  {zoom:.3f}\n"

    v1, v2 = AXIS_VECTORS[axis]
    row1 = f" {v1[0]:.6f}  {v1[1]:.6f}  {v1[2]:.6f}  0.000000  0.000000  0.000000\n"
    row2 = f" {v2[0]:.6f}  {v2[1]:.6f}  {v2[2]:.6f}  0.000000  0.000000  0.000000\n"

    lines = text.splitlines(keepends=True)
    lorient_idx = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n").strip() == "LORIENT"),
        None,
    )
    if lorient_idx is not None and lorient_idx + 4 <= len(lines):
        new_text = (
            "".join(lines[: lorient_idx + 2]) + row1 + row2 + "".join(lines[lorient_idx + 4 :])
        )
    else:
        new_text = (
            text
            + f"\nLORIENT\n 1.000000  0.000000  0.000000  0.000000  0.000000  0.000000\n{row1}{row2}"
        )
    return new_text


def _kill_vesta() -> None:
    """强制结束所有 VESTA 进程（Windows taskkill），防止 GUI 卡死残留。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/IM", "VESTA.exe", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
    except Exception:  # noqa: BLE001 - 清理失败不影响主流程
        pass


def _run_vesta_cli(command, expected_path: Path, wait_seconds: int = RENDER_WAIT) -> bool:
    """后台启动 VESTA CLI，轮询输出文件生成，超时/结束后强制清理进程。"""
    _kill_vesta()
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - VESTA 不可用
        return False
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if expected_path.is_file() and expected_path.stat().st_size > 0:
            break
        time.sleep(0.5)
    _kill_vesta()
    return expected_path.is_file() and expected_path.stat().st_size > 0


def _build_vesta_template(structure_path: Path, work_dir: Path) -> Optional[Path]:
    """调用 VESTA 由结构文件生成基础 .vesta 模板；失败返回 None。"""
    template_path = work_dir / f"_temp_{structure_path.stem}.vesta"
    ok = _run_vesta_cli(
        [_vesta_exe(), "-open", str(structure_path), "-save", str(template_path), "-close", ""],
        template_path,
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
    files_dir = (
        PROJECTS_DIR
        / project["name"]
        / task["task_type"]
        / task["model_name"]
        / "files"
    )
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
