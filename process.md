# VASP 项目管理系统 · 项目交接文档（process.md）

> 生成时间：2026-08-29 · 最近更新：2026-08-31 · 当前版本：v0.5.0（commit 见 §7，已推送 origin/main）
> 用途：本窗口上下文过长时，新窗口凭本文档 + `TODO.md` + `README.md` 直接接续开发。
> 项目位置：`D:\Skill\vasp-project-manager-web`（自包含，不依赖旧项目 `vasp-project-manager`）。
> 维护：本文档由开发助手持续维护，随每次版本提交同步更新（版本号、改动记录、待办状态）。

---

## 1. 项目概览

- VASP 第一性原理计算项目管理系统：总览 / 巡检中心 / 作业管理 / 智能报告 四大模块。
- 技术栈：React 18 + TypeScript + Vite 7 + AntD 5（前端，端口 5173）；Python + FastAPI + Paramiko（后端，端口 3001，`/docs` Swagger）。
- 存储：文件型 JSON（无数据库）：`data/projects.json` + 本地目录 + 自动备份 20 份 + 巡检归档 `data/checks/`。
- SSH：Paramiko 常驻连接池，操作真实 HPC（LSF 调度 bsub/bjobs/bkill）。

### 启动方式

```powershell
cd D:\Skill\vasp-project-manager-web
npm run server    # 后端 API，端口 3001（等价 python backend/run.py）
npm run dev       # 前端 Vite，端口 5173
```

