"""自动/定时执行动作系统（v0.9.6）。

层次：触发层（事件 / 定时）→ 规则层 → 调度层 → 执行层 → 审计层。

- `events.py`：事件总线（巡检完成发事件，不在巡检里调动作）
- `rules.py`：规则加载与条件匹配（`data/config/rules/*.json`，一文件一规则）
- `scheduler.py`：队列 / 并发控制（任务级锁、冷却、执行上限、幂等指纹）/ 长动作 run
- `actions.py`：动作目录（preflight + 执行，内部复用 `routers.jobs.core_*`）
- `store.py`：自动化开关、规则、历史、运行记录的持久化
- `audit.py`：审计（复用 `data/audit/actions.jsonl`，带 trigger / trigger_id）
"""

from automation.service import start_automation, stop_automation

__all__ = ["start_automation", "stop_automation"]
