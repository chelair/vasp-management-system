#!/usr/bin/env python3
"""用 VASPKIT 提取态密度并汇总成一个 JSON（2026-10-13，供报告/可视化程序直接读）。

设计口径（来自 待办.md）：

- **自动识别**：是否自旋极化（看 DOSCAR 数据列 + INCAR 的 ISPIN，两者不一致会在 notes 里记下）、
  有没有投影态密度（PROCAR 是否存在 + INCAR 的 LORBIT）、有没有细轨道（dxy/dyz/dz2/dxz/dx2 是否有非零值）；
- **不依赖交互**：调 `vaspkit -task 111`（总 DOS）与 `vaspkit -task 113`（按元素符号投影的 DOS，
  列是 s / py / pz / px / dxy / dyz / dz2 / dxz / dx2 / tot，自旋时分成 _UP/_DW 两个文件）；
- **在临时目录里跑**：VASPKIT 会往当前目录写 `.dat`，这里用软链接搭一个临时工作目录，不污染原始计算目录
  （`--keep-dat` 时把 .dat 拷到 `<输入目录>/dos_extract_dats/` 留档）；
- **丢弃 EMIN 首行伪值**：部分态密度（元素/轨道）的第一行是 DOS 最低能量边界的伪值，一律丢掉
  （`--drop-first-row=auto|always|never`；总 DOS 默认只在"首行明显异常"时才丢，保证点数口径清楚）；
- 某类数据不存在时对应字段留空并记 notes，**不报错中断**。

用法：
    python3 dos_extract.py --dir <VASP 计算目录> [--out dos.json] [--vaspkit /path/to/vaspkit]
                          [--tasks 111,113] [--drop-first-row auto] [--keep-dat] [--quiet]

输出 JSON 结构：
    {
      "metadata": {source, dir, generated_at, spin_polarized, nedos, points, partial_points,
                   efermi, efermi_outcar, e_min, e_max, has_projection, has_fine_orbitals,
                   elements, energy_grid, partial_energy_grid, dropped_first_row, notes},
      "total_dos": {"up": [...], "down": [...], "total": [...]},
      "element_dos": {"Fe": {"up": [...], "down": [...], "total": [...]}, ...},
      "orbital_dos": {"Fe": {"s": {...}, "p": {...}, "d": {...}, "dxy": {...}, ...}, ...}
    }
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0"
#: 找不到 vaspkit 时的兜底路径（生产机上实测位置）
FALLBACK_VASPKIT = "/data/gpfs03/mdye/vaspkit.1.3.5/bin/vaspkit"

#: VASPKIT 投影 DOS 的列（顺序固定；`tot` 是该元素合计）
ORBITAL_COLUMNS = ["s", "py", "pz", "px", "dxy", "dyz", "dz2", "dxz", "dx2"]
#: 合成轨道：p = py+pz+px，d = 5 个 d 轨道之和
COMPOSITE = {"p": ["py", "pz", "px"], "d": ["dxy", "dyz", "dz2", "dxz", "dx2"]}


# ------------------------------------------------------------------ 输入解析


def parse_incar(path: Path) -> Dict[str, str]:
    """INCAR → `{大写键: 原始值}`（忽略注释）。"""
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].split("!", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip().upper()] = value.strip()
    return out


def read_doscar_header(path: Path) -> Dict[str, Any]:
    """DOSCAR 头 → `{nions, e_max, e_min, nedos, efermi, spin, columns}`。

    VASP 格式（第 6 行）：`E_max  E_min  NEDOS  Efermi  weight`；
    数据列数：非自旋 3 列（E / DOS / 积分），自旋极化 5 列（E / up / down / 积分up / 积分down）。
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"找不到 DOSCAR：{path}")
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        head = [next(fh, "") for _ in range(8)]
    nions = int((head[0].split() or ["0"])[0] or 0)
    parts = head[5].split()
    if len(parts) < 4:
        raise RuntimeError("DOSCAR 第 6 行格式不认识（应有 E_max / E_min / NEDOS / Efermi）")
    e_max, e_min, nedos, efermi = (float(parts[0]), float(parts[1]), int(float(parts[2])), float(parts[3]))
    first_row = head[6].split()
    spin = len(first_row) >= 5
    return {
        "nions": nions,
        "e_max": e_max,
        "e_min": e_min,
        "nedos": nedos,
        "efermi": efermi,
        "spin": spin,
        "columns": len(first_row),
    }


