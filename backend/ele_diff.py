"""差分电荷（电子结构附属计算，2026-10-13）：把完整结构按原子分块，生成 1/2/… 分块计算。

用户口径（2026-10-13）：

远端（`<ele 任务目录>/`，与完整结构计算同级）::

    ele/<任务名>/{POSCAR,INCAR,KPOINTS,POTCAR,vasp.lsf,CHGCAR,OUTCAR,...}
    ele/<任务名>/1/  ← 分块A：只保留分块 A 的原子（POSCAR/INCAR/KPOINTS/POTCAR/vasp.lsf）
    ele/<任务名>/2/  ← 分块B
    …（可再加分块 C/D → 目录 3/4）

本地（`<ele 任务本地目录>/`）::

    files/                    ← 完整结构（主任务，既有约定）
    diffcharge_files/1/       ← 分块计算文件（flat：文件直接放这里，不再套 files/）
    diffcharge_files/2/
    diffcharge_files/chgfiles/CHGCAR_diff.vasp
                              ← **只回传一个差分文件**（2026-10-14 口径变更）
    diffcharge_files/images/  ← VESTA 处理出来的图

差分怎么算（2026-10-14 用户口径）：**在远端主目录用 VTST 脚本算好再回传**，
不再把各分块/完整结构的 CHGCAR（各 200MB+）都拉下来：

    chgsum.pl 1/CHGCAR 2/CHGCAR …      # → CHGCAR_sum
    chgdiff.pl CHGCAR CHGCAR_sum       # → CHGCAR_diff

（`chgsum.pl` / `chgdiff.pl` 在 VTST vtstscripts 目录里，可用 `servers.json: vtst_dir` 覆盖。）

规则：
- POSCAR 来自**主任务的 POSCAR**（电子结构主任务是静态计算，不用 CONTCAR）；
- 分块由用户在作业管理里框选原子指定（复用 POSCAR 页的选择逻辑），各块不重叠且合起来 = 全部原子；
- 每个分块只保留自己那部分原子（晶胞不变、元素顺序沿用父结构、重新统计元素数量）；
- INCAR 复制主任务的 INCAR 并**校验关键参数**：`LCHARG = .TRUE.`、`IBRION = -1`、
  `ISTART = 0`、`ICHARG = 2`（不一致就地改并回报；MAGMOM 暂不改，留后续自动化）；
- KPOINTS / vasp.lsf 直接复制主任务的；
- POTCAR 用远端 `pos2pot`（递归）生成 —— 在主任务目录跑一次，主结构与各分块一起出。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ssh
from config import PROJECTS_DIR
from dates import now_iso
from incar import modify_incar
from paths import to_local_rel, to_remote_rel
from potcar import run_pos2pot
from task_paths import (
    DIFF_CHARGE_DIR,
    ELE_DIFF_TYPE,
    local_files_dir,
    task_dir,
    task_remote_dir,
)

#: 差分电荷必须校验的 INCAR 关键参数（不一致就改，并在返回里说明）。
#: 分块**从零开始算**（不读主任务的波函数/电荷密度）：ISTART=0 + ICHARG=2；
#: 静态单点 IBRION=-1；同时要写 CHGCAR 供后续差分（LCHARG=.TRUE.）。
REQUIRED_INCAR = {"LCHARG": ".TRUE.", "IBRION": -1, "ISTART": 0, "ICHARG": 2}
#: 分块 INCAR **不保留**的输出类参数（用户 2026-10-13 口径：除了 LCHARG 以外不要其它输出参数）。
#: 键名与作业管理 INCAR 页「输出与文件」分组一致；MAGMOM/ENCUT/ISMEAR 这些照常复制。
DROP_INCAR_KEYS = ("LWAVE", "LAECHG", "LVHAR", "LVTOT", "LORBIT", "NEDOS")
#: 本地 CHGCAR 目录名（下载重命名后的 .vasp）
CHG_DIR = "chgfiles"
#: 本地图片目录名（VESTA 处理数据图）
IMAGES_DIR = "images"


class DiffChargeError(ValueError):
    """差分电荷创建失败（参数/文件不满足）。"""


# ------------------------------------------------------------------ POSCAR


@dataclass
class PoscarData:
    """POSCAR 解析结果（保留原文行，重写时只动必要的部分）。"""

    title: str
    lattice: List[str]  # 缩放行 + 3 条晶格行（原文）
    elements: List[str]  # VASP5 元素符号行；VASP4 为空列表
    counts: List[int]
    selective: bool
    mode: str  # Direct / Cartesian（原文）
    coord_lines: List[str]  # 每个原子一行（原文，含可能的 T/F 与标签）
    trailer: List[str] = field(default_factory=list)

    @property
    def n_atoms(self) -> int:
        return len(self.coord_lines)


def _is_int(token: str) -> bool:
    try:
        int(token)
    except (TypeError, ValueError):
        return False
    return True


def parse_poscar_text(text: str) -> PoscarData:
    """解析 POSCAR 文本（VASP4/VASP5、含或不含 Selective Dynamics）。"""
    if not isinstance(text, str) or not text.strip():
        raise DiffChargeError("POSCAR 内容为空")
    lines = [line.rstrip("\r") for line in text.splitlines()]
    lines[0] = lines[0].lstrip("\ufeff")
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 7:
        raise DiffChargeError("POSCAR 至少需要 7 行（标题 / 缩放 / 3 条晶格 / 元素 / 数量）")

    title = lines[0]
    lattice = lines[1:5]
    idx = 5
    tokens = lines[idx].split()
    if tokens and all(_is_int(t) for t in tokens):
        elements: List[str] = []
        counts = [int(t) for t in tokens]
        idx += 1
    else:
        elements = tokens
        if idx + 1 >= len(lines):
            raise DiffChargeError("POSCAR 缺少元素数量行")
        counts = [int(t) for t in lines[idx + 1].split()]
        idx += 2
    if not counts or any(c < 0 for c in counts):
        raise DiffChargeError("POSCAR 元素数量行非法")
    if elements and len(elements) != len(counts):
        raise DiffChargeError(
            f"POSCAR 元素符号数（{len(elements)}）与元素数量数（{len(counts)}）不一致"
        )

    selective = False
    if idx < len(lines) and lines[idx].strip()[:1].lower() == "s":
        selective = True
        idx += 1
    if idx >= len(lines):
        raise DiffChargeError("POSCAR 缺少坐标模式行（Direct / Cartesian）")
    mode = lines[idx]
    if mode.strip()[:1].lower() not in ("d", "c", "k"):
        raise DiffChargeError(f"POSCAR 坐标模式行无法识别：{mode!r}")
    idx += 1

    n_atoms = sum(counts)
    coords: List[str] = []
    cursor = idx
    while cursor < len(lines) and len(coords) < n_atoms:
        if lines[cursor].strip():
            if len(lines[cursor].split()) < 3:
                raise DiffChargeError(f"POSCAR 坐标行非法：{lines[cursor]!r}")
            coords.append(lines[cursor])
        cursor += 1
    if len(coords) < n_atoms:
        raise DiffChargeError(f"POSCAR 坐标行不足：需要 {n_atoms} 行，实际 {len(coords)} 行")
    trailer = lines[cursor:]
    return PoscarData(
        title=title,
        lattice=lattice,
        elements=elements,
        counts=counts,
        selective=selective,
        mode=mode,
        coord_lines=coords,
        trailer=trailer,
    )


def subset_poscar_text(poscar: PoscarData, indices: Sequence[int]) -> str:
    """只保留 `indices`（1 起的 POSCAR 原子序号）的 POSCAR 文本。"""
    wanted = sorted({int(i) for i in indices})
    n_atoms = poscar.n_atoms
    for index in wanted:
        if index < 1 or index > n_atoms:
            raise DiffChargeError(f"原子序号越界：{index}（共 {n_atoms} 个原子）")
    if not wanted:
        raise DiffChargeError("分块不能为空")

    # 每个元素保留几个（按父结构的元素顺序；数量为 0 的元素整块丢掉）
    keep_counts: List[int] = []
    cursor = 1
    for count in poscar.counts:
        block_end = cursor + count - 1
        keep = sum(1 for index in wanted if cursor <= index <= block_end)
        keep_counts.append(keep)
        cursor = block_end + 1

    out: List[str] = [poscar.title, *poscar.lattice]
    if poscar.elements:
        kept = [
            name for name, keep in zip(poscar.elements, keep_counts) if keep > 0
        ]
        if not kept:
            raise DiffChargeError("分块里没有任何原子")
        out.append("  ".join(kept))
        out.append("  ".join(str(keep) for keep in keep_counts if keep > 0))
    else:
        out.append("  ".join(str(keep) for keep in keep_counts if keep > 0))
    if poscar.selective:
        out.append("Selective Dynamics")
    out.append(poscar.mode)
    out.extend(poscar.coord_lines[index - 1] for index in wanted)
    return "\n".join(out) + "\n"


def plan_blocks(
    poscar_text: str, blocks: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """校验分块并生成每个分块的 POSCAR 文本。

    `blocks` = `[{"label": "A", "atoms": [1,2,…]}, …]`（原子序号 1 起）。
    要求：至少 2 块、各自非空、互不重叠、合起来正好是全部原子。
    """
    poscar = parse_poscar_text(poscar_text)
    if len(blocks) < 2:
        raise DiffChargeError("至少需要两个分块（如：分块A + 分块B）")
    seen: Dict[int, int] = {}
    plan: List[Dict[str, Any]] = []
    for order, block in enumerate(blocks, start=1):
        label = str((block or {}).get("label") or f"分块{order}").strip() or f"分块{order}"
        atoms = [int(a) for a in ((block or {}).get("atoms") or [])]
        if not atoms:
            raise DiffChargeError(f"{label} 没有选中任何原子")
        for atom in atoms:
            if atom in seen:
                raise DiffChargeError(f"原子 {atom} 同时出现在多个分块里（第 {seen[atom]}、{order} 块）")
            seen[atom] = order
        plan.append(
            {"index": order, "label": label, "atoms": sorted(set(atoms))}
        )
    missing = [i for i in range(1, poscar.n_atoms + 1) if i not in seen]
    if missing:
        head = "、".join(str(i) for i in missing[:8])
        more = f" 等 {len(missing)} 个" if len(missing) > 8 else ""
        raise DiffChargeError(f"这些原子没有分到任何块：{head}{more}（分块必须覆盖全部原子）")
    for item in plan:
        item["poscar"] = subset_poscar_text(poscar, item["atoms"])
    return plan


# ------------------------------------------------------------------ 目录/命名


def diff_charge_root_local(project_name: str, ele_task: Dict[str, Any]) -> Path:
    """本地差分电荷根目录：`<ele 任务目录>/diffcharge_files/`。"""
    return task_dir(project_name, ele_task) / DIFF_CHARGE_DIR


def block_local_dir(
    project_name: str, ele_task: Dict[str, Any], index: int
) -> Path:
    """分块本地目录：`diffcharge_files/<N>/`（flat，文件直接放这里）。"""
    return diff_charge_root_local(project_name, ele_task) / str(int(index))


def block_remote_dir(ele_remote: str, index: int) -> str:
    return f"{ele_remote.rstrip('/')}/{int(index)}"


#: VTST 的 chgsum.pl / chgdiff.pl 所在目录（可用 servers.json: vtst_dir 覆盖）
VTST_DEFAULT_DIR = "/data/gpfs03/mdye/VTST/vtstscripts"
#: 远端生成的差分文件名（VTST 约定）与本地回传后的名字
CHG_SUM_NAME = "CHGCAR_sum"
CHG_DIFF_NAME = "CHGCAR_diff"
LOCAL_CHG_DIFF_NAME = "CHGCAR_diff.vasp"


def vtst_dir(server: str) -> str:
    """VTST 脚本目录：`servers.json: vtst_dir` → 默认路径。"""
    from config import load_servers

    configured = str(load_servers().get(server, {}).get("vtst_dir") or "").strip()
    return configured or VTST_DEFAULT_DIR


def diff_charge_blocks(
    project: Dict[str, Any], ele_task: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """某个 ele 任务的全部分块子任务（按块序号排序）。"""
    parent = str(ele_task.get("task_id") or "")
    items = [
        task
        for task in project.get("tasks", [])
        if str(task.get("parent_task_id") or "") == parent
        and str(task.get("subtype") or "") == "diff_charge"
    ]
    return sorted(items, key=lambda t: int(t.get("ele_block") or 0))


def diff_charge_group_id(ele_task: Dict[str, Any]) -> str:
    """差分电荷分组 id（同一次创建的多个分块共用一个）。"""
    return f"ele_diff_{int(__import__('time').time() * 1000)}"


# ------------------------------------------------------------------ INCAR


def count_magmom_entries(incar_text: str) -> Optional[int]:
    """MAGMOM 的条目数（`4*3 2*-3 32*0` → 38）；没有 MAGMOM 返回 None。"""
    match = re.search(r"(?im)^[ \t]*MAGMOM[ \t]*=[ \t]*(.+)$", incar_text or "")
    if not match:
        return None
    total = 0
    for token in match.group(1).split():
        head, sep, _ = token.partition("*")
        if sep:
            try:
                total += int(head)
            except ValueError:
                return None
        else:
            total += 1
    return total


def strip_incar_keys(
    incar_text: str, keys: Sequence[str] = DROP_INCAR_KEYS
) -> Tuple[str, List[str]]:
    """删掉指定 INCAR 键所在的行，返回 `(新文本, 被删掉的键)`。

    注释行与其它参数原样保留；重复出现的键全部删掉。
    """
    wanted = {str(k).upper() for k in keys}
    kept: List[str] = []
    removed: List[str] = []
    for line in (incar_text or "").splitlines():
        body = line.split("#", 1)[0].split("!", 1)[0]
        if "=" in body:
            key = body.split("=", 1)[0].strip().upper()
            if key in wanted:
                if key not in removed:
                    removed.append(key)
                continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if kept else ""), removed


def check_incar(incar_text: str, extra: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, str], List[str]]:
    """复制 INCAR 时：先**去掉分块不需要的输出参数**，再校验关键参数（不一致就地改）。

    `LCHARG = .TRUE.`、`IBRION = -1`、`ISTART = 0`、`ICHARG = 2`。
    其它输出类参数（`LWAVE/LAECHG/LVHAR/LVTOT/LORBIT/NEDOS`）整行删除 —— 分块只需要 CHGCAR。

    返回 `(新文本, 改了什么, 警告)`。MAGMOM 不动（用户口径：先直接复制，后续再做自动化）。
    """
    text, removed = strip_incar_keys(incar_text or "")
    fixes: Dict[str, str] = {}

    def _current(key: str) -> Optional[str]:
        match = re.search(
            rf"^[ \t]*{key}[ \t]*=[ \t]*([^\s#!]+)", text, flags=re.IGNORECASE | re.MULTILINE
        )
        return match.group(1) if match else None

    for key, want in REQUIRED_INCAR.items():
        have = _current(key)
        if have is None:
            fixes[key] = f"缺失→{want}"
        elif have.strip().upper() != str(want).strip().upper():
            fixes[key] = f"{have}→{want}"
    changes: Dict[str, Any] = dict(REQUIRED_INCAR)
    changes.update({str(k): v for k, v in (extra or {}).items() if v is not None})
    explicit = dict(extra or {})
    updated, warnings = modify_incar(text, changes)
    # 用户显式传了同名字段 → 以他传的为准，不算“我们改过”
    for key in explicit:
        fixes.pop(str(key), None)
    if removed:
        warnings.insert(0, f"已去掉分块不需要的输出参数：{'、'.join(removed)}（只保留 LCHARG）")
    return updated, fixes, warnings


# ------------------------------------------------------------------ 创建


def read_main_poscar(server: str, project: Dict[str, Any], task: Dict[str, Any]) -> str:
    """读取主任务的 POSCAR 文本：优先本地镜像 `files/POSCAR`，缺失时从远端取。"""
    local = local_files_dir(str(project.get("name") or ""), task) / "POSCAR"
    if local.is_file() and local.stat().st_size > 0:
        return local.read_text(encoding="utf-8", errors="replace")
    remote = task_remote_dir(server, task).rstrip("/")
    if remote:
        text = _download_text(server, f"{remote}/POSCAR")
        if text.strip():
            return text
    raise DiffChargeError("主任务没有 POSCAR（先在 POSCAR 页生成/上传后再做差分电荷）")


def read_main_incar(server: str, project: Dict[str, Any], task: Dict[str, Any]) -> str:
    """读取主任务的 INCAR 文本：优先本地镜像 `files/INCAR`，缺失时从远端取。"""
    local = local_files_dir(str(project.get("name") or ""), task) / "INCAR"
    if local.is_file() and local.stat().st_size > 0:
        return local.read_text(encoding="utf-8", errors="replace")
    remote = task_remote_dir(server, task).rstrip("/")
    if remote:
        return _download_text(server, f"{remote}/INCAR")
    return ""


def _download_text(server: str, remote_path: str) -> str:
    result = ssh.run_remote(server, f'cat "{remote_path}" 2>/dev/null || true', timeout=60)
    return str(result.get("stdout") or "")


def _run_capture(server: str, cmds: List[str], timeout: int = 180) -> Dict[str, Any]:
    """跑一段远端 bash，**返回原始结果**（stdout/stderr/exit_code），不抛异常。

    与 `_run` 的区别：这里的脚本会主动打 `@@@XXX` 标记说明失败原因（缺文件 / 脚本缺失 / 转换失败…），
    调用方需要读原始输出才能给出准确提示。
    """
    import base64

    script = "\n".join(cmds)
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return ssh.run_remote(server, f"echo {encoded} | base64 -d | bash", timeout=timeout)


def _run(server: str, cmds: List[str], timeout: int = 180) -> None:
    import base64

    script = "\n".join(["set -e", *cmds])
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    result = ssh.run_remote(server, f"echo {encoded} | base64 -d | bash", timeout=timeout)
    if int(result.get("exit_code") or 0) != 0:
        raise DiffChargeError(
            f"远端命令执行失败（exit={result.get('exit_code')}）："
            f"{(result.get('stderr') or result.get('stdout') or '').strip()[:300]}"
        )


def create_block_files(
    server: str,
    project: Dict[str, Any],
    task: Dict[str, Any],
    plan: List[Dict[str, Any]],
    *,
    incar_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成各分块的本地文件与远端目录（不含任务登记，登记由调用方写库）。

    步骤：①② 写本地 `diffcharge_files/<N>/POSCAR|INCAR`；
    ③ **先**在远端建好主目录与各分块目录，再上传 POSCAR/INCAR、复制 KPOINTS/vasp.lsf
    （SFTP put 不会自动建父目录 —— 建目录晚一步就会报 `[Errno 2] No such file`）；
    ④ 主任务目录跑一次 `pos2pot`（递归 → 主结构与各分块一起生成 POTCAR）。
    """
    project_name = str(project.get("name") or "")
    ele_remote = task_remote_dir(server, task).rstrip("/")
    if not ele_remote:
        raise DiffChargeError("主任务缺少远程目录")

    block_count = len(plan)
    root_local = diff_charge_root_local(project_name, task)
    for sub in (CHG_DIR, IMAGES_DIR):
        (root_local / sub).mkdir(parents=True, exist_ok=True)

    raw_incar = read_main_incar(server, project, task)
    incar_text, fixes, warnings = check_incar(raw_incar, incar_params)
    _, incar_removed = strip_incar_keys(raw_incar)
    # MAGMOM 目前是**原样复制**（用户口径：留后续做自动化），但条目数与分块原子数不一致时
    # VASP 会直接报错，这里只**提示**不改动，避免分块白跑一轮。
    magmom_count = count_magmom_entries(incar_text)
    if magmom_count is not None:
        for item in plan:
            if magmom_count != len(item["atoms"]):
                warnings.append(
                    f"{item['label']}：MAGMOM 有 {magmom_count} 个条目，但该分块只有 "
                    f"{len(item['atoms'])} 个原子（MAGMOM 暂按『原样复制』处理，"
                    "请手动改成对应的每原子初始磁矩，否则 VASP 会报错）"
                )

    # ① 远端目录必须**先**建好：ssh.upload_file 走 SFTP put，目标目录不存在会直接抛
    #    `[Errno 2] No such file`（2026-10-13 用户踩坑：`PMS@model1/1` 不存在，
    #    而之前的 model2 恰好手工建过 1/2 所以没暴露）。
    _run(
        server,
        [f'mkdir -p "{ele_remote}"']
        + [f'mkdir -p "{block_remote_dir(ele_remote, int(item["index"]))}"' for item in plan],
        timeout=120,
    )

    remote_cmds: List[str] = []
    written: List[Dict[str, Any]] = []
    for item in plan:
        index = int(item["index"])
        local_dir = block_local_dir(project_name, task, index)
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "POSCAR").write_text(item["poscar"], encoding="utf-8", newline="\n")
        (local_dir / "INCAR").write_text(incar_text, encoding="utf-8", newline="\n")
        remote_block = block_remote_dir(ele_remote, index)
        ssh.upload_file(server, str(local_dir / "POSCAR"), f"{remote_block}/POSCAR")
        ssh.upload_file(server, str(local_dir / "INCAR"), f"{remote_block}/INCAR")
        written.append(
            {
                "index": index,
                "label": item["label"],
                "atoms": item["atoms"],
                "atoms_count": len(item["atoms"]),
                "local_dir": to_local_rel(str(local_dir)),
                "remote_dir": remote_block,
            }
        )
    remote_cmds = [
        f'for i in {" ".join(str(int(i["index"])) for i in plan)}; do',
        f'  [ -f "{ele_remote}/KPOINTS" ] && cp "{ele_remote}/KPOINTS" "{ele_remote}/$i/KPOINTS" || true',
        f'  [ -f "{ele_remote}/vasp.lsf" ] && cp "{ele_remote}/vasp.lsf" "{ele_remote}/$i/vasp.lsf" || true',
        f'  [ -f "{ele_remote}/submit.sh" ] && cp "{ele_remote}/submit.sh" "{ele_remote}/$i/submit.sh" || true',
        "done",
    ]
    _run(server, remote_cmds, timeout=180)

    # POTCAR：主任务目录跑一次 pos2pot（脚本递归），主结构与各分块一起出
    potcar: Dict[str, Any] = {}
    try:
        potcar = run_pos2pot(server, ele_remote, timeout=180, use_latest_con=False)
    except Exception as e:  # noqa: BLE001 - POTCAR 失败不影响分块创建，交给前端提示
        warnings.append(f"运行 pos2pot 生成 POTCAR 失败：{e}")
    # 各分块的 POTCAR 单独核一遍：pos2pot 的摘要只反映**主目录**，而主目录可能没有 POSCAR
    # （用户口径：主任务目录就是完整体系，一般有；但分块才是这次真正要用的）
    potcar_blocks: Dict[str, int] = {}
    try:
        probe = " ; ".join(
            f'[ -s "{block_remote_dir(ele_remote, int(item["index"]))}/POTCAR" ] '
            f'&& echo "POTCAR_OK {int(item["index"])} $(wc -c < "{block_remote_dir(ele_remote, int(item["index"]))}/POTCAR" | tr -d \' \')" '
            f'|| echo "POTCAR_MISSING {int(item["index"])}"'
            for item in plan
        )
        out = ssh.run_remote(server, probe, timeout=60).get("stdout") or ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "POTCAR_OK":
                potcar_blocks[parts[1]] = int(parts[2]) if len(parts) > 2 else 0
        missing_blocks = [
            str(int(item["index"]))
            for item in plan
            if str(int(item["index"])) not in potcar_blocks
        ]
        if missing_blocks:
            warnings.append(
                f"这些分块没有生成 POTCAR（可点分块页的「生成 POTCAR（pos2pot）」重试）：{'、'.join(missing_blocks)}"
            )
    except Exception as e:  # noqa: BLE001 - 只是核对，失败不影响创建
        warnings.append(f"核对分块 POTCAR 失败：{e}")

    return {
        "blocks": written,
        "block_count": block_count,
        "incar_fixes": fixes,
        "incar_removed": incar_removed,
        "incar_warnings": warnings,
        "potcar": potcar.get("potcar") or {},
        # 以**各分块**是否都有 POTCAR 为准（主目录没有 POSCAR 时 pos2pot 的摘要会是 MISSING）
        "potcar_generated": len(potcar_blocks) == len(plan),
        "potcar_blocks": potcar_blocks,
        "remote_root": ele_remote,
        "local_root": to_local_rel(str(root_local)),
        "created_at": now_iso(),
    }


