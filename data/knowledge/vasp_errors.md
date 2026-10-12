# VASP / LSF 常见错误对照表（2026-10-13 建立，人工维护）

用途：**AI 与人工共用**的错误知识源。机器可读的那份在 `data/config/check_errors.json`
（巡检自动诊断用，当前 11 类）；本文件是"特征 → 原因 → 处理"的人读版本，并补上机器库未收录的常见情况。

约定：
- 「特征」是 OUTCAR / 作业日志里能直接 grep 到的字符串；
- 「处理」写成可执行动作（改哪个文件、改什么值、之后怎么验证）；
- 处理完把案例写进 `data/knowledge/error_cases.jsonl`（见 4.1）。

---

## 一、电子步 / 数值求解类

| # | 特征（关键字符串） | 常见原因 | 处理 | 机器库 id |
|---|---|---|---|---|
| 1 | `EDDDAV: Call to ZHEGV failed` | 电子步求解失败：初始磁矩/混合参数差、结构过密、并行设置不当 | ① 降 `ALGO` 为 `Normal`；② 调 `AMIX/BMIX`（先 0.2/0.0001）或 `ALGO=All`；③ 检查 `NCORE/KPAR` 是否整除 k 点；④ 先跑 Γ 点单点验证结构 | `E_ZHEGV` |
| 2 | `LAPACK: routine ZPOTRF failed` | 同上（矩阵分解失败），常见于 `ISYM=2` + 非常规胞 + 并行 | ① `ISYM=0`；② `NCORE=1`、`KPAR=1` 重试；③ 缩小 `POTIM` / 减少 `NSW` 先跑通一步 | `E_ZPOTRF` |
| 3 | `VERY BAD NEWS! internal error in subroutine SGRCON` | 对称性识别失败（POSCAR 精度不足、原子重叠） | ① `ISYM=0` 先跑通；② 检查 POSCAR 里是否有两个原子几乎重合；③ 用 `vaspkit`/`materials project` 重新标准化晶胞 | `E_SGRCON` |
| 4 | `VERY BAD NEWS! internal error in subroutine IBZKPT` | k 点/对称性生成失败 | ① `KPOINTS` 改用 `Gamma` 或 `Monkhorst-Pack` 手写网格；② `ISYM=0`；③ 确认 `KPOINTS` 文件行数格式正确 | `E_IBZKPT` |
| 5 | `VERY BAD NEWS! internal error in subroutine INVGRP` / `PRICEL` | 对称操作求逆失败（晶胞过扁、原子坐标精度不够） | 同 3；并把 POSCAR 坐标精度提到 8 位以上 | `E_INVGRP` |
| 6 | `WARNING: DENTET` / `DENTET:` | 四面体方法缺 k 点（非致命） | 忽略；或 `ISMEAR=0` + `SIGMA=0.05` 用于 DOS 计算 | — |
| 7 | `BRMIX: very serious problems` | 电荷混合异常（金属体系常见） | ① `ISMEAR=1/2` + `SIGMA=0.1~0.2`；② `AMIX=0.1 BMIX=0.0001`；③ `ALGO=Fast` | — |
| 8 | 离子步力/能量持续振荡（无报错） | 混合或步长过大 | ① `IBRION=1` + `POTIM=0.2`；② 检查磁性 `MAGMOM` 是否合理；③ 检查 `EDIFFG` 是否过严 | — |
| 9 | 电子步达到 `NELM` 未收敛（无报错） | `NELM` 太小 / 混合参数差 | ① `NELM=120~200`；② 调 `ALGO/AMIX/BMIX`；③ 加大 `SIGMA` 先收敛再降温 | — |

## 二、结构 / 输入文件类

| # | 特征 | 常见原因 | 处理 | 机器库 id |
|---|---|---|---|---|
| 10 | `POTCAR` 缺失 / `No such file` / `TITEL` 顺序与 POSCAR 元素不符 | 元素顺序不匹配、POTCAR 拼接错 | 按 POSCAR 的元素顺序重新拼 POTCAR（`cat` 对应元素 POTCAR）；确认 `POTCAR` 与 `POSCAR` 元素顺序**完全一致** | `E_POTCAR` |
| 11 | `ERROR: the triple product of the lattice vectors is negative` | 左手晶胞（三个晶格矢量顺序反了） | 交换其中两个晶格矢量（或 `vaspkit 401` 标准化），保持右手系 | — |
| 12 | `POSCAR` 原子重叠 / 初始能量异常大（`E0` 巨大） | 插值/复制出错、原子坐标超界 | 检查 `POSCAR`（分数坐标 0–1）、用 VESTA 目视确认；重新生成插值结构 | — |
| 13 | `Selective dynamics` 丢失 / 固定原子没生效 | 生成结构时格式被破坏 | 重新生成 POSCAR（本项目用「POSCAR 页 → 选择性动力学」工具），确认 `T/T` 标志与顺序 | — |
| 14 | `ZBRENT: fatal error in bracketing` | 线性搜索失败：结构太差、`POTIM` 过大、初始步能垒异常 | ① `IBRION=2`→`1` 或 `POTIM` 减半；② 先单点（`NSW=0`）确认能量合理；③ 检查是否有原子重叠 | `E_ZBRENT` |
| 15 | `WARNING: Sub-Space-Matrix is not hermitian` | 数值噪声（一般无害） | 观察是否连续出现；频繁出现按 1/2 处理 | — |

