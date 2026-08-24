"""运行时依赖检查：后台执行，缺失时提示安装命令。"""

import importlib.util
from typing import Dict, List

INSTALL_HINT = "pip install -r requirements.txt"

REQUIRED_DEPS = [
    {"name": "fastapi", "purpose": "Web API 框架"},
    {"name": "uvicorn", "purpose": "ASGI 服务器"},
    {"name": "paramiko", "purpose": "SSH 远程目录同步"},
]

OPTIONAL_DEPS = [
    {"name": "pymatgen", "purpose": "VASP 输入文件生成（后续自动导入）"},
    {"name": "ase", "purpose": "原子结构建模（后续）"},
    {"name": "apscheduler", "purpose": "定时巡检调度（后续）"},
    {"name": "openai", "purpose": "大模型报告生成（后续）"},
]


def check_dependencies() -> List[Dict[str, object]]:
    result = []
    for item in REQUIRED_DEPS + OPTIONAL_DEPS:
        result.append(
            {
                "name": item["name"],
                "purpose": item["purpose"],
                "required": item in REQUIRED_DEPS,
                "installed": importlib.util.find_spec(item["name"]) is not None,
            }
        )
    return result


def missing_dependencies() -> List[Dict[str, object]]:
    return [d for d in check_dependencies() if not d["installed"]]
