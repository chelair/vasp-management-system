"""续算与输入文件构建：全部在远程服务器端完成，不经过本地文件传输。

按任务类型分发：
- opt / frac：同类型续算，任务目录下创建 conN，从最新有效输出目录
  （复用巡检 con* 扫描逻辑）复制 CONTCAR→POSCAR、POTCAR、KPOINTS、
  WAVECAR（移动）、提交脚本、INCAR（ISTART=1, ICHARG=0）。
- neb：NEB 续算 conN，端点 POSCAR 固定、中间映像 CONTCAR→POSCAR。
- ele：不提供续算，通过 build_ele_inputs 构建输入文件。

另有专属文件构建：
- create_frac_files：从 opt 最新输出构建频率矫正（frac）输入。
- build_ele_inputs：从 opt 导入或外部结构构建电子结构输入。
- create_neb_files：从初末态 opt 构建 NEB 计算文件（nebmake.pl 插值）。
"""

import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from config import PROJECTS_DIR, load_servers
from incar import modify_incar
from paths import resolve_local_path, to_local_rel, to_remote_rel
from task_paths import task_remote_dir

NEBMAKE_PL = "/data/gpfs03/mdye/VTST/vtstscripts/nebmake.pl"

ELEC_TYPE_PARAMS: Dict[str, Dict[str, Any]] = {
    "pdos": {
        "LORBIT": 11,  # 可 10/11/12，默认 11
        "EMIN": -10,  # 可改，留空则不包含
        "EMAX": 10,
        "NEDOS": 1000,
        "hint": "PDOS 需要轨道投影（LORBIT），可设置能量范围 EMIN/EMAX 与 NEDOS",
    },
    "bader": {
        "LCHARG": ".TRUE.",
        "LAECHG": ".TRUE.",
        "hint": "Bader 分析需要全电子电荷密度（LAECHG）",
    },
    "cohp": {
        "ISYM": -1,
        "NBANDS": 400,  # 可改，留空则不包含
        "LWAVE": ".TRUE.",
        "LORBIT": 11,  # 可 10/11/12，默认 11
        "hint": "COHP 需要波函数与轨道投影（LWAVE/LORBIT），且需较高能带数（NBANDS）",
    },
    "work_function": {
        "LVHAR": ".TRUE.",
        "LDIPOL": ".TRUE.",  # 默认开启偶极校正；关闭需用户确认
        "hint": "功函数需要局域势输出（LVHAR）与偶极校正（LDIPOL + DIPOL 矫正中心）",
    },
    "diff_charge": {
        "hint": "差分电荷计算后续实现",
    },
}

#: 电子结构基础设置（所有类型共用，用户可覆盖/留空则不包含）
ELEC_BASE_PARAMS: Dict[str, Any] = {
    "NSW": -1,
    "IBRION": -1,
}


def _remote_latest_dir(server: str, remote_dir: str, batch_check_path: str) -> str:
    """复用已部署的 batch_check.resolve_latest_output 定位最新有效续算目录。

    返回 '' 表示主目录；conN 为最新有效续算目录名。
    """
    # Windows 上 Path 会生成反斜杠，远程路径必须统一为正斜杠
    script_dir = str(Path(batch_check_path).parent).replace("\\", "/")
    code = (
        "import sys; sys.path.insert(0, sys.argv[2]); "
        "import batch_check; print(batch_check.resolve_latest_output(sys.argv[1])[0])"
    )
    cmd = f'python3 -c "{code}" "{remote_dir}" "{script_dir}"'
    r = ssh.run_remote(server, cmd, timeout=40)
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "定位最新输出目录失败")
    return r["stdout"].strip()


def _remote_latest_con(server: str, remote_dir: str, batch_check_path: str) -> str:
    """定位最新续算目录（最大编号 conN，存在即算），用于作业提交等场景。

    直接用 bash 列目录（比启动 python3 import batch_check 快得多）。
    """
    r = ssh.run_remote(
        server,
        f'bash -c \'ls -d "{remote_dir}"/con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -1\'',
        timeout=30,
    )
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "定位最新续算目录失败")
    return r["stdout"].strip()


