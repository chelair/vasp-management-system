# 00 · 阶段 0 基线审计（VASP 自主计算升级前的最小工程审计）

- 审计对象：`vasp-management-system` v1.0.1，`main` 分支 `099dfcb`
- 代码位置：`/home/zouyuxi/projects/vasp-manager`（ZYX-S，Ubuntu 26.04，Python 3.14.4）
- 审计时间：2026-10-19
- 方法：源码与测试直接阅读（含 4 路只读交叉审计）+ 只读查看生产运行态 + 新增最小离线夹具测试
- 边界：**未修改任何生产执行逻辑、未新增 Agent、未部署、未连接真实 HPC 执行有副作用的操作**

现有测试基线：`52` 个 unittest 全绿（3.1s）。本次新增 `10` 个离线用例全绿。两处均可复现，命令见 §5。

---

## 1. 可复用能力（阶段 1 直接扩展，不重写）

| # | 能力 | 位置 | 现状判断 |
|---|---|---|---|
| 1 | 动作目录 `ActionSpec`（preflight / execute / dry_run / long_running） | `automation/actions.py:38-53,145-163` | 已有三个动作：`task.continuation` / `task.submit` / `frac.create`；NEB 实现保留但未注册 |
| 2 | 调度层三件套：任务级锁（进程内 + `fcntl` 文件锁）、冷却、单任务次数上限 | `automation/scheduler.py:98-139,241-268` | 已实现，粒度 = `task_id` + `action` |
| 3 | 规则失败熔断、手动接管跳过 | `automation/scheduler.py:51-86,411-434` | 可用；阈值 `failure_threshold=3` |
| 4 | HTTP 动作端点与自动化共用同一把任务锁 | `routers/jobs.py:910-930,1237-1239,938-940` | 已修过一次「自动化接力 + 手动提交各拿一个作业号」事故（230578/230579） |
| 5 | 提交前远端非空预检（POSCAR/INCAR/KPOINTS/POTCAR/vasp.lsf，NEB 逐映像） | `routers/jobs.py:489-508,1187-1229` | 实质检查，一次 exec 完成 |
| 6 | `dry_run` 只跑到 `@@@CHECK_ONLY`，不 bsub、不写库 | `routers/jobs.py:500-508,534-542` | 提交动作的 dry_run 可信（只读 SSH 检查 + 一条审计） |
| 7 | 业务前置条件：`job_id` 且 `queued/running` → 409 | `routers/jobs.py:474-475` | 串行重复提交已被挡住 |
| 8 | 续算语义：只有 `action=created` 才算成功 | `routers/jobs.py:351-360`；`automation/scheduler.py:469-475` | 已有正确语义，可直接复用 |
| 9 | 五态动作审计 + 触发溯源 | `automation/audit.py:24-71` | 字段含 `trigger / trigger_id / rule_id / run_id / status / reason / elapsed_ms` |
| 10 | 事件总线：巡检只发事件，不直接调动作 | `automation/events.py:22-27,69-80` | 事件线程消费，避免巡检被动作拖死 |
| 11 | Agent 身份体系：`role=agent` + `delegate_to` + token `scope(read/propose/write)` | `permissions.py:111-165`；`middleware/auth.py:49-60` | 可见范围继承与单对象校验口径一致 |
| 12 | 待确认队列（提案 ≠ 执行；agent 不能自批） | `pending_actions.py:61-188`；`routers/pending_actions.py:128-154` | 提案时按 task 反查项目做归属校验 |
| 13 | 内建 Mock SSH + `_mock_bin` 打桩注入点 | `backend/ssh.py:48-176` | 阶段 1 的离线测试直接建在这上面（本次已用） |
| 14 | 数据目录隔离：`VASP_WEB_DATA_DIR` / `run.py --data-dir` | `config.py:11-12`；`run.py:14-21` | 测试可完全避开生产 `data/` |
| 15 | 单进程部署（uvicorn.run(app)，systemd `Type=simple`） | `run.py:29-34`；`/etc/systemd/system/vasp-manager.service` | 无多 worker，进程内锁 + 文件锁当前够用 |

**结论：阶段 1 需要的"动作执行 / 锁 / 预检 / 审计 / 身份 / 测试注入"全部已有，缺口集中在"预算、动作台账、UNKNOWN 对账、旁路收口"四项。**

---

## 2. 必须修复的风险

### P0（重复提交 / 越权 / 预算失控 / 数据破坏）

