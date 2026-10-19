# 阶段2：单OPT自主闭环

2026-10-19；Mock验收并已部署，自主执行保持关闭，零授权/OPT循环；未提交或推送，阶段3未开始。上线验证见PROGRESS.md第10节；真实自主计算仍未验证。

## 范围与复用

对一个已有POSCAR和配置的原始OPT任务，推进观察→诊断→决策→策略校验→动作→验证→结束/暂停。没有新增聊天、通用工作流框架、结构建模或任意SSH工具。

- `automation/opt_loop.py`：有限步骤、策略、结构化模型提案、暂停/恢复/人工结束、总结。运行位于原`data/agent_execution.json`的`opt_runs`，与现有授权/动作/预算同一原子事务存储。
- `automation/opt_evidence.py`：原巡检近三个目录观测作历史；巡检缺少SCF、完整输入和尝试身份，复用SSH进行固定文件只读补证。复用现有POSCAR、力块和错误解析器。
- 执行复用阶段1网关、任务族锁、预算、幂等、严格审计，以及现有`core_continuation`和INCAR草稿。参数不是从聊天直接传给执行器。
- 由原巡检完成事件推进，或人工调用`step`。没有额外定时轮询；运行中观察不调用模型。新能力受原自主总开关和单任务授权约束，默认关闭。

## 策略

| 情况 | 行为 |
| --- | --- |
| 已有输入且尚未提交 | 验证输入，通过网关提交 |
| LSF仍在排队/运行/挂起 | 记录状态，等待下次事件；不调用模型 |
| LSF明确walltime结束 | 完整证据且无冲突时调用现有续算并提交实际子任务 |
| NSW耗尽 | 仅在显式配置增量、绝对上限、修复次数及足够力改善时通过现有草稿增加NSW |
| SCF未收敛 | 给出诊断和人工建议，不自动修改ALGO、混合、展宽或磁性参数 |
| 状态未知、文件不完整/身份不符、新异常、预算不足、无改善 | 留下证据和原因，暂停；未知时仅查询/对账，不重提 |

walltime必须由`bjobs -l`确认`Job <id>`、作业名及`TERM_RUNLIMIT`；可写的result日志不能提供执行授权。详情格式不识别或历史被清理时安全暂停，真实集群格式尚待只读核验。

修复前保存输入文本/摘要、证据、决策、风险和重试余额，预算落盘后才应用NSW草稿。草稿diff以本次远端INCAR为准，保留本地镜像元数据；已有人工待应用草稿会阻止自动操作。bsub前再次验证新目录POSCAR等于确认的CONTCAR、其余输入未改变、INCAR只发生授权NSW和原续算必需的ISTART/ICHARG变化。

存在未结束OPT循环时（包括暂停），通用Agent动作入口不能绕过该循环策略；人工可先close结束托管。原人工业务操作仍可用于接管，后续循环会检测人工动作。暂停/结束自主处置不停止已有HPC作业。

## 证据与科学边界

- 来源为最新最大编号conN，不回退旧主目录。记录实际目录、作业ID/执行名、采样时间、文件大小/mtime/指纹、巡检观测ID。遇到未登记目录、未知作业或输出早于本次提交，不用旧镜像补结论。
- OUTCAR/OSZICAR/result有界读取尾部512KiB；指纹明确标记full或tail，结合大小/mtime校验，不把尾部哈希称作完整文件哈希。POTCAR仅存TITEL和完整摘要，不存完整势文件正文。输入超过解析范围则暂停。
- 初期自动范围：VASP5结构、正缩放、IBRION=1/2、显式NSW/NELM/EDIFF、负EDIFFG。约束原子、特殊缩放、缺少关键参数等需人工复核。
- 检查必需文件、元素/原子数、有限坐标/力、最后SCF周期变化、OUTCAR与OSZICAR最后离子步/能量一致、最终力相对EDIFFG、程序正常退出与LSF结束。单一`reached required accuracy`不能提供成功结论。
- 结果分COMPLETED/CONVERGED/FAILED/UNKNOWN；电子和离子PASS/FAIL/UNKNOWN另列，科学数值精度仍NOT_TESTED。没有自动证明ENCUT/k点精度、真实物理性质可靠性或科研预期成立。
- 核时继续按阶段1申请上界预留/结算，实际核时NOT_TESTED。
- 作业登记、排队和启动分开记录：job_registered_verified确认LSF已受理，只有RUN才令started_verified为真；PEND不会被冒充为已启动。