def _bjobs_status(server: str, job_id: str) -> str:
    """远程 bjobs -l 归一化状态（PEND/RUN/SSUSP/.../NOT_FOUND）。"""
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    r = ssh.run_remote(
        server,
        f'bash -lc "source {profile} >/dev/null 2>&1; bjobs -l {job_id}"',
        timeout=30,
    )
    out = f"{r.get('stdout', '')}\n{r.get('stderr', '')}"
    if re.search(r"\bPEND\b", out):
        return "PEND"
    if re.search(r"\bRUN\b", out):
        return "RUN"
    if re.search(r"\b(SSUSP|PSUSP|USUSP)\b", out):
        return "SSUSP"
    for token in ("DONE", "EXIT", "COMPLETED", "FAILED", "CANCELLED"):
        if token in out:
            return token
    return "NOT_FOUND"


def _running_job(
    server: str,
    remote_dir: str,
    con_dir: str,
    task: Dict[str, Any],
) -> Optional[str]:
    """最新续算目录上是否有任务正在运行（RUN/SSUSP）；返回作业号或 None。"""
    candidates = set()
    db_job = str(task.get("job_id") or "")
    if db_job:
        candidates.add(db_job)
    # 目录匹配：RUN 作业才有 exec_cwd（PEND 尚未分配节点）
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    try:
        r = ssh.run_remote(
            server,
            f'bash -lc "source {profile} >/dev/null 2>&1; bjobs -o \'jobid exec_cwd\'"',
            timeout=30,
        )
        for line in (r.get("stdout", "") or "").splitlines()[1:]:
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip().rstrip("/") == str(con_dir).rstrip("/"):
                candidates.add(parts[0].strip())
    except Exception:  # noqa: BLE001 - 目录匹配失败不影响 DB job_id 检查
        pass
    for job in candidates:
        if _bjobs_status(server, job) in ("RUN", "SSUSP"):
            return job
    return None


def _remote_max_con_index(server: str, remote_dir: str) -> int:
    r = ssh.run_remote(
        server,
        f'bash -c \'ls -d "{remote_dir}"/con[0-9]* 2>/dev/null | sed "s|.*/con||" | sort -n | tail -1\'',
        timeout=30,
    )
    out = r["stdout"].strip()
    return int(out) if out.isdigit() else 0


def _remote_con_exists(server: str, remote_dir: str, n: int) -> bool:
    r = ssh.run_remote(
        server,
        f'bash -c \'[ -d "{remote_dir}/con{n}" ] && echo YES\'',
        timeout=30,
    )
    return "YES" in r["stdout"]


def _next_free_con(server: str, remote_dir: str) -> tuple:
    """取下一个不存在的续算编号（跳过残留/并发产生的已存在 conN）。"""
    n = _remote_max_con_index(server, remote_dir) + 1
    while _remote_con_exists(server, remote_dir, n):
        n += 1
    return f"con{n}", n


def _remote_image_dirs(server: str, remote_dir: str) -> List[str]:
    r = ssh.run_remote(
        server,
        f'bash -c \'ls -d "{remote_dir}"/[0-9]* 2>/dev/null | xargs -n1 basename | sort -n\'',
        timeout=30,
    )
    return [line.strip() for line in r["stdout"].splitlines() if line.strip().isdigit()]


