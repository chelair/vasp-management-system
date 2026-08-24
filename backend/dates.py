"""时间工具（对齐参考实现 common.py / priority.py）。"""

from datetime import date, datetime


def now_iso() -> str:
    """本地时间 YYYY-MM-DDTHH:mm:ss。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def is_valid_date(value: str) -> bool:
    """校验 YYYY-MM-DD 是否为合法日历日期。"""
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def days_until(deadline: str) -> int:
    """距截止日期的自然日天数（按日期差，忽略时分秒）。"""
    return (date.fromisoformat(deadline) - date.today()).days
