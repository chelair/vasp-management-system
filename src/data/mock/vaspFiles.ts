/**
 * VASP 输入文件预览内容（占位）。
 * 后续由后端从远程目录读取真实文件，替换 buildInputFiles 即可。
 */
export type VaspInputFileName = 'INCAR' | 'POSCAR' | 'KPOINTS' | 'POTCAR';

export function buildInputFiles(taskName: string): Record<VaspInputFileName, string> {
  return {
    INCAR: `SYSTEM  = ${taskName}
ENCUT  = 520
EDIFF  = 1E-5
EDIFFG = -0.02
IBRION = 2
ISIF   = 3
NSW    = 100
ISMEAR = 0
SIGMA  = 0.05
PREC   = Accurate
LREAL  = Auto
NCORE  = 8
LORBIT = 11
LWAVE  = .TRUE.
LCHARG = .TRUE.`,
    POSCAR: `${taskName} (演示占位数据)
1.0
    5.50000000    0.00000000    0.00000000
    0.00000000    5.50000000    0.00000000
    0.00000000    0.00000000    5.50000000
Al   O   Ag
8    12   4
Direct
  0.00000000  0.00000000  0.00000000
  0.25000000  0.25000000  0.25000000
  0.50000000  0.50000000  0.50000000
  0.75000000  0.75000000  0.75000000
  0.12500000  0.37500000  0.62500000
  0.37500000  0.12500000  0.87500000
  0.62500000  0.87500000  0.12500000
  0.87500000  0.62500000  0.37500000
  0.00000000  0.50000000  0.50000000
  0.50000000  0.00000000  0.50000000
  0.50000000  0.50000000  0.00000000`,
    KPOINTS: `Automatic mesh
0
Gamma
4 4 4
0 0 0`,
    POTCAR: `POTCAR（占位）· 演示内容

正式版本将由 pymatgen / vaspkit 根据 POSCAR 元素自动拼接：
  - 路径：/home/vasp/potpaw_PBE/{element}/POTCAR
  - 校验：PAW_PBE 版本与 ENMAX 一致性检查
  - 合并顺序与 POSCAR 中元素顺序保持一致`,
  };
}
