# 阶段1 · 最小安全自主执行底座

2026-10-19；v1.0.1之后的工作区变更；Mock验收完成；经用户明确要求于2026-10-19部署，未提交推送。阶段2未开始。

## 已完成与复用

在现有 `ActionSpec`、`core_submit/core_continuation`、SSH模拟入口、任务锁、项目归属、token scope、pending-actions和审计上扩展，没有第二套任务库、DAG、聊天系统或SSH连接器。

- `automation/ledger.py`：授权、动作和预算预留保存在同一份 `data/agent_execution.json`（0600）。复用store进程锁+flock；文件fsync、原子替换、目录fsync。损坏文件拒绝执行，不按空记录恢复。默认自主开关false；无记录不自动创建生产台账。
- `automation/budget.py`：CPU单队列、固定核数和walltime；默认活跃作业1、提交次数3、单节点失败重试最多1（总尝试最多2）；核数、walltime上限、核时上限必须显式配置。未知/动态资源、job array、GPU等不支持的申请拒绝自动执行；-R仅支持已验证的span和整数内存rusage子集，不放行未知的CPU亲和性等表达式。
- `automation/gateway.py`：真实身份/session复核→项目/任务/动作白名单→LSF状态→预算预留→执行前复核→现有业务实现→持久记录与严格审计。仅开放现有三个动作，阶段1不接受任意参数修改。授权绑定任务根目录、类型及服务器目标指纹，发生变化必须重新授权。暂停、吊销token、项目归属变化后拒绝新动作。
- `automation/unknown.py`：只读LSF状态；不执行bsub。唯一作业名保留任务名称前缀并附UUID；拿不到响应或写库失败保留UNKNOWN及预留预算。进程退出后的running先记interrupted，再对账；排队但未执行的遗留动作标失败，不自动重放。PID及进程启动标识防止误认另一个仍在运行的worker。
- `routers/agent_execution.py`：API授权、预算、执行、历史、对账、人工解除。尚未接入AI工作台动作工具，现有聊天仍保持原能力边界。

`data/projects.json`等原项目存储不迁移；Agent执行台账不复制完整项目数据。旧项目数据可继续读取。

## 关键行为

### 提交与幂等

新入口要求Idempotency-Key，绑定授权与动作参数；相同请求返回原记录，参数变化拒绝。不同幂等键仍受任务族锁、未完成记录、次数和预算约束。

所有既有 `core_submit` 路径增加提交前持久记录和LSF核对（修复重复提交风险）。普通人工提交不要求Agent预算，但遇到UNKNOWN不能直接重提。远端成功、HTTP丢失或本地落库失败时，接口明确返回“不确定，禁止重复提交”，并在可返回的错误数据中带action_id和execution_status。

LSF脚本使用同一份字节快照进行预算解析、SHA256校验和bsub stdin传递；不在“校验文件后”重新读取可变文件作为提交内容。预检目录变化或脚本变化阻止提交，不会借较旧预检申请较大资源。

父任务及续算子任务共用任务族锁；受控的 `continuation → submit` 使用实际新建子任务，在同一台账/授权/预算中完成。中途失败保留阶段与子任务ID；不创建新的无预算接力动作。

### 预算与实际消耗

预算范围为单授权工作流、单服务器、单CPU队列；不跨队列或不同资源类型混算。预留核时=核数×walltime；活跃预留和已结算消耗一起占用总预算，失败尝试计数。预算和动作创建在一个事务中提交，多个任务并发也不能超额预留。

启动、显式对账以及新的非dry-run执行请求，会核对已有作业。LSF能确认结束则释放活跃槽位；当前没有已验证的实际计费采集器，消耗按申请上界保守记账，`consumption_basis=reserved_upper_bound`，不能当作实际核时统计。LSF结束不改写为VASP收敛/科学通过，科学状态由现有巡检确定。

### 审批及旧自动化

审批前重新核对当前项目归属与提案指纹；在执行前先持久化executing认领。并发批准、重放批准和审批参数修改被拒绝。审批执行也需要有效grant_id；旧提案没有指纹时需重新创建，不直接执行。全局dry_run仅预览，不将提案冒充执行成功。

Agent的write不再允许任意业务写接口；修改类请求默认拒绝，只允许受控执行、提案及必要的退出入口。Agent不能改授权、预算、开关、服务器或直接submit/continuation/create-frac。

旧自动化规则继续走原调度器，补持久队列记录、执行前锁内复检、失败计数、全局dry_run不可覆盖、事件幂等、实际子任务接力、定时历史增量合并；短动作也可通过原run查询接口读取。重启的旧长动作标interrupted，优先使用新台账的恢复结果。

新授权创建时enabled=false、managed=false，不影响旧规则。人工首次显式启用授权后，该任务进入托管范围；旧规则不能成为预算旁路。随后即使暂停自主开关/该授权，也不会悄悄恢复旧规则绕过限制。普通人工入口保留，但受提交不确定状态保护。

### 人工控制与秘密

人工可暂停整个自主入口、禁用单授权、吊销token、查看状态、只读对账。暂停只阻止新动作，不声称停止HPC作业；停止仍走现有人工停止入口。

