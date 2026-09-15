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

import base64
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from config import PROJECTS_DIR, load_servers
from incar import modify_incar
from input_state import (
    applied_items,
    audit_comment,
    mark_applied,
    pending_incar_params,
    pending_kpoints_mesh,
    set_kpoints_mesh,
)
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


def compute_g_correction(
    server: str,
    remote_dir: str,
    temperature: float = 298.15,
) -> float:
    """远端 vaspkit 501 计算 G(T) 热力学矫正（eV）。

    vaspkit 输出：Thermal correction to G(T): 31.277 kcal/mol  1.356307 eV
    取 kcal/mol 之后的 eV 值。
    """
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    result = ssh.run_remote(
        server,
        f'bash -c \'cd "{remote_dir}" && printf "501\\n{temperature}\\n" | vaspkit\'',
        timeout=180,
    )
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    m = re.search(
        r"Thermal correction to G\(T\):\s*[-\d.Ee+]+\s+kcal/mol\s+([-\d.Ee+]+)",
        raw,
    )
    if not m or result.get("exit_code") != 0:
        raise RuntimeError(f"vaspkit 501 未能解析矫正项：{raw[-400:] or '未知错误'}")
    return float(m.group(1))


def _remote_script(server: str, script: str, timeout: int = 180) -> str:
    """一次远程执行 bash 脚本（base64 传输，避免引号转义），返回 stdout。

    远程每条 exec 通道都有约 1.3s 的 shell 启动开销，因此把续算的多步
    文件操作合并进单次调用，可把 6-7 次往返压到 1 次。
    """
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    r = ssh.run_remote(server, f"echo {b64} | base64 -d | bash", timeout=timeout)
    if r["exit_code"] != 0:
        raise RuntimeError((r["stderr"] or r["stdout"]).strip() or "远程操作失败")
    return r.get("stdout", "") or ""


def _script_slice(out: str, start: str, end: str) -> str:
    """取输出中 start 与 end 两个标记之间的文本（跳过标记行后的换行）。"""
    s = out.find(start)
    if s < 0:
        return ""
    s += len(start)
    if s < len(out) and out[s] == "\n":
        s += 1
    e = out.find(end, s)
    return out[s:] if e < 0 else out[s:e]


def _script_tail(out: str, marker: str) -> str:
    e = out.find(marker)
    return "" if e < 0 else out[e + len(marker):]


def _state_value(state: str, key: str) -> str:
    for line in state.splitlines():
        if line.startswith(key + "="):
            return line[len(key) + 1:].strip()
    return ""


def _opt_continuation_script(server: str, remote_dir: str, task: Dict[str, Any]) -> str:
    """结构优化续算的单次远程脚本：
    编号计算 -> 运行中检查 -> OUTCAR/CONTCAR 状态检查 -> 输入完整性检查
    ->（条件满足时）复制/移动输入文件并回传 INCAR 与文件列表。
    """
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    db_job = str(task.get("job_id") or "")
    return f"""set -e
RD="{remote_dir}"
DBJOB="{db_job}"
source {profile} >/dev/null 2>&1 || true
MAX=$(ls -d "$RD"/con[0-9]* 2>/dev/null | sed 's|.*/con||' | sort -n | tail -1)
N=$((${{MAX:-0}} + 1))
while [ -d "$RD/con$N" ]; do N=$((N+1)); done
CON="con$N"
LATEST=$(ls -d "$RD"/con[0-9]* 2>/dev/null | sed 's|.*/||' | sort -V | tail -1)
if [ -n "$LATEST" ]; then CUR="$RD/$LATEST"; else CUR="$RD"; fi
RUNJOB=""
if [ -n "$DBJOB" ] && bjobs -l "$DBJOB" 2>/dev/null | grep -qE '\\b(RUN|SSUSP|PSUSP|USUSP)\\b'; then
  RUNJOB="$DBJOB"
else
  for j in $(bjobs -o 'jobid exec_cwd' 2>/dev/null | awk -v d="$CUR" 'NR>1 && $2==d {{print $1}}'); do
    if bjobs -l "$j" 2>/dev/null | grep -qE '\\b(RUN|SSUSP|PSUSP|USUSP)\\b'; then RUNJOB="$j"; break; fi
  done
fi
echo "===STATE==="
echo "CON=$CON"
echo "LATEST=$LATEST"
echo "RUNJOB=$RUNJOB"
[ -s "$CUR/OUTCAR" ] && echo O_OK
[ -s "$CUR/CONTCAR" ] && echo C_OK
for f in POSCAR INCAR KPOINTS POTCAR vasp.lsf submit.sh; do
  [ -s "$CUR/$f" ] && echo "OK_$f" || echo "MISS_$f"
done
echo "===STATE_END==="
if [ -n "$RUNJOB" ] || [ ! -s "$CUR/OUTCAR" ] || [ ! -s "$CUR/CONTCAR" ]; then
  exit 0
fi
NEW="$RD/$CON"
mkdir "$NEW"
[ -f "$CUR/CONTCAR" ] && cp "$CUR/CONTCAR" "$NEW/POSCAR" || true
[ -f "$CUR/POTCAR" ] && cp "$CUR/POTCAR" "$NEW/POTCAR" || true
[ -f "$CUR/KPOINTS" ] && cp "$CUR/KPOINTS" "$NEW/KPOINTS" || true
[ -f "$CUR/INCAR" ] && cp "$CUR/INCAR" "$NEW/INCAR" || true
[ -f "$CUR/vasp.lsf" ] && cp "$CUR/vasp.lsf" "$NEW/vasp.lsf" || true
[ -f "$CUR/submit.sh" ] && cp "$CUR/submit.sh" "$NEW/submit.sh" || true
if [ -f "$CUR/WAVECAR" ] && [ ! -e "$NEW/WAVECAR" ]; then mv "$CUR/WAVECAR" "$NEW/WAVECAR"; fi
[ -f "$NEW/INCAR" ] && cat "$NEW/INCAR" || true
echo "===FILES==="
ls -1 "$NEW"
"""


