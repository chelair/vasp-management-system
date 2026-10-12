# 待办清单（TODO）

> 创建时间：2026-08-24
> 适用项目：`vasp-management-system`（v0.8.8）
> 勾选约定：`[ ]` 未开始 · `[x]` 已完成

# 发现问题


## 当前进度概览

**待开发（报告解析与前端图表，2026-09-13 核对）**

- [x] 报告页接入组数据：自由能台阶图（PathStepChart / PathSummaryModal）、NEB 能垒图（nebef.pl 散点连线）——v0.4.1 / v0.4.5 已完成
- [ ] frac 频率输出解析（ZPE / 自由能矫正），回填组数据 `frac.zpe / correction`
      （当前矫正值来自 vaspkit 501 单点调用，未解析频率输出文件，需要解析虚频大小以及数量）—— **下一个优先项**


**尚未开始（其余模块）**

---

## 待完成清单

### 1. 后端 API 开发（最高优先级，其他模块依赖此步）



### 2. 文件型存储（网站同级目录，不使用数据库）

- [ ] `data/reports/`（生成报告）
- [x] 前端 SSH 配置页改由后端读写 `data/config/servers.json`（连接/延迟等 UI 状态仍留 localStorage）

### 3. 总览模块（Dashboard）

- [x] 项目进度四象限气泡图 + 进度列表（逾期/落后计划提示）
- [ ] 队列预计等待时间估算、趋势回溯（需外部数据源）

### 4. 巡检模块（Inspection）

- [x] NEB 过渡态看板（nebef.pl）：巡检时运行 nebef.pl 回传各映像 受力/能量/相对能垒，
      详情页散点连线能垒图（第四列相对能垒），悬停显示能量与受力
- [ ] NEB 结构看板（映像结构图矩阵，VESTA 三行对比）——搁置，后续实现
- [x] 后端定时巡检（v0.6.2）：自建后台线程调度（未引入 APScheduler），每 2 小时自动触发全局巡检，
      可在巡检中心开关

### 5. 作业管理模块（Jobs）

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
- **已有的自动化**：巡检定时（2h）/报告定时（24h，后台 60s 轮询）、提交成功后 2s 自动同步输入、归档后 1.5s 拉"本次计算用到的文件"（普通六件套；NEB 按映像目录）、巡检后作废并预热集群采集。
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

### 13. 智能体闭环：巡检 → 判断 → 执行（规则化自动执行已在 v0.9.6 落地）

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
- [x] **④ 授权生效**（**2026-09-20 完成，隔离目录已验证；生产待确认后部署**）：`backend/permissions.py`（`visible_projects` / `ensure_owner` / `ensure_task_owner`）接入 `projects / jobs(_resolve_task) / groups / free_energy / reports / inspections / dashboard`；`_audit_log` 增加 `username` 字段
  - 验收：A 账号看不到 B 的项目（列表 + 单对象 + 巡检 + 报告 + 总览统计）；直接拿 B 的 task_id 调动作 → `403`；admin 可见全部
- [x] **⑤ 收尾（前端角色化 + 403 处理 + 登录审计/安全加固，v0.9.5）**（**2026-09-20 完成，隔离目录已验证；生产待部署**）：前端角色化（隐藏他人项目、admin 多"全部项目"视图）、智能体长期 token（与 §13 白名单打通）、可选加固（HTTPS、在线会话与强制下线、密码策略、操作日志页）

**兼容与回滚**

- 加鉴权后**所有脚本/自动化/智能体都要带 token**（含本文档 §13 的动作）；上线前先准备好给每个外部调用方发 token。
- 回滚方式：`git revert` 对应提交 + `systemctl restart vasp-manager`。**不做"运行时关闭鉴权"的开关**（避免留后门）；排障期如确需临时放开，只在隔离测试实例上用独立数据目录。
- 顺序建议：**先认证（②）让系统"必须登录"，再授权（③④）做项目隔离**；③ 的迁移脚本在授权上线前跑完，避免上线即"看不到任何项目"。

### 15. 自动化按项目归属鉴权（2026-09-21 用户要求：**先写待办，暂不动代码**）

> 原话："这里自动化暂时只对管理员开放。后续要接入鉴权，防止自动化执行到不属于自己的项目（先写到todo）"。

**现状（2026-09-21，v0.9.12）**

- 自动化系统（`/api/actions/*`、`/api/automation/*`）**全部是 admin-only**：后端每个接口都走 `permissions.ensure_admin`，前端「自动化」页与 `/automation` 路由走 `AdminRoute`，侧栏入口也只对 admin 渲染。
- 规则是**全局**的（`data/config/rules/*.json` 不带归属），动作以系统身份执行：审计里 `username="automation"`，因此**规则命中后不会做项目归属校验** —— 只有 admin 能配置规则这一点在兜底。
- 风险：一旦把自动化开放给普通用户，若不校验归属，A 用户可写一条规则对 **B 的项目**执行续算/提交（等于越权写）；而且如果只在创建规则时校验，之后目标项目被移交/共享也会漏。

**目标**

普通用户也能用自动化（自己的规则作用于自己的项目），且**创建期与执行期都要校验归属**；admin 仍可维护对所有项目生效的全局规则。

**设计要点（建议实现顺序）**