def create_continuation(server: str, project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """续算分流入口：按最新目录状态决定创建续算或提示处理。

    - 最新目录（最大编号 conN，无则主目录）OUTCAR 与 CONTCAR 均非空
      -> 标准续算：创建 con(N+1)，返回 action="created"；
    - 否则不创建、不提交，检查输入文件完整性：
      - 完整 -> action="input_complete_but_not_finished"（可手动重新提交）；
      - 缺失 -> action="input_incomplete"（列出缺失文件）。
    NEB 任务沿用原有映像续算流程（action="created"）。
    """
    task_type = str(task.get("task_type", ""))
    if task_type not in ("opt", "neb"):
        raise ValueError("仅结构优化（opt）与 NEB 任务支持同类型续算")

    servers = load_servers()
    cfg = servers.get(server, {})
    batch_path = cfg.get("batch_check_path")
    if not batch_path:
        raise ValueError("服务器未配置 batch_check_path，无法定位最新输出")

    remote_dir = task_remote_dir(server, task).rstrip("/")
    if not remote_dir:
        raise ValueError("任务缺少 remote_dir")
    con, n = _next_free_con(server, remote_dir)
    new_dir = f"{remote_dir}/{con}"

    if task_type == "neb":
        result = _create_neb_continuation(server, remote_dir, con, new_dir)
        result["action"] = "created"
        result["message"] = f"已创建续算目录 {con}"
        return result

    # 定位最新续算目录（最大编号 conN，存在即算；无则主目录）
    latest = _remote_latest_con(server, remote_dir, batch_path)
    current_dir = f"{remote_dir}/{latest}" if latest else remote_dir

    # 首先判断最新续算目录是否有任务正在运行（RUN/SSUSP），有则提示不续算
    running_job = _running_job(server, remote_dir, current_dir, task)
    if running_job:
        return {
            "action": "running",
            "current_dir": current_dir,
            "latest_dir": latest or None,
            "job_id": running_job,
            "message": f"当前目录有任务正在运行（作业 {running_job}），请等待完成后再续算",
            "warnings": [],
        }

    # 状态判断：OUTCAR 与 CONTCAR 均存在且非空才视为正常完成
    check = ssh.run_remote(
        server,
        f'bash -c \'[ -s "{current_dir}/OUTCAR" ] && echo O_OK; [ -s "{current_dir}/CONTCAR" ] && echo C_OK\'',
        timeout=30,
    )
    out = check.get("stdout", "")
    outcar_ok = "O_OK" in out
    contcar_ok = "C_OK" in out
    if not (outcar_ok and contcar_ok):
        # 异常流程：不创建目录、不提交，仅检查输入文件完整性
        required = ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "vasp.lsf")
        conds = " ".join(
            f'[ -s "{current_dir}/{f}" ] && echo OK_{i} || echo MISS_{i};'
            for i, f in enumerate(required)
        )
        r = ssh.run_remote(server, f"bash -c '{conds}'", timeout=30)
        missing = [f for i, f in enumerate(required) if f"MISS_{i}" in r.get("stdout", "")]
        base = {
            "current_dir": current_dir,
            "latest_dir": latest or None,
            "warnings": [],
        }
        if missing:
            base.update(
                {
                    "action": "input_incomplete",
                    "missing_files": missing,
                    "message": f"当前目录未正常完成，且输入文件缺失或为空：{', '.join(missing)}",
                }
            )
            return base
        base.update(
            {
                "action": "input_complete_but_not_finished",
                "message": "当前目录未正常完成，但输入文件完整，可手动重新提交",
            }
        )
        return base

    # 标准续算：从最新目录复制/移动输入文件
    src = current_dir
    cmds = [
        "set -e",
        f'mkdir "{new_dir}"',
        *_source_files_cmds(src, new_dir),
    ]
    _run_remote_bash(server, cmds, timeout=120)
    # 统一 INCAR 修改：本地生成后上传（大小写/布尔兼容、重复合并）
    incar = _download_remote_text(server, f"{new_dir}/INCAR") or ""
    updated, incar_warnings = modify_incar(incar, {"ISTART": 1, "ICHARG": 0})
    _write_remote_file(server, f"{new_dir}/INCAR", updated)
    copied = _list_remote_dir(server, new_dir)
    return {
        "task_type": task_type,
        "con": con,
        "remote_dir": new_dir,
        "source_dir": src,
        "latest_dir": latest or None,
        "incar_changes": {"ISTART": "1", "ICHARG": "0"},
        "copied_files": copied,
        "warnings": incar_warnings,
        "action": "created",
        "current_dir": current_dir,
        "message": f"已创建续算目录 {con}",
    }