| # | 风险 | 证据 | 后果 |
|---|---|---|---|
| P0-1 | **bsub 已成功但结果不确定时无对账**：输出解析不到 `Job <id>` 直接 400，SSH 异常 502，落库失败只记 `DB_WARN`；三种都不写"未知"状态、不查 bjobs | `routers/jobs.py:513-514,554-577` | 远端已有作业，本地仍是 `pending`，下一次自动化/人工再提交 → **同一 conN 两个 LSF 作业**。已用测试固定现状：`test_bsub_success_but_response_lost` |
| P0-2 | **提交闸门只看本地库**，不看 LSF；巡检在无正常结束标志时判 `zombied` | `routers/jobs.py:474`；`batch_check.py:1034-1041` | `job_id` 丢失或被误判结束的任务会被规则命中（`status: zombied` → 续算 + follow_up submit），再次 bsub |
| P0-3 | **幂等实际未启用**：`_fingerprint()` 全仓无调用，只认客户端显式 `idempotency_key`；规则链路不传；key 不绑定 `task/action` | `automation/scheduler.py:42-48,270-280`；`automation/events.py:69-80` | 自动路径无去重，同事件重复投递即重复执行 |
| P0-4 | **检查与执行之间存在 TOCTOU**：冷却/上限在 `submit()` 入口判断，worker 执行前只复检 preflight，不再看冷却/上限 | `automation/scheduler.py:241-268,437-456` | 两个 worker / 两次并发请求可同时通过 → 重复执行 |
| P0-5 | **失败不计数**：`counts` 只在 `success` 时 +1；`cooldowns` 也只在 success 写 | `automation/scheduler.py:384-408` | `max_runs_per_task` 挡不住失败重试；续算失败（远端 conN 已建）会连续建 conN+1。测试：`test_failure_does_not_count_towards_max_runs` |
| P0-6 | **待确认动作批准绕过调度层**：不加任务锁、不看冷却/上限、不写动作审计，且"先执行、后改状态" | `pending_actions.py:158-177`；`routers/pending_actions.py:128-154` | 并发/重放批准各自 `core_submit` → 第二个 LSF 作业；且批准时**不复核项目归属**（任意普通用户可批准他人项目动作） |
| P0-7 | **follow_up 指向父任务**：续算成功的后续 submit 用父 `task_id`，而新建的是 `conN` 隐藏子任务（`pending`） | `automation/scheduler.py:523-535`；`routers/jobs.py:368-398,492-496` | 父/子锁键不同、却操作同一 `conN` → 与子任务手动提交并发时双 bsub |
| P0-8 | **无资源台账**：提交只落 `status=queued` + `job_id`，不记录核数 / walltime / 核时；报告里的 `core_hours` 是「1 当量 = 24 核 × 3 天 = 1728 核时」的估算常量 | `routers/jobs.py:571-578`；`report_builder.py:159-161,240,252` | 阶段 1 的"最大核时 / 最大 walltime / 最大核数"没有可信数据源，预算只能靠解析 `vasp.lsf` 重建 |
| P0-9 | **Agent 的 `write` scope 直连业务端点**：`POST /api/jobs/tasks/{id}/submit`、`/continuation`、`/create-frac` 只受归属校验约束 | `middleware/auth.py:49-60`；`routers/jobs.py:1232-1240,933-943` | Agent 可绕开 pending-actions、动作白名单与预算，与总则「LLM 不得直接获得任意执行权限」冲突 |
| P0-10 | **`GET /api/ssh/config` 回显明文 `password` 且无 admin 校验**（`read` token 即可读） | `routers/ssh.py:120-146`（对照 `PUT` 有 `ensure_admin`，`:156-161`） | 集群凭据泄露；与本阶段主线无关，但属最高危项，建议阶段 1 顺手修 |

### P1（阻塞阶段 1 或直接影响可验证性）

