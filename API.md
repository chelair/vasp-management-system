# 接口文档

维护日期：2026-10-28；应用 **v1.1.4**。本文维护HTTP/工具合同，不维护逐轮发布流水账。源码与已认证 `/docs`、`/openapi.json` 为准；[当前状态/运维](process.md)、[AI工作台](docs/ai-workspace.md)、[报告](docs/reports.md)、[执行](docs/execution.md)。

## 项目需求登记与预期对应

通用会话提供 `get_project_setup_options/create_project_from_request`；创建成功只允许从通用会话绑定新项目，不改绑已有项目会话。项目会话增加 `create_calculation_contents/update_project_details/get_project_requirements/save_project_requirements`。均限登录的人类用户并逐项目鉴权；复用原项目/分组创建核心，仅本地登记，不接SSH或提交。文本引用真实用户消息，原文与AI解释分开；重复登记核对类型和数量，冲突不覆盖。

| 方法与路径 | 合同 |
| --- | --- |
| GET `/api/projects/{id}/requirements` | 最新原文、source_hash/revision、计算内容/预期/任务绑定和已有Python比较；只读本地证据并更新派生结果，不发模型/SSH |
| POST `/api/projects/{id}/requirements/refresh` | 异步整理待更新对应表，使用当前用户自己的默认模型连接；原文不变，无连接/失败保留pending |

ProjectIn新增可选original_request（最多16000字符），既有description/calc_description/expected_results与deadline不变。save_project_requirements传source_hash、expected_revision和mapping；后端拒绝迟到版本、跨项目任务、伪造引文和未给定的能量。update_project_details只允许四个资料字段，并要求当前source_hash。后台失败不改变项目保存成功状态。

巡检事件只按已有绑定运行adsorption.estimate和固定数值比较；没有预期不生成排序，未支持性质只登记目标。AI上下文附有界摘要，完整关联按需读取。吸附能专题只在两组实际输入与对应表比较完全一致时冻结预期对照；历史观测不套当前结果，查看/导出不重读。完整边界见[项目需求](docs/project-requirements.md)。

## 默认简明专题报告

沿用 `/api/ai/chat` 私有连接、项目会话和SSE。默认工具 `search_report_data` → `create_topic_report`，必要时 `update_topic_report`；模型可以理解别名并自行绑定授权任务/角色，用户无须提供内部ID。create会直接构建并保存独立topic，不强制四轮分步编排。

| 方法与路径 | 合同 |
| --- | --- |
| POST `/api/reports/topic/quick` | conversation_id、question、request，可选project_ids；创建独立简明报告 |
| POST `/api/reports/topic/{id}/questions` | expected_revision、answers，可选布尔 continue_analysis（默认 false）；选择/自定义回答保存后，可继续原 AI 对话 |
| PUT `/api/reports/topic/{id}/content` | expected_revision、title/notes/blocks/deleted_block_ids/show_warnings；路径诊断可传 assessment={conclusion,recommendation}，仅定性文字；不修改科学结果 |
| POST `/api/reports/topic/{id}/rebuild` | 生成新独立报告，旧报告保留 |

create请求支持 property_id/model_queries、adsorbate_query、targets、title/notes/show_warnings 等。targets的角色可绑定 task_id/project_id/observation_id，也可用 energy_ev 或 energy_value+energy_unit，并附 label/source_quote/note。用户给定的参考能量不要求对应任务，服务端记录原话/归属，转换单位并由Python计算；AI解释或假设不能冒充验证记录。

吸附能默认 `adsorption.estimate`（adsorption.minimum.1.1.0），三个有限能量即给初步值，质量问题为提醒。简明报告不展示报错、缺项或警告，冻结风险和来源保留；show_warnings保留兼容。所有操作重新鉴权、no-store，修订冲突409；真正缺能量/角色时返回明确问题/操作建议。

`neb.barrier` 默认简明入口生成端点结构诊断（`reaction.topic.1`），不冒充已取得可靠能垒。create 支持 objective、定性 assessment、bond_elements/fragment_elements/contact_elements，以及 targets[].path。get_project_research_context 返回项目目标与端点关联；analyze_reaction_path 按需读取固定结构和同目录参数，返回反应键候选、片段内部距离变化、O–Li 接触变化、约束及来源。默认本地保存结构，远端须明确选择；不提交计算。

工具摘要 `questions` 用于对话确认，`conversation_notes` 仅供 AI 在对话简短总结。路径报告摘要包含冻结 path_evidence，后续回答不必重新读取。问题回答携带 continue_analysis=true 时，沿用原 start_run 与幂等 request_id，并在运行快照中记录 topic_continuation（原报告编号、修订、性质和已保存回答）。该运行误调 create/prepare 时返回原报告及续写指引，不创建副本或重读科学输入；其他性质拒绝混入。重新生成保留关联，旧卡片运行可从幂等编号恢复关联；仍按用户和对话鉴权。回答已保存但继续失败时返回 continuation_error，错误不写报告。详见 [路径诊断合同](docs/reaction-diagnosis.md)。

## 模型思考深度

连接POST/PUT支持 reasoning_api=auto|openai|deepseek、reasoning_effort=default|none|minimal|low|medium|high|xhigh|max；可选组合由后端型号能力表验证，不是所有模型都支持全部值。未知自动模式不附加猜测参数，旧字段/密钥/连接ID保留。

`GET /api/ai/chat/reasoning-capabilities?base_url=...&model=...&reasoning_api=auto` 只读本地定义，不请求模型。公开连接附能力和生效档位，verified仅指内置文档匹配，不是账号实测。DeepSeek工具轮思考只在运行内存延续，不进SSE/历史；不静默降深度或重试付费请求。设置和发送键旁快捷档位已接前端。

## 项目托管 M0（计划与预览）

| 方法与路径 | 用途 |
| --- | --- |
| GET `/api/managed` | 当前用户计划和execution_enabled摘要；不代表计划执行已接通 |
| POST `/api/managed/plans` | 保存项目目标/阶段/task_overrides/resource_rules |
| GET/PATCH `/api/managed/plans/{id}` | 查询/更新，PATCH须revision；冲突409 |
| POST `/api/managed/plans/{id}/status` | status=active/paused/ended；结束计划仅人工 |
| GET `/api/managed/plans/{id}/candidates` | 确定性任务排序 |
| GET `/api/managed/plans/{id}/resource-plan` | 读取共享真实资源，过滤/评分，不提交 |
| GET `/api/managed/plans/{id}/script-preview?index=0` | 只生成脚本预览，不写远端 |

工具 get_managed_plans/create_managed_plan/update_managed_plan/set_task_priority 可在项目AI会话保存业务计划。人工锁定不能被AI覆盖；权限/字段范围以managed_plan/managed_tools为准。计划存data/managed_plan.json，任务/作业真相仍属原项目库和执行台账。**没有从M0计划到巡检后自动提交的执行接线**，详见 [托管说明](docs/managed-compute.md)。

## 科学性质与正式验证

`GET /api/properties/recipes`、`GET /api/properties/discover`、`POST /api/properties/evaluate`、`GET /api/properties/reports/{id}`。固定PropertyRecipe、七类输入状态、逐项目鉴权、精确观测与Python运算；未知性质UNSUPPORTED。严格接口不接受任意公式或替代任务能量；不要用这条限制拒绝简明报告中的用户给定输入。

中性单O空位缺μ_O不能出绝对值；共同参考且其他前提成立时可以出B−A。人工μ_O按每O给数值/来源/条件，聊天严格工具不提供该设置字段。带电缺陷不套中性公式。吸附严格配方adsorption.simple与初步adsorption.estimate并存，参考类型periodic/isolated_molecule各有前提。[科学规范](ANALYSIS_FEATURES.md)

原参数证据：`GET /api/jobs/tasks/{id}/input`附任务族最近5次applied_history，不含草稿。AI按需 get_task_parameter_history/get_remote_task_evidence，后者限定证据token、目录和stale_evidence/source_mismatch/missing_parameters原因，只读、不触发巡检/提交。[工作台证据](docs/ai-workspace.md)

单OPT：`POST /api/agent-execution/opt-runs`创建；`GET /{id}`查询；`POST /{id}/step`推进；`POST /{id}/control`接收pause/resume/close，不停止远端作业。创建要求task_id/grant_id，可选max_steps（默认30）、max_repairs（默认1）、nsw_increment/nsw_max（默认0）、min_force_improvement（默认0.05）、connection_id。模型当前只审阅有限候选，不是完整项目规划执行。[执行边界](docs/execution.md)

完整报告AI注解：项目ai_report_notes_enabled默认false，开关位于智能报告页。`GET /api/reports/project/{id}/notes/ai-status`，`POST .../notes/ai-preview`接收key/connection_id仅返回草稿；原PUT notes可带draft_token/expected_revision及restore_previous。普通generate不等待模型，不接HPC工具。

## 高级分步专题接口（兼容）

复用原 `/api/ai/chat` 会话、连接凭据与SSE。项目会话启用原工作区后保留6个分步工具：`list_topic_projects`、`prepare_topic_report`、`plan_topic_report`、`write_topic_draft`、`save_topic_report`、`get_topic_report`；已有 `get_property_recipes` 提供配方定义。工具只保存专题文档，不新增计算/SSH/输入操作。

新增人工登录用户接口 `/api/reports/topic`；每次读/编辑/导出重新检查报告所有者及全部项目权限，Agent不能使用。完整协议与限制见 [R4](docs/reports.md)。

| 方法与相对路径 | 用途 |
| --- | --- |
| GET 空路径 `?conversation_id=...` | 当前用户报告目录，可按原对话筛选 |
| POST `/prepare` | `{conversation_id, question, request, project_ids?}`；先冻结R3/R2证据，独立ID |
| GET `/{id}?revision=...` | 最新或历史冻结版本；附当前新鲜度提示 |
| POST `/{id}/plan` | `{expected_revision,title?,sections?,selections}`；验证block_id/来源/相关性/可用性 |
| POST `/{id}/draft` | `{expected_revision,paragraphs:[{section,title,text,kind}]}`；必须先有计划 |
| PUT `/{id}` | 展示编辑：`expected_revision,title?,sections?,blocks?,hidden_block_ids?,deleted_block_ids?` |
| POST `/{id}/save` | `{expected_revision}`；草案标为保存，不覆盖完整报告 |
| POST `/{id}/resolve` | `{expected_revision,targets?,reference_report_id?,common_oxygen_reference?}`；显式选择产生新版本 |
| POST `/{id}/regenerate` | `{expected_revision,block_id,connection_id}`；私有连接重写单段，失败原子保留 |
| POST `/{id}/preview` | 空对象；预览已保存的冻结展示版本 |
| GET `/{id}/export.html?print=false` | 自包含HTML；`print=true`为PDF打印入口 |

`request` 支持R3的5种配方与`dos.comparison`（仅已有DOS/PDOS可视化，不新增派生公式）、1至4个`model_queries`、可选精确`targets`/已有人工氧参考报告ID。未知性质返回UNSUPPORTED缺口报告。严格prepare/evaluate接口不接受自定义公式、替代任务能量或任意文件路径；默认简明工具可以接收来源明确的用户给定能量，不适用这里的严格selector限制。多位点/多参考态保留候选；`common_oxygen_reference`在没有人工参考时仅形成待确认条件。

高级分步草稿文字中 `[[F01]]` 由Python展开为冻结事实的值/单位/状态；`[F01]` 为引用。拒绝自行填写数字、替代公式、无效事实引用和自定义HTML组件。AI原文与用户文字分离，PUT不能写`data`、Evidence、renderer或科学结果。冲突409附`current_revision`；无效400、不可访问/不存在403或404。所有报告响应禁止缓存。


## 1. 基础约定

| 项 | 说明 |
| --- | --- |
| Base URL | `http://192.168.1.20:3001/api`（局域网）· `http://10.147.20.10:3001/api`（ZeroTier） |
| 请求/响应 | JSON（`Content-Type: application/json`）；统一信封 `{"success": bool, "message": str, "data": {...}}` |
| 失败 | HTTP 4xx/5xx 且 `success=false`；`data.errors` 可带明细（例：提交前非空检查会返回缺失文件名） |
| 常见状态码 | `400` 参数/前置不满足 · `404` 任务/项目不存在 · `409` 重复操作（如重复提交、重复 conN） · `500` 服务端异常（含远端命令失败） |
| 时间 | ISO 字符串（服务器时区 `Asia/Shanghai`） |
| 任务状态 | `pending / queued / running / completed / unconverged / zombied / archived` |
| 巡检状态 | `normal / warning / error / low_precision / pending / archived` |
| 授权 | **v0.9.2 起按项目归属过滤**：普通用户只能看到/操作 `owner` 是自己的项目，越权一律 `403`（不返回 404）；admin 全可见。详见 §2.3 |
| 认证 | **v0.9.0 起强制登录**：除 `POST /api/auth/login`、`GET /api/health` 外，所有 `/api/**` 与 `/docs`、`/openapi.json` 都要 `Authorization: Bearer <token>`，未登录一律 `401`。详见 §2 |
| 执行方式 | 部分原业务HTTP同步；统一动作/AI有后台run与查询/SSE，不自动重发超时写操作 |
| 幂等 | 受控网关与统一动作支持稳定意图键、任务族锁和未对账阻塞；不能假定任意写接口均可安全重试 |
| 审计 | 原提交文本日志、automation审计及agent_execution持久动作台账；具体路径由对应模块维护 |

```bash
# 先登录拿 token（脚本/智能体推荐用长期 token，见 §2）
TOKEN=$(curl -s -X POST http://192.168.1.20:3001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"zouyuxi","password":"<密码>"}' | jq -r '.data.token')

# 之后每次调用都带头
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.1.20:3001/api/projects | jq '.data.projects[0].tasks[0]'
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://192.168.1.20:3001/api/jobs/tasks/<task_id>/submit
```

---

## 2. 认证与授权

> 登录认证和按项目归属授权均已实现。普通用户只能访问当前归属项目，admin按原管理权限；私有AI会话/连接另按user_id隔离，管理员不能越过该私有边界。

### 2.1 认证接口

