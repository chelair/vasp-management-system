# 待办清单（TODO）

> 创建时间：2026-08-24
> 适用项目：`vasp-management-system`（v0.8.8）
> 勾选约定：`[ ]` 未开始 · `[x]` 已完成

# 发现问题

> （当前无未处理问题）
> 原「自由能路径和 neb 路径重名时会自动合并」已修复，见「已完成（v0.8.6）」。

## 当前进度概览

**已完成（v0.9.1，2026-09-20 · 项目归属字段与迁移）**

- [x] `projects.json` 每个项目加 `owner` / `created_at`；新建项目自动把 `owner` 写成当前登录用户；`mappers` 输出这两个字段；前端项目树显示归属标签（仅展示，不参与权限判断）
- [x] `scripts/migrate_owners.py`：dry-run 默认 / `--apply` 前带时间戳备份 / 幂等（已有 owner 跳过）/ `--data-dir` 隔离 / owner 不存在时报错；隔离目录 26 项断言 + 前端 4 项断言通过


**已完成（v0.9.0，2026-09-20 · 账号体系 + 登录认证）**

- [x] 账号与会话底座：`backend/auth.py`（scrypt 哈希、token 只存 sha256、`data/users/*.json` 原子写 + 文件锁、首次启动自动建 `zouyuxi` admin）+ `scripts/set_password.py`（列表/建号/改密/禁用/启用/会话/强制下线）
- [x] 认证上线：全局中间件（白名单只有 `POST /api/auth/login`、`GET /api/health`；`/api/**` 与 `/docs`、`/openapi.json` 未登录 401；跳过 OPTIONS；Cookie/query 只对 GET 生效）+ `routers/auth.py` 六个接口（登录限速 5 次/15 分钟、登出、me、长期 token 签发/列出/吊销）+ 滑动续期 14 天
- [x] 前端：登录页（保留 `?from=`）、`client.ts` 自动注入 token 与 401 跳登录、`AuthContext` + 路由守卫、顶栏用户菜单（当前用户/退出）


**已完成（v0.8.9，2026-09-20 · 输入文件面板交互 + 复制/选择 + 电场并行参数）**

- [x] INCAR 待生效修改**逐项撤销**（不再一撤全撤）+ 多条时「全部撤销」；撤销主开关（LDAU / LDIPOL）时整组依赖参数一并撤销（不会留下孤立 +U / 电场参数）；`applyIncarGates` 改为整组置空，修掉"关掉 +U 后旧草稿仍被写入下次续算"
- [x] 刷新页面后表单显示**待生效草稿**（快照 + 草稿基线），并修掉本地 `files/INCAR` 异步读取盖回草稿的竞态
- [x] 「复制 INCAR 参数到其他作业」改为**写入目标任务的服务端草稿**并回填状态（原来只改会话状态、切换任务即被覆盖）
- [x] 任务选择弹窗重做：项目分组折叠 + 搜索 + **已关闭项目折到最后**；INCAR 复制（多选）与 POSCAR 复制（单选）共用 `TaskPickerList` / `TaskPickerModal`，删除 `CopyParamsModal`
- [x] POSCAR 结构视图左上角显示**选中原子分数坐标**（灰色小字，按序号排序、超 8 个折叠）
- [x] 偶极矩修正卡片新增 **EFIELD（单值，eV/Å，方向由 IDIPOL 决定）**，随 LDIPOL 开关联动
- [x] **NCORE 默认留空**（前端默认值 + `data/config/task_registry.json` 四种类型模板都去掉；只影响新建任务）


**已完成（v0.8.8，2026-09-19 · 状态显示修复）**

- [x] 作业管理显示巡检告警：`/api/projects` 每个任务带 `check{status,message,checked_at}`（与巡检中心同文案），任务树加 ⚠/⛔ 图标（**悬停图标本身**才弹结论，任务名的 tooltip 不含巡检文案）、作业概览「最近巡检」行显示状态标签+完整结论（低精度收敛/力未收敛等）；`checks_store` 加 30s 结果缓存并在巡检后失效，避免每次请求全量读 checks
- [x] 创建续算后 INCAR/KPOINTS 同步状态立即刷新（续算成功后再读一次父任务输入状态，不再需要刷新页面）
- [x] 任务树自由能结构节点/组节点、NEB 组节点显示"最高优先级"状态颜色（异常>未收敛>运行>排队>待提交>完成>归档），不再只显示灰色计数



**已完成（v0.8.7，2026-09-18 · 节点看板重构 + 本地镜像扁平化）**

- [x] 集群节点状态看板重构：新建 `ClusterNodeBoard`（左侧节点矩阵 + 右侧队列信息行、rAF 平滑滑动、拖动、指示条、三行 Tooltip），替换原「队列拥堵卡片 + bhost 明细表」；节点明细表按要求删除，`.queue-card*` / `.node-core-cell*` 死样式一并清理
- [x] **本地不再创建 `conN`**：`task_paths.strip_continuation_suffix()` 让续算子任务的本地路径归并到任务族根目录（`dir_path` 字段仍保留 `.../conN` 作逻辑主键）
- [x] **`inputs/` 并入 `files/`**：本地每个任务只有一份镜像，同步时用远端"最新计算目录"的 INCAR/KPOINTS/POSCAR/CONTCAR（+CIF）**覆盖**写入
- [x] **草稿保护**：有未生效草稿的文件跳过覆盖（本地副本保留），元数据仍按远端记录并标 `protected`，界面"本次计算值"不受影响
- [x] **归档静默拉取**：任务归档（关闭）后后台线程拉最新 `OUTCAR` + `OSZICAR` 到 `files/`，失败只记审计
- [x] 迁移脚本 `scripts/flatten_local_mirror.py`（dry-run/`--apply`）已执行：14 个 `inputs/` 合并、131 个空 `conN` 骨架删除，18 个被覆盖文件备份到 `data/backups/local_mirror_20260918_200029/`
- [x] mock 模式补强：`ssh.mock_enabled()/mock_local_path()` 公开，"最新目录定位"在 mock 下改扫本地 mock 远端树（原先无法离线联调同步路径）
- [x] **集群采集合并**：新增 `backend/cluster_probe.py`，总览与作业管理共用一次 exec 采集 + 一份 TTL 缓存（`cluster_cache_seconds`，默认 300s）；打开页面不再各自发 SSH，任一页刷新强制重采且两边同步，巡检后失效预热；采集失败有旧数据时标 `stale`（前端显示「缓存数据」）
- [x] **vasp.lsf 提交脚本自动生成**：`src/utils/vaspLsf.ts` 按 8 段模板（S1..S8）拼装，表单三组字段（任务名/队列/时分双框截止时间；总核数默认 24 + 每节点核数默认取队列规格 + "将分配 N 个节点"提示；软结束开关默认开，**`-wt` 预警时间可调：1–999 分钟、步长 5、默认 50**）；`POST /api/jobs/tasks/{id}/upload-submit-script` 写远端最新目录并备份 `old_vasp.lsf`、同步本地 `files/vasp.lsf`；提交仍 `bsub < vasp.lsf`
- [x] **POSCAR 上传远端**：POSCAR 页新增「上传 POSCAR 到远端」按钮（备份 `old_POSCAR`、同步本地镜像），另把"定位目录 + 备份"合并成一次 exec
- [x] **生成 POTCAR**：POSCAR 页新增「生成 POTCAR（pos2pot）」按钮，单次 exec 在远端当前目录运行 `pos2pot.sh`（递归处理含 POSCAR 的子目录），返回命令输出 + POTCAR 大小/行数/元素块；命令名按 `pos2pot` → `pos2pot.sh` → 绝对路径 自动解析
- [x] **提交前输入文件非空检查（按任务类型分）**：把「定位 conN + 检查非空 + bsub」合并进**同一次 exec**（3 次往返 → 1 次），缺文件返回 400 列出文件名并阻止提交；opt/frac/ele 检查五件套，**NEB 检查 `INCAR/KPOINTS/POTCAR/vasp.lsf` + 各映像目录 `00..(IMAGES+1)/POSCAR`**（VTST 根目录无 POSCAR，原口径会误拦）
- [x] **「上传到远端」改为「同步到远端」**（INCAR/KPOINTS/POSCAR）：写远端的同时把未生效草稿标记为已应用（`applied_in="remote"`）、刷新本地镜像与"本次计算值"元数据，界面原地更新；续算逻辑不变（已结清的草稿不会被重复应用）
- [x] 推荐网格判定改为「满足 k × 晶格常数 > 密度系数 的**最小整数**」（`floor(系数/L)+1`，不再是四舍五入），与巡检 `k×a > 20` 判定一致
- [x] 推荐网格改为一行弱化提示（不再独立成框、字号更小、**不采用即置灰**，采用后才转绿；「生成 KPOINTS 文件」保持主按钮）
- [x] **KPOINTS 页三种网格讲清楚**：区分并明确标注「本次计算（蓝，远端当前值）/ 待生效（橙，下次续算或同步到远端后生效）/ 推荐（灰，仅建议）」；修正原来把"待生效"值错标成"实际生效"的提示；推荐网格加「采用为待生效」按钮（不再让人猜哪个在生效）
- [x] 双击空白区取消选中（单击空白不再误清空，避免旋转时把框选结果清掉）
- [x] 修「Shift 框选原子时选中页面文本」：框选覆盖层 `preventDefault()` + 整页 `user-select:none`（body 标记类）+ 窗口 mouseup 兜底清理
- [x] **POSCAR 页「固定原子」已接前端**：弹窗支持「选中原子 / 整个元素 / 按高度区间」+ 编号方式 + 标签开关 + 可选同步远端；后端 `POST /tasks/{id}/selective-dynamics` 调脚本并刷新本地镜像/元数据（远端同步时备份 `old_POSCAR`）
- [x] **POSCAR 固定原子脚本** `scripts/selective_dynamics.py`：插入 `Selective Dynamics` + 写 `坐标 + T/F + 元素序号` 标签；固定规则可配（手动序号/标签、元素、z 高度区间、POSCAR 页选中 JSON）；原文件存 `old_POSCAR`；已固定过的文件可重跑覆盖；坐标块之后的附加内容（CONTCAR 的"空行 + 速度块"）原样保留；**原地改写 + 逐行保留原始行尾**，同参数重跑可与原文件逐字节一致（test/1 已验证 cmp 通过）

