# 待办清单（TODO）

> 创建时间：2026-08-24
> 适用项目：`vasp-management-system`（v0.2.0）
> 勾选约定：`[ ]` 未开始 · `[x]` 已完成

## 当前进度概览

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
- [x] 结果本地持久化：归档 `data/checks/check_results_*.json`，重开网站显示上次巡检结果
- [x] 本地模拟模式（VASP_SSH_MOCK + 夹具脚本）用于离线验证巡检流程
- [x] 清理演示项目：删除种子数据与前端 Mock 回退
- [x] 数据迁移：旧项目真实数据（项目库/配置/项目目录/备份/巡检结果）已迁入本项目 `data/`，
      运行不再依赖旧项目路径（旧项目仅作功能迁移参考，封装打包不漏文件）
- [x] 真实巡检验证：对 Ag_20260830（/data/gpfs03/mdye/projects/test/Ag_20260830）完成一轮真实巡检

**尚未开始（其余模块）**

---

## 待完成清单

### 1. 后端 API 开发（最高优先级，其他模块依赖此步）

- [x] 定后端技术栈：Python + FastAPI + Paramiko（`backend/`，`python backend/run.py` 运行）
- [x] 新增项目 API：`POST /api/projects`（校验 → 优先级计算 → 本地目录 → 可选远程同步 → 原子写库 + 备份）
- [x] 基础接口：`GET /api/projects`、`GET /api/servers`、`GET /api/task-types`、`GET /api/health`
- [ ] 设计其余 REST 接口清单（任务 / 巡检 / 报告 / SSH）
- [ ] 真实 SSH 连接服务（握手、保活、断线重连；当前 Paramiko 仅支持远程 mkdir，前端测试仍为模拟）
- [ ] 替换前端 `src/api/ssh.ts` 的三个函数：
  - `fetchServerConfigs` → `GET /api/ssh/config`
  - `persistServerConfigs` → `PUT /api/ssh/config`
  - `testRemoteConnection` → `POST /api/ssh/test`（真实握手）
- [x] 顶栏 SSH 状态改为轮询 `GET /api/ssh/status`（后端常驻连接池真实状态，前端回退 UI 状态）
- [ ] 前端请求封装：统一 loading / 错误提示（当前 `src/api/client.ts` 仅为模拟延迟）

### 2. 文件型存储（网站同级目录，不使用数据库）

- [x] 创建 `data/` 目录结构：`data/projects.json` + `data/config/` + `data/projects/` + `data/backups/`
- [x] 原子写入 + 自动备份机制（保留 20 份，对齐 `project_db.py`）
- [x] 首次启动自动生成 `data/config/`（servers.json / settings.json / task_registry.json）；**不再写入示例项目**
- [ ] `data/checks/`（巡检结果，对应 `check_results_*.json`）
- [ ] `data/reports/`（生成报告）
- [x] 前端 SSH 配置页改由后端读写 `data/config/servers.json`（连接/延迟等 UI 状态仍留 localStorage）

### 3. 总览模块（Dashboard）

- [x] 「新增项目」表单接真实后端：服务器下拉 + 子任务动态列表 + 后端校验/优先级计算/目录创建
- [ ] 统计卡片 / 项目进度 / 剩余时间接真实统计接口（当前进度由后端按任务状态派生）
- [ ] 近 7 天趋势图接后端统计接口（当前为 Mock 的 `src/data/mock/projects.ts`）
- [x] 最近任务表接 `GET /api/projects` 数据

### 4. 巡检模块（Inspection）

- [x] 「立即巡检」调真实 API：筛选任务 → 上传 `batch_check.py` → 服务器批量解析 → 状态机回填 → 归档 `data/checks/`
- [x] 巡检结果从 `data/checks/` 读取并按任务合并展示（前端筛选/搜索保留）
- [x] 异常项与任务状态联动（zombied / 力未收敛 / 文件缺失等自动标记）
- [ ] 后端定时任务：APScheduler 每 2 小时自动触发（当前自动指示为配置信息，未真正调度）

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

## 已知限制（当前演示版）

- SSH「测试连接」为前端模拟握手，未建立真实连接
- 服务器配置保存在浏览器 localStorage，多浏览器/多设备不共享，正式版需迁移到 `data/config/servers.json`
- 作业管理的「续算」「新子项创建」为前端会话级交互；POSCAR/INCAR/KPOINTS/submit.sh
  已可真实读写本地目录；POTCAR 仍为占位，节点状态已接真实 bhosts（SSH 失败时回退模拟）
- 无用户认证，公网穿透暴露时存在安全风险，仅建议临时演示

---

## 建议推进顺序

1. **后端骨架 + SSH 真实连接**（打通配置页与顶栏状态）
2. **文件型存储 + 项目/任务 CRUD API**（总览与作业管理接真实数据）
3. **巡检调度 + 结果读取**（巡检模块接真实数据）
4. **VASP 输入文件生成 + 续算**（作业管理核心功能）
5. **大模型报告生成**（报告模块核心功能）
6. **部署上线 + 认证权限**（按需）