| 接口 | 调用方式 | 说明 |
| --- | --- | --- |
| `POST /api/auth/login` | `{username, password, name?}` | 返回 `{token, expires_at, user, session}`；**失败限速 5 次 / 15 分钟**（第 6 次 `429`）；同时写 HttpOnly Cookie（仅供浏览器打开 `/docs`，只对 GET/HEAD 生效） |
| `POST /api/auth/logout` | 带头即可 | 删除当前会话，**旧 token 立即失效** |
| `GET /api/auth/me` | 带头即可 | `{user, session, is_admin}`，前端启动时校验登录态 |
| `POST /api/auth/users` | `{username, password?, role?, delegate_to?}`（**仅 admin**） | 建账号（v0.9.42）：`role=agent` + `delegate_to=<用户名>` = **AI 账号继承该用户的可见范围**；不传 `password` 则生成随机密码，**只回显一次** |
| `POST /api/auth/tokens` | `{username? \| user_id?, name?, expires_days?, scope?}`（**仅 admin**） | 签发长期 token（给脚本 / 智能体）；不传 `expires_days` 即长期有效；`scope` 见 §2.4（不传时 agent 默认 `["read"]`，人类默认不限）；**明文只返回一次** |
| `GET /api/auth/tokens` | 带头即可 | admin 看全部 token，其他用户只看自己的；返回 `session_id`（吊销时用） |
| `DELETE /api/auth/tokens/{session_id}` | 带头即可 | 吊销指定 token；admin 可吊销任意，其他用户只能吊销自己的（否则 403） |

### 2.2 调用约定

- **请求头**：`Authorization: Bearer <token>`（推荐）。备用：`X-Auth-Token: <token>`。
- **`?token=`**：**只对文档路径**（`/docs`、`/openapi.json`、`/redoc`）生效，且只用于首次打开 HTML；`/openapi.json` 这类后续请求需要 Cookie 或请求头（推荐直接在浏览器登录后用 Cookie 打开 `/docs`，脚本用 `Authorization` 头）。普通 API 的 GET **不接受** `?token=`（避免 token 进浏览器历史/代理日志）。
- **Cookie**：登录时由后端写入（HttpOnly、SameSite=Lax），只对 `GET`/`HEAD` 生效，**写操作必须用请求头**——这条规则是为了不引入 CSRF 面。
- **会话有效期**：默认 14 天并**滑动续期**（每次请求把有效期推回 14 天，漂移 ≥1 小时才写盘）；长期 token 默认不过期，可随时吊销。
- **失效场景**（都会返回 `401`）：token 不存在 / 已过期 / 已吊销 / 用户被禁用。改密与禁用会自动吊销该用户全部会话。
- **退出登录后**：旧 token 立即不可用（服务端删除会话，不依赖前端）。
- **日志/排障**：`sudo journalctl -u vasp-manager`；账号初始化（首次启动）会把随机初始密码打印到日志与 stdout。
- **审计**：账号相关动作（登录成功/失败、限速拦截、登出、长期 token 签发与吊销）与作业动作写同一份 `data/audit/actions.jsonl`，字段含 `at/username/command/result`（账号类额外带 `ip`，token 类带 `detail`）。
- **凭据响应不缓存**：`/auth/login`、`/auth/me`、`/auth/logout`、`/auth/tokens` 均返回 `Cache-Control: no-store`。

```bash
# 签发一个给智能体的长期 token（admin）
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"agent","name":"inspect-loop","expires_days":90}' \
  http://192.168.1.20:3001/api/auth/tokens | jq -r '.data.token'
```

账号管理（生产机）：

```bash
python scripts/set_password.py                    # 列出用户
python scripts/set_password.py <用户名>            # 建号/改密（交互输入）
python scripts/set_password.py <用户名> --generate # 随机密码并打印
python scripts/set_password.py <用户名> --disable  # 禁用（同时吊销其全部会话）
```

### 2.3 授权（v0.9.2 已生效）

- **归属模型**：项目带 `owner`（用户名）+ `created_at`；新建项目自动把 `owner` 写成当前登录用户；角色 `admin` 全可见，其他用户只能看到/操作自己的项目。
- **列表类**：`GET /projects`、`GET /inspections`、`GET /reports/groups`、`GET /reports/project/list`、`GET /dashboard/overview`、`GET /dashboard/cores-usage`、`GET /dashboard/risk-alerts` 等只返回当前用户可见的项目 / 任务 / 报告 / 巡检行 / 统计。
- **单对象类**：越权访问一律 **403**（统一信封 `{"success": false, "message": "无权访问该项目"/"无权访问该任务"}`），**不返回 404**，避免探测资源是否存在。
- **写操作**：全部校验（提交 / 续算 / 上传输入文件 / 生成 frac / 创建 NEB / 归档 / 删除 / 改草稿 …），实现集中在 `jobs._resolve_task`（所有 task 级接口的唯一入口）。
- **admin 专属**：`POST /inspections/run`（全局巡检）、`PUT /inspections/auto`（自动巡检开关）、全局配置写接口（`PUT /settings/root-paths`、`PUT /path-mapping`、`POST /path-mapping/rebase`、`PUT /ssh/config`、`POST /aux-molecules`）。
- **集群级信息**（节点 / 队列 / 存储 / 趋势采样）不涉及项目归属，保持全局可见（`/dashboard/cluster-health`、`/jobs/nodes`）。
- **审计**：写操作审计双写 —— `data/audit/actions.jsonl`（JSONL，含 `username`）+ 旧 `data/audit_submit.log`（原格式 + 行尾 `user=`）。
- 前端（v0.9.3）：按角色隐藏入口（侧栏 SSH/全局配置、巡检开关与触发按钮），非 admin 强访问 `/ssh` 跳首页；**403 只弹轻提示、不跳登录页**。前端隐藏是体验优化，后端 403 才是防线。
- 仍未做：多人共享项目（members）、用户管理/日志/在线会话页、HTTPS。HPC 侧仍是共享 `mdye` 账号（鉴权≠算力隔离）。
  （`role=agent` 的 token scope **已于 v0.9.42 生效**，见 §2.4）

### 2.4 AI 专用认证（v0.9.42 已生效）

给大模型 / 智能体用的**受限身份**：账号继承可见范围，token 限制能做什么。**人类账号与既有 token 完全不受影响**
（人类会话沿用原权限；Agent缺少scope不能视为无限写权限）。

| 概念 | 位置 | 取值 | 说明 |
| --- | --- | --- | --- |
| `delegate_to` | **账号**（`users[].delegate_to`） | 用户名 | `role=agent` 时**继承该用户的可见范围**（`GET /projects` 等只返回他的项目）；人类账号为空 |
| `scope` | **token**（`sessions[].scope`） | `read` / `propose` / `write` | 见下；不传时 agent token 默认 `["read"]`，人类会话为 `null`（不限） |

**scope 语义**（中间件按"这条请求需要什么能力"判定，`backend/middleware/auth.py::_needed_scope`）：

| 请求 | 需要 | 说明 |
| --- | --- | --- |
| 所有 `GET` / `HEAD` | `read` | 同时受项目/记录归属及接口权限约束 |
| `POST /api/pending-actions` | `propose` | AI 只能"提案"，进待确认队列等人工批准（§4.5） |
| 写操作 | `write`及端点白名单 | 不是任意写接口通行证；HPC须走受控网关和授权预算，原人工写端点不能绕过 |

组合规则：`write` 隐含 `propose`（能直接做就能提案）；`scope` 不足 → **403**，
消息形如 `该 token 的能力范围不含 write（当前：['read']）`。

**典型用法**：给巡检型 AI 签 `read`（看上下文、写分析、不改任何东西）；给需要处置的 AI 签 `propose`
（危险动作落进待确认队列，由人批准）；只有确定可信的自动化才签 `write`。

```bash
# 1) 建一个 AI 账号，继承 zouyuxi 的可见范围
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"agent_a","role":"agent","delegate_to":"zouyuxi"}' \
  http://192.168.1.20:3001/api/auth/users | jq '.data'

# 2) 给它签一个"只能提案"的长期 token
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"agent_a","name":"agent-a-propose","expires_days":90,"scope":["propose"]}' \
  http://192.168.1.20:3001/api/auth/tokens | jq -r '.data.token'

# 3) 吊销：DELETE /api/auth/tokens/{session_id}（session_id 见 GET /api/auth/tokens）
```

`GET /api/ai` 会回显当前 token 的 `role` / `delegate_to` / `scope`，便于 AI 自查自己有多大权限。

## 3. 只读接口（观测面）

`GET /api/jobs/tasks/{task_id}/file-status?remote=false`：固定返回INCAR、KPOINTS、POSCAR、POTCAR、CONTCAR、OUTCAR、OSZICAR七项，默认只读本地；人工刷新传remote=true，以一次只读SSH核对当前最大conN目录。逐项status为local/local_missing、synced/sampled/different/upload/download/local_only/missing/empty/changing/unknown，附本地/远端大小与数量、核对时间/目录。≤1MiB完整哈希，大文件只读头尾各64KiB，明确sampled；不传输文件、不提交作业。NEB兼容本地neb_images与远端映像目录；超过64映像或读取失败不判一致。沿用task归属校验。

`GET /api/inspections/{task_id}/atomic-forces?image=&refresh=`：逐原子受力取结构来源目录OUTCAR，固定标记和元素从同目录CONTCAR读取（包括NEB各映像）。响应`fixed_source=CONTCAR`、`schema=6`；固定原子灰色显示，排除最大力/RMS统计。缺CONTCAR明确报错，不借用POSCAR标记；旧schema缓存自动失效。部分方向含F仍按现有整原子固定口径处理。

NEB巡检结果补充：`force_thresholds`来自实际输出目录INCAR负EDIFFG，max=|EDIFFG|、RMS=|EDIFFG|/2；`force_max/force_rms`为中间映像末步最大值，`neb_force_checks`列各映像值、来源和收敛状态。仅全部中间映像正常结束且力收敛才`completed`，正常结束但超限/无法确认则`unconverged`，缺阈值/受力时`force_converged=null`并说明原因。端点不参与；排队/运行状态不被静态力检查覆盖。

### 3.1 项目 / 任务

| 接口 | 参数 | 关键返回 | 用途 |
| --- | --- | --- | --- |
| `GET /projects` | — | `projects[]`：`id/name/**owner**/**created_at**/closed/closedAt/progress/tasks[]`；每个任务含 `task_id/model_name/task_type/status/dir_path/remote_dir/job_id/last_energy/last_check_time` 与 **`check{status,message,checked_at,energy,has_inspection}`**（v0.8.8 起，与巡检中心同口径） | 全量盘点、判断"哪些任务该续算/该收尾" |
| `GET /task-types` | — | 四种任务类型与默认参数、子类型 | 校验动作参数 |
| `GET /reports/project/schema` | — | **数据契约**：`units`、`enums`、`status_families`（同一个 `status` 的四种含义）、`time_format`、`field_aliases`、`low_precision_policy`（2026-10-12 扩） | AI 先读契约再读数据 |
| `GET /servers` | — | 服务器名/主机/队列系统/节点分组 | 多服务器扩展 |
| `GET /health` | — | `uptime/startedAt`（判断后端是否已重启） | 健康检查 |
| `GET /projects/{project_id}` | — | 单项目详情（含 `deadline` / `calc_description` / `expected_results` / `urgency` / `priority_quadrant`） | 项目管理编辑弹窗取数 |
| `GET /reports/project/{report_id}/notes` | — | 报告注解 `{key: {analysis_note, paper_note, updated_at}}`；key 见 §4（`type_*` / `task_id` / `path:<group_id>`） | 结果分析 / 论文参考 |
| `GET /reports/project/{report_id}/edits` | — | 隐藏状态 `{hidden_sections[], hidden_elements[]}` | 报告页隐藏项恢复 |
| `GET /jobs/tasks/{task_id}/outcar-tail` | `?lines=40&image=` | OUTCAR 尾部（异常结束的任务点错误信息看最后数行）；返回 `{text, source, dir, lines}`。**优先级（2026-10-13 调整）**：未归档任务**直接读远端最新目录** —— 远端脚本自己按版本号挑最新 `conN`（NEB 再挑该 `conN` 里**最近修改**的映像 OUTCAR），本地那两份可能停在上一次同步的旧 conN；远端不可用才退回 归档摘要 `reports/outcar_tail.txt` → 本地镜像 `files/OUTCAR`。已归档任务仍走 摘要（秒回）→ 镜像 → 远端 |
| `GET /jobs/tasks/{task_id}/context` | `?n_checks=5&n_actions=10&refresh=0` | **任务上下文（AI 决策唯一入口）**：任务元数据（类型/状态/owner/group/created_at/归档痕迹）+ 最近 N 轮巡检（能量/力/收敛/精度/错误标志）+ 最近 N 条动作（`actor`+`actor_kind`=user/automation/system）+ 文件摘要（INCAR 关键参数、OUTCAR 尾部 4KB、result 尾部、NEB 各映像尾部）+ 人工痕迹（参数改动台账/归档/巡检 notes）+ 项目级 `calc_description`/`expected_results`；`hints.missing` 列出缺什么（2026-10-13 新增） | 大模型只读这一份即可决策 |
| `GET /reports/project/{report_id}/ai` | — | **AI 消费视图**：键名 snake_case、状态字段带族名（`task_status`/`check_status`/`output_state`/`queue_state`）、能量 eV·力 eV/Å、时间本地带 `+08:00`、`low_precision` 归并为 `task_status=completed`+`precision_ok=false`（2026-10-12 新增） | 大模型直读，无需自己猜枚举/单位/时区 |
| `GET /deps` | — | 依赖自检 | 运维 |

### 3.2 巡检结果