**已完成（v0.8.6，2026-09-18 · 同名组路径列误合并修复 + 节点接口回归修复）**

- [x] 修「自由能路径和 neb 路径重名时会自动合并」：巡检中心路径列的跨行合并键漏了类别，补成 `项目|task_category|组名`（Ag_20260830 的 PATH1/2/3 同时是自由能组与 NEB 组，排序相邻时被并成一格）；纯前端，`npm run build` 后刷新即生效
- [x] 修 `/api/jobs/nodes` 500 回归（v0.8.2 引入）：`from input_state import build_snapshot` 覆盖了 `cluster_status.build_snapshot`，节点接口改用别名 `build_node_snapshot`
- [x] 全盘核实其它分组逻辑（作业树 / 报告 / 组数据接口 / 图表文件名）均按 `group_id`、`task_id`，无按组名当键的残留
- [x] 新增 `scripts/connect-hpc.sh` + `scripts/connect-hpc.desktop`：一键登录 HPC（校验私钥权限 + SecureLink tun0 路由）

**已完成（v0.8.5，2026-09-18 · Linux 生产部署 + 输入参数页新功能）**

- [x] 迁移落到 Linux 生产机：代码/数据统一在 `/home/zouyuxi/projects/vasp-manager`，systemd `vasp-manager.service` 常驻（`.venv` Python 3.14.4；`npm run server` 改指 venv 解释器）
- [x] 输入参数页新增「DFT+U」卡片（主开关 + 元素表驱动 `LDAUL/LDAUU/LDAUJ` 三数组，关闭不写任何 LDAU\*）与「偶极矩修正」卡片（`LDIPOL/IDIPOL/DIPOL`，DIPOL 三分量齐全才写）；开关语义由 `applyIncarGates()` 统一到预览/本地/上传/草稿四条链路
- [x] 输入参数页布局改为两列独立流式（卡片自然高度，短卡片不再被撑出空白）；修「其他参数」新增/改名不可用（本地行 + 稳定 id）；修「一键清除」把红点全部点亮的前端 bug
- [x] 修迁移引入的大小写分叉（`Ag_20260830/neb` ↔ `NEB`，用软链接对齐）并全盘审计（本地 272 / 远端 324 条路径无其它分叉）
- [x] 删除一次性 `MIGRATION.md`，可复用内容并入 `process.md` §11 / `README.md` / `DEPENDENCIES.md`

**已完成（v0.8.4，2026-09-17 · 跨机器迁移交接）**

- [x] 新增 `MIGRATION.md`：打包清单 / 迁移后 11 项必改 / 首次自检验收表 / systemd + nginx / 回滚 / 故障排查 / data 目录速查
- [x] 新增 `scripts/migrate_paths.py`（dry-run + `--apply`，改写前自动备份）归一化遗留绝对路径
- [x] 修复跨机器迁移障碍：`aux_molecules.json` 路径改相对（读时还原本机绝对路径）；`reports/index.json.directory` 改相对（读时就地归一化）
- [x] 清理测试残留 `data/projects/P`
- [x] 迁移前置审查：无平台专有依赖、导入无大小写不一致、无非 ASCII 文件名、`projects.json` 0 处绝对路径、3Dmol 已入库

**已完成（v0.8.3，2026-09-17 · 输入文件页体验修正）**

- [x] 「文件结构」改为**同步状态**：最新（绿）/ 过时（黄）/ 有修改待提交（高亮）；POTCAR·submit.sh 标"不参与同步"；**去掉 WAVECAR**
- [x] POSCAR 原子：单击选中、**Ctrl/⌘ 多选**、**Shift 拖拽框选**（Ctrl+Shift 并入）；选中标签**自动合并区间**（Al1-3 Al6-7）；序号与 POSCAR 坐标行一致（1 起）
- [x] POSCAR ⇄ CONTCAR 切换**保持同一视角**（不再重置）；POSCAR 不参与远端修改（固定原子功能搁置）
- [x] NEB 映像**只取 CONTCAR**（不回退 POSCAR）；NEB 映像任务详情去掉 POSCAR 页签
- [x] 布尔参数支持 `.T./.F.` 等价写法（`LWAVE = .T.` 能正确勾选，且不误判为"已修改"）；含空格的多值参数（DIPOL/MAGMOM）完整保留
- [x] 只在实际改动时写文件：上传远端先比对快照；续算 INCAR 只在参数真变化时写回
- [x] 续算不再往 INCAR 写注释（乱码）；修正 KPOINTS 网格行行首空格、INCAR 每续算一次多一个 `\r`
- [x] 续算后父任务 `input_state` 与续算子任务一起落库（修掉"续算后仍显示待提交"）

**已完成（v0.8.2，2026-09-15 · 作业管理输入文件重构）**

- [x] 远端参数自动同步：提交作业后后台同步一次（1 exec + 4 SFTP 小文件），也可手动「同步最新参数」；快照落 `<任务>/files/`（含 CIF；v0.8.7 前是 `inputs/`），元数据存 `task["input_state"]`
- [x] 参数草稿 + 变更台账（file/key/from/to/at/applied_at/applied_in）：改参数不碰远端，**只在下次续算应用**
- [x] 续算应用：`continuation._apply_drafts_to_new_dir()` 合并草稿 INCAR 参数（ISTART/ICHARG 优先，冲突告警）→ KPOINTS 网格重写 → **POSCAR 永不覆盖** → INCAR 顶部写审计注释 → 台账标记 applied_in
- [x] INCAR 编辑器：默认只读（点「修改参数」解锁 → 确认修改才生效）、已修改/待生效参数高亮、「其他参数」列出本次计算里非预设参数（原"自定义参数"）
- [x] POSCAR 页重构：460px 3Dmol 大窗口 + 初始 POSCAR/最新 CONTCAR 切换 + 点击选中原子（金色高亮，为固定原子铺路）+ 结构数据 + 球棍/填充、缩放、自动旋转、a/b/c 视角、重置视角
- [x] KPOINTS：直接改 k1/k2/k3（同样只读闸门 + 确认 + 待生效高亮），显示 k×a 网格密度系数与巡检 >20 对照
- [ ] 后续：固定原子功能（选中原子写进 POSCAR 的 Selective dynamics）

**已完成（v0.8.1，2026-09-15）**

- [x] 总览「运行中的任务」固定高度 320px 内部滚动（作业变多不再撑高模块）
- [x] 新建项目支持建组：自由能（组名 + 结构数）/ NEB（组名 + 映像数），不再是"只能加单个频率矫正任务"
- [x] 创建自由能任务时**同时登记 结构优化(opt) + 频率矫正(frac)**，frac 作为 opt 子项（parent_task_id 指向它，呈现方式不变）
- [x] 后端放开 `ProjectIn.tasks` 的"至少 1 个独立任务"限制（允许只建组的项目）
- [x] INCAR：参数留空一律不写入（补齐"上传远端"链路 + `modify_incar` 忽略空值），NCORE 清空不再写成 `NCORE = `
- [x] INCAR 默认参数新增 `IVDW = 11`（DFT-D3(BJ)），前端 incar.ts 与后端 task_registry.json（含 defaults）四处同步

**已完成（v0.8.0，2026-09-13 · 报告排版重构 + 当量工期 + 巡检提速 + INCAR 精度检查）**

- [x] 报告页排版重构：列表 268px + 目录胶囊 + 正文 950/1080、图表统一 1000px、任务块（竖条标题+数据行+图+表）、信息卡、斑马纹表格、图片 eager 加载、导出 CSS 同步
- [x] 报告工作量/工期按当量：1 当量 600 核时、有效算力 200 核 × 24h × 70% = 3,360 核时/天，预计完成 = 剩余核时 ÷ 有效算力
- [x] 已关闭项目的报告折叠到列表底部（默认折叠、灰显、带「已关闭」标签）
- [x] 巡检提速：bjobs 每轮 2-3 次调用（原每任务 2-3 次）、OUTCAR 分块读（不再整文件读）；45 任务场景 24.8s → 1.3s，输出逐字段一致
- [x] 巡检读 INCAR（思路 A，零额外 SSH）：回传 incar/kpoints/lattice/force_thresholds/precision 快照
- [x] 收敛阈值改由 INCAR 的 EDIFFG 决定（缺失或正值退回 registry）
- [x] 新增精度检查（k×a > 20、EDIFFG ≤ -0.02、EDIFF ≤ 1E-5），不满足判「低精度收敛」（归档 low_precision、落库仍 completed、报告列为 medium 关注项）

**已完成（v0.7.4，2026-09-13）**

- [x] 报告「不同任务之间」加分隔线：结构优化 / 自由能路径 / NEB 每个任务区块之间插入 `---`（首尾不加）
- [x] 前端 `.report-markdown hr` 与导出 HTML 的 `hr` 统一样式（浅虚线 + 上下留白）

**已完成（v0.7.3，2026-09-13 · 报告看板与巡检详情同版式）**

- [x] 新增 `backend/report_panels.py`：自由能路径看板 / NEB 能垒看板按巡检详情页同版式生成（统计卡 + 图例 + 图）
- [x] 项目进度改为**分块长条**（1040px）：块宽 = 任务当量占比（opt/frac 1 · NEB 5 · ele 0.4），块内按该类型完成比例填充
- [x] 增加**当量加权主进度**（大数字 + 主进度条）与逐类型图例（完成数 / 百分比 / 当量占比）
- [x] 结构优化章节口径修正：只统计**独立** opt 任务（自由能中间体、NEB 初末态不算）——Ag 由错误的 28 个回到 3 个
- [x] 自由能收敛判定改用巡检 `force_converged`（归档任务不再整片显示"未收敛"）
- [x] 自由能 / NEB 明细表列与巡检详情页对齐（自由能加相对 ΔE 列；NEB 加映像明细表）
- [x] 删除被取代的旧 `step_chart` / `neb_barrier_chart` / `progress_bar_percent`

**已完成（v0.7.2，2026-09-13 · 报告 11 项修正：以总结为核心稳定版）**

