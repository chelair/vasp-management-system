"""作业输入文件状态：远端快照 / 本地草稿 / 变更台账（v0.8.2）。

三层职责（方案见 process.md §6.11）：

1. **远端 conN/**：这次计算真正用的输入文件（唯一真相）；
2. **本地镜像**：远端"最新计算目录"的副本，落盘在 `<任务目录>/files/`
   （INCAR / KPOINTS / POSCAR / CONTCAR + 由 vasp2cif 转出的 *.cif），
   元数据（哈希 / 参数 / 来源目录 / 时间）写在 `task["input_state"]`；
   **v0.8.7 起本地不再有 `inputs/` 与 `conN/` 子目录** —— 每个任务只有这一份文件，
   每次同步用远端最新目录覆盖（有未生效草稿的文件跳过，见 `build_snapshot`）；
3. **草稿 drafts**：用户在系统里改的参数，**不直接改远端**，
   只在**下一次续算**时由 `apply_drafts` 相关脚本应用，并把每条改动
   记进台账（changes）里标记 applied_at / applied_in。

为什么不在运行中改远端：运行中的作业不会重读 INCAR，直接改最新目录会把
"这次计算到底用了什么参数"的记录抹掉；所以改动一律延到下一次续算生效。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from dates import now_iso
from paths import resolve_remote_path
from task_paths import task_dir

SNAPSHOT_FILES = ("INCAR", "KPOINTS", "POSCAR", "CONTCAR")
CIF_FILES = ("POSCAR", "CONTCAR")
#: 归档（关闭任务）时静默拉回本地的文件：普通任务取"最新计算目录"下的这些文件
#: （2026-09-22 用户口径：CONTCAR、INCAR、KPOINTS、POSCAR、OUTCAR、OSZICAR）
ARCHIVE_OUTPUT_FILES = ("CONTCAR", "INCAR", "KPOINTS", "POSCAR", "OUTCAR", "OSZICAR")
#: NEB 任务归档：共享文件放 `files/`，各映像 `00..NN` 的这四个文件放 `files/<映像号>/`
ARCHIVE_NEB_SHARED = ("INCAR", "KPOINTS")
ARCHIVE_NEB_IMAGE_FILES = ("POSCAR", "CONTCAR", "OUTCAR", "OSZICAR")


# --------------------------------------------------------------------- 解析


def parse_incar_text(text: str) -> Dict[str, str]:
    """INCAR 文本 → {KEY: 值}（去注释、键大写、**值保留完整内容**）。

    注意值不能按空格截断：像 `DIPOL = 0.5 0.5 0.18`、`MAGMOM = 5*2.0 3*1.0`
    这类参数值本身含空格，截成第一个 token 会把参数改坏（v0.8.2 踩过）。
    """
    params: Dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].split("!", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = " ".join(value.split())  # 压掉多余空白，但保留多个 token
        if key:
            params[key] = value
    return params


def parse_kpoints_mesh(text: str) -> Tuple[Optional[List[int]], str]:
    """KPOINTS 文本 → (网格, 说明)；自动网格 / 显式 k 点列表返回 (None, 说明)。"""
    lines = [
        line.strip()
        for line in (text or "").splitlines()
        if line.strip() and not line.strip().startswith(("#", "!"))
    ]
    if len(lines) < 4:
        return None, "KPOINTS 内容不完整"
    mode = lines[2]
    parts = lines[3].split()
    if len(parts) < 3:
        return None, f"KPOINTS 网格行无法解析（{mode}）"
    try:
        mesh = [int(float(p)) for p in parts[:3]]
    except ValueError:
        return None, f"不是自动网格（{mode}）"
    if all(m > 0 for m in mesh):
        return mesh, mode
    return None, f"自动网格 0 0 0（{mode}）"


def set_kpoints_mesh(text: str, mesh: List[int]) -> str:
    """把 KPOINTS 的网格行（第 4 个有效行）替换成新的 k 网格。

    行首不留空格（早期版本写成 ` 2 3 1`，首个数前多一个空格，看着像缩进错误）。
    """
    lines = (text or "").splitlines()
    seen = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        seen += 1
        if seen == 4:
            lines[index] = f"{mesh[0]} {mesh[1]} {mesh[2]}"
            return "\n".join(lines) + "\n"
    return text


def poscar_meta(text: str) -> Dict[str, Any]:
    """POSCAR 摘要：元素 / 各元素原子数 / 晶格常数（供前端展示与差异摘要）。"""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 7:
        return {}
    try:
        scale = float(lines[1].split()[0])
        vectors = [[float(x) for x in lines[2 + i].split()[:3]] for i in range(3)]
        symbols_line = lines[5].split()
        if all(re.fullmatch(r"\d+", s) for s in symbols_line):
            elements = ["?"]  # VASP4：无元素行，只有计数
            counts = [int(s) for s in symbols_line]
        else:
            elements = symbols_line
            counts = [int(x) for x in lines[6].split()]
    except (ValueError, IndexError):
        return {}

    def norm(vec: List[float]) -> float:
        return round(abs(scale) * (sum(c * c for c in vec) ** 0.5), 4)

    return {
        "elements": elements,
        "counts": counts,
        "n_atoms": sum(counts),
        "lengths": {
            "a": norm(vectors[0]),
            "b": norm(vectors[1]),
            "c": norm(vectors[2]),
        },
    }


def _hash(text: str) -> str:
    return "sha1:" + hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 快照落盘


def snapshot_dir(task: Dict[str, Any]) -> Path:
    """本地计算文件目录：<任务目录>/files/。

    v0.8.7 前是独立的 `<任务目录>/inputs/` 快照目录；现在合并成一份 —— 与编辑器的
    "生成到本地"、巡检结构同步写的是同一个目录，同步时按最新远端目录覆盖。
    """
    task_with_project = dict(task)
    task_with_project.setdefault("project_name", task.get("project_name", ""))
    root = task_dir(str(task.get("project_name") or ""), task_with_project)
    return root / "files"


def _write_snapshot_file(task: Dict[str, Any], name: str, text: str) -> Path:
    path = snapshot_dir(task) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_snapshot_text(task: Dict[str, Any], name: str) -> Optional[str]:
    path = snapshot_dir(task) / name
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _convert_to_cif(task: Dict[str, Any], name: str) -> Optional[str]:
    """把快照里的 POSCAR/CONTCAR 转成同目录下的 .cif（返回 CIF 文本）。"""
    from cif_convert import convert_structure_to_cif

    src = snapshot_dir(task) / name
    out = snapshot_dir(task) / f"{name}.cif"
    if not src.is_file():
        return None
    if convert_structure_to_cif(src, out, overwrite=True) and out.is_file():
        try:
            return out.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return None


def read_snapshot_cif(task: Dict[str, Any], name: str) -> Optional[str]:
    path = snapshot_dir(task) / f"{name}.cif"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# -------------------------------------------------------------------- 同步


def _newest_dir_with_file(server: str, remote_dir: str, filename: str) -> str:
    """一次 exec 定位"最新且真的含 <filename> 的目录"（conN 优先，否则主目录）。"""
    if ssh.mock_enabled():
        # 本地模拟模式（VASP_SSH_MOCK=1）：直接扫 mock 远端目录树，便于离线联调
        base = ssh.mock_local_path(remote_dir)

        def _has_file(path: Path) -> bool:
            f = path / filename
            return f.is_file() and f.stat().st_size > 0

        def _con_index(path: Path) -> int:
            digits = "".join(ch for ch in path.name if ch.isdigit())
            return int(digits or 0)

        for candidate in sorted(
            (p for p in base.glob("con[0-9]*") if p.is_dir()),
            key=_con_index,
            reverse=True,
        ):
            if _has_file(candidate):
                return f"{remote_dir.rstrip('/')}/{candidate.name}"
        if _has_file(base):
            # 返回**远端路径**（与 conN 分支一致）：mock 模式下调用方还会再走一次
            # `ssh.download_file` 的路径映射，返回模拟根下的绝对路径会被二次拼接而找不到文件
            return remote_dir.rstrip("/")
        return ""
    script = (
        f'for d in $(ls -d "{remote_dir}"/con[0-9]* 2>/dev/null | sort -V -r); do '
        f'if [ -s "$d/{filename}" ]; then echo "$d"; exit 0; fi; done; '
        f'if [ -s "{remote_dir}/{filename}" ]; then echo "{remote_dir}"; fi'
    )
    result = ssh.run_remote(server, f"bash -c '{script}'", timeout=30)
    if result.get("exit_code") != 0:
        detail = (result.get("stderr") or result.get("stdout") or "").strip()
        raise RuntimeError(detail or "定位远端输入目录失败")
    return str(result.get("stdout") or "").strip()


def _download_mirror_file(
    server: str, task: Dict[str, Any], remote_path: str, name: str
) -> bool:
    """下载一个文件覆盖到本地镜像目录（返回是否成功；失败不抛错）。"""
    target = snapshot_dir(task) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        return bool(ssh.download_file(server, remote_path, str(target)))
    except Exception:  # noqa: BLE001 - 单文件失败不影响其它文件
        return False


def _list_remote_dirs(server: str, remote_dir: str, pattern: str) -> List[str]:
    """远端列出匹配 `pattern` 的**目录名**（如 `[0-9]*` 映像、`con[0-9]*` 续算目录）。"""
    if ssh.mock_enabled():
        base = ssh.mock_local_path(remote_dir)
        if not base.is_dir():
            return []
        names = [p.name for p in base.glob(pattern) if p.is_dir()]
    else:
        script = (
            f'RD="{remote_dir}"; [ -d "$RD" ] || exit 0; '
            f'for d in "$RD"/{pattern}; do [ -d "$d" ] && basename "$d"; done'
        )
        result = ssh.run_remote(server, f"bash -c '{script}'", timeout=30)
        if result.get("exit_code") != 0:
            raise RuntimeError(
                (result.get("stderr") or result.get("stdout") or "远端列目录失败").strip()[:200]
            )
        names = [ln.strip() for ln in str(result.get("stdout") or "").splitlines() if ln.strip()]

    def _index(name: str) -> int:
        digits = "".join(ch for ch in name if ch.isdigit())
        return int(digits or 0)

    return sorted(set(names), key=_index)


def pending_files(task: Dict[str, Any]) -> set:
    """有"未生效草稿"的文件名集合（这些文件同步时不覆盖本地副本）。"""
    state = task.get("input_state") or {}
    return {
        str(change.get("file"))
        for change in (state.get("changes") or [])
        if not change.get("applied_at")
    }


def _download_text(server: str, remote_path: str) -> Optional[str]:
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as fh:
        tmp = fh.name
    try:
        if not ssh.download_file(server, remote_path, tmp):
            return None
        return Path(tmp).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


def build_snapshot(
    server: str, task: Dict[str, Any], *, kind: str = "manual"
) -> Dict[str, Any]:
    """从远端最新目录取回输入文件，**覆盖**本地镜像并返回 input_state（不落库）。

    成本：1 次 exec（定位目录）+ 4 次 SFTP 小文件下载（INCAR/KPOINTS/POSCAR/CONTCAR）。
    **有未生效草稿的文件跳过覆盖**（保留本地副本，草稿留到下次续算生效），
    这些文件的元数据仍按远端记录并标记 `protected: true`，供界面显示"本次计算值"。
    """
    remote_dir = resolve_remote_path(
        server, str(task.get("remote_dir") or "")
    ).rstrip("/")
    if not remote_dir:
        raise ValueError("任务缺少远程目录")
    source_dir = _newest_dir_with_file(server, remote_dir, "INCAR") or remote_dir

    texts: Dict[str, str] = {}
    for name in SNAPSHOT_FILES:
        text = _download_text(server, f"{source_dir}/{name}")
        if text is not None and text.strip():
            texts[name] = text
    if not texts:
        raise RuntimeError(f"远端目录 {source_dir} 下没有可同步的输入文件")

    protected = pending_files(task)
    files: Dict[str, Any] = {}
    for name, text in texts.items():
        meta: Dict[str, Any] = {"hash": _hash(text), "size": len(text)}
        if name in protected:
            # 有未生效草稿：不覆盖本地副本；元数据仍按远端记录（界面显示"本次计算值"）
            meta["protected"] = True
            meta["remote_hash"] = meta["hash"]
        else:
            _write_snapshot_file(task, name, text)
        if name == "INCAR":
            meta["params"] = parse_incar_text(text)
        elif name == "KPOINTS":
            mesh, note = parse_kpoints_mesh(text)
            meta["mesh"] = mesh
            meta["mesh_note"] = note
        else:
            meta.update(poscar_meta(text))
        files[name] = meta
    for name in CIF_FILES:
        if name in texts and name not in protected:
            _convert_to_cif(task, name)

    con = source_dir[len(remote_dir):].lstrip("/") or ""
    return {
        "source": {
            "remote_dir": source_dir,
            "con": con,
            "job_id": str(task.get("job_id") or "") or None,
            "synced_at": now_iso(),
            "kind": kind,
            "protected": sorted(name for name in texts if name in protected),
        },
        "files": files,
        "draft": {},
        "changes": [],
    }


def _archive_one_dir(
    server: str,
    task: Dict[str, Any],
    source_dir: str,
    names: Tuple[str, ...],
    *,
    subdir: str = "",
    drafted: Optional[set] = None,
) -> Tuple[List[str], List[str], List[str]]:
    """把 `source_dir`（可选 `subdir` 子目录）下的若干文件下到本地镜像。

    返回 `(saved, missing, overwrote_draft)`：第三项是"这次覆盖了本地有未生效草稿的副本"
    的文件名（归档留档要真实，所以照下，但要在审计里标出来）。
    """
    saved: List[str] = []
    missing: List[str] = []
    overwrote: List[str] = []
    for name in names:
        remote_path = f"{source_dir}/{subdir}/{name}" if subdir else f"{source_dir}/{name}"
        local_name = f"{subdir}/{name}" if subdir else name
        if _download_mirror_file(server, task, remote_path, local_name):
            saved.append(local_name)
            if drafted and local_name in drafted:
                overwrote.append(local_name)
        else:
            missing.append(local_name)
    return saved, missing, overwrote


def download_archive_outputs(server: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """归档（关闭任务）时静默把"本次计算用到的文件"拉回本地镜像。

    - **普通任务**（opt / frac / ele…）：取"最新计算目录"（含 OUTCAR 的最大编号 conN，否则主目录），
      拉 `CONTCAR / INCAR / KPOINTS / POSCAR / OUTCAR / OSZICAR`（存在才下）；
    - **NEB 任务**：共享文件 `INCAR / KPOINTS` 放 `files/`，各映像 `00..NN` 的
      `POSCAR / CONTCAR / OUTCAR / OSZICAR` 放 `files/<映像号>/`
      （源目录 = 最大编号 conN，无则任务主目录）。

    单文件失败只记录、不抛错 —— 归档本身不依赖它。
    """
    remote_dir = resolve_remote_path(
        server, str(task.get("remote_dir") or "")
    ).rstrip("/")
    if not remote_dir:
        raise ValueError("任务缺少远程目录")
    pending = pending_files(task)

    if str(task.get("task_type") or "") == "neb":
        cons = _list_remote_dirs(server, remote_dir, "con[0-9]*")
        source_dir = f"{remote_dir}/{cons[-1]}" if cons else remote_dir
        saved, missing, overwrote = _archive_one_dir(
            server, task, source_dir, ARCHIVE_NEB_SHARED, drafted=pending
        )
        images = _list_remote_dirs(server, source_dir, "[0-9]*")
        image_saved: List[str] = []
        image_missing: List[str] = []
        for image in images:
            got, lost, _ = _archive_one_dir(
                server, task, source_dir, ARCHIVE_NEB_IMAGE_FILES, subdir=image
            )
            image_saved += got
            image_missing += lost
        return {
            "source_dir": source_dir,
            "latest_dir": cons[-1] if cons else "",
            "saved": saved,
            "missing": missing,
            "images": images,
            "image_saved": image_saved,
            "image_missing": image_missing,
            "overwrote_draft": overwrote,
        }

    source_dir = _newest_dir_with_file(server, remote_dir, "OUTCAR") or remote_dir
    saved, missing, overwrote = _archive_one_dir(
        server, task, source_dir, ARCHIVE_OUTPUT_FILES, drafted=pending
    )
    return {
        "source_dir": source_dir,
        "latest_dir": "",
        "saved": saved,
        "missing": missing,
        "images": [],
        "image_saved": [],
        "image_missing": [],
        "overwrote_draft": overwrote,
    }


def merge_snapshot(task: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """把新快照并入任务状态：**保留草稿与变更台账**。"""
    state = dict(task.get("input_state") or {})
    previous_source = state.get("source") or {}
    state["files"] = snapshot.get("files") or {}
    state["source"] = snapshot.get("source") or {}
    # 记录"远端被外部改动"的痕迹：只更新源时保留旧来源用于对比
    if previous_source.get("remote_dir"):
        state["previous_source"] = previous_source
    state.setdefault("draft", {})
    state.setdefault("changes", [])
    return state


# ------------------------------------------------------------------- 草稿


def _drop_pending(changes: List[Dict[str, Any]], file: str, key: str) -> List[Dict[str, Any]]:
    return [
        c
        for c in changes
        if not (
            c.get("file") == file
            and (key == "" or c.get("key") == key)
            and not c.get("applied_at")
        )
    ]


#: VASP 布尔的等价写法（`.T.` ≡ `.TRUE.` ≡ `T` ≡ `1`）
_BOOL_TRUE = {"1", "t", "true", ".t.", ".true.", "yes", "on"}
_BOOL_FALSE = {"0", "f", "false", ".f.", ".false.", "no", "off"}


def _canonical(value: Any) -> str:
    """参数值的规范化形式，用于判断"到底改没改"。

    - 布尔：`.T.` 与 `.TRUE.`、`.F.` 与 `.FALSE.` 等价；
    - 数值：`1E-6` 与 `1e-6`、`-0.02` 与 `-0.020` 等价；
    - 其他（含 `0.5 0.5 0.18` 这类多值）：去首尾空白后按字符串比较。
    """
    text = str(value or "").strip()
    low = text.lower()
    if low in _BOOL_TRUE:
        return "true"
    if low in _BOOL_FALSE:
        return "false"
    try:
        return repr(float(text.replace("D", "E").replace("d", "e")))
    except (TypeError, ValueError):
        return text


def set_incar_draft(state: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """写入 INCAR 草稿；值与快照相同（或留空）表示"不改这一项"。"""
    state = dict(state or {})
    snapshot_params = ((state.get("files") or {}).get("INCAR") or {}).get("params") or {}
    draft = dict(state.get("draft") or {})
    incar_draft = dict(draft.get("INCAR") or {})
    changes = [dict(c) for c in state.get("changes") or []]
    now = now_iso()
    for key, raw in (params or {}).items():
        key = str(key).strip().upper()
        value = "" if raw is None else str(raw).strip()
        base = str(snapshot_params.get(key, ""))
        if not key or value == "" or _canonical(value) == _canonical(base):
            incar_draft.pop(key, None)
            changes = _drop_pending(changes, "INCAR", key)
            continue
        incar_draft[key] = value
        for entry in changes:
            if (
                entry.get("file") == "INCAR"
                and entry.get("key") == key
                and not entry.get("applied_at")
            ):
                entry.update({"from": base, "to": value, "at": now})
                break
        else:
            changes.append(
                {
                    "file": "INCAR",
                    "key": key,
                    "from": base,
                    "to": value,
                    "at": now,
                    "applied_at": None,
                    "applied_in": None,
                }
            )
    draft["INCAR"] = incar_draft
    state["draft"] = {k: v for k, v in draft.items() if v}
    state["changes"] = changes
    return state


def set_kpoints_draft(state: Dict[str, Any], mesh: List[int]) -> Dict[str, Any]:
    """写入 KPOINTS 草稿（只改 k 点个数这一行，符合实际使用习惯）。"""
    state = dict(state or {})
    current = ((state.get("files") or {}).get("KPOINTS") or {}).get("mesh") or []
    draft = dict(state.get("draft") or {})
    changes = [dict(c) for c in state.get("changes") or []]
    now = now_iso()
    if not mesh or list(mesh) == list(current):
        draft.pop("KPOINTS", None)
        changes = _drop_pending(changes, "KPOINTS", "")
    else:
        draft["KPOINTS"] = {"mesh": list(mesh)}
        text_from = " × ".join(str(x) for x in current) if current else "—"
        text_to = " × ".join(str(x) for x in mesh)
        for entry in changes:
            if entry.get("file") == "KPOINTS" and not entry.get("applied_at"):
                entry.update({"from": text_from, "to": text_to, "at": now})
                break
        else:
            changes.append(
                {
                    "file": "KPOINTS",
                    "key": "mesh",
                    "from": text_from,
                    "to": text_to,
                    "at": now,
                    "applied_at": None,
                    "applied_in": None,
                }
            )
    state["draft"] = {k: v for k, v in draft.items() if v}
    state["changes"] = changes
    return state


def revert_draft(state: Dict[str, Any], file: str) -> Dict[str, Any]:
    """撤销某个文件的草稿（未应用的台账条目一并删除）。"""
    state = dict(state or {})
    draft = dict(state.get("draft") or {})
    draft.pop(file, None)
    state["draft"] = draft
    state["changes"] = _drop_pending(state.get("changes") or [], file, "")
    return state


# ---------------------------------------------------------------- 续算时应用


def pending_incar_params(state: Dict[str, Any]) -> Dict[str, str]:
    """待应用的 INCAR 参数（草稿）。"""
    return dict(((state or {}).get("draft") or {}).get("INCAR") or {})


def pending_kpoints_mesh(state: Dict[str, Any]) -> Optional[List[int]]:
    """待应用的 k 网格（草稿），无则 None。"""
    mesh = (((state or {}).get("draft") or {}).get("KPOINTS") or {}).get("mesh")
    return list(mesh) if mesh else None


def has_pending(state: Dict[str, Any]) -> bool:
    return bool((state or {}).get("draft"))


def mark_applied(state: Dict[str, Any], con_name: str) -> Dict[str, Any]:
    """把当前草稿对应的台账条目标记已应用，并清空草稿。"""
    state = dict(state or {})
    draft = state.get("draft") or {}
    now = now_iso()
    changes: List[Dict[str, Any]] = []
    for entry in state.get("changes") or []:
        item = dict(entry)
        if not item.get("applied_at") and draft.get(str(item.get("file") or "")):
            item["applied_at"] = now
            item["applied_in"] = con_name
        changes.append(item)
    state["changes"] = changes
    state["draft"] = {}
    state["last_applied"] = {
        "con": con_name,
        "at": now,
        "items": [c for c in changes if c.get("applied_in") == con_name],
    }
    return state


def applied_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """当前草稿对应（尚未标记应用）的台账条目。"""
    draft = (state or {}).get("draft") or {}
    return [
        c
        for c in (state or {}).get("changes") or []
        if not c.get("applied_at") and draft.get(str(c.get("file") or ""))
    ]


def mark_file_applied(
    state: Dict[str, Any], file_name: str, where: str
) -> Tuple[Dict[str, Any], List[str]]:
    """把**单个文件**的未生效台账条目标记已应用，并清掉该文件的草稿。

    用于「同步到远端」（v0.8.7）：用户不想等下次续算时，可以把当前参数直接
    推到远端最新目录 —— 推完这些修改就不再是"待生效"，台账记 `applied_in=<where>`。

    返回 `(新 state, 被应用的 key 列表)`。
    """
    state = dict(state or {})
    draft = dict(state.get("draft") or {})
    now = now_iso()
    applied_keys: List[str] = []
    changes: List[Dict[str, Any]] = []
    for entry in state.get("changes") or []:
        item = dict(entry)
        if item.get("file") == file_name and not item.get("applied_at"):
            item["applied_at"] = now
            item["applied_in"] = where
            applied_keys.append(str(item.get("key") or ""))
        changes.append(item)
    state["changes"] = changes
    draft.pop(file_name, None)
    state["draft"] = draft
    state["last_applied"] = {
        "con": where,
        "at": now,
        "items": [c for c in changes if c.get("applied_in") == where],
    }
    return state, applied_keys