def _neb_continuation_script(
    server: str, remote_dir: str, task: Dict[str, Any]
) -> str:
    """NEB 续算单次远程脚本：源目录取最新续算目录（conN 优先，无则主目录），
    共享文件复制、端点 POSCAR 固定并带上端点 OUTCAR（00/NN）、
    中间映像 CONTCAR→POSCAR；各映像（含端点/中间态）存在 WAVECAR 时随续算移动。
    有活跃作业时只回传状态并直接退出，不创建目录、不移动任何文件。
    """
    servers = load_servers()
    profile = str(
        servers.get(server, {}).get(
            "lsf_profile", "/opt/ibm/lsfsuite/lsf/conf/profile.lsf"
        )
    )
    db_job = str(task.get("job_id") or "")
    return f"""set -e
RD="{remote_dir}"
DBJOB="{db_job}"
source {profile} >/dev/null 2>&1 || true
MAX=$(ls -d "$RD"/con[0-9]* 2>/dev/null | sed 's|.*/con||' | sort -n | tail -1)
N=$((${{MAX:-0}} + 1))
while [ -d "$RD/con$N" ]; do N=$((N+1)); done
CON="con$N"
LATEST=$(ls -d "$RD"/con[0-9]* 2>/dev/null | sed 's|.*/||' | sort -V | tail -1)
if [ -n "$LATEST" ]; then SRC="$RD/$LATEST"; else SRC="$RD"; fi
NEW="$RD/$CON"
RUNJOB=""
if [ -n "$DBJOB" ] && bjobs -l "$DBJOB" 2>/dev/null | grep -qE '\\b(RUN|SSUSP|PSUSP|USUSP)\\b'; then
  RUNJOB="$DBJOB"
else
  for j in $(bjobs -o 'jobid exec_cwd' 2>/dev/null | awk -v d="$SRC" 'NR>1 && ($2==d || index($2, d"/")==1) {{print $1}}'); do
    if bjobs -l "$j" 2>/dev/null | grep -qE '\\b(RUN|SSUSP|PSUSP|USUSP)\\b'; then RUNJOB="$j"; break; fi
  done
fi
echo "===STATE==="
echo "CON=$CON"
echo "LATEST=$LATEST"
echo "SRC=$SRC"
echo "RUNJOB=$RUNJOB"
echo "===STATE_END==="
if [ -n "$RUNJOB" ]; then
  echo "===SKIP==="
  exit 0
fi
mkdir "$NEW"
for f in INCAR KPOINTS POTCAR vasp.lsf submit.sh; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$NEW/$f" || true
done
FIRST=$(find "$SRC" -maxdepth 1 -type d -name '[0-9]*' -printf '%f\\n' 2>/dev/null | sort -n | head -1)
LAST=$(find "$SRC" -maxdepth 1 -type d -name '[0-9]*' -printf '%f\\n' 2>/dev/null | sort -n | tail -1)
for d in "$SRC"/[0-9]*; do
  [ -d "$d" ] || continue
  img=$(basename "$d")
  mkdir -p "$NEW/$img"
  if [ "$img" = "$FIRST" ] || [ "$img" = "$LAST" ]; then
    [ -f "$SRC/$img/POSCAR" ] && cp "$SRC/$img/POSCAR" "$NEW/$img/POSCAR" || true
    [ -f "$SRC/$img/OUTCAR" ] && cp "$SRC/$img/OUTCAR" "$NEW/$img/OUTCAR" || true
  else
    if [ -f "$SRC/$img/CONTCAR" ]; then
      cp "$SRC/$img/CONTCAR" "$NEW/$img/POSCAR"
    elif [ -f "$SRC/$img/POSCAR" ]; then
      cp "$SRC/$img/POSCAR" "$NEW/$img/POSCAR"
    fi
  fi
  if [ -f "$SRC/$img/WAVECAR" ] && [ ! -e "$NEW/$img/WAVECAR" ]; then mv "$SRC/$img/WAVECAR" "$NEW/$img/WAVECAR"; fi
done
[ -f "$NEW/INCAR" ] && cat "$NEW/INCAR" || true
echo "===FILES==="
ls -1 "$NEW"
echo "===IMAGES==="
ls -1d "$NEW"/[0-9]* 2>/dev/null | xargs -n1 basename | sort -n
"""


