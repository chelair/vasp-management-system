# 阶段2补充：实际参数记录和按需远端只读证据

2026-10-19，Mock验收完成并于23:13部署；健康、鉴权、参数历史接口和工作区只读证据规则已验证。未提交推送，没有启用生产自主执行或进入阶段3；备份与部署验证见PROGRESS.md第10节。

## 问题与实现

原工具只标记con5/con6参数指纹不同，没有直接给出差异；旧巡检INCAR解析会截断MAGMOM/DIPOL等多值参数，NEB也缺少KPOINTS摘要。现在巡检工具返回逐项before/after，未来巡检保存完整参数值和参数实际来源，保留原巡检频率、状态判定和结构回传逻辑。

新增`parameter_history.py`复用原任务input_state存储。成功上传INCAR/KPOINTS、实际创建续算输入、LSF接受提交后记入`applied_history`；任务族共享最近5次实际操作记录，草稿编辑/撤销、dry_run、提交拒绝或上传失败不占名额。这与“巡检保留5个目录，每目录一个最新结果”是两套独立保留口径。

记录包含目录、时间、事件、作业号、实际采集的参数快照、旧/新值及来源。提交快照在bsub前同一次SSH采集，LSF接受后随任务状态同事务保存，不拿草稿或延迟同步镜像冒充提交参数。续算记录保存实际应用的INCAR；上传只记录该文件，不用其他目录的参数补齐未采集内容。输入超过提交采集上限64KiB则缺项，不伪造完整快照。

上传或续算写入代表输入文件已写入，不证明运行中的VASP已重读；提交快照也不证明数值收敛。旧值未采集时明确标记未知。历史从新操作开始累积，不自动向生产库补造旧记录；已有巡检参数或远端只读对比用于解释历史conN差异。

作业管理来源横幅增加折叠历史，保留草稿的原显示和撤销操作。已有input API附加applied_history，任务context附加记录引用；AI按需工具读取详细值，不每轮附完整历史。

## 查询顺序

1. 模型定位任务并调用`get_task_inspections`，先检查来源和采集时间。
2. 参与自动巡检的任务用固定4小时阈值，时间缺失/异常、目录/作业不符、参数从根目录回退读取或巡检后有新实际参数记录时，不能用旧观测确认当前状态。
3. 项目关闭、任务pending/archived、无服务器或自动巡检停用，不按4小时自动判旧；历史参数缺失仍可按需只读查询，不把历史当实时状态。
4. 证据足够新且来源一致时继续本地分析。参数差异优先读comparisons.parameter_diff、get_inspection_evidence(kind=parameters)和实际参数记录。
5. 只有过期、来源不符或参数缺失才调用`get_remote_task_evidence`；后端再次验证必要性及证据版本，不靠模型自述授权。
6. 同一次只读SSH采集固定文件和LSF，返回最新目录、采集时间、文件mtime/指纹/完整性、当前调度状态及与本地任务元数据的对应关系，再判断是否需要干预。只读证据不授予干预权限。

## 两个新增AI工具

`get_task_parameter_history(task_id, record_id?, offset=0)`：默认返回最近5条实际操作的摘要/差异；指定record_id分页读取快照，每页最多40项且不超过16000字符。大值预览有明确truncated标记，不能当完整值。

`get_remote_task_evidence(task_id, evidence_token, reason, directories?)`：evidence_token来自先前get_task_inspections；巡检、任务身份或最新实际参数记录改变后必须重新查询。reason仅stale_evidence/source_mismatch/missing_parameters。默认CURRENT，历史对比按旧→新指定最多2个MAIN/已知conN目录。

远端工具不接受命令、文件名、任意路径、凭据或服务器覆盖。复用原SSH连接池和LSF解析；一个请求一个exec，仅使用固定Python只读采样和bjobs。只读INCAR/KPOINTS、当前OUTCAR/OSZICAR/result尾部及最多8个NEB中间映像摘要，不读POTCAR、波函数或任意系统文件。拒绝符号链接和非普通文件；总文本预算24KiB、输入单文件8KiB，截断/缺失明确标记，不把片段哈希称完整文件哈希。超过读取范围就保持未知，不自动扩大读取范围。

相同证据请求在60秒内可复用内存结果，保留原采集时间。LSF失败、身份不明确时状态UNKNOWN；文件读成功不等于调度状态已核实。只返回当前任务范围的作业，不向模型提供服务器凭据或其他项目作业。日志按不可信数据处理并脱敏。

远端读取不修改本地结构/巡检归档/任务状态，不触发巡检、不上传、不提交、不停止作业。只在已启用工作区的会话工具中开放，沿用当前用户和项目归属；聊天仍无任意SSH/Shell/计算动作工具。调用及结果沿用AI运行历史的tool_events，界面显示采集时间和远端状态或“沿用本地证据”。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -q
# 53，通过；skipped=4的专用套件分别运行
.venv/bin/python -m unittest discover -s tests -p test_parameter_evidence.py -q
# 26，通过
.venv/bin/python -m unittest discover -s tests -p test_automation_baseline.py -q
# 10，通过
.venv/bin/python -m unittest discover -s tests -p test_agent_gateway.py -q
# 38，通过
.venv/bin/python -m unittest discover -s tests -p test_opt_loop.py -q
# 47，通过
PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/parameter-history.cjs
# 浏览器：具体差异、con目录/作业、草稿分离、无额外请求，通过
npm run typecheck
npx vite build --outDir /tmp/vasp-parameter-evidence-build
# 通过；没有覆盖生产dist，保留既有大包提示
```

新增真实HTTP/SSE模拟模型测试验证“巡检时效→实际参数记录→远端只读补证→LSF状态”的工具调用链；26项专项通过真实Mock SSH/LSF验证目录/越权/链接边界、单次exec、缓存、截断、脱敏、失败/草稿不入历史、实际提交/续算/上传、源变化失效等。总计174项Python测试通过。

真实模型及真实HPC只读链路尚未调用，生产应用效果NOT_TESTED。阶段2此前的约束体系等兼容限制仍存在，本次没有扩大自动修复范围。
