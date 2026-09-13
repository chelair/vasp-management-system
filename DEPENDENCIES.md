# 项目依赖说明（DEPENDENCIES）

> 维护约定：本文件随依赖变化同步更新；新增任何第三方依赖（含可选/测试用）
> 必须在此登记用途、安装方式与体积/风险提示。

## 1. 总览

| 层 | 环境 | 依赖 | 何时必需 |
| --- | --- | --- | --- |
| 前端 | Node.js ≥ 20.19（当前 24） | React 18 / Vite 7 / AntD 5 / Framer Motion / React Router 7（package.json） | 启动/构建前端 `npm run dev` / `npm run build` |
| 后端核心 | Python ≥ 3.11（当前 3.12） | fastapi / uvicorn / paramiko | 启动后端 `npm run server` 必需 |
| 后端可选 | 同上 | pymatgen / ase / apscheduler / openai | 仅对应功能用到时才装，见 §3 |

安装策略：**只装核心依赖即可运行**；可选依赖由 `backend/dependencies.py` 在启动时
后台检查缺失并提示，不影响核心功能。

## 2. Python 核心依赖（必需）

| 包 | 用途 |
| --- | --- |
| fastapi | Web 框架（`/api/*`、Swagger `/docs`） |
| uvicorn[standard] | ASGI 服务器（端口 3001） |
| paramiko | SSH 连接池（远程执行 / 上传 / 下载） |

安装（几十 MB，快速）：

```powershell
python -m pip install -r requirements.txt
```

## 3. Python 可选依赖（按功能）

| 包 | 用途 | 体积/风险 |
| --- | --- | --- |
| pymatgen | 未来 POTCAR 拼接等（`scripts/vasp2cif.py` 已改用自包含脚本，不再依赖它） | ⚠️ 最重，拉入完整科学计算栈，见 §4 |
| ase | **报告结构图渲染（计划中，2026-09-13 决定）**：读 POSCAR/CONTCAR/CIF 搭场景交给 POV-Ray 渲染，替换现在效果差的纯 Python 正交投影三视图（当前尚未接入） | 中等 |
| apscheduler | 自动巡检定时调度（当前未启用） | 小 |
| openai | 智能报告大模型接入（当前未实现） | 小 |

### 3a. POV-Ray（计划中的外部二进制，非 pip 包）

用途：与 ASE 配合做后端结构图渲染（高质量三视图 / 3D 结构图），
替换 `backend/report_charts.structure_views()` 的纯 Python 正交投影（用户 2026-09-13
反馈效果太差，**暂搁置**）。

- **不是 Python 包**：POV-Ray 是独立可执行程序，需要单独安装（Windows / Linux 各有安装包），
  或在部署时随项目分发；`ase.io.pov` 通过子进程调用它，因此要保证 `povray` 在 PATH 中或配置绝对路径。
- 体积/风险：安装包几十 MB；跨平台部署、服务器上缺少渲染环境都会让该功能静默失败，
  接入时必须做**可降级**（渲染失败就退回现有 SVG 或跳过结构图，不能阻塞报告生成）。
- 实现要点：ASE 读结构 → 生成 .pov 场景 → POV-Ray 渲染 PNG/SVG → 按 CIF 哈希缓存到本地，
  避免批量生成报告时重复渲染。

## 4. pymatgen 专项说明

用途：仅未来的 POTCAR 生成等功能需要。**`scripts/vasp2cif.py` 已改为
自包含脚本（见 §4a），不再需要 pymatgen**；不跑 pymatgen 相关功能就不要安装。
浏览器端测试页（`vasp-3dmol-test/`）的 POSCAR→CIF 转换是纯 JS 实现，
同样不依赖 pymatgen。

### 4a. vasp2cif 脚本（scripts/vasp2cif.py）

采用经典自包含实现（Peter Larsson / Torbjorn Bjorkman，Apache 2.0），
**纯标准库、无第三方依赖**，解析 POSCAR / CONTCAR / OUTCAR 直接输出 CIF：

- 单文件：`python scripts/vasp2cif.py POSCAR` → `POSCAR.cif`
- 多文件：`python scripts/vasp2cif.py POSCAR CONTCAR` → `POSCAR_etc.cif`（多数据块）
- 参数：`-o` 指定输出、`-e` 指定元素（VASP4 无 POTCAR 时）、
  `--no-findsym` 关闭对称化、`--findsym-tolerance` 设置容差
- 已做 Python 3 移植（原版为 Python 2），并去掉对 `grep`/`rm` 的
  shell 依赖，Windows / Linux 均可运行

### 安装坑（2026-08 实测）

- Windows + 旧 pip（23.2.1）直接 `pip install pymatgen` 会因
  monty → ruamel.yaml 的依赖回溯**解析失败**（ResolutionImpossible）。
- 必须先升级 pip 再装：

```powershell
python -m pip install -U pip
python -m pip install pymatgen
```

- **下载量大、耗时长**：wheel 合计 100+ MB（numpy / scipy / matplotlib /
  pandas / plotly / lxml / spglib / sympy 等），本机实测数分钟。

### 拖带依赖树

`pymatgen → pymatgen-core → monty / bibtexparser / joblib / lxml /
networkx / orjson / palettable / scipy / spglib / sympy / tabulate /
tqdm / uncertainties / matplotlib / pandas / plotly / requests /
ruamel.yaml`（以及 matplotlib/pandas/requests 各自的子依赖）。

## 5. 前端依赖

- Node.js ≥ 20.19；`npm install` 安装 package.json 依赖。
- `npm audit` 保持 0 漏洞（历史记录）。
- 3Dmol 测试页（`vasp-3dmol-test/`）：纯静态页面，`3Dmol-min.js` 已本地化
  （512 KB），双击 `index.html` 即可，无需安装任何包；仅要求浏览器支持 WebGL。

## 6. 安装命令汇总

```powershell
# 前端
npm install

# 后端核心（运行系统够用）
python -m pip install -r requirements.txt

# 仅当需要 vasp2cif / 结构转换时再装 pymatgen
python -m pip install -U pip
python -m pip install pymatgen
```

## 7. 变更记录

- 2026-08-31：新增本文件；登记 `scripts/vasp2cif.py` 对 pymatgen 的依赖，
  记录 Windows 旧 pip 安装失败与升级方案、拖带依赖树与体积提示。
  同日改用自包含 vasp2cif 脚本（经典实现 Python 3 移植，零第三方依赖），
  pymatgen 降级为可选（仅未来 POTCAR 生成用）。