| # | 风险 | 证据 |
|---|---|---|
| P1-1 | 全局 `dry_run` 可被请求体覆盖：`settings.dry_run if dry_run is None else bool(dry_run)` | `automation/scheduler.py:282` |
| P1-2 | `_tick_schedules` 锁外读 history、最后整文件 `save_history`，覆盖并发写入的 cooldown/count/指纹 | `automation/scheduler.py:556,653-654` |
| P1-3 | 队列只在内存；短动作无 run 记录（只有 `long_running` 落 `action_runs.json`），`wait` 超时后返回 `running` 但无法轮询 | `automation/scheduler.py:32,326-340,358`；`routers/automation.py:199-207` |
| P1-4 | 重启只把 `running` 标 `failed("服务重启导致中断")`，不清指纹、不对账、不区分 interrupted/unknown | `automation/service.py:12-23` |
| P1-5 | 续算先建远端 conN 再校验/写库，失败无回滚，重试继续 conN+1 | `continuation.py:219-227`；`routers/jobs.py:362-366` |
| P1-6 | `continuation` / `frac.create` 的 preflight 是形式检查（只看库，不碰远端） | `automation/actions.py:60-75,96-105` |
| P1-7 | 审计写失败静默放行（`except OSError: pass`），动作照跑；`blocked` 的 `audit_id` 用秒级时间戳，不唯一 | `automation/audit.py:64-70`；`automation/scheduler.py:185` |
| P1-8 | 动作端点 `guard` 由请求体给，缺省为空 → 等价无冷却无上限（仅 admin 可用） | `routers/automation.py:179-189` |
| P1-9 | `scope: []` 被归一成 `None`（全权）；agent 走密码登录拿到的会话没有 scope | `routers/auth.py:132-134,265-269`；`permissions.py:138-142` |

### P2（记录，不纳入本期）

Windows 上 `fcntl` 缺失导致跨进程锁静默退化；审计 JSONL 无锁无 fsync；`runs` 只保留 200 条且缺 `rule_id`；`_manual_takeover` 只扫审计尾部 400 行；`after` 模式 naive/aware 混用；`ssh.upload_file/download_file` 的 `timeout` 形参未使用；`_NebCreate` 未注册。

---

## 3. 下一阶段（阶段 1）最小改动方案

原则：**不新建第二套任务状态/权限/审计体系，全部挂在现有 `ActionSpec` + 任务锁 + 审计上**。

1. **受控执行网关** `automation/gateway.py`
   `run(action, task_id, params, actor, budget_id)` → 身份/项目归属 → 白名单 → 预算 → preflight → 任务锁 → 执行 → 台账 → 审计。
   复用 `scheduler._acquire_task_lock`、`actions.get()`、`audit.write()`；不复用内存 Queue 作为事实来源。
2. **预算账本** `automation/budget.py`
   每工作流：最大活跃作业、最大自动提交次数、失败重试次数、最大核时、最大 walltime、最大核数。
   核时/核数从 `vasp.lsf` 的 `#BSUB -n` / `#BSUB -W` 解析（解析失败 → 拒绝自动提交），预留量在提交前落账、作业退出后按实际更新；JSON + `flock`，读改写全在锁内。
3. **动作台账** `automation/ledger.py`
   先写记录（`action_id/task_id/actor/action/idempotency_key/status/requested_resources/budget_reservation/job_id/timestamps/result`）再执行；状态机 `pending → running → succeeded|failed|unknown`；服务启动时把 `running` 标 `interrupted` 并进入对账，不重放。
4. **UNKNOWN 对账** `automation/unknown.py`
   bsub 后拿不到 job_id / SSH 超时 / 落库失败 → 记 `unknown` + 唯一执行标识（写进远端提交脚本的环境变量或标记文件）→ 只查 `bjobs` 与 `conN` 目录 → 能绑定就绑定，不能确认则 `paused` 等人工。**任何情况下不立即再 bsub。**
5. **旁路收口**（最小改动）
   - `pending_actions.approve` 改走网关（获得锁/预算/审计），批准前复核项目归属；
   - agent 的 `write` scope 不再直连 `/api/jobs/tasks/{id}/submit|continuation|create-frac`（或在这三个端点内加"必须带预算单"校验）；
   - `effective_dry` 改为 `settings.dry_run or bool(dry_run)`；
   - `get_config` 加 `ensure_admin` 且不再回显 `password`。

明确不做：通用 DAG、多 Agent、科学知识库、真实计费、向量库、微服务拆分。

**验收映射（阶段 1 A–G）**：A 重复请求 → 网关幂等 + 台账；B 重启 → 台账 `interrupted` + 对账；C 预算 → 账本；D 无授权 → 网关白名单/归属；E 状态不确定 → `unknown` 流程；F 可追溯 → 台账 `action_id` + 审计 `trigger/rule_id`；G 回归 → 现有 52 例 + 新增用例。

---

## 4. 预计新增 / 修改文件