| 接口 | 参数 | 关键返回 | 用途 |
| --- | --- | --- | --- |
| `GET /inspections` | — | 前端行：`id/project_name/task_name/group_name/task_category/status/message/detail/task_status/has_inspection/last_check_time/...`（状态优先级：错误 > 警告 > 未检 > 正常 > 关闭） | **智能体判断的主输入**（一条任务一行结论） |
| `GET /inspections/meta` | — | 自动巡检开关、间隔、上次/下次执行时间、调度器状态 | 判断巡检节奏 |
| `GET /inspections/{task_id}` | — | 任务 + 巡检原始数据：`force_history[{step,energy,max_force}]`、`neb_barrier.images[]`、`analysis`（结构/CIF）、`frac_sibling`、`precision`、`incar/kpoints` 快照等 | 取详情做更细判断（力震荡、能垒、精度） |
| `GET /free-energy/{group_id}/summary` | — | 自由能台阶数据（中间体 DFT/矫正项/相对能/收敛） | 自由能路径进度判断 |
| `GET /reports/groups`、`GET /reports/groups/{group_id}/data` | — | 组结构化数据（台阶图/能垒图原始值） | 同上 |

> 原始归档：`data/checks/check_results_*.json`（每批一份，按任务裁剪，每个任务最多保留最近5个计算目录各自的一条最新观测，同目录更新覆盖）+ `data/checks/runs.json`（最近50轮执行摘要）。后台启动及每次巡检归档后自动整理；混合批次仅移除超额任务条目，空文件删除。`latest_results.json` 为最新合并结果视图，`daily_summary.json` 仅保留按日去重统计集合，避免清理历史改变总览/报告或丢失沿用的力信息；均非额外原始巡检历史。任务历史查询按实际checked_at倒序，最多5个不同目录，不再限制只扫描最新1200份文件。需要逐字段（`force_converged`、`precision.issues`、`markers`）时可直接读文件，或走 `GET /inspections/{task_id}`。

### 3.3 集群 / 总览

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `GET /dashboard/overview` | `?refresh=1` 强制重采 | 一次返回整页：统计、运行作业、核数、节点/队列/存储、风险、项目进度、趋势 |
| `GET /dashboard/cores-usage` / `cluster-health` / `risk-alerts` / `trend` | `?refresh=1` | 分块数据（风险预警含 `risks[].advice` 与 `actions.items[]`） |
| `GET /jobs/nodes` | `?refresh=1` | 作业管理节点看板数据（与总览共用一次采集 + TTL 缓存，默认 300s） |

### 3.4 任务文件 / 输入状态

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `GET /jobs/tasks/{task_id}/files` | — | 本地任务目录文件清单（name/size/modified） |
| `GET /jobs/tasks/{task_id}/files/{filename}` | 白名单文本文件 | 读取文件内容（`INCAR/POSCAR/KPOINTS/POTCAR/CONTCAR/OUTCAR/OSZICAR/...`） |
| `GET /jobs/tasks/{task_id}/input` | — | **输入状态**：`source{con,job_id,synced_at}`、`files{INCAR,KPOINTS,POSCAR,CONTCAR}{text,params/mesh/elements...}`、`draft`、`changes`、`last_applied`、`pending`、`poscar_cif/contcar_cif`（纯本地读取，不发 SSH） |

---

## 4. 动作接口（执行面）


### 4.0 报告扩展写入（2026-10-12）

| 接口 | body | 说明 |
| --- | --- | --- |
| `PUT /api/projects/{project_id}` | `{description?, deadline?, calc_description?, expected_results?, estimated_hours?}`（全部可选，只改传入字段） | 编辑项目；**名称不可改**；优先级是算出来的不接受写；改 deadline 会重算 urgency/priority_quadrant；owner 校验 |
| `GET /api/jobs/tasks/{task_id}/context` | `?n_checks=&n_actions=&refresh=1` | 任务上下文（AI 决策唯一入口，见 §3.1；只读、按需、指纹缓存 `<任务>/reports/task_context.json`） |
| `PUT /api/reports/project/{report_id}/notes` | `{key, analysis_note, paper_note}`（两条都空 = **删除**该条） | 写「结果分析描述 / 论文写作参考」（落 `data/reports/notes/<report_id>.json`）。**只在报告的「重点科学结果分析」章节里呈现**，key 有四种（2026-10-13 用户口径）：`type_opt` / `type_free_energy` / `type_neb` / `type_ele`（该类型一条总的）、`task_id`（结构优化每个子项、NEB 每个组）、`path:<group_id>`（自由能路径每个组）。电子结构目前是占位区块，**只有类型级的 `type_ele`、没有子项级**（子任务未完成） |
| `PUT /api/reports/project/{report_id}/edits` | `{hidden_sections: [...], hidden_elements: [...]}` | 保存报告页的隐藏状态（落 `data/reports/edits/<report_id>.json`） |
| `GET /api/reports/project/{report_id}/export.html` | `?sections=…&hide=section:x,task:<章节>:<标题>,figure:<章节>:<序号>&print=1&interactive=0&download=1` | 自包含 HTML：`sections` 选章节、`hide` 排除被隐藏的元素、`print=1` 打开即调起打印；**`interactive=0` 导出纯静态版**（不加 ECharts 运行时与 PDOS 数据，体积更小；默认 `1` = PDOS/功函数图可交互）；**`download=1` 按附件返回**（浏览器直接下载，文件名 `项目名_项目报告_日期.html`；默认 `inline` 在标签页打开） |

### 4.1 五个核心动作（智能体闭环会用到）

#### ① 提交作业

```
POST /api/jobs/tasks/{task_id}/submit        # 无 body
```

- **行为**：单次 exec 完成「定位最新 conN → 输入文件非空检查 → `bsub < vasp.lsf`」；成功后写 `job_id` + 状态 `queued`（事务内）。
- **前置/守卫**：`job_id` 且状态为 `queued/running` → `409`（勿重复操作）；缺远端目录 → `404`；
  文件检查失败 → **`400` 且不提交**，返回缺失文件名（opt/frac/ele 查 `POSCAR/INCAR/KPOINTS/POTCAR/vasp.lsf`；NEB 查 `INCAR/KPOINTS/POTCAR/vasp.lsf` + 各映像 `POSCAR`）。
- **返回**：`{job_id, new_status, raw_output}`
- **耗时**：1 次 exec（≈1.3–4s）。**幂等**：有 409 保护。**审计**：有。

#### ② 创建续算

```
POST /api/jobs/tasks/{task_id}/continuation   # 无 body
```

- **行为**：远端创建 `con(N+1)`，复制 `CONTCAR→POSCAR`/`POTCAR`/`KPOINTS`/`INCAR`/提交脚本，`WAVECAR` 用 `mv`（移动语义），`INCAR` 改 `ISTART=1/ICHARG=0` 并应用待生效草稿；NEB 走映像续算（带端点 `OUTCAR`、各映像 `WAVECAR`）；登记隐藏续算子任务。
- **前置/守卫**：续算子任务（`dir_path` 带 `conN`）→ `400`；任务类型非 `opt/neb` → `400`；重复 `conN` → `409`；
  **有活跃作业 → 不建目录、不动文件**，正常返回 `action="running"`。
- **返回（关键字段 `action`）**：`created`（真正建了目录）· `running` · `input_complete_but_not_finished` · `input_incomplete`；另有 `con/remote_dir/source_dir/incar_changes/copied_files/warnings`。
  ⚠️ **自动化里必须判 `action`，不要以 HTTP 200 当作"已创建"。**
- **耗时**：单次远端脚本 ≈3.5s。**幂等**：有 409 保护。**审计**：有。

#### ③ 修改 INCAR（4 个粒度，按需选）

| 目的 | 接口 | body | 说明 / 风险 |
| --- | --- | --- | --- |
| 记草稿（**推荐**） | `PUT /api/jobs/tasks/{task_id}/input/draft` | `{file:"INCAR", params:{KEY:"value", ...}}` | 只改本地库，**不碰远端**；下次续算应用，可逐项/整文件撤销。空值 = 撤销该项 |
| 生成到本地 | `PUT /api/jobs/tasks/{task_id}/files/{filename}` | `{content:"..."}` | 只写本地 `files/INCAR`（白名单文件名） |
| 同步到远端 | `POST /api/jobs/tasks/{task_id}/upload-incar` | `{params:{...}}` 或 `{content:"..."}` | 定位最新 conN → 备份 `old_INCAR` → **立即写远端** → 台账标 `applied_in="remote"`；返回 `{dir, backup_file, warnings, applied[], state}` |
| 撤销草稿 | `DELETE /api/jobs/tasks/{task_id}/input/draft/{file_name}` | — | `file_name` = `INCAR` / `KPOINTS`（整文件撤销） |

- 单值参数直接给值；多值参数（如 `MAGMOM = 5*2.0`、`DIPOL = 0.5 0.5 0.18`）**整串保留**；`.T.`/`.TRUE.`、`1E-6`/`1e-6` 视为等价不会误判改动。
- `EFIELD` 按 VASP 定义是**单个数值**（eV/Å），方向由 `IDIPOL` 决定；`NCORE` 默认留空（不写入）。
- 耗时：draft / 本地文件为纯本地 IO（快）；`upload-incar` 走 SSH（≈1.3–4s）。

#### ④ 自由能频率计算生成（frac 输入）

```
POST /api/jobs/tasks/{task_id}/create-frac    # body: {"ibration": 5}（可省，默认 5）
```

- **行为**：从 opt 任务最新输出生成频率矫正（frac）输入：`CONTCAR→POSCAR`、复制 `POTCAR/KPOINTS`，默认 `ISYM=0/SIGMA=0.05/NSW=1/IBRION=5/NFREE=2/POTIM=0.015`；回填 frac 子任务的 `input_source/notes`；同步刚生成目录的输入快照到本地，保留待生效草稿，页面立即回填参数。
- **前置**：任务必须是 `opt`（否则 `400`）；必须已存在 `<结构目录>/frac` 子任务（自由能组创建时自动登记，否则 `404`）。
- **返回**：`{frac_dir, source_dir, latest_dir, incar_changes, copied_files, input_synced, warnings}`
- **耗时**：远端 bash **timeout 180s**。**审计**：`create-frac`。

#### ④b 差分电荷分块计算生成（ele 附属，v0.9.44）

```
POST /api/jobs/tasks/{task_id}/create-diff-charge
body: {
  "blocks": [                       # 必填：≥2 块，原子序号 1 起，互不重叠且合起来 = 全部原子
    {"label": "分块A", "atoms": [1,2,…]},
    {"label": "分块B", "atoms": [17,18,…]},
    {"label": "分块C", "atoms": […]}  # 可选：第三、第四块（远端目录 3、4 …）
  ],
  "incar_params": {}                # 可选：额外写进分块 INCAR 的参数
}
```

- **行为**：把完整结构按原子拆成若干分块，各自单独做静态计算（**LSF 上各自独立提交**）：
  ① 每个分块只保留自己那部分原子的 POSCAR（晶胞不变、元素顺序沿用父结构、重新统计数量）；
  ② INCAR 复制主任务并**校验关键参数** `LCHARG = .TRUE.`、`IBRION = -1`、
  **`ISTART = 0`、`ICHARG = 2`**（分块从零开始算，不读主任务的波函数/电荷密度；不一致就地改并在
  `incar_fixes` 里回报），且**删掉除 LCHARG 以外的输出参数**
  （`LWAVE / LAECHG / LVHAR / LVTOT / LORBIT / NEDOS`，回报在 `incar_removed`；分块只要 CHGCAR）；
  MAGMOM 暂不改（只在条目数与分块原子数不一致时给 `incar_warnings` 提示）；③ KPOINTS / vasp.lsf 直接复制主任务；
  ④ 在主任务目录跑一次远端 `pos2pot`（脚本递归）→ 主结构与各分块一起生成 POTCAR。
- **前置**：任务必须是 `ele`（否则 `400`）；主任务本地/远端要有 `POSCAR`；同一任务已有分块时 `409`
  （要重做先删旧分块）；分块必须覆盖全部原子（漏原子/重叠/空块 → `400`）。
- **返回**：`{group_id, block_count, tasks[{task_id, model_name, ele_block, atoms_count,
  remote_dir}], local_root, remote_root, incar_fixes, incar_warnings, potcar, potcar_generated}`。
  `potcar_generated` 以**各分块**是否都有 POTCAR 为准，另有 `potcar_blocks` 给出每块的字节数
  （`pos2pot` 的 `potcar` 摘要只反映主任务目录，主目录没有 POSCAR 时会是 MISSING，别误判）。
- **子任务形态**：`task_type=ele_diff` + `subtype=diff_charge` + `parent_task_id`=ele 主任务 +
  `ele_block`/`ele_block_label`/`ele_block_atoms`；`local_layout=flat`（本地文件直接放任务目录）。
  分块是**附属任务**：巡检列表不单独成行（挂在 ele 主任务详情里）、不计当量、归档/重开跟随主任务。
- **目录口径**：

```
远端 <ele 任务目录>/            本地 <ele 任务本地目录>/
├── POSCAR/INCAR/…             ├── files/                      （主任务）
├── 1/   ← 分块A               ├── diffcharge_files/1/          （分块文件，flat）
├── 2/   ← 分块B               ├── diffcharge_files/2/
└── …（3、4 …）                ├── diffcharge_files/chgfiles/   （CHGCAR_diff.vasp = 差分电荷，
                               │                                  远端 chgsum.pl + chgdiff.pl 生成）
                               └── diffcharge_files/images/     （VESTA 导出的 chgdiff_{a,b,c}.png）
```

- **差分电荷口径（2026-10-14 变更）**：在**远端主目录**用 VTST 脚本算好差分，只回传一个文件：
  `chgsum.pl 1/CHGCAR 2/CHGCAR …` → `CHGCAR_sum`，再 `chgdiff.pl CHGCAR CHGCAR_sum` → `CHGCAR_diff`；
  回传后本地存 `diffcharge_files/chgfiles/CHGCAR_diff.vasp`。不再把各分块/完整结构的 CHGCAR（各 200MB+）
  都拉到本地。脚本路径默认 `/data/gpfs03/mdye/VTST/vtstscripts`，可用 `data/servers.json: vtst_dir` 覆盖；
  远端缺脚本/缺 CHGCAR 会明确报错（见 DEPENDENCIES.md §3c）。结果记在 ele 主任务
  `charge_diff`（`{ok, remote_path, local_path, bytes, elapsed_seconds, vtst_dir, synced_at}` 或
  `{ok:false, error}`），巡检详情 `diff_charge.charge_diff` 直接透出。
  **触发入口自 v0.9.46 起在巡检详情**（不再挂在归档上），见 §4.2 ④c。