def _create_neb_continuation(
    server: str, remote_dir: str, con: str, new_dir: str
) -> Dict[str, Any]:
    """NEB 续算：共享文件从原目录复制，映像 00..NN 逐一处理。"""
    images = _remote_image_dirs(server, remote_dir)
    warnings: List[str] = []
    cmds = [
        "set -e",
        f'mkdir "{new_dir}"',
    ]
    # 共享文件（原任务目录根）
    for f in ("INCAR", "KPOINTS", "POTCAR", "vasp.lsf", "submit.sh"):
        cmds.append(f'[ -f "{remote_dir}/{f}" ] && cp "{remote_dir}/{f}" "{new_dir}/{f}" || true')
    if not images:
        warnings.append("未发现映像子目录（00..NN），仅复制共享文件")
    else:
        first, last = images[0], images[-1]
        for img in images:
            cmds.append(f'mkdir -p "{new_dir}/{img}"')
            if img in (first, last):
                cmds.append(
                    f'[ -f "{remote_dir}/{img}/POSCAR" ] && cp "{remote_dir}/{img}/POSCAR" "{new_dir}/{img}/POSCAR" || true'
                )
            else:
                cmds.append(
                    f'if [ -f "{remote_dir}/{img}/CONTCAR" ]; then '
                    f'cp "{remote_dir}/{img}/CONTCAR" "{new_dir}/{img}/POSCAR"; '
                    f'elif [ -f "{remote_dir}/{img}/POSCAR" ]; then '
                    f'cp "{remote_dir}/{img}/POSCAR" "{new_dir}/{img}/POSCAR"; fi'
                )
    _run_remote_bash(server, cmds, timeout=180)
    # 统一 INCAR 修改（ISTART=1, ICHARG=0）
    incar = _download_remote_text(server, f"{new_dir}/INCAR") or ""
    updated, incar_warnings = modify_incar(incar, {"ISTART": 1, "ICHARG": 0})
    _write_remote_file(server, f"{new_dir}/INCAR", updated)
    return {
        "task_type": "neb",
        "con": con,
        "remote_dir": new_dir,
        "source_dir": remote_dir,
        "latest_dir": None,
        "incar_changes": {"ISTART": "1", "ICHARG": "0"},
        "copied_files": _list_remote_dir(server, new_dir),
        "images": images,
        "warnings": warnings + incar_warnings,
    }


def _source_files_cmds(src: str, dst: str) -> List[str]:
    """生成从 src 复制输入文件到 dst 的远程命令列表。

    CONTCAR→POSCAR 复制；POTCAR/KPOINTS/INCAR/提交脚本复制；
    WAVECAR 采用移动（移动前确认目标不存在，避免覆盖）。
    """
    return [
        f'[ -f "{src}/CONTCAR" ] && cp "{src}/CONTCAR" "{dst}/POSCAR" || true',
        f'[ -f "{src}/POTCAR" ] && cp "{src}/POTCAR" "{dst}/POTCAR" || true',
        f'[ -f "{src}/KPOINTS" ] && cp "{src}/KPOINTS" "{dst}/KPOINTS" || true',
        f'[ -f "{src}/INCAR" ] && cp "{src}/INCAR" "{dst}/INCAR" || true',
        f'[ -f "{src}/vasp.lsf" ] && cp "{src}/vasp.lsf" "{dst}/vasp.lsf" || true',
        f'[ -f "{src}/submit.sh" ] && cp "{src}/submit.sh" "{dst}/submit.sh" || true',
        f'if [ -f "{src}/WAVECAR" ] && [ ! -e "{dst}/WAVECAR" ]; then mv "{src}/WAVECAR" "{dst}/WAVECAR"; fi',
    ]