1. **规则归属**：`data/config/rules/*.json` 增加 `owner`（用户名；缺失视为 admin/全局的历史规则）。改动更小的备选：在 `data/config/automation.json` 里加 `rule_owners: {rule_id: username}` 映射。
2. **创建/编辑校验**：`owner` 取当前登录用户（admin 可显式指定他人的规则）；非 admin 提交的"作用对象"（具体项目 / 任务 / 组）必须落在 `permissions.visible_projects()` 内，越权直接 403（复用 `ensure_project_owner`）。
3. **执行期校验（最关键）**：调度层在 `preflight` 之前，用**规则 owner 作为行动人**再校验一次任务归属（`permissions.ensure_task_owner(task, {"username": rule_owner})`）；不通过 → 审计 `blocked`（reason 写明"不属于规则所属用户的项目"），**不执行、不消耗冷却、不计入执行次数**。这样即使项目后来被移交/共享，也不会跑到别人的数据上。
4. **事件过滤**：巡检事件按 task 匹配规则时，先按规则 owner 过滤；不属于 owner 的任务直接 skip 并写 `skipped` 审计。
5. **定时 scope 语义**：`scope=project:<名>` 只允许 owner 可见的项目；`scope=all` 表示"owner 可见的全部项目"（而不是全库）。
6. **前端**：自动化页对普通用户开放后只列自己的规则；「作用对象」下拉只给 `visible_projects`；admin 保留"全部规则"视图；`AdminRoute` 改为登录即可访问（页面内再按角色收敛）。
7. **审计与可见性**：决策日志/运行记录增加 `rule_owner`、`requested_by`（谁创建、谁手动触发），`/api/automation/decisions`、`/api/automation/runs` 对非 admin 只返回自己规则的记录。
8. **迁移**：历史规则无 owner → 视为 admin/全局保持不变；可选脚本 `scripts/migrate_rule_owners.py`（dry-run 默认，`--owner zouyuxi --apply` 补归属）。
9. **与 §12/§13 打通**：智能体长期 token（`role=agent`）同样需要 owner/scope，动作层应把"token scope 校验 + 项目归属校验"收敛到同一个 `permissions` 入口，避免两套规则打架。

**验收（将来实现时）**

- 普通用户创建规则时，作用对象只能选自己的项目/任务/组；直接构造他人项目的条件 → 403。
- 用 admin 把某条普通用户规则的目标改成他人项目后，该规则执行被 `blocked`（执行期校验兜住），审计有明确 reason，且不消耗冷却/计数。
- A 用户的规则在任何情况下都不会对 B 的项目产生动作（决策日志可查 blocked）。
- 非 admin 的决策日志/运行记录只包含自己的规则；admin 不受影响。
- 未开放前（当前状态）保持 admin-only 不变：后端 403、前端隐藏入口。

### 16. 接力动作的兜底（2026-09-21 事故复盘，**未实现**）

> 来源：排查"续算建了 conN 却没提交"时发现主因是字段保存 bug（v0.9.13 已修），但也暴露了接力语义上的两个缺口。

1. **接力提交被拦后不会补**：`follow_up_action` 只在主动作成功的那一次投递。如果这次被 `blocked`
   （冷却中 / `MANUAL_HOLD_SECONDS=300` 内有人手动操作过该任务 / 任务级锁忙），动作不会重试；
   而续算成功后**父任务状态会回落成 `pending`**，规则的 `status` 条件（通常写 completed/zombied/unconverged）
   就不再命中，直到该 conN 自己跑完被巡检改回状态 —— 也就是"续算建了但一直没提交"。
   建议：① 接力 blocked 时落一条"待补"记录，下一轮巡检事件优先补投（同样受冷却/上限约束）；
   或 ② 增加一个条件字段（如 `pending_continuation`：父任务下存在未提交的 conN），让规则能直接命中。
2. **规则"静默不匹配"不易察觉**：父任务变 `pending` 后，规则既不报错也不命中，页面上看不出"这条规则
   此刻没人可作用"。建议决策日志/规则列表补「最近命中时间 + 最近一次 skip 原因」，一眼能看出规则是否还活着。

### 17. 「复制 INCAR 参数到其他作业」是否要支持"同时写远端"（2026-09-21 待用户确认）

> 背景：用户问"点击后是不是直接远端运行 cp"，排查后确认现状**只写目标任务的待生效草稿、不碰远端任何文件**
> （v0.9.18 有实测证据：远端 INCAR 哈希不变、审计里没有远端命令；顺便把容易误解的按钮文案
> 「同步到 N 个作业」改成「记为 N 个作业的待生效修改」）。

> 进展（v0.9.19）：用户报"点击后没反应"的根因已修——自由能/NEB **组页面**里 `selectedTask` 是 `null`，
> 来源作业取不到就静默 return（弹窗不关、无提示、零请求）；现在打开弹窗时显式记住来源作业、取不到会明确报错。
> 下面"是否同时写远端"的选择仍然待定。

**待定选项**

1. 维持现状（推荐先这样）：只写草稿，目标作业下次续算时应用；要立即生效就在目标作业上点「同步到远端」。
2. 加一个「同时同步到远端」勾选项：勾上后对每个目标任务立刻调用 `upload-incar`
   （`modify_incar(远端旧 INCAR, params)` 合并 + 旧文件备份 `old_INCAR`，**不是整文件覆盖**）。
   风险：会直接改动别的作业正在使用的输入文件；建议要求"目标作业不在 queued/running"才允许，
   并把结果改成逐个汇报成功/失败（现在 `Promise.all` 会静默吞掉单项失败）。

两种做法的差异只在"是否立刻写远端"，草稿链路一样；用户确认后再动代码。

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