def create_continuation(server: str, project: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """续算分流入口：单次远程执行完成编号/运行中/状态/输入完整性检查与文件准备。

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

    remote_dir = task_remote_dir(server, task).rstrip("/")
    if not remote_dir:
        raise ValueError("任务缺少 remote_dir")

    if task_type == "neb":
        out = _remote_script(
            server, _neb_continuation_script(server, remote_dir, task), timeout=180
        )
        state = _script_slice(out, "===STATE===", "===STATE_END===")
        con = _state_value(state, "CON")
        latest = _state_value(state, "LATEST")
        running_job = _state_value(state, "RUNJOB")
        source_dir = _state_value(state, "SRC") or remote_dir
        if running_job:
            return {
                "action": "running",
                "current_dir": source_dir,
                "latest_dir": latest or None,
                "job_id": running_job,
                "message": f"当前目录有任务正在运行（作业 {running_job}），请等待完成后再续算",
                "warnings": [],
            }
        new_dir = f"{remote_dir}/{con}"
        incar_text = _script_slice(out, "===STATE_END===", "===FILES===")
        copied = [
            ln
            for ln in _script_slice(out, "===FILES===", "===IMAGES===").splitlines()
            if ln.strip()
        ]
        images = [
            ln
            for ln in _script_tail(out, "===IMAGES===").splitlines()
            if ln.strip().isdigit()
        ]
        warnings = [] if images else ["未发现映像子目录（00..NN），仅复制共享文件"]
        updated, draft_warnings, applied = _apply_drafts_to_new_dir(
            server, task, new_dir, con, incar_text
        )
        _write_remote_file(server, f"{new_dir}/INCAR", updated)
        if applied:
            task["input_state"] = mark_applied(task.get("input_state") or {}, con)
        return {
            "task_type": "neb",
            "con": con,
            "remote_dir": new_dir,
            "source_dir": source_dir,
            "latest_dir": latest or None,
            "incar_changes": {"ISTART": "1", "ICHARG": "0"},
            "copied_files": copied,
            "images": images,
            "warnings": warnings + draft_warnings,
            "applied_changes": applied,
            "action": "created",
            "current_dir": source_dir,
            "message": f"已创建续算目录 {con}",
        }

    out = _remote_script(
        server, _opt_continuation_script(server, remote_dir, task), timeout=180
    )
    state = _script_slice(out, "===STATE===", "===STATE_END===")
    con = _state_value(state, "CON")
    latest = _state_value(state, "LATEST")
    running_job = _state_value(state, "RUNJOB")
    current_dir = f"{remote_dir}/{latest}" if latest else remote_dir
    outcar_ok = "O_OK" in state
    contcar_ok = "C_OK" in state
    required = ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "vasp.lsf")
    missing = [f for f in required if f"MISS_{f}" in state]

    if running_job:
        return {
            "action": "running",
            "current_dir": current_dir,
            "latest_dir": latest or None,
            "job_id": running_job,
            "message": f"当前目录有任务正在运行（作业 {running_job}），请等待完成后再续算",
            "warnings": [],
        }

    if not (outcar_ok and contcar_ok):
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

    new_dir = f"{remote_dir}/{con}"
    incar_text = _script_slice(out, "===STATE_END===", "===FILES===")
    copied = [ln for ln in _script_tail(out, "===FILES===").splitlines() if ln.strip()]
    updated, draft_warnings, applied = _apply_drafts_to_new_dir(
        server, task, new_dir, con, incar_text
    )
    _write_remote_file(server, f"{new_dir}/INCAR", updated)
    if applied:
        task["input_state"] = mark_applied(task.get("input_state") or {}, con)
    return {
        "task_type": task_type,
        "con": con,
        "remote_dir": new_dir,
        "source_dir": current_dir,
        "latest_dir": latest or None,
        "incar_changes": {"ISTART": "1", "ICHARG": "0"},
        "copied_files": copied,
        "warnings": draft_warnings,
        "applied_changes": applied,
        "action": "created",
        "current_dir": current_dir,
        "message": f"已创建续算目录 {con}",
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


def _apply_drafts_to_new_dir(
    server: str,
    task: Dict[str, Any],
    new_dir: str,
    con: str,
    incar_text: str,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """把用户在系统里改的参数（input_state.draft）应用到续算目录。

    - INCAR：草稿参数随后一起交给 `modify_incar`（续算必需的 ISTART=1/ICHARG=0 优先，
      若用户也改了这两项则给出警告）；
    - KPOINTS：只改 k 网格行（整体重写该文件，先取回再写回）；
    - POSCAR：**不应用**（续算 POSCAR 来自 CONTCAR，用户改动只在台账里留痕）；
    - 应用后在 INCAR 顶部写入审计注释，并返回应用记录供上层标记台账。
    """
    state = task.get("input_state") or {}
    draft_incar = pending_incar_params(state)
    mesh = pending_kpoints_mesh(state)
    applied = applied_items(state)
    warnings: List[str] = []
    if not applied:
        return incar_text, warnings, []

    changes: Dict[str, Any] = {"ISTART": 1, "ICHARG": 0}
    for key, value in draft_incar.items():
        if key in changes and str(value) != str(changes[key]):
            warnings.append(
                f"续算需要 {key}={changes[key]}，已按续算要求覆盖你在系统里改的 {key}={value}"
            )
            continue
        changes[key] = value
    new_text, incar_warnings = modify_incar(incar_text, changes)
    warnings.extend(incar_warnings)
    comment = audit_comment(applied)
    if comment and not new_text.lstrip().startswith(comment):
        new_text = comment + "\n" + new_text

    if mesh:
        kpoints_text = _download_remote_text(server, f"{new_dir}/KPOINTS")
        if kpoints_text:
            _write_remote_file(server, f"{new_dir}/KPOINTS", set_kpoints_mesh(kpoints_text, mesh))
        else:
            warnings.append("KPOINTS 未取回，k 网格修改未应用")
    return new_text, warnings, applied


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
    defaults = {
        "ISYM": 0,
        "SIGMA": 0.05,
        "NSW": 1,
        "IBRION": 5,
        "NFREE": 2,
        "POTIM": 0.015,
    }
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
    """从初末态 opt 构建 NEB 计算文件：00..NN 映像 + nebmake.pl 插值。

    INCAR 从初态 opt 最新输出目录复制，只合并 NEB 专属参数
    （IBRION/POTIM/IOPT/LCLIMB/IMAGES/ICHAIN/SPRING/MAXMOVE 及用户参数），
    其余参数原样保留；初态 INCAR 缺失时才回退 NEB 默认模板。
    """
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
        f'[ -f "{src_is}/INCAR" ] && cp "{src_is}/INCAR" "{neb_dir}/INCAR" || true',
        # OUTCAR 便于 NEB 端点使用波函数信息
        f'[ -f "{src_is}/OUTCAR" ] && cp "{src_is}/OUTCAR" "{neb_dir}/00/OUTCAR" || true',
        f'[ -f "{src_fs}/OUTCAR" ] && cp "{src_fs}/OUTCAR" "{neb_dir}/{last:02d}/OUTCAR" || true',
        # nebmake.pl 生成 00..NN 全部映像（含中间态插值）
        f'cd "{neb_dir}" && perl "{nebmake}" 00/POSCAR "{last:02d}/POSCAR" {num_images}',
    ]
    _run_remote_bash(server, cmds, timeout=300)

    # NEB INCAR：以初态 opt INCAR 为基底，只合并 NEB 参数（其余参数原样保留）
    incar = _download_remote_text(server, f"{neb_dir}/INCAR") or ""
    if not incar.strip():
        # 初态 INCAR 缺失/为空时回退 NEB 默认模板
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
