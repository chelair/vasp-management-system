# Agent 开发进度（持续维护）

> 用途：记录「VASP 自主科研智能体」升级的实际进度、验收证据与待办。
> 规则：**每个阶段开始时更新状态，结束时补验收证据**；只写已实际执行/已核实的内容，不写计划外结论。
> 详细审计见 [`00-baseline.md`](./00-baseline.md)。代码与文档冲突时以源码与测试为准。

- 项目：`/home/zouyuxi/projects/vasp-manager`（ZYX-S）
- 基线版本：v1.0.1 / `099dfcb`
- 最近更新：2026-10-19

---

## 1. 阶段总表

| 阶段 | 内容 | 状态 | 验收证据 |
|---|---|---|---|
| 0 | 升级前最小工程审计 | ✅ 完成（2026-10-19） | [`00-baseline.md`](./00-baseline.md)；52 + 10 例离线测试全绿 |
| 1 | 最小安全自主执行底座 | ✅ Mock验收完成，已部署（2026-10-19，默认关闭） | [`01-gateway.md`](./01-gateway.md)；38项新测试+10项基线+52项既有回归 |
| 2 | 单 OPT 任务自主闭环 | ✅ Mock验收完成，已部署（2026-10-19，默认关闭） | 47项专项+52既有+10基线+38网关回归通过；见02-opt-loop.md |
| 3 | 最小多任务工作流（OPT→STATIC→DOS） | ⬜ 未开始 | 依赖阶段 2 通过 |
| 4 | 科研分析、科学验证与报告闭环 | ⬜ 未开始 | 依赖阶段 3 通过 |

状态图例：✅ 完成 / 🟡 进行中 / ⬜ 未开始 / ⛔ 阻塞

---

## 2. 阶段 0 · 已交付

### 2.1 产出

| 产出 | 位置 | 说明 |
|---|---|---|
| 基线审计报告 | `agent-upgrade/00-baseline.md` | 15 项可复用能力；10 条 P0、9 条 P1、6 条 P2；阶段 1 最小改动方案 |
| Mock 集群夹具 | `tests/mock_hpc.py` | `VASP_SSH_MOCK` + `_mock_bin/bsub` 打桩（ok/reject/error/hang）+ 调用计数 + 远端输入文件生成 |
| 离线回归用例 | `tests/test_automation_baseline.py` | 10 例，覆盖 dry_run / 提交 / 重复 / 拒绝 / 响应丢失 / 幂等键 / 失败计数 / 任务锁 / 重启 / OUTCAR |
| VASP 输出夹具 | `tests/fixtures/vasp/OUTCAR_opt_*` | 正常结束 / NSW 上限未收敛 |

### 2.2 执行记录（真实结果）

```
$ .venv/bin/python -m unittest discover -s tests
Ran 52 tests in 3.131s
OK (skipped=1)          # skipped = 新增用例在共享进程中被自动跳过（需独立进程）

$ .venv/bin/python -m unittest discover -s tests -p 'test_automation_baseline.py' -v
Ran 10 tests in 0.411s
OK
```

### 2.3 阶段 0 结论（一句话）

能力已具备（动作目录 / 任务锁 / 预检 / 五态审计 / agent 身份 / Mock SSH），
真正的缺口是**预算、动作台账、UNKNOWN 对账、旁路收口**；
不修 P0 就不能给 Agent 任何自动执行权。

---

## 3. 当前生产态快照（只读核实，2026-10-19 19:45）

| 项 | 值 |
|---|---|
| systemd | `vasp-manager.service` active，`Type=simple`，`User=zouyuxi`，`Restart=always` |
| 端口 | `127.0.0.1:3001` 返回 200；局域网 `192.168.1.20:3001` |
| 自动化开关 | `enabled=true`，`dry_run=false`，`schedules_enabled=false` |
| 规则 | 4 个文件，启用 1 条（`26653 FS自动续算`，`follow_up_action=task.submit`） |
| 最近动作 | 2026-10-19 15:47 有 `task.submit` 成功记录 |
| 审计体量 | `data/audit/actions.jsonl` 8.8MB / 20491 行 |
| 测试 | `.venv` Python 3.14.4；无 pytest；全量 3.1s |

> 含义：**改动必须在"线上正在跑自动化"的前提下保持兼容**；新能力默认关闭、与现有规则隔离。

---

## 4. 阶段 1 实施顺序（已完成，细节见01-gateway.md）

