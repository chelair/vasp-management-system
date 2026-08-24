"""生成巡检本地模拟所需的远程文件夹具（VASP_SSH_MOCK=1 时使用）。

用法：python scripts/make_mock_fixtures.py [模拟远程根目录]
默认根目录：项目 data/mock_remote
"""

from __future__ import annotations

import sys
from pathlib import Path

REMOTE_BASE = "data/gpfs03/mdye/projects/test"

AG_DIR = f"{REMOTE_BASE}/Ag_20260830/structure_opt/Al2O3_Ag"
AG_P12_DIR = f"{REMOTE_BASE}/Ag_20260830/structure_opt/Al2O3_Ag_P1_I2"
LI_DIR = f"{REMOTE_BASE}/LiSi_20260910/structure_opt/Li15Si4_opt"
VOL_DIR = f"{REMOTE_BASE}/LiSi_20260910/free_energy/Volume_vs_energy"
TOPO_DIR = f"{REMOTE_BASE}/Topo_Surf_20260905/electronic_structure/Bi2Se3_surface_band"

AG_POSCAR = """Al2O3_Ag demo
1.0
  5.50000000 0.00000000 0.00000000
  0.00000000 5.50000000 0.00000000
  0.00000000 0.00000000 5.50000000
Al O Ag
8 12 4
Direct
  0.00000000 0.00000000 0.00000000
  0.25000000 0.25000000 0.25000000
  0.50000000 0.50000000 0.50000000
  0.75000000 0.75000000 0.75000000
  0.12500000 0.37500000 0.62500000
  0.37500000 0.12500000 0.87500000
  0.62500000 0.87500000 0.12500000
  0.87500000 0.62500000 0.37500000
  0.00000000 0.50000000 0.50000000
  0.50000000 0.00000000 0.50000000
  0.50000000 0.50000000 0.00000000
  0.11111111 0.22222222 0.33333333
  0.22222222 0.33333333 0.44444444
  0.33333333 0.44444444 0.55555555
  0.44444444 0.55555555 0.66666666
  0.55555555 0.66666666 0.77777777
  0.66666666 0.77777777 0.88888888
  0.77777777 0.88888888 0.99999999
  0.88888888 0.99999999 0.11111111
  0.99999999 0.11111111 0.22222222
  0.12345678 0.23456789 0.34567891
  0.45678912 0.56789123 0.67891234
  0.78912345 0.89123456 0.91234567
"""

LI_POSCAR = """Li15Si4_opt demo
1.0
  5.50000000 0.00000000 0.00000000
  0.00000000 5.50000000 0.00000000
  0.00000000 0.00000000 5.50000000
Li
1
Direct
  0.00000000 0.00000000 0.00000000
"""

FILES = {
    f"{AG_DIR}/OUTCAR": (
        "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE\n"
        "     GENERAL ERROR\n"
        "  For more details, please check the OUTCAR file\n"
        " free  energy   TOTEN  =       -889.16669338 eV\n"
    ),
    f"{AG_DIR}/POSCAR": AG_POSCAR,
    f"{AG_DIR}/CONTCAR": AG_POSCAR.replace("Al2O3_Ag demo", "Al2O3_Ag CONTCAR demo"),
    f"{AG_P12_DIR}/OUTCAR": (
        " free  energy   TOTEN  =       -886.42011329 eV\n"
        " General timing and accounting informations for this job:\n"
        "    Total CPU time used (sec): 1234.567\n"
    ),
    f"{LI_DIR}/POSCAR": LI_POSCAR,
    f"{LI_DIR}/CONTCAR": LI_POSCAR.replace("Li15Si4_opt demo", "Li15Si4_opt CONTCAR demo"),
    f"{LI_DIR}/OUTCAR": (
        "TOTAL-FORCE (eV/Angst)\n"
        "     x      y      z     fx     fy     fz\n"
        " 0.00000000  0.00000000  0.00000000  0.12000000  0.08000000  0.15000000\n"
        " free  energy   TOTEN  =       -128.45519320 eV\n"
        "TOTAL-FORCE (eV/Angst)\n"
        "     x      y      z     fx     fy     fz\n"
        " 0.00000000  0.00000000  0.00000000  0.00300000  0.00200000  0.00400000\n"
        " free  energy   TOTEN  =       -128.50000100 eV\n"
        " reached required accuracy - stopping structural energy minimisation\n"
    ),
    f"{VOL_DIR}/OUTCAR": (
        " free  energy   TOTEN  =       -127.98024110 eV\n"
        " General timing and accounting informations for this job:\n"
        "    Total CPU time used (sec): 2345.678\n"
    ),
    f"{TOPO_DIR}/OUTCAR": (
        " free  energy   TOTEN  =       -310.44218810 eV\n"
        " Segmentation fault\n"
        " forrtl: severe (174): SIGSEGV, segmentation fault occurred\n"
    ),
}


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/mock_remote")
    for rel_path, content in FILES.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"  {rel_path}")
    print(f"已生成 {len(FILES)} 个夹具文件 -> {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
