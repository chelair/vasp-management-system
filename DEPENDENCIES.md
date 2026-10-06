# 项目依赖说明（DEPENDENCIES）

> 维护约定：本文件随依赖变化同步更新；新增任何第三方依赖（含可选/测试用）
> 必须在此登记用途、安装方式与体积/风险提示。

## 1. 总览

| 层 | 环境 | 依赖 | 何时必需 |
| --- | --- | --- | --- |
| 前端 | Node.js ≥ 20.19（生产机 22.22.1 / npm 9.2.0） | React 18 / Vite 7 / AntD 5 / Framer Motion / React Router 7（package.json） | 构建前端 `npm ci && npm run build`（150 包，约 25 s） |
| 后端核心 | Python ≥ 3.11（生产机 3.14.4，**已实测可用**） | fastapi / uvicorn / paramiko | 启动后端（生产机用仓库内 `.venv/bin/python backend/run.py`）必需 |
| 后端可选 | 同上 | pymatgen / ase / apscheduler / openai | 仅对应功能用到时才装，见 §3 |
| 系统工具（可选） | Linux 无头服务器 | **Xvfb** + Mesa 软件 GL（`libgl1-mesa-dri`） | **VESTA 结构渲染**（`backend/vesta_render.py`）需要图形环境；该渲染路径当前未被调用，接入后必需，见 §3b |

安装策略：**只装核心依赖即可运行**；可选依赖由 `backend/dependencies.py` 在启动时
后台检查缺失并提示，不影响核心功能。国内网络建议加镜像：
`.venv/bin/pip install -i https://mirrors.huaweicloud.com/repository/pypi/simple/ …`。

## 2. Python 核心依赖（必需）

| 包 | 用途 |
| --- | --- |
| fastapi | Web 框架（`/api/*`、Swagger `/docs`） |
| uvicorn[standard] | ASGI 服务器（端口 3001） |
| paramiko | SSH 连接池（远程执行 / 上传 / 下载） |

安装（几十 MB，快速；生产机 Linux）：

```bash
cd /home/zouyuxi/projects/vasp-manager
python3 -m venv .venv
.venv/bin/pip install -i https://mirrors.huaweicloud.com/repository/pypi/simple/ \
  "fastapi>=0.115" "uvicorn[standard]>=0.32" "paramiko>=3.4"   # 核心三件套
# 需要可选依赖时：# .venv/bin/pip install -r requirements.txt
```

> `uvicorn[standard]` 会带 uvloop / httptools / watchfiles / websockets；Python 3.14 下这几项
> 均有预编译轮子（实测 uvloop 0.22.1、httptools 0.8.0 安装即用）。

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

### 3b. VESTA + Xvfb（结构渲染的外部依赖 · 2026-10-06 定，**沿用此方案**）

用途：调 VESTA 命令行按晶轴渲染 POSCAR/CONTCAR 的 PNG 对比图
（`backend/vesta_render.py::render_task`）。入口约定（2026-10-06 定）：读
**`<任务目录>/files/{POSCAR,CONTCAR}`**，图写到 **与 files/ 同级**的
`<任务目录>/images/{poscar,contcar}_{a,b,c}.png`，**同名覆盖**；默认"图比结构新就复用"，
`force=True` 强制重画。**报告生成以后直接调它**（巡检详情另走浏览器端 3Dmol）。

> **2026-10-07 起**：报告里的结构三视图就走这条路 —— `backend/structure_images.py` 按
> 「opt/ele 已收敛或已归档、NEB 已完成/已归档」筛任务，巡检回填后与归档同步完成后各触发一次
> （后台队列 + `xvfb-run` 子进程，串行；NEB 走 `render_neb_images` 写到 `images/<映像号>/{a,b,c}.png`）。
> 报告生成时把 `<任务目录>/images/` 里的 PNG **base64 内联**进单文件 HTML，没有就跳过。
> 手动补课：`scripts/render_structure_images.py <项目> [--limit N] | --all`。

**依赖三件（都属系统层，非 pip 包）**：

| 依赖 | 说明 | 生产机状态 |
| --- | --- | --- |
| VESTA（外部二进制） | 路径取 `data/config/settings.json` 的 `vesta_path` | 已装：`/home/zouyuxi/APPs/VESTA-gtk3-x86_64/VESTA` |
| **Xvfb**（虚拟 X 服务器） | `sudo apt-get install -y xvfb`（约 1 MB，不装服务、不改配置） | **2026-10-06 已装**（`/usr/bin/Xvfb`、`/usr/bin/xvfb-run`） |
| Mesa 软件 GL（`libgl1-mesa-dri` / `libglx-mesa0`） | 让 Xvfb 里有可用的 OpenGL（llvmpipe） | 已随桌面环境安装（26.0.8） |

**为什么必须要 Xvfb**（2026-10-06 在 Linux 上实测）：

- VESTA 是 GTK/OpenGL **GUI** 程序：没有 `DISPLAY` 直接 `Unable to initialize GTK+`；
- 借用桌面会话的 `DISPLAY=:0` 能起 GUI、也能 `-save` 出 `.vesta`，但 **GL 画布渲染不出内容**
  → 导出报 `image.cpp: assert "IsOk()" failed in SaveFile(): invalid image`，拿不到 PNG；