- **耗时**：远端 bash + pos2pot **timeout 180s**。**审计**：`create-diff-charge`。

#### ④c 差分电荷计算与三视图（巡检详情入口，v0.9.46）

入口在**巡检详情 →「电子结构分析 → 差分电荷」标签**（前端 `DiffChargePanel`）。第一次点击依次做四件事：
① 远端校验文件完整性（完整结构 + 各分块 `CHGCAR`，**大小差别应 < 1%**，否则拒绝并给出具体原因）；
② 远端 VTST 算差分；③ 回传 `CHGCAR_diff`；④ 导入 VESTA 导出 a/b/c 三轴 PNG
（`vesta_render.render_volume_axes`：**直接打开体积文件**再 `-rotate_x/-rotate_y/-rotate_z`
转到 `AXIS_VIEW` 定义的目标朝向 —— 与结构图共用同一套视角定义，但**不走模板**：
VESTA 的 `.vesta` 不保存等值面，经 `IMPORT_DENSITY` 重导入的密度归一化也不同，
会只剩最强的那层瓣；取景用 VESTA 默认缩放，与手动打开该文件一致）。之后每次加载按阶梯取值：
**本地图 → 本地差分文件 → 远端差分文件 → 远端可算**（前两级零 SSH）。

```
POST   /api/jobs/tasks/{task_id}/charge-diff/analyze        # 触发（异步），body {"force": false}
GET    /api/jobs/tasks/{task_id}/charge-diff/status         # 状态；?remote=1 时附带远端探测（120s 缓存）
GET    /api/jobs/tasks/{task_id}/charge-diff/images/{axis}  # 取三视图 PNG（axis = a|b|c，image/png）
DELETE /api/jobs/tasks/{task_id}/charge-diff                # 清除本地结果；?images_only=1 只删图
```

- **触发返回**：`{run_id, status, reused}`。同一任务已有 run 在跑时复用（不会并发跑两遍）；
  全局同时只跑一条链路（`_JOB_LOCK`），VESTA 渲染另有**跨进程文件锁**
  （`data/locks/vesta_render.lock`）与结构图渲染互斥 —— 百 MB 体积数据 + VESTA 最容易拖卡机器。
- **状态返回**：`status`（`running|done|failed|idle`）、`stage` + `stage_label`
  （`checking` 远端校验 / `computing` VTST / `downloading` 回传 / `rendering` VESTA 出图）、
  `bytes_done` / `bytes_total`（回传进度）、`elapsed_seconds`、`error`、
  `local`（`{state, has_images, has_diff, diff_bytes, diff_mtime, image_mtime, blocks}`）、
  `remote`（仅 `remote=1`：`{state, reason, has_diff, integrity, vtst, remote_dir, checked_at}`）、
  `charge_diff`（写回任务台账的同一条记录）。
- **中断补偿**：远端已有 `CHGCAR_diff` → 只回传不重算；本地已有差分文件 → 只补出图；
  `?force=true` 才强制重算重画。失败原因写 `diffcharge_files/meta.json`（跨重启保留）。
- **图片取用**：`/api/**` 全部要鉴权，`<img src>` 带不了 `Authorization` 头 —— 前端用
  `requestBlobUrl()`（`src/api/client.ts`）带鉴权头 fetch 后转 blob URL 显示；未登录返回 401。
- **耗时**：校验 1 次 exec（约 0.5–1.5s）；VTST 计算数分钟（timeout 1800s）；回传 200MB 级视带宽；
  VESTA 出图约 11s（实测 130MB `CHGCAR_diff`：打开 3.6s + 每轴 2.4s，timeout 1800s）。
  **不算时间长，是因为长任务与大文件都走专用连接**（见下条）。
- **专用连接（v0.9.47，用户口径"单开"）**：常驻连接池是"一条连接 + 串行锁"，200MB 回传或
  几分钟的 `chgsum.pl` 占着锁会让同一服务器的巡检 / bjobs / 提交全部排队。现在：
  ① `download_file` 先借池连接 `stat` 拿大小，**超过 `dedicated_transfer_mb`（默认 32MB，
  `data/config/settings.json` 可覆盖，0 = 全部走池）就松开池锁另开一次性连接**搬；
  ② 长命令用 `run_remote(..., dedicated=True)`（差分电荷的 chgsum/chgdiff 走这条）。
  专用连接用完即关、不进池、不参与空闲回收，代价是多一次握手（~1s）；传输台账见
  `data/ssh_transfer.log`（server / bytes / dedicated / elapsed / path）。
- **审计**：`charge-diff-analyze` / `charge-diff-clear`；链路日志 `data/charge_diff.log`。

#### ④d Bader 电荷分析（巡检详情入口，v0.9.51 · 本轮只到处理链路）

入口在**巡检详情 →「电子结构分析 → Bader」标签**（前端 `BaderPanel`）。链路：
① 远端校验 `AECCAR0/1/2` 是否存在、**大小差别 < 1%**（一次 exec）；
② 远端 `chgsum.pl AECCAR0 AECCAR2` → **`CHGCAR_sum_aec`**（在子目录 `.bader_sum/` 里跑 chgsum 再 mv 出来）；
③ 远端 `bader CHGCAR -ref CHGCAR_sum_aec`（**耗时可能较长**，timeout 3600s，走专用连接）→ `ACF.dat`；
④ 回传 `ACF.dat` 到 `<任务本地目录>/bader/` 并解析成原子表。
**中断补偿**：远端已有 `ACF.dat` 就只回传；本地已有就只重新解析，不重跑。

> ⚠ **为什么参考电荷叫 `CHGCAR_sum_aec` 而不是 `CHGCAR_sum`**（2026-10-15 修）：`chgsum.pl` 把输出名
> **写死成 `CHGCAR_sum`**，而差分电荷链路跑的是 `chgsum.pl 1/CHGCAR 2/CHGCAR …`（**分块和**）——
> 两者撞名。现场就踩到了：`FS_Kaolin/model2` 等目录里那份 `CHGCAR_sum` 的头部是 `Fe S / 24 32`（分块），
> 而 `AECCAR0` 是 `Fe S O H / 24 33 5 1`（完整结构），拿它当 `-ref` 会算出错的 Bader 电荷。
> 现在 Bader 在 `.bader_sum/` 子目录里跑 chgsum（软链到两个 AECCAR，**不覆盖**那份遗留文件），
> 输出 mv 成 `CHGCAR_sum_aec`；复用它之前会校验**头部元素/计数行 + 总行数与 `AECCAR0` 一致**
> （`chgsum.pl` 会把第一个输入的前若干行原样拷进输出，所以这个判据是可靠的）。

```
POST   /api/jobs/tasks/{task_id}/bader/analyze   # 触发（异步），body {"force": false}
GET    /api/jobs/tasks/{task_id}/bader/status    # 状态；?remote=1 附带远端探测（120s 缓存）
GET    /api/jobs/tasks/{task_id}/bader           # 解析结果（ACF 原子表 + 页脚汇总）；没算过 404
DELETE /api/jobs/tasks/{task_id}/bader           # 清除本地 ACF.dat / meta（远端不动）
```

- **状态返回**：`status`（`running|done|failed|idle`）、`stage` + `stage_label`
  （`checking` 校验 / `summing` chgsum / `bader` 分析 / `downloading` 回传 / `parsing` 解析 / `done`）、
  `elapsed_seconds`、`error`、`local`（`{has_acf, acf_path, acf_bytes, acf_mtime}`）、
  `remote`（仅 `remote=1`：`{state, reason, sizes, integrity, tools, has_sum, has_sum_aec,
  sum_aec_valid, has_remote_acf, bader_exe}`）。
  远端 `state`：`ready`（可算；`sum_aec_valid=true` 才跳过 chgsum）/ `remote_acf`（远端已有 ACF）/
  `incomplete`（缺 AECCAR 或大小不一致）/ `no_bader` / `no_chgsum`（按提示改 `servers.json`）。
- **解析结果**（`GET .../bader`）：`{n_atoms, atoms[{index,x,y,z,charge,min_dist?,atomic_vol?,
  element?,zval?,net_charge?}], total_charge, n_electrons, vacuum_charge, vacuum_volume,
  has_atomic_vol, has_min_dist, elements, zval, net_charge_available, net_charge_reason, stats, source, bytes, meta}`。
  兼容集群上的 Fortran 版（含 `ATOMIC VOL` 列 + `VACUUM CHARGE/VOLUME`、`NUMBER OF ELECTRONS` 页脚）
  与老 C 版（无 ATOMIC VOL、页脚是数字表 → 放 `summary_row`）。
- **净电荷（v0.9.54）**：`Δq = ZVAL − Bader 电荷`（正=失电子）。ZVAL 取自**远端 POTCAR 的一次极轻
  grep**（`grep -E '^ *TITEL|ZVAL' POTCAR`；真 POTCAR 里 `ZVAL` 与 `POMASS` **同一行**），
  解析结果缓存在本地 `bader/meta.json` 的 `zval` 里 → `GET .../bader` 仍然**纯本地**（不连远端）。
  元素序列取本地 `files/POSCAR`；任一缺失则 `net_charge_available=false` +
  `net_charge_reason`（前端只显示原始电荷，不猜）。`stats` = `{n_atoms, charge_total, zval_total,
  net_total, net_mean, net_max{value,index,element}, net_min{…}}`。
- **审计**：`bader-analyze` / `bader-clear`；链路日志 `data/bader.log`。
- **还没做（分析链路，下一轮）**：净电荷 `Δq = ZVAL − Bader 电荷`（要读 POTCAR 的 ZVAL）、
  按元素/原子分组统计、图表、写进报告 —— 本轮的产出就是**原始 Bader 电荷表**。
- **前端**：Bader 标签页里带一个**结构预览框**（v0.9.53，结构取 `/jobs/tasks/{id}/input` 的
  `poscar_cif`/`contcar_cif`）：点原子（Ctrl 多选 / Shift 框选）在左上角看该原子的
  `Bader 电荷 / dmin / 原子体积` —— **只显示读数、暂不着色**（按元素配色）；
  原子序按 `ACF.dat` 行序（1 起）与 CIF 下标（0 起）做换算，并先比对两边原子数，不一致就不挂读数。
  **v0.9.54 补齐**：预览框**旁边一张卡片**对**当前选中原子实时**统计平均/最大/最小（+合计），
  选择方式 = 点选 / Ctrl 多选 / Shift 框选 / **按元素全选**（元素按钮，再点取消）；
  **「按电荷上色」开关**（与受力同位置）：红 = 失电子（Δq > 0）、蓝 = 得电子（Δq < 0），
  对称尺度 ±max|Δq|（下限 0.5 e），卡片里给图例；读数里也带 `Δq`。**不做元素分组**。
- **报告**：`report_builder` 的「电子结构」章节新增 `#### <任务> · Bader 电荷`：结论一句话
  （Σq / ΣZVAL / ΣΔq / 平均 / Δq 最正与最负的原子）+ 按 |Δq| 排序前 10 个原子的表；
  缺 ZVAL 时降级说明。图片/图表本轮不加。

#### ④e 功函数（巡检详情入口，v0.9.59）

入口在**巡检详情 →「电子结构分析 → 功函数」标签**（前端 `WorkFunctionPanel`）。链路：
① 前端选方向（默认 **c 轴**，支持 a/b）→ ② 远端检查 `LOCPOT`/`OUTCAR` 存在非零、**所选方向是否开了
偶极矫正**（`LDIPOL=.TRUE.` 且 `IDIPOL` 匹配该方向；a→1、b→2、c→3、4=全方向；**没开只警告不拦**）→
③ 远端 `vaspkit -task 426 -dir <x|y|z>` 写 `PLANAR_AVERAGE.dat`（约 8 KB）→
④ 回传内容（base64 随同一次 exec 返回，不需要 SFTP）→ 本地解析：
**功函数 = 真空能级 − E_F**（`E-fermi` 从 OUTCAR 读；真空能级优先取 VASPKIT 汇总值，
没有汇总时（缺 DOSCAR）退回本地"电位平台"估计并给说明）。

```
POST   /api/jobs/tasks/{task_id}/work-function/analyze    # 触发（异步），body {"axis": "c"}
GET    /api/jobs/tasks/{task_id}/work-function/status     # 状态；?remote=1 附带远端探测（120s 缓存）
GET    /api/jobs/tasks/{task_id}/work-function            # 解析结果（曲线 + 真空能级 + 功函数）；没算过 404
DELETE /api/jobs/tasks/{task_id}/work-function            # 清除本地 PLANAR_AVERAGE.dat / meta
```

- **方向口径**：界面上的晶轴 a/b/c 会被映射成 VASPKIT `-dir` 要的**笛卡尔** `x/y/z`
  （a↔x、b↔y、c↔z）。实测 `-dir c` 会报 `Wrong Direction Selected.c`。
- **状态返回**：`status`（`running|done|failed|idle`）、`stage` + `stage_label`
  （`checking` 校验 / `extracting` VASPKIT / `parsing` 解析 / `done`）、`elapsed_seconds`、`error`、
  `local`（`{has_result, data_path, bytes, axis}`）、
  `remote`（`remote=1`：`{state, reason, sizes, has_vaspkit, dipole{ldipol,idipol}, fermi, vaspkit_exe}`）。
  远端 `state`：`ready` / `no_locpot`（缺 LOCPOT，提示补 `LVHAR=.TRUE.`）/ `no_outcar` / `no_vaspkit`。
- **结果**（`GET .../work-function`）：`{ok, axis, axis_cartesian, efermi, vacuum_level,
  vacuum_level_vaspkit, vacuum_level_local, vacuum_level_source, work_function,
  work_function_vaspkit, plateau{side,start,end,value,points,spread}, points, dipole, warnings[],
  elapsed_seconds, local_path, z[], potential[]}` —— `z/potential` 直接喂图表。
