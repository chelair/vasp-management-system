"""INCAR 参数解析与修改核心函数（本地与远端共用）。

统一规则：
- 参数名大小写不敏感（ENCUT / Encut / encut 视为同一参数）；
- 等号与空格任意（ENCUT=400 / ENCUT = 400 / ENCUT =400）；
- 布尔值统一为 .TRUE. / .FALSE.（兼容 .true./TRUE/.t./T 等写法）；
- 保留参数行尾注释（# 或 ! 之后的内容）；
- 存在即替换、重复合并（保留最后一行 + 警告）、不存在追加。
"""

from typing import Any, Dict, List, Tuple

_TRUE_WORDS = {".true.", "true", ".t.", "t", "yes", "on"}
_FALSE_WORDS = {".false.", "false", ".f.", "f", "no", "off"}


def format_value(value: Any) -> str:
    """把修改值格式化为 INCAR 值字符串（布尔统一 .TRUE./.FALSE.）。"""
    if isinstance(value, bool):
        return ".TRUE." if value else ".FALSE."
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    low = s.lower()
    if low in _TRUE_WORDS:
        return ".TRUE."
    if low in _FALSE_WORDS:
        return ".FALSE."
    return s


def _split_comment(line: str) -> Tuple[str, str]:
    """拆分参数行与行尾注释（# 或 ! 之后为注释）。"""
    for marker in ("#", "!"):
        pos = line.find(marker)
        if pos != -1:
            return line[:pos], line[pos:]
    return line, ""


def _replace_value(line: str, key: str, new_value: str) -> str:
    """替换参数行等号后的值，保留行尾注释。"""
    body, comment = _split_comment(line)
    left = body.split("=", 1)[0].rstrip()
    if comment:
        return f"{left} = {new_value}  {comment}".rstrip()
    return f"{left} = {new_value}"


def modify_incar(content: str, changes: Dict[str, Any]) -> Tuple[str, List[str]]:
    """按统一规则修改 INCAR 文本。

    Args:
        content: 原始 INCAR 文本。
        changes: 需修改的参数字典（键大小写不敏感）。

    Returns:
        (修改后的文本, 警告列表)，警告如重复参数合并。
    """
    changes = {str(k).strip().upper(): v for k, v in (changes or {}).items()}
    warnings: List[str] = []
    if not changes:
        return content, warnings

    lines = content.splitlines()
    matches: Dict[str, List[Tuple[int, str]]] = {}
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        if "=" not in stripped:
            continue
        body, _ = _split_comment(stripped)
        left, _, _ = body.partition("=")
        key = left.strip().upper()
        if key:
            matches.setdefault(key, []).append((idx, line))

    out = list(lines)
    removed: set = set()
    for key, raw_value in changes.items():
        new_value = format_value(raw_value)
        hit = matches.get(key, [])
        if not hit:
            out.append(f"{key} = {new_value}")
            continue
        if len(hit) > 1:
            warnings.append(
                f"参数 {key} 重复 {len(hit)} 次，已合并为一行（保留最后一次）"
            )
            for idx, _ in hit[:-1]:
                removed.add(idx)
        keep_idx, keep_line = hit[-1]
        out[keep_idx] = _replace_value(keep_line, key, new_value)

    result = [line for i, line in enumerate(out) if i not in removed]
    return "\n".join(result) + ("\n" if result else ""), warnings
