# R2 · 细粒度、可复用报告元素：任务与接续交接

状态：**R2-A/B合同缺口已收敛，R2-C手工编辑/冻结证据预览导出及R2-D首批14类元素适配已实现并通过本地验收**（2026-10-20）。见实现记录§14、PROGRESS §16。本文件下文保留原始任务合同和历史接续顺序，标有“未开始/待做”的旧节不能覆盖本状态。R1生产仍运行；R2本轮**未部署、未推送**，不进入AI自动编排。

本文件是下一位开发者的完整任务合同与工作清单；`AGENTS.md` 为总入口，`PROGRESS.md` 记录验收，`process.md` 记录生产部署。以当前 Git 和源码为准，开始/停止时更新交接，不能只在聊天中汇报。

## 1. 用户要求与验收合同（必须保留）

在现有报告上建立轻量 **Evidence（科研事实/结果）+ ReportBlock（展示元素）**。Block 只引用 Evidence；一个 Block 可引用多条证据，多 Block 可共用同一证据，不把科学数据复制到每个 Block。

- 完整项目报告继续走原生成路径，外观、3D/图表/折叠/隐藏/注解及 HTML/PDF 保持；保留 Markdown/DOM，旧 `report.json`、`report.md`、notes、edits、HTML 必须可读。
- Block 最小字段结合现有代码确定：稳定 `block_id`、`type`、`title`、`project_id`、可选 `task_id/group_id`、`source_refs`、`data_status`、`validation_status`、`renderer`、`options`。ID 不能由图表序号/任务标题唯一确定；稳定身份和实际数据版本分离。
- 首批实用粒度：单任务基本信息、关键参数、最终能量/最大力、收敛曲线、结构可视化、自由能路径、NEB 能垒、PDOS、Bader、功函数数据/曲线、差分电荷图、对照表、分析文本、方法与来源；不要分到单原子/HTML标签/单元格。
- 候选集合必须从**授权项目与全部任务**查找，不能只解析已有 Markdown 或限额内 `science.opt`。区分没有数据、存在但未解析、未收敛、被完整报告省略/隐藏、已过期；“没展示”不是“没有计算”。
- 来源至少记录 task_id、计算目录/attempt、源归档/文件、可得的参数/输出指纹、解析时间；缺失来源标 UNKNOWN，不能伪称验证通过。采集时间/解析时间/报告生成时间分别记录。
- 简单组合输入：标题、有序 Block IDs、分组与展示选项；输出预览、结构化定义、HTML、PDF打印兼容和必要资源。复用 ECharts、结构、PDOS/Bader/功函数、NEB/自由能及自包含导出，不重写成熟组件。
- 编辑：添加已有元素、删除/隐藏、上/下移、简单分组、改标题、恢复；暂不做拖拽、自由画布、多列布局。
- 新隐藏逐步使用 block_id，旧标题/序号 key 保留兼容映射；歧义不能错误映射到其他任务。
- **最终人工验收**：选择两个模型→两个能量结果→参数对照表→一张相关图→自定义顺序→加文字→导出 HTML/PDF。重排、改标题和隐藏/恢复不使身份错乱；旧完整报告无明显回归。
- 禁止 AI 自动编排、多 Agent 框架、复杂数据库、知识图谱、通用工作流；不修改科研结果、巡检频率/回传、任务状态/输入文件或远端目录。模型/SSH/真实HPC不用于 R2 测试。

## 2. 已核实源码与关键缺口