def compute_charge_difference(
    server: str, project: Dict[str, Any], task: Dict[str, Any]
) -> Dict[str, Any]:
    """**远端**用 VTST 脚本算好差分电荷，只把 `CHGCAR_diff` 回传本地（2026-10-14 口径）。

    在主任务目录里执行：

        chgsum.pl 1/CHGCAR 2/CHGCAR …   → CHGCAR_sum（各分块电荷密度相加）
        chgdiff.pl CHGCAR CHGCAR_sum    → CHGCAR_diff（完整 − 分块之和）

    **为什么改成这样**：三个 CHGCAR 各 200MB+，原来要全拉回本地（700MB+）再自己处理，
    现在远端一条命令算完，只回传一个差分文件（约 200MB），本地也不用装 VTST。
    本地落 `<任务>/diffcharge_files/chgfiles/CHGCAR_diff.vasp`（保留 .vasp 扩展名，VESTA 直接能开）。

    CHGCAR 体积大，只在**归档时**（或手动触发）调用，不进巡检循环。
    """
    project_name = str(project.get("name") or "")
    ele_remote = task_remote_dir(server, task).rstrip("/")
    blocks = diff_charge_blocks(project, task)
    if not ele_remote or not blocks:
        raise DiffChargeError("该任务还没有差分电荷分块")

    script_dir = vtst_dir(server)
    inputs = " ".join(f'"{int(b.get("ele_block") or 0)}/CHGCAR"' for b in blocks)
    cmds = [
        "set -e",
        f'cd "{ele_remote}"',
        f'VTST="{script_dir}"',
        "for f in chgsum.pl chgdiff.pl; do",
        '  [ -x "$VTST/$f" ] || { echo "@@@NOSCRIPT=$VTST/$f"; exit 5; }',
        "done",
        f"for f in CHGCAR {inputs}; do",
        '  [ -s "$f" ] || { echo "@@@MISSING=$f"; exit 4; }',
        "done",
        # 注意：`set -e` 下 `OUT=$(cmd)` 失败会直接退出脚本，因此必须用 `if !` 包住才能
        # 把失败原因用 `@@@CHGSUM_FAIL` 记号带回本地（否则只剩一句笼统的"执行失败"）。
        f'if ! OUT=$("$VTST/chgsum.pl" {inputs} 2>&1); then '
        'echo "@@@CHGSUM_FAIL"; echo "$OUT" | tail -n 20; exit 6; fi',
        f'[ -s "{CHG_SUM_NAME}" ] || {{ echo "@@@NO_SUM"; exit 7; }}',
        f'if ! OUT=$("$VTST/chgdiff.pl" CHGCAR {CHG_SUM_NAME} 2>&1); then '
        'echo "@@@CHGDIFF_FAIL"; echo "$OUT" | tail -n 20; exit 8; fi',
        f'[ -s "{CHG_DIFF_NAME}" ] || {{ echo "@@@NO_DIFF"; exit 9; }}',
        f'echo "@@@SIZE=$(wc -c < "{CHG_DIFF_NAME}" | tr -d \' \')"',
    ]
    started = time.time()
    result = _run_capture(server, cmds, timeout=1800)
    raw = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()

    def fail(message: str) -> DiffChargeError:
        tail = " / ".join(line.strip() for line in raw.splitlines() if line.strip())[-500:]
        return DiffChargeError(f"{message}{('；远端输出：' + tail) if tail else ''}")

    for marker, message in (
        ("@@@NOSCRIPT=", "远端找不到 VTST 脚本"),
        ("@@@MISSING=", "远端缺少 CHGCAR"),
        ("@@@CHGSUM_FAIL", "chgsum.pl 执行失败"),
        ("@@@NO_SUM", "chgsum.pl 跑完但没有生成 CHGCAR_sum"),
        ("@@@CHGDIFF_FAIL", "chgdiff.pl 执行失败"),
        ("@@@NO_DIFF", "chgdiff.pl 跑完但没有生成 CHGCAR_diff"),
    ):
        if marker in raw:
            detail = ""
            if marker.endswith("="):
                detail = raw.split(marker, 1)[1].split("\n", 1)[0].strip()
                if marker.startswith("@@@NOSCRIPT"):
                    detail += "（可用 servers.json: vtst_dir 覆盖 VTST 目录）"
            raise fail(f"{message}{('：' + detail) if detail else ''}")
    if int(result.get("exit_code") or 0) != 0:
        raise fail("远端计算差分电荷失败")

    chg_dir = diff_charge_root_local(project_name, task) / CHG_DIR
    chg_dir.mkdir(parents=True, exist_ok=True)
    target = chg_dir / LOCAL_CHG_DIFF_NAME
    remote_path = f"{ele_remote}/{CHG_DIFF_NAME}"
    if not ssh.download_file(server, remote_path, str(target)):
        raise fail("差分文件回传失败（远端 CHGCAR_diff 下载不到）")
    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise fail("差分文件回传后为空")
    return {
        "ok": True,
        "block_count": len(blocks),
        "remote_path": remote_path,
        "remote_sum": f"{ele_remote}/{CHG_SUM_NAME}",
        "local_path": to_local_rel(str(target)),
        "dir": to_local_rel(str(chg_dir)),
        "bytes": target.stat().st_size,
        "elapsed_seconds": round(time.time() - started, 1),
        "vtst_dir": script_dir,
    }


