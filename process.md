# VASP 项目管理系统 · 项目交接文档（process.md）

> 生成时间：2026-08-29 · 最近更新：2026-09-13 · 当前版本：v0.6.7（自由能路径看板视觉/动画重做）
> 用途：本窗口上下文过长时，新窗口凭本文档 + `TODO.md` + `README.md` 直接接续开发。
> 项目位置：`D:\Skill\vasp-project-manager-web`（自包含，不依赖旧项目 `vasp-project-manager`）。
> 维护：**本文档由开发助手（Codex）负责维护**，是跨窗口交接的唯一权威说明；每次版本提交都同步更新
> 版本号、改动记录（§7）、待办状态（§9）与数据现状（§2）。发现文档与代码不一致时，以代码为准并立即回来改文档。

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
├── dashboard/
│   └── core_history.json      # 总览集群采样历史（核数/运行中任务，v0.6.0 起累积）
├── projects/                  # 本地项目镜像目录（files/ 等）
├── trash/                     # 删除任务/项目的回收站
├── aux_molecules/             # 辅助分子全局目录（opt|frac）
└── config/
    ├── servers.json           # 远程服务器配置（server1，见下）
    ├── settings.json          # 力收敛阈值、同步开关、dashboard_cache_seconds / dashboard_total_cores、
    │                          # auto_inspection_enabled / inspection_interval_hours 等
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

### 总览集群查询命令（v0.6.0，可配置）

