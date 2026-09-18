# VASP 项目管理系统 · 项目交接文档（process.md）

> 生成时间：2026-08-29 · 最近更新：2026-09-18 · 当前版本：v0.8.6（同名自由能组 / NEB 组路径列误合并修复 + `/api/jobs/nodes` 回归修复 + HPC 连接快捷脚本）
> 用途：本窗口上下文过长时，新窗口凭本文档 + `TODO.md` + `README.md` 直接接续开发。
> 项目位置（生产机）：`/home/zouyuxi/projects/vasp-manager`（Linux，自包含；旧机 Windows 路径 `D:\Skill\vasp-project-manager-web` 已停用）。部署与运维见 §11。
> 维护：**本文档由开发助手（Codex）负责维护**，是跨窗口交接的唯一权威说明；每次版本提交都同步更新
> 版本号、改动记录（§7）、待办状态（§9）与数据现状（§2）。发现文档与代码不一致时，以代码为准并立即回来改文档。

---

## 1. 项目概览

- VASP 第一性原理计算项目管理系统：总览 / 巡检中心 / 作业管理 / 智能报告 四大模块。
- 技术栈：React 18 + TypeScript + Vite 7 + AntD 5（前端，端口 5173）；Python + FastAPI + Paramiko（后端，端口 3001，`/docs` Swagger）。
- 存储：文件型 JSON（无数据库）：`data/projects.json` + 本地目录 + 自动备份 20 份 + 巡检归档 `data/checks/`。
- SSH：Paramiko 常驻连接池，操作真实 HPC（LSF 调度 bsub/bjobs/bkill）。

### 启动方式（Linux 生产机，systemd 常驻）

```bash
sudo systemctl start   vasp-manager      # 启动
sudo systemctl stop    vasp-manager      # 停止
sudo systemctl restart vasp-manager      # 重启（改了 backend/*.py 后必须）
systemctl status vasp-manager --no-pager # 状态（含 MainPID）
sudo journalctl -u vasp-manager -f       # 实时日志
```