| 入口 | 已有结构化数据/职责 | R2 注意点 |
| --- | --- | --- |
| `backend/report_builder.py::_task_facts()` | 从项目全任务与 `collect_results()` 合并巡检；能量、力、history、参数、来源、状态 | 可复用事实提取；保留原始未知值。不要为候选查询调用完整 `build_report()`，后者可能调 `cluster_snapshot()`/SSH |
| `_task_detail_row()`、`tasks.groups`、`appendix.all_tasks` | 主任务摘要不受6条正文上限；R1新增 INCAR/KPOINTS/来源/精度/巡检时间/组 | 摘要未保留完整曲线/CIF/图片，不能因此宣称具备全部细粒度证据；辅助 conN/差分分块由旧语义去重/关联，不全当独立模型 |
| `MAX_STRUCTURE_TASKS=6`、`build_report()` OPT循环 | 只给前6个符合条件且有 `force_history` 的独立OPT构建 `science.opt`、曲线、CIF、三视图/弹窗；未收敛也过滤 | **不是只有Markdown少展示**；超额任务缺少完整科学详情/资源。源码注释“其余只进结构化数据”仅对摘要成立。不能只提高常量或解析现成Markdown，须独立全候选 + 按选择解析 |
| `_free_energy_paths()`、`_neb_details()`、`_ele_details()` | 路径组与中间体、NEB映像/能垒、电子结构记录/差分分块 | 复用组ID和任务ID，保留依赖/参考态，不凭不同模型名字猜同体系 |
| `_pdos_report_data()`、`_work_function_report_data()`、build末段Bader/差分处理 | PDOS摘要/SVG（曲线有上限/采样）、功函数数值/曲线、Bader完整原子表/CIF、差分图弹窗 | 摘要/SVG不是全部DOS原始曲线；Bader优先冻结结构，`cif_source=mirror`不能冒充分析时结构；无静态图片不伪造 |
| `_sections_markdown()` | 根据上述数据生成固定章节、关键结果概览、各类型表格/叙述、图注、挂点、弹窗链接 | 大量**展示语义**只存在模板/Markdown：章节/标题顺序、表格列和组合、单位格式、参考态提醒、图注/链接、方法口径。不要把这些反解析为科学真相；按现有模板/纯函数建Adapter |
| `report_store.py::save_report()` | report.json/md、charts/images、结构化副本、每日HTML，原notes/edits分开 | **每项目只保留一份最新完整报告**，会删同项目其他 report_id 的目录/索引。专题组合不能直接塞入该清理规则；需明确独立命名空间，不改旧完整报告清理语义 |
| `report_export.py` | `_inline`/`markdown_to_html`、widget_renderer、notes、hidden、图像内联、打印脚本、`render_html()` | 扩展薄Adapter保留旧输出路径。R1已补XSS与过期提示，不能回退。新组合用稳定ID定位，旧key继续兼容 |
| `report_interactive.py` | payload映射、runtime/3Dmol内联，缺runtime降级静态 | `interactive_payload()` 的**PDOS会按task_id重新读当前本地数据**；新组合如宣称冻结版本，不能沿用此行为偷换版本。Bader/结构/功函数等多来自report快照 |
| `ai_view.py` | 单位/时间/状态规范化、从appendix列出任务；science.opt仍来自限额结果，电子结构不完整 | 可复用规范化工具，**不是完整证据目录**。`normalize_task_status()`非low_precision默认precision_ok=True，部分`bool(None)`变False；新Evidence不能据此把未知标PASS/FAIL。此审查未改旧API |
| `report_schema.py` | 当前报告schema **1.2.0**、单位/状态族 | 为新Block/组合声明独立轻量schema，保留旧报告兼容，不把Block硬塞成改版的全部旧文档 |
| `Report.tsx`、`reportHidden.ts` | 旧Markdown→DOM→Portal，按标题/文件名挂交互；隐藏 key 含 section/type/task/etask/figure序号 | 新block_id不能用这些标题/图序号生成；旧映射须基于授权任务/组与实际资源，标题重复/歧义保留旧key不误迁移。React/原生widget不能同时管理同一DOM子树（曾因此白屏） |

### 已有渲染器与特殊运行时