## 三、运行时 / 系统类

| # | 特征 | 常见原因 | 处理 | 机器库 id |
|---|---|---|---|---|
| 16 | `forrtl: severe (41): insufficient virtual memory` / `allocation failed` / `Out of memory` | 内存不足（`NCORE`/核数过多、`LREAL=.FALSE.`、大体系） | ① 降总核数或 `NCORE`；② `LREAL=Auto`；③ 减少 `KPAR`；④ 申请更大内存队列 | `E_OOM` |
| 17 | `forrtl: severe (174): SIGSEGV` / `Segmentation fault` / 进程被 `Killed` | 段错误（多为内存或库问题） | ① 看同目录 `*.err`；② 降低并行度重试；③ 换队列节点重跑；④ 若稳定复现，缩小体系定位 | `E_FORRTL` / `E_SEGFAULT` |
| 18 | `PMPI_xxx` / `MPI_ABORT` / `mpirun noticed that process ... exited` | MPI 层致命错误（节点故障、内存、通信库） | ① 记录出错 rank 与节点名；② 换节点/换队列重提；③ 降核数复现；④ 检查是否有 GPU/MKL 相关环境变量冲突 | `E_MPI` |
| 19 | 作业状态 `TERMINATED BY WALLTIME` / `RUNLIMIT` / `time limit` | 超过队列硬上限（看 `bqueues` 的 `RUNLIMIT`） | ① 用续算（本项目「续算」动作）继续；② 提高队列/加长 walltime；③ 检查 `#BSUB -W` 是否超过队列上限 | — |
| 20 | `STOPCAR` 出现 / 作业在 `-wt` 后被杀 | 软结束模块（`lsf_watcher`）在 walltime 前触发 | 正常保护行为：用续算接着跑即可 | — |
| 21 | `bsub` 报 `Job not submitted` / `Queue does not exist` / `exceeds queue's hard limit` | 队列名/上限/核数不对 | 核对 `#BSUB -q/-n/-W` 与 `bqueues`/`bhosts` 实际能力；本项目提交脚本页有硬上限预校验 | — |
| 22 | `No space left on device` / 写 `WAVECAR` 失败 | 磁盘配额满 | 清理 `WAVECAR/CHGCAR` 或改 `LWAVE=.FALSE.`；检查 `lquota` | — |

## 四、NEB 专项

| # | 特征 | 常见原因 | 处理 |
|---|---|---|---|
| 23 | `Error reading POSCAR (IMAGES)` / 映像目录缺失 | 各映像 `POSCAR` 没生成齐 | 用 nebmake 重新生成 `00..NN`，确认每个目录都有 `POSCAR` |
| 24 | 端点 `00/NN` 没有 `CONTCAR` | 端点不参与弛豫（设计如此） | 用端点 `POSCAR`（= 优化后的初/末态）；本项目巡检/NEB 视图已按此处理 |
| 25 | NEB 中间映像力一直很大/不降 | 路径不合理、`SPRING`/`LCLIMB` 设置 | ① 用 `vaspkit` 重新线性插值；② `LCLIMB=.TRUE.`（爬坡）后再找鞍点；③ 检查 `IMAGES` 数量 |
| 26 | `NEB: mesh` 相关报错 / `EDDDAV` 在 NEB 中 | 同 1/2，但每个映像单独报 | 按电子步类处理；可先固定端点只优化中间体定位失败映像 |

## 五、DFT+U / 磁性 / 光学专项

| # | 特征 | 常见原因 | 处理 |
|---|---|---|---|
| 27 | `LDAU` 打开后能量跳变/不收敛 | U 值不当或 `LMAXMIX` 不足 | `LMAXMIX=4`（d）/`6`（f`）；U 先从文献值起试；配合 `ISMEAR=-5` 做静态 |
| 28 | 磁矩不收敛/翻来覆去 | 初始 `MAGMOM` 不合理 | 按元素给合理初始磁矩（Fe 3–4、Ni 2、Co 3）；必要时 `NUPDOWN` 固定总磁矩 |
| 29 | `LVHAR`/`LVTOT` 没写 `LOCPOT` | 参数未生效或 `LCHARG` 冲突 | 功函数用 `LVHAR=.TRUE.`（本项目 INCAR 页已加该参数）；确认 OUTCAR 里有 `LOCPOT` |
| 30 | 频率矫正失败 / `vaspkit 501` 取不到 `G(T)` | 没有频率计算（`IBRION=5/6`）或输出缺失 | 先跑频率任务（本项目「创建频率矫正」动作），再算 `G(T)` |

---

## 维护说明

- 新增一类：在本表加一行（特征写**能 grep 到的原文**），同时在 `data/config/check_errors.json` 里加机器条目（`id/name/patterns/advice`），巡检下一轮自动生效；
- 处理完一次真实故障：往 `data/knowledge/error_cases.jsonl` 追加一条案例（格式见该文件首行注释 / `scripts/log_error_case.py`）；
- 本文件是**知识源**，不直接驱动代码；驱动代码的是 `check_errors.json`（诊断）与 `check_registry.json`（阈值）。