LSF历史缺失时不会把“查不到”当成失败。人工外部核实后可显式确认未提交或确认作业已结束，必须填写核实依据并记录操作者。仍有活跃/未知LSF作业时拒绝解除，Agent不能调用解除接口。确认结束也按申请上界记消耗，不自动伪造实际计费。

SSH配置仅管理员可读，响应只有password_configured，不回显password。前端不再持久化口令，兼容后端已有口令和缺省口令保存语义。scope=[]不再变成全权，Agent新会话缺省read，旧Agent无scope会话不能执行。

## 验证与验收

独立进程运行，避免配置DATA_DIR的模块缓存互相影响：

```bash
.venv/bin/python -m unittest discover -s tests -q
# 52 tests，OK (skipped=2：下方两套需单独运行)
.venv/bin/python -m unittest discover -s tests -p 'test_automation_baseline.py' -q
# 10 tests，OK
.venv/bin/python -m unittest discover -s tests -p 'test_agent_gateway.py' -q
# 38 tests，OK
node tests/test_ssh_frontend.cjs
# PASS：口令不缓存/不回显、已有口令连接兼容
npm run typecheck
npx vite build --outDir /tmp/vasp-stage1-build
# 成功；原有大包警告。未覆盖生产dist。
```

100项Python测试覆盖：

| 验收 | 证据 |
| --- | --- |
| A 重复请求不重复动作 | 同请求10次、双线程、双独立进程均仅1次bsub；变更参数拒绝 |
| B 重启不盲目重放 | 子进程在bsub后强制退出，再对账绑定Job ID；未执行队列记录不重放 |
| C 预算限制 | 核时/核数/walltime、活跃数、提交数、重试数、资源缺失/不支持；多任务共享预算并发 |
| D 授权 | 归属越权、无write scope、token吊销、全局/任务暂停；完整ASGI应用含lifespan的HTTP鉴权和旁路拒绝 |
| E 不确定状态 | 丢响应、提交后写库失败、LSF未知/历史清理、错误执行标识；只对账或人工解除 |
| F 可追溯 | 动作先持久化、严格审计、短动作run查询；模拟审计/台账写失败不执行 |
| G 原人工流程兼容 | 原52项、基线10项；Mock中真实core_continuation创建con1并实际接力submit；SSH口令保存兼容 |

新夹具在原Mock SSH上补bjobs PEND/RUN/DONE/EXIT/UNKNOWN、bsub丢响应、stdin快照、整应用HTTP harness和独立进程崩溃/并发；未连接真实HPC、未调用真实LLM、未修改真实生产数据。

## 兼容性、限制和上线前检查

- 写操作通过Mock验收；部署前已对真实server1执行只读LSF查询，验证上述bjobs字段格式能正确解析（当时RUN 4、DONE 1）。未做真实提交、续算、资源占用或历史清理演练；不支持/无法确认时仍拒绝提交。
- 自动资源解析只覆盖经测试的静态CPU单队列脚本。普通人工资源配置不强制套用该解析子集；提交安全检查和唯一作业名称会作用于人工入口。
- 不确定的续算文件副作用不自动回滚，也不自动重试；记录UNKNOWN，人工检查目录与输入来源后处置。
- 项目库仍采用原存储，生产部署维持单uvicorn进程；台账和同任务族锁已测跨进程，并不意味着整个项目库、巡检或定时器变成了完整多进程部署方案。
- 台账不自动清理，避免丢失预算/幂等依据；长期归档策略后续按实际体量建设。PID启动标识依赖当前Linux环境。
- 未新建配置UI，未把执行工具交给聊天模型；下一阶段再做单OPT Observe→Diagnose→Act→Verify，不能据此认为AI工作台已自主执行。
- 真实自动化正在生产运行；本轮未改其配置、授权、数据或运行进程。后续上线先备份台账/项目库/审批队列/自动化配置，再在隔离实例验证站点LSF兼容性，保持新入口关闭，显式授权少量任务后启用。

## 回滚

本轮已部署。需要回退时：先暂停新动作并保留现有作业，再确认或人工处置所有UNKNOWN及执行中记录，备份上述数据后回退代码。不能删除台账、将UNKNOWN改失败或直接恢复旧自动化来规避保护；回到不识别台账的旧版本前须先排除未确认作业。预算/台账/审批记录不得通过旧备份倒退后自动重放。


## 部署记录（2026-10-19）

- 用户明确要求部署后，先完成私有备份，再复制已验证前端资源并原子替换index，重载systemd服务。保留旧前端哈希资源供已有页面使用。
- 真实LSF仅进行只读查询验证，未触发提交/续算/停止；未启用任何Agent授权。新服务PID 2184680，启动时间2026-10-19 21:47:32（Asia/Shanghai）。
- 在线验证：/api/health、/jobs及6个静态资源正常；未登录访问新接口/SSH配置均401；带临时read scope验证凭证访问新入口，确认enabled=false、grants/actions均为空；SSH配置无password字段。验证凭证已在finally撤销。
- 私有备份：/home/zouyuxi/projects/vasp-manager/data/backups/stage1-deploy/20261019-214719（目录0700、文件0600），含原dist、原HEAD后端代码归档、项目/审批/历史/配置及AI SQLite一致性备份。不含AI主密钥，不入Git。
- 既有自动化配置保持不变；仍未把执行工具接入聊天模型，阶段2未开始。