| 类型 | 页面复用 | 单文件HTML/PDF复用 |
| --- | --- | --- |
| 能量/力曲线 | `EnergyForceCharts`，通常在收敛弹窗 | `report_charts.energy_force_chart` SVG +旧弹窗/打印 |
| OPT结构/自由能中间体 | `ReportStructure3D` / `ReportFreeEnergy3D` +本地3Dmol | `structure3dWidget`、`reportRuntime.ts`、3Dmol内联；三视图PNG打印兜底 |
| 自由能/NEB图 | `FreeEnergyReportPanel` / `NebReportPanel` ECharts | 旧导出以SVG为主，独立runtime没有通用NEB/自由能曲线mount；不要误报现有导出已全是ECharts |
| PDOS | `PdosReportChart` → `mountPdosWidget`（当前组件按task_id拉API） | `pdosWidget` +内联payload +ECharts，静态SVG打印 |
| Bader | `BaderChargePanel` / `BaderFullTable` | 原完整表+结构3D runtime，核对冻结CIF与ACF来源一致 |
| 功函数 | `WorkFunctionReportChart` / `workFunctionWidget` | 内联summary/ECharts +SVG打印，复用CSV/TXT数据逻辑 |
| 差分电荷 | 原images/三视图dialog/图片浏览 | 原PNG base64内联与打印；不重新计算CHGCAR |

`dist/report/report-interactive.js` 是**后端内联读取的文件，不是公开 `/report/` 路由**；运行时由 `src/interactive/reportRuntime.ts` 打包。禁止漏构建/漏携带3Dmol和静态兜底。

## 3. 建议的最小合同（待下一位以测试落实，不是已实现）

不要先造平台。先做一个项目内、只读本地候选→固定证据→手工组合的闭环。

### Evidence 与 Block 分开

```text
Evidence:
  evidence_id            任务/组+证据种类的稳定逻辑标识
  version                身份、实际payload与来源的内容摘要；不可用报告生成时间冒充版本
  project_id/task_id/group_id
  kind, payload          科学数据仅在此处保存一次
  provenance[]           task_id、directory/attempt、archive/file、observed_at、parsed_at、hash及hash_scope
  availability           available | missing | unparsed | unknown
  validation             PASS | FAIL | WARNING | NOT_TESTED | UNKNOWN，分项说明证据
  freshness              fresh | stale | unknown，附判断依据

ReportBlock:
  block_id               项目/任务或组/类型/variant的确定性ID；文本块创建UUID
  type, title, project_id, task_id?, group_id?
  source_refs[]          {evidence_id, version}，不复制payload
  data_status, validation_status
  renderer               注册白名单类型，不是任意组件名/代码
  options                白名单展示设置，不含命令/任意文件路径/科学值覆盖

Composition:
  composition_id, project_id, title, schema_version
  block_ids[]            有序稳定引用；分组/标题/隐藏按block_id保存
  blocks, evidence       去重映射；证据版本冻结，变化只能显式刷新后另核对
  groups[], hidden_block_ids[], updated_at, revision
```

- 同任务的能量、曲线、结构Block可引用同一证据；参数对照表引用两个任务的参数证据。重命名/重排/隐藏不改变block_id。ID不含能量值、conN版本、标题或图序号；数据变更更新version。
- 避免用单枚举混淆缺失/未解析/未收敛/省略/隐藏/过期：候选另记 `full_report_visibility`（shown/omitted_limit/omitted_unconverged/hidden/not_applicable），收敛和freshness独立。UNKNOWN必须保留。
- 默认项目内选元素；多项目合并不是首批验收，不能因跨项目复用绕过每条证据的权限。读取/保存/预览/导出/资源请求都验证当前归属。
- 候选只返回轻量状态/身份，不为所有任务跑图/CIF/DOS。选定时使用已有本地解析、checks归档和资源白名单；原文件存在而未解析标unparsed；解析失败返回可解释状态，不等同missing、不触发SSH或改任务库。
- 提交组合时后端从合法ID解析证据，不接受前端伪造科研payload、renderer代码、路径；用户分析文本允许纯文本/现有安全Markdown，不能以文字覆盖事实。
- 初期用原报告根下独立 `compositions/` 命名空间，简单原子JSON与修订检查；与完整报告索引/删除/单份清理隔离。最小方案一份组合JSON内有去重evidence映射和相对assets，不引入数据库/通用证据仓库/GC平台。
- 预览和导出必须用**同一固定Evidence版本**；PDOS组件增加可选冻结view输入或薄包装，默认旧API路径保持。新组合runtime数据按block_id/实例键索引，不能仅task_id，否则相同任务的不同元素/版本相互覆盖；旧data-task-id保持回退。
- 删除元素要可恢复：从有序列表移除但保留目录/配置/隐藏状态，不删除Evidence或原计算；恢复时保持ID。初期可明确拒绝重复添加同一block_id，之后若需要副本再引入展示实例ID。