- [x] 去掉附录章节（`REPORT_SECTIONS` 只剩 基本信息 / 重点科学结果分析 / 异常与关注项 / 下一步建议；附录数据仍留在 report.json 供大模型消费）
- [x] opt 任务三视图与能量/力曲线横向排版成**一张面板图**（左侧 a/b/c 三视图 + 右侧双轴曲线，同一基线对齐）
- [x] 能量与力曲线按巡检 `LineChart` 风格重画（同边距/网格/配色/字号 + 力阈值虚线 + 图内最终值标注）
- [x] 修复项目进度图不显示（`_sections_markdown` 误把 `charts` 字典当路径取值，改为固定 `charts/progress.svg`）
- [x] 修复自由能台阶图 / NEB 能垒图无数据（字段键 `free_energy_ev` / `relative_energy_ev` 与图表函数参数对齐）
- [x] 前端只显示图片（删掉交互式 3D 折叠区与 Markdown / 结构化数据切换），做到「报告所见即所得」
- [x] 导出范围改为点击「导出」后才展开（Popover），导出入口移到「报告内容」标题行
- [x] 同项目新报告**直接覆盖**旧报告（报告 ID 稳定为 `rpt_<project_id>`，索引只留一条；列表改称「项目报告」）
- [ ] （待确认）是否需要后端静态 3D 渲染：3Dmol 是浏览器端 JS 库，Python 后端没有；要做需引入 headless 浏览器（新增依赖）

**已完成（v0.7.1，2026-09-13 · 报告以总结为核心）**

- [x] 章节精简为 5 章：基本信息 / 重点科学结果分析 / 异常与关注项 / 下一步建议 / 附录（正文 25KB → 8KB）
- [x] opt 每任务：结构三视图（纯 Python 正交投影）+ 能量与最大力同图（双纵轴 + 力阈值）
- [x] 自由能按路径（台阶图 + 中间体表）；NEB 按组（能垒图 + 映像结构对比矩阵）；电子结构占位
- [x] 异常与关注项改为模板生成（最多 6 条）；下一步建议最多 5 条
- [x] 每天自动生成：复用巡检调度线程，`auto_report_enabled` + `report_interval_hours`（默认 24h）
- [x] 前端科学结果章节上方提供交互式 3D（3Dmol 结构 / NEB 映像对比），导出仍用静态图　→　**v0.7.2 已按用户要求移除，改为只显示图片**

**已完成（v0.7.0，2026-09-13 · 智能报告重构：分项目报告生成）**

- [x] 结构化数据（schema 1.0.0，枚举/单位/时间格式统一）+ Markdown（章节一一对应）+ SVG 图表
- [x] 11 章：元数据 / 执行摘要 / 进度总览 / 任务详情 / 科学结果 / 巡检异常 / 资源集群 / 风险分析 / 行动清单 / 大模型上下文 / 附录
- [x] 图表纯 Python SVG（零依赖）：能量-步、力-步、自由能台阶、NEB 能垒、核数圆环、存储进度条
- [x] 风险规则外置（13 条，声明式 all/any + field/op/value），`closed` 闸门避免已关闭项目误报
- [x] 接口：generate（单个/批量）、list、detail、structured、markdown、export.html（按章节、图表内联、print→PDF）、files、delete
- [x] 前端报告页重写：按项目生成 / 一键全部、历史分组、章节导航、**导出范围勾选**、视图切换、下载 MD/JSON、导出 HTML/PDF
- [x] 统计口径：完成率分母为未关闭任务，归档任务不参与风险判定；全归档项目记 100%

**已完成（v0.6.14，2026-09-13）**

- [x] NEB 映像视图只留一个「原子缩放」滑杆（默认 0.35），画面整体倍率固定 2.5（不暴露控制）
- [x] 「重置视角」按 原子缩放 0.35 + 画面倍率 2.5 复位

**已完成（v0.6.13，2026-09-13）**

- [x] 更正 v0.6.11 的理解偏差：原子尺寸恢复默认 0.35（范围 0.15–0.85）
- [x] 新增独立「画面缩放」滑杆（相机倍率，默认 1.35、范围 0.6–2.2）；
      倍率变化先 zoomTo 归零再拉近，重置视角复位到默认倍率

**已完成（v0.6.12，2026-09-13）**

- [x] NEB 映像面板对齐：头部固定 34px + 不换行，ΔE/受力移到画布下方固定高度页脚
      （原来部分面板头部两行 → 画布起点错位、多出白边）
- [x] NEB 映像恒定横排：`grid-auto-flow: column` + 横向滚动，宽度不足时不再换行

**已完成（v0.6.11，2026-09-13）**

- [x] NEB 3D 视图初始放大倍率调高：原子尺寸默认 0.35 → 0.5，滑杆上限放宽到 1.0，
      `zoomTo()` 后补 `zoom(1.15)` 相机拉近

**已完成（v0.6.10，2026-09-13 · 修复 v0.6.9 的两个前端缺陷）**

- [x] 部分 NEB 任务详情白屏：NEB 专属 `analysis` 不再落到 `StructurePanel`（改为独立分支，
      无映像时显示带说明的占位）；`StructurePanel` 对 `warnings` / `files` 加可选链兜底
- [x] 左上角白色遮挡：`.neb3d__canvas` 补 `position: relative; overflow: hidden`
      （3Dmol canvas 是绝对定位，容器缺定位上下文会逃到页面左上角）
- [x] `NebImages3DViewer` 加固：3Dmol 缺失降级提示、单映像渲染失败不影响其他、补 `resize()`

**已完成（v0.6.9，2026-09-13）**

- [x] NEB 映像结构分析：IS → 中间态 → FS 横向 3D 对比（`NebImages3DViewer`，只展示优化后结构）
- [x] 触发条件与结构优化一致（25 离子步一桶 + 目录变化重置）：batch_check 新增 `neb_band_steps`
      （中间映像 OUTCAR 的 TOTAL-FORCE 最大块数，**运行中的 NEB 也统计**）
- [x] 同步用单次远端脚本 base64 回传各映像 CONTCAR（缺则 POSCAR）→ CIF 写入 `reports/structure/images/`
- [x] 详情接口返回 `analysis.neb_images`（role / CIF / ΔE / 最大受力，标签按数值与 nebef 对齐）
- [x] 视角联动、球棍/空间填充、自动旋转、缩放、重置、元素图例；鞍点面板高亮；弹窗自动加宽

**已完成（v0.6.8，2026-09-13）**

- [x] NEB 能垒看板重做（新增 `NebBarrierPanel`）：统计卡（映像数 / Ea / 最大受力 / 末态相对能）
      + 相对能垒曲线（直线连接不插值、鞍点标注、渐变面积、悬停信息卡）+ 映像明细列表（角色徽标）
- [x] 动画：曲线从左向右绘制、数据点依次弹出、面积与鞍点标注淡入、列表行错峰上浮
      （`prefers-reduced-motion` 下关闭）
- [x] 悬停联动：曲线与明细行互相高亮；删除无用的 `.neb-barrier-layout` 样式

**已完成（v0.6.7，2026-09-13）**

- [x] 自由能路径看板重做：顶部统计卡（中间体数 / 矫正完成度 / 收敛 / 最高相对能）+ 相对能台阶图 + 中间体明细列表
- [x] 台阶图视觉：渐变柱体与面积、未收敛/未矫正琥珀标记、缺数据灰色虚线、图例与参考说明
- [x] 交互与动画：悬停上浮 + 发光 + 跟随鼠标信息卡、点击台阶/列表行直达巡检详情、
      台阶依次滑入 + 连接线淡入 + 列表错峰上浮（支持 prefers-reduced-motion）
- [x] 明细列表自绘（正负着色、收敛/矫正徽标、跳转箭头），窄屏自动重排
- [x] 后端修复：路径汇总的 `converged` 兼容归档任务（archived + archived_from=completed），
      否则归档路径会被误判成"未收敛"

**已完成（v0.6.6，2026-09-13）**

- [x] 巡检列表排序：状态优先级（错误 > 警告 > 未检 > 正常 > 关闭）+ 归档任务沉底
- [x] 自由能 / NEB 同组作为一个排序单元，用组内最高优先级状态整体参与排序（组员恒定相邻）
- [x] 原有规则保留为 tie-break：类别 → 组名自然序 → 组内结构顺序 → 任务名
- [x] 修复自测发现的两个坑：排序单元键需带 task_category（自由能与 NEB 组可能同名）、
      "组内归档成员沉底"必须在组键之后（否则会把组拆开）

**已完成（v0.6.5，2026-09-13）**

- [x] 归档任务禁止巡检：单任务巡检返回 400「任务已关闭（归档），请先重新打开再巡检」，
      避免巡检回填覆盖归档状态（线上实际问题）
- [x] 巡检列表归档任务状态列显示「关闭」（`CheckStatus` 新增 `archived`，筛选加"关闭"选项），
      信息列「任务已关闭（归档）」，不计入「未检」，改在项目块头部统计「关闭 N」
- [x] 归档行的「单独巡检」按钮置灰（列表 + 详情弹窗），详情仍可查看
- [x] `mappers` 暴露 `archived_from` / `archived_at`，"重新打开"弹窗显示真实恢复目标

**已完成（v0.6.4，2026-09-13）**

- [x] 自由能结构优化主任务归档时**连带归档** `<结构目录>/frac` 频率矫正；重新打开成对恢复
      （响应回传 `archived_siblings` / `reopened_siblings`，重复归档可补齐历史遗漏）
- [x] 归档确认弹窗按频率矫正状态提示：未完成（非 completed）时加 ⚠️ 警告；成功/重开提示写明连带关系
- [x] `mappers` 为自由能 opt 输出 `frac_sibling`（作业管理任务面板据此提前提示）
- [x] 新增 `scripts/repair_frac_archive.py`：一次性修复历史"主任务已归档、frac 未归档"数据（默认 dry-run）

**已完成（v0.6.3，2026-09-13）**

- [x] 巡检详情弹窗 footer 新增「关闭（归档）」/「重新打开」（未完成同样弹窗警告）
- [x] 作业管理已关闭项目默认折叠（受控 expandedKeys，用户仍可手动展开）
- [x] 总览「已关闭项目」折叠区样式重做（胶囊按钮 + 虚线分隔 + 灰色进度条，与卡片风格统一）

**已完成（v0.6.2，2026-09-13 · 巡检链路加固 + 归档/关闭 + 定时调度）**

- [x] `submit` 改走 `db_transaction`，消除与巡检回填的写覆盖竞态
- [x] 全局巡检**按项目分批**：脚本每服务器每轮只上传一次；远端检查在事务外，
      每项目独立事务回填归档；单项目失败只影响自己（摘要 `failed_batches`），
      数据库写锁从 75-90s 缩到单项目回填的几秒
