# Agent 开发进度（持续维护）

当前修复（2026-10-20）：用户反馈InCI6旧作业751321的LSF历史已不可查，人工提交被阻止，前端无历史作业核实入口。本轮核实远端只读证据，修复无旧执行台账时的受控人工确认及提交报错弹窗一键处理（用户明确要求不放常驻入口），保留活跃作业/身份/权限闸门，不提交或续算HPC；同时说明模型对计算内容/预期的建议能力与执行边界。完成结果追加§18。

当前部署状态（2026-10-20）：用户授权后R2已于11:04部署，基线b0f9455，私有备份/单writer切换/线上只读核验均完成；发布提交及origin/main核对见Git。配置未变，未启用AI/自主执行，不调用真实模型/HPC。详见§17。

> 用途：记录「VASP 自主科研智能体」升级的实际进度、验收证据与待办。
> 规则：**每个阶段开始时更新状态，结束时补验收证据**；只写已实际执行/已核实的内容，不写计划外结论。
> 详细审计见 [`00-baseline.md`](./00-baseline.md)。代码与文档冲突时以源码与测试为准。

- 项目：`/home/zouyuxi/projects/vasp-manager`（ZYX-S）
- 基线版本：v1.0.1 / `099dfcb`
- 最近更新：2026-10-20

当前状态（2026-10-20）：用户“你继续开发吧”后，R2合同修复+C手工编辑/冻结预览导出+D首批14类元素适配已验收，后续授权部署完成，详见§16/17及实现记录§14/15。历史§14/15待办已由本轮最新节替代。

---

## 1. 阶段总表

- 2026-10-19 用户授权部署并推送 R1（维持应用 v1.1.0），本轮先备份/部署/验证，再发布 Git；R2 仅启动源码审查与可接续交接，不实现元素编排，不启用 AI 自动编排或阶段3/4。

- R1（现有完整项目报告 AI 注解）：✅ Mock验收完成并于2026-10-19 23:56部署；默认关闭，20项专项与174项既有回归通过，详见 §12/13 和 `R1-report-notes.md`。
- R2（细粒度ReportBlock/Evidence）：✅ A/B合同与C/D手工专题报告已实现、验收并于2026-10-20 11:04部署；业务b0f9455，发布main提交看Git。40项R2专项与原系统回归通过，线上只读核验见§17；不启动AI自动编排或自主阶段3/4。

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

## 12. R1 · 完整项目报告 AI 分析与写作（2026-10-19）

- 项目编辑增加默认关闭开关；复用当前用户自己的工作台连接。普通报告独立生成完成，选择连接后单条/重生/缺失批量生成待审草稿。当前会话新生成报告可自动生成缺失草稿，已有任意文本整条跳过；定时后台报告无用户连接时不调用模型。
- 原两类注解和存储/导出继续复用，预览→采用→人工编辑→明确保存；支持放弃与一次恢复。来源/模型/时间/输入指纹最小记录，前端不能伪造 AI 来源；原注解修订与最新报告依据双检阻止旧草稿覆盖人工或新数据。
- 四种描述输入规则、真实结果优先、Results/Discussion 分段校验、快照参数/来源/验证状态；报告 schema 1.2.0，布局与旧字段兼容。保存的 AI 来源文本按实际数据/描述变化提示过期，报告仅换生成时间不触发。
- AI 只读固定科研报告证据、不带工作台工具。连接/超时/JSON/空值/截断/工具返回、部分失败、取消均隔离；真实 HTTP 验证断开后中断上游并释放并发位，等待模型时普通报告仍可读取。修复 BaseHTTPMiddleware 下即时断开检测漏报，以及同 ID 重生成时旧 Provider 提前启动自动草稿的竞态。
- XSS：复用安全 Markdown，注解/草稿禁自动外部图片，修补原导出链接转义与协议检查；没有新增模型对 SSH/作业/INCAR/POSCAR/科学结果的写能力。
- Python：全量常规53项（5个需隔离的套件容器单独运行），基线10、网关38、OPT47、参数证据26、R1新增20项，合计 **194项通过**。命令均为 `.venv/bin/python -m unittest discover -s tests [-p '<对应文件>'] -q`；全部隔离数据/Mock 模型/HPC，未调用真实服务。
- 浏览器：`PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/report-ai-notes.cjs` 通过；覆盖预览/编辑/恢复/放弃、部分失败、人工优先、取消、关闭/未配置、自动草稿、XSS、完整 Report 页面同ID重生成/项目切换/注解挂载，并将隔离 HTML 实际打印成 PDF。
- `npm run typecheck`、`npx vite build --outDir /tmp/vasp-r1-report-build`、`node tests/test_ssh_frontend.cjs`、`git diff --check` 通过；构建只保留原有大包提示，未替换生产 dist。
- 未部署/重启、未修改真实项目开关/配置/密钥/计算结果，未提交或推送；用户原有两份文档删除保持原状。未进入下一阶段。真实模型文风/科学忠实度仍需人工试用；结构校验不能证明科学事实，旧报告缺参数不会补造，多实例并发不在本阶段。详细交付和使用见 `R1-report-notes.md`。