- 在 **Xvfb + 软件 GL** 下稳定出图，实测约 **1.5 s/张**（a/b/c × POSCAR/CONTCAR 共 6 张约 8 s）。
- **导出倍数（"图像质量"）默认 2**：VESTA CLI 支持 `-export_img <文件> scale=N`（2026-10-06 实测：
  `scale=2` 把 1126×649 变成 2252×1298，放大到同尺寸显示时线条/球体明显更锐利）。
 代码里由 `backend/vesta_render.py::_vesta_image_scale()` 统一加参数，默认取
  `data/config/settings.json` 的 **`vesta_image_scale`（现为 2）**；改成 1 就回到与画布同尺寸。
  **改了导出倍数（或视角定义）要把 `VIEW_VERSION` +1**，否则 `<任务目录>/images/.view_version`
  对得上、旧图会被当成"还是新的"而不重画（现为 v3）。
- **收尾时机（2026-10-06 踩到，用户报"poscar_a 损坏"）**：VESTA 是**边渲染边写**，
  文件刚出现时只有几 KB。原来"文件存在且非空就 kill"会留下**打不开的截断 PNG**
  （实测 `images/poscar_a.png` 只有 4096 字节，`zlib: incomplete or truncated stream`）。
  现在 `_run_vesta_cli()` 等 **大小连续两次不变 + `_output_ready()`**（PNG 末尾要有 IEND 块）
  才收尾；`_image_is_fresh()` 也把截断的旧图判成过期 → 下次自动重画。

**调用方式**（无头环境里用 `xvfb-run` 自动起/停 Xvfb）：

```bash
cd /home/zouyuxi/projects/vasp-manager
LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe \
  xvfb-run -a -s "-screen 0 1400x1000x24" \
  .venv/bin/python -c "import sys; sys.path.insert(0,'backend'); \
    from vesta_render import render_task; print(render_task({'name':'temp','server':'server1'}, \
    {'task_id':'t','task_type':'opt','model_name':'temp','dir_path':'temp','remote_dir':'temp'}, steps=99))"
```

若以后要常驻（接入巡检/报告），二选一：① systemd 里加常驻 `Xvfb :99` + `Environment=DISPLAY=:99`；
② 后端调用 VESTA 时用 `xvfb-run` 包一层（改动更小，每次渲染多一次进程启动）。
**动 systemd 属于生产变更，实施前先确认。**

**代码侧已修的三点（2026-10-06，commit `096a129`）**：
1. 改写 `.vesta` 的 LORIENT 时**只替换前三列（旋转）**，后三列（视图中心）必须原样保留
   —— 清零会让 VESTA 直接段错误、导出无效图（Windows 上一直没暴露）；
2. `_kill_vesta()` 原来只处理 Windows → Linux 上 VESTA（启动器再 fork `sh -c → VESTA-gui`）
   收不了尾、进程越积越多；现改为 `start_new_session=True` + **按进程组** SIGTERM→SIGKILL；
2b. **关窗口要发 WM_DELETE_WINDOW，不要杀进程**（2026-10-06 实测）：VESTA 是**单实例多窗口**
   —— 后开的文件会被转进已经在跑的那个进程，杀进程会**连用户自己开的窗口一起杀掉**；
   而 `VESTA -close <文件>` 只关文档、窗口留成空白（越关越多）。现用
   `vesta_render.close_x_windows()`（纯 ctypes 调 libX11，**不新增依赖**）按窗口标题精确关闭。
3. **视角语义（2026-10-06 实测定稿）**：`.vesta` 里真正决定画面的是 `SCENE`（生效朝向 = `SCENE · LMATRIX`），
   `LMATRIX` 单独改不动画面、`LORIENT` 只是 VESTA 自己的备注（单改它会得到默认的 a*/b*/c* 那组，
   就是用户第一次说"方向不对"的那种图）。现在按用户口径改写 `SCENE` 前三行：
   **a = 沿 a 轴看、c 朝上；b = 沿 b 轴看、c 朝上；c = 沿 c 轴看、a 朝右**（写死这张 `AXIS_VIEW` 表，
   想调朝向只改它；改完把 `VIEW_VERSION` +1 会自动作废旧图）。
   另外两件事：给 VESTA 一个整体旋转过的结构**没用**（它按晶胞参数重算朝向）；
   窗口模式要用位置参数 `VESTA <文件>`，`VESTA -open <文件>` 会多弹一个空白窗口。
   （顺带修了 `_kill_vesta` 的一处竞态：**pgid 必须在启动瞬间记下**——VESTA 启动器 fork 出
   `sh -c → VESTA-gui` 后自己先退出，之后再 `os.getpgid(pid)` 会失败 → GUI 残留。）

> 体积/风险：xvfb 很小；真正的代价是**渲染耗时**（约 1.5 s/张）。缓存按 `<任务目录>/images/.view_version`
> 判断，改了视角定义（`AXIS_VIEW` / `VIEW_VERSION`）会自动作废重画，不用手动删图。

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

- 2026-10-06：登记 **VESTA 结构渲染**的外部依赖（§3b）——Linux 无头服务器需要 **Xvfb + Mesa 软件 GL**
  （生产机已装 xvfb；VESTA 二进制已存在），并记录调用方式、实测耗时与代码侧修的三点（LORIENT 视图中心、
  进程组收尾、b 视图视线方向）。该渲染路径当前未被调用，属"以后接入时按此方案准备"。
- 2026-08-31：新增本文件；登记 `scripts/vasp2cif.py` 对 pymatgen 的依赖，
  记录 Windows 旧 pip 安装失败与升级方案、拖带依赖树与体积提示。
  同日改用自包含 vasp2cif 脚本（经典实现 Python 3 移植，零第三方依赖），
  pymatgen 降级为可选（仅未来 POTCAR 生成用）。
