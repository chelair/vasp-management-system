"""极简 5 段 cron 解析（零依赖，替代 APScheduler 的 cron 触发）。

支持字段：`分 时 日 月 周`，取值：

- `*` 任意；`5` 定值；`1-5` 范围；`*/10` 步长；`1-5/2` 范围步长；`1,3,5` 列表。
- 周字段用 0-7（0 与 7 都表示周日）。

说明：不引入 APScheduler（项目一直零新依赖），行为对齐"cron 表达式 + 持久化 +
改完立即生效"；`next_after()` 从当前时间往后逐分钟找第一个命中时刻。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Set

FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 7),
)


class CronError(ValueError):
    """cron 表达式不合法。"""


def _parse_field(expr: str, low: int, high: int) -> Set[int]:
    values: Set[int] = set()
    for chunk in str(expr).strip().split(","):
        chunk = chunk.strip()
        if not chunk:
            raise CronError("空字段")
        step = 1
        if "/" in chunk:
            chunk, _, step_text = chunk.partition("/")
            try:
                step = int(step_text)
            except ValueError:
                raise CronError(f"步长非法：{step_text}") from None
            if step <= 0:
                raise CronError("步长必须为正整数")
        if chunk == "*":
            start, end = low, high
        elif "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise CronError(f"范围非法：{chunk}") from None
        else:
            try:
                start = end = int(chunk)
            except ValueError:
                raise CronError(f"字段非法：{chunk}") from None
        if start < low or end > high or start > end:
            raise CronError(f"字段越界：{chunk}（允许 {low}-{high}）")
        values.update(range(start, end + 1, step))
    return values


def parse(expr: str) -> Dict[str, Set[int]]:
    parts = str(expr or "").split()
    if len(parts) != 5:
        raise CronError(f"cron 需要 5 段（分 时 日 月 周）：{expr!r}")
    parsed: Dict[str, Set[int]] = {}
    for (name, low, high), chunk in zip(FIELDS, parts):
        parsed[name] = _parse_field(chunk, low, high)
    # 周日 7 归一成 0
    if 7 in parsed["weekday"]:
        parsed["weekday"].discard(7)
        parsed["weekday"].add(0)
    return parsed


def matches(parsed: Dict[str, Set[int]], moment: datetime) -> bool:
    weekday = (moment.weekday() + 1) % 7  # 周一=1 … 周日=0
    return (
        moment.minute in parsed["minute"]
        and moment.hour in parsed["hour"]
        and moment.day in parsed["day"]
        and moment.month in parsed["month"]
        and weekday in parsed["weekday"]
    )


def next_after(expr: str, after: datetime | None = None, limit_days: int = 400) -> datetime:
    """返回严格晚于 `after` 的下一个命中时刻（按分钟对齐）。"""
    parsed = parse(expr)
    base = (after or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    moment = base
    for _ in range(limit_days * 24 * 60):
        if matches(parsed, moment):
            return moment
        moment += timedelta(minutes=1)
    raise CronError(f"未来 {limit_days} 天内没有匹配时间：{expr!r}")


def describe(expr: str) -> str:
    """给前端展示的简要说明（解析失败时返回原文）。"""
    try:
        parse(expr)
    except CronError:
        return f"非法表达式：{expr}"
    return expr