- **图上元素**：电位-距离曲线 + **真空能级**与 **E_F** 两条水平虚线（带数值标签）；
  关键数值卡给功函数 / 真空能级 / E_F。
- **告警（不阻断）**：所选方向没开偶极矫正；本地估的真空能级与 VASPKIT 汇总差 > 0.05 eV
  （真空平台不平，提示"真空可能不够厚/没收敛"）；缺 E_F 时功函数给不出。
- **耗时**：200MB 级 LOCPOT 约 3 s（登录节点实测）；远端在 `mktemp -d` 临时目录里跑，
  **不往任务目录写任何文件**。**审计**：`work-function-analyze` / `work-function-clear`。

#### ⑤ NEB 创建计算文件

```
POST /api/jobs/tasks/{task_id}/create-neb-files
body: {
  "initial_opt_task_id": "...",     # 必填，必须是 opt
  "final_opt_task_id": "...",       # 必填，必须是 opt
  "num_images": 3,
  "params": {"IOPT":3,"LCLIMB":".TRUE.","ICHAIN":0,"SPRING":-5,"MAXMOVE":0.2,"POTIM":0}
}
```

- **行为**：以 IS INCAR 为基底只改 NEB 参数 → 远端 `nebmake.pl` 线性插值生成 `00..NN` 映像目录与文件。
- **前置**：任务必须是 `neb`（否则 `400`）；初/末态任务必须存在、类型为 `opt`（否则 `404`/`400`）；
  **初/末态必须 `status=completed` 或 `status=archived && archived_from=completed`**；归档前未收敛/原状态未知仍拒绝，否则 `400`（"优化未收敛，请先完成结构优化"）。
- **返回**：`{neb_dir, source_is, source_fs, num_images, images[], incar_changes, copied_files, input_synced, warnings}`
- **创建后同步**：NEB/frac/电子结构均同步刚生成的确切目录，不让旧conN替换本次创建参数。同步失败仍保留创建成功事实，`input_synced=false`并返回warnings；前端强制重读本地参数页缓存，不新增提交或后台轮询。
- **耗时**：远端 `nebmake.pl` **timeout 300s（最重）**。**审计**：`create-neb images=N`。

### 4.2 巡检动作

| 接口 | body | 说明 |
| --- | --- | --- |
| `POST /inspections/run` | `{project_name?: str, task_id?: str}` | 立即巡检（可限定项目/任务）；返回 `{run_id, checked_at, inspected, updated, unchanged, warnings, rejected, skipped_projects, failed_batches, archived_files, scope}`；全局巡检约 75–90s |
| `POST /inspections/run-single/{task_id}` | — | 单任务巡检（约 12–15s）；归档任务返回 `400` |
| `PUT /inspections/auto` | `{enabled: bool, interval_hours?: number}` | 自动巡检开关（写 `settings.json`，后台 60s 轮询判定） |

### 4.3 其他写接口（简表）

| 分类 | 接口 | 备注 |
| --- | --- | --- |
| 作业 | `POST /jobs/tasks/{id}/stop` | 任务族锁内bkill，成功返回后同步本地与台账，不额外轮询；落库失败明确报未同步，再提交仍重查LSF活跃作业；**高风险** |
| 作业 | `POST /jobs/tasks/{id}/archive` · `/unarchive` | 归档/重开（自由能主任务连带 frac） |
| 作业 | `POST /jobs/tasks/{id}/build-ele-inputs` | ele 输入（`{source_type:"opt"/"external", source_task_id?, ...}`） |
| 作业 | `POST /jobs/tasks/{id}/create-diff-charge` | **差分电荷分块计算**（ele 附属，v0.9.44）：`{blocks:[{label,atoms}], incar_params?}` → 见 §4.2 ④b |
| 作业 | `POST /jobs/tasks/{id}/selective-dynamics` | 固定原子生成新 POSCAR（`{manual/indices/elements/z_range/..., sync_remote?}`） |
| 作业 | `POST /jobs/tasks/{id}/upload-poscar` · `/upload-kpoints` · `/upload-submit-script` · `/generate-potcar` | 写远端最新目录；KPOINTS先比对真实远端，相同不重写但刷新网格记录，返回unchanged/state；变更时沿用old_* |
| 作业 | `POST /jobs/tasks/{id}/input/sync` | 从远端重新取回四件套（1 exec + 4 SFTP；会覆盖本地镜像，有草稿的文件跳过） |
| 作业 | `PATCH /jobs/tasks/{id}` · `DELETE /jobs/tasks/{id}` | 重命名 / 删除（本地进回收站，**远端不删**） |
| 项目 | `POST /projects` · `GET /projects/{id}` · `POST /projects/{id}/close` · `/reopen` · `DELETE /projects/{id}` | 关闭要求可见任务全部归档；新建项目自动写 `owner`=当前登录用户（v0.9.1） |
| 组 | `POST /groups` · `POST /groups/{id}/structures` · `POST /groups/tasks` | 建自由能/NEB 组、加结构、建独立任务 |
| 报告 | `POST /reports/project/generate` (`{project_id?, all?}`) · `GET /reports/project/list` · `/{id}` · `/{id}/structured` · `/{id}/markdown` · `/{id}/export.html` · `DELETE /{id}` | 分项目报告（同项目重生成覆盖） |
| 配置 | `PUT /settings/root-paths` · `PUT /path-mapping` · `POST /path-mapping/rebase` · `PUT /ssh/config` · `POST /ssh/test` | 运维类，**权限敏感** |
| 分析 | `POST /jobs/tasks/{id}/pdos/analyze` · `GET /jobs/tasks/{id}/pdos/status` · `GET /jobs/tasks/{id}/pdos` · `DELETE /jobs/tasks/{id}/pdos` | **PDOS 分析（v0.9.45 重建）**：异步触发（返回 `run_id`）→ 轮询 → 取解析数据 → 清除重跑；见 §4.5 |
| 分析 | `POST /jobs/tasks/{id}/charge-diff/analyze` · `GET .../charge-diff/status` · `GET .../charge-diff/images/{axis}` · `DELETE .../charge-diff` | **差分电荷（v0.9.46）**：巡检详情入口；远端校验（三份 CHGCAR 大小差 < 1%）→ VTST 算差分 → 回传 → VESTA 三视图；异步 + 阶梯缓存；见 §4.2 ④c |
| 分析 | `POST /jobs/tasks/{id}/bader/analyze` · `GET .../bader/status` · `GET .../bader` · `DELETE .../bader` | **Bader 电荷（v0.9.51，处理链路）**：巡检详情入口；远端校验 AECCAR 完整性 → `chgsum.pl` → `bader CHGCAR -ref CHGCAR_sum` → 回传解析 `ACF.dat`；净电荷/图表属分析链路；见 §4.2 ④d |
| 分析 | `POST /jobs/tasks/{id}/work-function/analyze` · `GET .../work-function/status` · `GET .../work-function` · `DELETE .../work-function` | **功函数（v0.9.59）**：巡检详情入口；选方向（a/b/c，默认 c）→ 校验 LOCPOT/OUTCAR/偶极矫正 → 远端 VASPKIT `-task 426 -dir x/y/z` → 回传解析平面平均电位（真空能级 + 功函数 = 真空 − E_F）；见 §4.2 ④e |
| 分析 | `POST /jobs/tasks/{id}/calculate-correction` | 自由能矫正项（vaspkit 501） |
| 结构转换 | `POST /tools/cif-to-poscar` | CIF → POSCAR（`{content}` → `{poscar, elements, counts, atoms, cell, formula, warnings}`；纯文本不落盘，页面「导入 POSCAR」选 .cif 走的就是它；解析失败 400 带中文原因） |

报告进度口径（2026-10-18）：`basic_info.weighted_progress_percent` 为包含归档成果的当量加权主进度；`basic_info.progress_percent` 与列表 `completion_percent` 仍为未归档任务完成率。新生成报告的列表另带可选 `weighted_progress_percent`，旧报告可能没有该字段。进度风险与摘要使用加权主进度；`workload.core_hours_*` 是当量折算核时，工期为固定产能假设下的估算。重新生成同一 report_id 时保留注解，并按图片路径迁移原有单图隐藏位置。


> 未列全的请求体字段以 `/docs`（Swagger）为准；本文档只覆盖接入常用面。

---

## 4.4 统一动作与自动化（v0.9.6，仅 admin）

> 旧规则管理仍是admin全局能力，未改造成普通用户可编辑的私有规则系统。已托管任务不能经旧规则绕过授权/预算；不得直接开放此入口替代按项目鉴权的托管计划工具。当前前端统一位于`/automation`两个标签，均只对管理员开放。

所有动作走同一入口（调度器不直接调业务接口），内部复用 `routers.jobs` 的四个核心实现。

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `GET /api/actions` | — | 动作目录：名称 / 说明 / 是否长动作 / 参数提示 |
| `POST /api/actions/{action_name}` | `{task_id?, params?, dry_run?, idempotency_key?, wait?}` | `task.continuation` / `task.submit` / `frac.create`（`neb.create` v0.9.8 起暂未启用，调用返回 400） |
| `GET /api/actions/runs/{run_id}` | — | 长动作轮询：`running / success / failed / skipped` + result |
| `GET /api/automation/status` | — | 全局开关 + 定时任务（含下次触发）+ 规则（含 `follow_up_action`、`progress` 已运行次数）+ 计数 |
| `GET/PUT /api/automation/settings` | `{enabled?, dry_run?, schedules_enabled?, failure_threshold?}` | 改完**立即生效**（enabled=false 即全局暂停） |
| `GET /api/automation/rules` | — | 规则列表 |
| `POST /api/automation/rules` | 规则对象 | 新建规则（id 冲突 409；校验 id/cron/动作/guard + 顶层字段白名单） |
| `PUT /api/automation/rules/{id}` | `{enabled?, description?, trigger?, condition?, action?, guard?, follow_up_action?}` | 修改规则（改 cron / after_seconds 后**立即重排下次触发**） |
| `POST /api/automation/rules/{id}/reset-runs` | — | **重置该规则目标任务的执行次数与冷却**（Guard 的「单任务执行上限」撑满后用它放行）：目标用 `rules.resolve_rule_targets()`（与 `/automation/status` 的 `progress` 同一口径，忽略状态类条件），**主动作与接力动作都清**；同时清掉连续失败计数与熔断标记；返回 `{task_count, tasks, actions, cleared:{counts,cooldowns,last_results}, progress}`（`progress` 是重置**之后**的进度） |
| `DELETE /api/automation/rules/{id}` | — | 删除规则（含其冷却/计数/熔断/下次触发历史） |
| `POST /api/automation/rules/{id}/run` | — | 立即触发一条定时规则（不等 cron） |
| `GET /api/automation/decisions?limit=` | — | 决策日志（五态） |
| `GET /api/automation/runs?limit=` | — | 动作运行记录 |
| `POST /api/automation/reload` | — | 显式重载配置（本该每次现读） |

返回值约定：

- `dry_run=true` → `{status: "dry_run", preflight_ok, preflight, will_do}`，**不执行、不写状态**；
- 短动作 → `{status: "success"|"failed"|"skipped"|"blocked", result, audit_id, reason}`；
- 长动作 → `{status: "running", run_id}`（`frac.create` / `neb.create`）；
- `task.continuation` 的**业务结果**在 `result.action`：只有 `created` 才算创建成功，
  `running` / `input_complete_but_not_finished` / `input_incomplete` 一律按 `skipped` 记账。

`GET /api/automation/status` 里每条规则（定时任务行同）带 `progress`：**已运行次数 / 单任务执行上限**
（前端显示成 `3/5`），计数口径与调度层 guard 完全一致（`counts["<task_id>|<action>"]`，接力动作各算一份）：

```json
{
  "action": "task.continuation",
  "follow_up_action": "task.submit",
  "limit": 5,                 // guard.max_runs_per_task，0 = 不限制
  "max_count": 1,             // 目标任务里用得最多的主动作次数
  "max_follow_up_count": 1,
  "target_count": 2,          // 命中（身份类）条件的目标任务数
  "targets": [                // 只回传前 20 个
    { "task_id": "task_..._5", "label": "Ag_20260830 · Ag@Al2O3_I4",
      "count": 1, "follow_up_count": 1, "matched": true }
  ]
}
```

> 选目标任务时**忽略 `status` / `converged` / `archived` / `job_id` / `frac_*` 这些"当前状态"字段**
> （它们只体现在 `matched` / `reason` 上）——否则任务一回到 pending/completed，已经用掉的次数就从界面消失。
> 撑满上限后自动化会被 guard 拦下（决策日志里是 `已达执行上限（5/5）`），需要 `reset-runs` 才继续。

规则文件：`data/config/rules/<id>.json`（一文件一规则）。前端配置规则时先选**作用对象**，
再（可选）加附加条件，映射关系：

| 作用对象 | 具体对象（可多选） | 生成的 condition | 定时规则的 scope |
| --- | --- | --- | --- |
| 项目 | 具体项目（留空=全部） | `project`（单值或列表） | 只涉及 1 个项目 → `project:<名>`，否则 `all` |
| opt 任务（结构优化） | 具体任务（**树：项目 → 组/独立任务 → 任务**，可搜索） | `task_type=opt` + `task_id`（单值或列表） | 同上（按所选任务反查项目） |
| NEB 任务（路径计算） | 具体 NEB 任务（**树：项目 → NEB 组 → 任务**，可搜索） | `task_type=neb` + `task_id`（单值或列表） | 同上（按所选任务反查项目） |
| 自由能组 | 具体路径组（**树：项目 → 自由能组**，可搜索） | `group_type=free_energy` + `group_id`（单值或列表） | 同上（按所选组反查项目） |

附加条件（可选，界面全是下拉，字段带中文名与说明）：

| 字段 | 取值 |
| --- | --- |
| `status` | 多选：待提交 / 排队中 / 运行中 / 已完成 / 未收敛 / 异常（僵尸）/ 已归档 |
| `group_role` | 多选：自由能结构优化 / 频率矫正 / NEB 初态优化 / NEB 末态优化 / NEB 映像计算 |
| `converged` / `frac_missing` / `initial_converged` / `final_converged` / `images_created` / `is_continuation` / `archived` | 是 / 否 |
| `model_name` | 手填（带示例提示），用于锁定某个具体任务 |

