"""统一启动入口：python backend/run.py [--data-dir <数据根目录>]

- 默认数据目录：项目下 data/（已迁移真实数据，自包含）
- 指定其他数据目录（测试隔离 / 其他机器部署）：
    python backend/run.py --data-dir D:\\path\\to\\data
- 端口可用 PORT 环境变量覆盖，默认 3001。
"""

import argparse
import os
import sys

parser = argparse.ArgumentParser(description="VASP 项目管理系统后端")
parser.add_argument(
    "--data-dir",
    default=None,
    help="数据根目录（含 projects.json / config / projects / backups）",
)
args = parser.parse_args()
if args.data_dir:
    os.environ["VASP_WEB_DATA_DIR"] = os.path.abspath(args.data_dir)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

from main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "3001")),
        log_level="info",
    )
