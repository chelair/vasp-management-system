# 待办清单（TODO）

> 创建时间：2026-08-24
> 适用项目：`vasp-management-system`（v0.2.0）
> 勾选约定：`[ ]` 未开始 · `[x]` 已完成

## 当前进度概览

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