- [x] 新增 `inspection_scheduler.py`：后台线程每 60s 判定，开关 + 间隔（默认 2h）→ 自动全局巡检；
      `PUT /api/inspections/auto` 切换，`/meta` 返回调度器实时状态
- [x] 全局巡检成功后静默作废并预热集群快照缓存（`invalidate_cluster_cache(prewarm=True)`）
- [x] 任务「关闭（归档）」/「重新打开」：`POST /jobs/tasks/{id}/archive`、`/unarchive`
      （不硬性要求 completed，前端弹窗提醒；恢复时用 `archived_from`）
- [x] 项目「关闭」/「重新打开」：`POST /projects/{id}/close`（要求可见任务全部归档）、`/reopen`
- [x] 巡检中心按项目分块（组内顺序不变），关闭项目排最后、默认折叠、灰显；顶部加自动巡检开关
- [x] 总览项目进度：已关闭项目收进折叠区；作业管理：关闭项目排最后、灰显、任务行有归档按钮
- [x] `vite.config.ts` 支持 `VITE_API_TARGET` 覆盖后端地址（隔离测试 / 指向其他机器）

**已完成（v0.6.1，2026-09-13）**

- [x] 巡检列表未巡检行文案：信息列「待提交」→「未检」，detail 改为「暂无巡检记录，可点击「单独巡检」获取该任务当前状态」
      （状态列仍为待提交/灰色，保持不变）
- [x] 修掉未巡检行操作按钮的英文残留 `check` → 「单独巡检」

**已完成（v0.6.0，2026-09-13 · 总览模块重构与扩展）**

- [x] 后端 `backend/dashboard.py` + `routers/dashboard.py`：单次 SSH 合并查询集群（bjobs/blimits/df/bhosts/bqueues）
      + `@@@` 分段解析 + 5 分钟缓存（`settings.json: dashboard_cache_seconds`）+ 集群采样历史
      `data/dashboard/core_history.json` + 作业↔任务映射 + 核数按项目聚合 + 风险预警 + 项目进度 + 近 7 天趋势
- [x] 新增接口 `GET /api/dashboard/overview | cores-usage | cluster-health | risk-alerts | trend`
      （`?refresh=1` 强制重新查询集群）
- [x] 前端总览重构：顶部状态栏（异常卡片→巡检中心、运行中卡片→展开运行任务）+ 快捷操作
      （新建项目 / 触发全局巡检 / 刷新集群状态）+ 运行中任务表（点行跳 `/jobs?task=`）
      + ECharts 核数圆环（按项目着色、90% 橙 / 100% 红闪烁）+ 集群健康（节点灯 / 队列拥堵 / 存储告警）
      + 风险预警（未收敛 / Zombie / 巡检异常）+ 项目四象限气泡 + 最近任务明细
- [x] 引入 echarts 6.1.0（按需注册 + 独立 vendor chunk）、数字滚动动画、30 分钟自动刷新
- [x] 修复总览既有问题：逾期项目显示「已完成」、进度分母含隐藏续算目录、删除按钮换行破版、
      趋势图为 MOCK 假数据；清理死代码 `TrendChart.tsx` / `src/data/mock/projects.ts`
- [x] 集群查询命令可配置（`servers.json` 5 个键：node_status / queue_status / user_used_cores /
      user_total_cores / storage_check，`{storage_path}` 自动替换为 remote_base）

**已完成（v0.5.5，2026-09-13）**

- [x] NEB 续算活跃作业保护：`bjobs` 命中 RUN/SSUSP/PSUSP/USUSP 时只回传 `action="running"`，
      不建 conN、不移动 WAVECAR（此前 NEB 路径无拦截，与 opt 不一致）
- [x] NEB 续算各映像（含端点 00/NN 与中间态）WAVECAR 随续算 mv 移动（目标已有不覆盖）
- [x] `modify_incar` 清理源文本头部空行（兼容 LF / CRLF / 纯空白行）
- [x] `_script_slice` 跳过标记行换行，修复续算 `===FILES===` 解析出空字符串首项
- [x] `GET /api/health`：`uptime` 改为后端进程运行秒数 + 新增 `startedAt`（原值为系统开机时长，易误判）

**已完成（v0.3.0 计算流程组重构，2026-08-25）**

- [x] 任务类型收敛为四种：opt / frac / neb / ele（ele 带 subtype：pdos/bader/diff_charge/work_function）
- [x] 组元数据：任务 `group{group_id, group_type, group_role, structure_label}`、
      `parent_task_id`（frac 父任务=同结构 opt）、`input_source`（poscar_from 等）
- [x] 目录结构规范：独立任务 `<项目>/<模型名>`；自由能组 `<项目>/<组根>/<结构标签>/opt|frac`；
      NEB 组 `<项目>/<组根>/initial_opt|final_opt|neb_calc`（neb_calc 下 00..n+1 映像目录）
- [x] `dir_path` 落库为权威路径，mappers/巡检/结构分析/渲染/文件接口统一走 task_paths
- [x] 组创建 API：`POST /api/groups`（自由能组含辅助分子、NEB 组含映像数）、
      `POST /api/groups/{id}/aux`、`POST /api/groups/tasks`（独立任务），自动生成
      目录、默认 INCAR/KPOINTS 与 group 元数据
- [x] 报告数据接口：`GET /api/reports/groups`、`GET /api/reports/groups/{id}/data`
      （自由能台阶图结构：opt 能量已提取 + frac 矫正占位；NEB 能垒图：映像能量 + 能垒）
- [x] 全量迁移：Ag_20260830 / Co_0830 的 DB、本地目录（15）、远程目录（30）迁移到新类型与扁平目录
- [x] 前端：任务树组层级（自由能组/NEB 组可折叠）、组创建向导、任务卡组信息、类型/标签更新
- [x] 巡检回归：Co_2_op（opt + 扁平路径 + con2 续算监测）正常
- [x] Ag 三条路径组织成组：每条路径 = 自由能_PATHn（I1-I7 主结构 opt+frac）+ NEB_PATHn
      （初态/末态优化 + 现有 NEB 任务），本地/远程目录同步迁移（含 SSH 中文路径 UTF-8 编码修复）
- [x] 辅助分子全局化：统一存放 data/aux_molecules/<标签>/opt|frac + 全局注册表，
      `GET/POST /api/aux-molecules`，自由能组仅引用标签不建项目任务
- [x] 默认组名：自由能_PATH1 / NEB_PATH1（支持中文组名）；项目 + 号菜单支持新建子项/自由能组/NEB 组
- [x] 布局与交互：左侧项目树固定高度内部滚动、右侧面板保持可见；点击子项自动定位所属项目
- [x] v0.4.0 目录规范：本地/远端/前端同构 —— 项目 → 类型分类（结构优化/自由能/NEB/电子结构）→
      自由能组 <组名>/<结构X>/opt|frac、NEB 组 opt/IS|FS + neb/00..n+1；SSH 中文路径 UTF-8 已修复
- [x] v0.4.1 目录名改为 ASCII：opt / free_energy / neb / ele、free_energy_PATHn / neb_PATHn、
      struct_NN；界面仍显示中文（结构优化/自由能/NEB/电子结构、结构N）；本地/远端/DB 全量迁移
- [x] 组目录再简化：free_energy/PATH1、neb/PATH1（去掉类型前缀），组名存入 group.name 元数据
- [x] 交互重构：项目 + 号菜单四类型（结构优化/自由能组/NEB 组/电子结构），点选后弹对应新建窗口；
      四个分类节点自带 + 号直达新建；自由能/NEB 组节点显示组名（PATH1）
- [x] 顶层「新建项目」与总览共用新增项目弹窗：截止日期改为日期点选，子任务按四种类型树状分组
- [x] 自由能结构目录：struct_01/opt → 1/（opt 直接位于结构目录），frac 移到 1/frac 与续算 conN 同级；
      已全量迁移并核查：dir_path 权威路径使巡检/结构分析/报告/文件接口自动适配，续算 1/con1 可识别
- [x] 同类型续算（服务器端完成）：`POST /api/jobs/tasks/{id}/continuation` 定位最新输出（复用巡检 conN
      逻辑）→ 创建 conN → 复制 CONTCAR→POSCAR/POTCAR/KPOINTS/提交脚本、移动 WAVECAR → 修改 INCAR
      （ISTART=1, ICHARG=0）→ 登记续算子任务（parent_task_id/dir_path/input_source）；NEB 特殊处理
      映像 00..NN；前端续算窗口保留同类型/跨类型选择，同类型直接调后端创建并自动选中
- [x] 路径映射固化：data/config/path_mapping.json（local_root ↔ 各服务器 remote_root），
      `GET/PUT /api/path-mapping` + `POST /api/path-mapping/rebase` 批量重算任务路径
- [x] 子项基础操作：`PATCH /api/jobs/tasks/{id}` 重命名（同步本地/远端目录与数据库）、
      `DELETE /api/jobs/tasks/{id}` 删除（本地目录移入 data/trash，远端不自动删）；前端重命名弹窗 + 删除确认
- [x] 自由能组添加结构：`POST /api/groups/{id}/structures`（自动生成 结构N+1 的 opt+frac），
      前端组节点 + 号触发数量弹窗；所有改动落盘 projects.json / 配置文件，重启后保留
- [x] v0.5.0 路径规范化：任务元数据路径全部改为相对项目根目录（dir_path/remote_dir/input_source/
      current_output），统一 `paths.resolve_local_path / resolve_remote_path` 解析；
      文件接口/巡检/续算/报告/结构分析/VESTA 全部适配
- [x] 根目录可配置：data/config/path_mapping.json + `GET/PUT /api/settings/root-paths`
      （SSH 页新增「项目根目录」配置卡片），修改根目录自动重定位，任务路径无需改动
- [x] 旧数据迁移：绝对路径 → 相对（dir 80 / remote 80 / input 36，0 异常），已备份可回滚
- [x] 结构优化“未收敛”状态：OUTCAR 正常结束但力未收敛（max>0.02 或 rms>0.01）→ 任务状态改为
      unconverged（未收敛）而非 completed；状态机新增 unconverged（running/completed→unconverged、
      unconverged→completed/queued 等）；巡检/结构同步/分析范围同步纳入；前端新增状态标签与排序；
      同时修复 batch_check 力解析仍用旧类型名 structure_opt 的遗漏
