"""POSCAR/CONTCAR → CIF 转换（vasp2cif 脚本封装）。

规则：
- 本地已有 CIF 直接用；
- 没有 CIF 但本地有 POSCAR/CONTCAR 源文件时，用脚本转换补缺（不覆盖已有 CIF）；
- 巡检触发产生新结构结果时主动转换并**覆盖**旧 CIF；
- 转换先写临时文件、成功后再原子替换：失败时旧 CIF 原样保留（保留上次结果）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

VASP2CIF_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vasp2cif.py"


def convert_structure_to_cif(src: Path, out: Path, overwrite: bool = False) -> bool:
    """用 vasp2cif 把结构文件转为 CIF；成功返回 True。

    - 已有非空 CIF 且不强制覆盖 → 直接返回 True（有 CIF 就用 CIF）；
    - 转换先写 <out>.tmp，成功后再 os.replace 原子覆盖，失败清理临时文件，
      旧 CIF（若有）保持原样。
    """
    if out.is_file() and out.stat().st_size > 0 and not overwrite:
        return True
    if not src.is_file() or src.stat().st_size == 0:
        return False
    tmp = out.with_name(out.name + ".tmp")
    try:
        proc = subprocess.run(
            [sys.executable, str(VASP2CIF_SCRIPT), "-o", str(tmp), str(src)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return True
        return False
    except Exception:
        return False
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def structure_report_dir(project: Dict[str, Any], task: Dict[str, Any]) -> Path:
    """结构 CIF 输出目录：<任务目录>/reports/structure/。"""
    from task_paths import task_files_dir

    files_dir = task_files_dir(project["name"], task)
    return files_dir.parent / "reports" / "structure"


def read_or_convert_cif(
    project: Dict[str, Any], task: Dict[str, Any], label: str
) -> Optional[str]:
    """读取结构 CIF 文本；缺失时若本地有源文件则就地转换补缺。

    只补缺、不覆盖已有 CIF（避免详情展示把巡检新结果之外的旧结果冲掉）。
    """
    report_dir = structure_report_dir(project, task)
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"{label}.cif"
    if out.is_file() and out.stat().st_size > 0:
        return out.read_text(encoding="utf-8", errors="replace")

    from task_paths import task_files_dir

    src = task_files_dir(project["name"], task) / label
    if src.is_file() and src.stat().st_size > 0:
        if convert_structure_to_cif(src, out):
            return out.read_text(encoding="utf-8", errors="replace")
    return None
