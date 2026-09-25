"""作业管理接口：本地任务目录的统一文件读写。

本地目录约定（v0.3.0，dir_path 为权威字段）：
    独立任务：data/projects/<项目名>/<模型名>/
    自由能组：data/projects/<项目名>/<组根>/<结构标签>/<opt|frac>/
    NEB 组：  data/projects/<项目名>/<组根>/<initial_opt|final_opt|neb_calc>/
每个任务目录下：files/（VASP 文件）、images/、reports/、continuation/
"""

import base64
from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import DATA_DIR, load_servers
# 注意：input_state 里也有一个同名函数 build_snapshot（输入文件快照），
# 下面 from input_state import build_snapshot 会覆盖这个名字；节点状态用别名区分，
# 否则 /api/jobs/nodes 会因 use_cache 参数不被接受而 500（v0.8.2 起的回归）。
from cluster_status import build_snapshot as build_node_snapshot
from continuation import (
    _download_remote_text,
    _remote_latest_con,
    _write_remote_file,
    build_ele_inputs,
    compute_g_correction,
    create_continuation,
    create_frac_files,
    create_neb_files,
    local_continuation_dir,
)
from dates import now_iso
from envelope import fail, ok
from incar import modify_incar
import permissions
from paths import resolve_local_path, resolve_remote_path, to_local_rel, to_remote_rel
import ssh
from storage import STATUS_ENUM, db_transaction, load_db, save_db, update_task_status
from task_paths import free_energy_frac_task, is_continuation_task, task_dir
from input_state import (
    _hash as text_hash,
    build_snapshot,
    download_archive_outputs,
    has_pending,
    mark_file_applied,
    merge_snapshot,
    parse_incar_text,
    parse_kpoints_mesh,
    poscar_meta,
    read_snapshot_cif,
    read_snapshot_text,
    snapshot_dir,
    revert_draft,
    set_incar_draft,
    set_kpoints_draft,
)
from cif_convert import read_or_convert_cif, refresh_structure_cif

router = APIRouter(prefix="/jobs", tags=["jobs"])

AUDIT_LOG = DATA_DIR / "audit_submit.log"

#: 允许读取/写入的文本文件白名单（防目录穿越；WAVECAR/CHGCAR 等二进制后续单独处理）
TEXT_FILE_WHITELIST = {
    "INCAR",
    "POSCAR",
    "KPOINTS",
    "POTCAR",
    "CONTCAR",
    "OSZICAR",
    "OUTCAR",
    "DOSCAR",
    "EIGENVAL",
    "vasprun.xml",
    "submit.sh",
    "run.sh",
    "vasp.lsf",
}


class FileWritePayload(BaseModel):
    content: str


class RenameTaskPayload(BaseModel):
    model_name: str


NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_@]*$")


@router.get("/nodes")
def cluster_nodes(refresh: bool = False):
    """查询集群节点状态：bhost 主数据 + bqueues 补充 + node_groups 映射。

    默认使用 60 秒缓存；传入 ?refresh=1 强制重新查询。
    """
    try:
        servers = load_servers()
        server_name = next(iter(servers.keys()), "server1")
        snapshot = build_node_snapshot(server_name, use_cache=not refresh)
        return ok("查询成功", snapshot)
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=fail(f"查询节点状态失败：{e}"),
        )


def _resolve_task_dir(task_id: str) -> Path:
    """按 task_id 定位任务本地目录（项目库 -> 任务字段）；顺带做归属校验。"""
    db = load_db()
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                permissions.enforce_task(task, db)
                return task_dir(str(project.get("name", "")), task)
    raise LookupError(f"任务 {task_id} 不存在")


def _resolve_task(task_id: str, *, enforce: bool = True):
    """返回 (project, task)，任务不存在时抛 LookupError。

    **这是所有作业动作的唯一入口**：在这里统一做归属校验（第 4 步）——
    非 owner 且非 admin 抛 `PermissionDenied`（→ 403），一次性覆盖提交 / 续算 /
    上传输入文件 / 生成 frac / 创建 NEB / 归档 / 删除等全部 task 级接口。
    `enforce=False` 供后台线程等内部调用显式跳过（此时 contextvar 里也没有用户）。
    """
    db = load_db()
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                if enforce:
                    permissions.enforce_task(task, db)
                return project, task
    raise LookupError(f"任务 {task_id} 不存在")


def _new_task_id(project: Dict) -> str:
    import time

    ts = int(time.time() * 1000)
    used = {t.get("task_id") for t in project.get("tasks", [])}
    seq = 1
    while f"task_{ts}_{seq}" in used:
        seq += 1
    return f"task_{ts}_{seq}"


def _validate_name(filename: str) -> str:
    if filename not in TEXT_FILE_WHITELIST:
        raise ValueError(f"不支持的文件名：{filename}")
    return filename


def _files_dir(task_dir: Path) -> Path:
    """统一文件目录为 <任务目录>/files/，不存在时退化到任务根目录扫描。"""
    files_dir = task_dir / "files"
    return files_dir if files_dir.is_dir() else task_dir


def _prepare_remote_write(
    server: str, remote_dir: str, name: str, backup_name: str
) -> tuple[str, bool]:
    """**一次 exec** 完成「定位最新 conN（无则主目录）+ 把已有 <name> 备份为 <backup_name>」。

    返回 `(工作目录, 是否真有旧文件被备份)`。原来"定位目录"和"备份"是两次往返，
    现在合并成一次（调用方随后用 SFTP 写内容即可）。
    mock 模式（VASP_SSH_MOCK=1）直接操作本地 mock 远端树，便于离线验证。
    """
    if ssh.mock_enabled():
        base = ssh.mock_local_path(remote_dir)
        work = base
        if base.is_dir():
            cons = sorted(
                (p for p in base.glob("con[0-9]*") if p.is_dir()),
                key=lambda p: int("".join(ch for ch in p.name if ch.isdigit()) or 0),
            )
            if cons:
                work = cons[-1]
        src = work / name
        had_old = src.is_file()
        if src.is_file():
            dst = work / backup_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        suffix = work.relative_to(base).as_posix() if work != base else ""
        return (f"{remote_dir}/{suffix}" if suffix else remote_dir), had_old

    script = "\n".join(
        [
            # 目录还不存在时先建出来（v0.9.30）：新建的独立任务以前不在远端建目录，
            # 第一次「同步到远端」就会因为目录不存在失败（用户 2026-09-25 踩坑）
            'mkdir -p "' + remote_dir + '" 2>/dev/null || { echo "@@@MKDIR_FAIL"; exit 4; }',
            'cd "' + remote_dir + '" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
            'LATEST=$(ls -d con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -1)',
            'WORK="' + remote_dir + '"',
            '[ -n "$LATEST" ] && WORK="' + remote_dir + '/$LATEST"',
            'cd "$WORK" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
            'if [ -f "' + name + '" ]; then',
            '  mv -f "' + name + '" "' + backup_name + '"',
            '  echo "@@@BACKUP=1"',
            "else",
            '  echo "@@@BACKUP=0"',
            "fi",
            'echo "@@@WORK=$WORK"',
        ]
    )
    try:
        script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        result = ssh.run_remote(
            server, f"echo {script_b64} | base64 -d | bash", timeout=60
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception:  # noqa: BLE001 - 定位失败回退主目录写入
        return remote_dir, False
    out = str(result.get("stdout") or "")
    if "@@@MKDIR_FAIL" in out:
        raise ActionError(
            502, f"远端目录 {remote_dir} 不存在且创建失败（检查账号权限/磁盘配额）"
        )
    if "@@@NO_DIR" in out:
        return remote_dir, False
    match = re.search(r"@@@WORK=(.+)", out)
    work_dir = match.group(1).strip() if match else remote_dir
    return work_dir, "@@@BACKUP=1" in out


def _open_in_explorer(path: str) -> None:
    """在服务器所在机器打开文件管理器并定位到目录（Windows 资源管理器优先）。"""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined] - Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _audit_log(project: str, task_id: str, remote_dir: str, command: str, result: str) -> None:
    """写操作审计（第 4 步起带用户名）。

    双写：
    - **JSONL**：`data/audit/actions.jsonl`，每行一条结构化记录（新格式，便于后续
      智能体/审计页消费）；
    - **旧文本**：`data/audit_submit.log` 保持原格式（只在行尾追加 `user=`），
      因为总览趋势的"提交作业数"仍从它回溯统计，不能停写。
    """
    username = permissions.context_username() or "-"
    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"[{timestamp}] project={project} "
                f"task={task_id} dir={remote_dir} cmd={command} result={result} user={username}\n"
            )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception:  # noqa: BLE001 - 审计日志失败不影响提交
        pass
    try:
        jsonl = DATA_DIR / "audit" / "actions.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "at": timestamp,
                        "username": username,
                        "project": project,
                        "task_id": task_id,
                        "remote_dir": remote_dir,
                        "command": command,
                        "result": result,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception:  # noqa: BLE001
        pass


# ============================================================ 动作核心（v0.9.6）
# 下面四个 `core_*` 是「提交作业 / 创建续算 / 生成频率矫正 / 创建 NEB 文件」的
# 业务实现，**HTTP 接口与自动化动作层共用同一份**（接缝要求：不让调度器直接调
# 业务接口，也不在两个地方各写一份逻辑）。前置条件不满足时抛 `ActionError`，
# 由调用方决定映射成 HTTP 响应还是动作失败原因。