> 条件字段有**白名单**：`rules.CONDITION_KEYS`（与 `build_context()` 输出对齐）。
> 写错字段名会被 400 拒绝并列出可用字段，不会出现"规则静默永不命中"。

> **规则顶层字段也有白名单**（`routers.automation.RULE_FIELDS` = `id / enabled / description / trigger /
> condition / action / guard / follow_up_action`）：新建与编辑时多写或拼错字段一律 **400**，
> 不会静默丢弃。可用字段在编辑接口里是 `EDITABLE_FIELDS`（同上，但 `id` 不可改）。
> ⚠️ **维护提醒**：给规则加新字段时，**四处**要一起改 —— `RULE_FIELDS`（校验白名单）、
> `EDITABLE_FIELDS`（PUT 可覆盖）、`GET /api/automation/status` 里对规则的**逐字段投影**
> （前端自动化页读的是它，漏字段 = 界面上看不到/回显不出来）、前端 `RuleModal` 的 payload。
> 两次真实事故：v0.9.13 漏 `EDITABLE_FIELDS` → "勾了保存不生效"；v0.9.14 漏 status 投影 →
> "保存成功了但重开弹窗还是未勾"。

```json
{
  "id": "opt-unconverged-continuation",
  "enabled": true,
  "trigger": { "type": "inspection_completed" },
  "condition": { "task_type": "opt", "status": ["unconverged", "zombied"], "is_continuation": false },
  "action": "task.continuation",
  "guard": { "cooldown_seconds": 1800, "max_runs_per_task": 5 },
  "follow_up_action": "task.submit"
}
```

> `follow_up_action`（可选）：主动作**成功**后自动接着执行的动作（典型用法：续算成功 → 提交作业；
> 界面上就是「动作」右边那个"执行成功后自动提交作业"勾选项）。续算未真正创建（`action != created`）
> 或主动作失败时不会接力；手动动作入口 `POST /api/actions/{name}` 也支持顶层 `follow_up` 参数。
> 幂等去重只认显式传入的 `idempotency_key`，重复次数由 `guard` 的冷却与上限控制。

> **NEB 也走同一条动作链**（v0.9.15）：`task.continuation` 支持 `task_type` 为 `opt` 或 `neb`
> （NEB 续算 = 最新 conN 优先、端点 POSCAR+OUTCAR 固定、中间映像 `CONTCAR→POSCAR`、各映像 WAVECAR
> 随续算移动；有活跃作业时不建目录），提交侧按 INCAR 的 `IMAGES` 逐个检查映像 POSCAR。
> 因此「作用对象 = NEB 任务 → 动作 = 创建续算 → 勾选自动提交」就能覆盖 NEB 的日常续算；
> NEB 常用的附加条件是 `initial_converged=是` 与 `final_converged=是`（初末态都收敛才值得续算映像）。

> **续算编号以远端为准**（v0.9.16）：`conN` 是远端扫出来的（远端的 `con(N+1)` 一定还不存在）。
> 若远端被手动"打回重算"（远端只剩 con1、本地还登记着 con2..con5），远端重新数出来的编号会与本地旧记录
> 同路径 —— 这时接口**复用**那条本地记录（状态回 `pending`、清 `job_id`，备注记录原状态），返回里
> `reused: true` / `previous_status` 会标明，**不再返回 409**，自动化不会因此中断。
> 系统不参与、也不清理用户的远端重算操作；本地"远端已不存在"的旧记录保持原样（不删、不改）。

> 前端界面用**中文日程**表达（每天 02:00 / 每周一 08:30 / 每隔 30 分钟 / 30 分钟后执行一次），
> 不要求用户理解调度表达式；下面两种存储形式是接口层的形态（脚本/智能体可直接使用）。

定时规则有两种模式（都要带 `scope`，支持 `all` 或 `project:<项目名>`）：

```json
{ "trigger": { "type": "schedule", "mode": "cron",  "cron": "0 2 * * *", "scope": "all" } }
{ "trigger": { "type": "schedule", "mode": "after", "after_seconds": 1800, "scope": "all" } }
```

- `mode=cron`：按表达式周期执行（界面上对应"每隔 N 分钟 / 每隔 N 小时 / 每天 / 每周 / 每月"，也可自定义）；
- `mode=after`：**N 秒后执行一次**（一次性）。新建/修改规则时按 `now + after_seconds` 排期，
  触发一次后 `next_run` 清空、`last_fired_at` 记录，不会重复；要再来一次就在页面上点
  「重新计时」（等价于重新保存该规则），或对同一规则 `PUT` 一次。
- 两种模式都支持「立即触发」：`POST /api/automation/rules/{id}/run`。全局开关在 `data/config/automation.json`：
`{enabled, dry_run, schedules_enabled, disabled_rules, failure_threshold}`。

> **报告里的能量/力曲线（v0.9.60 迁移）**：后端仍生成 `charts/<task_id>_energy_force.svg`
> （**导出单文件 HTML 用这张静态图**），但**报告页**会把这张 `<img>` 就地换成 ECharts 组件
> （`components/common/EnergyForceCharts.tsx`，与巡检详情同一套配置 → 悬停十字线 + 两图联动），
> 数据取结构化载荷里的 `science.opt[].energy_force_series`（[`{step, energy, max_force}`]）。
> 即"同一份数据，页面交互渲染、导出静态渲染"；要不要在导出里也内联 ECharts 运行时见 §10 待办。

## 4.4b PDOS 分析链路（v0.9.45 重建，仅电子结构任务）

> 入口：**巡检详情 → 电子结构分析章节的一级标签页 `[PDOS] [Bader] [COHP] [功函数]`**
> （2026-10-13 用户口径：从下拉二级菜单改回并列标签，**切到哪个标签才加载哪个**）。
> 链路 = 远端 vaspkit 提取 → 整合数据回传 → 本地解析成"菜单树 + 曲线" → 前端画图。
> **vaspkit 的原始 `.dat` 不回传**（远端临时目录跑完即清），本地只存一个整合数据文件 + 一个轻量元数据。

| 接口 | 说明 |
| --- | --- |
| `POST /api/jobs/tasks/{id}/pdos/analyze` | **异步触发**：上传 `scripts/dos_extract.py` 到任务远端目录并执行（`vaspkit -task 111/113`），整合 JSON 回传本地。返回 `{run_id, status, reused}`；同一任务已有分析在跑时 `reused=true`（不会并发跑两遍） |
| `GET /api/jobs/tasks/{id}/pdos/status?run_id=` | 轮询：`{run_id, status: idle/running/done/failed, error, has_data, meta}`；`run_id` 可省（取该任务当前/最近一次） |
| `GET /api/jobs/tasks/{id}/pdos` | 解析结果 `{meta, energy:{total,partial}, tree, series}`；**没分析过返回 404**（前端据此显示"开始分析"）。`meta` 含 `efermi / spin_polarized / elements / has_projection / has_fine_orbitals / notes` |
| `DELETE /api/jobs/tasks/{id}/pdos` | 清除本地结果（`pdos/dos.json` + `meta.json` + 内存缓存/运行状态），便于重新分析 |

**存与解析**：`<任务本地目录>/pdos/dos.json`（远端回传的整合数据，唯一大文件）+
`pdos/meta.json`（分析时间、run_id、费米能级、自旋、元素、文件字节数、失败原因）；
解析结果按文件指纹缓存在内存（同一文件不重复解析），首次分析时同步写元数据。
**权限**：四个接口都走 `_resolve_task`，越权一律 403。

**带中心（band center，v0.9.55 · 纯前端）**：前端底部「带中心」勾选框打开后，对**当前显示的每条曲线**
在下面「范围」内做加权平均能量 `∫E·DOS(E)dE / ∫DOS(E)dE`（梯形积分 + 区间边界线性裁剪）：

- **含未占据态** —— 区间跨过 E_F 也照算（用户 2026-10-15 口径：d 带中心本来就是按占据+未占据的
  加权平均来表征吸附活性，只看占据态会丢掉反键态那一半）；**up / down 各自算**（每条曲线一个值）；
  数值**相对 E_F**（与横轴一致）。
- 呈现：图例芯片里显示每条曲线的带中心数值；曲线图上画同色**垂直虚线 + 数值标签**
  （显示 ≤4 条时全画 —— 常见的"选一组轨道 = up/down 两条"；更多时只画「只看这条」选中的那条）。
- **不需要任何新接口/远端调用**：数据（`energy` 网格 + `series.values`）本来就在 `GET .../pdos` 载荷里，
  改「范围」（两个输入框 / 自适应）即实时重算。
- 实现：`src/utils/bandCenter.ts`（`bandCenter` / `bandCenters` / `formatCenter`）+ `PdosPanel`。

**逐曲线配色（v0.9.56，v0.9.57 扩到 120 色）**：`tree[].curves[].color` 以前**同一元素的所有曲线
共用一个颜色**（Fe 的 dxy/dyz/dz2/dxz/dx2 与 up/down 全同色），现在改成**每条曲线一个颜色**
（`pdos.py::_CURVE_PALETTE`，**生成式 120 色**：黄金角布色（相邻色相差 ~137.5°，视觉差异最大）
+ 亮度三档循环，色相避开总态密度的蓝；总态密度固定蓝色族 up `#5B8DEF` / down `#8AB4F8`）。
实测真机：model1 34 条曲线 / 34 色、model2 74 条曲线 / 74 色，**零重色，up/down 永不撞色**。
按菜单遍历顺序轮转取色 → 同一次分析里颜色稳定（勾掉别的曲线不会换色），
且 **up/down 紧挨着取色 → 必不同色**。带中心虚线再叠加两道区分：**up 长虚线 `[7,4]` / down 点线 `[2,3]`**，
且两条带中心挨得近（< 可视范围 4.5%）时**数值标签自动错行**（`distance` 6/20/34/48 px 循环）。
**注意**：改了配色口径后，已存在的 PDOS 分析需要**重开一次页面**（视图按 30s 文件指纹缓存；
重启后端即清内存缓存），数据本身不用重算。

**菜单树三级**（用户口径：一级总态密度 / 二级元素×轨道 / 三级只对 p、d 分方向）：

```
total                          总态密度（自旋时 up/down 两条）
el:Fe                          （元素节点，仅分组）
  el:Fe:s  el:Fe:p  el:Fe:d    （轨道；p/d 还有下一级）
  el:Fe:d:dxy / dyz / dz2 / dxz / dx2      （方向投影，界面显示 dx²−y²）
```

曲线数值放在顶层 `series`（`id → {grid, values}`），`grid` 指向 `energy.total`（总态密度，点数 = NEDOS）
或 `energy.partial`（元素/轨道投影，已按用户要求**丢弃 EMIN 首行**，比总态密度少 1 点）。
能量为**绝对能量**（提取脚本已把 vaspkit 的 `E−Efermi` 校正回来）；前端画图时减 `meta.efermi`
得到相对费米能级的横轴。

---

## 4.5 待确认队列：AI 提案 → 人工批准（v0.9.42）

**AI 触发的 confirm 级动作不直接执行**，先入队；人工看过再决定执行/驳回。
动作的实现与自动化调度**完全共用**（`automation/actions.py` 的 `preflight` + `execute`），
入队不占用算力、不改任务状态。

| 接口 | 谁用 | 说明 |
| --- | --- | --- |
| `GET /api/pending-actions/catalog` | 双方 | 可用动作目录（动作名 / 说明 / 是否长动作 / 参数提示），= `GET /api/actions` 的内容 |
| `POST /api/pending-actions` | **AI**（token scope 需 `propose`） | 提交提案：`{action, payload:{task_id,...}, reason?, project_name?, task_name?}`；**只入库不执行** |
| `GET /api/pending-actions` | 人工 | 队列（新 → 旧）：`?status=pending,approved,rejected,failed` / `?project=<项目名>` / `?limit=`，返回 `{items, counts, available_actions}` |
| `POST /api/pending-actions/{id}/approve` | **人工** | 批准 → 真正执行；执行失败标 `failed` 并留 `error`（不抛给调用方） |
| `POST /api/pending-actions/{id}/reject` | **人工** | 驳回，只改状态 |

返回值与约束：

- 提案条目字段：`id`（`pa_00001`）/ `created_at` / `status` / `action` / `action_label` / `payload` /
  `reason` / `requested_by` / `requested_kind`（`agent` | `user`）/ `project_name` / `task_id` / `task_name` /
  `decided_at` / `decided_by` / `decision_note` / `result` / `error`；
- 状态机：`pending` → `approved`（执行成功）/ `failed`（执行报错，`error` 有原因）/ `rejected`（人工驳回），
  已处理的条目**重复处理返回 400**；
- **归属校验在入队时做**：带 `task_id` 的提案会反查项目并 `ensure_project_owner`，AI 只能对自己可见的任务提案
  （不可见的任务返回 403，不存在的返回 404）；
- **agent 账号不能批准/驳回**（`role=agent` 一律 403：`AI 不能自审自批`），只有人类会话能处置；
- 落盘 `data/pending_actions.json`（原子写 + 进程内锁）；**提案 / 批准 / 驳回各写一条审计**
  （`data/audit/actions.jsonl`，`command` 为 `auth.pending-propose` / `auth.pending-approve` / `auth.pending-reject`，
  带 `ip` 与 `detail`，便于追溯"谁让 AI 做了什么"）。

```bash
# AI 侧：发现某任务该续算 → 提案（不执行）
curl -s -X POST -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"task.continuation","payload":{"task_id":"task_1789455573013_1"},"reason":"连续两轮 unconverged，建议续算"}' \
  http://192.168.1.20:3001/api/pending-actions | jq '.data.item.id'

# 人工侧：看队列并批准
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" 'http://192.168.1.20:3001/api/pending-actions?status=pending' | jq '.data.items'
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://192.168.1.20:3001/api/pending-actions/pa_00002/approve | jq '.data.item.status'
```

---

## 4.6 AI 专用入口（`/api/ai`，v0.9.42）