- 数据目录可用 `python backend/run.py --data-dir <目录>` 覆盖（测试隔离用）。
- 后端无 `--reload`：**改 backend/*.py 后必须重启后端进程才生效**。
- 前端 Vite 热更新；改 `src/data/mock/incar.ts` 等默认值后需**刷新页面**（内存 workspace 不会自动重建）。
- `data/` 是运行时数据（已 gitignore），部署/换机要连同 `data/` 一起复制。

---

## 2. 数据与配置

```
data/
├── projects.json              # 项目/任务主库（dir_path、remote_dir 均为相对根目录的路径）
├── backups/                   # projects.json 自动备份（20 份）+ 迁移前备份
├── checks/                    # 巡检归档 check_results_*.json + runs.json
├── projects/                  # 本地项目镜像目录（files/ 等）
├── trash/                     # 删除任务/项目的回收站
├── aux_molecules/             # 辅助分子全局目录（opt|frac）
└── config/
    ├── servers.json           # 远程服务器配置（server1，见下）
    ├── settings.json          # 阈值/VESTA 路径等
    ├── task_registry.json     # 各任务类型 default_incar / 权重 / 续算规则（后端模板）
    ├── path_mapping.json      # local_root ↔ remote_root（根目录迁移核心）
    └── check_registry.json    # 巡检力收敛阈值（0.02 / 0.01）
```

### 远程服务器（server1）

- host `hpc.xmu.edu.cn`，user `mdye`，key 认证。
- 远程项目根：`/data/gpfs03/mdye/projects/HS`（path_mapping `remote_roots.server1`）。
- batch_check 部署路径：`/data/gpfs03/mdye/tools/vasp_skill/batch_check.py`（**每次巡检自动上传覆盖**）。
- LSF profile：`/opt/ibm/lsfsuite/lsf/conf/profile.lsf`（bsub/bjobs/bkill 前需 source）。
- VTST 脚本：`/data/gpfs03/mdye/VTST/vtstscripts/nebef.pl`（NEB 能垒分析）。
- 当前项目：Ag_20260830（三条自由能路径 PATH1-3 + NEB）、Co_260902、Co_0830 等（以 projects.json 为准）。

---

## 3. 目录与任务类型规范

- 任务类型：`opt`（结构优化）/ `frac`（频率矫正）/ `neb`（NEB）/ `ele`（电子结构，subtype：pdos/bader/diff_charge/work_function）。
- **目录一律 ASCII**：`opt/`、`ele/`、`free_energy/<组名>/<结构N>/`（opt 直接在结构目录，frac 为 `1/frac` 与 conN 同级）、`neb/<组名>/opt/IS|FS` + `neb/<组名>/neb/00..NN`（conN 续算同级）。
- 元数据路径全部为**相对项目根目录**（禁止绝对路径 / `~`），统一 `paths.resolve_local_path / resolve_remote_path` 解析。
- 续算目录 `conN`：作业提交/状态/续算源使用“最新目录”（最大编号 conN，存在即算）；巡检结果使用“最新有结果目录”（OUTCAR 有效，逐级回退到主目录）。
- 状态枚举：`pending / queued / running / completed / unconverged / zombied / archived`；**状态机无白名单，任意合法流转**。

---

## 4. 后端模块说明（backend/）

| 文件 | 功能 |
| --- | --- |
| `run.py` | 启动入口（uvicorn，无 reload） |
| `main.py` | FastAPI app 装配、路由挂载、启动时后台预热 SSH 连接 |
| `ssh.py` | **统一 SSH 连接池**：`run_remote`（exec）/ `upload_file` / `download_file` / `mkdir_remote` 共用一条常驻连接；Paramiko 传输层 keepalive 30s + 后台每 60s 应用层保活（echo ok 实测延迟写入连接池状态）、空闲 5min 回收、断线重连；`VASP_SSH_MOCK=1` 本地模拟模式。禁止业务代码自建 Paramiko 客户端 |
| `config.py` | 读取 data/config 下各 JSON（servers/settings/task_registry/path_mapping），每次现读无缓存 |
| `paths.py` | 相对路径 ↔ 绝对路径解析（local_root / remote_root） |
| `task_paths.py` | 任务目录推导、`is_continuation_task`、类型→顶层分类目录 |
| `storage.py` | 文件型 DB：原子写 + 备份 + `update_task_status`（无流转白名单） |
| `batch_check.py` | **远端巡检脚本**（自动上传部署）：定位最新输出、bjobs 状态（抗折行解析）、OUTCAR 解析（能量/力历史/收敛）、NEB 映像状态判定、nebef.pl 能垒 |
| `inspection_runner.py` | 巡检编排：筛选 → 上传脚本 → 远端批量执行 → 结果回填（job_id/current_output/状态）→ 归档；结构同步按「离子步每 25 步一桶 + 目录变化重置」触发（见 §6.2b），触发时下载 POSCAR/CONTCAR 并调 `scripts/vasp2cif.py` 生成 CIF（reports/structure/） |
| `checks_store.py` | 巡检归档合并（最新条目 + 旧 force_history 沿用）、列表行组装（has_inspection 等） |
| `continuation.py` | **续算与文件构建核心**：opt/NEB 续算（单次 base64 远程脚本 + 池化 SFTP 上传）、`create_frac_files`（opt→frac）、`build_ele_inputs`（ele 输入构建）、`create_neb_files`（IS/FS→NEB 映像 + nebmake.pl）、矫正项 vaspkit 501 |
| `incar.py` | `modify_incar` 统一 INCAR 参数修改（大小写/空格/布尔兼容、重复合并、缺失追加） |
| `cluster_status.py` | bhost/bqueues/节点分组快照 |
| `structure_analysis.py` | 结构对比（晶格/原子位移）；`vesta_render.py` 已停用（不再被调用，VESTA PNG 渲染由 3Dmol 替代） |
| `aux_molecules.py` | 辅助分子全局目录与注册表 |
| `mappers.py` / `models.py` / `priority.py` / `dates.py` / `envelope.py` / `dependencies.py` / `latest_output.py` | 映射/模型/优先级/时间/响应封装/依赖检查/最新输出辅助 |

### routers/

| 路由 | 说明 |
| --- | --- |
| `projects.py` | 项目 CRUD、新建项目（校验+优先级+目录+落库）、任务重命名/删除 |
| `groups.py` | 自由能组/NEB 组创建、加结构、默认 INCAR/KPOINTS 写入 |
| `free_energy.py` | 自由能路径汇总/详情/矫正项 |
| `jobs.py` | 作业管理：文件读写（白名单）、提交 `POST /tasks/{id}/submit`、停止 `POST /tasks/{id}/stop`（已结束按成功处理）、续算 `continuation`、create-frac、build-ele-inputs、create-neb、upload-incar/upload-kpoints（备份 old_*） |
| `inspections.py` | 巡检列表/详情/立即巡检/单任务巡检 `run-single/{task_id}` |
| `reports.py` | 报告数据（自由能台阶、NEB 能垒） |
| `ssh.py` | SSH 配置 CRUD + 状态 `GET /status` + **真实延迟测试 `POST /test`** |
| `settings.py` / `paths.py` | 根目录配置、路径迁移 rebase |
| `auxiliary.py` / `meta.py` | 辅助分子、元信息/健康检查 |

---

## 5. 前端模块说明（src/）

- `pages/`：Dashboard（总览）、Inspection（巡检中心，含筛选/详情/单任务巡检/自由能详情看板）、Jobs（作业管理，任务树 + 详情面板）、Report、SSH。
- `components/jobs/`：IncarEditor（INCAR 编辑器：分类表单 + 自定义参数框 + 生成到本地 + 上传远端）、KpointsPanel（KPOINTS 生成）、PoscarPanel、SubmitScriptPanel、ContinuationModal、NebFilesModal、EleInputModal、GroupWizardModal、NewTaskModal、TaskOverview、StructureDetail、NebGroupDetail、CopyParamsModal、JobsTree。
- `components/inspection/`：ForceHistoryCharts / LineChart（能量-力曲线，悬停竖线）、PathStepChart（自由能台阶图）、PathSummaryModal、StructurePanel（结构分析表 + Structure3DViewer）、**Structure3DViewer**（3Dmol：并排/叠加/单侧、球棍/空间填充、缩放/自动旋转/a-b-c 视角、双侧相机同步、点击原子金色高亮联动、空白取消、左下角 abc 方向图例、右下角元素配色图例）、EleAnalysisPanel、PdosModal。
- `utils/poscar.ts`：POSCAR 解析、k 网格推荐、`buildKpoints`（**纯 ASCII 输出**）。
- `utils/structure3d.ts`：3Dmol 数据工具（CIF 解析、VESTA 元素配色、共价半径算键）；3Dmol 库本地化于 `public/3dmol/3Dmol-min.js`（index.html 全局引入，无 npm 依赖）。
- `data/mock/incar.ts`：**编辑器默认参数定义**（INCAR_CATEGORIES 的 defaultValue / PRECISION_PRESETS 低中高 / TASK_TYPE_INCAR 类型覆盖 / buildDefaultParams / buildIncarText 分组空行 / parseCustomIncar）。
- `types/index.ts`：任务/状态/INCAR 类型（IncarParamDef 含 `fracOnly` 标记）。

---

## 6. 关键业务流要点

1. **SSH 连接**：统一走 `ssh.py` 连接池；每条 exec 有 ~1.3-2s 远端 shell 启动开销（HPC 负载高时 3-4s），**多步操作必须合并成单次 base64 bash 脚本**（参考 continuation `_remote_script` + `===STATE===/===FILES===` 标记分段）。
2. **巡检**：全局 `POST /api/inspections/run`、单任务 `run-single/{task_id}`（任意状态可巡检，跳过筛选）；batch_check 自动上传远端；结果归档 data/checks 并按 task_id 合并；运行中任务也回传 last_energy + force_history。
2b. **结构分析触发（analysis_needed，v0.4.6 起）**：仅 opt 任务；离子步每 25 步一桶（0-24→桶0、25-49→桶1、50-74→桶2…）。同一输出目录：桶 ≥1 且比上次触发桶更大才触发（25-49 触发后，再次巡检仍在 25-49 不触发，直到 50-74 及以后）；输出目录变化：视为新目录重置计数，重复按桶触发。触发时下载 POSCAR/CONTCAR → `scripts/vasp2cif.py` 生成 `reports/structure/{POSCAR,CONTCAR}.cif`（新结果覆盖旧 CIF），任务持久化 `last_analysis_bucket` / `last_analysis_dir`。**CIF 使用规则**：详情接口有本地 CIF 直接用；没有 CIF 但本地有 POSCAR/CONTCAR 时用脚本现场转换补缺（只补缺不覆盖）；转换先写临时文件成功后再原子替换，失败保留上一次结果。前端 Structure3DViewer 用 3Dmol 渲染（VESTA PNG 方案已移除）。
3. **续算**：`POST /jobs/tasks/{id}/continuation`。opt：最新目录 OUTCAR/CONTCAR 均非空 → 创建 con(N+1)，复制 CONTCAR→POSCAR/POTCAR/KPOINTS/INCAR/提交脚本、**WAVECAR 用 mv**，INCAR 改 ISTART=1/ICHARG=0；未完成 → 分流提示（input_complete_but_not_finished / input_incomplete）；运行中 → 提示等待。NEB：从最新续算目录复制共享文件 + 端点 POSCAR 固定并**带上 00/NN OUTCAR**、中间映像 CONTCAR→POSCAR。续算在 DB 登记隐藏子任务（不展示，供后台定位）。
4. **提交/停止**：提交 = 定位最新 con → 检查 vasp.lsf → `bsub < vasp.lsf`，成功后**立即写库 job_id**；停止 = bkill，输出 `Job has already finished` 也按成功处理（状态→pending，job_id 保留为历史）。
5. **文件构建**：`create_frac_files`（opt 最新输出 → frac，默认 ISYM=0/SIGMA=0.05/NSW=1/IBRION=5/**NFREE=2**/POTIM=0.015）；`create_neb_files`（**以 IS INCAR 为基底只改 NEB 参数**：IBRION=3/POTIM=0/IOPT=3/LCLIMB/IMAGES/ICHAIN/SPRING=-5/MAXMOVE=0.2）；`build_ele_inputs`（NSW=-1/IBRION=-1 + 各类型参数，冲突抛错）。
6. **矫正项**：frac 巡检完成后自动尝试 vaspkit 501；前端矫正项框有值也可点击重算（联动：frac 未完成先单独巡检）。
7. **NEB 能垒**：巡检对 NEB 任务跑 nebef.pl，结果 `neb_barrier.images`；端点 OUTCAR 是创建时从 IS/FS 复制的伪结果，**不作为运行证据**。