- [x] 前端树：项目 → 四种类型分类 → 组/结构/独立任务；自由能组结构节点为「结构优化+频率矫正」合并页面，
      NEB 组节点为「初态 IS / 末态 FS / NEB 映像」合并页面，ele 任务显示 subtype
- [x] 全量迁移：Ag_20260830 / Co_0830 本地与远程目录、DB dir_path/remote_dir/structure_label 全部更新

**待开发（报告解析与前端图表，2026-09-13 核对）**

- [x] 报告页接入组数据：自由能台阶图（PathStepChart / PathSummaryModal）、NEB 能垒图（nebef.pl 散点连线）——v0.4.1 / v0.4.5 已完成
- [ ] frac 频率输出解析（ZPE / 自由能矫正），回填组数据 `frac.zpe / correction`
      （当前矫正值来自 vaspkit 501 单点调用，未解析频率输出文件）—— **下一个优先项**
- [ ] NEB 映像 POSCAR 线性插值（初末态 CONTCAR 生成 00..n+1，现依赖 nebmake.pl）

**已完成（前端框架）**

- [x] Vite + React 18 + TypeScript 项目基础结构
- [x] 侧边栏导航 + 顶部状态栏（SSH 状态 / 系统时钟），移动端适配
- [x] 四大模块页面：总览 / 巡检中心 / 作业管理 / 智能报告
- [x] SSH 连接配置页（服务器增删改、模拟握手测试、连接/断开）
- [x] 页面切换动画、卡片悬停、骨架屏加载
- [x] Mock 数据层（`src/data/mock/` + `src/api/`），字段与现有 Python 后端对齐
- [x] 作业管理模块完整前端框架：项目-子项树、POSCAR 导入预览、INCAR 参数编辑器、
      KPOINTS 自动生成、续算流程、提交脚本生成（节点状态 Mock）
- [x] 局域网访问（Vite `host: true`），README 已含防火墙/内网穿透说明
- [x] 依赖升级至 Vite 7 / React Router 7，`npm audit` 0 漏洞

**已完成（后端起步，2026-08-24）**

- [x] Python + FastAPI 后端骨架（`backend/`，Uvicorn 端口 3001，可静态托管 dist 单端口部署，自带 `/docs` 文档）
- [x] 「新增项目」真实落地：`POST /api/projects` 复刻 `add_project.py` 全流程（初版为 Express，已按决策迁移到 FastAPI）
- [x] 文件型存储：`data/projects.json` + 本地目录 + 自动备份（20 份）
- [x] 运行时依赖检查：后台线程检查 + 后端日志提示 + 前端顶部提示条（`/api/deps`）
- [x] SSH 配置同步到后端：`GET/PUT /api/ssh/config`，含"项目远程根目录"（新增项目均建在此根目录下）
- [x] 新增项目排除频率计算（与自由能绑定）；自由能权重调整为 1.2
- [x] 巡检系统真实落地：`POST /api/inspections/run`（上传 batch_check → 服务器解析 → 状态机回填 → 归档）
- [x] 巡检结果列表 `GET /api/inspections` + 调度信息 `GET /api/inspections/meta`
- [x] 巡检详情 `GET /api/inspections/{task_id}`：能量/力随离子步曲线、结构分析
      （POSCAR/CONTCAR 晶格对比 + VESTA a/b/c 三轴渲染图）、分析范围筛选
- [x] 结构分析按 ISIF 智能切换：ISIF=2（默认）显示原子位移分析，其余显示晶格参数对比
- [x] 分析范围收紧：仅"结构优化 + 两次巡检状态有变化（run→completed/zombied）"才下载校验
      POSCAR/CONTCAR（analysis_needed 判定与巡检回填同步收紧）
- [x] 结果保留策略：同一子项按 task_id 保留最新一条结果；本次未检查时沿用上次的
      检查标记 / 力历史 / 力统计（只更新、不删除）
- [x] 最新输出定位（续算 conN 优先）：batch_check 远程解析 `con1/con2/...`（按编号降序，
      取第一个 OUTCAR 正常结束的目录，全部异常回退主目录）；结构对比/能量/力历史读取
      最新目录的 CONTCAR/OUTCAR/OSZICAR，POSCAR 仍取主目录；`current_output`
      落库并在巡检列表「输出位置」与详情中展示（报告模块可直接读取该字段）
- [x] 结果本地持久化：归档 `data/checks/check_results_*.json`，重开网站显示上次巡检结果
- [x] 本地模拟模式（VASP_SSH_MOCK + 夹具脚本）用于离线验证巡检流程
- [x] 清理演示项目：删除种子数据与前端 Mock 回退
- [x] 数据迁移：旧项目真实数据（项目库/配置/项目目录/备份/巡检结果）已迁入本项目 `data/`，
      运行不再依赖旧项目路径（旧项目仅作功能迁移参考，封装打包不漏文件）
- [x] 真实巡检验证：对 Ag_20260830（/data/gpfs03/mdye/projects/test/Ag_20260830）完成一轮真实巡检
- [x] 续算监测真实数据验证：Co_0830/Co_2_op（con1-con3，con3 运行中）——最新输出定位为 con2，
      能量/力历史/结构对比均取自 con2（-1173.163 eV、71 离子步），状态经状态机 running→completed
      写入（0 拒绝），输入文件与最新输出已同步本地 files/

**尚未开始（其余模块）**

---

## 待完成清单

### 1. 后端 API 开发（最高优先级，其他模块依赖此步）

- [x] 定后端技术栈：Python + FastAPI + Paramiko（`backend/`，`python backend/run.py` 运行）
- [x] 新增项目 API：`POST /api/projects`（校验 → 优先级计算 → 本地目录 → 可选远程同步 → 原子写库 + 备份）
- [x] 基础接口：`GET /api/projects`、`GET /api/servers`、`GET /api/task-types`、`GET /api/health`
- [x] 设计其余 REST 接口清单（任务 / 巡检 / 报告 / SSH）——已随各模块落地
- [x] 真实 SSH 连接服务：连接池 + 30s keepalive + 60s 应用层保活 + 空闲回收 + 断线重连（v0.4.5 / v0.5.0）
- [x] 替换前端 `src/api/ssh.ts` 的三个函数：
  - `fetchServerConfigs` → `GET /api/ssh/config`
  - `persistServerConfigs` → `PUT /api/ssh/config`
  - `testRemoteConnection` → `POST /api/ssh/test`（真实握手）
- [x] 顶栏 SSH 状态改为轮询 `GET /api/ssh/status`（后端常驻连接池真实状态，前端回退 UI 状态）
- [x] 前端请求封装：`src/api/client.ts` 提供统一 `request()`（统一信封解析 + 后端不可用提示），
      总览/巡检/作业等接口已复用；页面级 loading 与错误提示仍在各页实现

### 2. 文件型存储（网站同级目录，不使用数据库）

- [x] 创建 `data/` 目录结构：`data/projects.json` + `data/config/` + `data/projects/` + `data/backups/`
- [x] 原子写入 + 自动备份机制（保留 20 份，对齐 `project_db.py`）
- [x] 首次启动自动生成 `data/config/`（servers.json / settings.json / task_registry.json）；**不再写入示例项目**
- [x] `data/checks/`（巡检结果 `check_results_*.json` + `runs.json`）
- [ ] `data/reports/`（生成报告）
- [x] 前端 SSH 配置页改由后端读写 `data/config/servers.json`（连接/延迟等 UI 状态仍留 localStorage）

### 3. 总览模块（Dashboard）

- [x] 「新增项目」表单接真实后端：服务器下拉 + 子任务动态列表 + 后端校验/优先级计算/目录创建
- [x] 统计卡片接真实聚合接口（项目数/异常项/今日完成/运行中任务，均来自 `/api/dashboard/overview`）
- [x] 近 7 天趋势图接后端（核数占用 + 运行中任务 + 每日提交数；核数历史自 v0.6.0 累积，提交数可回溯）
- [x] 最近任务表走总览接口（按项目轮转取样，避免整表只来自一个项目）
- [x] 运行中任务明细（bjobs 实时：任务名/队列/核数/作业号/状态，点行跳转作业管理）
- [x] 核数占用圆环（blimits 配额 + 按项目分组，90%/100% 阈值告警）
- [x] 集群健康（bhosts 节点灯 + bqueues 队列拥堵 + df 存储配额告警）
- [x] 任务健康与风险预警（未收敛 / Zombie / 巡检异常，点击跳转）
- [x] 项目进度四象限气泡图 + 进度列表（逾期/落后计划提示）
- [ ] 队列预计等待时间估算、趋势回溯（需外部数据源）

### 4. 巡检模块（Inspection）

- [x] 「立即巡检」调真实 API：筛选任务 → 上传 `batch_check.py` → 服务器批量解析 → 状态机回填 → 归档 `data/checks/`
- [x] 巡检结果从 `data/checks/` 读取并按任务合并展示（前端筛选/搜索保留）
- [x] 异常项与任务状态联动（zombied / 力未收敛 / 文件缺失等自动标记）
- [x] 巡检中心单表风格：任务类别 chips（结构优化/自由能/NEB/电子结构）+ 表格类别列与分组排序，
      下滑翻页加载更多（不点击分页），保持原有布局
- [x] 巡检筛选改为表格列头勾选（项目 / 任务类别 / 状态），去掉顶部筛选按钮只留搜索；
      删除冗余的检查类别列
- [x] 修复巡检部署路径反斜杠 bug：`inspection_runner` 用 `str(Path(...).parent)` 在 Windows 上
      生成 `\data\...` 反斜杠路径，导致服务器 home 下误建名为 `\data\gpfs03\mdye\tools\vasp_skill`
      的空目录（内含多余 check_registry.json）；已统一 `.replace("\\", "/")` 并清理误建目录
- [x] 单任务巡检：列表接口返回 `has_inspection`，未巡检任务操作列显示「单独巡检」、已巡检显示「详情」；
      `POST /api/inspections/run-single/{task_id}` 跳过全局状态筛选直接定位任务（任意状态可巡检），
      详情弹窗 footer 提供「单独巡检」按钮，完成后刷新列表与详情
