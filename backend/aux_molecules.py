"""辅助分子全局统一存储（跨项目共享，能量固定复用）。

辅助分子不属于任何项目：文件固定在 <数据根>/aux_molecules/<标签>/opt|frac/，
注册表为 <数据根>/aux_molecules.json。自由能组通过组元数据引用辅助分子标签，
报告聚合时从全局存储读取能量（含 ZPE/矫正占位）。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR, load_task_registry
from dates import now_iso

AUX_DIR = DATA_DIR / "aux_molecules"
REGISTRY_FILE = DATA_DIR / "aux_molecules.json"
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_@]*$")


def _load_registry() -> Dict[str, Any]:
    if not REGISTRY_FILE.is_file():
        return {"molecules": []}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"molecules": []}


def _save_registry(data: Dict[str, Any]) -> None:
    AUX_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_aux_molecules() -> List[Dict[str, Any]]:
    """辅助分子列表（dir/opt_dir/frac_dir 统一还原成**当前机器的绝对路径**）。

    注册表里存的是相对数据根的路径（v0.8.3 起），老数据里可能是 Windows 绝对路径，
    这里统一解析：绝对路径直接用、相对路径按 DATA_DIR 拼接、Windows 盘符残留按标签重建。
    """
    return [_resolve_entry(m) for m in _load_registry().get("molecules", [])]


def _resolve_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """把注册表条目的路径字段解析成本机绝对路径。"""
    item = dict(entry)
    label = str(entry.get("label") or "")
    root = AUX_DIR / label
    for key, default in (("dir", root), ("opt_dir", root / "opt"), ("frac_dir", root / "frac")):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            item[key] = str(default)
            continue
        candidate = Path(raw)
        # Windows 盘符/反斜杠残留（旧数据）→ 丢弃，按标签重建
        if re.match(r"^[A-Za-z]:[\\/]", raw) or "\\" in raw:
            item[key] = str(default)
            continue
        item[key] = str(candidate if candidate.is_absolute() else DATA_DIR / candidate)
    return item


def get_aux(label: str) -> Optional[Dict[str, Any]]:
    for m in list_aux_molecules():
        if m.get("label") == label:
            return m
    return None


def _write_default_inputs(task_path: Path, task_type: str) -> None:
    registry = load_task_registry()
    cfg = registry.get(task_type, {})
    params = dict(cfg.get("default_incar", {}))
    if params:
        width = max(len(str(k)) for k in params)
        text = "\n".join(f"{str(k).ljust(width + 2)}= {v}" for k, v in params.items())
        (task_path / "INCAR").write_text(text + "\n", encoding="utf-8")
    (task_path / "KPOINTS").write_text(
        "Automatic mesh\n0\nGamma\n4 4 4\n0 0 0\n",
        encoding="utf-8",
    )


def add_aux_molecule(label: str) -> Dict[str, Any]:
    """新增辅助分子：创建 opt/frac 目录与默认输入文件，写入全局注册表。"""
    if not LABEL_PATTERN.fullmatch(label):
        raise ValueError("辅助分子标签仅支持字母、数字、下划线、@")
    if get_aux(label) is not None:
        raise ValueError(f"辅助分子 {label} 已存在")
    root = AUX_DIR / label
    for role in ("opt", "frac"):
        task_path = root / role
        (task_path / "files").mkdir(parents=True, exist_ok=True)
        _write_default_inputs(task_path, role)
    entry = {
        "label": label,
        # 路径存**相对数据根**的形式（跨机器迁移后仍然有效）；
        # 读取时用 aux_paths() 还原成绝对路径
        "dir": f"aux_molecules/{label}",
        "opt_dir": f"aux_molecules/{label}/opt",
        "frac_dir": f"aux_molecules/{label}/frac",
        "energy": None,
        "zpe": None,
        "correction": None,
        "status": "pending",
        "created_at": now_iso(),
    }
    data = _load_registry()
    data.setdefault("molecules", []).append(entry)
    _save_registry(data)
    return entry