class ActionError(Exception):
    """动作前置条件不满足（HTTP 400/404/409 或自动化 blocked/preflight 失败）。"""

    def __init__(self, status_code: int, message: str, data: Dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = message
        self.data = data or {}


def core_continuation(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """同类型续算核心：远端建 conN 并登记隐藏续算子任务。

    返回 `{**result, task_id, local_dir, remote_dir}`；`result["action"]` 为
    `created / running / input_complete_but_not_finished / input_incomplete`，
    **只有 created 才算真的创建了目录**（自动化层必须判这个字段）。
    """
    task_id = str(task.get("task_id") or "")
    if is_continuation_task(task):
        raise ActionError(400, "续算子任务不支持再续算，请对原始任务操作")
    if task.get("task_type") not in ("opt", "neb"):
        raise ActionError(400, "仅结构优化（opt）与 NEB 任务支持同类型续算")

    result = create_continuation(project.get("server"), project, task)
    if result.get("action") != "created":
        _audit_log(
            project["name"],
            task_id,
            str(result.get("current_dir", "")),
            "continuation",
            f"action={result.get('action')} missing={result.get('missing_files') or []}",
        )
        return dict(result)

    if task.get("task_type") != "neb" and "POSCAR" not in result.get("copied_files", []):
        raise ActionError(
            400,
            f"源目录缺少 CONTCAR，无法生成续算 POSCAR（源：{result.get('source_dir')}）",
        )

    # 登记续算子任务：dir_path 写 `<任务目录>/conN`（逻辑主键），本地不再建 conN 目录
    con = result["con"]
    local_dir = local_continuation_dir(str(task.get("dir_path", "")), con)
    now = now_iso()
    rel_remote = to_remote_rel(project.get("server"), result["remote_dir"])
    sub_task = {
        "task_id": _new_task_id(project),
        "task_type": task.get("task_type"),
        "subtype": task.get("subtype"),
        "model_name": f"{task.get('model_name', 'task')}_{con}",
        "status": "pending",
        "last_energy": None,
        "last_check_time": None,
        "job_id": None,
        "notes": f"由 {task.get('model_name')} 同类型续算创建（{con}）",
        "continuation_ready": False,
        "continuation_dir": None,
        "dir_path": local_dir,
        "remote_dir": rel_remote,
        "group": None,
        "parent_task_id": task_id,
        "input_source": {
            "poscar_from": to_remote_rel(
                project.get("server"), f"{result['source_dir']}/CONTCAR"
            ),
            "potcar_from": None,
            "kpoints_from": None,
        },
        "created_at": now,
        "updated_at": now,
    }
    from storage import save_db

    db = load_db()
    proj = next(p for p in db["projects"] if p["name"] == project["name"])
    # create_continuation 会把应用过的草稿写进 task["input_state"]，必须一起落库
    if task.get("input_state") is not None:
        parent = next((t for t in proj["tasks"] if t.get("task_id") == task_id), None)
        if parent is not None:
            parent["input_state"] = task["input_state"]

    existing = next((t for t in proj["tasks"] if t.get("dir_path") == local_dir), None)
    if existing is not None:
        # 远端"打回重算"：远端可能只剩 con1，而本地已登记到 con5 —— 这时远端重新数出来的
        # conN 会跟本地旧记录撞路径。远端这个目录刚刚就在本次脚本里建好，所以**复用**这条记录
        # （对齐远端真实编号），而不是报 409 把自动化卡死。
        previous = str(existing.get("status") or "") or "未知"
        existing.update(
            {
                "task_type": sub_task["task_type"],
                "subtype": sub_task["subtype"],
                "status": "pending",
                "last_energy": None,
                "last_check_time": None,
                "job_id": None,
                "notes": (
                    f"由 {task.get('model_name')} 同类型续算创建（{con}）；"
                    f"远端重算后复用本地已登记记录（原状态：{previous}）"
                ),
                "continuation_ready": False,
                "continuation_dir": None,
                "remote_dir": rel_remote,
                "parent_task_id": task_id,
                "input_source": sub_task["input_source"],
                "updated_at": now,
            }
        )
        # 复用 = 这条记录重新开始算，归档标记要清掉（否则状态/归档信息自相矛盾）
        existing.pop("archived_from", None)
        existing.pop("archived_at", None)
        save_db(db)
        return {
            **result,
            "task_id": existing["task_id"],
            "local_dir": local_dir,
            "remote_dir": rel_remote,
            "reused": True,
            "previous_status": previous,
            "message": (
                f"已创建续算目录 {con}（远端编号回退，复用本地已登记的 {con} 记录，"
                f"原状态：{previous}）"
            ),
        }

    proj["tasks"].append(sub_task)
    save_db(db)

    return {
        **result,
        "task_id": sub_task["task_id"],
        "local_dir": local_dir,
        "remote_dir": rel_remote,
    }


def core_submit(
    project: Dict[str, Any], task: Dict[str, Any], *, dry_run: bool = False
) -> Dict[str, Any]:
    """提交作业核心：一次 exec 完成「定位最新 conN → 输入文件非空检查 → bsub」。

    `dry_run=True` 时只跑到检查（脚本打印 `@@@CHECK_ONLY` 就退出），
    **不执行 bsub、不改状态**，返回 `{dry_run, will_submit, work_dir}`。
    """
    task_id = str(task.get("task_id") or "")
    status = task.get("status")
    job_id = task.get("job_id")
    if job_id and status in ("queued", "running"):
        raise ActionError(409, "作业已提交/运行中，请勿重复操作")

    server = project.get("server")
    remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
    if not remote_dir:
        raise ActionError(404, "任务缺少远程目录")

    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    submit_script = "vasp.lsf"
    command = f'cd "{remote_dir}" && bsub < {submit_script}'
    lines = [
        'cd "' + remote_dir + '" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
        'LATEST=$(ls -d con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -1)',
        'WORK="' + remote_dir + '"',
        '[ -n "$LATEST" ] && WORK="' + remote_dir + '/$LATEST"',
        'cd "$WORK" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
        'echo "@@@WORK=$WORK"',
        *_submit_preflight_lines(str(task.get("task_type") or ""), submit_script),
        '[ -n "$EMPTY" ] && { echo "@@@EMPTY=$EMPTY"; exit 4; }',
    ]
    if dry_run:
        lines.append('echo "@@@CHECK_ONLY"')
    else:
        lines += [
            'echo "@@@BSUB"',
            "source " + profile + " >/dev/null 2>&1 || true",
            'bsub < "' + submit_script + '"',
            'echo "@@@BSUB_RC=$?"',
        ]
    script = "\n".join(lines)
    try:
        script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        result = ssh.run_remote(server, f"echo {script_b64} | base64 -d | bash", timeout=90)
    except Exception as e:  # noqa: BLE001 - SSH 连接类错误统一按 502 上报
        raise ActionError(502, f"无法连接远程服务器，请检查 SSH 配置：{e}") from e

    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    work_match = re.search(r"@@@WORK=(.+)", raw)
    work_dir = work_match.group(1).strip() if work_match else remote_dir
    if "@@@NO_DIR" in raw:
        raise ActionError(404, f"远程目录不存在：{remote_dir}")
    empty_match = re.search(r"@@@EMPTY=(.*)", raw)
    if empty_match:
        missing = [name for name in empty_match.group(1).split() if name]
        _audit_log(
            project["name"], task_id, work_dir, command,
            f"PRECHECK_FAIL empty={','.join(missing)}",
        )
        raise ActionError(
            400,
            f"以下输入文件缺失或为空，已阻止提交：{'、'.join(missing)}"
            f"（目录 {work_dir}；请先补齐再提交）",
            {"missing": missing, "work_dir": work_dir},
        )
    if dry_run:
        return {
            "dry_run": True,
            "will_submit": True,
            "task_id": task_id,
            "work_dir": work_dir,
            "submit_script": submit_script,
            "raw_output": raw,
        }

    # bsub 的报错要**原样带给用户**：像 LSF 拒绝提交（RUNLIMIT 超队列硬上限等）时
    # 输出里根本没有 "Job <id>"，旧实现只会抛"未能解析作业 ID"，用户完全看不懂（2026-09-24 踩坑）。
    def _bsub_detail() -> str:
        lines = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.startswith("@@@")
        ]
        return " / ".join(lines[:3]) or "bsub 没有任何输出"

    bsub_rc_match = re.search(r"@@@BSUB_RC=(\d+)", raw)
    bsub_rc = bsub_rc_match.group(1) if bsub_rc_match else ""
    submit_match = re.search(r"Job <(\d+)> is submitted", raw)
    match = submit_match or re.search(r"Job <(\d+)>", raw)
    if not match:
        detail = _bsub_detail()
        _audit_log(
            project["name"], task_id, work_dir, command,
            f"BSUB_REJECTED rc={bsub_rc or '?'} {detail}",
        )
        raise ActionError(
            400,
            f"bsub 提交被集群拒绝（rc={bsub_rc or '?'}）：{detail}"
            + (f"；工作目录 {work_dir}" if work_dir else ""),
            {"work_dir": work_dir, "bsub_rc": bsub_rc, "raw_output": raw},
        )
    new_job_id = match.group(1)
    try:
        with db_transaction() as db:
            update_task_status(
                db, project["name"], task_id, "queued", {"job_id": new_job_id}
            )
    except Exception as e:  # noqa: BLE001 - 状态落库失败不影响已提交事实
        _audit_log(project["name"], task_id, remote_dir, command, f"DB_WARN: {e}")
    _audit_log(project["name"], task_id, remote_dir, command, f"OK job={new_job_id}")
    _schedule_input_sync(str(project.get("name") or ""), task_id)
    return {"job_id": new_job_id, "new_status": "queued", "raw_output": raw}


def core_create_frac(
    project: Dict[str, Any],
    task: Dict[str, Any],
    params: Dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """生成频率矫正（frac）输入文件核心。"""
    task_id = str(task.get("task_id") or "")
    if task.get("task_type") != "opt":
        raise ActionError(400, "仅结构优化任务可创建频率矫正")
    frac_task = next(
        (
            t
            for t in project.get("tasks", [])
            if t.get("dir_path") == f"{task.get('dir_path', '')}/frac"
        ),
        None,
    )
    if frac_task is None:
        raise ActionError(404, "未找到对应的频率矫正子任务（frac），请先在自由能组中创建")
    if dry_run:
        return {
            "dry_run": True,
            "will_do": "从任务最新输出生成 frac 输入文件（CONTCAR→POSCAR / POTCAR / KPOINTS）",
            "task_id": task_id,
            "frac_task_id": frac_task.get("task_id"),
            "source_dir_hint": task.get("continuation_dir") or task.get("remote_dir"),
        }
    result = create_frac_files(
        project["server"], project, task, frac_task, params=params or {}
    )
    frac_task["input_source"] = {
        "poscar_from": f"{result['source_dir']}/CONTCAR",
        "potcar_from": f"{result['source_dir']}/POTCAR",
        "kpoints_from": f"{result['source_dir']}/KPOINTS",
    }
    frac_task["notes"] = (
        f"频率矫正输入由 {task.get('model_name')} 生成（{result['latest_dir'] or '主目录'}）"
    )
    db = load_db()
    proj = next(p for p in db["projects"] if p["name"] == project["name"])
    for t in proj["tasks"]:
        if t.get("task_id") == frac_task["task_id"]:
            t.update(frac_task)
    save_db(db)
    _audit_log(
        project["name"], task_id, result["frac_dir"],
        "create-frac", f"OK src={result['source_dir']}",
    )
    return dict(result)


def core_create_neb(
    project: Dict[str, Any],
    task: Dict[str, Any],
    payload: Dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """创建 NEB 计算文件核心（nebmake.pl 插值）。"""
    task_id = str(task.get("task_id") or "")
    body = payload or {}
    if task.get("task_type") != "neb":
        raise ActionError(400, "仅 NEB 任务可创建计算文件")
    initial_id = body.get("initial_opt_task_id")
    final_id = body.get("final_opt_task_id")
    try:
        num_images = int(body.get("num_images", 3))
    except (TypeError, ValueError):
        raise ActionError(400, "num_images 必须是整数") from None
    if not initial_id or not final_id:
        raise ActionError(400, "缺少初态/末态优化任务 ID")
    tasks = project.get("tasks", [])
    initial_task = next((t for t in tasks if t.get("task_id") == initial_id), None)
    final_task = next((t for t in tasks if t.get("task_id") == final_id), None)
    if initial_task is None or final_task is None:
        raise ActionError(404, "初态/末态优化任务不存在")
    if initial_task.get("task_type") != "opt" or final_task.get("task_type") != "opt":
        raise ActionError(400, "初态/末态必须是结构优化任务")
    if initial_task.get("status") != "completed":
        raise ActionError(
            400,
            f"初态优化未收敛（当前状态：{initial_task.get('status')}），请先完成结构优化",
        )
    if final_task.get("status") != "completed":
        raise ActionError(
            400,
            f"末态优化未收敛（当前状态：{final_task.get('status')}），请先完成结构优化",
        )
    if dry_run:
        return {
            "dry_run": True,
            "will_do": f"用 nebmake.pl 在 NEB 目录生成 {num_images} 个映像",
            "task_id": task_id,
            "initial_opt_task_id": initial_id,
            "final_opt_task_id": final_id,
            "num_images": num_images,
        }
    result = create_neb_files(
        project["server"],
        project,
        task,
        initial_task,
        final_task,
        num_images,
        params=body.get("params") or {},
    )
    task["input_source"] = {
        "poscar_from": f"{result['source_is']}/CONTCAR",
        "potcar_from": f"{result['source_is']}/POTCAR",
        "kpoints_from": f"{result['source_is']}/KPOINTS",
    }
    db = load_db()
    proj = next(p for p in db["projects"] if p["name"] == project["name"])
    for t in proj["tasks"]:
        if t.get("task_id") == task_id:
            t.update(task)
    save_db(db)
    _audit_log(
        project["name"], task_id, result["neb_dir"],
        f"create-neb images={num_images}", "OK",
    )
    return dict(result)


@router.get("/tasks/{task_id}/files")
def list_task_files(task_id: str):
    try:
        task_dir = _resolve_task_dir(task_id)
        scan_dir = _files_dir(task_dir)
        entries = []
        if scan_dir.is_dir():
            for f in sorted(scan_dir.iterdir(), key=lambda p: p.name.lower()):
                if not f.is_file():
                    continue
                st = f.stat()
                entries.append(
                    {
                        "name": f.name,
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
        return ok(
            "查询成功",
            {"task_id": task_id, "dir": str(scan_dir), "files": entries},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取任务目录失败：{e}"))


@router.get("/tasks/{task_id}/files/{filename}")
def read_task_file(task_id: str, filename: str):
    try:
        name = _validate_name(filename)
        task_dir = _resolve_task_dir(task_id)
        path = _files_dir(task_dir) / name
        if not path.is_file():
            return JSONResponse(
                status_code=404,
                content=fail(f"{name} 不存在于任务目录 {task_dir}"),
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        return ok("读取成功", {"name": name, "path": str(path), "content": content})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取 {filename} 失败：{e}"))


@router.put("/tasks/{task_id}/files/{filename}")
def write_task_file(task_id: str, filename: str, payload: FileWritePayload):
    try:
        name = _validate_name(filename)
        project, task = _resolve_task(task_id)
        task_dir = _resolve_task_dir(task_id)
        files_dir = task_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        path = files_dir / name
        path.write_text(payload.content, encoding="utf-8")
        # 结构文件写入后立刻重算 CIF（覆盖），否则 3D 结构视图要等下一次 GET /input 才更新
        if name in ("POSCAR", "CONTCAR"):
            refresh_structure_cif(project, task, name)
        state = _input_payload(project, task)
        return ok(
            "保存成功",
            {"name": name, "path": str(path), "size": path.stat().st_size, "state": state},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"写入 {filename} 失败：{e}"))


@router.post("/tasks/{task_id}/open-folder")
def open_task_folder(task_id: str):
    """在服务器本机打开任务本地目录（定位到 files/），便于直接查看/编辑文件。"""
    try:
        task_dir = _resolve_task_dir(task_id)
        files_dir = task_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        target = files_dir if files_dir.is_dir() else task_dir
        _open_in_explorer(str(target))
        return ok("已打开文件夹", {"path": str(target)})
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"打开文件夹失败：{e}"))


@router.post("/tasks/{task_id}/continuation")
def create_same_type_continuation(task_id: str):
    """同类型续算：全部在远程服务器完成，创建 conN 目录并登记续算子任务。"""
    try:
        project, task = _resolve_task(task_id)
        data = core_continuation(project, task)
        if data.get("action") != "created":
            return ok(data.get("message", "续算检查完成"), data)
        return ok("续算目录已创建", data)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ActionError as e:
        return JSONResponse(status_code=e.status_code, content=fail(e.message, e.data or None))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建续算失败：{e}"))
@router.post("/tasks/{task_id}/create-frac")
def create_frac(task_id: str, payload: dict = Body(default={})):
    """为结构优化任务构建频率矫正（frac）输入文件（自由能流程）。"""
    try:
        project, task = _resolve_task(task_id)
        result = core_create_frac(project, task, payload.get("params") or {})
        return ok("频率矫正输入文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ActionError as e:
        return JSONResponse(status_code=e.status_code, content=fail(e.message, e.data or None))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建频率矫正失败：{e}"))
@router.post("/tasks/{task_id}/build-ele-inputs")
def build_ele(task_id: str, payload: dict = Body(default={})):
    """为电子结构任务构建输入文件（从 opt 导入或外部结构）。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "ele":
            return JSONResponse(status_code=400, content=fail("仅电子结构任务可构建输入文件"))
        source_type = str(payload.get("source_type", "opt"))
        source_task_id = payload.get("source_task_id")
        ele_types = payload.get("ele_types") or payload.get("ele_type") or []
        if isinstance(ele_types, str):
            ele_types = [ele_types]
        ele_types = [str(t) for t in ele_types if t]
        params = payload.get("params") or {}
        result = build_ele_inputs(
            project["server"],
            project,
            task,
            source_type,
            source_task_id,
            ele_types,
            params,
        )
        task["input_source"] = {
            "poscar_from": (
                f"{result['source_dir']}/CONTCAR" if result.get("source_dir") else "external/POSCAR"
            ),
            "potcar_from": (
                f"{result['source_dir']}/POTCAR" if result.get("source_dir") else None
            ),
            "kpoints_from": (
                f"{result['source_dir']}/KPOINTS" if result.get("source_dir") else None
            ),
        }
        task["subtype"] = ",".join(ele_types) if ele_types else None
        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == task_id:
                t.update(task)
        save_db(db)
        _audit_log(
            project["name"], task_id, result["ele_dir"],
            f"build-ele-inputs type={ele_type}", "OK",
        )
        return ok("电子结构输入文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"构建电子结构输入失败：{e}"))


@router.post("/tasks/{task_id}/create-neb-files")
def create_neb(task_id: str, payload: dict = Body(default={})):
    """根据初末态 opt 任务创建 NEB 计算文件（nebmake.pl 插值）。"""
    try:
        project, task = _resolve_task(task_id)
        result = core_create_neb(project, task, payload)
        return ok("NEB 计算文件已生成", result)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ActionError as e:
        return JSONResponse(status_code=e.status_code, content=fail(e.message, e.data or None))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"创建 NEB 计算文件失败：{e}"))
@router.patch("/tasks/{task_id}")
def rename_task(task_id: str, payload: RenameTaskPayload):
    """重命名独立任务：同步更新本地/远端目录与数据库。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("group"):
            return JSONResponse(
                status_code=400,
                content=fail("组内任务请通过结构管理调整，不支持直接重命名"),
            )
        new_name = payload.model_name.strip()
        if not NAME_PATTERN.fullmatch(new_name):
            return JSONResponse(
                status_code=400,
                content=fail("名称仅支持字母、数字、下划线、@，且不能以数字开头"),
            )
        if any(t.get("model_name") == new_name for t in project["tasks"]):
            return JSONResponse(status_code=400, content=fail("项目中已存在同名任务"))
        old_name = task.get("model_name", "")
        old_local = resolve_local_path(task.get("dir_path", ""))
        new_local = old_local.parent / new_name
        if old_local.is_dir() and old_local != new_local and not new_local.exists():
            shutil.move(str(old_local), str(new_local))
        old_remote = resolve_remote_path(project.get("server"), task.get("remote_dir", ""))
        new_remote = ""
        if old_remote and old_name:
            new_remote = old_remote.rsplit("/", 1)[0] + f"/{new_name}"
            from ssh import run_remote

            r = run_remote(
                project.get("server"),
                f'bash -c \'[ -d "{old_remote}" ] && [ ! -e "{new_remote}" ] '
                f'&& mv "{old_remote}" "{new_remote}" || true\'',
                timeout=60,
            )
            if r["exit_code"] != 0:
                return JSONResponse(
                    status_code=500,
                    content=fail(f"远程目录重命名失败：{(r['stderr'] or r['stdout']).strip()}"),
                )
        task["model_name"] = new_name
        from paths import to_local_rel

        task["dir_path"] = to_local_rel(str(new_local))
        if new_remote:
            task["remote_dir"] = to_remote_rel(project.get("server"), new_remote)
        from storage import save_db

        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        for t in proj["tasks"]:
            if t.get("task_id") == task_id:
                t.update(task)
        save_db(db)
        return ok(
            "任务已重命名",
            {
                "task_id": task_id,
                "model_name": new_name,
                "dir_path": task["dir_path"],
                "remote_dir": task["remote_dir"],
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"重命名失败：{e}"))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    """删除最末端子项：本地目录移入回收站，记录从数据库移除（远端目录不自动删除）。"""
    try:
        project, task = _resolve_task(task_id)
        children = [
            t for t in project["tasks"]
            if t.get("parent_task_id") == task_id
        ]
        if children:
            return JSONResponse(
                status_code=400,
                content=fail("该任务存在续算子任务，请先删除子任务"),
            )
        trash_path = None
        old_local = resolve_local_path(task.get("dir_path", ""))
        if old_local.is_dir():
            trash_dir = DATA_DIR / "trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            trash_path = trash_dir / f"{task_id}_{int(datetime.now().timestamp())}"
            shutil.move(str(old_local), str(trash_path))
        from storage import save_db

        db = load_db()
        proj = next(p for p in db["projects"] if p["name"] == project["name"])
        proj["tasks"] = [t for t in proj["tasks"] if t.get("task_id") != task_id]
        save_db(db)
        return ok(
            "任务已删除",
            {
                "task_id": task_id,
                "model_name": task.get("model_name"),
                "local_trash": str(trash_path) if trash_path else None,
                "remote_dir": task.get("remote_dir"),
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"删除任务失败：{e}"))


def _submit_preflight_lines(task_type: str, submit_script: str) -> list:
    """提交前的输入文件检查（shell 片段）：把缺失项累积到 `EMPTY`。

    - **普通任务**（opt / frac / ele）：工作目录下 POSCAR / INCAR / KPOINTS / POTCAR /
      vasp.lsf 都必须非空；
    - **NEB 任务**：工作目录（`neb/<组名>/neb`，或续算 `conN`）里是
      INCAR / KPOINTS / POTCAR / vasp.lsf + **映像子目录 00..NN**，
      POSCAR 在**每个映像目录**里（VTST 约定，根目录没有 POSCAR）。
      因此按 INCAR 的 `IMAGES` 推算应有 `00 .. (IMAGES+1)`，逐个检查非空 POSCAR；
      INCAR 里没有 IMAGES 时退化为"至少 3 个数字映像目录且每个都有非空 POSCAR"。
    """
    common = [
        'EMPTY=""',
        "for f in INCAR KPOINTS POTCAR " + submit_script + "; do",
        '  [ -s "$f" ] || EMPTY="$EMPTY $f"',
        "done",
    ]
    if task_type != "neb":
        return [
            'EMPTY=""',
            "for f in POSCAR INCAR KPOINTS POTCAR " + submit_script + "; do",
            '  [ -s "$f" ] || EMPTY="$EMPTY $f"',
            "done",
        ]
    return [
        *common,
        "IMAGES=$(grep -iE '^[[:space:]]*IMAGES[[:space:]]*=' INCAR | tail -1 | tr -dc '0-9')",
        'if [ -n "$IMAGES" ]; then',
        "  EXPECT=$((IMAGES + 2))",
        "  i=0",
        '  while [ "$i" -lt "$EXPECT" ]; do',
        '    d=$(printf "%02d" "$i")',
        '    [ -s "$d/POSCAR" ] || EMPTY="$EMPTY $d/POSCAR"',
        "    i=$((i + 1))",
        "  done",
        "else",
        '  NIMG=$(ls -d [0-9][0-9] 2>/dev/null | wc -l | tr -d " ")',
        '  [ "$NIMG" -ge 3 ] || EMPTY="$EMPTY 映像目录(00..NN)"',
        '  for d in $(ls -d [0-9][0-9] 2>/dev/null); do',
        '    [ -s "$d/POSCAR" ] || EMPTY="$EMPTY $d/POSCAR"',
        "  done",
        "fi",
    ]


@router.post("/tasks/{task_id}/submit")
def submit_task(task_id: str):
    """提交作业：远程目录内执行 bsub < vasp.lsf，登记 job_id 并将状态更新为 queued。"""
    try:
        project, task = _resolve_task(task_id)
        data = core_submit(project, task)
        return ok(f"作业 {data['job_id']} 已提交到队列", data)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ActionError as e:
        return JSONResponse(status_code=e.status_code, content=fail(e.message, e.data or None))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"提交作业失败：{e}"))
@router.post("/tasks/{task_id}/archive")
def archive_task(task_id: str):
    """关闭（归档）任务：只改状态，本地/远端文件都不动。

    - 前端在任务未正常结束（状态不是 completed）时会弹窗提醒，后端不做硬性拦截；
    - **自由能组的结构优化主任务**：连带归档其频率矫正（frac）子任务，
      返回 `archived_siblings` 与归档前的 frac 状态（前端据此提示）。
    """
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    previous = str(task.get("status") or "")
    frac = free_energy_frac_task(project, task)
    frac_status = str(frac.get("status") or "") if frac else None
    if previous == "archived" and (frac is None or frac_status == "archived"):
        return JSONResponse(status_code=409, content=fail("任务已经处于关闭（归档）状态"))
    siblings: List[Dict[str, Any]] = []
    try:
        with db_transaction() as db:
            if previous != "archived":
                update_task_status(
                    db,
                    project["name"],
                    task_id,
                    "archived",
                    {"archived_at": now_iso(), "archived_from": previous},
                )
            # 自由能主任务归档 → 频率矫正子任务一并归档（否则项目无法关闭）
            fresh_project = next(
                (p for p in db.get("projects", []) if p.get("name") == project["name"]),
                None,
            )
            fresh_task = (
                next(
                    (
                        t
                        for t in fresh_project.get("tasks", [])
                        if t.get("task_id") == task_id
                    ),
                    None,
                )
                if fresh_project
                else None
            )
            if fresh_project and fresh_task:
                sibling = free_energy_frac_task(fresh_project, fresh_task)
                if sibling is not None and str(sibling.get("status")) != "archived":
                    sibling_prev = str(sibling.get("status") or "")
                    update_task_status(
                        db,
                        project["name"],
                        str(sibling["task_id"]),
                        "archived",
                        {"archived_at": now_iso(), "archived_from": sibling_prev},
                    )
                    siblings.append(
                        {
                            "task_id": str(sibling["task_id"]),
                            "model_name": str(sibling.get("model_name") or ""),
                            "previous_status": sibling_prev,
                            "was_completed": sibling_prev == "completed",
                        }
                    )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"关闭任务失败：{e}"))
    # 归档后静默拉回最新计算目录的 OUTCAR / OSZICAR 到本地镜像（失败不影响归档）
    _schedule_archive_outputs(str(project.get("name") or ""), task_id)
    return ok(
        "任务已关闭（归档）",
        {
            "task_id": task_id,
            "project_name": project["name"],
            "new_status": "archived",
            "previous_status": previous,
            "was_completed": previous == "completed",
            "frac_status": frac_status,
            "archived_siblings": siblings,
        },
    )


@router.post("/tasks/{task_id}/unarchive")
def unarchive_task(task_id: str):
    """重新打开已归档任务：恢复到归档前的状态（默认 pending）。

    自由能组主任务重新打开时，**连带重新打开其频率矫正子任务**（保持成对）。
    """
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    if str(task.get("status") or "") != "archived":
        return JSONResponse(status_code=409, content=fail("任务未处于关闭（归档）状态"))
    restore = str(task.get("archived_from") or "")
    if restore not in STATUS_ENUM or restore == "archived":
        restore = "pending"
    siblings: List[Dict[str, Any]] = []
    try:
        with db_transaction() as db:
            update_task_status(
                db,
                project["name"],
                task_id,
                restore,
                {"reopened_at": now_iso()},
            )
            fresh_project = next(
                (p for p in db.get("projects", []) if p.get("name") == project["name"]),
                None,
            )
            fresh_task = (
                next(
                    (
                        t
                        for t in fresh_project.get("tasks", [])
                        if t.get("task_id") == task_id
                    ),
                    None,
                )
                if fresh_project
                else None
            )
            if fresh_project and fresh_task:
                sibling = free_energy_frac_task(fresh_project, fresh_task)
                if sibling is not None and str(sibling.get("status")) == "archived":
                    sibling_restore = str(sibling.get("archived_from") or "")
                    if sibling_restore not in STATUS_ENUM or sibling_restore == "archived":
                        sibling_restore = "pending"
                    update_task_status(
                        db,
                        project["name"],
                        str(sibling["task_id"]),
                        sibling_restore,
                        {"reopened_at": now_iso()},
                    )
                    siblings.append(
                        {
                            "task_id": str(sibling["task_id"]),
                            "model_name": str(sibling.get("model_name") or ""),
                            "new_status": sibling_restore,
                        }
                    )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"重新打开任务失败：{e}"))
    return ok(
        "任务已重新打开",
        {
            "task_id": task_id,
            "project_name": project["name"],
            "new_status": restore,
            "reopened_siblings": siblings,
        },
    )


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str):
    """停止作业：远程 bkill 终止运行中的作业，任务状态回退为待提交。"""
    try:
        project, task = _resolve_task(task_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))

    job_id = task.get("job_id")
    if not job_id or task.get("status") not in ("queued", "running"):
        return JSONResponse(
            status_code=409,
            content=fail("作业未在排队/运行中，无法停止"),
        )

    server = project.get("server")
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    try:
        result = ssh.run_remote(
            server,
            f'bash -c "source {profile} >/dev/null 2>&1; bkill {job_id}"',
            timeout=60,
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001 - SSH 连接类错误
        return JSONResponse(
            status_code=502,
            content=fail(f"无法连接远程服务器，请检查 SSH 配置：{e}"),
        )
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    # LSF：对已结束/不存在的作业执行 bkill 会输出 "Job <id>: Job has already
    # finished" 且退出码非 0 —— 作业实际上已停止，按停止成功处理（归档为待提交）
    already_finished = bool(re.search(r"already finished", raw, re.IGNORECASE))
    if result.get("exit_code") != 0 and not already_finished:
        _audit_log(project["name"], task_id, str(job_id), "bkill", f"FAILED: {raw}")
        return JSONResponse(status_code=500, content=fail(f"停止作业失败：{raw or '未知错误'}"))

    # 作业已终止：状态回退为待提交（可重新提交或续算）
    try:
        with db_transaction() as db:
            update_task_status(db, project["name"], task_id, "pending")
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001 - 状态落库失败不影响停止事实
        _audit_log(project["name"], task_id, str(job_id), "bkill", f"DB_WARN: {e}")
    _audit_log(
        project["name"],
        task_id,
        str(job_id),
        "bkill",
        "OK (already finished)" if already_finished else "OK",
    )
    return ok(
        "作业已停止（作业此前已结束）" if already_finished else "作业已停止",
        {
            "job_id": job_id,
            "new_status": "pending",
            "already_finished": already_finished,
        },
    )


# ------------------------------------------------------------ 输入文件（v0.8.2）
# 三层职责：远端 conN（运行真相）→ 本地镜像 files/（同步副本，v0.8.7 前是 inputs/）
# → 草稿（下次续算生效）。方案与口径见 process.md §6.11；
# 同步成本 = 1 次 exec + 4 次 SFTP 小文件。


def _find_task_in_db(db: Dict[str, Any], task_id: str) -> Dict[str, Any] | None:
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("task_id") == task_id:
                return task
    return None


def _push_input_file(
    project: Dict[str, Any],
    task_id: str,
    name: str,
    text: str,
    work_dir: str,
) -> tuple:
    """「同步到远端」之后的本地状态更新（v0.8.7）。

    1. 更新本地镜像 `<任务目录>/files/<name>`（内容就是刚推上去的文本）；
    2. 用刚写入的内容重算 `input_state.files[name]` 元数据（哈希/参数/k 网格/结构摘要），
       界面上的"本次计算值"立刻变成新值，不再显示"已修改"；
    3. 把该文件的**未生效台账条目标记已应用**（`applied_in="remote"`）、清掉该文件草稿；
    4. 落库并返回 `(刷新后的输入面板载荷, 被应用的 key 列表)`。
    """
    now = now_iso()
    with db_transaction() as db:
        current = _find_task_in_db(db, task_id)
        if current is None:
            raise LookupError(f"任务 {task_id} 不存在")
        task_for_path = {**current, "project_name": project.get("name", "")}
        # ① 本地镜像
        try:
            target = snapshot_dir(task_for_path) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except OSError:
            pass
        # ② 元数据（与 build_snapshot 同口径）
        meta: Dict[str, Any] = {"hash": text_hash(text), "size": len(text)}
        if name == "INCAR":
            meta["params"] = parse_incar_text(text)
        elif name == "KPOINTS":
            mesh, note = parse_kpoints_mesh(text)
            meta["mesh"] = mesh
            meta["mesh_note"] = note
        elif name in ("POSCAR", "CONTCAR"):
            meta.update(poscar_meta(text))
        state = dict(current.get("input_state") or {})
        files_meta = dict(state.get("files") or {})
        files_meta[name] = meta
        state["files"] = files_meta
        # ③ 台账：这条修改已经推到远端，不再"待生效"
        state, applied = mark_file_applied(state, name, "remote")
        source = dict(state.get("source") or {})
        source.update(
            {
                "kind": "push",
                "synced_at": now,
                "pushed": {"file": name, "at": now, "dir": work_dir},
            }
        )
        state["source"] = source
        current["input_state"] = state
        updated = dict(current)
    # 结构文件推到远端后，本地镜像也换了内容 → 顺手重算 CIF（3D 视图立刻反映新结构）
    if name in ("POSCAR", "CONTCAR"):
        refresh_structure_cif(project, updated, name)
    return _input_payload(project, updated), applied


def _input_payload(project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """组装输入文件面板所需的全部数据：本地镜像 + 草稿 + 变更台账 + 3D 用 CIF。

    v0.8.7 起"本地镜像"就是 `<任务目录>/files/`（原 inputs/ 快照已合并进来），
    `text` 直接读镜像里的文件；`files[name]` 的元数据仍以远端"本次计算"为准
    （有未生效草稿的文件带 `protected: true`，只跳过覆盖、元数据照更新）。
    """
    state = dict(task.get("input_state") or {})
    files_meta = dict(state.get("files") or {})
    files: Dict[str, Any] = {}
    for name in ("INCAR", "KPOINTS", "POSCAR", "CONTCAR"):
        text = read_snapshot_text(task, name)
        if text is None:
            continue
        files[name] = {**files_meta.get(name, {}), "text": text}

    poscar_cif = read_snapshot_cif(task, "POSCAR")
    if poscar_cif is None:
        try:
            poscar_cif = read_or_convert_cif(project, task, "POSCAR")
        except permissions.PermissionDenied:
            raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
        except Exception:  # noqa: BLE001 - 转换失败不阻塞面板
            poscar_cif = None
    contcar_cif = read_snapshot_cif(task, "CONTCAR")

    return {
        "task_id": str(task.get("task_id") or ""),
        "source": state.get("source"),
        "synced": bool(state.get("source")),
        "files": files,
        "draft": state.get("draft") or {},
        "changes": state.get("changes") or [],
        "last_applied": state.get("last_applied"),
        "pending": has_pending(state),
        "poscar_cif": poscar_cif,
        "contcar_cif": contcar_cif,
    }


def _sync_input_now(project: Dict[str, Any], task: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """同步一次远端输入并落库，返回更新后的 payload。"""
    snapshot = build_snapshot(
        str(project.get("server") or ""),
        {**task, "project_name": project.get("name")},
        kind=kind,
    )
    updated: Dict[str, Any] = {}
    with db_transaction() as db:
        current = _find_task_in_db(db, str(task.get("task_id") or ""))
        if current is None:
            raise LookupError(f"任务 {task.get('task_id')} 不存在")
        current["input_state"] = merge_snapshot(current, snapshot)
        updated = dict(current)
    return _input_payload(project, updated)


def _schedule_input_sync(project_name: str, task_id: str, delay: float = 2.0) -> None:
    """提交作业成功后后台同步一次输入参数（不阻塞接口返回）。"""

    def worker() -> None:
        time.sleep(delay)
        try:
            db = load_db()
            project = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = next(
                (
                    t
                    for t in (project or {}).get("tasks", [])
                    if t.get("task_id") == task_id
                ),
                None,
            )
            if project is None or task is None:
                return
            payload = _sync_input_now(project, task, "submit")
            _audit_log(
                project_name,
                task_id,
                str(((payload.get("source") or {}).get("remote_dir")) or ""),
                "input-sync",
                f"OK kind=submit job={task.get('job_id')}",
            )
        except permissions.PermissionDenied:
            raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
        except Exception as e:  # noqa: BLE001 - 后台同步失败只记审计
            _audit_log(project_name, task_id, "", "input-sync", f"FAILED: {e}")

    threading.Thread(target=worker, daemon=True, name=f"input-sync-{task_id}").start()


def _schedule_archive_outputs(
    project_name: str, task_id: str, delay: float = 1.5
) -> None:
    """归档（关闭任务）后后台静默拉取最新 OUTCAR / OSZICAR 到本地镜像。

    只影响本地文件：失败、远端缺文件、SSH 未连接都只记一条审计日志，不回传给用户。
    """

    def worker() -> None:
        time.sleep(delay)
        try:
            db = load_db()
            project = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = next(
                (
                    t
                    for t in (project or {}).get("tasks", [])
                    if t.get("task_id") == task_id
                ),
                None,
            )
            if project is None or task is None:
                return
            result = download_archive_outputs(str(project.get("server") or ""), task)
            images = result.get("images") or []
            image_saved = result.get("image_saved") or []
            image_missing = result.get("image_missing") or []
            extra = ""
            if images:
                extra = (
                    f" images={len(images)} img_saved={len(image_saved)}"
                    f" img_missing={len(image_missing)}"
                )
            elif image_missing:
                extra = f" img_missing={len(image_missing)}"
            if result.get("overwrote_draft"):
                extra += f" overwrote_draft={','.join(result['overwrote_draft'])}"
            _audit_log(
                project_name,
                task_id,
                str(result.get("source_dir") or ""),
                "archive-outputs",
                f"OK saved={','.join(result.get('saved') or []) or '-'} "
                f"missing={','.join(result.get('missing') or []) or '-'}{extra}",
            )
        except permissions.PermissionDenied:
            raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
        except Exception as e:  # noqa: BLE001 - 后台下载失败只记审计
            _audit_log(project_name, task_id, "", "archive-outputs", f"FAILED: {e}")

    threading.Thread(
        target=worker, daemon=True, name=f"archive-outputs-{task_id}"
    ).start()


@router.get("/tasks/{task_id}/input")
def read_task_input(task_id: str):
    """输入文件面板数据：远端快照（含参数）+ 草稿 + 变更台账 + 3D 用 CIF。"""
    try:
        project, task = _resolve_task(task_id)
        return ok("查询成功", _input_payload(project, task))
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取输入文件状态失败：{e}"))


@router.post("/tasks/{task_id}/input/sync")
def sync_task_input(task_id: str, payload: dict = Body(default={})):
    """同步远端最新计算目录的输入文件（1 次 exec + 4 次 SFTP 小文件下载）。"""
    try:
        project, task = _resolve_task(task_id)
        kind = str((payload or {}).get("kind") or "manual")
        return ok("已同步远端最新参数", _sync_input_now(project, task, kind))
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content=fail(f"同步失败：{e}"))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"同步输入文件失败：{e}"))