## 4. 下一位的顺序与停止点

以下全是**待做**，不能报告完成。

1. **R2-A：合同+候选目录**。先做 `backend/report_blocks.py` 的最小schema/稳定ID、全授权任务候选、来源与状态Adapter，以及隔离测试。优先复用 `_task_facts`、`checks_store`/`ai_inspections`、`task_paths` 和本地解析，不调完整build_report。最少8个OPT夹具，验证第7/8个仍可发现；未收敛、无历史、有原文件但未解析、同名任务、缺来源都不误判。这是接手后的第一个可独立验收提交。
2. **R2-B：两模型最小闭环**。只先打通两个能量结果、参数对照、一张曲线、用户文字。后端按ID解析/固定Evidence，保存简单组合定义；验证一条Evidence供多Block使用不重复payload。不要等14类全写完才接UI。
3. **R2-C：编辑与统一预览/导出**。原报告页保留完整路径，新组合入口用同一成熟报告组件/样式；添加、删除/隐藏、上下移、分组、改标题、恢复。HTML/PDF走原导出器薄Adapter；先验证同Evidence版本、XSS、权限、资源打包与重排身份稳定。
4. **R2-D：补全首批类型/兼容**。按第1节14类补上结构、NEB/自由能、PDOS/Bader/功函数/差分、方法来源。旧key映射、重复标题、旧JSON/md/notes/edits读取、完整报告与R1草稿/过期/恢复回归。必要时扩展runtime支持block_id，保留老task_id兼容。
5. 完成用户人工验收流程与全部隔离测试；更新本文件/PROGRESS/process/AGENTS后交付停止。用户未追加授权时，**后续R2提交不自动部署/推送**；本轮部署推送授权用于已完成R1及R2起步交接，不把未验收R2上线。

建议新增仅：`backend/report_blocks.py`、`backend/routers/report_compositions.py`、前端 `ReportCompositionEditor` / BlockRenderer 与相应隔离测试；存储/导出在原模块加明确组合函数，具体拆分由首个闭环决定。不要先加空壳API、迁移或大批空renderer。

## 5. 当前可运行回归与生产边界

- 项目：`/home/zouyuxi/projects/vasp-manager`，main。**这里同时是生产目录**，后台单实例 `vasp-manager.service`；禁止另起连接同一data的后端。临时测试必须 `VASP_WEB_DATA_DIR` + `VASP_AI_KEY_FILE` 隔离，模型/SSH用Mock。
- 应用v1.1.0，报告schema1.2.0（不同版本体系）。R1于本轮部署，AI项目开关均为false；自主执行仍关闭。不得替用户启用AI、恢复/覆盖生产数据、改巡检或提交HPC。
- R1备份：`data/backups/r1-report-deploy/20261019-235623`（0700/0600，Git忽略）。含旧dist/配置/notes/edits/SQLite一致性副本、R1前Git归档与候选源码；不是R2工程文件，不上传。不要重放UNKNOWN或盲目覆盖部署后数据。
- 历史工作区已存在 `待办.md`、`问题.md` 两处用户删除，本轮不纳入提交、不恢复；后续也不要 `git add -A` 或 `git restore .` 混入这些改动。
- 当前194项Python已通过：常规53、基线10、gateway38、OPT47、参数证据26、R1 20。通用discover有5个套件容器需独立进程，不把skip当已覆盖。

```bash
.venv/bin/python -m unittest discover -s tests -q
# 隔离套件逐个进程运行：test_automation_baseline.py / test_agent_gateway.py /
# test_opt_loop.py / test_parameter_evidence.py / test_report_ai_notes.py
.venv/bin/python -m unittest discover -s tests -p 'test_report_presentation.py' -q
.venv/bin/python -m unittest discover -s tests -p 'test_report_ai_notes.py' -q
npm run typecheck
npx vite build --outDir /tmp/vasp-r2-build
PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/report-ai-notes.cjs
git diff --check
```

