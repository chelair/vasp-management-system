"""同类型续算：全部在远程服务器端完成，不经过本地文件传输。

普通任务（opt/frac/ele）：在任务目录下创建 conN，从最新有效输出目录
（复用巡检的 con* 扫描逻辑）复制 CONTCAR→POSCAR、POTCAR、KPOINTS、
WAVECAR（若存在）、提交脚本、INCAR，并修改 INCAR（ISTART=1, ICHARG=0）。

NEB 任务：在任务目录下创建 conN，共享文件从原任务目录复制，
映像 00..NN 逐一处理（中间映像优先 CONTCAR，初末态用 POSCAR）。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from config import PROJECTS_DIR, load_servers
from paths import resolve_local_path, to_local_rel, to_remote_rel
from task_paths import task_remote_dir


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
    """在远程服务器上创建同类型续算目录，返回续算信息。"""
    servers = load_servers()
    cfg = servers.get(server, {})
    batch_path = cfg.get("batch_check_path")
    if not batch_path:
        raise ValueError("服务器未配置 batch_check_path，无法定位最新输出")

    remote_dir = task_remote_dir(server, task).rstrip("/")
    if not remote_dir:
        raise ValueError("任务缺少 remote_dir")
    task_type = str(task.get("task_type", ""))
    con, n = _next_free_con(server, remote_dir)
    new_dir = f"{remote_dir}/{con}"

    if task_type == "neb":
        return _create_neb_continuation(server, remote_dir, con, new_dir)

    latest = _remote_latest_dir(server, remote_dir, batch_path)
    src = f"{remote_dir}/{latest}" if latest else remote_dir
    cmds = [
        "set -e",
        f'mkdir "{new_dir}"',
        f'[ -f "{src}/CONTCAR" ] && cp "{src}/CONTCAR" "{new_dir}/POSCAR"',
        f'[ -f "{src}/POTCAR" ] && cp "{src}/POTCAR" "{new_dir}/POTCAR"',
        f'[ -f "{src}/KPOINTS" ] && cp "{src}/KPOINTS" "{new_dir}/KPOINTS"',
        # WAVECAR 体积大，采用移动而非复制，避免双份占用磁盘
        f'[ -f "{src}/WAVECAR" ] && mv "{src}/WAVECAR" "{new_dir}/WAVECAR"',
        f'[ -f "{src}/vasp.lsf" ] && cp "{src}/vasp.lsf" "{new_dir}/vasp.lsf"',
        f'[ -f "{src}/submit.sh" ] && cp "{src}/submit.sh" "{new_dir}/submit.sh"',
        f'[ -f "{src}/INCAR" ] && cp "{src}/INCAR" "{new_dir}/INCAR" || true',
        f'if [ ! -f "{new_dir}/INCAR" ]; then printf "ISTART = 1\\nICHARG = 0\\n" > "{new_dir}/INCAR"; fi',
        _sed_incar(new_dir),
    ]
    r = ssh.run_remote(server, "bash -c '" + "; ".join(cmds) + "'", timeout=120)
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "续算文件复制失败")
    copied = _list_remote_dir(server, new_dir)
    return {
        "task_type": task_type,
        "con": con,
        "remote_dir": new_dir,
        "source_dir": src,
        "latest_dir": latest or None,
        "incar_changes": {"ISTART": "1", "ICHARG": "0"},
        "copied_files": copied,
        "warnings": [],
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
    # INCAR 修改（默认 ISTART=1, ICHARG=0）
    cmds.append(
        f'if [ ! -f "{new_dir}/INCAR" ]; then printf "ISTART = 1\\nICHARG = 0\\n" > "{new_dir}/INCAR"; fi'
    )
    cmds.append(_sed_incar(new_dir))
    r = ssh.run_remote(server, "bash -c '" + "; ".join(cmds) + "'", timeout=180)
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "NEB 续算文件复制失败")
    return {
        "task_type": "neb",
        "con": con,
        "remote_dir": new_dir,
        "source_dir": remote_dir,
        "latest_dir": None,
        "incar_changes": {"ISTART": "1", "ICHARG": "0"},
        "copied_files": _list_remote_dir(server, new_dir),
        "images": images,
        "warnings": warnings,
    }


def _sed_incar(path: str) -> str:
    return (
        f'if [ -f "{path}/INCAR" ]; then '
        f'if grep -q "ISTART" "{path}/INCAR"; then sed -i "s/^[[:space:]]*ISTART.*/ISTART = 1/" "{path}/INCAR"; '
        f'else echo "ISTART = 1" >> "{path}/INCAR"; fi; '
        f'if grep -q "ICHARG" "{path}/INCAR"; then sed -i "s/^[[:space:]]*ICHARG.*/ICHARG = 0/" "{path}/INCAR"; '
        f'else echo "ICHARG = 0" >> "{path}/INCAR"; fi; fi'
    )


def _list_remote_dir(server: str, remote_dir: str) -> List[str]:
    r = ssh.run_remote(server, f'bash -c \'ls -1 "{remote_dir}" 2>/dev/null\'', timeout=30)
    return [line.strip() for line in r["stdout"].splitlines() if line.strip()]


def local_continuation_dir(parent_dir_path: str, con: str) -> str:
    """续算子任务的本地镜像目录（相对路径；不传输文件，仅建空目录保证一致性）。"""
    return to_local_rel(str(resolve_local_path(parent_dir_path) / con))