def build_block_task(
    project: Dict[str, Any],
    task: Dict[str, Any],
    item: Dict[str, Any],
    *,
    group_id: str,
    task_id: str,
) -> Dict[str, Any]:
    """分块子任务记录（字段与 `groups._base_record` 对齐，`local_layout=flat`）。"""
    index = int(item["index"])
    now = now_iso()
    project_name = str(project.get("name") or "")
    server = str(project.get("server") or "")
    local_dir = block_local_dir(project_name, task, index)
    remote_block = block_remote_dir(task_remote_dir(server, task), index)
    return {
        "task_id": task_id,
        "task_type": ELE_DIFF_TYPE,
        "subtype": "diff_charge",
        "model_name": f"{task.get('model_name') or 'ele'}_diff{index}",
        "status": "pending",
        "last_energy": None,
        "last_check_time": None,
        "job_id": None,
        "notes": "",
        "continuation_ready": False,
        "continuation_dir": None,
        "dir_path": to_local_rel(str(local_dir)),
        # remote_dir 存**相对路径**（与其它任务一致）；local_layout=flat 让本地文件直接落在
        # diffcharge_files/<N>/ 下（不再套 files/）
        "remote_dir": to_remote_rel(server, remote_block),
        "local_layout": "flat",
        "group": None,
        "parent_task_id": str(task.get("task_id") or ""),
        "input_source": {
            "kind": "diff_charge",
            "from_task_id": str(task.get("task_id") or ""),
            "source": "主任务 POSCAR / INCAR（LCHARG=.TRUE. / IBRION=-1 已校验）",
        },
        "ele_block": index,
        "ele_block_label": str(item.get("label") or f"分块{index}"),
        "ele_block_atoms": list(item.get("atoms") or []),
        "diff_charge_group": group_id,
        "created_at": now,
        "updated_at": now,
    }