## 13. R1部署发布与R2起步交接（2026-10-19至20）

- 用户授权部署/推送1.1并为其他agents准备R2交接；应用版本保持1.1.0，不改写历史提交、不补打/移动tag。R1新增功能部署，R2仅文档审查/设计，不含业务代码或迁移。
- 2026-10-19 23:56:56（Asia/Shanghai）单实例部署完成：旧PID2356811→新PID2409520，systemd自动重启；发布入口 `index-DsgMllLr.js`，旧hash资源保留。报告runtime隔离构建并发布，578923字节；3Dmol/静态打印资源保留。无活动AI回答时切换，未启用任何项目AI开关或自主授权。
- 私有备份 `data/backups/r1-report-deploy/20261019-235623`（0700/0600）：旧dist、config/users、notes/edits/索引、根JSON、SQLite一致性副本、R1前Git归档与候选源码/哈希清单。无主密钥副本，禁止上传；回滚须核对部署后新数据，不能盲目恢复或重放UNKNOWN。
- 部署前重跑R1 20项专项通过，隔离Vite和esbuild报告runtime构建通过；沿用本轮此前194项回归/浏览器/typecheck验证记录，未把旧记录冒称本次再次全量重跑。
- 上线检查：健康200、/reports及6个静态资源200、旧hash存在；未登录R1新接口/SSH配置401；临时只读会话验证API版本1.1.0、报告schema1.2.0、新路由、7份现有报告AI状态正常，项目AI开启数0、自主enabled=false，4份服务器/自动化等配置哈希不变；报告runtime可读取。临时验证会话已撤销。未调真实模型/生成或改写生产报告/执行HPC。
- R2审查关键发现：OPT上限6在详情/资源构建前截断，不只是Markdown；完整报告存储会清理同项目其他report_id；AI view不是完整Evidence且存在未知归并；当前PDOS预览/导出可能取当前任务数据，组合必须固定来源版本；旧隐藏依赖标题/图序号，需稳定block_id兼容映射。
- 新增 `R2-report-blocks.md`：完整任务合同、14类元素、源码/运行时地图、Evidence与Block建议合同、A/B/C/D实施顺序、人工验收、隔离测试/生产边界、双向交回模板。AGENTS.md开头明确当前任务，agent.md仅提供入口，process等同步更新。**下一条任务是R2-A合同/全候选目录及隔离测试；目前R2零业务代码/接口/迁移/测试。**
- 发布内容仅源码、Mock测试和交接文档；两份用户文档删除不提交，data/配置/密钥/dist/备份不进Git。提交和推送成功与否以最终Git日志和origin/main为准，后续接手先核对该状态；未来R2未验收不自动部署。

## 14. R2-A/R2-B · 报告元素系统后端闭环（2026-10-20）

