"""路径与配置加载（文件型存储，数据目录与前端约定一致）。"""

import json
import os
import shutil
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent

# 数据根目录（可用环境变量 VASP_WEB_DATA_DIR 覆盖，便于测试隔离）
DATA_DIR = Path(os.environ.get("VASP_WEB_DATA_DIR", str(PROJECT_ROOT / "data")))
CONFIG_DIR = DATA_DIR / "config"
PROJECTS_DIR = DATA_DIR / "projects"
BACKUPS_DIR = DATA_DIR / "backups"
DEFAULTS_DIR = SERVER_DIR / "defaults"

DEFAULT_CONFIG_FILES = (
    "servers.json",
    "settings.json",
    "task_registry.json",
    "path_mapping.json",
    "report_rules.json",
)


def ensure_data_dirs() -> None:
    """初始化数据目录；缺少 config 文件时从 defaults 复制。"""
    for directory in (CONFIG_DIR, PROJECTS_DIR, BACKUPS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    for name in DEFAULT_CONFIG_FILES:
        target = CONFIG_DIR / name
        if not target.exists():
            shutil.copyfile(DEFAULTS_DIR / name, target)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_servers() -> dict:
    return load_json(CONFIG_DIR / "servers.json")


def load_settings() -> dict:
    return load_json(CONFIG_DIR / "settings.json")


def save_settings(patch: dict) -> dict:
    """合并写入 settings.json（原子替换），返回写入后的完整配置。"""
    ensure_data_dirs()
    path = CONFIG_DIR / "settings.json"
    current = load_json(path) if path.is_file() else {}
    current.update(patch or {})
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
    return current


def load_task_registry() -> dict:
    return load_json(CONFIG_DIR / "task_registry.json")


def load_path_mapping() -> dict:
    """本地/远端路径一一对应关系（固化在 data/config/path_mapping.json）。"""
    path = CONFIG_DIR / "path_mapping.json"
    if path.is_file():
        try:
            data = load_json(path)
            if (
                isinstance(data, dict)
                and data.get("local_root")
                and isinstance(data.get("remote_roots"), dict)
            ):
                return data
        except Exception:
            pass
    return {
        "local_root": str(PROJECTS_DIR),
        "remote_roots": {
            name: cfg.get("remote_base", "")
            for name, cfg in load_servers().items()
        },
    }