给智能体的**稳定调用面**：只做别名与自查，**不复制业务逻辑**（内部转调既有实现）。

| 接口 | 等价于 | 说明 |
| --- | --- | --- |
| `GET /api/ai` | — | **入口清单** + 自身身份：`{actor:{username, role, delegate_to, scope, scope_meaning}, entrypoints[], hint}` |
| `GET /api/ai/contract` | `GET /api/reports/project/schema` | 数据契约：状态族 / 单位 / 时间格式 / 字段别名 |
| `GET /api/ai/tasks/{task_id}/context` | `GET /api/jobs/tasks/{id}/context` | **任务上下文**（AI 决策的唯一入口）：`?n_checks&n_actions&refresh` |
| `GET /api/ai/tasks/{task_id}/outcar-tail` | `GET /api/jobs/tasks/{id}/outcar-tail` | OUTCAR 尾部：`?lines&image` |
| `GET /api/ai/pending-actions` | `GET /api/pending-actions` | 自己的提案在队列里的状态：`?status&limit` |
| `POST /api/pending-actions` | — | 提交提案（需 `scope=propose`），见 §4.5 |

建议顺序：`GET /api/ai`（我能做什么）→ `GET /api/ai/contract`（字段怎么读）→
`GET /api/ai/tasks/{id}/context`（这个任务发生了什么，含 `hints.missing`）→ 需要时
`POST /api/pending-actions`（把结论变成待人工批准的动作）。

---

## 4.7 知识层（`data/knowledge/`，v0.9.42 起积累）

给"异常识别 / 处置建议 / 报告撰写"逐步积累素材，**只落文件，暂不接推理**：

| 文件 | 内容 | 维护方式 |
| --- | --- | --- |
| `data/knowledge/vasp_errors.md` | **VASP 常见错误对照表**（30 类：电子步 / 结构 / 运行时 / NEB / DFT+U），每行带「机器库 id」与 `data/config/check_errors.json` 对照 | 手工补充；新增机器规则时同步 |
| `data/knowledge/incar_reference.md` | INCAR 常用参数速查（作用 / 取值 / 搭配 / 相互影响） | 手工补充 |
| `data/knowledge/error_cases.jsonl` | **错误案例库**：一行一案例（错误特征 / OUTCAR 片段 / 处理方式 / 结果） | 处理完真实错误后 `python3 scripts/log_error_case.py ...` 追加 |
| `data/reports/structured/<report_id>.json` | **报告结构化副本**（含 `ai_view` 规范化视图） | 生成报告时自动落盘（`report_store.save_report`），供后续向量化/RAG |

```bash
# 记一条错误处理案例（纯标准库，不需要 venv；--outcar 省略时自动取任务 reports/outcar_tail.txt）
python3 scripts/log_error_case.py --project FS_Kaolin --task task_1789455573013_1 \
  --error E_ZBRENT --keywords "ZBRENT: fatal error in bracketing" \
  --summary "POTIM 0.5→0.2，IBRION=2→1 重跑" --changes "IBRION=2->1,POTIM=0.5->0.2" \
  --outcome resolved --note "续算第 12 离子步达标"
```

---

## 4.8 AI 工作台

前端 `/ai`，接口统一前缀 `/api/ai/chat`。支持对话、本地上下文及按项目约束的文件工作区；不开放任意代码/SSH或计算执行，报告和托管计划按专用工具写入。需人类账号登录；每条连接、会话和运行按 `user_id` 隔离，即使管理员也不能通过这些接口读取其他人的私有记录。项目会话额外检查当前项目可见权限，失去权限后不再返回历史内容。

| 方法 | 路径（省略前缀） | 用途 |
| --- | --- | --- |
| GET / POST | `/connections` | 列出 / 创建私有模型连接 |
| PUT / DELETE | `/connections/{id}` | 编辑 / 删除连接 |
| POST | `/connections/{id}/test` | 只查询 `/models` 验证连接，不发起生成 |
| GET | `/targets` | 当前账号可见的项目与任务 |
| GET / POST | `/conversations` | 列出 / 创建通用或绑定项目的会话 |
| GET / PUT / DELETE | `/conversations/{id}` | 历史、会话名称/提示词/模型设置、删除；GET 的 `before` 用于更早消息分页 |
| GET | `/conversations/{id}/context` | 最新本地快照，不触发远端同步 |
| GET | `/conversations/{id}/workspace` | 项目目录地图、主任务本地位置及远端来源、工具开关 |
| GET | `/conversations/{id}/workspace/files` | `path` 虚拟相对目录、`offset` 分页，最多100项；根目录用空路径 |
| GET | `/conversations/{id}/workspace/file` | `path` 文本文件、`offset` 字节偏移、`tail`，最多12000字节；含时间和分片哈希 |
| POST | `/conversations/{id}/messages` | `{content, retry, request_id}`；创建回答运行，返回 run；同一 request_id 去重 |
| GET | `/runs/{id}` | 运行、用量及当时的提示词 / 上下文快照 |
| GET | `/runs/{id}/events` | 带认证的 SSE；只订阅已有运行，不产生新的模型请求 |
| POST | `/runs/{id}/cancel` | 停止接收并关闭上游流，保留已显示的内容 |