| # | 任务 | 落地位置 | 验收 |
|---|---|---|---|
| 1 | Fake bjobs 夹具 + 整应用 harness + 并发驱动 | `tests/mock_hpc.py` 扩展、`tests/test_agent_gateway.py` | 能脚本化 PEND/RUN/DONE/EXIT/UNKNOWN |
| 2 | 动作台账（先写后执行、状态机、重启对账） | `backend/automation/ledger.py` | 重启后 `running → interrupted`，不重放 |
| 3 | 预算账本（核数/walltime/核时，解析 `vasp.lsf`） | `backend/automation/budget.py` | 超额拒绝；解析失败拒绝自动提交 |
| 4 | 受控执行网关（身份→归属→白名单→预算→preflight→锁→执行→台账→审计） | `backend/automation/gateway.py` | 阶段 1 验收 A–G |
| 5 | UNKNOWN 对账（bsub 无 job_id / SSH 超时 / 落库失败） | `backend/automation/unknown.py` | 不立即重提，能绑定或暂停 |
| 6 | 旁路收口（approve 走网关、agent 写端点限流、`effective_dry`、ssh 配置收敛） | `pending_actions.py`、`routers/*`、`scheduler.py` | 现有 52 例 + 新用例全绿 |

阶段 1 验收（来自 `AGENTS.md`）：

- [x] A 重复请求不产生重复真实动作
- [x] B 服务重启不盲目重复提交
- [x] C 预算不足无法自动执行
- [x] D 无授权不能执行
- [x] E 不确定远端状态安全暂停
- [x] F 所有自动动作可追溯到触发原因
- [x] G 原有人工管理功能回归通过

---

## 5. 决策与约定（本系列）

1. 只扩展 `backend/automation/`、`backend/ssh.py`、`routers/jobs.py` 的既有接缝，不新建第二套任务状态/权限/审计。
2. 持久化用 JSON + `flock` 原子写（与现有 `storage.py`/`automation/store.py` 一致），不引入数据库。
3. 预算只做**上限拦截**，不是计费；核时 = 申请核数 × walltime 的最坏情况预留。
4. 不确定状态（UNKNOWN）**绝不**当 FAILED，也绝不立即重放副作用。
5. 新自主能力默认关闭；第一次使用必须显式授权任务与预算。
6. 不改动 POSCAR 建模/编辑；只读解析结构。
7. 所有新增有副作用的操作必须能在 Mock 环境完整演练（`VASP_SSH_MOCK=1`）。

---

## 6. 阶段0风险登记（阶段1 Mock处置状态）

| 编号 | 风险 | 状态 |
|---|---|---|
| P0-1 | bsub 成功但结果不确定 → 重复提交 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-2 | 提交闸门只看本地库，不查 LSF | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-3 | 幂等实际未启用 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-4 | 冷却/上限 TOCTOU | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-5 | 失败不计数 → 无限重试 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-6 | approve 绕过锁/调度/归属 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-7 | follow_up 用父 task_id → 父子双提交 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-8 | 无资源台账 → 预算无依据 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-9 | agent `write` 直连业务端点 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |
| P0-10 | `GET /api/ssh/config` 回显明文口令 | ✅ 阶段1已处理，Mock验证；边界见01-gateway.md |

---

## 7. 变更日志

| 日期 | 阶段 | 内容 |
|---|---|---|
| 2026-10-19 | 0 | 完成基线审计；新增 `tests/mock_hpc.py`、`tests/test_automation_baseline.py`、2 个 OUTCAR 夹具；52 + 10 例全绿；产出 `00-baseline.md` |

- 2026-10-19：启动阶段1。先补Mock对账/并发夹具，再实现动作台账、预算和受控入口；不部署生产、不改真实项目数据。

## 8. 阶段1验收（2026-10-19）

- 复用既有执行接缝、任务族锁、SSH、审批和审计；新增gateway/budget/ledger/unknown和受控API。授权、预留和动作在同一JSON事务中提交，默认关闭。
- 100项Python测试通过（52既有+10基线+38新用例），其中新两套必须独立进程；Node口令兼容回归、TypeScript和隔离目录Vite构建通过。未调用真实HPC或模型。
- 覆盖重复10次、线程/进程竞争、bsub丢响应/强制崩溃、写库失败、真实Mock续算接力、共享预算竞争、审批篡改及越权、暂停和人工解除。
- 原基线的两个缺陷断言已改成修复后的回归（丢响应可对账、失败计入上限）；重启运行记录改为interrupted。
- 尚未部署、提交或推送；生产配置/真实数据/服务未变；阶段2未开始。当前阶段等待用户验收。
- 后续先验证真实LSF输出及脚本兼容；核时暂按申请上界保守结算，不是实际计费。完整交付/回滚说明见01-gateway.md。

- 2026-10-19 21:48：经用户明确要求部署阶段1。真实LSF只读格式核验通过；前后端上线、健康/鉴权/静态资源正常，新入口关闭且零授权，临时验证凭证已撤销。备份：/home/zouyuxi/projects/vasp-manager/data/backups/stage1-deploy/20261019-214719。未执行真实作业动作、未进入阶段2、未提交推送。

- 2026-10-19：启动阶段2。先核对巡检证据与模型调用接缝，建立可恢复的单OPT有限执行循环；不部署或启用生产自主执行。