- 接手：从其他 agents 临时接手 R2。基线 `435140f`（v1.1.0，R1 已部署、R2 仅设计文档）。先读 `AGENTS.md` 当前任务 → `R2-report-blocks.md` → `R1-report-notes.md` → git 状态，未要求用户复述需求。
- **R2-A 完成**：新增 `backend/report_blocks.py`。14 类元素注册表（renderer/证据种类/scope/是否已接入）；稳定 ID = `sha256(项目|类型|任务/组|variant)` 截断，文本块 UUID；候选目录覆盖**全部授权任务**（不受完整报告 6 条上限影响），辅助任务（conN/差分分块）不单独成元素；`availability / validation / freshness / full_report_visibility` 四类状态分开记，UNKNOWN 不冒充 PASS；有 OUTCAR 无归档判 `unparsed`、真无数据才 `missing`。
- **R2-B 完成**：新增 `backend/report_compositions.py` + `backend/routers/report_compositions.py`。两模型最小闭环（两条能量 + 参数对照 + 一条曲线 + 用户文字）；Evidence 去重冻结、Block 只存 `source_refs`；保存时后端重算 ID（伪造 400）、版本不一致返回 409 `evidence_stale`（显式 `refresh_evidence` 才接受）；组合 CRUD + 乐观锁 + 软删除/恢复 + 自包含 HTML 导出（内联 SVG/表格、转义脚本、剥离外链图片）。
- 存储：`data/reports/compositions/<项目>/cmp_<12hex>.json`，与完整报告索引/单份清理隔离；旧 `report.json/md/notes/edits/HTML` 与报告 schema 1.2.0 未改。
- 新增测试 26 项：`tests/r2_fixtures.py`、`tests/test_report_blocks.py`（13）、`tests/test_report_compositions.py`（13）。实测：两套各 `OK`；既有回归 53 常规（7 skip 为隔离容器）+ 10/38/47/26/20 逐套件全 `OK`，**合计 220 项通过**（194 既有 + 26 新增）。
- 未做：R2-C 前端编辑器/页面预览/浏览器与 PDF 回归；R2-D 剩余6种Block类型（NEB/自由能/PDOS/Bader/功函数/差分）解析渲染及结构3D、旧隐藏 key 映射。R2-A 对这6类只给候选并标 `resolvable=false`，解析请求明确拒绝而不是伪造。
- **未部署、未推送、未重启服务**：生产 `vasp-manager.service`、`dist/`、`data/` 均未变动；前端无改动。用户原有 `待办.md`、`问题.md` 删除保持未暂存。
- 交接文档：`agent-upgrade/R2-blocks-implementation.md`（摘要 + 详细改动 + 坑 + 下一步）；`R2-report-blocks.md` 状态与 §7 已回填；`AGENTS.md` 当前任务/进度、`API.md` R2 章节已更新。代码提交 `dd807cf`（本地 main，未推送）。下一条任务：**R2-C 前端组合编辑器 + 同一冻结证据预览**。

## 15. 本助手接回R2（2026-10-20）

- 接手HEAD `8601bab`，代码 `dd807cf`，A/B后端初版已在本地；C前端与D剩余6种Block/结构3D等未实现。线上仍为R1，PID2409520未变。没有在本轮开始新功能、改业务代码、推送或部署。
- 实际重跑 `test_report_blocks.py` 13项、`test_report_compositions.py` 13项，均OK；此前220项为上一位的执行记录，本轮不冒称重跑全部。
- 临时DATA_DIR探针：14种注册、8种可解析（含文本）、6种未接入；单独未接入/evidence请求实测500（组合保存为400）；只改checked_at会使task.summary版本变化。未操作生产科研数据/配置。
- 源码核对另确认：选定两模型参数对照尚未实现、groups未用于导出呈现、expected_revision/旧source_refs仍可缺省、来源仅payload指纹未到原文件证据、24h时效/展示上限口径与原系统未完全统一、整份组合删除无恢复入口。详情与下一步在 `R2-blocks-implementation.md` §13，均只记录未修复。
- README/process/PROGRESS旧“R2无业务实现”摘要与API类型计数/保证已修正；AGENTS指向当前真实状态。下一步先收敛关键后端合同，再推进R2-C，不重复实现A/B，不进入自主阶段3/4或AI自动编排。
- 本轮交接文档未提交；原 `待办.md`、`问题.md` 删除保留。后续核对git状态，不将文档更新混成已部署功能。


## 16. R2续开发：本地手工闭环验收（2026-10-20）

- 从8601bab接续，收敛A/B版本、修订、参数对照、来源/时效、正文上限和400/409合同；实现报告页「专题报告」Drawer、14类元素Adapter、排序/分组/标题/隐藏/删除恢复、同一冻结证据预览/HTML/PDF。实现合同/文件与完整限制见 `R2-blocks-implementation.md` §14，API.md已更新。
- 真正执行：普通Python discover Ran53 OK（8个需要独立数据的套件占位Skip），再独立执行baseline10、gateway38、OPT47、参数26、R1 20、R2 14+18+8，全部OK；报告呈现6另跑OK但不重复计数。R1与R2两套Playwright均PASS，包括实际HTML/PDF、真实本地API认证及并发/冻结/显式刷新。typecheck、/tmp最终Vite构建、diff检查通过。
- 未改生产数据、服务或dist。只读systemctl确认active/PID2409520/启动2026-10-19 23:56:56 CST；不部署、不推送、不接AI自动编排/自主下一阶段。Git提交见本轮R2 commit，基线dd807cf/8601bab；原用户两份文档删除保留未提交。
- 遗留边界：真实项目上线验收待用户部署授权；旧图序号/同名歧义需手工核对；PDF不自动生成缺失结构PNG；未解析原始电子文件不触发科学计算；多进程写/复杂布局/AI编排不在本阶段。整份组合软删除无恢复UI/API（元素可恢复）。
- 接手下一步：先读AGENTS与实现§14，不重做历史缺口；部署若获授权需备份、构建两种前端产物、单writer重启与回归。当前待用户 review/部署指令，不自行进入下一阶段。