---

## 7. 近期重要改动记录（v0.4.1 → v0.5.0）

- v0.4.5（commit `02c167c`，已推送）：续算合并单脚本 + 连接池化上传/下载/建目录（opt/NEB 10-15s→3.5s）；巡检修复（作业停止感知——bjobs 折行解析、NEB 按映像 OUTCAR 判定、运行中回传 last_energy）；NEB 创建文件以 IS INCAR 为基底、续算带端点 OUTCAR；停止作业 already-finished 按成功；SSH 真实延迟测试接口；INCAR 编辑器（自定义参数/生成到本地/分类分组空行/NFREE 仅 frac/MAGMOM 留空/POTIM 0.2/KPOINTS 纯 ASCII）；默认参数同步 task_registry.json（LWAVE/LCHARG=.FALSE.、NCORE=1、POTIM=0.2）；矫正项可点击重算。
- v0.5.0（commit 见 `git log --oneline -1`，本次推送）：① **结构 3D 化**——结构分析触发条件改为「离子步每 25 步一桶 + 目录变化重置」（§6.2b）；新增 `scripts/vasp2cif.py`（经典 vasp2cif Python 3 移植，零第三方依赖）+ `backend/cif_convert.py`（原子写入：有 CIF 用 CIF、缺 CIF 现场转、失败保留旧结果）；详情接口返回 `poscar_cif/contcar_cif`（vesta_render 停用）；前端 Structure3DViewer + structure3d.ts + public/3dmol/3Dmol-min.js（backend/main.py 挂载 `/3dmol`），StructurePanel 以 3Dmol 结构视图替代 VESTA 三轴 PNG。② NEB 续算端点 OUTCAR 复制修复（find 仅匹配纯数字目录）。③ 组创建/加结构/独立任务改用服务器 remote_root 拼项目名（不再信任旧 remote_base）。④ 巡检列表 NEB 组按「项目+组名」自然排序相邻、组内 IS→FS→neb。⑤ SSH 保活延迟回传（后台 60s 保活实测延迟，`/api/ssh/status` 增 `latencyMs/latencyAt`，顶栏/SSH 页实时刷新）。⑥ 新增 DEPENDENCIES.md 依赖文档。数据侧修复（data/ 已 gitignore，不入库）：Ag_20260830.remote_base 已改回 HS 根、误建 test 下 PATH1_TS2 已删（本地移入 data/trash）、Ag PATH2/neb con6 已手动补 04/OUTCAR。
- v0.4.1：详情页分析模块 + 自由能路径看板（台阶图）+ 矫正联动 + 悬停竖线动画。
- v0.3.x：自由能 opt 单任务巡检顺带检查 frac；INCAR 统一修改 + 续算参数规格；NEB 创建流程参数。
- 更早：目录 ASCII 化、路径相对化（v0.5.0 路径规范）、根目录迁移 HS、单任务巡检、续算分流、NEB/自由能组管理。