新增：
- `backend/automation/gateway.py`（执行网关）
- `backend/automation/budget.py`（预算与核时估算）
- `backend/automation/ledger.py`（动作台账，JSON + flock）
- `backend/automation/unknown.py`（不确定状态对账）
- `tests/test_agent_gateway.py`、`tests/test_budget_ledger.py`、`tests/test_unknown_reconcile.py`
- `agent-upgrade/01-gateway.md`（阶段 1 交付说明）

修改（尽量小）：
- `backend/automation/scheduler.py`：执行前锁内复查冷却/上限；`effective_dry` 修正；`_tick_schedules` 改 `update_history`
- `backend/automation/service.py`：启动对账钩子
- `backend/pending_actions.py`、`backend/routers/pending_actions.py`：approve 走网关
- `backend/middleware/auth.py` 或 `routers/jobs.py`：agent 写动作收口
- `backend/routers/ssh.py`：配置读取加 admin、去 password

新增文件合计约 4 个模块 + 3 个测试文件，均为"薄封装"，不改现有数据结构。

---

## 5. 测试基线与阻塞事项

### 5.1 现有基线（已完成，可复现）

```bash
cd /home/zouyuxi/projects/vasp-manager
.venv/bin/python -m unittest discover -s tests        # Ran 52 tests, OK, 3.1s
```

- 全部 stdlib `unittest`，无 pytest / 无 conftest；测试不连真实集群（逐用例 patch 或 `VASP_SSH_MOCK`）。

### 5.2 本次新增的最小测试工具（已落地，全绿）

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_automation_baseline.py' -v   # Ran 10 tests, OK
```

| 文件 | 作用 |
|---|---|
| `tests/mock_hpc.py` | 隔离"假集群"：`VASP_SSH_MOCK=1` + `<mock根>/_mock_bin/bsub` 打桩（ok/reject/error/hang）+ 调用日志 + 远端输入文件生成 |
| `tests/test_automation_baseline.py` | 10 例：dry_run 无副作用、正常提交、重复提交 409、bsub 被拒、**bsub 成功但响应丢失（P0-1 证据）**、幂等键去重、**失败不计数（P0-5 证据）**、任务锁、重启标 failed、OUTCAR 收敛/未收敛夹具 |
| `tests/fixtures/vasp/OUTCAR_opt_{converged,unconverged}` | 正常结束 / NSW 上限未收敛的输出夹具 |

> 注意：该用例集靠 `VASP_WEB_DATA_DIR` 决定数据目录，必须在**独立进程**运行；放在全量 discover 中时会自动 `skip`（本轮验证：`OK (skipped=1)`），不会污染其它用例。

### 5.3 阶段 1 前还需要补的测试工具（不阻塞，但要在写代码前建好）

1. **Fake bjobs**：脚本化返回 `PEND/RUN/DONE/EXIT/UNKNOWN`（续算与对账都依赖它）；
2. **整应用 harness**：`main.app` 带 `lifespan` 的临时实例（现有测试都是自己拼 app）；
3. **重启两阶段夹具**：同一临时数据目录跑"执行 → 丢响应 → 重启 → 对账"；
4. **并发驱动**：多线程同时 `scheduler.submit()`，断言 bsub 实际次数。

### 5.4 阻塞事项 / 需要确认的点

1. **生产自动化当前是开着的**：`data/config/automation.json` → `enabled=true, dry_run=false`；4 条规则（1 条 enabled：`26653 FS自动续算`，`follow_up_action=task.submit`）；`data/action_history.json` 显示最近一次成功动作在 2026-10-19 15:47，审计 8.8MB / 20491 行。**阶段 1 的任何改动都不得改变现有规则行为**，新能力必须默认关闭且可单独开关。
2. 阶段 1 是否允许顺手修 P0-10（凭据回显）与 P1-9（scope 归一）——两项都不影响现有用户流程，但属于安全面，建议允许。
3. 预算的"核时估算"只用于**上限拦截**，不是计费；需要确认同一 HPC 内不同队列（`normal_2week` / `charge` 等）是否允许简单累加，还是必须按队列分别计账。

### 5.5 验收自检（阶段 0）

- [x] 每个发现都有源码位置或测试证据
- [x] 明确指出已有能力，不重复建设（§1 共 15 项）
- [x] 有可运行的安全测试基线（52 + 10 例，离线、临时目录）
- [x] 可以据此立即开始最小安全执行升级（§3 五件套）