## 9. 阶段2验收（2026-10-19）

- 2026-10-19：参数证据链补齐并通过Mock验收：实际上传/续算/提交记录按任务族保留5条（草稿不计）、目录间参数明细差异、固定4小时且按自动巡检参与范围判断的时效、独立按需远端只读补证。53项常规+26项新增专项+10项基线+38项网关+47项OPT通过，共174项Python测试；实际参数历史浏览器验证、TypeScript和隔离构建通过。未部署；未调整原巡检频率或结构回传，阶段3未开始。详见03-parameter-evidence.md（阶段2补充，不是阶段3）。

- 单OPT观察/诊断/结构化提案/策略检查/执行/验证/暂停与总结已接通。状态写入原执行台账opt_runs；事件来自原巡检完成通知，没有新增轮询器或第二套聊天系统。
- 明确walltime可续算，NSW须显式配置增量/绝对上限及力改善条件；SCF问题仅诊断建议人工处理，尚无充分验证的自动参数策略。
- 最新conN、作业身份、文件时间/摘要、OUTCAR/OSZICAR步数和能量、POTCAR元素/结构与实际续算输入交叉验证；程序结束、电子/离子收敛、科学数值精度分别记录。
- 47项新增离线测试通过；覆盖完整Mock提交→续算→收敛、DeepSeek流式JSON提案、危险参数/日志注入、未知LSF、旧镜像、输入变更、预算、无改善、人工暂停、重启恢复及绕过循环策略的拦截；排队受理与实际启动分开验证。
- 52项既有、10项基线、38项阶段1回归通过，总计147项Python测试；Node口令回归、TypeScript和隔离目录Vite构建通过（保留既有大包提示）。
- 真实HPC提交/续算、真实模型请求、真实LSF walltime详情格式及完整科学精度：NOT_TESTED。Mock通过不等于生产自主运行或物理结果可靠。
- 本轮未部署、未启用生产授权、未提交推送；阶段3未开始。使用与边界见02-opt-loop.md。

- 2026-10-19 23:12：经用户要求，开始部署阶段2及参数证据链；先备份数据和静态资源，再重启单实例服务，自主开关保持关闭。

## 10. 阶段2及参数证据链部署（2026-10-19 23:13）

- 经用户明确要求，发布已通过174项Python回归、浏览器、TypeScript及隔离构建的前后端；systemd单实例重启，PID2356811，startedAt=2026-10-19T23:13:00。
- 健康检查、/jobs及首页6个静态资源和3Dmol通过；原报告导出运行时原样保留（由后端内联，不是公开/report静态路由）。旧哈希资源保留，避免已打开页面加载失败。
- 未登录新API/SSH配置均401；临时只读凭证验证阶段2路由、实际input.applied_history、项目工作区只读补证规则及environment标记均通过，验证凭证已撤销。自主enabled=false、零授权/动作/OPT循环；既有自动化与服务器配置不变。
- 私有备份：/home/zouyuxi/projects/vasp-manager/data/backups/parameter-evidence-deploy/20261019-231247（目录0700/文件0600）；含旧dist、运行元数据/配置/审计、SQLite一致性备份、候选源码与Git HEAD归档。候选源码不是旧进程的阶段1内存代码；Git HEAD也早于阶段1，不将其冒称上一线上版本的精确源码快照。回滚数据前须核对部署后新操作，不盲目覆盖运行数据或重放UNKNOWN。
- 实际参数历史从部署后成功操作开始累积；不补造旧记录。没有触发真实模型、远端补证或HPC提交/续算；完整生产自主闭环和此前约束兼容边界仍未验证，阶段3未开始。未提交或推送Git。

- 2026-10-19：经用户要求开始v1.1.0发布，汇总已部署的结构展示同步、阶段1/2与参数证据链；检查版本、源码及私密文件边界后推送main，沿用无tag惯例。不纳入用户原有两份文档删除。

## 11. v1.1.0版本发布

- 2026-10-19：按用户要求发布1.1（package/lockfile/侧边栏/API元数据统一为1.1.0），包含已部署的结构展示同步、阶段1/2及参数证据链；沿用main，不创建tag。
- 发布验证：npm run typecheck、隔离Vite生产构建、隔离esbuild报告运行时构建、Node SSH口令兼容回归及git diff --cached --check通过。此前174项Python回归和两项浏览器验证结果保持有效，本轮仅修改版本元数据与发布文档，未重跑这些套件。
- 63个待提交文件均为源码/离线夹具/测试/文档；运行数据、私密配置、密钥、SQLite、dist和备份未暂存，秘密模式扫描无命中。原有待办.md和问题.md删除保持未暂存。
- 本轮不部署或重启服务，生产自主开关不变；发布版本标识下次部署生效。提交及远端同步结果以Git日志和origin/main为准。