连接创建/编辑字段：`name`、`base_url`、`model`、`api_key`、`max_tokens`（128–32768，默认 2048）、`is_default`。基础地址通常形如 `https://provider.example/v1`，第一版支持 OpenAI 兼容 Chat Completions SSE。常规模型发送 `max_tokens`；gpt-5 / gpt-6 / o 系列发送 `max_completion_tokens`。不自动重试生成以避免重复计费。协议参考 [OpenAI 官方流式指南](https://developers.openai.com/api/docs/guides/streaming-responses) 与 [Chat Completions 参数说明](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。服务商未在流中返回 usage 时显示未返回，不伪造 token 用量。

**保密**：API Key 只写不读，所有响应都不带原值或密文；后端 Fernet 加密密钥，数据库目录 0700、文件 0600。主密钥默认 `~/.config/vasp-manager/ai.key`，可用环境变量 `VASP_AI_KEY_FILE` 指定，独立于 `data/ai/chat.sqlite3`。主密钥丢失后需重新配置连接；当前任务不要求新增备份，凭据不得加入Git。模型接口不跟随 HTTP 跳转；更换基础地址须重新输入密钥。远端 API 要求 HTTPS，本机模型允许 HTTP；从浏览器配置密钥也要求 HTTPS 或本机端口转发。不要向聊天框粘贴凭据。

**项目级附加上下文（2026-10-18 调整）**：新建会话使用 `{title, project_id, connection_id}`；不传 project_id 则为通用会话。旧 task_id 创建参数仍兼容，但会解析为所属项目。会话绑定项目后不允许编辑为其他项目，避免混用聊天历史；同一项目可创建多个独立会话。旧任务会话启动时补齐 project_id，保留原 task_id、标题、消息、提示词和旧回答快照，不合并历史。权限按当前项目可见范围重新校验。

上下文接口现在返回完整项目概览：项目说明/目标/预期、全部主任务的类型/状态/分组/作业/目录/能量/力/NEB结果摘要、最近巡检与操作记录。附属续算和分块不重复列为主任务，其操作仍可出现在项目日志。聚合只读本地、共用巡检缓存，不逐个任务读取大文件。发送模型时遵循字符预算，任务较多先转为 task_table（columns/rows），保留覆盖数量；确实超预算时由 summary.included_task_count / omitted_task_count 和 budget_note 明确说明。侧栏展示完整本地概览，“本轮依据”展示实际发给模型的版本。

**DeepSeek 官方接口**：模型连接中点击“填入 DeepSeek 官方配置”，基础地址为 `https://api.deepseek.com`，默认 `deepseek-flash`、8192 tokens、直接回答；也可选择 `deepseek-v4-pro` 或手填服务商返回的模型名。连接新增 `thinking_mode=default|enabled|disabled`；仅对 DeepSeek 官方域名的当前型号发送 `thinking.type`，其他兼容接口不附加该参数。官方连接请求包含 `stream_options.include_usage=true`。思考片段不作为最终回答保存或回传；工作区沿用显式思考深度；必要思考链仅本轮内存延续，不写历史。只有思考、没有最终答案时提示提高输出上限或改用直接回答。旧连接自动增加默认模式字段，密文及关联会话保留。参考 [DeepSeek 官方接入说明](https://api-docs.deepseek.com/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode) 与 [Chat Completion 参数](https://api-docs.deepseek.com/api/create-chat-completion)。

**上下文**：工作台使用上文的项目级聚合，按需读取本地任务元数据、共用巡检缓存与项目操作日志；通用会话不附加任何项目数据。每次发问重建观测快照，任务结果与结构来源目录不一致时明确提示。原有 `/api/ai/tasks/{task_id}/context` 仍保留单任务接口契约，工作台不再以它作为唯一附加单位。

**长度与恢复**：完整历史保留；每轮最多选取 40 条、24000 字符的近期历史，项目快照预算 28000 字符，截断/省略会标明，可在“本轮依据”查看。第一版没有自动语义摘要。单账号最多 3 个并发回答，同一会话只允许 1 个。断开页面不取消后台回答；重新打开可继续订阅。后端重启将未结束运行标为 interrupted，不自动重发付费请求。

**项目文件工作区**：每轮项目上下文仅附 `workspace_rules` 简短规则（项目边界、只读/草稿权限、地图查询入口），不附完整 `directory_map` 或任务 `workspace_path`。模型需定位文件时调用 `read_workspace` 读取 `evidence/directory-map.json`；前端完整地图接口保持不变，地图仍沿用 `task_paths.py` 的布局约定。虚拟根为 `project/`、`reports/`、`evidence/`、`knowledge/`、`reference/`（只读）和 `work/`（会话私有草稿）。模型文件工具为 `list_workspace`、`read_workspace`、`write_workspace`，另有只读巡检工具 `find_project_tasks`、`get_task_inspections`、`get_inspection_evidence`；禁用路径越界、符号链接、敏感文件及覆盖。写入仅新建 work 文件，单文件120000字节、每会话4 MiB/100文件。不设每轮工具总调用次数或总推理轮数上限；单次模型响应最多12个并行工具调用，工具结果总预算90000字符，分析总时限10分钟。触发资源/协议边界时拒绝相应请求，补齐同批未执行调用的拒绝结果，转入一次无工具总结（最多60秒/12000字符）；模型仍不返回正文或接口失败时提供明确收尾说明，不重复执行已成功操作。工具自身的参数/配额/权限拒绝继续作为工具错误反馈；人工停止/撤权不再请求模型，真实接口故障保留failed且显示说明。后续推理与总结累计服务商已返回的实际usage，不自动重试已可能计费请求。`tool_events` 保留意图、参数、结果和状态，并随运行/SSE返回；服务重启的未结束工具标为 interrupted。PUT 会话可传 `workspace_enabled`；新建项目会话默认启用，已有会话原地升级默认关闭。通用会话不可启用。不兼容工具协议可关闭，无自动降级重试。凭据和全局状态继续由后端持有；不提供远端、代码执行或正式文件应用。详见 [docs/ai-workspace.md](docs/ai-workspace.md)。


**模型按需巡检链路**：在启用工作区的项目会话中，由模型按问题定位任务并调用 `get_task_inspections(task_id, limit=3)`，默认最近3个计算目录、最多5个目录各自的最新观测；同目录后续巡检更新覆盖，不保留该目录多次巡检时间序列。需要具体曲线/参数/NEB数值时再调用 `get_inspection_evidence(task_id, observation_id, kind, offset=0)`。查询返回完整JSON，而非页面截图或任意字节截断；原始字段缺失不从最新汇总补填，跨目录/作业/参数阶段不直接计算差值。观测被同目录更新或超过5目录保留范围时明确报错、需重新查询。名称歧义可用 `find_project_tasks(query)`，返回本项目最多20个候选。参与自动巡检的实时决策证据缺失、超过后端4小时阈值或未来时间异常时提示刷新，历史完成结果不机械按年龄失效；均不发SSH。工具定义属于模型请求协议，不是新增公开HTTP动作路由；工具参数、原始数值证据及状态持久化到运行 `tool_events`，可在本轮依据审阅。工具能力继续由工作区开关控制。

新巡检总能统一使用已输出的离子步 `TOTEN`（含色散修正），不使用未完成电子迭代的能量。历史巡检摘要及详情按归档原值返回，不在读取时重解析或自动更正，也不返回 `energy_correction`；原始归档、`observation_id` 和已冻结报告/聊天保持原样。后续实际巡检产生的新观测按新取数规则更新。

**个人操作经验**：原私有工作台新增 GET `/api/ai/chat/work-experience`（本人设置/最近50经验与100操作/Markdown），PUT `/work-experience/settings`（enabled、本人connection_id），POST `/work-experience/learn`（手动整理，每自然周最多两次尝试，自动最多一次），PUT `/work-experience/{id}`（title/body/confirmed/disabled，禁止改owner/项目/来源）。模型只读工具 `search_work_experience(query)` 使用中文关键词检索，最多5条，当前项目优先，仅本人及当前可访问项目；停用立即排除。周整理输入最多40事件/16000字符、输出2048token，候选不证明通用规律或计算收敛。日志每周压缩保留28天/64MiB，提交统计独立累计；经验存私有SQLite与Markdown，不进共享knowledge目录。见[操作经验](docs/operation-learning.md)。

**模型按需结构工具**：`check_structure(structure, reference?, pbc?)`按整体结构/优化重构迹象→局部配位/界面→计算设置返回全原子筛查；元素/赝势为基础核对项，不默认最高优先级。参考省略时CONTCAR尝试同任务POSCAR（远端MAIN，本地镜像）；缺默认参考标未知，显式参考缺失报错。固定只读同目录INCAR/POTCAR摘要/OUTCAR头，未证明同次计算、不自动判相/变性或收敛。原项目工作台还提供 `get_structure_summary(structure, pbc?, axis?, atom_offset?, layer_gap_angstrom?)`、`get_structure_environment(structure, pbc?, atom_indices?|elements?, neighbor_elements?, cutoff_angstrom?)`、`compare_structures(reference, target, pbc?, pairs?)`。结构selector为 `{task_id, file?:POSCAR|CONTCAR, source?:local|remote, directory?:CURRENT|MAIN|conN, image?, expected_sha256?}`；默认CONTCAR/local，directory仅远端支持，NEB必须指定映像。每次重查当前项目/任务归属，远端只读固定结构文件，不触发巡检/同步/HPC动作。返回Å/°几何值、完整sha256、采集/文件时间及来源selector；后续携带指纹防混用。概览坐标每页24原子；环境最多6中心/16邻居及最近6邻居夹角；文件1 MiB/2000原子，有搜索预算和截断标记。跨任务不自动映射原子，变胞不报告逐原子位移，几何邻居/分层不等于成键/物相判定。仅工具协议增量，无新增HTTP动作路由或结构预加载；见 [结构工具](docs/structure-tools.md)。

## 5. 现有自动化与托管执行边界

固定规则、受控网关和单OPT有限循环已存在，不再把dry-run、幂等键、审计或触发调度列为“未实现”。外部Agent执行通过 `/api/agent-execution/actions`、有效授权/预算与稳定幂等键；不能绕到原人工submit/continuation端点。需审批的动作走pending-actions，已授权动作不逐次要求人工。

当前M0可保存计划和预览资源，尚未接通整轮候选仲裁、运行中异常分流和自动执行。单OPT也不是跨任务科研工作流，具体适用/停止条件见 [执行](docs/execution.md) 与 [托管](docs/managed-compute.md)。

动作成功不等于计算收敛；bsub结果未知先对账，人工停止依bkill返回更新本地但不代表科学收敛，再提交仍须通过实时活跃检查。调用方须同时看HTTP、业务状态和记录身份。

## 6. 维护约定

- 新增或变更接口时更新本文档：新增/变更接口、body 字段、前置条件、耗时与风险级别。
- 本文档只描述**对外可见的 HTTP 面**；内部函数（`inspection_runner`、`continuation`、`input_state` 等）见相关源码和 `process.md`。
- 变更接口时优先改代码 → 再更新本文档；发现不一致以代码 + `/docs` 为准并立即回来修正。


### 作业管理结构展示同步（2026-10-19）

无新增后端接口或巡检回传变更。前端巡检请求成功返回后、切换任务时，作业页面重新读取现有 `GET /api/jobs/tasks/{task_id}/input` 中的本地结构，仅更新POSCAR/CONTCAR展示，不回填参数编辑器。不定时轮询、不添加后台推送、不触发远端结构同步；本轮未回传结构时继续使用本地已保存结果。

## 阶段1：受控自主执行（2026-10-19，已部署，默认关闭）

独立于旧automation开关，新入口默认关闭；没有授权不能执行。完整边界和必要验证入口见 `docs/execution.md`。AI工作台尚未注册执行工具。

| 方法与路径 | 权限与作用 |
| --- | --- |
| `GET /api/agent-execution` | 当前可见授权及动作台账；Agent仅看自己的授权 |
| `PUT /api/agent-execution/settings` | 仅admin；`{"enabled":true/false}`，暂停不停止已有HPC作业 |
| `POST /api/agent-execution/grants` | 人工项目owner/admin创建授权；初始enabled=false、managed=false |
| `PATCH /api/agent-execution/grants/{id}` | 人工owner/admin；只接受`{"enabled":true/false}`，不能由Agent改预算 |
| `POST /api/agent-execution/actions` | Agent有效write scope或项目人工身份；必须有有效grant、动作/任务白名单和幂等键 |
| `POST /api/agent-execution/actions/{id}/reconcile` | 人工owner/admin只读对账；没有bsub或队列重放 |
| `POST /api/agent-execution/tasks/{task_id}/reconcile` | 人工owner/admin按任务族只读对账；返回blocked/job_id/scheduler_state/reason；不重新提交、不强制解除UNKNOWN |
| `POST /api/agent-execution/actions/{id}/resolve-not-submitted` | 人工确认未知动作没有提交；`confirmed_no_submission:true,evidence`，证据至少20字 |
| `POST /api/agent-execution/actions/{id}/resolve-finished` | 已知Job ID但历史已清理时人工确认结束；`confirmed_finished:true,evidence`，按申请上界结算 |

授权示例（仅说明协议，不代表已启用生产）：

```json
{
  "agent_username": "project_agent",
  "task_ids": ["existing_task_id"],
  "allowed_actions": ["task.submit", "task.continuation"],
  "queue": "normal",
  "limits": {
    "max_active_jobs": 1,
    "max_submissions": 3,
    "max_retries": 1,
    "max_core_hours": 48,
    "max_walltime_hours": 1,
    "max_cores": 24
  }
}
```

前三项有保守默认，后三项必须显式配置。一个授权只能对应一个项目、服务器和CPU队列；绑定任务根目录、任务类型及服务器目标指纹，变化后必须重新授权。新授权未启用时不影响旧规则；首次显式启用后任务进入托管范围，旧规则不能绕过预算，暂停也不会恢复该旁路。

执行示例：

```json
{
  "grant_id": "grant_...",
  "task_id": "existing_task_id",
  "action": "task.continuation",
  "follow_up": "task.submit",
  "idempotency_key": "stable-intent-identifier",
  "params": {},
  "dry_run": true
}
```

也可通过`Idempotency-Key`请求头提供键。仅允许现有task.submit、task.continuation、frac.create；仅continuation可接submit，后续动作也必须在授权白名单。阶段1不接受任意参数修改；续算子任务继承原任务授权但必须位于指定根目录的conN中。

响应仍为统一信封；data是持久动作记录，包含id、status、requested资源(resources)、reservation、job_id、时间、result/reason、事件和触发依据。状态为prepared/running/succeeded/failed/skipped/unknown/interrupted；succeeded仅表示动作执行完成。dry_run只返回预检与预算预览，不预留、不建远端文件、不提交；全局dry_run不能被请求覆盖。相同键返回原记录，参数改变拒绝；换键仍受预算/重试和未对账动作限制。

资源只解析静态CPU单作业LSF子集：固定`#BSUB -n`、`#BSUB -W HH:MM`、`#BSUB -q`，不支持的选项、动态声明、数组和GPU资源拒绝自动执行。并发预算事务内更新。实际核时尚无可信采集器，结束后以申请上界记`consumed_core_hours`，标注`consumption_basis=reserved_upper_bound`，不作计费数据。

审批提案payload需包含task_id、grant_id，可选follow_up。批准时重新校验项目归属和提案指纹，先持久化认领，再走同一网关；不能在批准请求中修改参数。旧无指纹提案需重新创建。Agent不能批准，也不能直接调用原submit/continuation/create-frac、修改配置或授权；原Agent无scope会话不能执行，scope=[]不再代表全权。

兼容变化：原人工提交仍不要求Agent预算，但新增LSF/持久台账安全闸门；提交响应或本地写入不确定返回503及unknown说明，禁止直接重提。可返回的错误data带action_id/execution_status。原`GET /api/actions/runs/{id}`现在能读取持久化短动作；重启的running不再直接冒充已知failed。SSH配置GET仅admin可读，GET/PUT均不回显password，改为password_configured；不提供password时保留后端已有凭据。

## 阶段R2：报告元素与专题组合（2026-10-20，已部署）

完整报告路径不变。新元素只引用Evidence，数据在组合的evidence映射中去重冻结，存储为 `data/reports/compositions/<项目>/<id>.json`，不参与完整报告单份清理。所有项目数据接口复用登录与项目归属校验；admin按原权限，Agent不能绕过受控网关直接写业务API。

| 方法 | `/api/reports/blocks` 后缀 | 说明 |
| --- | --- | --- |
| GET | `/schema` | 14类元素、renderer/scope和上限 |
| GET | `/{project_ref}/candidates?refresh=false` | 全授权任务轻量候选，不依赖Markdown/6条正文上限 |
| POST | `/{project_ref}/evidence` | `{type,task_id?,group_id?}` 本地解析，不保存；非法类型/错任务400 |
| POST | `/{project_ref}/preview` | 组合草稿→`{document,html}`，不写盘；已有组合带composition_id/expected_revision |
| GET/POST | `/{project_ref}/compositions` | 列表/创建 |
| GET/PUT/DELETE | `/{project_ref}/compositions/{id}` | 详情/更新/整份软删除 |
| POST | `/{project_ref}/compositions/{id}/check` | 比较冻结证据与当前数据，返回changes，不更新报告 |
| GET | `/{project_ref}/compositions/{id}/export.html?download=&print=` | 授权下载HTML/浏览器打印PDF；全部资源内联 |

`project_ref` 可为项目ID或名称。统一信封 `{success,message,data}`。

```json
{
  "title": "两模型专题",
  "blocks": [
    {"type": "task.energy_force", "task_id": "task_a"},
    {"type": "task.energy_force", "task_id": "task_b"},
    {"type": "project.comparison", "task_ids": ["task_a", "task_b"]},
    {"type": "task.convergence_curve", "task_id": "task_a"},
    {"type": "text.analysis", "text": "人工分析"}
  ],
  "groups": [], "hidden_block_ids": [], "deleted_block_ids": [],
  "expected_revision": 1, "refresh_evidence": false
}
```

- 所选参数对照 `task_ids` 为2至12个项目内任务；ID的variant按排序后的任务集合生成，引用多条task.params Evidence，不复制数据。没有task_ids的旧project.comparison仍是项目能量表。前端临时组合块可提交client_id=draft_…，后端将分组/隐藏/删除引用规范化为真实block_id。
- 更新必须提供整数expected_revision，缺省400，冲突409 `data.code=revision_conflict`。新建/新增证据按真实数据解析，提交过期引用409 evidence_stale。已有元素普通展示编辑直接使用服务器冻结证据；省略或伪造evidence payload/source_refs不能悄悄更新计算数据。只有布尔 `refresh_evidence=true` 明确更新证据，仍检查revision。预览/导出不重新加载当前PDOS。
- ID与版本分离；版本排除采集/解析时间以及基本信息中的运行时长。来源包含任务、目录/attempt、可匹配的巡检归档/observation_id、解析时间；本地分析文件保留SHA256，参数保留快照摘要与hash_scope。合并巡检可能跨观测补字段，来源说明明确此限制，不能等同单个OUTCAR原文全量验证。
- availability为available/missing/unparsed/unknown；validation与freshness另列。正文可见性有shown/omitted_limit/omitted_unconverged/omitted_no_history，不把省略当无数据。4小时过期只用于参加自动巡检的任务，排除项/未来时间为unknown。完整报告旧隐藏key保留，候选legacy_hidden_keys供显式导入稳定block_id；图序号/同名歧义不猜测。
- 14类已接本地Adapter：基本信息/参数/能量力/收敛/结构、自由能/NEB、PDOS/Bader/功函数/差分图、对照/分析文字/方法来源。原始DOSCAR等没有本地分析产物时保持unparsed，不执行分析、作业或SSH。CIF转换仅写系统临时目录，不回写模型；Bader只用分析时已有冻结CIF，缺失不冒充当前结构。
- 上限40块（含可恢复删除）、50份活动组合/项目、文字4000字；拒绝跨项目路径/符号链接，单读取文件超过24MiB返回说明。HTML使用既有安全Markdown/SVG、内联报告运行时/3Dmol，外部连接受CSP限制，iframe预览沙箱隔离。隐藏或删除块的独占证据不出现在导出来源附录。
- 元素恢复由deleted_block_ids控制；整份组合DELETE仅供脚本软删除，本阶段UI不提供整份删除/恢复。3D需WebGL；缺少现成结构PNG时PDF只有已有表格/数值和说明，不生成假的结构图。缺少报告运行时降级静态图。


## 旧作业历史缺失的人工处理（2026-10-20）

2026-10-22人工停止补充：指定job的bkill明确返回`No matching job found`/`No job found`也按幂等停止收尾，返回`job_not_found=true`、`confirmed_by=bkill_not_found`。清理本地运行状态和对应预留，台账记`NOT_FOUND`，不记科学完成。带job前缀的回执须匹配请求ID；SSH、权限、命令失败仍报错且保留状态。停止不额外轮询，后续提交仍实时检查活跃作业。

- `GET /api/agent-execution/tasks/{task_id}/prior-job`：项目owner/admin/已有归属Agent只读，返回当前LSF状态、task族阻塞、可确认标志、身份review_fingerprint、固定旧job_id.out回执摘要和建议核实依据。只在报错弹窗打开时查询，无定时轮询。读取任务根目录/最多100个conN目录的最多3份定名回执，每份只取头尾有界文本；回执不直接提供执行授权。
- `POST /api/agent-execution/tasks/{task_id}/prior-job/confirm-finished`：仅人工owner/admin，必须四字段 `{confirmed_finished:true, expected_job_id, review_fingerprint, evidence}`。核实依据20–4000字，确认时重查LSF并检查任务族锁、旧job ID/服务器签名/目录/归属未变化、无未完成或UNKNOWN动作；活跃或未知目录/LSF失败一律拒绝。写原agent_execution台账和严格审计，不改job_id、科学状态、预算开关，不提交/续算远端。
- 新前端仅在提交报“原作业无法在LSF确认结束”时显示弹窗；LSF回执必须匹配旧job ID、工作目录和结束时间，才能提供“确认旧作业已结束并解除报错”按钮。用户不必另外输入依据/勾选；一次点击是明确人工确认，服务端保存展示过的依据并重新查LSF。回执不全时保持阻塞，不把查不到当作结束。
- 确认按任务族+旧job ID+服务器目标+根目录+归属绑定；新job ID/换目标不复用旧确认，新提交仍重新检查LSF。已有actions/{id}/resolve-finished的人工确认也绑定此身份，可真正解除旧作业缺失检查。

2026-10-20台账同步补充（已随v1.1.2部署）：普通人工提交前和巡检异步事件后复用只读LSF对账，不改变巡检回传/频率、不新增轮询。终态与科学收敛独立；旧记录不恢复已停止作业号、不覆盖更新提交；来源变化/目录不符/查询失败保留阻塞。详见 [执行说明](docs/execution.md)。