报告运行时测试也须输出临时目录（esbuild同 `scripts/build-report-interactive.mjs` 选项）；**npm run build 会直接写生产dist，不用于日常测试**。R1浏览器覆盖真实Report组件重生成/切换/注解与实际HTML→PDF，但不是R2验收，不可冒用为Block系统测试。

## 6. 接手/交回协议

下一位先读：`AGENTS.md`开头当前任务→本文件→`PROGRESS.md` §12/13→`R1-report-notes.md`→当前git状态/最近提交，再定位第2节源码。不要再次要求用户复述需求，不要把旧自主阶段指令当成本轮待执行。

每完成一个小提交，回填本文件和PROGRESS：

```text
交接日期 / agent：
工作分支 / 基线提交 / 当前提交（未提交则列文件）：
已完成的R2-A/B/C/D项及实际入口：
Evidence/Block/组合合同的实际定义与设计偏差：
真实运行的测试命令、结果、未覆盖内容：
是否部署/推送；生产PID、版本、备份（仅实际发生时）：
已知缺陷 / 当前阻塞 / 下一步第一条可执行任务：
保留的用户改动与敏感文件边界：
```

如果只做到某一半，明确标记“进行中”，给出最后通过的测试和未完成接缝，禁止把设计当实现。下一次本助手回来也按同一入口读，不能依赖当前聊天历史。

---

## 7. 本轮进展回填（2026-10-20）

```text
交接日期 / agent：2026-10-20 / 临时代班（从其他 agents 接手）
工作分支 / 基线提交 / 当前提交：main / 435140f / dd807cf（本地提交，未推送）
已完成的R2-A/B/C/D项：
  R2-A 完成 —— backend/report_blocks.py（14 类注册表、稳定 ID、全任务候选、来源/状态适配）
  R2-B 完成 —— backend/report_compositions.py + routers/report_compositions.py（冻结证据、组合 CRUD、HTML 导出）
  R2-C 未开始（前端编辑器/页面预览/浏览器回归）
  R2-D 未开始（NEB/自由能/PDOS/Bader/功函数/差分解析与渲染、旧 key 映射）
Evidence/Block/组合合同的实际定义与设计偏差：
  实际 block_id/evidence_id = sha256(项目|类型|任务/组|variant) 截断；文本块 uuid
  version 排除 observed_at/parsed_at（时间不冒充版本）；availability/validation/freshness/visibility 四分
  evidence 去重映射 + source_refs 引用；保存时重算 ID 并校验版本，伪造 400、过期 409
  偏差：R2-A 只接入 6 类证据解析（fact/params/energy/structure/comparison/method），
        其余6种Block类型候选为 resolvable=false，可用性仍按文件情况标 unparsed/missing，resolve 抛 UnsupportedEvidence（不伪造）
真实运行的测试命令、结果、未覆盖内容：见 R2-blocks-implementation.md §9（13+13 新增全绿；194 既有回归全绿）
是否部署/推送；生产PID、版本、备份：未部署、未推送、未重启服务；生产 PID/版本/备份均未变化
已知缺陷 / 当前阻塞 / 下一步第一条可执行任务：
  缺陷：组合写锁是进程内锁（沿用单后端进程假设）；R2-C/D 未接入
  下一步：R2-C 前端 ReportCompositionEditor + 同一冻结证据预览 + 浏览器/PDF 回归
保留的用户改动与敏感文件边界：待办.md、问题.md 两处删除未提交、未恢复；data/配置/密钥/dist/备份不进 Git
```

## 8. 续开发结果（2026-10-20）

已实现用户的两模型人工组合验收流程，页面入口「智能报告→专题报告」。A/B缺口、C/D实现、测试、生产边界与限制统一记录在 `R2-blocks-implementation.md` §14，PROGRESS §16同步；本文件§1的完整任务要求保留。后续先核对Git日志与上述最新节，部署须另有用户授权，不重做历史§4的已完成步骤。