def read_outcar_efermi(path: Path) -> Optional[float]:
    """OUTCAR 里最后一个 `E-fermi :` 的数值（单点 DOS 只有一个；优化任务取最终那次）。"""
    if not path.is_file():
        return None
    value: Optional[float] = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "E-fermi" not in line:
                    continue
                parts = line.replace(":", " ").split()
                for index, token in enumerate(parts):
                    if token == "E-fermi" and index + 1 < len(parts):
                        try:
                            value = float(parts[index + 1])
                        except ValueError:
                            pass
                        break
    except OSError:
        return None
    return value


def read_total_dos_from_doscar(path: Path, nedos: int) -> Dict[str, List[float]]:
    """直接从 DOSCAR 的第一个数据块读总态密度（第 7 行起 NEDOS 行）。

    为什么需要它：**VASPKIT 1.3.5 的 task 111 也要求 PROCAR 存在**（实测：没有 PROCAR 时
    它直接报 "The PROCAR File NOT Exist."），而"只算总态密度"的算例本来就没有 PROCAR。
    这里按 VASP 的 DOSCAR 格式自己读，作为 VASPKIT 不可用时的回退与交叉校验。

    返回 `{"up": [...], "down": [...]}`（非自旋时只有 `up`，即那一列 DOS）。
    """
    energies: List[float] = []
    up: List[float] = []
    down: List[float] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for _ in range(6):  # 跳过 5 行头 + 第 6 行的 NEDOS/Efermi 行
            fh.readline()
        for _ in range(nedos):
            line = fh.readline()
            if not line:
                break
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                energies.append(float(parts[0]))
                up.append(float(parts[1]))
                if len(parts) >= 5:  # 自旋：E / up / down / int_up / int_down
                    down.append(float(parts[2]))
            except ValueError:
                continue
    if len(up) != nedos:
        raise RuntimeError(f"DOSCAR 总 DOS 块行数异常：期望 {nedos}，实际 {len(up)}")
    out: Dict[str, List[float]] = {
        "energies": [round(v, 6) for v in energies],
        "up": up,
    }
    if down:
        out["down"] = down
    return out


# ------------------------------------------------------------------ VASPKIT


def resolve_vaspkit(explicit: Optional[str]) -> str:
    """vaspkit 可执行文件：显式参数 → $VASPKIT_CMD → PATH → 已知路径。"""
    for candidate in (explicit, os.environ.get("VASPKIT_CMD")):
        if candidate:
            return candidate
    found = shutil.which("vaspkit")
    if found:
        return found
    if Path(FALLBACK_VASPKIT).is_file():
        return FALLBACK_VASPKIT
    raise RuntimeError("找不到 vaspkit（用 --vaspkit 指定绝对路径，或设置 VASPKIT_CMD）")


#: VASPKIT 需要的输入文件（有就软链到临时工作目录）
INPUT_FILES = ("DOSCAR", "OUTCAR", "POSCAR", "INCAR", "PROCAR", "vasprun.xml", "EIGENVAL", "KPOINTS", "POTCAR")


def make_work_dir(src_dir: Path, tmp_root: Path) -> Path:
    """临时工作目录：只软链输入文件，让 VASPKIT 把 .dat 写在这里。"""
    work = tmp_root / "vaspkit_work"
    work.mkdir(parents=True, exist_ok=True)
    for name in INPUT_FILES:
        target = src_dir / name
        if not target.exists():
            continue
        link = work / name
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(target)
        except OSError:
            shutil.copy2(target, link)
    return work