总览页把 5 条集群命令合并进**一次 exec**（标记分段 `@@@BJOBS / @@@BLIMITS / @@@DF / @@@BHOSTS / @@@BQUEUES`），
命令可在 `servers.json`（按服务器）或 `settings.json`（全局）中覆盖，缺省用内置默认值
（见 `backend/dashboard.py DEFAULT_COMMANDS），便于适配 Slurm：

| 键 | 默认值 | 用途 |
| --- | --- | --- |
| `user_used_cores_cmd` | `bjobs -u $USER -o "jobid stat queue job_name slots exec_host" -noheader` | 当前用户作业与核数 |
| `user_total_cores_cmd` | `blimits` | 核数配额（取本用户的 SLOTS `已用/上限`） |
| `node_status_cmd` | `bhosts` | 节点状态（正常/满载/关闭/宕机） |
| `queue_status_cmd` | `bqueues` | 队列拥堵（PEND/RUN） |
| `storage_check_cmd` | `df -h {storage_path}` | 存储容量（`{storage_path}` 自动替换为 remote_base） |

核数上限优先取 `blimits`；若想由系统配置固定一个上限（例如管理员给了口头配额），
在 `settings.json` 写 `dashboard_total_cores: 200` 即可覆盖，界面会标注「系统配置手动指定」。

### 项目盘点（2026-09-13，均 server1 / HS 根下，以 projects.json 为准）

| 项目 | 任务数 | 构成 | 状态与备注 |
| --- | --- | --- | --- |
| Ag_20260830 | 127 | opt 59 / neb 47 / frac 21 | 三条自由能路径 PATH1-3（含 NEB）；completed 47 / pending 74 / queued 5 / zombied 1 |
| Co_260902 | 53 | opt 22 / neb 18 / frac 12 / ele 1 | completed 30 / pending 23 |
| TMDZYX | 34 | opt 34 | 7 个过渡金属（Zn/Al/Co/Ti/Cu/Fe/Ni）各一条 opt + con1..con4 续算子任务；completed 1 / unconverged 3 / zombied 3 / pending 27。**v0.5.0 之后新增，本项目尚未在其中任何目录做过破坏性测试** |

TMDZYX 的 dir_path/remote_dir 形如 `TMDZYX/opt/Co/con2`：续算子任务不占顶层展示，但参与提交/巡检定位。

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
| `inspection_scheduler.py` | **自动巡检调度**（v0.6.2）：后台线程每 60s 检查一次，`auto_inspection_enabled` 打开且「距上次巡检 ≥ `inspection_interval_hours`」时触发一轮全局巡检；提供 `scheduler_status()` 与 `update_schedule()`（写入 settings.json） |
| `checks_store.py` | 巡检归档合并（最新条目 + 旧 force_history 沿用）、列表行组装（has_inspection 等） |
| `dashboard.py` | **总览聚合**：单次 SSH 合并查询（bjobs/blimits/df/bhosts/bqueues）+ 解析 + 5 分钟缓存（`dashboard_cache_seconds`）+ 集群采样历史 + 运行作业↔任务映射 + 核数按项目聚合 + 风险预警 + 项目进度 + 近 7 天趋势 |
| `continuation.py` | **续算与文件构建核心**：opt/NEB 续算（单次 base64 远程脚本 + 池化 SFTP 上传 + 活跃作业保护）、`create_frac_files`（opt→frac）、`build_ele_inputs`（ele 输入构建）、`create_neb_files`（IS/FS→NEB 映像 + nebmake.pl）、矫正项 vaspkit 501 |
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
| `jobs.py` | 作业管理：文件读写（白名单）、提交 `POST /tasks/{id}/submit`（**走 db_transaction**）、停止 `POST /tasks/{id}/stop`（已结束按成功处理）、**关闭（归档）`POST /tasks/{id}/archive` / 重新打开 `/unarchive`**、续算 `continuation`、create-frac、build-ele-inputs、create-neb、upload-incar/upload-kpoints（备份 old_*） |
| `inspections.py` | 巡检列表/详情/立即巡检/单任务巡检 `run-single/{task_id}`、**自动巡检开关 `PUT /auto`**；`GET /meta` 带调度器实时状态 |
| `projects.py` | 项目列表 / 新增 / 删除、**关闭项目 `POST /{id}/close`（要求可见任务全部归档）/ 重新打开 `/reopen`** |
| `reports.py` | 报告数据（自由能台阶、NEB 能垒） |
| `dashboard.py` | 总览接口：`/api/dashboard/overview`（整页聚合）、`cores-usage`、`cluster-health`、`risk-alerts`、`trend`；`?refresh=1` 强制重新查询集群 |
| `ssh.py` | SSH 配置 CRUD + 状态 `GET /status` + **真实延迟测试 `POST /test`** |
| `settings.py` / `paths.py` | 根目录配置、路径迁移 rebase |
| `auxiliary.py` / `meta.py` | 辅助分子、元信息/健康检查 |

---

## 5. 前端模块说明（src/）

- `pages/`：Dashboard（总览，v0.6.0 重构：状态→资源→趋势→明细四层 + 快捷操作）、Inspection（巡检中心，含筛选/详情/单任务巡检/自由能详情看板）、Jobs（作业管理，任务树 + 详情面板）、Report、SSH。
  - 巡检中心**列表排序**（v0.6.6）：状态优先级 `错误(0) > 警告(1) > 待提交/未检(2) > 正常(3) > 关闭(4)`；自由能 / NEB **同一组算一个排序单元**，用组内最高优先级状态整体参与排序（组内成员恒定相邻）；整组归档的单元沉到其他任务下面；其余保持原规则（类别 → 组名自然序 → 组内结构顺序 → 任务名）。同项目下自由能组与 NEB 组可能同名（如都有 PATH1），排序单元键必须带 `task_category` 区分。
- `components/dashboard/`：RunningTasksPanel（bjobs 实时作业表，点行跳 `/jobs?task=`）、CoresUsagePanel（ECharts 圆环 + 项目着色 + 90%/100% 阈值）、ClusterHealthPanel（节点灯 / 队列拥堵 / 存储进度）、RiskAlertsPanel（未收敛+Zombie+巡检异常，点条目跳转）、TrendPanel（近 7 天核数/运行任务/提交数）、ProjectProgressPanel（四象限气泡 + 项目进度列表 + **已关闭项目折叠区**，样式为胶囊按钮 + 虚线分隔）、`useEcharts.ts`（**ECharts 按需注册**：Pie/Line/Bar/Scatter + Grid/Tooltip/Legend/Title/MarkLine + Canvas）。
- `hooks/useCountUp.ts`：统计卡片数字滚动动画。
- `api/dashboard.ts`：总览接口封装（overview / cores-usage / cluster-health / risk-alerts / trend）。
- `components/jobs/`：IncarEditor（INCAR 编辑器：分类表单 + 自定义参数框 + 生成到本地 + 上传远端）、KpointsPanel（KPOINTS 生成）、PoscarPanel、SubmitScriptPanel、ContinuationModal、NebFilesModal、EleInputModal、GroupWizardModal、NewTaskModal、TaskOverview、StructureDetail、NebGroupDetail、CopyParamsModal、JobsTree。
- `components/inspection/`：ForceHistoryCharts / LineChart（能量-力曲线，悬停竖线）、**PathSummaryModal + PathStepChart**（自由能路径看板 v0.6.7：顶部统计卡（中间体数/矫正完成度/收敛情况/最高相对能）→ 相对能台阶图 → 中间体明细列表；台阶带渐变柱体与面积、状态点、跟随鼠标的 HTML 信息卡（自由能/相对 ΔE/DFT/矫正项/收敛矫正状态）、悬停上浮 + 发光、点击台阶或行打开该结构巡检详情；入场动画为台阶从左依次滑入 + 连接线淡入 + 标签依次出现，列表行错峰上浮，`prefers-reduced-motion` 下全部关闭）、StructurePanel（结构分析表 + Structure3DViewer）、**Structure3DViewer**（3Dmol：并排/叠加/单侧、球棍/空间填充、缩放/自动旋转/a-b-c 视角、双侧相机同步、点击原子金色高亮联动、空白取消、左下角 abc 方向图例、右下角元素配色图例）、EleAnalysisPanel、PdosModal。
- `utils/poscar.ts`：POSCAR 解析、k 网格推荐、`buildKpoints`（**纯 ASCII 输出**）。
- `utils/structure3d.ts`：3Dmol 数据工具（CIF 解析、VESTA 元素配色、共价半径算键）；3Dmol 库本地化于 `public/3dmol/3Dmol-min.js`（index.html 全局引入，无 npm 依赖）。
- `data/mock/incar.ts`：**编辑器默认参数定义**（INCAR_CATEGORIES 的 defaultValue / PRECISION_PRESETS 低中高 / TASK_TYPE_INCAR 类型覆盖 / buildDefaultParams / buildIncarText 分组空行 / parseCustomIncar）。
- `types/index.ts`：任务/状态/INCAR 类型（IncarParamDef 含 `fracOnly` 标记）。

---

## 6. 关键业务流要点

1. **SSH 连接**：统一走 `ssh.py` 连接池；每条 exec 有 ~1.3-2s 远端 shell 启动开销（HPC 负载高时 3-4s），**多步操作必须合并成单次 base64 bash 脚本**（参考 continuation `_remote_script` + `===STATE===/===FILES===` 标记分段）。
2. **巡检**：全局 `POST /api/inspections/run`、单任务 `run-single/{task_id}`（任意状态可巡检，跳过筛选）；batch_check 自动上传远端；结果归档 data/checks 并按 task_id 合并；运行中任务也回传 last_energy + force_history。
2b. **结构分析触发（analysis_needed，v0.4.6 起）**：仅 opt 任务；离子步每 25 步一桶（0-24→桶0、25-49→桶1、50-74→桶2…）。同一输出目录：桶 ≥1 且比上次触发桶更大才触发（25-49 触发后，再次巡检仍在 25-49 不触发，直到 50-74 及以后）；输出目录变化：视为新目录重置计数，重复按桶触发。触发时下载 POSCAR/CONTCAR → `scripts/vasp2cif.py` 生成 `reports/structure/{POSCAR,CONTCAR}.cif`（新结果覆盖旧 CIF），任务持久化 `last_analysis_bucket` / `last_analysis_dir`。**CIF 使用规则**：详情接口有本地 CIF 直接用；没有 CIF 但本地有 POSCAR/CONTCAR 时用脚本现场转换补缺（只补缺不覆盖）；转换先写临时文件成功后再原子替换，失败保留上一次结果。前端 Structure3DViewer 用 3Dmol 渲染（VESTA PNG 方案已移除）。
3. **续算**：`POST /jobs/tasks/{id}/continuation`。opt：最新目录 OUTCAR/CONTCAR 均非空 → 创建 con(N+1)，复制 CONTCAR→POSCAR/POTCAR/KPOINTS/INCAR/提交脚本、**WAVECAR 用 mv**，INCAR 改 ISTART=1/ICHARG=0；未完成 → 分流提示（input_complete_but_not_finished / input_incomplete）；运行中 → 提示等待。NEB：从最新续算目录复制共享文件 + 端点 POSCAR 固定并**带上 00/NN OUTCAR**、中间映像 CONTCAR→POSCAR、**各映像（含端点/中间态）存在 WAVECAR 时随续算 mv 移动**（目标已有不覆盖）。续算在 DB 登记隐藏子任务（不展示，供后台定位）。
   - **活跃作业保护（v0.5.5）**：opt/NEB 续算脚本都在创建目录**之前**用 `bjobs -l`（含 `bjobs -o 'jobid exec_cwd'` 按源目录/映像子目录二次匹配）判定是否有 RUN/SSUSP/PSUSP/USUSP 作业，命中则只回传状态、返回 `action="running"`，**不建目录、不移动文件**。opt 自 v0.4.5 起如此，NEB 在 v0.5.5 补齐（此前 NEB 续算对运行中作业没有拦截）。
   - **WAVECAR 是移动语义**：续算成功后源目录不再保留 WAVECAR（opt 与 NEB 一致，目标已存在则不覆盖）。NEB 连端点 00/NN 的 WAVECAR 也一并移动，端点 POSCAR/OUTCAR 是复制。
4. **提交/停止**：提交 = 定位最新 con → 检查 vasp.lsf → `bsub < vasp.lsf`，成功后**立即写库 job_id**；停止 = bkill，输出 `Job has already finished` 也按成功处理（状态→pending，job_id 保留为历史）。
5. **文件构建**：`create_frac_files`（opt 最新输出 → frac，默认 ISYM=0/SIGMA=0.05/NSW=1/IBRION=5/**NFREE=2**/POTIM=0.015）；`create_neb_files`（**以 IS INCAR 为基底只改 NEB 参数**：IBRION=3/POTIM=0/IOPT=3/LCLIMB/IMAGES/ICHAIN/SPRING=-5/MAXMOVE=0.2）；`build_ele_inputs`（NSW=-1/IBRION=-1 + 各类型参数，冲突抛错）。
6. **矫正项**：frac 巡检完成后自动尝试 vaspkit 501；前端矫正项框有值也可点击重算（联动：frac 未完成先单独巡检）。
7. **NEB 能垒**：巡检对 NEB 任务跑 nebef.pl，结果 `neb_barrier.images`；端点 OUTCAR 是创建时从 IS/FS 复制的伪结果，**不作为运行证据**。
8. **闭环：提交 → 巡检 → 归档（v0.6.2）**：
   - **提交**：`POST /jobs/tasks/{id}/submit` 成功后写 `queued` + job_id（**已在 db_transaction 内**，不会再被巡检回填覆盖）。
   - **全局巡检分批**：`_plan_batches()` 按**项目**切批次（同一服务器可多批），脚本与阈值每个服务器每轮只上传一次；远端检查在**事务之外**执行，回填 + 归档时才进入该项目的独立 `db_transaction`，因此单项目失败不影响其他项目（摘要返回 `failed_batches`），数据库写锁只持有本地回填那一小段。
   - **自动巡检**：`inspection_scheduler` 后台线程每 60s 判定一次（开关 + 距上次巡检 ≥ 间隔，默认 2h）→ 触发全局巡检；页面开关写 `settings.json` 即刻生效。
   - **巡检后刷新集群**：全局巡检成功后（无失败批次）调用 `dashboard.invalidate_cluster_cache(servers, prewarm=True)`，作废快照缓存并后台预热，用户切到总览即是最新数据。
   - **归档 / 关闭**：任务可「关闭（归档）」→ `status=archived`（记 `archived_at` / `archived_from`，`/api/projects` 会把这两个字段一并返回，供"重新打开"显示恢复目标）；**自由能结构优化主任务归档时，连同其 `<结构目录>/frac` 频率矫正子任务一起归档**，重新打开时也成对恢复（`archived_siblings` / `reopened_siblings` 回传，前端提示连带关系；主任务归档时若 frac 未完成会弹窗警告）。项目下**可见任务全部归档**后可「关闭项目」→ `project.closed=true`，在总览、巡检中心、作业管理里统一排到最后、灰显、默认折叠。归档/关闭都不动本地与远端文件。
   - **归档任务不可巡检（v0.6.5）**：单任务巡检遇到 `archived` 任务直接返回 400「任务已关闭（归档），请先重新打开再巡检」，避免巡检回填把归档状态覆盖回 completed/zombied；全局巡检本来就跳过 archived。巡检列表中归档任务状态列显示 **「关闭」**（`CheckStatus` 新增 `archived`），信息列写「任务已关闭（归档）」，且不计入项目块头部的「未检」计数，操作列的「单独巡检」按钮置灰并提示先重新打开。

9. **总览数据流（v0.6.0）**：`GET /api/dashboard/overview` 一次返回整页（顶部统计 + 运行作业 + 核数 + 集群 + 风险 + 项目进度 + 趋势 + 最近任务）。
   - 集群部分来自**一次 exec** 的 `@@@` 分段输出（bjobs/blimits/df/bhosts/bqueues），服务端缓存 5 分钟（`settings.json: dashboard_cache_seconds`），前端每 30 分钟自动刷新一次；`?refresh=1` 强制查询（约 2-4s）。
   - 本地聚合（风险/趋势/项目进度/完成统计）缓存 60 秒：巡检归档有数百个结果文件，逐个读取约 1-2 秒。
   - **口径**：①「运行中任务」取 LSF 实时 `RUN` 作业数（不是任务表状态，任务状态要等巡检回填）；②「核数占用」优先用 `blimits` 的 SLOTS 已用/上限（按队列组），`settings.json: dashboard_total_cores` 可手动覆盖上限，两者都没有时退回 bjobs 汇总；③「项目进度」分母为**可见任务**（不含 conN 续算目录），与作业管理页口径一致；④「今日完成」= 当天巡检观察到 completed 且前一天未完成的任务；⑤「节点满载」按 RUN≥MAX 判定（LSF 常把跑满节点置为 closed）。
   - 每次成功查询把 `{ts, usedCores, runningTasks, pendingTasks} `追加到 `data/dashboard/core_history.json`（10 分钟内不重复采样，最多 4000 条），趋势图按天取峰值；**历史从 v0.6.0 上线那天开始累积**，之前不可回溯；「提交作业数」由 `data/audit_submit.log` 回溯统计，是完整历史。

---

## 7. 近期重要改动记录（v0.4.1 → v0.6.7）

> 版本号说明：v0.5.5 的代码提交是 `60e995d`（+ `292d5fc` 文档补 commit 号），其 commit message 前缀当时写作 v0.5.1，随后统一为 v0.5.5；查历史时按 commit 号找，不要按版本号找。

- v0.6.3（commit `fab6139`，已推送 origin/main）：**归档入口补齐 + 关闭项目展示细化**。① **巡检详情弹窗 footer 新增「关闭（归档）」**（已归档任务显示「重新打开」）：未正常结束的任务同样弹窗警告（写明当前状态、说明"关闭后不再参与全局巡检"），关闭后自动关闭弹窗并刷新列表；重新打开会重拉详情。② **作业管理已关闭项目默认折叠**：`JobsTree` 从 `defaultExpandAll` 改为受控 `expandedKeys`，初始集合排除已关闭项目及其子树（新建/归档/关闭后重置为该规则），用户仍可手动展开。③ **总览「已关闭项目」样式重做**：原来只有裸按钮 + 默认样式（看起来与卡片风格不一致），现在改为虚线分隔 + 胶囊按钮（圆角 999px、浅底、hover 变蓝）+ 列表项带灰色进度条与「另 N 个续算目录」说明。

- v0.6.2（commit `2c04a1e`，已推送 origin/main）：**巡检链路加固 + 任务归档/项目关闭 + 定时调度**。① `submit` 改走 `db_transaction`，消除"提交后又被巡检回填覆盖"的竞态（[jobs.py](backend/routers/jobs.py)）。② 全局巡检改为**按项目分批**：`_plan_batches()` 规划批次，脚本/阈值每服务器每轮只上传一次，远端检查在事务外、每项目独立事务回填归档——单项目失败不再整轮回滚（摘要新增 `failed_batches`），数据库写锁从 75-90s 缩到单项目回填的几秒。③ 新增 `inspection_scheduler.py`：后台线程每 60s 判定，开关 + 间隔（默认 2h）→ 自动跑全局巡检；`PUT /api/inspections/auto` 切换，`GET /inspections/meta` 返回调度器实时状态（running / last / next / error）。④ 每次全局巡检成功后 `dashboard.invalidate_cluster_cache(prewarm=True)` 静默作废并预热集群快照。⑤ **任务归档**：`POST /jobs/tasks/{id}/archive`（未强制要求 completed，前端弹窗提醒）、`/unarchive` 恢复 `archived_from`；`archived` 状态终于接入 UI（此前枚举里有、无处写入）。⑥ **项目关闭**：`POST /projects/{id}/close`（要求该项目可见任务全部归档）与 `/reopen`；`mappers` 输出 `closed/closedAt`。⑦ 前端：巡检中心表格改为**按项目分块**（项目内保持自由能/NEB 组顺序，关闭项目排最后、默认折叠、灰显）并加入自动巡检开关与调度状态；总览项目进度把已关闭项目收进「已关闭项目」折叠区并支持关闭/重新打开；作业管理任务快捷操作新增「关闭（归档）/重新打开」、已关闭项目在树中排最后且灰显（不提供新建入口）；`vite.config.ts` 支持 `VITE_API_TARGET` 覆盖后端地址（便于隔离测试）。

- v0.6.1（commit `9773b35`，已推送 origin/main）：**巡检列表未巡检行文案修正**。① 未巡检（无归档记录）的合成行，信息列由「待提交」改为 **「未检」**，detail 由「任务待提交，暂无运行输出」改为「暂无巡检记录，可点击「单独巡检」获取该任务当前状态」——原文案把「没有巡检记录」误述成任务状态，容易和任务本身的「待提交」混淆（**状态列仍是待提交/灰色，本次不改**）。② 修掉两处按钮的英文残留 `check` → **「单独巡检」**（列表未巡检行的操作按钮 + 巡检详情弹窗 footer 按钮，与 TODO/本文档既有描述一致）。③ 前端点击未巡检行的提示语同步改为「该任务暂无巡检记录，请先用「单独巡检」获取当前状态」。

- v0.6.0（commit `8b9d629`，已推送 origin/main）：**总览模块重构与扩展**。① 后端新增 `backend/dashboard.py` + `routers/dashboard.py`：单次 SSH 合并查询（bjobs/blimits/df/bhosts/bqueues，`@@@` 分段解析）、5 分钟缓存（可配）、集群采样历史 `data/dashboard/core_history.json`、作业↔任务映射（job_id 优先、作业名回退）、核数按项目聚合、风险预警（未收敛/Zombie/巡检异常）、项目进度与近 7 天趋势；新增接口 `/api/dashboard/overview|cores-usage|cluster-health|risk-alerts|trend`（`?refresh=1` 强制刷新）。② 前端重写总览页：顶部状态栏（可点击跳巡检/展开运行任务）+ 快捷操作（新建项目/触发全局巡检/刷新集群状态）+ 运行中任务表（点行跳 `/jobs?task=`）+ ECharts 核数圆环（按项目着色、90% 橙 / 100% 红闪烁）+ 集群健康（节点灯/队列拥堵/存储告警）+ 风险预警 + 项目四象限气泡 + 最近任务明细；引入 **echarts 6.1.0（按需注册，独立 vendor chunk）**、`useCountUp` 数字滚动、30 分钟自动刷新。③ 修掉 4 个原有总览问题：逾期项目显示「已完成」、进度分母含隐藏续算目录、删除按钮换行破版（网格 4 列 5 元素）、趋势图 MOCK 假数据。④ 清理死代码：`TrendChart.tsx`、`src/data/mock/projects.ts`、`fetchDashboardMeta/fetchWeeklyTrend`。⑤ 配置：`servers.json` 新增 5 个可覆盖查询命令，`settings.json` 新增 `dashboard_cache_seconds`。

- v0.5.5（commit `60e995d`，已推送 origin/main）：① **NEB 续算活跃作业保护**——NEB 续算脚本补齐与 opt 一致的 `bjobs` 检查，运行中作业只回传 `action="running"`，不建 conN、不移动 WAVECAR（此前 NEB 路径无拦截，运行中任务可能被搬走 WAVECAR）。② NEB 续算各映像（含端点 00/NN 与中间态）存在 WAVECAR 时随续算 `mv` 移动（目标已有不覆盖），与 opt 语义一致。③ `modify_incar` 清理源文本头部空行（兼容 LF/CRLF/纯空白行；续算标记切片曾带入前导换行）。④ `_script_slice` 跳过标记行后的换行，修复 `===FILES===` 解析出空字符串首项。⑤ `GET /api/health` 的 `uptime` 改为后端进程运行秒数并新增 `startedAt`（原实现返回 `time.monotonic()`，在 Windows 上是**系统开机时长**，易误判后端是否已重启）。⑥ 文档：登记 TMDZYX 项目，明确交接文档由助手维护。

- v0.4.5（commit `02c167c`，已推送）：续算合并单脚本 + 连接池化上传/下载/建目录（opt/NEB 10-15s→3.5s）；巡检修复（作业停止感知——bjobs 折行解析、NEB 按映像 OUTCAR 判定、运行中回传 last_energy）；NEB 创建文件以 IS INCAR 为基底、续算带端点 OUTCAR；停止作业 already-finished 按成功；SSH 真实延迟测试接口；INCAR 编辑器（自定义参数/生成到本地/分类分组空行/NFREE 仅 frac/MAGMOM 留空/POTIM 0.2/KPOINTS 纯 ASCII）；默认参数同步 task_registry.json（LWAVE/LCHARG=.FALSE.、NCORE=1、POTIM=0.2）；矫正项可点击重算。
- v0.5.0（commit `6d6b78a`，已推送）：① **结构 3D 化**——结构分析触发条件改为「离子步每 25 步一桶 + 目录变化重置」（§6.2b）；新增 `scripts/vasp2cif.py`（经典 vasp2cif Python 3 移植，零第三方依赖）+ `backend/cif_convert.py`（原子写入：有 CIF 用 CIF、缺 CIF 现场转、失败保留旧结果）；详情接口返回 `poscar_cif/contcar_cif`（vesta_render 停用）；前端 Structure3DViewer + structure3d.ts + public/3dmol/3Dmol-min.js（backend/main.py 挂载 `/3dmol`），StructurePanel 以 3Dmol 结构视图替代 VESTA 三轴 PNG。② NEB 续算端点 OUTCAR 复制修复（find 仅匹配纯数字目录）。③ 组创建/加结构/独立任务改用服务器 remote_root 拼项目名（不再信任旧 remote_base）。④ 巡检列表 NEB 组按「项目+组名」自然排序相邻、组内 IS→FS→neb。⑤ SSH 保活延迟回传（后台 60s 保活实测延迟，`/api/ssh/status` 增 `latencyMs/latencyAt`，顶栏/SSH 页实时刷新）。⑥ 新增 DEPENDENCIES.md 依赖文档。数据侧修复（data/ 已 gitignore，不入库）：Ag_20260830.remote_base 已改回 HS 根、误建 test 下 PATH1_TS2 已删（本地移入 data/trash）、Ag PATH2/neb con6 已手动补 04/OUTCAR。
- v0.4.1：详情页分析模块 + 自由能路径看板（台阶图）+ 矫正联动 + 悬停竖线动画。
- v0.3.x：自由能 opt 单任务巡检顺带检查 frac；INCAR 统一修改 + 续算参数规格；NEB 创建流程参数。
- 更早：目录 ASCII 化、路径相对化（v0.5.0 路径规范）、根目录迁移 HS、单任务巡检、续算分流、NEB/自由能组管理。

---

## 8. 已知注意事项 / 坑

- **后端无热重载（踩过坑，务必照做）**：改完 `backend/*.py` **必须重启后端进程**，否则页面行为还是旧逻辑。v0.6.4 就踩过：归档连带频率矫正的代码写完了，但 3001 上还是 01:30 启动的旧进程，用户在页面上归档时 frac 不会跟着归档。判断当前进程是否为最新代码看 `GET /api/health` 的 `startedAt`（v0.5.5 起）；**不要**再用 `uptime` 数值推断——v0.5.5 之前它返回的是系统开机时长。
- **总览的集群命令只在 LSF 环境验证过**：`bjobs -o "jobid stat queue job_name slots exec_host" -noheader`、`blimits` 的 SLOTS 列、`bhosts`/`bqueues` 表头都按 IBM LSF 实测解析；换 Slurm 需改 `servers.json` 的 5 个命令键并同步改 `dashboard.py` 的解析函数（`parse_jobs/parse_blimits/parse_bhosts/parse_bqueues/parse_df`）。
- **blimits 配额是“按队列组”的**：同一用户可能有多行（不同队列组各自限制），当前取各行的最大值作为上限；`usedCores` 优先用它的已用值，与 bjobs 汇总通常一致（实测 144 = 144）。
- **核数/运行中任务趋势无法回溯**：`data/dashboard/core_history.json` 从 v0.6.0 起累积，页面会显示「自 X 起累积」；只有「提交作业数」来自 audit 日志可回溯 7 天。
- **前端新增依赖 echarts 6**：只被总览页使用，按需注册在 `components/dashboard/useEcharts.ts`；`vite.config.ts` 单独拆 `echarts-vendor` chunk（581KB / gzip 198KB）。若以后其它页面要用图表，复用该 hook 而不是再引入图表库。
- **总览「未登记任务」**：如果作业在集群上跑但 `job_id` 与任务表对不上（且作业名也匹配不上），会归到「未登记任务」项目分组，不会静默丢弃。
- **归档没有硬限制**：关闭（归档）任务只要求"非已归档"，未正常结束（不是 completed）也能关，前端只弹窗提醒；`archived` 任务不参与全局巡检（`SKIPPED_STATUSES`），但单任务巡检仍可强制查它。
- **自由能主任务与 frac 成对归档**（v0.6.4）：归档 opt 会连带归档 `<结构目录>/frac`；历史数据中已存在"主任务 archived、frac 未归档"的状态，用 `python scripts/repair_frac_archive.py`（先预览，`--apply` 写入）一次性补齐，否则这些项目无法关闭。
- **关闭项目的前提**：项目下**可见任务（不含 conN 续算子任务）全部 archived**；后端返回 400 时会把还没关的任务名列出来。关闭只写 `project.closed/closed_at`，任务状态与文件都不动。
- **自动巡检默认开启**：`auto_inspection_enabled` 默认 true（与页面既有文案一致），阈值 `inspection_interval_hours` 默认 2。调度器在**后端启动时就开始判定**——如果上次巡检已超过 2 小时（或从未巡检过），启动后会立刻跑一轮全局巡检。不想让它自动跑就在巡检中心把开关关掉（写入 settings.json）。
- **全局巡检的分批粒度是"项目"**：Ag / Co / TMDZYX 各一批，实测仍是 75-90 秒（脚本上传从每批 2 次降为每服务器 1 次），但失败隔离与锁粒度都更细；摘要里的 `failed_batches` 非空时不会触发集群快照预热。
- **改完前端别忘 `npm run build`**：生产模式（后端 3001 托管 `dist/`）读的是构建产物，只改 `src/` 不重建的话页面仍是旧包（v0.6.1 就踩过：5173 dev 已是「单独巡检」，3001 仍显示旧的 `check`）；dev 5173 有 HMR，容易造成「改了却看不到」的错觉。
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

按优先级（2026-09-13 核对 TODO.md 后重排）：

1. **frac 频率输出解析**（ZPE / 自由能矫正回填组数据 `frac.zpe / correction`）：目前自由能台阶图的矫正值来自 vaspkit 501 单点调用，未解析 OUTCAR/频率结果文件。
2. **NEB 映像 POSCAR 线性插值**：`create_neb_files` 依赖 nebmake.pl，尚未内置线性插值兜底。
3. **电子结构链路**：PDOS（vaspkit 111/113/115）有弹窗入口，文件生成与回传待完善；Bader / COHP / 功函数 / 差分电荷为占位。
4. **POTCAR 生成**：后端按 POSCAR 元素拼接伪势（pymatgen）仍为占位
5. ~~后端定时巡检未真正调度~~ → v0.6.2 已用自建后台线程实现（未引入 APScheduler），见 §6.8。
6. 提交/巡检路径的进一步合并 exec 优化（提交已 3 次调用，可压到 1 次）。
7. 常驻 shell 命令网关（可选提速，需专门设计）；后端“精度档”（低/中/高）机制未实现，仅前端概念；自由能路径汇总表（`free_energy_path_summary`）未落独立表，当前用巡检归档实时聚合。
8. **总览可选增强**（v0.6.0 已交付主体，剩余为锦上添花）：队列预计等待时间估算、趋势图核数历史回溯（需要外部数据源）、集群健康按队列筛选、总览卡片自定义排序。

TODO.md 与本节冲突时以本节 + 代码实际状态为准（TODO.md 历史条目较多，部分已过时）。

---

## 10. 新窗口接续清单

1. `git -C D:\Skill\vasp-project-manager-web log --oneline -3` 确认在 v0.6.2；`git status` 应干净（有未提交改动时先看 §7 末尾是否为「待提交」事项）。
2. 读 `TODO.md` + `README.md`（SSH 约定章节）+ 本文件。
3. 需要联调时：重启后端（`npm run server`）→ 启动前端（`npm run dev`）→ 打开 http://localhost:5173 与 http://localhost:3001/docs。
4. 用户对“默认参数 / 目录结构 / 作业号同步 / 巡检状态”等改动很敏感，动手前先确认范围；禁止用运行中的任务做破坏性测试（可用项目树外的临时目录，测完删除）。
5. 提交版本时沿用 commit message 前缀 `v0.x.y: ...`（无 git tag 习惯），改 package.json version 后 `git add -A && git commit && git push origin main`。
6. 提交完成后：更新本文档 §7（新增版本条目）+ §2（数据现状）+ §9（待办），保持「版本号 / 改动记录 / 待办」三处同步。
- v0.6.4（commit `3921566`，已推送 origin/main）：**自由能主任务归档连带频率矫正**。① 后端 `task_paths.free_energy_frac_task()` 按 `<结构目录>/frac` 约定（并校验 `parent_task_id`）定位 frac 子任务；`POST /jobs/tasks/{id}/archive` 归档自由能 opt 时**连带归档 frac**，`/unarchive` 连带恢复（各回各自的 `archived_from`），响应新增 `frac_status` / `archived_siblings` / `reopened_siblings`；对"主任务已归档但 frac 未归档"的历史状态，重复调用 archive 也会把 frac 补齐（幂等修复，不再直接 409）。② `mappers` 为自由能 opt 任务输出 `frac_sibling{task_id,model_name,status}`。③ 前端（作业管理任务面板 + 巡检详情弹窗）归档确认文案按 frac 状态区分：**未完成（非 completed）时加 ⚠️ 警告**"该任务的频率矫正（xxx）当前为「未收敛」，尚未正常结束；关闭主任务会一并归档它"，成功提示与"重新打开"提示也写明连带关系。④ 新增 `scripts/repair_frac_archive.py`：一次性修复历史"主任务已归档、frac 未归档"的数据（默认 dry-run，`--apply` 才写入，写入走事务并自动备份）。
- v0.6.5（commit `1da2de6`，已推送 origin/main）：**归档状态与巡检的关系修正**。① **归档任务禁止巡检**：`inspection_runner._plan_batches()` 单任务分支遇到 `archived` 任务抛 ValueError → 接口 400「任务已关闭（归档），请先重新打开再巡检」，杜绝"单独巡检把归档状态覆盖回 completed/zombied"（此前是线上实际发生的问题）。② **巡检列表显示「关闭」**：`CheckStatus` 新增 `archived`（`CHECK_STATUS_LABELS.archived = '关闭'`，CSS 用既有 `.status-tag--archived`），归档任务在列表状态列显示"关闭"、信息列"任务已关闭（归档）"，不再按"未检/待提交"呈现，也不计入项目块头部「未检」计数（改为单独统计「关闭 N」）；状态列筛选新增"关闭"选项。③ 归档行的「单独巡检」按钮置灰（列表与详情弹窗都加，带提示），已归档任务仍可查看详情。④ `mappers` 暴露 `archived_from` / `archived_at`，前端"重新打开"弹窗能显示真实恢复目标（此前恒显示"待提交"）。⑤ **运维教训归档**：v0.6.4 的归档连带在真机上"没生效"，原因是 3001 上的后端进程还是 01:30 启动的旧代码（改后端不重启 = 页面行为不变），已在 §8 强化说明。
- v0.6.6（commit `965a8b0`，已推送 origin/main）：**巡检列表排序规则**（前端 `Inspection.tsx` 的 `filtered` 排序键）。① 状态优先级进入排序：`错误 > 警告 > 待提交（未检）> 正常 > 关闭`。② 自由能 / NEB **同组作为一个排序单元**，取组内**最高优先级状态**整体参与排序（组员恒定相邻）；整组归档的单元沉到其他任务下面（"归档任务放在其他任务下面"）。③ 原有规则保持不变，作为后续 tie-break：任务类别（结构优化→自由能→NEB→电子结构）→ 组名自然序（PATH1 < PATH2 < PATH10）→ 组内结构顺序（自由能 1..N、NEB IS→FS→neb）→ 任务名；组内被归档的成员沉到**该组末尾**（不破坏组相邻）。④ 实现中修掉两个自测发现的坑：排序单元键最初用 `项目|组名`，但同项目下自由能组与 NEB 组可能同名（Ag 都有 PATH1/2/3），导致跨类别串组、组权重算错 → 键改为 `项目|类别|组名`；"组内归档成员沉底"最初放在组键之前，会把归档成员挤到别的组后面（NEB 的 NC 组被拆开）→ 移到组键之后。
- v0.6.7（commit `bd9e7bb`，已推送 origin/main）：**自由能路径看板视觉与动画重做**（`PathSummaryModal` + `PathStepChart` 重写，样式见 global.css 的 `.fe-*`）。① 顶部新增四张统计卡：中间体数量、矫正项完成度（N/M）、结构优化收敛（N/M）、最高相对能（含对应结构）。② 台阶图纵轴改为**相对自由能**（ΔE = E − E参考，参考取第一个有数据的中间体），保留绝对能量显示在 tooltip 与列表；台阶带渐变柱体 + 向下渐变面积 + 状态点（未收敛/未矫正时琥珀色 + 圆点），缺数据显示灰色虚线"无数据"。③ 交互：悬停台阶上浮 3px + 柱体加粗发光 + 跟随鼠标的信息卡（自由能 / 相对 ΔE / DFT / 矫正项 / 状态 / "点击查看巡检详情"），点击台阶或列表行打开该结构巡检详情。④ 动画：台阶按顺序从左滑入（80ms 错峰）、连接线淡入、数值与结构标签依次出现，列表行错峰上浮；`prefers-reduced-motion` 下全部禁用。⑤ 明细表改为自绘列表（中间体 chip / DFT / 矫正项（正负着色）/ 自由能 / 相对 ΔE / 收敛·矫正徽标 / 跳转箭头），窄屏自动重排。⑥ **后端语义修复**：`/api/free-energy/{gid}/summary` 的 `converged` 改为「`completed`，或 `archived` 且 `archived_from == completed`」——否则归档后的路径会被整片渲染成"未收敛"琥珀色（与 v0.6.4/v0.6.5 的归档功能叠加后才暴露）。