- [x] 远程根目录迁移 test → HS：备份配置与数据库到 `data/backups/pre_migration_20260825_HS/`，
      修改 path_mapping/servers 的 remote_base 为 `/data/gpfs03/mdye/projects/HS` 并重启验证；
      系统仅按备案项目名拼接路径，HS 下其他项目目录不触碰；修复 /rebase 绝对路径写入 bug
- [x] 巡检详情路径修复：`task.current_output` 存量绝对路径（test/structure_opt 旧结构）清空，
      详情接口统一按当前远程根把相对路径解析为完整路径展示（改根后自动重定位，不再显示旧 test）
- [x] 状态机放开 `zombied → unconverged` 流转（zombied 现可转 queued / unconverged）
- [x] 修复收敛误判：力统计的固定原子标志改用最新输出目录（conN）自身 POSCAR（主目录 POSCAR
      缺少 Selective dynamics 会把固定原子恒定大力算入活动原子，导致力曲线一条直线、误判未收敛）；
      实测 Ag@Al2O3/con2 force_max 0.0169 → completed；信息性 markers 不再误报 warning
- [x] 放开状态流转白名单：合法枚举状态间任意流转（以巡检/服务器观测为准），不再拦截
- [x] 修复创建项目/组远程目录缺失：创建项目 mkdir 前拼接远程根（避免建到 home 下）；
      NEB 组创建时为 opt/IS、opt/FS、neb 及映像目录逐一创建远端目录（与 free_energy 一致）；
      Co_260902 现有 NC / Co4N@NC 远端目录已补建
- [x] NEB 组创建不再自动生成映像子目录（00..n+1），映像由后续自行提供；已清理 NC/Co4N@NC
      本地与远端的空映像目录
- [x] 作业提交：`POST /api/jobs/tasks/{task_id}/submit`（远程 bsub < vasp.lsf，登记 job_id、
      状态更新 queued、审计日志 data/audit_submit.log）；前端快捷操作区「提交作业」按钮（loading、
      已提交禁用、任务信息显示作业号）；提交成功以 bsub 的 Job <id> is submitted 为准
- [x] 续算系统重构：按任务类型分发（opt/frac 通用 conN、neb 映像续算、ele 拒绝续算）；
      新增 create-frac（频率矫正输入构建）、build-ele-inputs（opt 导入/外部 + 类型参数）、
      create-neb-files（nebmake.pl 插值 + INCAR IMAGES/SPRING）；前端续算弹窗简化、
      频率计算/创建计算文件/ele 构建输入按钮与弹窗
- [x] 修复巡检与作业管理状态不同步：并发单任务巡检的读-改-写竞态会互相覆盖 projects.json
      回填（归档独立文件不受影响）；新增 storage.db_transaction 串行事务，巡检回填走锁；
      已按归档回填 15 个被覆盖任务（Ag111_I1 等 pending → completed/unconverged/zombied）
- [x] 巡检详情未读红点：归档 observed_changed 转 status_changed，状态有更新的任务在「详情」
      按钮右上角显示红点，点开详情或「一键清除」后消失（localStorage 持久化已读）
- [x] 区分巡检与提交的目录定位：巡检显示最新**有运行结果**目录（OUTCAR 非空且离子步数>5，
      batch_check.resolve_latest_output）；作业提交定位最新**续算目录**（最大编号 conN，
      resolve_latest_con）；job_id 按最新输出目录 exec_cwd 匹配，匹配不到且 OUTCAR 空则待提交
- [x] 停止作业：`POST /api/jobs/tasks/{task_id}/stop`（远程 bkill + 状态回退待提交 + 审计）；
      前端「停止作业」按钮（有 job_id 且 queued/running 可点，Popconfirm 确认）
- [x] 续算登记防重：创建续算时检查同目录是否已登记（409 拒绝），清理 Ag24@Al2O3_I7_con4
      重复记录；续算子任务（_conN）为设计行为，指向服务器真实续算目录
- [x] 续算子任务不再前端展示：作业管理/巡检列表过滤 _conN 子项（DB 保留供后台定位），
      创建续算成功后直接打开续算文件夹；续算子任务不允许再续算
- [x] 续算分流：最新目录（最大编号 conN）OUTCAR+CONTCAR 均非空 -> 创建 con(N+1)（created）；
      否则不创建不提交，输入完整返回 input_complete_but_not_finished、缺失返回 input_incomplete
      并列出缺失文件；移除 pending 前置拦截；审计日志记录分流结果
- [x] INCAR 重构：统一 modify_incar 核心函数（大小写/空格/布尔兼容、注释保留、重复合并+警告、
      缺失追加），续算/frac/ele/neb 的 INCAR 修改统一走该函数（本地生成后上传）；
      新增 upload-incar 接口（远端最新目录备份 old_INCAR 后上传），IncarEditor 加「上传到远端」
- [x] 续算 INCAR 参数规格：ele 基础 NSW=-1/IBRION=-1 + 类型参数（PDOS LORBIT/EMIN/EMAX/NEDOS、
      Bader LCHARG/LAECHG、COHP ISYM/NBANDS/LWAVE/LORBIT、功函数 LVHAR/LDIPOL+DIPOL 矫正中心，
      关闭 LDIPOL 弹警告）；frac ISYM/SIGMA/NSW/IBRION/POTIM 可配置；NEB 初末态数据库收敛校验 +
      IBRION/POTIM/IOPT/LCLIMB/IMAGES/ICHAIN/SPRING/MAXMOVE 参数化；前端 NEB/ele 弹窗参数界面
- [x] 详情页分析模块：折线图悬停竖线+交点放大+提示区；电子结构 available_analyses 识别 +
      PDOS（vaspkit 111/113/115 文件回传）+ 占位；自由能等式看板（vaspkit 501 矫正）+
      路径台阶图（汇总接口 + 看板弹窗，路径名可点击）；NEB 能垒图（映像能量解析）
- [x] NEB 过渡态看板（nebef.pl）：巡检时运行 nebef.pl 回传各映像 受力/能量/相对能垒，
      详情页散点连线能垒图（第四列相对能垒），悬停显示能量与受力
- [ ] NEB 结构看板（映像结构图矩阵，VESTA 三行对比）——搁置，后续实现
- [x] 后端定时巡检（v0.6.2）：自建后台线程调度（未引入 APScheduler），每 2 小时自动触发全局巡检，
      可在巡检中心开关

### 5. 作业管理模块（Jobs）

- [x] 前端框架：左侧项目树 + 右侧编辑区（概览 / POSCAR / INCAR / KPOINTS / 提交脚本 五个标签页）
- [x] POSCAR 导入（本地文件上传 / 从其他任务复制）+ 晶格信息解析预览（a/b/c、角度、体积）
- [x] INCAR 参数编辑器：分类表单、布尔复选框、枚举下拉（含说明）、数值科学计数法输入，
      低/中/高精度一键填充（可转自定义微调）、保存/加载预设（localStorage 持久化）、
      复制参数到其他作业、实时预览生成 INCAR
- [x] KPOINTS 自动生成：按 POSCAR 晶格常数 + 密度系数（默认 20）推荐网格，
      Gamma-centered / Monkhorst-Pack 两种模式
- [x] 续算流程前端：同类型（con1/con2…）/ 跨类型（电子结构/自由能等）两种模式，
      展示文件操作清单并在会话内生成新子项
- [x] 提交脚本生成：节点状态摘要（Mock 节点/CPU/可用核）、队列/分区、核数与作业名设置，
      LSF / Slurm 脚本生成 + 可编辑预览 + 保存提示
- [x] 本地目录统一管理：后端 `GET/PUT /api/jobs/tasks/{task_id}/files/...`（白名单文本文件读写，
      目录约定 `data/projects/<项目>/<类型>/<子项>/files/`）
- [x] 真实节点状态：后端 `GET /api/jobs/nodes`（bhosts 主数据 + bqueues 补充），
      节点-队列映射固化在 servers.json `node_groups`（b001-b014 → normal_2week 等五组），
      SSH 不可用/失败时回退模拟负载；60 秒缓存 + `?refresh=1` 强制刷新
- [x] 提交脚本页可视化队列拥堵：队列卡片（总/运行/空闲核、拥堵率、walltime、CPU、挂起风险、
      付费单价、bqueues 作业数）+ 节点明细表（bhost 状态/核数占用），队列下拉用真实映射
- [x] 节点查询提速与时机：单次 SSH 连接合并 bhosts+bqueues（非登录 shell，约 16s → 10s），
      打开/刷新网站时后台更新快照，提交脚本页直接读取并支持手动「刷新」按钮
- [x] 常驻 SSH 连接池：系统启动时后台建立连接并保活（30s keepalive）、复用、空闲 5 分钟回收、
      断线自动重连；`GET /api/ssh/status` 提供真实状态，顶栏每 15 秒轮询显示「SSH 已连接」
- [x] 首次打开/刷新自动扫描各子项本地目录，文件就绪状态与 POSCAR/INCAR/KPOINTS 内容自动读取
      （已有 POSCAR 无需重复导入）
- [x] POSCAR 导入真实写入本地 `files/POSCAR`；INCAR / KPOINTS / submit.sh 生成与保存同样落盘
- [ ] POTCAR 生成：后端按 POSCAR 元素拼接伪势（pymatgen），当前仅占位
- [ ] 新子项 / 续算创建时真实建立本地目录并复制文件（当前为会话级）
- [ ] 续算真实文件操作：CONTCAR → POSCAR、WAVECAR 续算（可复用 `task_registry.json`
      的 `continuation_rules`，含 walltime_killed / completed 分支）
- [ ] 真实节点状态：由后端 SSH 读取（LSF bnodes / Slurm sinfo）替换 `src/data/mock/cluster.ts`
- [ ] 子任务创建/续算持久化到 `data/projects.json`，并与后端状态机打通
- [ ] 文件预览区改为读取远程真实文件

### 6. 报告模块（Report）

- [ ] 大模型 API 接入（GPT-4 / Claude / DeepSeek），`API 配置` 表单真实持久化（当前仅前端状态）
- [ ] 组装 Prompt：项目进度 + 巡检结果 + 作业信息
- [ ] 固定格式报告生成（标题 / 摘要 / 风险列表 / 建议列表），历史记录落盘到 `data/reports/`
- [ ] 数据收集可参考/复用 `generate_summary_html.py` 的已有逻辑（含结构分析、优先级四象限等）
      （`current_output` 字段已就绪：contcar/outcar/oszicar 路径与 finished/running/failed/waiting 状态）