@router.put("/tasks/{task_id}/input/draft")
def update_task_input_draft(task_id: str, payload: dict = Body(default={})):
    """写入参数草稿（不碰远端）：INCAR 按参数合并，KPOINTS 只改 k 网格。"""
    try:
        project, task = _resolve_task(task_id)
        file_name = str((payload or {}).get("file") or "").upper()
        if file_name not in ("INCAR", "KPOINTS"):
            return JSONResponse(
                status_code=400, content=fail("仅支持 file=INCAR / KPOINTS 的草稿")
            )
        updated: Dict[str, Any] = {}
        with db_transaction() as db:
            current = _find_task_in_db(db, task_id)
            if current is None:
                return JSONResponse(status_code=404, content=fail("任务不存在"))
            state = dict(current.get("input_state") or {})
            if file_name == "INCAR":
                state = set_incar_draft(state, (payload or {}).get("params") or {})
            else:
                state = set_kpoints_draft(state, (payload or {}).get("mesh") or [])
            current["input_state"] = state
            updated = dict(current)
        data = _input_payload(project, updated)
        count = len([c for c in data["changes"] if not c.get("applied_at")])
        return ok(
            f"已记录参数修改（共 {count} 项待生效，将在下次续算时应用）", data
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"保存参数草稿失败：{e}"))


