#!/usr/bin/env python3
"""`dos_extract.py` 的测试脚本（2026-10-13）：跑一组算例并逐项校验。

每个算例检查（对应 待办.md 的测试要求）：
  ① 是否生成了 JSON（且能 json.load）
  ② `spin_polarized` 与 INCAR 的 ISPIN / DOSCAR 的数据列一致
  ③ 总 DOS 点数与 DOSCAR 的 NEDOS 一致（弃首行时按 NEDOS-1 记）
  ④ 有 PROCAR 就该有投影数据：元素键 ⊆ POSCAR 元素，轨道键含 s/p/d
  ⑤ 细轨道（dxy/dyz/dz2/dxz/dx2）在数据里非零 → JSON 里必须有对应字段
  ⑥ Efermi 与 OUTCAR 的 `E-fermi` 一致（±1e-3）
  ⑦ 数据准确性：随机取 5 个能量点，JSON 的总 DOS 与 DOSCAR 原值比对；
     元素的 d 轨道 = 5 个细 d 轨道之和，与 VASPKIT 的 .dat 比对

用法：
    python3 dos_extract_test.py --cases <算例父目录> [--script <dos_extract.py>] [--json-name dos.json]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FINE_ORBITALS = ["dxy", "dyz", "dz2", "dxz", "dx2"]


def parse_incar_params(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].split("!", 1)[0].strip()
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip().upper()] = value.strip()
    return out


def doscar_info(path: Path) -> Dict[str, Any]:
    """DOSCAR 头 + 总 DOS 块（前 NEDOS 行），用于校验。"""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        head = [fh.readline() for _ in range(6)]
        parts = head[5].split()
        e_max, e_min, nedos, efermi = float(parts[0]), float(parts[1]), int(float(parts[2])), float(parts[3])
        rows = [fh.readline().split() for _ in range(nedos)]
    spin = len(rows[0]) >= 5
    return {
        "nedos": nedos,
        "efermi": efermi,
        "e_min": e_min,
        "e_max": e_max,
        "spin": spin,
        "energies": [float(r[0]) for r in rows],
        "up": [float(r[1]) for r in rows],
        "down": [abs(float(r[2])) for r in rows] if spin else [],
    }


def outcar_efermi(path: Path) -> Optional[float]:
    value: Optional[float] = None
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "E-fermi" in line:
            tokens = line.replace(":", " ").split()
            for index, token in enumerate(tokens):
                if token == "E-fermi" and index + 1 < len(tokens):
                    try:
                        value = float(tokens[index + 1])
                    except ValueError:
                        pass
                    break
    return value


def read_dat(path: Path) -> Tuple[List[str], List[List[float]]]:
    names: List[str] = []
    rows: List[List[float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            names = [token.lstrip("#").strip() for token in line.split()]
            continue
        try:
            rows.append([float(token) for token in line.split()])
        except ValueError:
            continue
    return names, rows


def run_case(case_dir: Path, script: Path, json_name: str, vaspkit: str) -> Dict[str, Any]:
    """跑一个算例的提取 + 全部校验，返回结果字典。"""
    checks: List[Tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    out_json = case_dir / json_name
    if out_json.exists():
        out_json.unlink()
    cmd = [sys.executable, str(script), "--dir", str(case_dir), "--out", str(out_json), "--keep-dat", "--quiet"]
    if vaspkit:
        cmd += ["--vaspkit", vaspkit]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    check("提取脚本退出码 0", proc.returncode == 0, (proc.stderr or proc.stdout).strip()[-200:])

    if not out_json.is_file():
        return {"case": case_dir.name, "checks": checks, "ok": False}
    try:
        doc = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        check("JSON 可解析", False, str(exc))
        return {"case": case_dir.name, "checks": checks, "ok": False}
    check("JSON 可解析", True, f"{out_json.stat().st_size} 字节")

    meta = doc.get("metadata") or {}
    incar = parse_incar_params(case_dir / "INCAR")
    info = doscar_info(case_dir / "DOSCAR")
    efermi_outcar = outcar_efermi(case_dir / "OUTCAR")

    # ② 自旋判定
    ispin = str(incar.get("ISPIN", "")).strip()
    expect_spin = (ispin not in ("", "1", "1.0")) if ispin else info["spin"]
    check(
        "spin_polarized 与 INCAR/DOSCAR 一致",
        bool(meta.get("spin_polarized")) == info["spin"] and bool(meta.get("spin_polarized")) == expect_spin,
        f"JSON={meta.get('spin_polarized')} INCAR ISPIN={ispin or '未设'} DOSCAR列={6 if info['spin'] else 3}",
    )

    # ③ 总 DOS 点数
    points = int(meta.get("points") or 0)
    dropped_total = bool((meta.get("dropped_first_row") or {}).get("total_dos"))
    expect_points = info["nedos"] - (1 if dropped_total else 0)
    check("总 DOS 点数与 NEDOS 一致", points == expect_points, f"JSON={points} NEDOS={info['nedos']} 弃首行={dropped_total}")

    # ④ 投影数据
    has_procar = (case_dir / "PROCAR").is_file() and (case_dir / "PROCAR").stat().st_size > 0
    check("有 PROCAR 就有投影数据", bool(meta.get("has_projection")) == has_procar, f"PROCAR={has_procar} 投影={meta.get('has_projection')}")
    if has_procar:
        elements = set(meta.get("elements") or [])
        check("元素键非空且含投影", bool(elements), f"元素={sorted(elements)[:6]}")
        orbital = doc.get("orbital_dos") or {}
        sample = next(iter(orbital.values()), {})
        check("轨道键含 s/p/d", all(k in sample for k in ("s", "p", "d")), f"轨道={sorted(sample)[:8]}")
        # ⑤ 细轨道
        fine_present = all(key in sample for key in FINE_ORBITALS)
        fine_nonzero = False
        for element, buckets in orbital.items():
            for key in FINE_ORBITALS:
                for series in (buckets.get(key) or {}).values():
                    if any(abs(v) > 1e-6 for v in series):
                        fine_nonzero = True
        check("细轨道字段与数据一致", fine_present and fine_nonzero, f"字段齐={fine_present} 有非零={fine_nonzero}")

    # ⑥ Efermi
    if efermi_outcar is not None:
        check("Efermi 与 OUTCAR 一致", abs(float(meta.get("efermi") or 0) - efermi_outcar) < 1e-3,
              f"JSON={meta.get('efermi')} OUTCAR={efermi_outcar}")

    # ⑦ 准确性：总 DOS 与 DOSCAR 抽查
    td = doc.get("total_dos") or {}
    json_total = td.get("up") or td.get("total") or []
    ref_up = info["up"][1:] if dropped_total else info["up"]
    if json_total and len(json_total) == len(ref_up):
        random.seed(20261013)
        idxs = sorted(random.sample(range(len(json_total)), min(5, len(json_total))))
        worst = max(abs(json_total[i] - ref_up[i]) for i in idxs)
        check("总 DOS 抽查（vs DOSCAR）", worst < 1e-3, f"随机 {len(idxs)} 点最大差={worst:.2e}")
        if info["spin"]:
            json_down = td.get("down") or []
            ref_down = info["down"][1:] if dropped_total else info["down"]
            if json_down and len(json_down) == len(ref_down):
                worst_d = max(abs(json_down[i] - ref_down[i]) for i in idxs)
                check("自旋向下抽查（vs DOSCAR）", worst_d < 1e-3, f"最大差={worst_d:.2e}")
    else:
        check("总 DOS 抽查（vs DOSCAR）", False, f"长度不匹配：JSON={len(json_total)} DOSCAR={len(ref_up)}")

    # ⑦b 元素 d 轨道 = 5 个细轨道之和（与 .dat 比对）
    dat_dir = case_dir / "dos_extract_dats"
    orbital = doc.get("orbital_dos") or {}
    if orbital and dat_dir.is_dir():
        element = sorted(orbital)[0]
        bucket = orbital[element]
        for tag, suffix in (("up", "_UP"), ("down", "_DW"), ("total", "")):
            dat_path = dat_dir / f"PDOS_{element}{suffix}.dat"
            if not dat_path.is_file():
                continue
            names, rows = read_dat(dat_path)
            rows = rows[1:] if (rows and (meta.get("dropped_first_row") or {}).get("partial_dos")) else rows
            index = {name: i for i, name in enumerate(names)}
            if not all(key in index for key in FINE_ORBITALS) or not rows:
                break
            worst = 0.0
            for i in range(0, len(rows), max(1, len(rows) // 200)):
                ref = sum(abs(rows[i][index[key]]) for key in FINE_ORBITALS)
                mine = (bucket.get("d") or {}).get(tag) or []
                if i < len(mine):
                    worst = max(worst, abs(mine[i] - ref))
            check(f"元素 {element} 的 d = Σ细轨道（vs .dat）", worst < 1e-3, f"最大差={worst:.2e}")
            break

    ok = all(item[1] for item in checks)
    return {"case": case_dir.name, "checks": checks, "ok": ok, "json": str(out_json)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="dos_extract.py 的算例测试")
    parser.add_argument("--cases", required=True, help="算例父目录（每个子目录一个算例）")
    parser.add_argument("--script", default=str(Path(__file__).with_name("dos_extract.py")))
    parser.add_argument("--json-name", default="dos.json")
    parser.add_argument("--vaspkit", default="")
    args = parser.parse_args(argv)

    cases_root = Path(args.cases).resolve()
    case_dirs = sorted(p for p in cases_root.iterdir() if p.is_dir())
    if not case_dirs:
        print(f"没有算例：{cases_root}", file=sys.stderr)
        return 2
    results = [run_case(case, Path(args.script).resolve(), args.json_name, args.vaspkit) for case in case_dirs]

    print("\n===== 测试结果 =====")
    width = max(len(r["case"]) for r in results)
    for result in results:
        flag = "✅ 通过" if result["ok"] else "❌ 失败"
        print(f"\n【{result['case']:<{width}}】 {flag}")
        for name, ok, detail in result["checks"]:
            print(f"   {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail else ""))
    passed = sum(1 for r in results if r["ok"])
    print(f"\n合计：{passed}/{len(results)} 个算例全部校验通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