def run_vaspkit(cmd: str, work_dir: Path, task: str, timeout: int = 900) -> Dict[str, Any]:
    """跑一个 VASPKIT 任务，返回 `{ok, task, returncode, output, files}`。"""
    before = {p.name for p in work_dir.glob("*.dat")}
    env = dict(os.environ)
    env.setdefault("VASPKIT_UTILITIES_PATH", str(Path(cmd).resolve().parent))
    try:
        proc = subprocess.run(
            [cmd, "-task", str(task)],
            cwd=str(work_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
        )
        output = (proc.stdout or "")[-4000:]
        code = proc.returncode
    except subprocess.TimeoutExpired:
        return {"ok": False, "task": task, "returncode": None, "output": f"超时（>{timeout}s）", "files": []}
    except OSError as exc:
        return {"ok": False, "task": task, "returncode": None, "output": f"无法执行 vaspkit：{exc}", "files": []}
    produced = sorted({p.name for p in work_dir.glob("*.dat")} - before)
    ok = code == 0 and bool(produced)
    return {"ok": ok, "task": task, "returncode": code, "output": output, "files": produced}


# ------------------------------------------------------------------ .dat 解析


def read_dat(path: Path) -> Tuple[List[str], List[List[float]]]:
    """读 VASPKIT 的 .dat：首行 `#...` 是列名（可能带 `#Energy`），其余是数值行。"""
    names: List[str] = []
    rows: List[List[float]] = []
    for index, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            names = [token.lstrip("#").strip() for token in line.split()]
            continue
        parts = line.split()
        try:
            values = [float(token) for token in parts]
        except ValueError:
            if index == 0:  # 有的版本首行不是 # 而是列名
                names = parts
                continue
            continue
        rows.append(values)
    if not names and rows:
        names = ["#Energy"] + [f"col{i}" for i in range(1, len(rows[0]))]
    return names, rows


def first_row_is_anomalous(values: List[float], rest: List[float]) -> bool:
    """首行是不是"EMIN 伪值"：远大于后面若干行的量级（或非有限值）。"""
    if not values:
        return False
    head = max(abs(v) for v in values)
    if not math.isfinite(head):
        return True
    sample = [abs(v) for v in rest[:20] if math.isfinite(v)]
    if not sample:
        return False
    median = sorted(sample)[len(sample) // 2]
    if median <= 0:
        return head > 1.0
    return head > 20 * median


def column_series(rows: List[List[float]], index: int) -> List[float]:
    out: List[float] = []
    for row in rows:
        out.append(row[index] if index < len(row) else 0.0)
    return out


def sum_series(*series: List[float]) -> List[float]:
    if not series:
        return []
    length = min(len(item) for item in series)
    return [round(sum(item[i] for item in series), 6) for i in range(length)]


# ------------------------------------------------------------------ 主流程


def extract(
    src_dir: Path,
    out_path: Path,
    *,
    vaspkit_cmd: str,
    tasks: List[str],
    drop_first_row: str = "auto",
    keep_dat: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """跑 VASPKIT + 汇总 JSON；返回写出的 JSON 内容。"""
    notes: List[str] = []
    doscar = src_dir / "DOSCAR"
    header = read_doscar_header(doscar)
    incar = parse_incar(src_dir / "INCAR")
    efermi_outcar = read_outcar_efermi(src_dir / "OUTCAR")

    spin = bool(header["spin"])
    ispin = incar.get("ISPIN", "")
    if ispin:
        declared = str(ispin).strip() not in ("", "1", "1.0")
        if declared != spin:
            notes.append(
                f"INCAR 的 ISPIN={ispin} 与 DOSCAR 数据列（{'自旋' if spin else '非自旋'}）不一致，以 DOSCAR 为准"
            )
    else:
        notes.append("INCAR 没有 ISPIN，按 DOSCAR 数据列判断自旋")
    if efermi_outcar is not None and abs(efermi_outcar - header["efermi"]) > 1e-3:
        notes.append(
            f"OUTCAR 的 E-fermi={efermi_outcar:.4f} 与 DOSCAR 的 {header['efermi']:.4f} 不同（取 DOSCAR 的值）"
        )

    has_procar = (src_dir / "PROCAR").is_file() and (src_dir / "PROCAR").stat().st_size > 0
    lorbit = incar.get("LORBIT", "")
    has_projection_hint = bool(lorbit) and str(lorbit).strip() not in ("0",)
    if has_projection_hint and not has_procar:
        notes.append(f"INCAR 的 LORBIT={lorbit} 要求投影，但目录里没有 PROCAR → 只能给总态密度")
    if has_procar and not has_projection_hint:
        notes.append("目录里有 PROCAR（可做投影），但 INCAR 未设 LORBIT（按有投影处理）")

    tmp_root = Path(tempfile.mkdtemp(prefix="dos_extract_"))
    try:
        work = make_work_dir(src_dir, tmp_root)
        runs: Dict[str, Dict[str, Any]] = {}
        for task in tasks:
            if task == "113" and not has_procar:
                notes.append("跳过投影 DOS（task 113）：没有 PROCAR")
                continue
            result = run_vaspkit(vaspkit_cmd, work, task)
            runs[task] = result
            if not result["ok"]:
                tail = " / ".join(
                    line.strip() for line in result["output"].splitlines() if line.strip()
                )[-300:]
                notes.append(f"VASPKIT task {task} 失败（rc={result['returncode']}）：{tail or '无输出'}")

        # ---- 总 DOS ----
        total_dos: Dict[str, List[float]] = {}
        energy_grid: List[float] = []
        dropped_total = False
        total_source = ""
        crosscheck: Optional[float] = None
        crosscheck_energy: Optional[float] = None
        tdos_path = work / "TDOS.dat"
        if tdos_path.is_file():
            total_source = f"vaspkit task 111（{vaspkit_cmd}）"
            names, rows = read_dat(tdos_path)
            if rows:
                # VASPKIT 的能量轴是 **E - Efermi**（相对费米能级）；这里加回 Efermi，
                # 统一成 DOSCAR 里的绝对能量（消费者要画相对 EF 的图，减 metadata.efermi 即可）。
                energy_grid = [round(row[0] + header["efermi"], 6) for row in rows]
                up = column_series(rows, 1)
                down = column_series(rows, 2) if spin and len(rows[0]) > 2 else []
                if down:
                    # VASPKIT 把自旋向下的 DOS 镜像成**负值**；统一取绝对值（与 DOSCAR 一致）
                    down = [abs(value) for value in down]
                if drop_first_row == "always" or (
                    drop_first_row == "auto" and first_row_is_anomalous(up[:1], up[1:])
                ):
                    dropped_total = True
                    energy_grid = energy_grid[1:]
                    up = up[1:]
                    down = down[1:] if down else []
                    notes.append("总 DOS 的首行是 EMIN 伪值，已丢弃")
                if down:
                    total_dos = {"up": up, "down": down, "total": sum_series(up, down)}
                else:
                    total_dos = {"total": up}
            else:
                notes.append("TDOS.dat 里没有数据行")

        # VASPKIT 没给出总 DOS（最常见：没有 PROCAR，1.3.5 的 task 111 会直接报错）
        # → 用 DOSCAR 自己的总 DOS 块兜底；两种情况都做一次交叉校验。
        if not total_dos:
            try:
                fallback = read_total_dos_from_doscar(doscar, header["nedos"])
                energy_grid = fallback["energies"]
                up = fallback["up"]
                down = fallback.get("down") or []
                if down:
                    total_dos = {"up": up, "down": down, "total": sum_series(up, down)}
                else:
                    total_dos = {"total": up}
                total_source = "DOSCAR 总 DOS 块（VASPKIT task 111 不可用：没有 PROCAR 时它要求 PROCAR）"
                notes.append("总 DOS 直接读自 DOSCAR（VASPKIT 1.3.5 的 111 需要 PROCAR，本算例只有总 DOS）")
            except Exception as exc:  # noqa: BLE001 - 兜底失败就在 notes 里说明
                notes.append(f"总 DOS 读取失败（VASPKIT 与 DOSCAR 都不行）：{exc}")
        else:
            try:
                ref = read_total_dos_from_doscar(doscar, header["nedos"])
                diffs: List[float] = []
                for key, ref_key in (("up", "up"), ("down", "down")):
                    mine = total_dos.get(key) or []
                    theirs = ref.get(ref_key) or []
                    if mine and theirs:
                        diffs += [abs(abs(a) - abs(b)) for a, b in zip(mine, theirs)]
                if not diffs and total_dos.get("total"):
                    diffs = [
                        abs(abs(a) - abs(b))
                        for a, b in zip(total_dos["total"], ref.get("up") or [])
                    ]
                crosscheck = max(diffs) if diffs else None
                ref_energy = ref.get("energies") or []
                if energy_grid and ref_energy:
                    crosscheck_energy = max(
                        abs(a - b) for a, b in zip(energy_grid, ref_energy)
                    )
            except Exception:  # noqa: BLE001 - 交叉校验失败不影响结果
                crosscheck = None

        # ---- 元素/轨道投影 ----
        element_dos: Dict[str, Dict[str, List[float]]] = {}
        orbital_dos: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
        partial_energy: List[float] = []
        dropped_partial = False
        has_fine = False
        for path in sorted(work.glob("PDOS_*.dat")):
            stem = path.stem
            if stem.startswith("IPDOS_"):
                continue
            body = stem[len("PDOS_") :]
            if body.endswith("_UP"):
                element, spin_tag = body[: -len("_UP")], "up"
            elif body.endswith("_DW"):
                element, spin_tag = body[: -len("_DW")], "down"
            elif body.startswith("A") and body[1:].isdigit():
                # task 112 的按"第 N 种元素"命名（A1/A2…）：没有元素符号，跳过（我们用 113）
                notes.append(f"忽略按序号命名的投影文件 {path.name}（用 task 113 的元素符号版本）")
                continue
            else:
                element, spin_tag = body, "total"
            names, rows = read_dat(path)
            if not rows:
                continue
            if drop_first_row in ("auto", "always"):
                rows = rows[1:]
                dropped_partial = True
            index = {name: i for i, name in enumerate(names)}
            element_energy = [round(row[0] + header["efermi"], 6) for row in rows]
            if not partial_energy:
                partial_energy = element_energy
            bucket = orbital_dos.setdefault(element, {})
            series: Dict[str, List[float]] = {}
            for column in ORBITAL_COLUMNS:
                if column not in index:
                    continue
                values = column_series(rows, index[column])
                if spin_tag == "down":
                    values = [abs(value) for value in values]
                entry = bucket.setdefault(column, {})
                entry[spin_tag] = values
                series[column] = values
                if column in ("dxy", "dyz", "dz2", "dxz", "dx2") and any(abs(v) > 1e-6 for v in values):
                    has_fine = True
            for group, members in COMPOSITE.items():
                parts = [series[col] for col in members if col in series]
                if parts:
                    bucket.setdefault(group, {})[spin_tag] = sum_series(*parts)
            if "tot" in index:
                total_values = column_series(rows, index["tot"])
                if spin_tag == "down":
                    total_values = [abs(value) for value in total_values]
                element_dos.setdefault(element, {})[spin_tag] = total_values

        # 元素合计：用 PDOS 的 tot 列；自旋时补一条 total = up + down
        for element, values in element_dos.items():
            up = values.get("up")
            down = values.get("down")
            if up and down:
                values["total"] = sum_series(up, down)

        has_projection = bool(element_dos or orbital_dos)
        if has_procar and not has_projection:
            notes.append("有 PROCAR 但没解析出投影数据（VASPKIT 未生成 PDOS_*.dat）")

        payload: Dict[str, Any] = {
            "metadata": {
                "source": f"VASPKIT task {'+'.join(tasks)}（{Path(vaspkit_cmd).name}）",
                "dir": str(src_dir),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "spin_polarized": spin,
                "ispin_incar": ispin or None,
                "lorbit_incar": lorbit or None,
                "nedos": header["nedos"],
                "points": len(energy_grid),
                "partial_points": len(partial_energy),
                "efermi": header["efermi"],
                "efermi_outcar": efermi_outcar,
                "e_min": header["e_min"],
                "e_max": header["e_max"],
                "nions": header["nions"],
                "has_projection": has_projection,
                "has_fine_orbitals": has_fine,
                "total_dos_source": total_source or None,
                # 与 DOSCAR 自带的总 DOS 逐点比较的最大绝对差（应≈0；None = 没比成）
                "total_dos_crosscheck_maxdiff": crosscheck,
                "energy_crosscheck_maxdiff": crosscheck_energy,
                # 轴与符号约定（消费者照这个读）
                "energy_axis": "absolute（eV，与 DOSCAR 一致）；要画相对费米能级的图请减 metadata.efermi",
                "down_sign": "positive（VASPKIT 会把自旋向下镜像成负值，这里已取绝对值）",
                "elements": sorted(orbital_dos.keys()) or sorted(element_dos.keys()),
                "energy_grid": energy_grid,
                "partial_energy_grid": partial_energy,
                "dropped_first_row": {"total_dos": dropped_total, "partial_dos": dropped_partial},
                "tasks": {task: {"ok": r["ok"], "files": r["files"]} for task, r in runs.items()},
                "notes": notes,
            },
            "total_dos": total_dos,
            "element_dos": element_dos,
            "orbital_dos": orbital_dos,
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = out_path.with_name(out_path.name + ".tmp")
        tmp_out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_out, out_path)

        if keep_dat:
            dst = src_dir / "dos_extract_dats"
            dst.mkdir(parents=True, exist_ok=True)
            for dat in work.glob("*.dat"):
                shutil.copy2(dat, dst / dat.name)

        meta = payload["metadata"]
        if not quiet:
            print(
                f"[dos_extract] {src_dir} → {out_path} | "
                f"自旋={'是' if spin else '否'} 投影={'有' if has_projection else '无'} "
                f"细轨道={'有' if has_fine else '无'} | 能量点 {meta['points']}"
                f"（部分 {meta['partial_points']}）| Efermi {meta['efermi']:.4f} | "
                f"元素 {','.join(meta['elements']) or '-'}"
            )
            for note in notes:
                print(f"[dos_extract] 注意：{note}")
        # 这一行**无论 quiet 与否都打印**：调用方（系统/脚本）靠它取结果
        print(f"@@@DONE json={out_path} bytes={out_path.stat().st_size} spin={int(spin)} "
              f"points={meta['points']} projection={int(has_projection)} fine={int(has_fine)}")
        return payload
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="用 VASPKIT 提取 DOS 并汇总为 JSON")
    parser.add_argument("--dir", default=".", help="VASP 计算目录（含 DOSCAR/OUTCAR/POSCAR/INCAR）")
    parser.add_argument("--out", default="", help="输出 JSON 路径（默认 <dir>/dos.json）")
    parser.add_argument("--vaspkit", default="", help="vaspkit 可执行文件（默认自动查找）")
    parser.add_argument("--tasks", default="111,113", help="要跑的 VASPKIT 任务（默认 111,113）")
    parser.add_argument(
        "--drop-first-row",
        default="auto",
        choices=["auto", "always", "never"],
        help="部分 DOS 的 EMIN 首行：auto（默认，部分态密度一律丢、总 DOS 只在异常时丢）/ always / never",
    )
    parser.add_argument("--keep-dat", action="store_true", help="把 VASPKIT 生成的 .dat 拷到 <dir>/dos_extract_dats/")
    parser.add_argument("--quiet", action="store_true", help="只输出结果 JSON（不打印摘要）")
    parser.add_argument("--version", action="version", version=f"dos_extract {VERSION}")
    args = parser.parse_args(argv)

    src = Path(args.dir).resolve()
    if not src.is_dir():
        print(f"[dos_extract] 输入目录不存在：{src}", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else src / "dos.json"
    tasks = [t.strip() for t in str(args.tasks).split(",") if t.strip()]
    try:
        vaspkit_cmd = resolve_vaspkit(args.vaspkit or None)
    except RuntimeError as exc:
        print(f"[dos_extract] {exc}", file=sys.stderr)
        return 3
    try:
        extract(
            src,
            out,
            vaspkit_cmd=vaspkit_cmd,
            tasks=tasks,
            drop_first_row=args.drop_first_row,
            keep_dat=args.keep_dat,
            quiet=args.quiet,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 统一错误出口
        print(f"[dos_extract] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