@router.delete("/tasks/{task_id}/input/draft/{file_name}")
def revert_task_input_draft(task_id: str, file_name: str):
    """撤销某个文件的参数草稿。"""
    try:
        project, task = _resolve_task(task_id)
        target = file_name.upper()
        if target not in ("INCAR", "KPOINTS"):
            return JSONResponse(status_code=400, content=fail("仅支持撤销 INCAR / KPOINTS"))
        updated: Dict[str, Any] = {}
        with db_transaction() as db:
            current = _find_task_in_db(db, task_id)
            if current is None:
                return JSONResponse(status_code=404, content=fail("任务不存在"))
            state = dict(current.get("input_state") or {})
            current["input_state"] = revert_draft(state, target)
            updated = dict(current)
        return ok(f"已撤销 {target} 的参数修改", _input_payload(project, updated))
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"撤销参数修改失败：{e}"))


@router.post("/tasks/{task_id}/upload-incar")
def upload_incar(task_id: str, payload: dict = Body(default={})):
    """本地生成 INCAR 并上传到远端最新目录；旧文件备份为 old_INCAR。"""
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        # 最新目录：最大编号 conN（存在即算），无则主目录；不创建新目录
        servers = load_servers()
        batch_path = servers.get(server, {}).get("batch_check_path")
        latest = ""
        if batch_path:
            try:
                latest = _remote_latest_con(server, remote_dir, batch_path)
            except permissions.PermissionDenied:
                raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
            except Exception:  # noqa: BLE001 - 定位失败回退主目录
                latest = ""
        work_dir = f"{remote_dir}/{latest}" if latest else remote_dir

        content = payload.get("content")
        params = payload.get("params")
        old = _download_remote_text(server, f"{work_dir}/INCAR") or ""
        if content:
            new_text = str(content)
            warnings = []
        elif params:
            new_text, warnings = modify_incar(old, params)
        else:
            return JSONResponse(
                status_code=400,
                content=fail("请提供 content（完整文本）或 params（参数字典）"),
            )

        # 备份旧文件（存在则 mv 为 old_INCAR，old_INCAR 已存在则覆盖）
        ssh.run_remote(
            server,
            f'bash -c \'[ -f "{work_dir}/INCAR" ] && mv -f "{work_dir}/INCAR" "{work_dir}/old_INCAR" || true\'',
            timeout=30,
        )
        _write_remote_file(server, f"{work_dir}/INCAR", new_text)
        # 同步到远端 = 立即应用：本地镜像/元数据一并刷新，草稿台账标记已应用
        payload_state, applied = _push_input_file(project, task_id, "INCAR", new_text, work_dir)
        _audit_log(
            project["name"],
            task_id,
            work_dir,
            "upload-incar",
            f"OK backup={'old_INCAR' if old else 'none'} applied={','.join(applied) or '-'}",
        )
        return ok(
            "INCAR 已同步到远端",
            {
                "dir": work_dir,
                "backup_file": "old_INCAR" if old else None,
                "warnings": warnings,
                "applied": applied,
                "state": payload_state,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"上传 INCAR 失败：{e}"))