## 17. R2部署发布（2026-10-20，当前生产态）

- 用户“部署推送”明确授权。业务b0f9455，从PID2409520切至2794809，启动11:04:50 CST，健康startedAt11:04:51，服务active；仍单backend writer。应用1.1.0，新完整报告schema1.2.0，组合r2.1.0，旧schema1.1.0报告保留可读。发布main，无新标签/强推。
- 备份 `data/backups/r2-report-deploy/20261020-110356` 私有；隔离发布构建后切换dist，入口index-BTL-2MmI.js，旧hash资源保留，report runtime578923字节/3Dmol524112字节。详见实现记录§15。
- 实际本次核验：新接口未登录401；临时用户读取14类型、7项目776候选、真实数据两模型5元素预览（16385字节HTML，不保存），7历史报告和R1状态、旧HTML导出、6静态资源均正常。8配置哈希未变，AI项目开关0、自主enabled=false；临时会话均撤销，未调用模型/HPC，不改科研结果。
- 本次只重新构建与线上只读核验，前轮完整Python/浏览器回归见§16，不冒称重跑。本轮文档随main推送，精确提交/远端结果看Git日志；用户两份删除保持未提交，data/dist/备份不入Git。
- 未实现范围：AI自动编排、多任务计划依赖、科研偏差→验证→调整再算闭环、模型结构自动修改；报告整份删除恢复/3D自动截图PDF/复杂布局。已有单OPT Mock闭环仍须真实授权验证，默认关闭。后续等待用户指定目标，不自动进入下一阶段。


## 18. InCI6旧LSF作业阻塞与前端一键核实（2026-10-20）

- 用户要求解决InCI6旧作业无法在LSF确认结束、前端无处理路径；后续明确只放提交报错窗口，一次点击解除，不设常驻按钮。
- 真实只读核对：InCI6父任务task_1792162930753_2，旧job751321，pending，当前结构结果con1，已创建con2但未提交。bjobs没有该task族（总4条其他作业）；bjobs -l/ bhist均无历史，bacct旧会计文件不可用。con1/751321.out的LSF回执Subject Done、工作目录匹配con1、Terminated at Mon Oct 19 09:53:12 2026；result尾部为软停止后的正常进程退出，不认定为结构已收敛。
- 根因：assert_remote_idle始终要求旧job在当前LSF结果中出现；旧作业不在阶段1执行台账，resolve-finished接口无记录可处理。现有resolve-finished确认也未被旧job检查读取，后续仍可能再次阻塞。
- 修复：原gateway/ledger/审计中保存有身份绑定的人工结束确认，不清job_id、不改科学状态/授权预算。新增GET/POST task prior-job路由，确认时重新查询LSF、重查任务族和身份；活动任务族conN、未知目录、LSF失败、身份变化、Agent/越权、未对账动作、审计失败均不放行。既有resolve-finished也产生同样绑定，后续提交保留全部活跃检查。失败预检保存原因，不再只留空reason。
- 前端：Jobs提交捕获该具体报错，打开PriorJobReviewDialog；显示有界LSF回执与旧job/目录/时间，匹配ID/目录/结束时间后，一键明确人工确认并记录依据；无常驻入口、无额外填字/勾选、无自动重提。缺证或活动/未知状态保持阻塞。
- 已执行验证：网关43项（新增5项，包括真实HTTP认证/显式确认/防Agent写/并发状态变化、作用域、审计失败、旧接口确认重用），OPT47、基线10通过；typecheck、/tmp/vasp-prior-job-final-build构建、prior-job-review浏览器通过；参数证据26及原Jobs结构刷新浏览器结果见本轮最终核对。远端只读回执读取实测1份，含正确终止时间及Done。
- 生产上线/备份与最终PID待本节末尾回填。按最新交互，未替用户写人工确认记录；让用户在报错窗口按展示的证据点击确认。不会替用户提交con2；AI/自主开关不改，不进入阶段3/4。
- 关于模型：ai_chat_service项目上下文及task_context都含calc_description/expected_results，模型可据证据分析和提出下一步建议；OPT模型仅审核确定性候选或pause，不会自主从科研目标生成结构或多任务计划。该能力边界本轮未改变。