def _merge_incar(incar_text: str, params: Dict[str, Any]) -> Tuple[str, List[str]]:
    """统一 INCAR 修改（大小写/空格/布尔兼容、重复合并、缺失追加）。"""
    return modify_incar(incar_text, params)


def _merge_ele_params(ele_types: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """合并多个电子结构计算类型的参数。

    同一参数值一致 -> 正常合并（重复参数）；
    同一参数值不一致 -> 返回冲突列表（调用方抛出警告/错误）。
    """
    merged: Dict[str, Any] = {}
    conflicts: List[str] = []
    for t in ele_types:
        cfg = ELEC_TYPE_PARAMS.get(t, {})
        for key, value in cfg.items():
            if key == "hint":
                continue
            if key in merged and str(merged[key]) != str(value):
                conflicts.append(f"{key}：{merged[key]}（已选类型）与 {value}（{t}）冲突")
            elif key not in merged:
                merged[key] = value
    return merged, conflicts


def _write_remote_file(server: str, remote_path: str, content: str) -> None:
    """把文本内容写入远程文件（本地临时文件 + 上传）。"""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as f:
        f.write(content)
        tmp = f.name
    try:
        ssh.upload_file(server, tmp, remote_path)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


def _download_remote_text(server: str, remote_path: str) -> Optional[str]:
    """下载远程文本文件内容；不存在或失败返回 None。"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
        tmp = f.name
    try:
        ok = ssh.download_file(server, remote_path, tmp)
        if not ok:
            return None
        return Path(tmp).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


def _run_remote_bash(server: str, cmds: List[str], timeout: int = 180) -> None:
    r = ssh.run_remote(server, "bash -c '" + "; ".join(cmds) + "'", timeout=timeout)
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "远程操作失败")


def create_frac_files(
    server: str,
    project: Dict[str, Any],
    opt_task: Dict[str, Any],
    frac_task: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从结构优化最新输出构建频率矫正（frac）输入文件（全部在远端）。"""
    servers = load_servers()
    cfg = servers.get(server, {})
    batch_path = cfg.get("batch_check_path")
    if not batch_path:
        raise ValueError("服务器未配置 batch_check_path，无法定位最新输出")

    opt_dir = task_remote_dir(server, opt_task).rstrip("/")
    frac_dir = task_remote_dir(server, frac_task).rstrip("/")
    if not opt_dir or not frac_dir:
        raise ValueError("任务缺少 remote_dir")

    latest = _remote_latest_dir(server, opt_dir, batch_path)
    src = f"{opt_dir}/{latest}" if latest else opt_dir
    cmds = [
        "set -e",
        f'mkdir -p "{frac_dir}"',
        *_source_files_cmds(src, frac_dir),
    ]
    _run_remote_bash(server, cmds, timeout=180)

    # INCAR 频率计算参数（默认值可覆盖，留空则不包含）
    incar = _download_remote_text(server, f"{frac_dir}/INCAR") or ""
    defaults = {"ISYM": -1, "SIGMA": 0.05, "NSW": 1, "IBRION": 5, "POTIM": 0.015}
    changes = {
        **defaults,
        **{str(k): v for k, v in (params or {}).items() if v is not None},
    }
    updated, incar_warnings = _merge_incar(incar, changes)
    _write_remote_file(server, f"{frac_dir}/INCAR", updated)
    return {
        "frac_dir": frac_dir,
        "source_dir": src,
        "latest_dir": latest or None,
        "incar_changes": {k: str(v) for k, v in changes.items()},
        "copied_files": _list_remote_dir(server, frac_dir),
        "warnings": incar_warnings,
    }


def build_ele_inputs(
    server: str,
    project: Dict[str, Any],
    task: Dict[str, Any],
    source_type: str,
    source_task_id: Optional[str],
    ele_types: List[str],
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """为电子结构任务构建输入文件（从 opt 导入或外部结构）。"""
    ele_dir = task_remote_dir(server, task).rstrip("/")
    if not ele_dir:
        raise ValueError("任务缺少 remote_dir")

    if not ele_types:
        raise ValueError("请至少选择一种电子结构计算类型")
    extra, conflicts = _merge_ele_params(ele_types)
    if conflicts:
        raise ValueError(f"所选计算类型存在参数冲突，请调整选择：{'；'.join(conflicts)}")
    # 电子结构基础设置（NSW=-1 / IBRION=-1），用户 params 可覆盖
    extra = {**ELEC_BASE_PARAMS, **extra}
    extra.update({str(k): v for k, v in (params or {}).items() if v is not None})

    src = ""
    warnings: List[str] = []
    if source_type == "opt":
        opt_task = next(
            (
                t
                for t in project.get("tasks", [])
                if t.get("task_id") == source_task_id
            ),
            None,
        )
        if opt_task is None:
            raise ValueError("指定的结构来源任务不存在")
        servers = load_servers()
        cfg = servers.get(server, {})
        batch_path = cfg.get("batch_check_path")
        opt_dir = task_remote_dir(server, opt_task).rstrip("/")
        latest = _remote_latest_dir(server, opt_dir, batch_path) if batch_path else ""
        src = f"{opt_dir}/{latest}" if latest else opt_dir
        cmds = ["set -e", f'mkdir -p "{ele_dir}"', *_source_files_cmds(src, ele_dir)]
        _run_remote_bash(server, cmds, timeout=180)
    elif source_type == "external":
        # 外部导入：从本地任务目录 files/POSCAR 上传，其余用默认模板
        from task_paths import task_dir

        local_poscar = task_dir(project.get("name", ""), task) / "files" / "POSCAR"
        if not local_poscar.is_file():
            raise ValueError("外部导入需要先在任务本地目录 files/ 放置 POSCAR")
        cmds = ["set -e", f'mkdir -p "{ele_dir}"']
        _run_remote_bash(server, cmds, timeout=60)
        ssh.upload_file(server, str(local_poscar), f"{ele_dir}/POSCAR")
        warnings.append("外部导入：INCAR/KPOINTS 使用电子结构默认模板")
    else:
        raise ValueError("结构来源类型仅支持 opt / external")

    # INCAR：基于源 INCAR（若存在）或默认模板，合并电子结构参数
    incar = _download_remote_text(server, f"{ele_dir}/INCAR") or ""
    if not incar.strip():
        from config import load_task_registry

        registry = load_task_registry()
        defaults = (registry.get("ele") or {}).get("default_incar", {})
        incar = "\n".join(f"{k} = {v}" for k, v in defaults.items()) + "\n"
    updated, incar_warnings = _merge_incar(incar, extra)
    _write_remote_file(server, f"{ele_dir}/INCAR", updated)
    warnings.extend(incar_warnings)

    return {
        "ele_dir": ele_dir,
        "source_type": source_type,
        "source_dir": src or None,
        "ele_types": ele_types,
        "incar_changes": {k: str(v) for k, v in extra.items()},
        "copied_files": _list_remote_dir(server, ele_dir),
        "warnings": warnings,
    }


def create_neb_files(
    server: str,
    project: Dict[str, Any],
    neb_task: Dict[str, Any],
    initial_task: Dict[str, Any],
    final_task: Dict[str, Any],
    num_images: int,
    nebmake: str = NEBMAKE_PL,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从初末态 opt 构建 NEB 计算文件：00..NN 映像 + nebmake.pl 插值。"""
    if num_images < 1:
        raise ValueError("中间态数量至少为 1")
    servers = load_servers()
    cfg = servers.get(server, {})
    batch_path = cfg.get("batch_check_path")

    neb_dir = task_remote_dir(server, neb_task).rstrip("/")
    if not neb_dir:
        raise ValueError("NEB 任务缺少 remote_dir")

    def _latest_src(task: Dict[str, Any]) -> str:
        base = task_remote_dir(server, task).rstrip("/")
        if not batch_path:
            return base
        latest = _remote_latest_dir(server, base, batch_path)
        return f"{base}/{latest}" if latest else base

    src_is = _latest_src(initial_task)
    src_fs = _latest_src(final_task)
    last = num_images + 1
    cmds = [
        "set -e",
        f'mkdir -p "{neb_dir}"',
        f'mkdir -p "{neb_dir}/00" "{neb_dir}/{last:02d}"',
        f'cp "{src_is}/CONTCAR" "{neb_dir}/00/POSCAR"',
        f'cp "{src_fs}/CONTCAR" "{neb_dir}/{last:02d}/POSCAR"',
        # POTCAR / KPOINTS / 提交脚本（从初态源复制）
        f'[ -f "{src_is}/POTCAR" ] && cp "{src_is}/POTCAR" "{neb_dir}/POTCAR" || true',
        f'[ -f "{src_is}/KPOINTS" ] && cp "{src_is}/KPOINTS" "{neb_dir}/KPOINTS" || true',
        f'[ -f "{src_is}/vasp.lsf" ] && cp "{src_is}/vasp.lsf" "{neb_dir}/vasp.lsf" || true',
        f'[ -f "{src_is}/submit.sh" ] && cp "{src_is}/submit.sh" "{neb_dir}/submit.sh" || true',
        # OUTCAR 便于 NEB 端点使用波函数信息
        f'[ -f "{src_is}/OUTCAR" ] && cp "{src_is}/OUTCAR" "{neb_dir}/00/OUTCAR" || true',
        f'[ -f "{src_fs}/OUTCAR" ] && cp "{src_fs}/OUTCAR" "{neb_dir}/{last:02d}/OUTCAR" || true',
        # nebmake.pl 生成 00..NN 全部映像（含中间态插值）
        f'cd "{neb_dir}" && perl "{nebmake}" 00/POSCAR "{last:02d}/POSCAR" {num_images}',
    ]
    _run_remote_bash(server, cmds, timeout=300)

    # NEB INCAR：默认模板 + NEB 参数（默认值可覆盖，留空则不包含）
    from config import load_task_registry

    registry = load_task_registry()
    defaults = (registry.get("neb") or {}).get("default_incar", {})
    incar = "\n".join(f"{k} = {v}" for k, v in defaults.items()) + "\n"
    neb_changes = {
        "IBRION": 3,
        "POTIM": 0,
        "IOPT": 3,
        "LCLIMB": ".TRUE.",
        "IMAGES": num_images,
        "ICHAIN": 0,
        "SPRING": -5,
        "MAXMOVE": 0.2,
        **{str(k): v for k, v in (params or {}).items() if v is not None},
    }
    updated, incar_warnings = _merge_incar(
        incar,
        neb_changes,
    )
    _write_remote_file(server, f"{neb_dir}/INCAR", updated)
    return {
        "neb_dir": neb_dir,
        "source_is": src_is,
        "source_fs": src_fs,
        "num_images": num_images,
        "images": [f"{i:02d}" for i in range(0, last + 1)],
        "incar_changes": {k: str(v) for k, v in neb_changes.items()},
        "copied_files": _list_remote_dir(server, neb_dir),
        "warnings": incar_warnings,
    }


def _list_remote_dir(server: str, remote_dir: str) -> List[str]:
    r = ssh.run_remote(server, f'bash -c \'ls -1 "{remote_dir}" 2>/dev/null\'', timeout=30)
    return [line.strip() for line in r["stdout"].splitlines() if line.strip()]


def local_continuation_dir(parent_dir_path: str, con: str) -> str:
    """续算子任务的本地镜像目录（相对路径；不传输文件，仅建空目录保证一致性）。"""
    return to_local_rel(str(resolve_local_path(parent_dir_path) / con))
