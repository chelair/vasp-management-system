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
    diffcharge_files/chgfiles/{1.vasp,2.vasp,…,(块数+1).vasp}
                              ← CHGCAR 下载重命名：1..N = 各分块，N+1 = 完整结构
    diffcharge_files/images/  ← VESTA 处理出来的图

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


def chg_file_name(block_count: int, index: int) -> str:
    """CHGCAR 下载后的文件名：`<N>.vasp`（1..块数 = 各分块，块数+1 = 完整结构）。"""
    return f"{int(index)}.vasp"


def full_chg_index(block_count: int) -> int:
    """完整结构的 CHGCAR 编号 = 分块数 + 1（两块 → 3.vasp）。"""
    return int(block_count) + 1


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
    ③ 远端 `mkdir` + 上传 POSCAR/INCAR + 复制 KPOINTS/vasp.lsf；
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

    remote_cmds: List[str] = []
    written: List[Dict[str, Any]] = []
    for item in plan:
        index = int(item["index"])
        local_dir = block_local_dir(project_name, task, index)
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "POSCAR").write_text(item["poscar"], encoding="utf-8", newline="\n")
        (local_dir / "INCAR").write_text(incar_text, encoding="utf-8", newline="\n")
        remote_block = block_remote_dir(ele_remote, index)
        remote_cmds.append(f'mkdir -p "{remote_block}"')
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
    remote_cmds += [
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

    return {
        "blocks": written,
        "block_count": block_count,
        "incar_fixes": fixes,
        "incar_removed": incar_removed,
        "incar_warnings": warnings,
        "potcar": potcar.get("potcar") or {},
        "potcar_generated": bool(potcar.get("generated")),
        "remote_root": ele_remote,
        "local_root": to_local_rel(str(root_local)),
        "full_chg_index": full_chg_index(block_count),
        "created_at": now_iso(),
    }


def download_charge_files(
    server: str, project: Dict[str, Any], task: Dict[str, Any]
) -> Dict[str, Any]:
    """把各分块与完整结构的 CHGCAR 拉回本地，重命名成 `chgfiles/<N>.vasp`。

    编号口径（用户 2026-10-13）：1..块数 = 各分块，**块数+1 = 完整结构**
    （两块 → `1.vasp` 分块A、`2.vasp` 分块B、`3.vasp` 完整体系）。
    CHGCAR 体积大，只在**归档时**（或手动触发）调用，不进巡检循环。
    """
    project_name = str(project.get("name") or "")
    ele_remote = task_remote_dir(server, task).rstrip("/")
    blocks = diff_charge_blocks(project, task)
    if not ele_remote or not blocks:
        raise DiffChargeError("该任务还没有差分电荷分块")
    chg_dir = diff_charge_root_local(project_name, task) / CHG_DIR
    chg_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    missing: List[str] = []
    for block in blocks:
        index = int(block.get("ele_block") or 0)
        remote = f"{ele_remote}/{index}/CHGCAR"
        target = chg_dir / chg_file_name(len(blocks), index)
        try:
            ok = ssh.download_file(server, remote, str(target))
        except Exception:  # noqa: BLE001 - 单文件失败不影响其它
            ok = False
        if ok and target.is_file() and target.stat().st_size > 0:
            saved.append(target.name)
        else:
            if target.is_file() and target.stat().st_size == 0:
                target.unlink(missing_ok=True)
            missing.append(f"{index}.vasp（{remote}）")
    full_index = full_chg_index(len(blocks))
    remote_full = f"{ele_remote}/CHGCAR"
    target_full = chg_dir / chg_file_name(len(blocks), full_index)
    try:
        ok = ssh.download_file(server, remote_full, str(target_full))
    except Exception:  # noqa: BLE001
        ok = False
    if ok and target_full.is_file() and target_full.stat().st_size > 0:
        saved.append(target_full.name)
    else:
        if target_full.is_file() and target_full.stat().st_size == 0:
            target_full.unlink(missing_ok=True)
        missing.append(f"{full_index}.vasp（{remote_full}）")
    return {
        "dir": to_local_rel(str(chg_dir)),
        "saved": saved,
        "missing": missing,
        "block_count": len(blocks),
        "full_index": full_index,
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