### 7. 部署与访问

- [ ] 生产部署方案定案：Nginx / IIS 托管 `dist/`，或由后端静态托管前端
- [ ] 内网穿透安全加固：cpolar/ngrok 隧道认证，公网暴露建议加访问控制
- [ ] （可选）HTTPS 配置

### 8. 认证与权限（如需要）

- [ ] 登录与用户管理
- [ ] 操作权限（查看 / 编辑 / 触发巡检 / 生成报告）

### 9. 前端体验优化（可穿插进行）

- [ ] 各页面加载态进一步细化（骨架屏已具备基础版）
- [ ] 全局错误边界与请求失败提示
- [ ] 表格分页/排序服务端化（当前为前端 Mock 分页）
- [ ] antd 体积优化：按需加载或进一步分包（当前已拆 react/antd/motion 三个 vendor chunk）

### 10. 报告结构图渲染（搁置中，2026-09-13 用户决策）

- [ ] **后端结构图改用 ASE + POV-Ray 渲染**：现在的 `report_charts.structure_views()`
      是纯 Python 正交投影 SVG，视觉效果差（用户 2026-09-13 反馈"效果太差"），**先搁置不再投入**，
      后续用 ASE 读结构 + POV-Ray 渲染出高质量结构图
  - 计划：ASE 读 POSCAR/CONTCAR/CIF 建场景 → POV-Ray 渲染三视图或单张 3D 图 →
    替换报告里的 `structure_views` / `structure_matrix`（v0.7.3 起报告与详情页共用同一版式）
  - 依赖：`ase`（pip 可选依赖，已在 `DEPENDENCIES.md` 登记）+ **POV-Ray 二进制**（非 pip，需单独安装/随包分发，注意跨平台与部署体积）
  - 待定：渲染耗时与缓存策略（建议按 CIF 哈希缓存到本地，批量生成报告时不重复渲染）

### 11. 巡检异常规则引擎（搁置中，2026-09-20 用户决策）

- [ ] **把巡检的异常判定从代码搬到可配置规则**：需求是"巡检时判断异常情况，例如离子步很多但力一直在震荡 → 该审视结构合理性"，但**异常种类很多、用户无法一次说全**，所以不写成 `if`，改成"指标 + 规则"两层（用户 2026-09-20：先搁置，记进 TODO）
  - **照抄现成先例**：`backend/report_rules.py` + `defaults/report_rules.json` 已是声明式规则引擎（`when: all/any + field/op/value`、severity、模板文案 + advice、`max_items`、60s 缓存热更新，改 JSON 不用重启、不用动代码），搬一套成 `check_rules.json` 给巡检用
  - **① 指标层（代码，只算不判断，零额外 SSH）**：现有 `force_history[{step,energy,max_force}]`、`neb_band_steps`、`force_max/force_rms/force_converged`、`precision`、`queue_status`、结构 CIF 已经够算出过程形态指标 —— 待补：`force_best`（历史最小最大力）、`stall_steps`（距最近刷新最优值的步数）、`rebound_count_lastN`（最近 N 步反弹次数）、`force_slope`/`force_std_lastN`、`energy_drift`/`energy_jump_max`、`max_displacement`、`lattice_change`、`running_hours`、`min_interatomic_distance`
  - **② 判定层（data/config/check_rules.json）**：规则示例「力震荡」= `steps ≥ 60` **且** `rebound_count_last20 ≥ 4` **且** `force_max_ratio_to_best ≥ 0.8` → warning，建议检查初始结构/磁性/对称性或换更保守的 POTIM/IOPT；同类可扩展：停滞、能量跳变、力平台、结构漂移、原子过近、运行超时、NEB 能垒异常（Ea≈0/过大）、僵尸/挂起续算等
  - **③ 输出层**：一条任务可命中多条 → 巡检结果带 `findings: [{rule_id, severity, category, message, advice}]`，任务级状态取最高 severity；巡检中心行显示最关键那条、详情页列全部；作业管理（v0.8.8 已接 `check.message`）与报告「异常与关注项」复用同一批
  - **免打扰**：按「任务 + 规则」记已读/忽略，或规则加 `cooldown` / 只在"每 25 离子步桶推进"时提醒一次；数值阈值全部放在规则文件里便于自调
  - **实施与验收方式**：第一步把现有硬编码判定（未收敛/低精度/挂起/文件标记）平移到 `check_rules.json` 并验证行为等价；第二步上 5–8 条通用规则；第三步**用历史数据回放**（`data/checks` 有 600+ 归档且含 `force_history`）校准阈值、检查误报，全程不碰远端

### 12. 自动执行 / 大模型动作接口（设计已定，未实现；2026-09-20 审计）

> 目标：支持「定时/自动执行某个动作」，并让大模型在拿到**巡检结果 + 异常汇总**后输出**动作执行命令**（续算、固定原子、创建 NEB…）。用户明确：先出审计与设计，实现待拍板。

**现状审计（73 个接口 = 32 读 + 41 写）**

- 写接口散布在 `jobs`(21) / `groups`(3) / `projects`(4) / `inspections`(3) / `reports`(2) / 配置类(8)，**参数形态不统一**（`{content}` / `{params}` / 空 body / `{atoms}` …）。
- **没有**：统一动作目录、dry-run 前置校验（只有 `submit` 内嵌了五件套非空检查）、幂等键、异步 run 句柄、统一动作台账（仅 `jobs.py::_audit_log` 文本行，且只覆盖 部分动作）、审批闸门、通知出口。
- **长动作同步阻塞**：`create-neb-files` 远端脚本 timeout 300s、`create-frac`/`build-ele-inputs` 180s、`generate-potcar` 120s、全局巡检 75–90s、`continuation` ≈3.5s。
- **已有的自动化**：巡检定时（2h）/报告定时（24h，后台 60s 轮询）、提交成功后 2s 自动同步输入、归档后 1.5s 拉 OUTCAR/OSZICAR、巡检后作废并预热集群采集。
- **已有的"给大模型"半成品**：`report_rules.json` 13 条声明式规则 → `risks[].advice` → `actions.items[{action_id,priority,task_id,action(自然语言),reason,link,risk_id}]` + `llm_context{purpose,key_findings,open_questions,data_references,constraints}` —— 但 `action` 只是句子，没有可执行的动作名与参数。

**建议新增的接口**

| 接口 | 作用 |
| --- | --- |
| `GET /actions` | 动作目录（JSON Schema）：动作名 / 参数 schema / 前置条件 / 风险级别 / 是否幂等 / 是否长任务 |
| `POST /actions/{name}` | 统一执行入口：`{target, params, dry_run, idempotency_key, requested_by, reason}`；`dry_run=true` 只跑 preflight 并返回"将会发生什么"；高风险动作返回 `needs_approval` |
| `GET /actions/runs/{run_id}` | 长动作轮询（accepted → running → done/failed） |
| `POST /actions/runs/{run_id}/approve` / `/cancel` | 审批与取消 |
| `GET /actions/ledger` | 动作台账（谁/为什么/参数/前后状态/结果），建议落 `data/actions/ledger.jsonl` |
| `GET /observe/context?project=&task=` | 一次给出大模型输入：巡检 `findings[]` + 任务事实（force_history/analysis/precision/incar/kpoints）+ 集群快照 + 最近动作历史 |

**动作清单（建议统一命名；括号内为现状）**

- 观测：`observe.context`（缺）、`inspection.detail`（有）
- 巡检：`inspection.run` / `inspection.run_single`（有接口，未动作化）
- 输入：`task.input.sync`（有）、`task.input.set`（有底层 upload-incar/kpoints/poscar，建议只允许"参数档/白名单键"）
- 结构/参数：`task.fix_atoms`（有 selective-dynamics，建议支持 by_index/by_element/by_z/by_displacement 策略）
- 作业：`task.submit`（有 + 前置检查）、`task.stop`（有，**高风险**）、`task.resubmit`（缺）、`task.continuation`（有）、`task.archive`/`unarchive`（有，建议批量）
- 流程：`frac.create`（有）、`ele.build`（有）、`neb.create`（有，需异步）、`neb.replan`（缺：改映像数/SPRING 重插值）
- 报告/通知：`report.generate`（有）、`notify.send`（缺）

**落地顺序**

1. 动作目录 + 统一执行端点（包装现有写接口，内部实现先不动）+ 给 `continuation` / `selective-dynamics` / `create-neb-files` 补 preflight（dry-run）；
2. 动作台账 + `idempotency_key` 去重 + 审批闸门（高风险动作 `needs_approval`）；
3. 长动作异步化（`run_id` + 后台线程 + 轮询 + 失败重试）；
4. 大模型闭环：`GET /observe/context` → 决策 → `POST /actions/{name}`，**先只放开低风险子集**。

**待用户拍板（5 项）**

1. 无人值守白名单：建议放开「巡检、输入同步、参数推送、续算、报告、通知」，`stop`(bkill)/删除/批量归档/改结构必须人工确认。
2. 是否先"LLM 提议 → 人确认 → 执行"，稳定后再对白名单免审。
3. 大模型改 INCAR 的边界：建议只允许选**预设参数档**，不允许任意键值。
4. 台账位置与保留量：`data/actions/ledger.jsonl`，保留最近 N 条？
5. 失败重试策略与通知渠道（UI / 邮件 / 企业微信 / 钉钉）。

### 13. 智能体闭环：巡检 → 判断 → 执行（2026-09-20 用户决策：先写待办，**暂不实现自动执行**）

> 用户目标（原话）："我想做的就是巡检 - 根据结果判断下一个步骤 - 执行，很简单"。
> 约束：**尽量把对系统的影响降到最低**——只读为主、动作最少、可回放、可一键停。

**接口面已就绪**：`API.md`（v0.8.9 新建，观测面 + 执行面 + 闭环建议 + 缺口清单）。现有端点足够支撑闭环，缺的是"策略 + 受控执行 + 台账"。

**设计（三层，互不侵入现有业务代码）**