SELECTIVE_DYNAMICS_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "selective_dynamics.py"


@router.post("/tasks/{task_id}/selective-dynamics")
def apply_selective_dynamics(task_id: str, payload: dict = Body(default={})):
    """按选中的原子生成带 `Selective Dynamics` 的 POSCAR（v0.8.7）。

    调用仓库里的 `scripts/selective_dynamics.py`（纯标准库）在临时目录里生成结果：

    - 入参：`content`（POSCAR 文本，缺省用本地镜像 `files/POSCAR`）、
      `mode`（manual/elements/z_range）、`atoms`（[{element,poscarIndex}]）、
      `elements`、`zRange`、`numbering`（element/global）、`labels`、`syncRemote`；
    - 本地：写回 `<任务>/files/POSCAR`，旧文件备份为 `files/old_POSCAR`，
      并刷新 `input_state.files.POSCAR` 元数据；
    - `syncRemote=true` 时同时写入远端最新目录（旧文件备份为 `old_POSCAR`）。
    """
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        mode = str(payload.get("mode") or "manual")
        numbering = str(payload.get("numbering") or "element")
        labels = bool(payload.get("labels", True))
        sync_remote = bool(payload.get("syncRemote"))

        content = str(payload.get("content") or "")
        if not content.strip():
            mirror = _resolve_task_dir(task_id) / "files" / "POSCAR"
            if mirror.is_file():
                content = mirror.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            return JSONResponse(
                status_code=400,
                content=fail("没有可用的 POSCAR：请先导入/同步 POSCAR，或在 content 里传文本"),
            )
        if not SELECTIVE_DYNAMICS_SCRIPT.is_file():
            return JSONResponse(
                status_code=500,
                content=fail(f"缺少脚本 {SELECTIVE_DYNAMICS_SCRIPT}"),
            )

        args = [
            sys.executable,
            str(SELECTIVE_DYNAMICS_SCRIPT),
            "--poscar",
            "{tmp}/POSCAR",
            "--mode",
            mode,
            "--numbering",
            numbering,
            "--backup-mode",
            "keep_first",
        ]
        if not labels:
            args.append("--no-labels")
        if mode == "manual":
            indices = []
            for atom in payload.get("atoms") or []:
                if isinstance(atom, dict):
                    value = atom.get("poscarIndex")
                    if value is None and atom.get("index") is not None:
                        value = int(atom["index"]) + 1
                    if value is not None:
                        indices.append(str(int(value)))
                elif atom is not None:
                    indices.append(str(atom))
            if not indices:
                return JSONResponse(
                    status_code=400,
                    content=fail("manual 模式需要在 POSCAR 图上选中原子（或传 atoms）"),
                )
            args += ["--fixed-atoms", ",".join(sorted(set(indices), key=int))]
        elif mode == "elements":
            elements = [str(e).strip() for e in (payload.get("elements") or []) if str(e).strip()]
            if not elements:
                return JSONResponse(
                    status_code=400, content=fail("elements 模式需要传 elements（如 [\"Fe\"]）")
                )
            args += ["--fixed-elements", ",".join(elements)]
        elif mode == "z_range":
            z_range = payload.get("zRange") or [0.0, 0.25]
            args += ["--z-range", str(float(z_range[0])), str(float(z_range[1]))]
        else:
            return JSONResponse(
                status_code=400,
                content=fail("mode 仅支持 manual / elements / z_range"),
            )

        with tempfile.TemporaryDirectory(prefix="sd_") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "POSCAR").write_text(content, encoding="utf-8")
            proc = subprocess.run(
                [a.replace("{tmp}", tmp) for a in args],
                capture_output=True,
                text=True,
                timeout=60,
            )
            log = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode != 0 or not (tmp_path / "POSCAR").is_file():
                return JSONResponse(
                    status_code=400,
                    content=fail(f"生成 Selective Dynamics 失败：{log.strip()[-400:] or '未知错误'}"),
                )
            new_text = (tmp_path / "POSCAR").read_text(encoding="utf-8", errors="replace")

        # ---- 写本地镜像（旧文件备份为 files/old_POSCAR）----
        files_dir = _resolve_task_dir(task_id) / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        local_backup = ""
        target = files_dir / "POSCAR"
        if target.is_file():
            backup = files_dir / "old_POSCAR"
            shutil.copy2(target, backup)
            local_backup = str(backup)

        # ---- 可选：同步到远端最新目录 ----
        work_dir = ""
        remote_backup = None
        if sync_remote:
            remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
            if not remote_dir:
                return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
            work_dir, had_old = _prepare_remote_write(
                server, remote_dir, "POSCAR", "old_POSCAR"
            )
            _write_remote_file(server, f"{work_dir}/POSCAR", new_text)
            remote_backup = "old_POSCAR" if had_old else None

        payload_state, _applied = _push_input_file(
            project, task_id, "POSCAR", new_text, work_dir
        )
        summary = "；".join(
            line.strip() for line in log.splitlines() if line.strip().startswith(("结构：", "固定：", "注意：", "规则："))
        )
        _audit_log(
            project["name"], task_id, work_dir or str(files_dir), "selective-dynamics",
            f"OK mode={mode} numbering={numbering} labels={labels} sync_remote={sync_remote}",
        )
        return ok(
            "已生成带 Selective Dynamics 的 POSCAR",
            {
                "text": new_text,
                "mode": mode,
                "numbering": numbering,
                "labels": labels,
                "summary": summary,
                "local_backup": local_backup or None,
                "remote_dir": work_dir or None,
                "remote_backup": remote_backup,
                "synced_remote": sync_remote,
                "state": payload_state,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content=fail("生成超时（60s）"))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"生成 Selective Dynamics 失败：{e}"))