---

## 8. 已知注意事项 / 坑

- **后端无热重载**：改 `backend/*.py`（如 continuation.py / jobs.py）必须重启后端（当前进程可能仍是旧代码）。
- **生产模式静态资源**：后端只自动挂载 `dist/assets`；新增 `public/` 下的目录（如 `3dmol`）必须在 `backend/main.py` 显式 `app.mount`，否则会被 SPA 兜底路由当成 index.html 返回（浏览器拿到 HTML 当 JS 执行，`$3Dmol` 未定义、组件静默空白）。
- **batch_check.py 例外**：每次巡检自动上传远端，改它无需重启后端；但下次巡检前远端副本可能是旧版。
- **前端默认参数生效条件**：改 `src/data/mock/incar.ts` 后要刷新页面；且任务本地已有 `files/INCAR` 时，打开任务会**自动读取文件覆盖默认值**（精度切自定义）。
- **前端默认 ≠ 后端模板**：编辑器默认在 `src/data/mock/incar.ts`，后端生成文件模板在 `data/config/task_registry.json`，两处需同步改。
- **HPC 负载**：登录节点负载高时单条 exec 3-4s（load 曾达 73），属环境问题非代码回归；避免拆分远程调用。
- **常驻 shell 方案未实现**：实测常驻 `bash --noprofile --norc -s` 每条命令 110-250ms，但并发/超时/分帧风险大，仅作后续优化方向。
- **作业号同步设计**：提交立即写库；停止/结束后 job_id 保留为历史（不被巡检清除）；续算隐藏子任务 job_id 常为 None。
- **NEB 状态判定**：错误 = bjobs 无活跃作业 + 中间映像 OUTCAR 无结束标志；只有端点 OUTCAR 视为未运行（待提交）。
- **路径安全**：远端路径统一正斜杠；禁止在元数据存绝对路径/`~`；删除任务只移本地到 trash，远端不自动删。
- **命名易混**：`Ag@Al2O3_I7`（PATH2/7）与 `Ag24@Al2O3_I7`（PATH3/7）名字接近，排查时先核对 remote_dir。

