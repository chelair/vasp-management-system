#!/usr/bin/env python3
"""读 `dos_extract.py` 产出的 JSON 做个小结（2026-10-13）。

用途有两个：
  1. **验证"下载后本地可解析"**：本机没有 DOSCAR/OUTCAR/PROCAR，只有这个 JSON；
  2. 作为后续可视化程序的参考读法（怎么取总 DOS、某元素的 d 轨道 DOS、积分占位数）。

用法：
    python3 dos_json_summary.py dos.json [--element Fe] [--orbital d]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def trapz(xs: List[float], ys: List[float]) -> float:
    """梯形积分（用于估占位数；这里不引 numpy）。"""
    total = 0.0
    for i in range(1, min(len(xs), len(ys))):
        dx = xs[i] - xs[i - 1]
        total += 0.5 * (ys[i] + ys[i - 1]) * dx
    return total


def occupancy(
    energy: List[float], dos: List[float], efermi: float
) -> Optional[float]:
    """E ≤ Efermi 的部分做积分（判断 d 带填充是否合理）。"""
    xs = [e - efermi for e in energy[: len(dos)]]
    pairs = [(x, y) for x, y in zip(xs, dos) if x <= 0]
    if len(pairs) < 2:
        return None
    return trapz([p[0] for p in pairs], [p[1] for p in pairs])


def series_of(doc: Dict[str, Any], element: str, orbital: str) -> Dict[str, List[float]]:
    return ((doc.get("orbital_dos") or {}).get(element) or {}).get(orbital) or {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DOS JSON 小结")
    parser.add_argument("json_path")
    parser.add_argument("--element", default="", help="默认取 JSON 里的第一个元素")
    parser.add_argument("--orbital", default="d", help="s / p / d / dxy / dyz / dz2 / dxz / dx2")
    args = parser.parse_args(argv)

    doc = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    meta = doc.get("metadata") or {}
    print("=== 元信息 ===")
    print(f"  来源        : {meta.get('source')}")
    print(f"  目录        : {meta.get('dir')}")
    print(f"  自旋极化    : {meta.get('spin_polarized')}（INCAR ISPIN={meta.get('ispin_incar')}）")
    print(f"  投影/细轨道 : {meta.get('has_projection')} / {meta.get('has_fine_orbitals')}")
    print(f"  能量点      : {meta.get('points')}（部分态密度 {meta.get('partial_points')}）· NEDOS={meta.get('nedos')}")
    print(f"  E_fermi     : {meta.get('efermi')}（OUTCAR {meta.get('efermi_outcar')}）")
    print(f"  能量范围    : {meta.get('e_min')} ~ {meta.get('e_max')} eV（{meta.get('energy_axis')}）")
    print(f"  元素        : {', '.join(meta.get('elements') or []) or '—'}")
    if meta.get("notes"):
        for note in meta["notes"]:
            print(f"  注意        : {note}")

    energy = [float(v) for v in (meta.get("energy_grid") or [])]
    total = doc.get("total_dos") or {}
    print("\n=== 总态密度 ===")
    for key, label in (("up", "自旋向上"), ("down", "自旋向下"), ("total", "合计")):
        values = [float(v) for v in (total.get(key) or [])]
        if not values:
            continue
        peak = max(range(len(values)), key=lambda i: values[i])
        occ = occupancy(energy, values, float(meta.get("efermi") or 0.0))
        line = f"  {label:<8}: {len(values)} 点 · 峰值 {values[peak]:.3f} @ {energy[peak]:.3f} eV"
        if occ is not None:
            line += f" · 占位数≈{occ:.3f}"
        print(line)

    elements = meta.get("elements") or []
    element = args.element or (elements[0] if elements else "")
    orbital = args.orbital
    if element:
        bucket = series_of(doc, element, orbital)
        print(f"\n=== {element} 的 {orbital} 轨道 ===")
        if not bucket:
            print("  （该元素没有这个轨道的数据）")
        for key, label in (("up", "自旋向上"), ("down", "自旋向下"), ("total", "合计")):
            values = [float(v) for v in (bucket.get(key) or [])]
            if not values:
                continue
            partial_energy = [float(v) for v in (meta.get("partial_energy_grid") or [])] or energy[: len(values)]
            peak = max(range(len(values)), key=lambda i: values[i])
            occ = occupancy(partial_energy, values, float(meta.get("efermi") or 0.0))
            print(
                f"  {label:<8}: {len(values)} 点 · 峰值 {values[peak]:.3f} @ {partial_energy[peak]:.3f} eV"
                + (f" · 占位数≈{occ:.3f}" if occ is not None else "")
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