@router.post("/tasks/{task_id}/upload-poscar")
def upload_poscar(task_id: str, payload: dict = Body(default={})):
    """把导入的 POSCAR 写入远端最新目录；旧文件备份为 `old_POSCAR`（逻辑同 INCAR）。"""
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        content = str(payload.get("content") or "")
        if not content.strip():
            return JSONResponse(status_code=400, content=fail("请提供 content（POSCAR 全文）"))

        # 一次 exec：定位最新 conN + 备份 old_POSCAR；随后 SFTP 写内容
        work_dir, had_old = _prepare_remote_write(
            server, remote_dir, "POSCAR", "old_POSCAR"
        )
        _write_remote_file(server, f"{work_dir}/POSCAR", content)

        # 本地镜像 + 元数据同步刷新（POSCAR 没有草稿，applied 为空）
        payload_state, applied = _push_input_file(project, task_id, "POSCAR", content, work_dir)
        local_path = str(_resolve_task_dir(task_id) / "files" / "POSCAR")

        _audit_log(
            project["name"], task_id, work_dir, "upload-poscar",
            f"OK size={len(content)} applied={','.join(applied) or '-'}",
        )
        return ok(
            "POSCAR 已同步到远端",
            {
                "dir": work_dir,
                "remote_path": f"{work_dir}/POSCAR",
                "backup_file": "old_POSCAR" if had_old else None,
                "size": len(content),
                "local_path": local_path,
                "applied": applied,
                "state": payload_state,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"上传 POSCAR 失败：{e}"))