1. **观测层（已可用，零改动）**：`POST /api/inspections/run`（或等自动巡检）→ `GET /api/inspections`（每个任务一行结论）→ 细节用 `GET /api/inspections/{task_id}`（`force_history` / `neb_barrier` / `precision`）；项目面 `GET /api/projects`（任务自带 `check` 摘要）。
2. **判断层（新增，纯只读）**：规则放 `data/config/agent_rules.json`（照搬 `report_rules.py` 的声明式 `when: all/any + field/op/value` 写法，改 JSON 不用重启），输出 `[{task_id, action, reason, evidence}]`。
3. **执行层（新增，受控）**：白名单动作 + `dry_run` + 幂等键 + 冷却时间 + 台账；**动作内部直接复用现有函数/端点**，不复制业务逻辑。

**低影响原则（写进策略默认值）**

- 默认**只读判断**；动作白名单先只放开 `inspection.run`、`task.continuation`、`task.input.draft`、`frac.create`、`report.generate`；
  `task.submit` / `task.stop` / `task.archive` / 删除 / 改远端文件 **必须人工确认**。
- 每个任务每轮巡检最多 1 个动作；同任务动作冷却 ≥ 巡检间隔（默认 2h）。
- 业务字段判成功：`continuation` 必须 `action="created"`；巡检必须 `failed_batches` 为空；HTTP 200 不算成功。
- 全部动作写 `data/agent/actions.jsonl`（时间 / 触发依据 run_id + 结论 / 动作 / 参数 / 结果 / 是否 dry-run）。
- 调度器默认**关闭**，需在设置里显式开启（复用 `inspection_scheduler` 的后台线程模式）。

**落地顺序**

- [x] 写 `API.md`（观测面 + 执行面 + 闭环建议 + 缺口）——v0.8.9
- [ ] `data/config/agent_rules.json` 草案（先只定义 5–8 条"下一步建议"规则，纯数据）
- [ ] `GET /api/agent/status`（只读）：给定 `project/task` 返回"建议动作 + 依据 + 前置是否满足"，**零副作用**
- [ ] `POST /api/agent/execute`：`{action, target, params, dry_run, idempotency_key}`；先只实现白名单 2 个动作（`inspection.run`、`task.continuation`）+ dry-run（复用现成 preflight）
- [ ] 台账 `data/agent/actions.jsonl` + `GET /api/agent/actions`（回放/审计）
- [ ] 可选：`agent_scheduler`（默认关）与简单管理页（开关 / 冷却 / 白名单 / 最近动作）
- [ ] 与 §14 打通：智能体用**独立长期 token**（`role=agent`），只允许白名单动作

### 14. 账号 + 认证 + 授权（2026-09-20 用户要求：先方案与清单，**暂不动代码**）

> 用户要求：① **认证**——客机必须登录后才能操作系统，否则无法调用；② **授权**——每个账号只能管理和查看**自己创建的项目**。

**方案总览**

| 层 | 方案 | 说明 |
| --- | --- | --- |
| 用户存储 | `data/config/users.json` | `{username, password_hash(scrypt), salt, role, created_at, disabled}`；**零新依赖**（`hashlib.scrypt`） |
| 会话存储 | `data/config/sessions.json` | 只存 `token` 的 `sha256` + username + 过期时间 + last_seen（`data/` 泄露也拿不到可用 token） |
| 认证 | `POST /api/auth/login` → `Bearer token` | 登录换取随机 token（`secrets.token_urlsafe(32)`）；滑动过期默认 14 天；失败限速（5 次/15 分钟） |
| 认证入口 | FastAPI 中间件 + 白名单 | 对 `/api/*` **除白名单外一律 401**；白名单仅 `POST /api/auth/login`、`GET /api/health`；`/docs`、`/openapi.json` 也要保护 |
| 长期 token | `POST /api/auth/tokens` | 给智能体/脚本用（可命名、可设有效期、可吊销）；`GET/DELETE /api/auth/tokens` 自查自撤 |
| 授权模型 | `project.owner` + 角色 | `admin` 看全部；`user` 只看/改自己的；`agent` 只允许白名单动作、无 UI |
| 授权实现 | `permissions.py` 统一入口 | `visible_projects(db, user)`（列表过滤）+ `ensure_owner/ensure_task_owner`（单对象校验，越权 403） |
| 前端 | 登录页 + token 注入 | `request()` 统一带 `Authorization`；401 → 跳登录；顶栏显示用户名/退出；按角色隐藏入口 |

**为什么不选 JWT**：本项目是文件型存储、单机部署、需要"立即吊销"能力（改密/下线/智能体 token 作废）；服务端会话表零依赖、语义直白，比 JWT + 吊销列表更简单可靠。

**授权要覆盖的查询面（容易漏）**

- 列表：`GET /projects`、`GET /inspections`、`GET /inspections/meta`、`GET /dashboard/*`、`GET /reports/project/list`、`GET /reports/groups*`、`GET /free-energy/{gid}/summary`、`GET /jobs/nodes`、`GET /aux-molecules`。
- 单对象：`POST /jobs/**`（关键：`jobs.py::_resolve_task(task_id)` 是所有作业动作的唯一入口，**在它里面加 owner 校验即可覆盖提交/续算/上传/归档等全部写操作**）、`/groups/{gid}`、`/reports/project/{report_id}`、`/inspections/{task_id}`、`/projects/{id}`。
- 全局派生数据：`data/checks/*`（巡检归档按 task_id 索引，需 join 任务 owner）、`data/dashboard/core_history.json`（集群采样，项目聚合要按可见项目过滤）、`data/audit_submit.log`。
- 共享资源：SSH 仍是**同一个 HPC 账号**（`mdye`）→ 鉴权只解决"谁能看/改哪些项目"，不解决"算力配额隔离"；若将来要按人隔离 HPC 凭据，另立条目。

**实施清单（分 5 步，每步可独立验收）**

- [x] **① 用户与会话底座**（**2026-09-20 完成**）：`backend/auth.py`（scrypt 哈希/校验、token 生成与 sha256 存储、会话读写/清理、`authenticate`/`find_user`/`create_session`/`verify_token`/`revoke_*`、`ensure_users_file`）+ `scripts/set_password.py`（列表/建号/改密/禁用/启用/会话/强制下线）+ `main.py` 启动钩子（首次启动自动建 `zouyuxi`(admin)，随机密码打印到 stdout 与日志，并清理过期会话）。
  - 数据文件按约定落到 `data/users/users.json`（`user_id/username/password_hash/role/enabled/created_at`）与 `data/users/sessions.json`（`token_hash/user_id/created_at/last_seen/expires_at/name`）；原子写 + `fcntl.flock`（跨进程）+ 进程内 RLock，权限 0600/0700；**零新依赖**。
  - 附带语义：改密/禁用会**自动吊销该用户全部会话**（凭据变更即下线）；`list_sessions` 对外只回显 `token_hash` 前 12 位；`verify_token` 的 `last_seen` 每 5 分钟最多写一次。
  - 验收（隔离数据目录 + mock SSH 启动真实 app，47 项断言全过）：首次启动建 admin/幂等、哈希含随机 salt、建号/改密/禁用/启用、旧密码与旧会话失效、token 只存哈希、过期清理、12 线程并发建号无丢失、CLI 全部子命令。
- [x] **② 认证上线（先认证、后授权）**（**2026-09-20 完成，未提交**）：`backend/routers/auth.py`（`login`/`logout`/`me`/`tokens`）+ 全局中间件白名单 + `/docs` 保护；前端登录页、`request()` 注入 token、401 统一跳登录、顶栏用户菜单
  - 验收：无 token 调 `/api/projects` → `401`；登录后可正常用；错密码限速生效；`/docs` 未登录不可读
- [x] **③ 归属字段与迁移**（**2026-09-20 完成，隔离目录已验证；生产数据迁移待用户确认后执行 `--apply`**）：`projects.json` 增加 `owner`/`created_at`；`scripts/migrate_owners.py`（dry-run 默认，`--apply` 写入）把现有 4 个项目归给指定管理员；`mappers` 输出 `owner`
- [ ] **④ 授权生效**：`backend/permissions.py`（`visible_projects` / `ensure_owner` / `ensure_task_owner`）接入 `projects / jobs(_resolve_task) / groups / free_energy / reports / inspections / dashboard`；`_audit_log` 增加 `username` 字段
  - 验收：A 账号看不到 B 的项目（列表 + 单对象 + 巡检 + 报告 + 总览统计）；直接拿 B 的 task_id 调动作 → `403`；admin 可见全部
- [ ] **⑤ 收尾**：前端角色化（隐藏他人项目、admin 多"全部项目"视图）、智能体长期 token（与 §13 白名单打通）、可选加固（HTTPS、在线会话与强制下线、密码策略、操作日志页）

**兼容与回滚**

- 加鉴权后**所有脚本/自动化/智能体都要带 token**（含本文档 §13 的动作）；上线前先准备好给每个外部调用方发 token。
- 回滚方式：`git revert` 对应提交 + `systemctl restart vasp-manager`。**不做"运行时关闭鉴权"的开关**（避免留后门）；排障期如确需临时放开，只在隔离测试实例上用独立数据目录。
- 顺序建议：**先认证（②）让系统"必须登录"，再授权（③④）做项目隔离**；③ 的迁移脚本在授权上线前跑完，避免上线即"看不到任何项目"。

---

## 已知限制（2026-09-13 更新）

- SSH 连接、测试握手、保活延迟均已是真实后端行为（连接池 + `/api/ssh/status`），不再是前端模拟
- 服务器配置已落到 `data/config/servers.json`（探测/连接等 UI 状态仍在浏览器 localStorage）
- 续算、提交、停止、频率矫正输入构建、NEB 输入构建、ele 输入构建均已真实落库 + 远端执行；
  POSCAR/INCAR/KPOINTS/submit.sh 可真实读写；**POTCAR 仍为占位**
- 节点/队列状态已接真实 `bhosts`/`bqueues`（SSH 失败时回退模拟，60s 缓存）
- 报告模块（智能报告页）仍为前端 Mock：未接大模型 API、未落盘 `data/reports/`
- 无用户认证，公网穿透暴露时存在安全风险，仅建议临时演示

---

## 建议推进顺序

1. **后端骨架 + SSH 真实连接**（打通配置页与顶栏状态）
2. **文件型存储 + 项目/任务 CRUD API**（总览与作业管理接真实数据）
3. **巡检调度 + 结果读取**（巡检模块接真实数据）
4. **VASP 输入文件生成 + 续算**（作业管理核心功能）
5. **大模型报告生成**（报告模块核心功能）
6. **部署上线 + 认证权限**（按需）
