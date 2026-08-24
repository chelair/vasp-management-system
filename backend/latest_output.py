"""任务最新输出目录定位：优先续算目录 conN，否则回退主目录。

约定：任务目录下形如 con1/con2/... 的子目录为续算目录。
算法（与巡检需求一致）：
1. 列出所有 ^con\\d+$ 子目录，按编号降序；
2. 从最大编号开始，若该目录 OUTCAR 末尾含正常结束标志，则取为 latest_dir 并停止；
3. 全部 con* 均不正常时回退主目录；
4. 输出 current_output：contcar/outcar/oszicar 路径与状态。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SUCCESS_MARKERS = (
    "General timing and accounting informations for this job",
    "reached required accuracy",
)
ERROR_KEYWORDS = ("EEEE", "Error", "Segmentation fault", "forrtl: severe")
CON_DIR_RE = re.compile(r"^con(\d+)$")


def ends_normally(outcar: Path) -> bool:
    """OUTCAR 末尾是否包含正常结束标志。"""
    if not outcar.is_file():
        return False
    try:
        tail = outcar.read_text(encoding="utf-8", errors="replace")[-8192:]
    except OSError:
        return False
    return any(marker in tail for marker in SUCCESS_MARKERS)


def list_con_dirs(task_dir: Path) -> List[Path]:
    """按编号升序返回任务目录下的 conN 子目录。"""
    if not task_dir.is_dir():
        return []
    cons = [
        p for p in task_dir.iterdir() if p.is_dir() and CON_DIR_RE.fullmatch(p.name)
    ]
    return sorted(cons, key=lambda p: int(CON_DIR_RE.fullmatch(p.name).group(1)))


def find_latest_output(task_dir: Path) -> Dict[str, Any]:
    """定位最新输出目录，返回 current_output 信息。"""
    cons = list_con_dirs(task_dir)
    latest: Optional[Path] = None
    for con in reversed(cons):
        if ends_normally(con / "OUTCAR"):
            latest = con
            break

    output_dir = latest or task_dir
    outcar = output_dir / "OUTCAR"
    oszicar = output_dir / "OSZICAR"
    contcar = output_dir / "CONTCAR"

    status, reason = "waiting", "无输出文件"
    if outcar.is_file():
        try:
            text = outcar.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if any(marker in text for marker in SUCCESS_MARKERS):
            status, reason = "finished", "正常结束"
        elif any(keyword in text for keyword in ERROR_KEYWORDS):
            status, reason = "failed", "输出包含错误关键字"
        else:
            status, reason = "running", "OUTCAR 存在但未见结束标记"

    return {
        "latest_dir": latest.name if latest else None,
        "dir": str(output_dir),
        "contcar_path": str(contcar),
        "outcar_path": str(outcar),
        "oszicar_path": str(oszicar),
        "status": status,
        "reason": reason,
        "is_continuation": bool(latest),
        "is_latest_con": bool(latest) and latest == cons[-1] if cons else False,
    }