@router.post("/tasks/{task_id}/generate-potcar")
def generate_potcar(task_id: str):
    """在远端"当前目录"运行 `pos2pot` 生成 POTCAR，返回输出与结果摘要。

    - 远端脚本实际是 `/data/gpfs03/mdye/projects/potcar/pos2pot.sh`：**递归**遍历当前目录下
      所有含 `POSCAR` 的子目录并调用 `potcar.sh $(sed -n 6p POSCAR)`；`pos2pot` 只是
      `~/.bashrc` 里的 alias，非交互 exec 看不到，因此这里按
      `pos2pot` → `pos2pot.sh` → 绝对路径 依次解析。
    - 命令可用 `servers.json` 的 `pos2pot_cmd` 覆盖（写裸命令或绝对路径，不带参数）。
    - 单次 exec 完成：跑命令 + 报告 POTCAR 大小/行数/元素，不额外发请求。
    """
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        configured = str(
            load_servers().get(server, {}).get("pos2pot_cmd") or "pos2pot"
        ).strip()

        # 单次 exec：脚本内部自己定位最新 conN（不额外发请求）
        script = "\n".join(
            [
                'cd "' + remote_dir + '" 2>/dev/null || { echo "@@@NO_DIR"; exit 3; }',
                'LATEST=$(ls -d con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -1)',
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
                # 元素取每个块首的 TITEL 行（`TITEL  = PAW_PBE Al 04Jan2001` → Al）
                '  echo "ELEMENTS=$(awk \'/^ *TITEL/{printf "%s,", $4}\' POTCAR)"',
                '  echo "NBLOCKS=$(grep -c \'^ *TITEL\' POTCAR)"',
                '  head -n 2 POTCAR',
                "else",
                '  echo "MISSING"',
                "fi",
                'echo "@@@POTCAR_END"',
            ]
        )
        script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        result = ssh.run_remote(server, f"echo {script_b64} | base64 -d | bash", timeout=120)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:  # noqa: BLE001 - SSH 连接类错误
        return JSONResponse(
            status_code=502,
            content=fail(f"运行 pos2pot 失败（SSH）：{e}"),
        )

    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    work_match = re.search(r"@@@WORK=(.+)", raw)
    work_dir = work_match.group(1).strip() if work_match else remote_dir
    if "@@@NO_DIR" in raw:
        return JSONResponse(status_code=404, content=fail(f"远程目录不存在：{work_dir}"))
    not_found = re.search(r"@@@NOT_FOUND=(\S*)", raw)
    if not_found:
        return JSONResponse(
            status_code=400,
            content=fail(
                f"远端找不到命令 {not_found.group(1) or 'pos2pot'}"
                "（可在 servers.json 用 pos2pot_cmd 指定绝对路径）"
            ),
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
    potcar = {
        "exists": generated,
        "size": int(size_match.group(1)) if size_match else 0,
        "lines": int(lines_match.group(1)) if lines_match else 0,
        "elements_count": int(blocks_match.group(1)) if blocks_match else len(elements),
        "elements": elements,
    }
    _audit_log(
        project["name"], task_id, work_dir, "generate-potcar",
        f"rc={rc} potcar={'ok' if generated else 'missing'} size={potcar['size']}",
    )
    return ok(
        "POTCAR 已生成" if generated else "pos2pot 执行结束，但未检测到 POTCAR",
        {
            "dir": work_dir,
            "command": command,
            "exit_code": rc,
            "output": output,
            "potcar": potcar,
            "generated": generated,
        },
    )


@router.post("/tasks/{task_id}/upload-submit-script")
def upload_submit_script(task_id: str, payload: dict = Body(default={})):
    """把前端生成的 `vasp.lsf` 写入远端最新目录（旧文件备份为 `old_vasp.lsf`）。

    与 INCAR / KPOINTS 的写入逻辑一致：
    - 目标目录 = 最大编号 conN（存在即算，续算后改脚本自然落到新目录），否则任务主目录；
    - 同名文件先 `mv -f` 成 `old_vasp.lsf`（已存在则覆盖），再写入新内容；
    - 文本统一 LF（`_write_remote_file`），并同步一份到本地镜像 `files/vasp.lsf`
      （`vasp.lsf` 不在四件套同步集合里，不会被同步流程覆盖）。
    """
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        content = str(payload.get("content") or "")
        if not content.strip():
            return JSONResponse(
                status_code=400, content=fail("请提供 content（完整脚本文本）")
            )

        # 一次 exec：定位最新 conN + 备份 old_vasp.lsf；随后 SFTP 写内容
        work_dir, had_old = _prepare_remote_write(
            server, remote_dir, "vasp.lsf", "old_vasp.lsf"
        )
        _write_remote_file(server, f"{work_dir}/vasp.lsf", content)

        local_path = ""
        try:
            # 本地镜像固定写 <任务目录>/files/（与输入四件套同一份镜像；
            # vasp.lsf 不参与同步覆盖，不会被远端四件套冲掉）
            target = _resolve_task_dir(task_id) / "files" / "vasp.lsf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            local_path = str(target)
        except permissions.PermissionDenied:
            raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
        except Exception:  # noqa: BLE001 - 本地镜像写失败不影响远端结果
            local_path = ""

        _audit_log(
            project["name"],
            task_id,
            work_dir,
            "upload-submit-script",
            f"OK backup={'old_vasp.lsf' if had_old else 'none'} size={len(content)}",
        )
        return ok(
            "提交脚本已写入远端",
            {
                "dir": work_dir,
                "remote_path": f"{work_dir}/vasp.lsf",
                "backup_file": "old_vasp.lsf" if had_old else None,
                "size": len(content),
                "local_path": local_path or None,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"写入提交脚本失败：{e}"))


@router.post("/tasks/{task_id}/upload-kpoints")
def upload_kpoints(task_id: str, payload: dict = Body(default={})):
    """上传 KPOINTS 到远端最新目录；旧文件备份为 old_KPOINTS（逻辑同 INCAR）。"""
    try:
        project, task = _resolve_task(task_id)
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        servers = load_servers()
        batch_path = servers.get(server, {}).get("batch_check_path")
        latest = ""
        if batch_path:
            try:
                latest = _remote_latest_con(server, remote_dir, batch_path)
            except permissions.PermissionDenied:
                raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
            except Exception:  # noqa: BLE001 - 定位失败回退主目录
                latest = ""
        work_dir = f"{remote_dir}/{latest}" if latest else remote_dir

        content = payload.get("content")
        if not content:
            return JSONResponse(status_code=400, content=fail("请提供 KPOINTS 内容（content）"))
        old = _download_remote_text(server, f"{work_dir}/KPOINTS") or ""
        ssh.run_remote(
            server,
            f'bash -c \'[ -f "{work_dir}/KPOINTS" ] && mv -f "{work_dir}/KPOINTS" "{work_dir}/old_KPOINTS" || true\'',
            timeout=30,
        )
        _write_remote_file(server, f"{work_dir}/KPOINTS", str(content))
        payload_state, applied = _push_input_file(
            project, task_id, "KPOINTS", str(content), work_dir
        )
        _audit_log(
            project["name"],
            task_id,
            work_dir,
            "upload-kpoints",
            f"OK backup={'old_KPOINTS' if old else 'none'} applied={','.join(applied) or '-'}",
        )
        return ok(
            "KPOINTS 已同步到远端",
            {
                "dir": work_dir,
                "backup_file": "old_KPOINTS" if old else None,
                "applied": applied,
                "state": payload_state,
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"上传 KPOINTS 失败：{e}"))


@router.post("/tasks/{task_id}/analysis/pdos")
def analyze_pdos(task_id: str, payload: dict = Body(default={})):
    """PDOS 分析：远端执行 vaspkit 111/113/115，生成文件下载回本地 files/analysis/。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "ele":
            return JSONResponse(status_code=400, content=fail("仅电子结构任务支持 PDOS 分析"))
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        mode = int(payload.get("mode", 111))
        if mode not in (111, 113, 115):
            return JSONResponse(status_code=400, content=fail("mode 仅支持 111 / 113 / 115"))
        groups = payload.get("groups") or []
        if mode == 115 and not groups:
            return JSONResponse(status_code=400, content=fail("自定义分析需提供至少一组元素与轨道"))

        lines = [str(mode)]
        if mode == 115:
            for g in groups:
                elem = str(g.get("elements", "")).strip()
                orb = str(g.get("orbitals", "")).strip()
                if elem:
                    lines.append(f"{elem} {orb}".strip())
            lines.append("")
        else:
            lines.append("")
        input_text = "\n".join(lines) + "\n"
        escaped = input_text.replace("\\", "\\\\").replace('"', '\\"')
        result = ssh.run_remote(
            server,
            f'bash -c \'cd "{remote_dir}" && printf "{escaped}" | vaspkit\'',
            timeout=180,
        )
        raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
        if result.get("exit_code") != 0:
            return JSONResponse(
                status_code=500,
                content=fail(f"vaspkit 执行失败：{raw or '未知错误'}"),
            )

        # 收集远端 *.dat 文件下载到本地 files/analysis/
        from task_paths import task_dir

        local_analysis = task_dir(project.get("name", ""), task) / "files" / "analysis"
        local_analysis.mkdir(parents=True, exist_ok=True)
        ls = ssh.run_remote(
            server,
            f'bash -c \'ls -1 "{remote_dir}"/*.dat 2>/dev/null\'',
            timeout=30,
        )
        downloaded = []
        for name in (ls.get("stdout") or "").splitlines():
            name = name.strip()
            if not name:
                continue
            local = local_analysis / Path(name).split("/")[-1]
            if ssh.download_file(server, f"{remote_dir}/{name}", str(local)):
                downloaded.append(str(local))
        _audit_log(
            project["name"],
            task_id,
            remote_dir,
            f"pdos mode={mode}",
            f"OK files={len(downloaded)}",
        )
        return ok(
            "PDOS 分析完成",
            {
                "mode": mode,
                "files": downloaded,
                "raw": raw[:800],
            },
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"PDOS 分析失败：{e}"))


@router.post("/tasks/{task_id}/calculate-correction")
def calculate_correction(task_id: str, payload: dict = Body(default={"temperature": 298.15})):
    """自由能矫正项：远端 frac 目录执行 vaspkit 501，解析 Thermal correction to G(T)。"""
    try:
        project, task = _resolve_task(task_id)
        if task.get("task_type") != "frac":
            return JSONResponse(status_code=400, content=fail("仅频率矫正任务可计算矫正项"))
        server = project.get("server")
        remote_dir = resolve_remote_path(server, task.get("remote_dir", "")).rstrip("/")
        if not remote_dir:
            return JSONResponse(status_code=404, content=fail("任务缺少远程目录"))
        temperature = float(payload.get("temperature", 298.15))
        try:
            correction = compute_g_correction(server, remote_dir, temperature)
        except permissions.PermissionDenied:
            raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
        except Exception as e:  # noqa: BLE001 - 计算失败返回明确错误
            return JSONResponse(status_code=500, content=fail(str(e)))
        with db_transaction() as db:
            proj = next(p for p in db["projects"] if p["name"] == project["name"])
            for t in proj["tasks"]:
                if t.get("task_id") == task_id:
                    t["correction"] = correction
                    t["correction_temp"] = temperature
                    t["correction_at"] = now_iso()
        _audit_log(
            project["name"],
            task_id,
            remote_dir,
            f"vaspkit501 T={temperature}",
            f"OK correction={correction}",
        )
        return ok(
            "矫正项计算完成",
            {"correction": correction, "temperature": temperature},
        )
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"计算矫正项失败：{e}"))