## 模型与权限

可选`connection_id`绑定启动人工账号自己的现有AI工作台连接，沿用加密密钥和OpenAI兼容流式请求，支持DeepSeek。不提供连接时执行确定性策略。只有修复候选需要模型审阅，普通状态查询不调用模型。

模型得到有界任务/项目上下文、近三目录历史、当前诊断/证据引用、候选和JSON Schema；日志按不可信数据处理。必须返回严格JSON，可同意候选或暂停，不能扩大动作/参数。置信度不构成授权。非法JSON、截断、工具调用、越界参数或要求人工复核都阻止执行。

创建/推进/控制循环须人工项目owner/admin。后台绑定启动会话，身份失效、会话吊销/过期、Agent禁用、项目归属/服务器目标变化、授权暂停时停止新动作。循环锁复用现有进程锁/文件锁，副作用仍持有任务族锁。

进程中断后，已存在成功动作可恢复到VERIFYING；没有动作记录或动作UNKNOWN时暂停，不重放。先通过阶段1对账/人工核实，再决定恢复或close。部分创建的con目录、已应用草稿不自动删除或回滚；现有续算对WAVECAR的移动仍遵守原逻辑。

AI聊天新增只读`get_opt_runs(task_id)`，按当前项目查询诊断、决策、历史及总结；没有新增聊天执行工具或配置面板。

## 使用

先用阶段1接口明确授权任务、动作、队列和预算并显式启用（必须人工操作），再调用`POST /api/agent-execution/opt-runs`：

```json
{
  "task_id": "existing_opt_task_id",
  "grant_id": "grant_...",
  "max_steps": 30,
  "max_repairs": 1,
  "nsw_increment": 50,
  "nsw_max": 300,
  "min_force_improvement": 0.05
}
```

可选connection_id为本人现有连接ID。创建不立即提交，等待巡检事件或`POST /api/agent-execution/opt-runs/{id}/step`。`GET /api/agent-execution`列出可见运行摘要，`GET /api/agent-execution/opt-runs/{id}`查看明细。`POST .../{id}/control`接收`{"command":"pause"}`、resume或close。NSW两个值缺省均0，表示禁止自动增加；修复上限不得超过grant.max_retries。配置要修改时人工结束当前循环并重新创建，不能让模型改自己的预算。

## 验证

独立进程运行，三套专用测试的DATA_DIR模块缓存不能混用：

```bash
.venv/bin/python -m unittest discover -s tests -q
# 52，通过；skipped=3的专用套件分别运行
.venv/bin/python -m unittest discover -s tests -p test_automation_baseline.py -q
# 10，通过
.venv/bin/python -m unittest discover -s tests -p test_agent_gateway.py -q
# 38，通过
.venv/bin/python -m unittest discover -s tests -p test_opt_loop.py -q
# 47，通过
node tests/test_ssh_frontend.cjs
npm run typecheck
npx vite build --outDir /tmp/vasp-stage2-build
```

总计147项Python离线测试。新增47项覆盖完整Mock业务入口、真实HTTP鉴权、续算草稿及输入复核、模型流解析、越权/日志注入/策略旁路、旧镜像、无改善、预算、人工暂停及恢复、排队和启动区分等。

真实HPC提交/续算、真实模型调用、真实LSF walltime详情格式和完整科学精度均NOT_TESTED。隔离构建没有覆盖生产dist。Vite保留既有大包提示。