- 单元：`/etc/systemd/system/vasp-manager.service`（`User=zouyuxi`、`WorkingDirectory=/home/zouyuxi/projects/vasp-manager`、`ExecStart=…/.venv/bin/python backend/run.py`、`Restart=always`、已 `enabled` 开机自启）。
- 访问：`http://192.168.1.20:3001`（局域网）/ `http://10.147.20.10:3001`（ZeroTier）；`/docs` 为 Swagger。
- 前台调试（**先 `systemctl stop`**）：`cd /home/zouyuxi/projects/vasp-manager && .venv/bin/python backend/run.py`；`npm run server` 等价（脚本已指向 `.venv/bin/python`）。
- 前端开发用 `npm run dev`（Vite 5173）；生产是单端口 3001 同时托管 `dist/` 与 `/api`，**改前端只需 `npm run build`，不用重启后端**。
- 数据目录可用 `backend/run.py --data-dir <目录>` 覆盖（测试隔离用）。
- 后端无 `--reload`：**改 backend/*.py 后必须重启后端**；改 `src/data/mock/incar.ts` 等默认值后需 `npm run build` + 刷新页面。
- **同一个 `data/` 只能有一个后端在写**（systemd 服务与前台进程二选一）。
- `data/` 是运行时数据（已 gitignore），部署/换机要连同 `data/` 一起复制。

---

## 2. 数据与配置

> 换机器/换操作系统（Windows → Linux）迁移看 **§11 部署与运维**：目录与服务、日常操作、常驻检查项、Linux 特有的坑、nginx 反代与回滚都在那里（原一次性文档 `MIGRATION.md` 已删除，内容并入 §11）；辅助脚本 `python scripts/migrate_paths.py [--apply]` 用来把 `data/` 里遗留的绝对路径归一化成相对路径。

```
data/
├── projects.json              # 项目/任务主库（dir_path、remote_dir 均为相对根目录的路径）
├── backups/                   # projects.json 自动备份（20 份）+ 迁移前备份
├── checks/                    # 巡检归档 check_results_*.json + runs.json
├── dashboard/
│   └── core_history.json      # 总览集群采样历史（核数/运行中任务，v0.6.0 起累积）
├── projects/                  # 本地项目镜像目录（files/ 等）
├── reports/                   # 分项目报告（v0.7.0 起）：<项目>/<报告ID>/{report.json,report.md,charts/*.svg} + index.json
├── trash/                     # 删除任务/项目的回收站
├── aux_molecules/             # 辅助分子全局目录（opt|frac）
└── config/
    ├── servers.json           # 远程服务器配置（server1，见下）
    ├── settings.json          # 力收敛阈值、同步开关、dashboard_cache_seconds / dashboard_total_cores、
    │                          # auto_inspection_enabled / inspection_interval_hours /
    │                          # auto_report_enabled / report_interval_hours 等
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
| `inspection_runner.py` | 巡检编排：筛选 → 上传脚本 → 远端批量执行 → 结果回填（job_id/current_output/状态）→ 归档；结构同步按「离子步每 25 步一桶 + 目录变化重置」触发（见 §6.2b）：opt 下载 POSCAR/CONTCAR，NEB（v0.6.9）单次远端脚本取各映像 CONTCAR/POSCAR，均调 `scripts/vasp2cif.py` 生成 CIF（opt → reports/structure/，NEB → reports/structure/images/） |
| `inspection_scheduler.py` | **自动巡检调度**（v0.6.2）：后台线程每 60s 检查一次，`auto_inspection_enabled` 打开且「距上次巡检 ≥ `inspection_interval_hours`」时触发一轮全局巡检；提供 `scheduler_status()` 与 `update_schedule()`（写入 settings.json） |
| `checks_store.py` | 巡检归档合并（最新条目 + 旧 force_history 沿用）、列表行组装（has_inspection 等） |
| `report_builder.py` / `report_charts.py` / `report_panels.py` / `report_rules.py` / `report_store.py` / `report_schema.py` / `report_export.py` | **分项目报告（v0.7.0，v0.7.3 起看板同版式）**：数据收集（任务元数据 + 巡检归档 + 集群快照 + 审计日志）→ 结构化对象 → Markdown → 纯 Python SVG 图表；`report_charts.py` 是通用图（双轴曲线 / 圆环 / 进度条 / 结构三视图 / 映像矩阵），**`report_panels.py` 是与巡检详情页同版式的看板图**（统计卡 + 图例 + 自由能台阶图 / NEB 能垒曲线 / 项目进度分块进度条）；风险规则外置可配；按项目分目录存储 + 索引；自包含 HTML 导出（可选章节、图表内联） |
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
  - 巡检中心**列表排序 + 路径列跨行合并**（v0.6.6 排序 / v0.8.6 合并修复）：状态优先级 `错误(0) > 警告(1) > 待提交/未检(2) > 正常(3) > 关闭(4)`；自由能 / NEB **同一组算一个排序单元**，用组内最高优先级状态整体参与排序（组内成员恒定相邻）；整组归档的单元沉到其他任务下面；其余保持原规则（类别 → 组名自然序 → 组内结构顺序 → 任务名）。同项目下自由能组与 NEB 组可能同名（如都有 PATH1），**排序单元键与跨行合并键都必须带 `task_category`**（`项目|类别|组名`）——合并键漏掉类别会让同名两组在排序相邻时被并成一格（v0.8.6 已修，见 §7）。
- `components/dashboard/`：RunningTasksPanel（bjobs 实时作业表，点行跳 `/jobs?task=`）、CoresUsagePanel（ECharts 圆环 + 项目着色 + 90%/100% 阈值）、ClusterHealthPanel（节点灯 / 队列拥堵 / 存储进度）、RiskAlertsPanel（未收敛+Zombie+巡检异常，点条目跳转）、TrendPanel（近 7 天核数/运行任务/提交数）、ProjectProgressPanel（四象限气泡 + 项目进度列表 + **已关闭项目折叠区**，样式为胶囊按钮 + 虚线分隔）、`useEcharts.ts`（**ECharts 按需注册**：Pie/Line/Bar/Scatter + Grid/Tooltip/Legend/Title/MarkLine + Canvas）。
- `hooks/useCountUp.ts`：统计卡片数字滚动动画。
- `api/dashboard.ts`：总览接口封装（overview / cores-usage / cluster-health / risk-alerts / trend）。
- `pages/Report.tsx` + `api/reports.ts` + `utils/markdown.ts`：分项目报告页——按项目生成 / 一键生成所有项目、**项目报告列表（每项目一份，同项目重生成直接覆盖）**、章节导航、Markdown 渲染（自写轻量渲染器，无第三方依赖，`chartResolver` 把 `charts/x.svg` 映射到 `/api/reports/project/{id}/files/x.svg`）；**正文只渲染图片，没有任何交互式组件或结构化数据视图**（v0.7.2 起"所见即所得"——前端看到的排版与导出 HTML/PDF 一致）；**导出按钮挂在「报告内容」标题行**，点击才展开章节勾选 Popover（下载 Markdown / 导出 HTML / 导出 PDF）。图里的看板版式（自由能 / NEB / 项目进度）由后端 `report_panels.py` 生成，与巡检详情页保持一致。
- `components/jobs/`：IncarEditor（INCAR 编辑器：分类表单 + 自定义参数框 + 生成到本地 + 上传远端）、KpointsPanel（KPOINTS 生成）、PoscarPanel、SubmitScriptPanel、ContinuationModal、NebFilesModal、EleInputModal、GroupWizardModal、NewTaskModal、TaskOverview、StructureDetail、NebGroupDetail、CopyParamsModal、JobsTree。
- `components/inspection/`：ForceHistoryCharts / LineChart（能量-力曲线，悬停竖线）、**NebImages3DViewer**（NEB 映像结构分析 v0.6.9：IS → 中间态 → FS 横向 3D 对比，视角联动/球棍·空间填充/自动旋转/缩放/重置/元素图例，鞍点面板高亮）、**NebBarrierPanel**（NEB 能垒看板 v0.6.8：统计卡（映像数 / Ea / 最大受力 / 末态相对能）+ 相对能垒曲线（直线连接不插值、鞍点标注、渐变面积、悬停按映像出信息卡）+ 映像明细列表（角色徽标），曲线绘制 / 数据点弹出 / 列表错峰入场动画，样式复用 `.fe-*`）、**PathSummaryModal + PathStepChart**（自由能路径看板 v0.6.7：顶部统计卡（中间体数/矫正完成度/收敛情况/最高相对能）→ 相对能台阶图 → 中间体明细列表；台阶带渐变柱体与面积、状态点、跟随鼠标的 HTML 信息卡（自由能/相对 ΔE/DFT/矫正项/收敛矫正状态）、悬停上浮 + 发光、点击台阶或行打开该结构巡检详情；入场动画为台阶从左依次滑入 + 连接线淡入 + 标签依次出现，列表行错峰上浮，`prefers-reduced-motion` 下全部关闭）、StructurePanel（结构分析表 + Structure3DViewer）、**Structure3DViewer**（3Dmol：并排/叠加/单侧、球棍/空间填充、缩放/自动旋转/a-b-c 视角、双侧相机同步、点击原子金色高亮联动、空白取消、左下角 abc 方向图例、右下角元素配色图例）、EleAnalysisPanel、PdosModal。
- `utils/poscar.ts`：POSCAR 解析、k 网格推荐、`buildKpoints`（**纯 ASCII 输出**）。
- `utils/structure3d.ts`：3Dmol 数据工具（CIF 解析、VESTA 元素配色、共价半径算键）；3Dmol 库本地化于 `public/3dmol/3Dmol-min.js`（index.html 全局引入，无 npm 依赖）。
- `data/mock/incar.ts`：**编辑器默认参数定义**（INCAR_CATEGORIES 的 defaultValue / PRECISION_PRESETS 低中高 / TASK_TYPE_INCAR 类型覆盖 / buildDefaultParams / buildIncarText 分组空行 / parseCustomIncar）。
- `types/index.ts`：任务/状态/INCAR 类型（IncarParamDef 含 `fracOnly` 标记）。

---

## 6. 关键业务流要点

1. **SSH 连接**：统一走 `ssh.py` 连接池；每条 exec 有 ~1.3-2s 远端 shell 启动开销（HPC 负载高时 3-4s），**多步操作必须合并成单次 base64 bash 脚本**（参考 continuation `_remote_script` + `===STATE===/===FILES===` 标记分段）。
2. **巡检**：全局 `POST /api/inspections/run`、单任务 `run-single/{task_id}`（任意状态可巡检，跳过筛选）；batch_check 自动上传远端；结果归档 data/checks 并按 task_id 合并；运行中任务也回传 last_energy + force_history。
2b. **结构分析触发（analysis_needed，v0.4.6 起；v0.6.9 起 opt + neb 同规则）**：opt 与 neb 任务都适用；离子步每 25 步一桶（0-24→桶0、25-49→桶1、50-74→桶2…）。同一输出目录：桶 ≥1 且比上次触发桶更大才触发（25-49 触发后，再次巡检仍在 25-49 不触发，直到 50-74 及以后）；输出目录变化：视为新目录重置计数，重复按桶触发。触发时下载 POSCAR/CONTCAR → `scripts/vasp2cif.py` 生成 `reports/structure/{POSCAR,CONTCAR}.cif`（新结果覆盖旧 CIF）；**NEB 任务**（v0.6.9）步数取中间映像 OUTCAR 的 TOTAL-FORCE 块最大值，触发时用单次远端脚本把各映像 CONTCAR（缺则 POSCAR）base64 回传，生成 `reports/structure/images/<label>.cif`（IS → 中间态 → FS，详情页做 3D 横向对比），任务持久化 `last_analysis_bucket` / `last_analysis_dir`。**CIF 使用规则**：详情接口有本地 CIF 直接用；没有 CIF 但本地有 POSCAR/CONTCAR 时用脚本现场转换补缺（只补缺不覆盖）；转换先写临时文件成功后再原子替换，失败保留上一次结果。前端 Structure3DViewer 用 3Dmol 渲染（VESTA PNG 方案已移除）。
3. **续算**：`POST /jobs/tasks/{id}/continuation`。opt：最新目录 OUTCAR/CONTCAR 均非空 → 创建 con(N+1)，复制 CONTCAR→POSCAR/POTCAR/KPOINTS/INCAR/提交脚本、**WAVECAR 用 mv**，INCAR 改 ISTART=1/ICHARG=0；未完成 → 分流提示（input_complete_but_not_finished / input_incomplete）；运行中 → 提示等待。NEB：从最新续算目录复制共享文件 + 端点 POSCAR 固定并**带上 00/NN OUTCAR**、中间映像 CONTCAR→POSCAR、**各映像（含端点/中间态）存在 WAVECAR 时随续算 mv 移动**（目标已有不覆盖）。续算在 DB 登记隐藏子任务（不展示，供后台定位）。
   - **活跃作业保护（v0.5.5）**：opt/NEB 续算脚本都在创建目录**之前**用 `bjobs -l`（含 `bjobs -o 'jobid exec_cwd'` 按源目录/映像子目录二次匹配）判定是否有 RUN/SSUSP/PSUSP/USUSP 作业，命中则只回传状态、返回 `action="running"`，**不建目录、不移动文件**。opt 自 v0.4.5 起如此，NEB 在 v0.5.5 补齐（此前 NEB 续算对运行中作业没有拦截）。
   - **WAVECAR 是移动语义**：续算成功后源目录不再保留 WAVECAR（opt 与 NEB 一致，目标已存在则不覆盖）。NEB 连端点 00/NN 的 WAVECAR 也一并移动，端点 POSCAR/OUTCAR 是复制。
4. **提交/停止**：提交 = 定位最新 con → 检查 vasp.lsf → `bsub < vasp.lsf`，成功后**立即写库 job_id**；停止 = bkill，输出 `Job has already finished` 也按成功处理（状态→pending，job_id 保留为历史）。
5. **文件构建**：`create_frac_files`（opt 最新输出 → frac，默认 ISYM=0/SIGMA=0.05/NSW=1/IBRION=5/**NFREE=2**/POTIM=0.015）；`create_neb_files`（**以 IS INCAR 为基底只改 NEB 参数**：IBRION=3/POTIM=0/IOPT=3/LCLIMB/IMAGES/ICHAIN/SPRING=-5/MAXMOVE=0.2）；`build_ele_inputs`（NSW=-1/IBRION=-1 + 各类型参数，冲突抛错）。
   - **输入文件状态：快照 / 草稿 / 变更台账（v0.8.2，`backend/input_state.py`）**：三层职责——① **远端 conN/** 是这次计算真正用的输入（唯一真相）；② **本地快照** `<任务目录>/inputs/`（INCAR / KPOINTS / POSCAR / CONTCAR + 同目录 *.cif），元数据（哈希 / 解析出的参数 / k 网格 / 结构摘要 / 来源目录 / 同步时间）写在 `task["input_state"]`；③ **草稿 drafts** + **变更台账 changes**（`file/key/from/to/at/applied_at/applied_in`）。
     - **同步时机**：提交作业成功后后台自动同步一次（`_schedule_input_sync`，延迟 2s，不阻塞接口）；用户可随时点「同步最新参数」手动同步。成本固定为 **1 次 exec + 4 次 SFTP 小文件**（定位"最新且真的有 INCAR 的目录"→ 下载四个文件），不做后台轮询。
     - **改参数不碰远端**：编辑器默认**只读**，点「修改参数」才解锁，改完点「确认修改」才写入草稿 —— **只在下次续算时应用**（运行中的作业不会重读 INCAR，直接改最新目录会抹掉"这次计算用了什么参数"的记录）。
     - **续算应用**（`continuation._apply_drafts_to_new_dir`）：cp 文件后按 `modify_incar(ISTART=1/ICHARG=0 + 草稿参数)` 写 conN/INCAR（续算必需项优先，用户改了这两项会告警），KPOINTS 草稿只改网格行（网格行**行首不留空格**），**POSCAR 永不覆盖**（续算 POSCAR 来自 CONTCAR）；台账条目标记 `applied_in=conN` 并清空草稿。
       - **只在实际改动时写文件**：INCAR 只在"有草稿应用，或 ISTART/ICHARG 与目标值不同"时写回，没变化就保持 `cp` 过来的原文件；KPOINTS 只有草稿才写。返回值里的 `incar_written` 标明是否写过。
       - **不往 INCAR 里写注释**（v0.8.3 起）：早期版本会在 conN/INCAR 顶部写 `# [vasp-manager] … 续算应用参数变更：…`，中文注释被按 GBK 解码时显示成乱码（用户要求去掉），改动记录只留在本地变更台账，界面横幅显示"上次续算已应用 N 项"。
       - **值比较是语义化的**（v0.8.3）：布尔 `.T.` ≡ `.TRUE.`、数值 `1E-6` ≡ `1e-6`/`-0.02` ≡ `-0.020` 都算"没改"，不会误记成待提交；含空格的参数值（`DIPOL = 0.5 0.5 0.18`、`MAGMOM = 5*2.0`）**完整保留**，不能按空格截断。
       - **续算后父任务状态必须落库**（v0.8.3 修）：`create_same_type_continuation` 里 `create_continuation` 改的是内存里的 task，登记续算子任务时的 `save_db` 用的是重新 `load_db()` 的副本 —— 必须在同一次保存里把父任务的 `input_state` 一起写回，否则界面会一直显示"有修改待提交"。
     - **POSCAR vs CONTCAR 语义**：作业管理输入页的 POSCAR 是**提交时的初始结构（不会变）**，CONTCAR 是**这次计算的最新结构**；同步同时取回两者并各转一份 CIF，页面可切换查看（3D 大窗口 + 点选原子 + 结构数据），所以"POSCAR 永远不变"不再是问题（要看当前结构就切 CONTCAR）。
   - **INCAR 默认参数与"留空即不写"（v0.8.1）**：默认参数两处同步——前端 `src/data/mock/incar.ts`（编辑器默认值/选项）与后端 `data/config/task_registry.json`（建组/建任务时写盘，模板在 `backend/defaults/`）；**v0.8.1 起四种任务类型的 default_incar 都含 `IVDW = 11`（DFT-D3(BJ)）**。**参数值留空（空字符串 / None / 仅空白）一律不写入 INCAR**：前端 `buildIncarText` 本就跳过空值，v0.8.1 补齐了"上传远端"链路（`IncarEditor` 过滤空值 + `incar.modify_incar` 忽略空值），把 NCORE 之类的框清空不会再写出 `NCORE = `；注意 `modify_incar` 对**已存在**的参数行只做"不覆盖"，不会因为留空而删除该行。
   - **新建项目可直接建组（v0.8.1）**：`AddProjectModal` 的自由能/NEB 分类改成"按组创建"——自由能 = 组名 + 结构数（后端 `POST /api/groups` 会为**每个结构同时登记 结构优化(opt) + 频率矫正(frac) 两个任务**，frac 的 `parent_task_id` 指向同结构 opt，即频率矫正始终是自由能的子项），NEB = 组名 + 映像数；opt/ele 仍是单任务。提交顺序是"先建项目 → 再逐个建组"，因此 `models.ProjectIn.tasks` 放开了"至少 1 个独立任务"的限制（允许只建组）。
6. **矫正项**：frac 巡检完成后自动尝试 vaspkit 501；前端矫正项框有值也可点击重算（联动：frac 未完成先单独巡检）。
7. **NEB 能垒**：巡检对 NEB 任务跑 nebef.pl，结果 `neb_barrier.images`；端点 OUTCAR 是创建时从 IS/FS 复制的伪结果，**不作为运行证据**。
8. **闭环：提交 → 巡检 → 归档（v0.6.2）**：
   - **提交**：`POST /jobs/tasks/{id}/submit` 成功后写 `queued` + job_id（**已在 db_transaction 内**，不会再被巡检回填覆盖）。
   - **全局巡检分批**：`_plan_batches()` 按**项目**切批次（同一服务器可多批），脚本与阈值每个服务器每轮只上传一次；远端检查在**事务之外**执行，回填 + 归档时才进入该项目的独立 `db_transaction`，因此单项目失败不影响其他项目（摘要返回 `failed_batches`），数据库写锁只持有本地回填那一小段。
   - **自动巡检**：`inspection_scheduler` 后台线程每 60s 判定一次（开关 + 距上次巡检 ≥ 间隔，默认 2h）→ 触发全局巡检；页面开关写 `settings.json` 即刻生效。
   - **巡检后刷新集群**：全局巡检成功后（无失败批次）调用 `dashboard.invalidate_cluster_cache(servers, prewarm=True)`，作废快照缓存并后台预热，用户切到总览即是最新数据。
   - **归档 / 关闭**：任务可「关闭（归档）」→ `status=archived`（记 `archived_at` / `archived_from`，`/api/projects` 会把这两个字段一并返回，供"重新打开"显示恢复目标）；**自由能结构优化主任务归档时，连同其 `<结构目录>/frac` 频率矫正子任务一起归档**，重新打开时也成对恢复（`archived_siblings` / `reopened_siblings` 回传，前端提示连带关系；主任务归档时若 frac 未完成会弹窗警告）。项目下**可见任务全部归档**后可「关闭项目」→ `project.closed=true`，在总览、巡检中心、作业管理里统一排到最后、灰显、默认折叠。归档/关闭都不动本地与远端文件。
   - **归档任务不可巡检（v0.6.5）**：单任务巡检遇到 `archived` 任务直接返回 400「任务已关闭（归档），请先重新打开再巡检」，避免巡检回填把归档状态覆盖回 completed/zombied；全局巡检本来就跳过 archived。巡检列表中归档任务状态列显示 **「关闭」**（`CheckStatus` 新增 `archived`），信息列写「任务已关闭（归档）」，且不计入项目块头部的「未检」计数，操作列的「单独巡检」按钮置灰并提示先重新打开。
   - **巡检性能（2026-09-13 优化，`batch_check.py`）**：① **bjobs 每轮只查 2 次**——`main()` 先取一次 `bjobs -o "jobid exec_cwd"` 全量表（`_bjobs_cwd_table()`），再把「库里 job_id ∪ 该表的 job_id」用 `bjobs -l id1 id2 …` 批量查明细（`prefetch_bjobs_details()`，40 个一组），`run_bjobs` / `match_job_id_by_cwd` 全部命中缓存；**不要再改回逐任务起子进程**（登录节点上每次 50-500ms，60 个任务就是几十秒，实测 45 任务 × 0.2s：115 次 → 3 次，24.8s → 1.3s）。② **不再整文件读 OUTCAR**：`resolve_latest_output` 改为「尾部 8KB 判正常结束 + 分块计数（`_count_marker(cap=…)` 超阈值即返回）」，NEB 每映像从「读全文判结束 + 再扫一遍数块」合并成一次 `_scan_outcar()`；`_count_marker` 加了跨块重叠避免漏计。实测同一批任务输出结果**逐字段完全一致**，纯 I/O 部分快约 1.2×、含 bjobs 开销快 6–20×。

   - **INCAR 读取 + 精度检查（2026-09-13，思路 A）**：`batch_check.py` 在**已经在读**的最新输出目录里顺手读一次 `INCAR` / `KPOINTS` / `POSCAR`（1KB 级文本，**不新增任何 exec / SFTP**），随结果回传 `incar`（键值快照）/ `kpoints.mesh` / `lattice_abc` / `force_thresholds` / `precision`。① **结构优化的力收敛阈值改由 INCAR 的 `EDIFFG` 决定**（负值＝力判据 eV/Å；RMS 阈值取 |EDIFFG|/2，与旧的 registry 0.02/0.01 比例一致，`EDIFFG=-0.02` 时与旧行为完全相同；`EDIFFG` 缺失或为正值时退回 `check_registry.json`），`force_thresholds.source` 会写明取值来源。② **精度检查**（要求写在 `check_registry.json` 的 `precision` 段，可改）：k 网格密度系数 = k × 晶格常数 **> 20**（三个方向都要满足；Auto/0 0 0 记「无法判定」不算不达标）、力收敛精度 `EDIFFG ≤ -0.02`、电子步收敛 `EDIFF ≤ 1E-5`（未设置时按 VASP 默认 1E-4 判）；任一项不满足 → 该结构优化任务判定为 **低精度收敛**。③ **低精度收敛的落法**：巡检归档里状态是 `low_precision`（巡检列表显示「低精度收敛」、走 warning 色，详情里列出未达标项与阈值来源），**数据库任务状态仍写 `completed`**（`inspection_runner._apply_result` 里做映射），所以进度/看板/作业管理的口径不受影响；报告「异常与关注项」会把它列为 medium 关注项。④ 想宽松些：把 `precision.treat_missing_as_default` 设为 false（INCAR 未写 EDIFF/EDIFFG 就只记「无法判定」，不判不达标）。

9. **总览数据流（v0.6.0）**：`GET /api/dashboard/overview` 一次返回整页（顶部统计 + 运行作业 + 核数 + 集群 + 风险 + 项目进度 + 趋势 + 最近任务）。
   - 集群部分来自**一次 exec** 的 `@@@` 分段输出（bjobs/blimits/df/bhosts/bqueues），服务端缓存 5 分钟（`settings.json: dashboard_cache_seconds`），前端每 30 分钟自动刷新一次；`?refresh=1` 强制查询（约 2-4s）。
   - 本地聚合（风险/趋势/项目进度/完成统计）缓存 60 秒：巡检归档有数百个结果文件，逐个读取约 1-2 秒。
   - **口径**：①「运行中任务」取 LSF 实时 `RUN` 作业数（不是任务表状态，任务状态要等巡检回填）；②「核数占用」优先用 `blimits` 的 SLOTS 已用/上限（按队列组），`settings.json: dashboard_total_cores` 可手动覆盖上限，两者都没有时退回 bjobs 汇总；③「项目进度」分母为**可见任务**（不含 conN 续算目录），与作业管理页口径一致；④「今日完成」= 当天巡检观察到 completed 且前一天未完成的任务；⑤「节点满载」按 RUN≥MAX 判定（LSF 常把跑满节点置为 closed）。
  - 每次成功查询把 `{ts, usedCores, runningTasks, pendingTasks} `追加到 `data/dashboard/core_history.json`（10 分钟内不重复采样，最多 4000 条），趋势图按天取峰值；**历史从 v0.6.0 上线那天开始累积**，之前不可回溯；「提交作业数」由 `data/audit_submit.log` 回溯统计，是完整历史。

10. **报告的工作量 / 工期口径（2026-09-13 定，用户要求）**：一切都按**任务当量**折算——
    - 当量 = `task_registry.workload_weight` 按类别累加（结构优化 1 · 频率矫正 1 · NEB 5 · 电子结构 0.4；自由能路径的中间体与 frac 各计 1）；**归档/已完成都算已完成当量**。
    - **1 当量 ≈ 600 核时**（`settings.json: core_hours_per_weight`）。
    - **有效算力 = 200 核 × 24h × 70% = 3,360 核时/天**（`cluster_max_cores` / `cluster_utilization`）。
    - 主进度 = 已完成当量 / 总当量；**预计完成 = 今天 + 剩余核时 ÷ 有效算力**；剩余为 0 时记"已收尾"。
    - 落地位置：`report_builder._workload_plan()` → 结构化的 `basic_info.workload` / `progress.workload` / `progress.eta_days`，进度图 `report_panels.segmented_progress_chart(notes=...)` 与报告头 meta 都会显示（Ag 实测：87 当量 = 52,200 核时，已完成 31,800，剩余 20,400 → 还需 6.1 天）。

---

## 7. 近期重要改动记录（v0.4.1 → v0.8.6）

- v0.8.6（commit `052ff27`，已推送 origin/main）：**同名自由能组 / NEB 组路径列误合并修复 + `/api/jobs/nodes` 回归修复 + HPC 连接快捷脚本**。① **修「自由能路径和 NEB 路径重名时会自动合并」**（用户登记在 TODO.md「发现问题」）：巡检中心把同组的行**跨行合并「路径」列**，排序用的单元键是 `项目|task_category|组名`，但合并用的键只有 `项目|组名` → Ag_20260830 的 PATH1/2/3 双身份组（自由能 `free_energy_Ag111` 等 7 行 + NEB `neb_Ag111` 等 3 行）在排序里类别相邻（自由能 1 → NEB 2）且键相同，被并成一格、NEB 组失去自己的路径格。修法：`src/pages/Inspection.tsx` 的 `rowSpanByProject` 合并键补 `task_category` 并留注释防回退；**纯前端改动**，`npm run build` 后刷新页面即生效（3001 单端口托管 `dist/`，无需重启后端）。后端侧已核实无同类隐患：作业管理任务树、报告（`_free_energy_paths` / `_neb_details`）、组数据接口、图表文件名全部按 `group_id` / `task_id` 聚合，仅"显示名"取 `group.name`。② **修 `/api/jobs/nodes` 的 500 回归**（v0.8.2 引入）：`backend/routers/jobs.py` 先 `from cluster_status import build_snapshot`（签名 `(server_name, use_cache=True)`），又被后面的 `from input_state import build_snapshot`（签名 `(server, task, *, kind="manual")`）覆盖，节点接口传 `use_cache=` 必然 `TypeError` → 500；改为 `from cluster_status import build_snapshot as build_node_snapshot`（节点接口用别名，输入快照仍用原名），实测 `GET /api/jobs/nodes` 返回 200 + 真实节点数据（`source: real`，15 个节点）。③ **新增 `scripts/connect-hpc.sh` + `scripts/connect-hpc.desktop`**：桌面/终端一键登录 HPC（默认 `mdye@hpc.xmu.edu.cn`，`HPC_HOST` / `HPC_USER` 可覆盖），登录前校验私钥存在与 `600` 权限、校验目标 IP 路由是否走 `tun0`（SecureLink 校园 VPN），支持 `--cmd '命令'` 单命令执行与 `--pause`（桌面启动器用，退出后窗口不闪退）。④ 文档：TODO.md「发现问题」清空并登记本次修复，process.md §5 排序条目补「跨行合并键同样必须带 `task_category`」。
- v0.8.5（commit `589338e`，已推送 origin/main）：**迁移落到 Linux + 输入参数页两张新卡片 + 两处线上 bug 修复 + 文档合并**。① **部署**：代码与数据统一在 `/home/zouyuxi/projects/vasp-manager`（git clone + `.venv` + `npm ci && npm run build`，`data/` 在仓库内故 `path_mapping.local_root` 保持相对 `data/projects`），用 systemd `vasp-manager.service`（`User=zouyuxi`、开机自启、`Restart=always`）常驻；Python 实测 **3.14.4** 可用（fastapi 0.141.1 / uvicorn[standard] 0.53.0 / paramiko 5.0.0；uvloop 0.22.1、httptools 0.8.0 均有 cp314 轮子），Node 22.22.1；`package.json` 的 `server` 脚本由 `python` 改为 `.venv/bin/python`，避免 Linux 下 `python: command not found`。② **输入参数页新增「DFT+U」卡片**：主开关关闭时整卡置灰且**不写入任何 LDAU\* 参数**；打开时写 `LDAU = .TRUE.`，并按元素表生成 `LDAUL / LDAUU / LDAUJ`（一一对应，行增删同步更新三个数组；元素名取 POSCAR 元素行，默认首元素加 U：`2 / 4.0 / 0.0`，其余 `-1 / 0.0 / 0.0`），`LDAUTYPE`（默认 1）、`LMAXMIX`（默认 4）按选择写入。③ **新增「偶极矩修正」卡片**：关闭时不写 `LDIPOL / IDIPOL / DIPOL`；打开时写 `LDIPOL = .TRUE.`、`IDIPOL` 按选择（默认 3）、`DIPOL` **三个分量都非空才写** `x y z`。开关语义用 `applyIncarGates()` 统一，同时作用于**预览文本 / 生成到本地 / 上传远端 / 续算草稿**四条链路（后端 `modify_incar` 把空值视为"不写入"，故关闭时必须清空该组参数）。④ **输入参数页布局**：卡片容器由"按行对齐的 grid"改为**两列独立流式**（`.job-incar-grid` + `.job-incar-col`，窄屏单列），卡片各自自然高度，离子弛豫 / 自旋与磁性等短卡片不再被同行高卡片撑出大片空白。⑤ **修「一键清除」红点 bug**：原实现 `setReadChanges(new Set())` + `localStorage.removeItem()` 等于清空"已读"记录，而红点条件是 `status_changed && !已读` → 点一次反而全部重新点亮；改为把当前所有 `status_changed` 任务标记为已读并写回 localStorage（与"点开详情"同一机制）。⑥ **修「其他参数」不可编辑**：原来直接渲染 `extraIncarParams()`（只保留非空值）→ 新增的空值行被过滤掉、看不见也打不进字，且行以参数名为 React key、改名会重建输入框丢焦点；改为"本地行 + 稳定 id"模型（`ExtraRow {id,key,value}`，编辑即写回参数、外部变化才重建），并补上编辑态行内「添加参数」入口与空态文案。⑦ **迁移踩坑与修复**：Windows 大小写不敏感导致 `data/projects/Ag_20260830/` 下同时存在 `NEB/`（老数据，含完整映像 00–04）与 `neb/`（Linux 新写入的空壳），页面 NEB 映像只剩中间 3 个 → 已把新文件并回老树并用软链接 `neb → NEB` 对齐；全盘审计（本地路径 272 条 / 远端路径 324 条 / 模块导入 / 产物引用）确认**无其它大小写分叉**。⑧ **文档合并**：删除一次性的 `MIGRATION.md`，可复用的部署、运维、验收与故障排查内容并入本文档 §11 与 `README.md` / `DEPENDENCIES.md`。
- v0.8.4（commit `aaae4b3`，已推送 origin/main）：**跨机器迁移交接（Windows → Linux）**。① 新增 **`MIGRATION.md`** 交接文档：三块构成（代码 / `data/` / 远端 HPC）→ 打包清单（逐项 + `data/` 各子目录作用与大小）→ 旧机停机与打包 → 目标机依赖与数据放置 → **迁移后必改 11 项**（SSH 私钥、`path_mapping.local_root`、`settings.json`、时区、编码、启动命令 `python`→venv `python3`、`npm run build`、遗留路径归一化、端口、xdg-open、"打开文件夹"、进程常驻）→ **首次自检验收表** → systemd 单元与 nginx 反代示例 → 注意事项（**绝不能两台机器同时跑同一 `data/`**）→ 回滚 → 已知 Windows 痕迹 → 故障排查表 → 附录（`data/` 速查 + 迁移前实测快照）。② 新增 **`scripts/migrate_paths.py`**（dry-run 默认 + `--apply`）：把 `data/aux_molecules.json` 的 `dir/opt_dir/frac_dir` 与 `data/reports/index.json` 的 `directory` 归一化成相对路径，改写前备份到 `data/backups/migration_<时间>/`，并只读扫描 `projects.json` / `checks/runs.json` 里其它绝对路径。③ **修复两处会阻碍迁移的绝对路径**：`aux_molecules.json` 改存相对数据根路径（`aux_molecules/<标签>[/opt|/frac]`），读取时由 `_resolve_entry()` 还原成**当前机器**的绝对路径（老数据里的 Windows 盘符/反斜杠自动丢弃、按标签重建，已实测 API 返回本机路径）；`reports/index.json` 的 `directory` 写入即相对（`<项目>/<报告ID>`），读取时 `_read_index()` 就地归一化。④ 清理测试残留目录 `data/projects/P`（0 文件、库中无引用）。⑤ 迁移前置审查结论：**代码无平台专有依赖**（无 pywin32/winreg/ctypes/signal 专用逻辑，`_open_in_explorer` 已含 Linux `xdg-open` 分支）、**本地模块导入无大小写不一致**（45 个模块全量扫描通过，Linux 大小写敏感）、**仓库与 `data/` 无任何非 ASCII 文件名**、`projects.json` **0 处绝对路径**、`public/3dmol/3Dmol-min.js` 已入库 → 迁移只需"clone 代码 + 拷 `data/` + 配 SSH 私钥 + 改 11 项配置"。⑥ `process.md` §2 与 `README.md` 顶部加了指向 `MIGRATION.md` 的入口。
- v0.8.3（commit `76ef158`，已推送 origin/main）：**作业管理输入文件页的一批修正**（用户逐条验收后的收尾）。① **「文件结构」改成「同步状态」**：INCAR/KPOINTS/POSCAR/CONTCAR 显示 **最新（绿）/ 过时（黄，只在本地没同步过）/ 有修改待提交（琥珀高亮）**，POTCAR 与 submit.sh 标"不参与同步"，**去掉 WAVECAR**。② **POSCAR 页原子操作**：单击选中（金色高亮）、**Ctrl/⌘ 点击多选**、**按住 Shift 拖拽框选**（Ctrl/⌘+Shift 框选为并入），选中标签按 POSCAR 序号**自动合并区间**（`Al1 Al2 Al3 Al6 Al7` → `Al1-3 Al6-7`），序号与 **POSCAR 坐标行一致（从 1 开始，即 `Ag17`/`O33`）**；切 POSCAR ⇄ CONTCAR **保持同一视角**（`getView`/`setView` 往返，不再重置）；POSCAR 目前不参与远端修改（后续只有"固定原子"会改它，先搁置）。③ **NEB 映像只取 CONTCAR**（不再回退 POSCAR —— 映像的 POSCAR 是插值初始结构，当"优化后结构"展示会误导），NEB 映像任务的详情页**去掉 POSCAR 页签**。④ **参数识别修正**：布尔支持 `.T./.F.` 全等价写法（原来只认 `.TRUE.`，导致 `LWAVE = .T.` 显示未勾选、还会被误判成"已修改"）；含空格的参数值（`DIPOL = 0.5 0.5 0.18`、`MAGMOM = 5*2.0 3*1.0`）**完整保留**，不再被截成第一个 token。⑤ **只在实际改动时写文件**：「上传到远端」先与本次计算的快照比对，一致就跳过；续算时 INCAR 只在参数真变化时写回。⑥ **续算不再写审计注释**（中文注释在 GBK 环境显示成乱码，用户要求去掉），改动只记在本地台账；顺带修正 KPOINTS 网格行行首多一个空格、INCAR 每续算一次多一个 `\r`（`_write_remote_file` 统一 LF）两个回归。⑦ **续算后状态落库**：`create_same_type_continuation` 把父任务被应用过的 `input_state` 与续算子任务一起保存，修掉"续算成功后界面仍显示有修改待提交"。
- v0.8.2（commit `2785c91`，已推送 origin/main）：**作业管理输入文件重构：自动同步远端参数 + 参数草稿/变更台账 + 续算应用 + POSCAR 3D 编辑页**。① 新增 `backend/input_state.py`：远端 conN 的 INCAR/KPOINTS/POSCAR/CONTCAR 同步到 `<任务>/inputs/`（含 CIF），元数据（哈希/参数/k 网格/结构摘要/来源）存 `task["input_state"]`；**提交作业成功后后台自动同步一次**（延迟 2s、不阻塞提交），也可手动「同步最新参数」，成本 1 次 exec + 4 次 SFTP 小文件，无后台轮询。② 新增接口 `GET /jobs/tasks/{id}/input`、`POST …/input/sync`、`PUT …/input/draft`、`DELETE …/input/draft/{file}`；**参数改动不再直接改远端**，而是写草稿 + 变更台账（file/key/from/to/at/applied_at/applied_in），只在**下次续算**时应用——符合"运行中的作业不重读 INCAR，不能抹掉这次计算的参数记录"这一前提。③ `continuation._apply_drafts_to_new_dir()`：续算 cp 文件后把草稿 INCAR 参数并进 `modify_incar`（ISTART/ICHARG 续算必需项优先，冲突告警）、KPOINTS 草稿只改网格行、**POSCAR 永不覆盖**（续算 POSCAR 来自 CONTCAR），并在 conN/INCAR 顶部写 `# [vasp-manager] …` 审计注释、台账标记已应用。④ 前端：INCAR 页**默认只读**（点「修改参数」解锁 → 改 → 「确认修改」才生效），**已修改/待生效参数高亮**（琥珀色 + "待生效"角标 + 原值提示），顶部来源横幅显示「来源 conN · 作业号 · 同步时间」+ 待生效清单（可逐项撤销）；**其他参数**（原"自定义参数"）改为列出本次计算 INCAR 里不在预设表单中的键值（可编辑，留空即不写）；`buildIncarText` 同步支持把这些"其他参数"写进 INCAR。⑤ **POSCAR 页重构**：大尺寸 3Dmol 窗口（460px）+ 初始 POSCAR / 最新 CONTCAR 切换 + **点击选中原子**（金色高亮、多选、可清空，为后续固定原子铺路）+ 结构数据卡（元素组成/原子数/晶格）+ 交互按钮（球棍/空间填充、原子缩放、自动旋转、a/b/c 视角、重置视角）；「固定选中原子」按钮先占位置灰。⑥ KPOINTS 页新增「本次计算的 K 点网格」卡：直接改 k1/k2/k3（同样走只读闸门 + 确认 + 待生效高亮），并显示网格密度系数 k×a 与巡检 >20 的对照。⑦ 实测（真机）：`task_1787633537913_1` 同步 10s 取回 con1 的 INCAR（22 个参数，含 ISTART/ICHARG/EDIFFG/IVDW）、KPOINTS 2×2×1、POSCAR/CONTCAR（41 原子）与两份 CIF；草稿写入 EDIFFG -0.02→-0.01 / KPOINTS 2×2×1→3×3×1 成功记录 3 项并可逐项撤销；离线单测验证续算应用（INCAR 参数合并 + 审计注释 + KPOINTS 网格重写 + 台账 applied_in）。
- v0.8.1（commit `ae8ad08`，已推送 origin/main）：**总览滚动 + 新建项目建组 + INCAR 细节**。① **总览「运行中的任务」固定高度**：表格加 `scroll={{ y: 320 }}`，作业变多时模块不再被撑高（固定 320px 内部滚动、表头吸顶），实测 9 行时卡片高度 477px（其中表格体 320px）。② **新建项目支持"建组"**：`AddProjectModal` 的自由能/NEB 分类从"加单个任务"改为"按组创建"——自由能 = 组名 + 结构数、NEB = 组名 + 映像数，提交时先建项目再调 `POST /api/groups`；**创建自由能任务会同时登记结构优化(opt) 与频率矫正(frac) 两个任务**（frac 仍作为 opt 的子项，`parent_task_id` 指向它，呈现方式不变），修掉了"新建项目里只能建出一个 `xxx · 频率矫正`"的问题。③ **后端放开"至少 1 个独立任务"**：`models.ProjectIn.tasks` 允许空列表（只建组的项目），前端仍要求"至少 1 个子任务或 1 个组"。④ **INCAR 留空不写入**：`incar.modify_incar` 忽略空字符串/None/仅空白值，"上传远端"链路也先过滤空值——把 NCORE 之类的框清空不会再生成 `NCORE = `（已存在的行不会被删，见 §6.5）。⑤ **INCAR 默认参数新增 `IVDW`（默认 11 = DFT-D3(BJ)）**：`src/data/mock/incar.ts`（枚举选项 + 默认值）与 `data/config/task_registry.json` / `backend/defaults/task_registry.json`（四种任务类型的 default_incar）同步。⑥ 实测（隔离数据目录 + `VASP_SSH_MOCK=1`，测完删除）：只建组的项目创建成功；自由能 PATH1 × 2 个结构 → 4 个任务（2 opt + 2 frac，frac.parent=同结构 opt）、NEB NC1 × 5 映像 → 3 个任务、生成的 INCAR 含 `IVDW = 11`；`modify_incar({NCORE: ""})` 不再写入空参数。
- v0.8.0（commit `93f2138`，已推送 origin/main）：**报告排版重构 + 当量/核时工期 + 巡检提速 + INCAR 精度检查**（五件事一起发版）。① **报告页排版重构**（用户："改得一塌糊涂，按你的想法重排"）：报告列表 340→268px、目录从左侧竖排改成顶部胶囊 chips、正文栏 728→950px（最大 1080 居中）；**所有图表统一 1000px 宽**（opt 面板 = 三视图 438 + 曲线 538、自由能/NEB 看板、进度条、NEB 映像矩阵按列均分），页面按 ~0.95 等比展示，字号终于一致；每个任务变成「左侧蓝竖条任务标题 + 一行灰色关键数据 + 图 + 表」的块，块间保留分隔线；基本信息 5 条字段改成两列信息卡；表格加斑马纹、数值列右对齐等宽数字；异常项/建议改左侧色条行；**图片从 `loading="lazy"` 改为 eager + 异步解码**（懒加载会让报告页十几张图不加载）；导出 HTML 的 CSS 同步（h2 竖条 / h5 任务标题 / 表格 / hr / figure）。② **报告工作量与工期按当量折算**（用户口径）：1 当量 = 600 核时、有效算力 = 200 核 × 24h × 70% = 3,360 核时/天；主进度 = 完成当量 / 总当量，**预计完成 = 今天 + 剩余核时 ÷ 有效算力**；落地在 `report_builder._workload_plan()` → `basic_info.workload` / `progress.workload`，进度图多两行说明、报告头 meta 直接显示（Ag 实测：87 当量 = 52,200 核时，已完成 31,800 / 剩余 20,400 → 还需 6.1 天）。③ **已关闭项目的报告折叠成一块**（与总览/巡检/作业管理一致）：列表底部「已关闭项目（N）」胶囊默认折叠，展开后组名灰显 + 「已关闭」标签；默认选中第一个未关闭项目的报告；搜索过滤掉全部已关闭项时整块隐藏。④ **巡检提速**（详见 §6.8 性能条）：bjobs 从每任务 2-3 次子进程降到每轮 2-3 次（cwd 全量表 + `bjobs -l id1 id2 …` 批量明细），OUTCAR 不再整文件读（`resolve_latest_output` 尾部 8KB + 分块计数带 cap；NEB 每映像合并成一次 `_scan_outcar`）；实测 45 任务场景 115→3 次调用、24.8s→1.3s，**输出逐字段完全一致**。⑤ **INCAR 读取 + 精度检查 + 低精度收敛**（思路 A，零额外 SSH）：远端顺手读 INCAR/KPOINTS/POSCAR 回传快照；**结构优化的力收敛阈值改由 INCAR 的 EDIFFG 决定**（RMS 取一半，-0.02 时与旧行为相同，缺失/正值退回 registry）；新增「精度检查」——k 网格密度系数 > 20、EDIFFG ≤ -0.02、EDIFF ≤ 1E-5（要求写在 `check_registry.json` 的 `precision` 段），任一项不满足判定为**低精度收敛**（归档状态 `low_precision`，巡检列表 warning 色显示「低精度收敛」，数据库状态仍写 `completed` 以免影响进度口径，报告「异常与关注项」列为 medium）。⑥ 文档：把「Python 正交投影三视图效果差 → 后续改用 ASE + POV-Ray」登记进 TODO.md §10 / process.md §9 / DEPENDENCIES.md §3a（POV-Ray 是外部二进制，接入时必须可降级）。
- v0.7.4（commit `2b24330`，已推送 origin/main）：**报告里不同任务之间加分隔线**。结构优化 / 自由能路径 / NEB 三节现在都是「一个任务一个区块」，区块之间插入 Markdown `---`（渲染成 `<hr>`，前端 `.report-markdown hr` 与导出 HTML 的 `hr` 都是浅虚线 + 20-22px 上下留白），首尾不加；实测 Ag 报告 9 条分隔线（3 个 opt 之间 2 条 + 3 条自由能路径之间 2 条 + 6 个 NEB 组之间 5 条），前端与导出 HTML 都是 9 条。
- v0.7.3（commit `6a099a2`，已推送 origin/main）：**报告看板与巡检详情页同版式 + 结构优化口径修正**。① 新增 `backend/report_panels.py`：把「统计卡 + 图例 + 图」的看板版式按前端巡检详情页（`PathStepChart` / `NebBarrierPanel` / `.fe-*`）的几何、配色、字号原样实现成纯 Python SVG——自由能路径看板（中间体数量 / 矫正项完成度 / 结构优化收敛 / 最高相对能 + 相对能台阶图，青=收敛且已矫正、琥珀=未收敛或未矫正、灰虚线=无数据，台阶间虚线连接、下方结构 chip）、NEB 能垒看板（映像数量 / 能垒 Ea / 最大受力 / 末态相对能 + 紫渐变面积能垒曲线，鞍点红虚线 + Ea 药丸标注、端点/中间点半径区分、映像轴标签）。② **项目进度改为分块长条**（`segmented_progress_chart`，1040px 宽）：块宽 = 该任务类型的**当量占比**（`task_registry.workload_weight`：结构优化 1 · 频率矫正 1 · NEB 5 · 电子结构 0.4），块内按该类型自身完成比例填充，另给一条**当量加权主进度**大数字 + 主进度条，下方图例逐类型列出「完成数 / 百分比 / 当量（占整体 %）」；`basic_info.progress_segments` 与 `basic_info.weighted_progress_percent` 同步写入结构化数据。③ **结构优化章节口径修正**：只统计**独立结构优化任务**（`group_type` 既不是 free_energy 也不是 neb），自由能路径的中间体与 NEB 初/末态优化一律不在该章节出现——Ag 项目从错误的「28 个」回到真实的 **3 个**（Ag@Al2O3 / Ag24@Al2O3 / Ag111）。④ 自由能 `converged` 改用巡检结果 `force_converged`（归档任务也保留该结果），不再因为「已关闭」被误判为未收敛；Markdown 表格改为与详情页一致的列（中间体 / DFT 能量 / 矫正项 / 自由能 / 相对 ΔE / 状态），NEB 增加映像明细表（相对能垒 / 绝对能量 / 最大受力 / 角色）。⑤ 删除 `report_charts.py` 里被取代的旧 `step_chart` / `neb_barrier_chart` / `progress_bar_percent`（避免「报告和详情页各画一套」）。⑥ 实测：Ag 报告图表 24 张、生成 4-6s；三个项目（Ag / Co / TMDZYX）批量生成 4.1s，Co 的四类型分段进度（结构优化 7.2% · 自由能 58% · NEB 33.8% · 电子结构 1%）与 TMDZYX 的单类型满宽进度均正确。
- v0.7.2（commit `15cb551`，已推送 origin/main）：**报告 11 项修正**。① **去掉附录章节**——`REPORT_SECTIONS` 只剩 `basic_info / science / issues / actions` 四章，附录数据仍留在 `report.json` 里供大模型消费，只是不再作为正文章节（正文里"其余见附录"改为"其余仅保留在报告数据中"）。② **opt 任务三视图与能量/力曲线横向排版成一张图**——新增 `report_charts.task_panel(views_svg, curve_svg)`：左侧 a/b/c 三视图（3×150px）+ 右侧双轴曲线（620×260px）拼成同一张 SVG，共用同一基线、上下对齐，正文每个任务只出一张 `*_panel.svg`（无 CIF 时退回 `*_energy_force.svg`）。③ **修掉项目进度图不显示**——`_sections_markdown` 里误写成 `charts.get('progress.svg')`，而 `charts` 是 `{文件名: SVG 文本}` 字典，取到的是整段 SVG 源码，图片 `src` 就变成 SVG 文本；改为固定路径 `charts/progress.svg`。④ **修掉自由能台阶图没数据**——`step_chart` 读 `free_energy` 而报告结构里字段叫 `free_energy_ev`（NEB 同理：`neb_barrier_chart` 读 `relative`、结构里是 `relative_energy_ev`），在调用处做键映射后 3 张台阶图与 6 张能垒图全部有数据。⑤ **能量与力曲线按巡检 `LineChart` 风格重画并合并**——同边距（66/62/24/34）、`#E7ECF3` 网格、`#9CA3AF` 坐标轴、`#374151` 标题 13px、`#6B7A90` 刻度 10px、蓝色 `#5B8DEF` 能量 + 橙色 `#E8A33D` 力 + 红色 `#D9535B` 力阈值虚线（标注"阈值 0.020"）、旋转纵轴单位、底部"离子步"、图内标注最终能量/最终力。⑥ **前端只显示图片**——删掉 v0.7.1 加的交互式 `Structure3DViewer` / `NebImages3DViewer` 折叠区块与 `interactiveStructures`，报告页只剩 Markdown 里的静态 SVG。⑦ **去掉 Markdown / 结构化数据切换**——删 `Segmented` / `viewMode` / 结构化 `<pre>` / 下载 JSON / 复制 JSON 按钮。⑧ **导出范围改为点击后展开**（Popover 挂在「报告内容」标题行的 `extra` 里，不再常驻显示勾选项）。⑨ **同项目新报告直接覆盖旧报告**——`report_id` 稳定化为 `rpt_<project_id>`，`report_store.save_report` 同项目下 `shutil.rmtree` 旧目录并只保留索引一条，报告列表标题改为「项目报告」。⑩ 实测：正文 Markdown 约 5.3KB、章节 `['basic_info','science','issues','actions']`、Ag 报告 3.8–7.1s 生成、按 `sections=science,actions` 导出的 HTML 确认不含基本信息与异常章节。⑪ 待向用户澄清：`public/3dmol/3Dmol-min.js` 是**浏览器端 JS 库**，Python 后端没有 3Dmol，静态三视图是纯 Python 正交投影 SVG；要做真实静态 3D 渲染得引入 headless 浏览器（用户此前明确不加依赖）。

- v0.7.1（commit `dc21220`，已推送 origin/main）：**报告改为「以总结为核心」+ 每天自动生成**。① 章节精简为 5 章：**基本信息**（项目 / 生成时间 / 整体状态色标 / 进度条 + 一句话任务概览）/ **重点科学结果分析**（opt 每任务：结构三视图 + **能量与最大力同图（双纵轴，力带 0.02 阈值线）** + 一行关键数据；自由能按路径：台阶图 + 中间体表（含 ZPE 矫正列）；NEB 按组：能垒图 + **映像结构对比矩阵**（行 a-b/b-c/a-c，列 IS→FS）；电子结构占位说明）/ **异常与关注项**（模板生成，最多 6 条，含建议）/ **下一步建议**（最多 5 条）/ **附录**（任务清单 + 生成参数）。正文 Markdown 从约 25KB 降到 **8KB**（结构优化任务上限 6 个，其余只进附录），其余数据（tasks/resources/risks/llm_context）仍保留在结构化数据里供大模型消费。② 新增图表：`energy_force_chart`（双纵轴）、`structure_views`（纯 Python 正交投影三视图，元素着色 + 晶胞框）、`structure_matrix`（NEB 映像矩阵）、`progress_bar_percent`。③ **每天自动生成**：复用巡检调度线程，新增 `auto_report_enabled`（默认开）+ `report_interval_hours`（默认 24），到期为每个项目各生成一份报告（单项目失败不影响其他）；`/api/inspections/meta` 的 scheduler 字段新增 `report_enabled / report_interval_hours / report_running / last_report_at / next_report_at`，`PUT /api/inspections/auto` 可改这两项。④ 前端报告页在「重点科学结果分析」上方提供**交互式结构视图**（opt 用 3Dmol 的 Structure3DViewer、NEB 用映像对比 NebImages3DViewer，折叠展开）；导出 HTML/PDF 仍用静态三视图与对比矩阵。

- v0.7.0（commit `d8bfb75`，已推送 origin/main）：**智能报告模块重构——分项目报告生成**（后端 7 个新文件 + 前端报告页重写）。① 报告产物三件套：`report.json`（结构化数据，schema 1.0.0，字段/枚举/单位/时间格式统一，可直接作为大模型输入）+ `report.md`（章节与结构化字段一一对应的 Markdown）+ `charts/*.svg`；按项目分目录存 `data/reports/<项目>/<报告ID>/`，索引 `data/reports/index.json`（原子写 + 锁）。② 11 个章节：元数据 / 执行摘要 / 进度总览 / 任务状态详情 / 科学结果分析 / 巡检与异常 / 资源与集群 / 风险分析 / 行动清单 / 大模型上下文 / 附录。③ **图表纯 Python 生成 SVG**（`report_charts.py`，零依赖；本机无 matplotlib 且不引入）：能量-离子步、力-离子步（含 0.02 阈值线）、自由能台阶、NEB 能垒、核数圆环、存储进度条；数值同时以数组写入结构化数据（图片与数据分离）。④ **风险规则外置**（`report_rules.py` + `defaults/report_rules.json`，可覆盖到 `data/config/`）：声明式 `when`（all/any + field/op/value）+ 严重程度 + 建议模板，13 条规则；`closed` 闸门避免已关闭项目误报逾期/队列。⑤ 接口挂在 `/api/reports/project/...`（避免与既有 `/api/reports/groups` 冲突）：schema / generate（单个或 `all=true` 批量）/ list / detail / structured / markdown / **export.html（按 `sections` 勾选范围导出，图表内联成自包含 HTML，`print=1` 直接调起打印→另存 PDF）** / files/{name} / DELETE。⑥ 前端报告页重写：项目下拉 + 生成报告 + 一键生成所有项目、报告历史按项目分组、章节导航、**导出范围勾选**、Markdown/结构化数据视图切换、下载 MD/JSON/复制 JSON、导出 HTML/PDF。⑦ 统计口径修正：完成率分母为**未关闭任务**，已关闭（归档）任务单独计数且不参与风险判定；全归档项目完成度记 100%。⑧ 实测：Ag 报告 5.2s 生成（要求 <15s）、27 张图、10 条风险；按 `sections=risks,actions` 导出的 HTML 只含这两章（5.6KB），全量导出 103KB 且含 25 个内联 SVG。

- v0.6.14（commit `29c329f`，已推送 origin/main）：**NEB 映像视图只保留一个滑杆**。按需求收敛控制项：① 界面只留「**原子缩放**」滑杆（默认 0.35、范围 0.15–0.85）；② **画面整体倍率改为固定 2.5**（常量 `VIEW_ZOOM`，不暴露控制），初始渲染 `zoomTo()` 自适应后 `zoom(2.5)`，「重置视角」也按 0.35 + 2.5 复位；③ 删除 v0.6.13 新增的「画面缩放」滑杆及其状态与副作用。实测：控件为 球棍/空间填充 + 原子缩放 + 自动旋转 + 重置视角；五个映像面板在倍率 2.5 下渲染面积约 15KB（对比 1.35 时约 8KB），面板头部 34px、画布 y 坐标一致、仍为单行横排。

- v0.6.13（commit `aaa5d64`，已推送 origin/main）：**区分「画面缩放」与「原子尺寸」**。v0.6.11 把用户说的「整体缩放倍率」误当成原子球大小做了（0.35 → 0.5），本次更正：① 原子尺寸恢复默认 **0.35**、滑杆范围回到 0.15–0.85；② 新增独立的**画面缩放**滑杆（相机倍率，默认 **1.35**、范围 0.6–2.2），初始渲染即 `zoomTo()` 自适应后再 `zoom(1.35)`；倍率变化时先 `zoomTo()` 归零再按倍率拉近，避免倍数叠加；「重置视角」把倍率复位到 1.35 并对所有面板重新取景。实测同一批映像在倍率 0.6 / 1.35 / 2.2 下的渲染面积单调变化（面板截图 4.7KB / 8.0KB / 13KB），原子大小保持不变。

- v0.6.12（commit `3bad80d`，已推送 origin/main）：**NEB 映像面板对齐 + 恒定横排**。① 面板头部原来把「映像号 + 角色徽标 + ΔE + 最大受力」挤在一行，宽度不足时**部分面板换行成两行**（实测 01/02 头部 56px、其余 38px），导致各面板 3D 画布起点差 18px、看着错位并出现多余白边。修法：头部固定 `height: 34px` + `flex-wrap: nowrap`，ΔE / 最大受力移到画布**下方固定的 26px 页脚**，面板改 `display:flex; column` 保证结构一致（实测五个面板头部均为 34px、画布 y 坐标完全相同）。② 网格由 `repeat(auto-fit, minmax(160px,1fr))` 改为 `grid-auto-flow: column; grid-auto-columns: minmax(190px,1fr)` + `overflow-x: auto`：**整条路径恒定一排**，宽度不够时横向滚动，不再换行打断 IS→中间态→FS 的对比（实测 1500/1280/1100/900px 下始终 1 行，900px 时横向滚动）。

- v0.6.11（commit `330708f`，已推送 origin/main）：**NEB 映像 3D 视图初始放大倍率调高**。`NebImages3DViewer` 的原子尺寸默认值 0.35 → **0.5**，缩放滑杆范围放宽到 0.25–1.0（原先上限 0.85 偏紧）；`zoomTo()` 之后再调一次 `viewer.zoom(1.15)` 把相机拉近 15%（3Dmol 的 `zoom(k)` 即 k 倍，>1 为拉近）。实测 5 个映像面板的渲染面积整体增加约 15–17%，画布仍限制在各自面板内。

- v0.6.10（commit `7f41aa3`，已推送 origin/main）：**修复 v0.6.9 引入的两个前端缺陷**。① **部分 NEB 任务点开详情白屏**：v0.6.9 给 NEB 返回了专属 `analysis`（只有 `neb_images` / `steps` / `skipped`），但详情抽屉的渲染分支在"没有 `neb_images`"时会落到 `StructurePanel`，而后者会访问 `analysis.warnings.map()` / `analysis.files.poscar` → 未定义字段抛错 → React 整页白屏。修法：`Inspection.tsx` 里 NEB **单独分支**（有映像 → 映像视图；无映像 → 带说明的 Empty 占位，文案取 `analysis.skipped`），永不再落到 `StructurePanel`；同时给 `StructurePanel` 加 `(analysis.warnings ?? [])` 与 `analysis.files?.poscar` 兜底。② **左上角一块白色遮挡 / 3D 显示异常**：3Dmol 会在容器内插入**绝对定位**的 canvas，而新增的 `.neb3d__canvas` 没有定位上下文，画布相对页面定位跑到左上角形成白色遮挡。修法：`.neb3d__canvas` 加 `position: relative; overflow: hidden`（与 opt 的 `.s3d-canvas` 一致）。③ 顺带加固 `NebImages3DViewer`：`window.$3Dmol` 缺失时给降级提示而不是抛错、单个映像渲染失败只 `console.warn` 不影响其他映像、创建后补 `viewer.resize()`。

- v0.6.9（commit `b0e37c8`，已推送 origin/main）：**NEB 映像结构分析**（对应 opt 的结构 3D 对比）。① 触发条件与 opt 相同：25 离子步一桶 + 目录变化重置；NEB 的「步数」取**中间映像 OUTCAR 的 TOTAL-FORCE 块最大值**（VTST 各映像同步推进，端点伪结果不计入），由 batch_check 新增 `neb_band_steps` 回传——**运行中的 NEB 也会统计**（此前只有作业结束走 `_analyze_neb_status` 才有数，导致运行期永远拿不到步数）。② 同步：`inspection_runner._sync_neb_image_structures()` 用**单次远端 bash 脚本**把各映像结构 base64 回传（避免 N 次 SSH 往返），每个映像取 CONTCAR（优化后几何）、缺失时退回 POSCAR；原始文件写 `files/neb_images/<label>`，CIF 写 `reports/structure/images/<label>.cif`（覆盖旧结果、失败保留旧文件）。③ 详情接口新增 `analysis.neb_images`（label / role（is|middle|fs）/ CIF 文本 / 相对能垒 / 最大受力），标签按数值归一化与 nebef.pl 的 0..N 对齐（目录名是 00/01…，nebef 是 0/1…）。④ 前端新增 `NebImages3DViewer`：IS → 中间态 → FS **横向 3D 对比**，拖动/滚轮联动所有面板视角、球棍/空间填充、自动旋转、缩放、重置视角、元素配色图例，**鞍点面板高亮边框**，每格显示 ΔE 与最大受力；NEB 详情弹窗自动加宽到 1200px 以容纳整条路径。⑤ 实现过程中修掉两个坑：`inspection_runner` 漏 `import base64`（NameError 被 except 吞成「解码失败」）、`routers/inspections.py` 用 `Any` 未导入（详情接口 500）。

- v0.6.8（commit `b6653fd`，已推送 origin/main）：**NEB 能垒看板视觉/动画重做**（新增 `NebBarrierPanel`，替换原「通用折线图 + antd 表格」拼版，样式复用 `.fe-*` 版式）。① 顶部四张统计卡：映像数量（端点 2 + 中间 N-2）、能垒 Ea（最高相对能 + 对应映像）、最大受力（含映像号）、末态相对能（判断反应是否回到初态）。② 能垒曲线：相对能垒直线连接（**不做插值**，如实反映各映像）、渐变面积、鞍点红色虚线 + Ea = +x.xxx eV 标注、端点/鞍点数据点区分大小与配色；悬停出竖线 + 放大点 + 信息卡（映像号 + 初态/末态/鞍点角色 + 相对能垒/绝对能量/最大受力）。③ 明细列表改为自绘行（映像 chip / 相对能垒 / 绝对能量 / 受力（最大受力行橙色）/ 角色徽标），悬停行与曲线联动高亮。④ 动画：曲线从左向右绘制（pathLength 归一化 + dashoffset）、数据点依次弹出、面积与鞍点标注随后淡入、列表行错峰上浮；`prefers-reduced-motion` 下全部关闭。⑤ 删除已无用的 `.neb-barrier-layout` 样式。


> 版本号说明：v0.5.5 的代码提交是 `60e995d`（+ `292d5fc` 文档补 commit 号），其 commit message 前缀当时写作 v0.5.1，随后统一为 v0.5.5；查历史时按 commit 号找，不要按版本号找。

- v0.6.7（commit `bd9e7bb`，已推送 origin/main）：**自由能路径看板视觉与动画重做**（`PathSummaryModal` + `PathStepChart` 重写，样式见 global.css 的 `.fe-*`）。① 顶部新增四张统计卡：中间体数量、矫正项完成度（N/M）、结构优化收敛（N/M）、最高相对能（含对应结构）。② 台阶图纵轴改为**相对自由能**（ΔE = E − E参考，参考取第一个有数据的中间体），保留绝对能量显示在 tooltip 与列表；台阶带渐变柱体 + 向下渐变面积 + 状态点（未收敛/未矫正时琥珀色 + 圆点），缺数据显示灰色虚线"无数据"。③ 交互：悬停台阶上浮 3px + 柱体加粗发光 + 跟随鼠标的信息卡（自由能 / 相对 ΔE / DFT / 矫正项 / 状态 / "点击查看巡检详情"），点击台阶或列表行打开该结构巡检详情。④ 动画：台阶按顺序从左滑入（80ms 错峰）、连接线淡入、数值与结构标签依次出现，列表行错峰上浮；`prefers-reduced-motion` 下全部禁用。⑤ 明细表改为自绘列表（中间体 chip / DFT / 矫正项（正负着色）/ 自由能 / 相对 ΔE / 收敛·矫正徽标 / 跳转箭头），窄屏自动重排。⑥ **后端语义修复**：`/api/free-energy/{gid}/summary` 的 `converged` 改为「`completed`，或 `archived` 且 `archived_from == completed`」——否则归档后的路径会被整片渲染成"未收敛"琥珀色（与 v0.6.4/v0.6.5 的归档功能叠加后才暴露）。
- v0.6.6（commit `965a8b0`，已推送 origin/main）：**巡检列表排序规则**（前端 `Inspection.tsx` 的 `filtered` 排序键）。① 状态优先级进入排序：`错误 > 警告 > 待提交（未检）> 正常 > 关闭`。② 自由能 / NEB **同组作为一个排序单元**，取组内**最高优先级状态**整体参与排序（组员恒定相邻）；整组归档的单元沉到其他任务下面（"归档任务放在其他任务下面"）。③ 原有规则保持不变，作为后续 tie-break：任务类别（结构优化→自由能→NEB→电子结构）→ 组名自然序（PATH1 < PATH2 < PATH10）→ 组内结构顺序（自由能 1..N、NEB IS→FS→neb）→ 任务名；组内被归档的成员沉到**该组末尾**（不破坏组相邻）。④ 实现中修掉两个自测发现的坑：排序单元键最初用 `项目|组名`，但同项目下自由能组与 NEB 组可能同名（Ag 都有 PATH1/2/3），导致跨类别串组、组权重算错 → 键改为 `项目|类别|组名`；"组内归档成员沉底"最初放在组键之前，会把归档成员挤到别的组后面（NEB 的 NC 组被拆开）→ 移到组键之后。
- v0.6.5（commit `1da2de6`，已推送 origin/main）：**归档状态与巡检的关系修正**。① **归档任务禁止巡检**：`inspection_runner._plan_batches()` 单任务分支遇到 `archived` 任务抛 ValueError → 接口 400「任务已关闭（归档），请先重新打开再巡检」，杜绝"单独巡检把归档状态覆盖回 completed/zombied"（此前是线上实际发生的问题）。② **巡检列表显示「关闭」**：`CheckStatus` 新增 `archived`（`CHECK_STATUS_LABELS.archived = '关闭'`，CSS 用既有 `.status-tag--archived`），归档任务在列表状态列显示"关闭"、信息列"任务已关闭（归档）"，不再按"未检/待提交"呈现，也不计入项目块头部「未检」计数（改为单独统计「关闭 N」）；状态列筛选新增"关闭"选项。③ 归档行的「单独巡检」按钮置灰（列表与详情弹窗都加，带提示），已归档任务仍可查看详情。④ `mappers` 暴露 `archived_from` / `archived_at`，前端"重新打开"弹窗能显示真实恢复目标（此前恒显示"待提交"）。⑤ **运维教训归档**：v0.6.4 的归档连带在真机上"没生效"，原因是 3001 上的后端进程还是 01:30 启动的旧代码（改后端不重启 = 页面行为不变），已在 §8 强化说明。
- v0.6.4（commit `3921566`，已推送 origin/main）：**自由能主任务归档连带频率矫正**。① 后端 `task_paths.free_energy_frac_task()` 按 `<结构目录>/frac` 约定（并校验 `parent_task_id`）定位 frac 子任务；`POST /jobs/tasks/{id}/archive` 归档自由能 opt 时**连带归档 frac**，`/unarchive` 连带恢复（各回各自的 `archived_from`），响应新增 `frac_status` / `archived_siblings` / `reopened_siblings`；对"主任务已归档但 frac 未归档"的历史状态，重复调用 archive 也会把 frac 补齐（幂等修复，不再直接 409）。② `mappers` 为自由能 opt 任务输出 `frac_sibling{task_id,model_name,status}`。③ 前端（作业管理任务面板 + 巡检详情弹窗）归档确认文案按 frac 状态区分：**未完成（非 completed）时加 ⚠️ 警告**"该任务的频率矫正（xxx）当前为「未收敛」，尚未正常结束；关闭主任务会一并归档它"，成功提示与"重新打开"提示也写明连带关系。④ 新增 `scripts/repair_frac_archive.py`：一次性修复历史"主任务已归档、frac 未归档"的数据（默认 dry-run，`--apply` 才写入，写入走事务并自动备份）。
- v0.6.3（commit `fab6139`，已推送 origin/main）：**归档入口补齐 + 关闭项目展示细化**。① **巡检详情弹窗 footer 新增「关闭（归档）」**（已归档任务显示「重新打开」）：未正常结束的任务同样弹窗警告（写明当前状态、说明"关闭后不再参与全局巡检"），关闭后自动关闭弹窗并刷新列表；重新打开会重拉详情。② **作业管理已关闭项目默认折叠**：`JobsTree` 从 `defaultExpandAll` 改为受控 `expandedKeys`，初始集合排除已关闭项目及其子树（新建/归档/关闭后重置为该规则），用户仍可手动展开。③ **总览「已关闭项目」样式重做**：原来只有裸按钮 + 默认样式（看起来与卡片风格不一致），现在改为虚线分隔 + 胶囊按钮（圆角 999px、浅底、hover 变蓝）+ 列表项带灰色进度条与「另 N 个续算目录」说明。

- v0.6.2（commit `2c04a1e`，已推送 origin/main）：**巡检链路加固 + 任务归档/项目关闭 + 定时调度**。① `submit` 改走 `db_transaction`，消除"提交后又被巡检回填覆盖"的竞态（[jobs.py](backend/routers/jobs.py)）。② 全局巡检改为**按项目分批**：`_plan_batches()` 规划批次，脚本/阈值每服务器每轮只上传一次，远端检查在事务外、每项目独立事务回填归档——单项目失败不再整轮回滚（摘要新增 `failed_batches`），数据库写锁从 75-90s 缩到单项目回填的几秒。③ 新增 `inspection_scheduler.py`：后台线程每 60s 判定，开关 + 间隔（默认 2h）→ 自动跑全局巡检；`PUT /api/inspections/auto` 切换，`GET /inspections/meta` 返回调度器实时状态（running / last / next / error）。④ 每次全局巡检成功后 `dashboard.invalidate_cluster_cache(prewarm=True)` 静默作废并预热集群快照。⑤ **任务归档**：`POST /jobs/tasks/{id}/archive`（未强制要求 completed，前端弹窗提醒）、`/unarchive` 恢复 `archived_from`；`archived` 状态终于接入 UI（此前枚举里有、无处写入）。⑥ **项目关闭**：`POST /projects/{id}/close`（要求该项目可见任务全部归档）与 `/reopen`；`mappers` 输出 `closed/closedAt`。⑦ 前端：巡检中心表格改为**按项目分块**（项目内保持自由能/NEB 组顺序，关闭项目排最后、默认折叠、灰显）并加入自动巡检开关与调度状态；总览项目进度把已关闭项目收进「已关闭项目」折叠区并支持关闭/重新打开；作业管理任务快捷操作新增「关闭（归档）/重新打开」、已关闭项目在树中排最后且灰显（不提供新建入口）；`vite.config.ts` 支持 `VITE_API_TARGET` 覆盖后端地址（便于隔离测试）。

- v0.6.1（commit `9773b35`，已推送 origin/main）：**巡检列表未巡检行文案修正**。① 未巡检（无归档记录）的合成行，信息列由「待提交」改为 **「未检」**，detail 由「任务待提交，暂无运行输出」改为「暂无巡检记录，可点击「单独巡检」获取该任务当前状态」——原文案把「没有巡检记录」误述成任务状态，容易和任务本身的「待提交」混淆（**状态列仍是待提交/灰色，本次不改**）。② 修掉两处按钮的英文残留 `check` → **「单独巡检」**（列表未巡检行的操作按钮 + 巡检详情弹窗 footer 按钮，与 TODO/本文档既有描述一致）。③ 前端点击未巡检行的提示语同步改为「该任务暂无巡检记录，请先用「单独巡检」获取当前状态」。

- v0.6.0（commit `8b9d629`，已推送 origin/main）：**总览模块重构与扩展**。① 后端新增 `backend/dashboard.py` + `routers/dashboard.py`：单次 SSH 合并查询（bjobs/blimits/df/bhosts/bqueues，`@@@` 分段解析）、5 分钟缓存（可配）、集群采样历史 `data/dashboard/core_history.json`、作业↔任务映射（job_id 优先、作业名回退）、核数按项目聚合、风险预警（未收敛/Zombie/巡检异常）、项目进度与近 7 天趋势；新增接口 `/api/dashboard/overview|cores-usage|cluster-health|risk-alerts|trend`（`?refresh=1` 强制刷新）。② 前端重写总览页：顶部状态栏（可点击跳巡检/展开运行任务）+ 快捷操作（新建项目/触发全局巡检/刷新集群状态）+ 运行中任务表（点行跳 `/jobs?task=`）+ ECharts 核数圆环（按项目着色、90% 橙 / 100% 红闪烁）+ 集群健康（节点灯/队列拥堵/存储告警）+ 风险预警 + 项目四象限气泡 + 最近任务明细；引入 **echarts 6.1.0（按需注册，独立 vendor chunk）**、`useCountUp` 数字滚动、30 分钟自动刷新。③ 修掉 4 个原有总览问题：逾期项目显示「已完成」、进度分母含隐藏续算目录、删除按钮换行破版（网格 4 列 5 元素）、趋势图 MOCK 假数据。④ 清理死代码：`TrendChart.tsx`、`src/data/mock/projects.ts`、`fetchDashboardMeta/fetchWeeklyTrend`。⑤ 配置：`servers.json` 新增 5 个可覆盖查询命令，`settings.json` 新增 `dashboard_cache_seconds`。

- v0.5.5（commit `60e995d`，已推送 origin/main）：① **NEB 续算活跃作业保护**——NEB 续算脚本补齐与 opt 一致的 `bjobs` 检查，运行中作业只回传 `action="running"`，不建 conN、不移动 WAVECAR（此前 NEB 路径无拦截，运行中任务可能被搬走 WAVECAR）。② NEB 续算各映像（含端点 00/NN 与中间态）存在 WAVECAR 时随续算 `mv` 移动（目标已有不覆盖），与 opt 语义一致。③ `modify_incar` 清理源文本头部空行（兼容 LF/CRLF/纯空白行；续算标记切片曾带入前导换行）。④ `_script_slice` 跳过标记行后的换行，修复 `===FILES===` 解析出空字符串首项。⑤ `GET /api/health` 的 `uptime` 改为后端进程运行秒数并新增 `startedAt`（原实现返回 `time.monotonic()`，在 Windows 上是**系统开机时长**，易误判后端是否已重启）。⑥ 文档：登记 TMDZYX 项目，明确交接文档由助手维护。

- v0.5.0（commit `6d6b78a`，已推送）：① **结构 3D 化**——结构分析触发条件改为「离子步每 25 步一桶 + 目录变化重置」（§6.2b）；新增 `scripts/vasp2cif.py`（经典 vasp2cif Python 3 移植，零第三方依赖）+ `backend/cif_convert.py`（原子写入：有 CIF 用 CIF、缺 CIF 现场转、失败保留旧结果）；详情接口返回 `poscar_cif/contcar_cif`（vesta_render 停用）；前端 Structure3DViewer + structure3d.ts + public/3dmol/3Dmol-min.js（backend/main.py 挂载 `/3dmol`），StructurePanel 以 3Dmol 结构视图替代 VESTA 三轴 PNG。② NEB 续算端点 OUTCAR 复制修复（find 仅匹配纯数字目录）。③ 组创建/加结构/独立任务改用服务器 remote_root 拼项目名（不再信任旧 remote_base）。④ 巡检列表 NEB 组按「项目+组名」自然排序相邻、组内 IS→FS→neb。⑤ SSH 保活延迟回传（后台 60s 保活实测延迟，`/api/ssh/status` 增 `latencyMs/latencyAt`，顶栏/SSH 页实时刷新）。⑥ 新增 DEPENDENCIES.md 依赖文档。数据侧修复（data/ 已 gitignore，不入库）：Ag_20260830.remote_base 已改回 HS 根、误建 test 下 PATH1_TS2 已删（本地移入 data/trash）、Ag PATH2/neb con6 已手动补 04/OUTCAR。
- v0.4.5（commit `02c167c`，已推送）：续算合并单脚本 + 连接池化上传/下载/建目录（opt/NEB 10-15s→3.5s）；巡检修复（作业停止感知——bjobs 折行解析、NEB 按映像 OUTCAR 判定、运行中回传 last_energy）；NEB 创建文件以 IS INCAR 为基底、续算带端点 OUTCAR；停止作业 already-finished 按成功；SSH 真实延迟测试接口；INCAR 编辑器（自定义参数/生成到本地/分类分组空行/NFREE 仅 frac/MAGMOM 留空/POTIM 0.2/KPOINTS 纯 ASCII）；默认参数同步 task_registry.json（LWAVE/LCHARG=.FALSE.、NCORE=1、POTIM=0.2）；矫正项可点击重算。
- v0.4.1：详情页分析模块 + 自由能路径看板（台阶图）+ 矫正联动 + 悬停竖线动画。
- v0.3.x：自由能 opt 单任务巡检顺带检查 frac；INCAR 统一修改 + 续算参数规格；NEB 创建流程参数。
- 更早：目录 ASCII 化、路径相对化（v0.5.0 路径规范）、根目录迁移 HS、单任务巡检、续算分流、NEB/自由能组管理。

---

## 8. 已知注意事项 / 坑

- **3Dmol 视图的两个硬性要求**（v0.6.10 踩坑）：① 承载 3Dmol 的容器必须有 `position: relative`（+ `overflow: hidden`），否则画布绝对定位到页面左上角、盖出一块白色遮挡（opt 的 `.s3d-canvas`、NEB 的 `.neb3d__canvas` 都已遵守）；② 给某类任务新增专属 `analysis` 载荷时，**必须同时给它一个独立的渲染分支**——不能让它落到 `StructurePanel`（它按 opt 字段访问 `files/poscar/warnings`，字段缺失会抛错白屏）。新增任务类型分析时请照此处理。
- **后端没有 3Dmol（v0.7.2 澄清）**：`public/3dmol/3Dmol-min.js` 是**浏览器端 JS 库**（WebGL 渲染），Python 后端无法直接用；报告里的静态“三视图”是 `report_charts.structure_views()` 用纯 Python 做的正交投影 SVG。若要做真实静态 3D 渲染（带透视/材质），需要引入 headless 浏览器或 Node 端渲染，属于新增依赖，**动手前先问用户**。
- **报告图表函数的参数键必须与结构化字段名对齐**（v0.7.2 踩坑）：`report_builder.py` 传给 `report_charts` 的字典键必须与图表函数读取的键一致，否则图表静默画出空图（不出数据、不报错）。已修两处：`free_energy_ev`（`step_chart` 原读 `free_energy`）、`relative_energy_ev`（`neb_barrier_chart` 原读 `relative`）。另外 `build_report()` 的 `charts` 是 `{文件名: SVG 文本}` 字典——**引用图片要用 `"charts/<名字>.svg"` 字符串**，不要写成 `charts.get('x.svg')`，否则会把整段 SVG 文本当成路径写进 Markdown。
- **报告看板要与巡检详情页同版式**（v0.7.3）：报告里的自由能台阶图 / NEB 能垒图 / 项目进度都在 `backend/report_panels.py`，几何与配色是照抄前端 `PathStepChart` / `NebBarrierPanel` / `.fe-*` 的常量（`STEP_W/H/M`、`NEB_W/H/M`、`FE_OK/FE_WARN`、`NEB_LINE/NEB_LINE_SOFT/NEB_SADDLE`、`SEGMENT_COLORS`）。**改详情页视觉时同步改这里**，否则又会出现"报告和详情页各画一套"的返工。另外同一份导出 HTML 会内联多张 SVG——所有渐变 `id` 必须用 `_uid()` 加前缀，否则多个图会互相抢渐变定义。
- **报告口径的两个坑**（v0.7.3）：① 「结构优化」章节只能统计**独立** opt 任务（`group.group_type` 既非 `free_energy` 也非 `neb`），否则一条 7 中间体的自由能路径会被算成 7 个结构优化任务（Ag 曾把 28 个中间体/端点误报成结构优化）；② 自由能中间体的 `converged` 要用巡检的 `force_converged`，**不能**用 `status == "completed"`——任务归档（archived）后状态不再是 completed，会整片显示"未收敛"。
- **报告里的"三视图"是临时方案**（2026-09-13 用户确认搁置）：`report_charts.structure_views()` 用纯 Python 做正交投影（元素着色 + 晶胞框），只是"能看"的水平，用户明确反馈效果差。**不要再在这上面投入打磨**——后续统一换成 **ASE + POV-Ray** 后端渲染（见 §9 第 9 条），届时 `structure_views` / `structure_matrix` 一起替换。
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
9. **报告结构图渲染改用 ASE + POV-Ray**（2026-09-13 用户决策，**暂时搁置**）：当前 `report_charts.structure_views()` 是纯 Python 正交投影 SVG，效果差；后续用 ASE 读 POSCAR/CONTCAR/CIF + POV-Ray 渲染高质量结构图，替换报告里的 `structure_views` / `structure_matrix`。依赖 `ase`（pip 可选）+ **POV-Ray 二进制**（非 pip，需单独安装或随包分发），落地时要考虑渲染耗时与按 CIF 哈希缓存。**在换掉之前不要在这套 Python 投影图上继续投入**。

TODO.md 与本节冲突时以本节 + 代码实际状态为准（TODO.md 历史条目较多，部分已过时）。

---

## 10. 新窗口接续清单

1. `git -C /home/zouyuxi/projects/vasp-manager log --oneline -3` 确认在 v0.8.5；`git status` 应干净（有未提交改动时先看 §7 末尾是否为「待提交」事项）。
2. 读 `TODO.md` + `README.md`（SSH 约定章节）+ 本文件。
3. 需要联调时（生产机 Linux）：`sudo systemctl restart vasp-manager` → 打开 `http://192.168.1.20:3001`（前端已构建在 `dist/`）与 `http://192.168.1.20:3001/docs`；改前端记得先 `npm run build`，需要热更新时才另开 `npm run dev`（5173）。部署细节见 §11。
4. 用户对“默认参数 / 目录结构 / 作业号同步 / 巡检状态”等改动很敏感，动手前先确认范围；禁止用运行中的任务做破坏性测试（可用项目树外的临时目录，测完删除）。
5. 提交版本时沿用 commit message 前缀 `v0.x.y: ...`（无 git tag 习惯），改 package.json version 后 `git add -A && git commit && git push origin main`（本机 `git push` 走 `~/.ssh/config` 里的 `github.com → ssh.github.com:443` + `~/.ssh/id_github`，无需额外配置）。
6. 提交完成后：更新本文档 §7（新增版本条目）+ §2（数据现状）+ §9（待办），保持「版本号 / 改动记录 / 待办」三处同步。

---

## 11. 部署与运维（Linux 生产机）

> 2026-09-18 由一次真实迁移落地。原一次性文档 `MIGRATION.md` 的可复用内容已并入本节，该文件已删除。
> 生产机：Ubuntu 26.04（主机名 `ZYX-S`）· 运行用户 `zouyuxi` · 局域网 `192.168.1.20` · ZeroTier `10.147.20.10`

### 11.1 目录与服务

| 项 | 位置 / 值 |
| --- | --- |
| 代码 + 数据 | `/home/zouyuxi/projects/vasp-manager`（git 克隆；`data/` 在仓库内，故 `path_mapping.local_root` 保持相对 `data/projects`） |
| Python 环境 | 仓库内 `.venv`（Python 3.14.4；核心依赖 fastapi / uvicorn[standard] / paramiko 实测可用） |
| 前端产物 | 仓库内 `dist/`（`npm ci && npm run build` 生成，由后端单端口托管） |
| systemd 单元 | `/etc/systemd/system/vasp-manager.service`（`User=zouyuxi`、`WorkingDirectory=<仓库>`、`ExecStart=<仓库>/.venv/bin/python backend/run.py`、`Environment=PYTHONIOENCODING=utf-8` / `TZ=Asia/Shanghai`、`Restart=always`、`enabled`） |
| 访问 | `http://192.168.1.20:3001`（局域网）/ `http://10.147.20.10:3001`（ZeroTier）；`/docs` = Swagger |
| 日志 | `journalctl -u vasp-manager`（原 Windows 的 `*_log.txt` 不再使用） |

```bash
sudo systemctl start|stop|restart vasp-manager
systemctl status vasp-manager --no-pager        # 含 MainPID（启动时报进程号）
sudo journalctl -u vasp-manager -n 100 --no-pager
```

### 11.2 日常操作对照

| 改了什么 | 要做什么 |
| --- | --- |
| 前端 `src/**` | `npm run build`（不用重启后端），浏览器硬刷新 |
| 后端 `backend/*.py` | `sudo systemctl restart vasp-manager` |
| `data/config/*.json` | 重启最稳（部分设置接口即时生效） |
| 仅 `data/` 运行时数据 | 无需重启 |
| 换数据目录 | 用 `--data-dir`，并把 `path_mapping.local_root` 改成**绝对路径** `<数据根>/projects` |

**硬规则**：`data/` 是唯一真相，**同一时刻只能有一个后端在写** —— 起前台进程前先 `systemctl stop`；旧 Windows 机保持停止。

### 11.3 迁移后的常驻检查项（原 MIGRATION.md §6 验收表的长期版本）

1. `/api/health` 返回 `startedAt` = 本次启动时间；
2. `/api/projects` = 4 项目 / 120 可见任务（63 / 34 / 7 / 16）；
3. 顶部「SSH 已连接」+ 总览核数（`blimits`）、节点、队列、存储都有数据；
4. 单任务巡检（选已完成任务）12–15 s 内返回；报告 4 份可读；「同步最新参数」能取回 INCAR/KPOINTS/POSCAR/CONTCAR；
5. 巡检中心调度器显示上次/下次时间（自动巡检默认开、间隔 2h；自动报告默认开、24h）；
6. 时区 `Asia/Shanghai`，服务内 `PYTHONIOENCODING=utf-8`（单元里已设）；
7. `/docs` 可打开。

### 11.4 Linux 特有的坑（都已踩过）

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| NEB 映像只剩中间 3 个、本地文件"看不到" | **Windows 大小写不敏感**：老数据在 `data/projects/Ag_20260830/NEB/`，而 `projects.json` 里三个主 NEB 任务的 `dir_path` 写的是 `neb/`；Linux 上是两个目录，后端在小写路径下新建了空壳 | 已把新文件并回老树并做软链接 `neb → NEB`（两套引用命中同一份数据）。全盘审计确认再无其它大小写分叉；新增目录时留意同层仅大小写不同的名字 |
| apt / npm 报 `Temporary failure resolving …`，而 `dig` 正常 | SecureLink（校园 VPN）数据面 `sl-dp` 把 `/etc/resolv.conf` 改成 `nameserver 127.0.0.1` 自建 DNS 代理，对部分域名解析失败 | 用 `/etc/hosts` 托管段 + `/32` 例外路由 + 15 秒自愈 systemd timer（`codex-net-guard`）挡住；日志 `/var/log/codex-net-guard.log` |
| 连 SecureLink 时后端/面板掉线 | 隧道 `tun0` 抢默认路由并把出站流量导向校园出口（模型后端 `api.deepseek.com` 随之不可达） | 同上（例外路由让后端/Codex 流量始终走物理网卡）；**HPC 操作则需要在 SecureLink 连上时做**（`hpc.xmu.edu.cn` 的路由在 `tun0` 里） |
| 改后端不生效 | 后端无 `--reload` | `sudo systemctl restart vasp-manager` |
| 「打开文件夹」按钮无反应 | 无桌面环境时 `xdg-open` 无效 | 忽略，或用 SFTP/终端查看 |
| `npm run server` 报 `python: command not found` | Linux 只有 `python3` | `package.json` 的 `server` 脚本已改为 `.venv/bin/python backend/run.py` |
| apt 下载极慢 | 默认 `archive.ubuntu.com`/`security.ubuntu.com` 在此网络下慢且偶发解析失败 | 已把 apt 源换成**华为云镜像**（`/etc/apt/sources.list.d/ubuntu.sources`，原文件备份在 `/tmp/ubuntu.sources.orig-backup`）；pip 也可用 `-i https://mirrors.huaweicloud.com/repository/pypi/simple/` |

### 11.5 可选：nginx 反代（80 → 3001）

```nginx
server {
  listen 80;
  server_name _;
  client_max_body_size 200m;        # 上传 POSCAR/INCAR/KPOINTS
  location / {
    proxy_pass http://127.0.0.1:3001;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;        # 巡检/续算接口耗时长
  }
}
```

### 11.6 回滚

1. 数据没动过：直接回旧机跑（旧机保留一份完整 `data/` 副本）；
2. 新机已产生新数据（巡检/报告/续算）而想退回：把整份 `data/` 拷回旧机，**不要只拷 `projects.json`**（`checks/`、`reports/`、`projects/` 是配套的）；
3. 迁移前的自动备份：`data/backups/project_db_*.json`（最近 20 份）+ `data/backups/migration_*/`。