---

## 9. 待办 / 开放事项

- TODO.md 中未勾选项仍有效（报告页接入组数据图表、frac 频率输出解析等，部分已由巡检/看板覆盖，接续时先核对）。
- 电子结构分析链路：PDOS（vaspkit 111/113/115）已有弹窗入口，Bader/COHP/功函数/差分电荷为占位；PDOS 文件生成与回传待完善。
- 常驻 shell 命令网关（可选提速，需专门设计）。
- 后端“精度档”（低/中/高）机制未实现，仅前端概念。
- 提交/巡检等路径的进一步合并 exec 优化（提交已 3 次调用，可压到 1 次）。
- 自由能路径汇总表（`free_energy_path_summary`）为需求设计，当前用巡检归档实时聚合，未落独立表。

---

## 10. 新窗口接续清单

1. `git -C D:\Skill\vasp-project-manager-web log --oneline -3` 确认在 v0.4.5；工作区现状以 §7「待提交」为准（提交后更新本文档对应小节）。
2. 读 `TODO.md` + `README.md`（SSH 约定章节）+ 本文件。
3. 需要联调时：重启后端（`npm run server`）→ 启动前端（`npm run dev`）→ 打开 http://localhost:5173 与 http://localhost:3001/docs。
4. 用户对“默认参数 / 目录结构 / 作业号同步 / 巡检状态”等改动很敏感，动手前先确认范围；禁止用运行中的任务做破坏性测试（可用项目树外的临时目录，测完删除）。
5. 提交版本时沿用 commit message 前缀 `v0.x.y: ...`（无 git tag 习惯），改 package.json version 后 `git add -A && git commit && git push origin main`。
