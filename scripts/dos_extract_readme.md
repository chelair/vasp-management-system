# dos_extract —— 用 VASPKIT 提取态密度并汇总为 JSON

> 2026-10-13 建立。脚本只用 **Python 3 标准库** + 服务器上的 **VASPKIT**（实测 1.3.5），
> 不需要装任何第三方 Python 包。

## 1. 做什么

在**任意 VASP 计算目录**（含 `DOSCAR`、通常还有 `OUTCAR` / `POSCAR` / `INCAR` / `PROCAR`）里：

1. 自动判断**是否自旋极化**（以 DOSCAR 的数据列为准，并与 INCAR 的 `ISPIN` 对照）、
   是否有**投影态密度**（`PROCAR` 是否存在 / `LORBIT` 设置）、是否有**细轨道**（`dxy/dyz/dz2/dxz/dx2` 非零）；
2. 调 `vaspkit -task 111`（总 DOS）和 `vaspkit -task 113`（按**元素符号**投影的 DOS）——
   VASPKIT 会往当前目录写 `.dat`，脚本用**临时目录 + 软链接**跑，不污染原始计算目录
   （`--keep-dat` 时才把 `.dat` 拷到 `<目录>/dos_extract_dats/` 留档）；
3. 把结果汇总成一个 **JSON**（默认写在计算目录下的 `dos.json`），下载到本地后用
   `json.load()` 即可读，**不再需要原始 VASP 文件**。

## 2. 用法

```bash
# 基本用法：在计算目录里跑，产出 ./dos.json
python3 dos_extract.py --dir /data/gpfs03/mdye/projects/HS/<项目>/ele/<任务>

# 指定输出与 vaspkit 路径
python3 dos_extract.py --dir <目录> --out /tmp/dos.json --vaspkit /data/gpfs03/mdye/vaspkit.1.3.5/bin/vaspkit

# 只算总态密度（不跑投影）/ 保留 VASPKIT 的 .dat
python3 dos_extract.py --dir <目录> --tasks 111 --keep-dat

# 安静模式（只输出一行结果，便于被系统调用）
python3 dos_extract.py --dir <目录> --quiet
```

成功时最后一行是机器可读的：

```
@@@DONE json=<路径> bytes=<n> spin=1 points=3000 projection=1 fine=1
```

## 3. 输出 JSON 结构

```jsonc
{
  "metadata": {
    "source": "VASPKIT task 111+113（vaspkit）",
    "dir": "...", "generated_at": "...",
    "spin_polarized": true, "ispin_incar": "2", "lorbit_incar": "11",
    "nedos": 3000, "points": 3000, "partial_points": 2999,
    "efermi": -0.91384126, "efermi_outcar": -0.9138,
    "e_min": -16.22857158, "e_max": 4.37198613, "nions": 56,
    "has_projection": true, "has_fine_orbitals": true,
    "total_dos_source": "...", "total_dos_crosscheck_maxdiff": 5e-06,
    "energy_axis": "absolute（eV，与 DOSCAR 一致）；要画相对费米能级的图请减 metadata.efermi",
    "down_sign": "positive（VASPKIT 会把自旋向下镜像成负值，这里已取绝对值）",
    "elements": ["Fe", "S"],
    "energy_grid": [ ... ],            // 总 DOS 的能量轴（0 点起）
    "partial_energy_grid": [ ... ],    // 元素/轨道数组的能量轴（若弃了 EMIN 首行则少 1 点）
    "dropped_first_row": {"total_dos": false, "partial_dos": true},
    "tasks": {"111": {"ok": true, "files": ["TDOS.dat", "ITDOS.dat"]}, "113": {...}},
    "notes": [ ... ]
  },
  "total_dos": {"up": [...], "down": [...], "total": [...]},       // 非自旋只有 total
  "element_dos": {"Fe": {"up": [...], "down": [...], "total": [...]}, ...},   // 元素合计（PDOS 的 tot 列）
  "orbital_dos": {
    "Fe": {
      "s":  {"up": [...], "down": [...]},        // 非自旋时只有 total
      "p":  {"up": [...], ...},                  // = py+pz+px（合成）
      "py": {...}, "pz": {...}, "px": {...},
      "d":  {"up": [...], ...},                  // = 5 个细 d 轨道之和（合成）
      "dxy": {...}, "dyz": {...}, "dz2": {...}, "dxz": {...}, "dx2": {...}
    }, ...
  }
}
```

要点（读的时候注意）：

- **能量轴是绝对能量**（与 DOSCAR 一致）。VASPKIT 默认把能量轴平移到费米能级（`E - Efermi`），
  脚本已经加回 `Efermi`；要画相对 EF 的图，用 `metadata.efermi` 减一下即可。
- **自旋向下已取绝对值**：VASPKIT 的 `TDOS-DOWN` / `PDOS_*_DW` 是负值（镜像画法），JSON 里统一为正。
- **部分态密度丢弃了 EMIN 首行**（DOS 最低能量边界处第一行的数值是伪值）：
  `partial_energy_grid` 与元素/轨道数组因此比总 DOS 少 1 个点；
  总 DOS 默认**不丢**（点数与 NEDOS 一致），只有首行明显异常时才丢并记在 `notes` 里。
- 某类数据没有时对应字段为空，并在 `metadata.notes` 里说明，**不会报错中断**。

## 4. 本地读 JSON

```bash
python3 dos_json_summary.py dos.json --element Fe --orbital d
```

它会打印元信息、总 DOS 的峰值/占位数、以及该元素某轨道的自旋向上/向下曲线摘要
（本机不需要 DOSCAR/OUTCAR/PROCAR）。

## 5. 自测

```bash
python3 dos_extract_test.py --cases <算例父目录>
```

逐个算例校验：JSON 是否生成、自旋判定是否与 INCAR/DOSCAR 一致、总 DOS 点数是否与 NEDOS 一致、
投影/细轨道字段是否与数据一致、Efermi 是否与 OUTCAR 一致，并随机抽点与 DOSCAR / VASPKIT 的 `.dat`
比对数值（详见脚本头部说明）。

## 6. 已知限制

- **VASPKIT 1.3.5 的 `task 111` 也要求 `PROCAR` 存在**（没有 PROCAR 时它直接报
  `The PROCAR File NOT Exist.`）。所以"只算总态密度"的算例，脚本会**直接读 DOSCAR 的总 DOS 块**兜底，
  并在 `metadata.total_dos_source` 里写明来源；有 VASPKIT 结果时会额外做一次逐点交叉校验
  （`total_dos_crosscheck_maxdiff`，实测 ~5e-06）。
- 目前只跑 111（总）与 113（元素投影，含 s/p/d 与 5 个细 d 轨道）。
  需要**按原子**投影（`PROCAR` 里逐离子）时，VASPKIT 还有别的任务号，需要时再加。
- 投影 DOS 的细轨道是否非零取决于 `LORBIT`/`ISYM`（`LORBIT=11` 且 `ISYM=0` 时通常可用），
  JSON 里用 `has_fine_orbitals` 标注。
