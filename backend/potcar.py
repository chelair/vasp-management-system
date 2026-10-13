"""POTCAR 生成：在远端目录运行 `pos2pot` 并解析结果（2026-10-13 抽出，供多处复用）。

远端脚本实际是 `/data/gpfs03/mdye/projects/potcar/pos2pot.sh`：**递归**遍历当前目录下
所有含 `POSCAR` 的子目录并调用 `potcar.sh $(sed -n 6p POSCAR)`；`pos2pot` 只是
`~/.bashrc` 里的 alias，非交互 exec 看不到，因此按 `pos2pot` → `pos2pot.sh` → 绝对路径
依次解析；命令可用 `servers.json` 的 `pos2pot_cmd` 覆盖。

调用方：
- `POST /api/jobs/tasks/{id}/generate-potcar`（作业管理 POSCAR 页按钮，当前目录 = 最新 conN）；
- 差分电荷创建（`ele_diff.create_diff_charge`）：在主任务目录跑一次，**递归**把
  主结构 + 各分块子目录的 POTCAR 一起生成。
"""

from __future__ import annotations

import base64
import re
from typing import Any, Dict

import ssh
from config import load_servers


class PotcarError(Exception):
    """pos2pot 无法执行：`kind` = no_dir（远端目录不存在）/ not_found（找不到命令）。"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _potcar_script(remote_dir: str, configured: str, use_latest_con: bool = True) -> str:
    """单次 exec 完成的脚本：定位目录 → 跑 pos2pot → 输出 POTCAR 摘要。"""
    before = (
        'LATEST=$(ls -d con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -1)'
        if use_latest_con
        else 'LATEST=""'
    )
    return "\n".join(
        [
            'cd "' + remote_dir + '" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
            before,
            'WORK="' + remote_dir + '"',
            '[ -n "$LATEST" ] && WORK="' + remote_dir + '/$LATEST"',
            'cd "$WORK" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
            'echo "@@@WORK=$WORK"',
            'CMD="' + configured + '"',
            'if ! command -v "$CMD" >/dev/null 2>&1; then',
            "  for cand in pos2pot.sh /data/gpfs03/mdye/projects/potcar/pos2pot.sh; do",
            '    if command -v "$cand" >/dev/null 2>&1; then CMD="$cand"; break; fi',
            "  done",
            "fi",
            'if ! command -v "$CMD" >/dev/null 2>&1; then',
            '  echo "@@@NOT_FOUND=$CMD"; exit 5',
            "fi",
            'echo "@@@RUN=$CMD"',
            'OUT=$("$CMD" 2>&1); RC=$?',
            'echo "@@@RC=$RC"',
            'echo "@@@OUT_START"',
            'echo "$OUT" | tail -n 40',
            'echo "@@@OUT_END"',
            'echo "@@@POTCAR_START"',
            "if [ -s POTCAR ]; then",
            '  echo "SIZE=$(wc -c < POTCAR | tr -d \' \')"',
            '  echo "LINES=$(wc -l < POTCAR | tr -d \' \')"',
            '  echo "ELEMENTS=$(awk \'/^ *TITEL/{printf "%s,", $4}\' POTCAR)"',
            '  echo "NBLOCKS=$(grep -c \'^ *TITEL\' POTCAR)"',
            '  head -n 2 POTCAR',
            "else",
            '  echo "MISSING"',
            "fi",
            'echo "@@@POTCAR_END"',
        ]
    )


def run_pos2pot(
    server: str, remote_dir: str, *, timeout: int = 120, use_latest_con: bool = True
) -> Dict[str, Any]:
    """在 `remote_dir` 运行 pos2pot，返回 `{dir, command, exit_code, output, potcar, generated}`。

    `use_latest_con=False` 时只在给定目录里跑（差分电荷要的是**主目录递归**，
    不能跑到 conN 里去）。失败抛 `PotcarError`。
    """
    configured = str(
        load_servers().get(server, {}).get("pos2pot_cmd") or "pos2pot"
    ).strip()
    if not remote_dir:
        raise PotcarError("no_dir", "缺少远程目录")
    script = _potcar_script(remote_dir, configured, use_latest_con=use_latest_con)
    script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    result = ssh.run_remote(server, f"echo {script_b64} | base64 -d | bash", timeout=timeout)
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    work_match = re.search(r"@@@WORK=(.+)", raw)
    work_dir = work_match.group(1).strip() if work_match else remote_dir
    if "@@@NO_DIR" in raw:
        raise PotcarError("no_dir", f"远程目录不存在：{work_dir}")
    not_found = re.search(r"@@@NOT_FOUND=(\S*)", raw)
    if not_found:
        raise PotcarError(
            "not_found",
            f"远端找不到命令 {not_found.group(1) or 'pos2pot'}"
            "（可在 servers.json 用 pos2pot_cmd 指定绝对路径）",
        )
    run_match = re.search(r"@@@RUN=(\S+)", raw)
    command = run_match.group(1) if run_match else configured

    def _slice(start: str, end: str) -> str:
        s = raw.find(start)
        if s < 0:
            return ""
        s += len(start)
        e = raw.find(end, s)
        return raw[s:e].strip() if e >= 0 else raw[s:].strip()

    rc_match = re.search(r"@@@RC=(-?\d+)", raw)
    rc = int(rc_match.group(1)) if rc_match else -1
    output = _slice("@@@OUT_START", "@@@OUT_END")
    potcar_block = _slice("@@@POTCAR_START", "@@@POTCAR_END")
    size_match = re.search(r"SIZE=(\d+)", potcar_block)
    lines_match = re.search(r"LINES=(\d+)", potcar_block)
    elems_match = re.search(r"ELEMENTS=(.*)", potcar_block)
    blocks_match = re.search(r"NBLOCKS=(\d+)", potcar_block)
    elements = [
        item for item in (elems_match.group(1).split(",") if elems_match else []) if item
    ]
    generated = "MISSING" not in potcar_block and bool(size_match)
    return {
        "dir": work_dir,
        "command": command,
        "exit_code": rc,
        "output": output,
        "generated": generated,
        "potcar": {
            "exists": generated,
            "size": int(size_match.group(1)) if size_match else 0,
            "lines": int(lines_match.group(1)) if lines_match else 0,
            "elements_count": int(blocks_match.group(1)) if blocks_match else len(elements),
            "elements": elements,
        },
    }
