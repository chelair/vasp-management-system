# R2 实现记录（A/B初版历史 + C/D接续验收）

> 交接给下一位：先读 `AGENTS.md` 开头「当前接手任务」→ `R2-report-blocks.md` → 本文件 → `PROGRESS.md` §14。
> 本文件记录**实际做了什么、没做什么、为什么**；设计合同仍以 `R2-report-blocks.md` 为准。

> **最新状态见§14**：2026-10-20续开发已收敛A/B合同，并实现C/D本地手工闭环。下列§0–13保留历史交接审计，不代表当前待办。

## 0. 历史交接摘要

| 项 | 值 |
| --- | --- |
| 交接日期 / agent | 2026-10-20 / 临时代班（从其他 agents 接手） |
| 工作分支 / 基线提交 | `main` / `435140f`（v1.1.0 集成 R1 与 R2 起步文档） |
| 本轮提交 | `dd807cf`（本地 `main`，**未推送**）；交接记录提交见 `git log -2` |
| 已完成 | **R2-A 后端初版**（候选目录、稳定 ID、Evidence 来源/状态）+ **R2-B 后端初版**（两模型最小闭环、组合存储、自包含 HTML 导出） |
| 未完成 | R2-C 前端编辑器与页面级预览、R2-D 余下 6 种尚未接入的 Block 类型、结构3D渲染与旧 key 兼容映射 |
| 实际运行测试 | 新增 26 项（13 + 13）全绿；既有 194 项回归全绿（见 §9） |
| 部署/推送 | 均未执行；生产 `vasp-manager.service` 未重启，`data/` 未改 |
| 下一条可执行任务 | R2-C：`ReportCompositionEditor` 接现有组件 + 用同一份冻结证据做页面预览 |

**一句话**：R2 现在有一个可运行、可测试、权限与版本都收紧的**后端闭环**——能列出全部授权任务的 14 类候选、按稳定 ID 解析并冻结 Evidence、保存/重排/改名/隐藏/软删除组合、导出不依赖外部资源的 HTML；前端页面、剩余6种Block解析/渲染和结构3D仍未接入。

---

## 1. 为什么是这个顺序

`R2-report-blocks.md` §4 要求从 R2-A 开始、R2-B 紧接着做最小闭环，不要等 14 类全写完才接 UI。
本轮严格按此执行：先证明"候选能覆盖超出 6 条上限的任务、状态不误判、ID 稳定"，再证明"两条能量证据能被两个块共用、重排改名不换身份、版本变化要显式刷新"。

没有做的事（避免不必要复杂度）：

- 没有新建数据库、没有迁移 `report.json`、没有改完整报告的 `report_store` 索引与清理规则；
- 没有把 Block 硬塞进旧报告 schema（旧报告仍 1.2.0，新组合独立 `r2.1.0`）；
- 没有接 AI 自动编排，没有改巡检频率/回传、任务状态、输入文件或远端目录；
- 没有调用 `build_report()`（避免集群快照/SSH 与 6 条上限）。

---

## 2. 实际合同（与设计稿的落地差异）

### 2.1 稳定 ID

```text
block_id   = "blk_" + sha256("block|{project_id}|{type}|{task_id}|{group_id}|{variant}")[:20]
evidence_id= "ev_"  + sha256("evidence|{project_id}|{kind}|{task_id}|{group_id}")[:20]
文本块     = "blk_txt_" + uuid4().hex        # 用户创建，不参与确定性推导
```

- 不含标题、能量值、conN 编号、图表序号；改标题/重排/隐藏都不换 ID（测试覆盖）。
- 同名任务（两个模型都叫 `Model04`）按 `task_id` 区分（测试覆盖）。
- 保存组合时后端**重算** `block_id` 并与提交值比对，伪造/借用别人的 ID 直接 400（测试覆盖）。

### 2.2 Evidence 版本

```text
version = "sha256:" + sha256({kind, payload, provenance[task_id,directory,attempt,archive,local_files]})[:32]
```

- `payload_version` 外层排除 `observed_at` / `parsed_at`；现有测试证明 energy 证据不随采集时间变。但 task.fact 的 payload 仍含巡检时间与运行时长，接回时复现仅改 checked_at 即改版本，见 §13，不能把这一保证推广到全部证据。
- `payload` 只存一份；Block 只有 `source_refs=[{evidence_id, version}]`。
- 同一任务的 `energy_force` 与 `convergence_curve` 共用同一条 `task.energy` 证据（测试覆盖）。
- 保存时版本不一致 → `409 evidence_stale`，必须显式 `refresh_evidence: true` 才接受；导出只用组合里**冻结**的版本，不重新解析。

### 2.3 四类状态分开记（未合并）

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `availability` | `available` / `missing` / `unparsed` / `unknown` | "有没有数据 / 有没有解析"，与"没展示"无关 |
| `validation` | `PASS` / `FAIL` / `WARNING` / `NOT_TESTED` / `UNKNOWN` + `items[]` | 没有规则就 NOT_TESTED；未收敛是 FAIL；拿不到结论是 UNKNOWN，绝不默认 PASS |
| `freshness` | `fresh` / `stale` / `unknown` + `basis` | 阈值 24h，附"最近巡检时间 + 距今小时数" |
| `full_report_visibility` | `shown` / `omitted_limit` / `omitted_unconverged` | 与完整报告 6 条上限、未收敛过滤对齐 |

`unparsed` 与 `missing` 的区别是本轮的重点之一：**有 OUTCAR 但没有巡检归档**判 `unparsed`（"存在但未解析"），只有真的什么都没有才 `missing`。

### 2.4 Composition

```text
composition_id, schema_version="r2.1.0", project_id/name, title,
revision（乐观锁）, created_at/updated_at,
blocks[]（有序，含 block_id/type/title/renderer/options/source_refs/data_status/validation_status/text）,
evidence{}（evidence_id → 冻结的完整 Evidence）,
groups[]（group_id/title/block_ids/collapsed）,
hidden_block_ids[], deleted_block_ids[]（软删除，可恢复）
```

- 落盘：`data/reports/compositions/<项目名>/cmp_<12hex>.json`，与 `report_store` 的 `index.json` / 单份清理**完全隔离**（测试断言不写 `index.json`）。
- 上限：单组合 40 块、单项目 50 份、文本 4000 字、标题 200 字。
- 元素软删除通过 `deleted_block_ids`，清空相应ID可恢复。整份组合 DELETE 则写 `deleted_revision` 并保留文件，但当前没有恢复API，且PUT拒绝已删除组合；两种删除不能混为一谈。

---

## 3. 新增文件

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `backend/report_blocks.py` | 801 | R2-A：类型注册表、稳定 ID、候选目录、Evidence 解析（fact/params/energy/structure/comparison/method）、状态与来源适配、选项白名单 |
| `backend/report_compositions.py` | 555 | R2-B：组合校验与存储、乐观锁、版本冻结/刷新、软删除、自包含 HTML 渲染 |
| `backend/routers/report_compositions.py` | 250 | 9 个路由：schema / candidates / evidence / 组合 CRUD / export.html，全部按项目归属校验 |
| `tests/r2_fixtures.py` | 185 | 隔离夹具：10 个 OPT 任务（含未收敛、有文件未解析、完全无数据、同名任务、辅助 conN）、巡检归档、本地镜像文件 |
| `tests/test_report_blocks.py` | 194 | R2-A 13 项 |
| `tests/test_report_compositions.py` | 321 | R2-B 13 项 |
| `agent-upgrade/R2-blocks-implementation.md` | 本文件 | 摘要 + 详细改动，供后续交接 |

## 4. 修改文件

| 文件 | 改动 |
| --- | --- |
| `backend/main.py` | 导入并注册 `report_compositions` 路由（`/api/reports/blocks/...`），其余不变 |

> 没有改 `report_builder.py` / `report_store.py` / `report_export.py` / 前端：R2-A/B 只读复用它们，导出只调用 `report_export.markdown_to_html` 与 `report_charts.energy_force_chart`。

## 5. 复用的旧代码（没有重写）

| 复用点 | 用途 |
| --- | --- |
| `report_builder._task_facts()` / `_task_category()` / `_submit_times()` / `MAX_STRUCTURE_TASKS` / `STATUS_DONE` | 任务事实、类别与完整报告 6 条上限口径（同一份数据，不另造一套） |
| `checks_store.merged_results(force=)` | 巡检归档合并（30s 缓存，测试用 `force=True`） |
| `task_paths.task_files_dir()` / `is_auxiliary_task()` | 本地镜像文件存在性、辅助任务（conN/差分分块）排除 |
| `cif_convert.read_or_convert_cif()` | 结构块 CIF（只在解析该块时读） |
| `report_charts.energy_force_chart()` | 曲线 SVG（组合导出与完整报告同款） |
| `report_export.markdown_to_html()` | 文本块的安全 Markdown（R1 已加固转义/链接协议） |
| `permissions.ensure_project_owner()` | 全部接口的项目归属校验 |
| `envelope.ok/fail` + `storage.load_db` | 与既有路由一致的响应信封与数据源 |

## 6. 接口（`/api/reports/blocks`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/schema` | 14 类元素 → 渲染器/证据种类/是否已接入 + 上限 |
| GET | `/{project_ref}/candidates?refresh=false` | 全部授权任务的轻量候选（`project_ref` = project_id 或项目名） |
| POST | `/{project_ref}/evidence` | `{type, task_id?, group_id?}` → 一条 Evidence（不落盘） |
| GET | `/{project_ref}/compositions` | 组合列表（不含已软删除） |
| POST | `/{project_ref}/compositions` | 新建：`{title, blocks[], groups?, hidden_block_ids?, deleted_block_ids?}` |
| GET | `/{project_ref}/compositions/{id}` | 组合详情（含冻结证据） |
| PUT | `/{project_ref}/compositions/{id}` | 整体替换（`expected_revision` 乐观锁） |
| DELETE | `/{project_ref}/compositions/{id}` | 软删除 |
| GET | `/{project_ref}/compositions/{id}/export.html?download=&print=` | 自包含 HTML（内联 SVG/表格，无外部资源） |

错误约定：

| 状态码 | `data.code` | 场景 |
| --- | --- | --- |
| 400 | — | 未知类型 / 伪造 block_id / 选项超白名单 / 文本超长 / 重复块 |
| 403 | — | 非项目 owner 且非 admin（全局 `PermissionDenied` 处理器） |
| 404 | — | 项目/组合/任务不存在 |
| 409 | `revision_conflict` | 提交的 `expected_revision` 落后 |
| 409 | `evidence_stale` | 证据版本变化，需 `refresh_evidence: true`（`changes` 列出 block/evidence/新旧版本） |

## 7. 关键实现细节（供下一位改代码时避坑）

1. **不要调用 `build_report()`**：它会取 `cluster_snapshot()`（SSH）并按 6 条上限裁剪。候选只用 `_task_facts` + `merged_results`。
2. **`_local_files()` 只 stat 不解析**：`paths.local_root()` 依赖 `data/config/*.json`；测试里必须先 `config.ensure_data_dirs()`，否则会静默返回空文件列表（本轮踩过）。
3. **版本摘要必须排除时间戳**：`observed_at`/`parsed_at` 进摘要会导致"每次刷新都变版本"，组合永远 stale。
4. **`_payload_energy` 的能量取任务记录的 `last_energy`，力取巡检归档的 `force_max`**：只改归档能量不会改 payload（这是现有数据口径，不要在 R2 里另立一套）。
5. **导出不重新解析**：`render_html(doc)` 只读 `doc["evidence"]`；任何"导出时再查一次数据"的改动都会破坏"预览=导出"的验收。
6. **文本块导出前过 `_strip_images()`**：`markdown_to_html` 对非 `charts/`/`images/` 的图片会输出外链 `<img>`；组合必须自包含，所以直接去掉图片语法（保留 alt 文字）。
7. **`app.routes` 在本地 FastAPI 版本里包含 `_IncludedRouter` 包装**，不要用 `r.path` 断言路由数量；直接检查 `router.router.routes`。
8. **辅助任务不进候选**：conN / 差分分块跟随主任务（与完整报告口径一致）；`task_opt_01_con1` 已用测试固定。

## 8. 数据与兼容

- 新目录 `data/reports/compositions/`，不在 Git 中（`data/` 已忽略）、不参与 `report_store` 的"每项目一份"清理。
- 旧 `report.json` / `report.md` / notes / edits / HTML / 隐藏 key 完全不受影响（本轮未改这些代码路径）。
- 旧报告 schema 仍 `1.2.0`；组合用自己的 `r2.1.0`，只共享元素类型名，不复用旧文档结构。
- 组合导出是独立 HTML，不替换原 `/api/reports/project/{id}/export.html`。

## 9. 测试（真实运行的命令与结果）

```bash
cd /home/zouyuxi/projects/vasp-manager

# R2 新增两套（必须独立进程：数据目录在 import 前由环境变量固定）
.venv/bin/python -m unittest discover -s tests -p 'test_report_blocks.py' -q
# Ran 13 tests in 0.046s  OK
.venv/bin/python -m unittest discover -s tests -p 'test_report_compositions.py' -q
# Ran 13 tests in 0.306s  OK

# 既有回归
.venv/bin/python -m unittest discover -s tests -q
# Ran 53 tests in 3.221s  OK (skipped=7)   ← 7 个 = 需独立进程的套件容器
# 逐套件：test_automation_baseline 10 / test_agent_gateway 38 / test_opt_loop 47 /
#         test_parameter_evidence 26 / test_report_ai_notes 20 —— 全部 OK
```

合计：**194 项既有 + 26 项新增 = 220 项通过**（7 个 skip 是同一批套件在共享进程里的容器，不是未覆盖）。

R2-A 覆盖点：10 个 OPT 任务全部进候选（第 7–10 个标 `omitted_limit`）、未收敛保留并 FAIL、有文件无归档 `unparsed`、无数据 `missing`+UNKNOWN、同名任务 ID 不撞、目录确定性、辅助任务排除、对照表只统计有能量的任务、版本随数据变但不随观测时间变、未接入类型拒绝而非伪造、选项白名单。

R2-B 覆盖点：两模型 7 块闭环（证据 5 条、2 块共用 1 条）、重排+改名+隐藏后 ID 不变、软删除与恢复、revision 冲突、证据变化需显式刷新、伪造 block_id 拒绝、未知类型/非法选项/超长文本拒绝、未接入类型拒绝、HTML 自包含且转义脚本、隐藏块不进导出、存储与完整报告索引隔离、列表/删除、路由级归属校验。

未覆盖（明确留给 R2-C/D）：前端交互与浏览器回归、真实 HTTP/登录会话下的接口联通、NEB/自由能/PDOS/Bader/功函数/差分电荷的解析与渲染、结构 3D 交互、PDF 打印回归、旧隐藏 key 到 block_id 的映射、多实例并发写。

## 10. 安全与兼容检查

- 权限：所有 R2 接口在路由层 `ensure_project_owner`（admin 全可见）；组合读取/导出同样校验，不靠前端隐藏。
- 伪造：后端重算 `block_id`/`evidence_id`，拒绝借用；`options` 只允 5 个白名单键且类型校验；`renderer` 由服务端按类型查表，不接受客户端传组件名。
- XSS：文本走 `markdown_to_html`（`html.escape` 先行，链接限协议），导出前剥离图片语法；标题/表格单元格全部 `html.escape`。
- 自包含：导出不含外部 `src`/`href` 资源，曲线内联 SVG，证据版本表内联。
- 无副作用：不写任务库、不改巡检、不连 SSH、不生成完整报告；测试全部在临时 `VASP_WEB_DATA_DIR`。
- 兼容：`main.py` 只加一行注册；未改旧路由、旧 schema、旧导出与前端。

## 11. 提交与部署状态（以 Git 日志为准）

- 代码/测试/文档提交：`dd807cf`「R2-A/B: 报告元素候选目录、证据冻结与组合闭环（后端，未部署）」，`main` 上**本地提交，未 push**。
- 本轮改动：§3/§4 列出的 6 个代码/测试文件 + 3 个文档（本文件、`R2-report-blocks.md` 状态回填、`PROGRESS.md` §14、`AGENTS.md` 当前任务、`API.md` R2 章节）。
- **未部署、未推送**：未重启 `vasp-manager.service`，未替换 `dist/`，未改生产 `data/`；前端无改动所以不涉及重新构建。
- 未纳入提交：用户原有的 `待办.md`、`问题.md` 删除保持未暂存，未 `git add -A`。

## 12. 下一条可执行任务（R2-C）

1. 前端：`src/components/reports/ReportCompositionEditor.tsx` + `BlockRenderer.tsx`，接 `/api/reports/blocks/*`；列表式编辑（添加/删除/隐藏/上下移/分组/改标题/恢复），不做拖拽/画布。
2. 页面：在现有 Report 页加入口，保留完整报告原路径；组合预览用**同一份** `doc.evidence` 渲染，不允许预览时再取当前数据。
3. 导出：HTML 复用本轮 `render_html`；PDF 走浏览器打印（`?print=1`），补 Playwright 回归。
4. 浏览器验收：两个模型 → 两个能量 → 参数表 → 曲线 → 自定义顺序 → 加文字 → 导出 HTML/PDF；重排/改名/隐藏/恢复后身份不乱。
5. 之后 R2-D：按 §1 的 14 类补齐解析与渲染（NEB/自由能、PDOS/Bader/功函数/差分、结构 3D），再做旧隐藏 key 的兼容映射与完整报告回归。

## 13. 本助手接回核对（2026-10-20，以源码为准）

已读取AGENTS/任务合同/本实现记录及3个后端模块、路由与测试；接手HEAD `8601bab`，业务提交 `dd807cf`，R1基线 `435140f`。本轮是接手与文档核对，不开始R2-C、不修改业务代码、不推送/部署。生产PID仍2409520，启动2026-10-19 23:56:56，运行R1。

本轮实际重跑：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_report_blocks.py' -q
# Ran 13 tests，OK
.venv/bin/python -m unittest discover -s tests -p 'test_report_compositions.py' -q
# Ran 13 tests，OK
```

此前220项回归为上一位执行记录，本轮仅重跑上述26项。另用临时DATA_DIR探针核对注册表计数、未接入类型路由及task.summary版本变化，未读取/修改生产科研数据。

### 需要先收敛的合同缺口（本轮仅记录，均未修复）

1. **类型数量与实际交付**：14种Block中8种resolvable（含文本），对应6种科学Evidence；未接入的是6种Block，而不是此前文档的“10类”。结构CIF可冻结，但HTML只显示占位说明，3D未实现。A/B是后端初版，完整R2人工验收待C/D。
2. **参数对照与分组呈现未完成**：`project.comparison`目前是整个项目的能量/力表，无两个选定模型的参数对照；`task.params`只是单任务INCAR表，导出未展示其KPOINTS。groups已校验/存储，但`render_html()`没有按groups组织显示。不能把两个参数表并列当成用户要求的参数对照表已经验收。
3. **版本/编辑冲突合同仍可绕过**：`save()`允许缺省expected_revision，`build_composition()`缺省旧source_refs时跳过版本比较；保存总会重新解析。R2-C必须保留revision与引用，后续应明确“只编辑展示保留冻结证据”与“显式刷新科研数据”的合同。task.fact payload还含inspection_checked_at/runtime_hours；隔离探针已复现只改checked_at即改summary版本，现有energy时间稳定测试未覆盖此情况。
4. **来源与科学状态不能过度解释**：provenance当前只有通用checks说明/目录/文件名，`hash=None, hash_scope=payload_only`，不是具体归档ID或原文件完整指纹；结构来自当前本地镜像，不能仅因有CIF就证明属于巡检目录/attempt。局部PASS（如有INCAR、力收敛）也不等于参数完整、数值精度或科学结论可信。曲线0.02是写死的默认参考，不是已核对的本次EDIFFG。
5. **时效/完整报告可见性待统一**：R2写死24h，和既有AI证据链“参与自动巡检的任务4h”不同；不能用于自动干预判断。`_opt_indices/_visibility`按全部独立OPT顺序计数、archived直接shown，未按原报告“有history且符合展示条件才占6个名额”精确复现；也尚未映射edits隐藏。
6. **路由与恢复边界**：POST `/evidence`没捕获UnsupportedEvidence，隔离调用实测500；组合保存捕获并转ValueError返回400。整份组合DELETE虽保留文件，但没有恢复入口，PUT拒绝已删除组合；已通过的恢复测试是元素deleted_block_ids恢复。接UI前区分并补契约/真实HTTP回归。

下一步建议先给上述来源/版本/选定模型参数对照/错误返回补针对性隔离测试并收敛最小后端合同，再接R2-C（编辑器与同一冻结证据预览）。这不会重做既有A/B；未授权时不部署、不推送，不接AI自动编排。

本轮同步修正README、process、PROGRESS顶部旧“无业务实现”摘要及API/本文件的数量/保证表述；文档改动留工作区，未提交。两份用户文档删除保持原样。后续接手先核对git状态，再更新本节/PROGRESS，不依赖聊天记录。


## 14. 本助手续开发交付（2026-10-20，当前权威状态）

用户“你继续开发吧”授权继续R2。工作基线8601bab（A/B代码dd807cf），本轮业务提交以Git日志中“R2: complete manual report composition…”为准；未部署、未推送。应用仍1.1.0，完整报告schema1.2.0，组合schema r2.1.0。

### 已实现入口与文件

- 智能报告页选项目→「专题报告」，`ReportCompositionEditor.tsx/.css`、`src/api/reportCompositions.ts`；列表式添加已有元素、筛选多个模型、2–12模型参数对照、人工文字、排序、分组/改分组名、改标题、隐藏、删除和恢复。切换报告/离开有未保存提示；导出前必须保存，预览过期有标记。
- 同一后端 `report_compositions.render_html()` 同时用于草稿预览、下载和PDF；前端iframe沙箱，不造第二套React图表渲染器，也不让React/原生widget争用同一DOM子树。预览不会写盘，服务端不采信客户端evidence payload/renderer。
- `report_compositions.py`：旧展示编辑使用服务器冻结证据，明示刷新才重读科学数据；PUT必带整数expected_revision，冲突409。新增 `/preview` 和 `/{id}/check`，后者只比数据不更新报告。`ApiError`保留结构化409数据，原request调用保持兼容。
- `project.comparison + task_ids`按所选任务集生成稳定variant，引用多条task.params，与单任务参数块共享Evidence；对照含完整快照INCAR/KPOINTS/来源。旧无task_ids的项目能量表保持可读。临时client_id在服务端统一映射分组/隐藏/删除引用，预览规范化后身份不乱。
- `report_block_science.py`：只读本地Adapter，复用PDOS/Bader/功函数解析、结构转换、差分PNG、report_panels自由能/NEB SVG；14类Block均已可解析/保存（文本不需要科学Evidence，共12种科学Evidence）。PDOS完整view和静态SVG一并冻结；结构3D、PDOS/功函数复用原runtime，实例键使用block_id，保留旧task_id协议；导出不调用interactive_payload重读当前PDOS。
- 结构转CIF只写系统临时目录，不改源模型/历史CIF缓存；Bader仅使用已有分析快照CIF，缺失不回填/不拿当前镜像冒充。没有现成PNG则PDF保留数值和说明，不伪造结构图。
- `report_blocks.py`：观测时间/运行时长不污染基本信息版本；4小时阈值只适用参与自动巡检的任务，排除项/未来时间unknown；OPT6条限制按有history且收敛或归档的实际条件计数。电子任务列出可共存的四种分析产物，不只按subtype漏掉其他结果。
- 来源记录匹配归档/observation_id、任务、真实目录/attempt、解析时间，参数快照摘要及可读本地文件SHA256/hash_scope。明确merged字段可能跨观测，缺来源不声称已验证。力阈值仅在快照负EDIFFG可取时显示；原完整报告的默认曲线行为保持。
- `reportHidden.ts` +候选legacy_hidden_keys支持明确沿用旧隐藏选择，保存新block_id；图序号和同名歧义不自动映射。旧report.json/md/notes/edits、原HTML/PDF和R1界面路径保留，无格式迁移。导出不显示隐藏/删除块独占的来源附录数据。

### 实际验证

独立临时DATA_DIR/AI密钥，无真实模型/SSH/HPC；API测试复用真实认证中间件、临时用户/session及项目归属。前端构建仅/tmp，运行时浏览器夹具自行构建/tmp/runtime.js。

| 命令/套件 | 实际结果 |
| --- | --- |
| unittest discover -s tests -q | Ran53，OK；8个隔离套件占位Skip，均另起进程执行如下 |
| test_automation_baseline.py / test_agent_gateway.py / test_opt_loop.py | 10 / 38 / 47，全部OK |
| test_parameter_evidence.py / test_report_ai_notes.py | 26 / 20，全部OK |
| test_report_blocks.py / test_report_compositions.py / test_report_block_science.py | 14 / 18 / 8，全部OK |
| test_report_presentation.py（另跑） | 6，OK（也包含在普通discover中，不重复计数） |
| npm run typecheck | 通过 |
| npx vite build --outDir /tmp/vasp-r2-final-build | 通过；仅已有bundle大小建议 |
| tests/browser/report-compositions.cjs（Playwright Edge） | 真实编辑器+隔离Python API：两模型/两个能量/参数对照/曲线/文字、分组重排隐藏删除恢复、快照保留/显式刷新/并发冲突、XSS、HTML下载与实际PDF、离线PDOS/功函数runtime、结构宿主/安全WebGL降级、旧隐藏映射，PASS |
| tests/browser/report-ai-notes.cjs | 原注解采用/编辑/恢复/批量部分失败/取消/开关/无模型、完整报告重新生成/切换、XSS及HTML/PDF，PASS；esbuild夹具增加输出路径以支持新组件CSS导入 |
| git diff --check | 通过 |

### 限制与下一步

- 这是本地夹具/Mock验收，未对真实科研项目操作，未上线。全套检查有原有Python3.14弃用提醒及Vite chunk大小提醒，不是功能失败。
- 不执行新的PDOS/Bader/功函数/差分计算。原始文件存在但没有本地产物、损坏/不完整产物会标unparsed并解释；不把“无图”当作没有计算。当前本地结构与历史观测的一致性未自动证明，验证保持NOT_TESTED/UNKNOWN，不宣称科学结论已证实。
- 组合3D依赖WebGL/本地报告runtime；缺PNG时PDF不含交互3D画面。部署必须按原构建流程包含report-interactive.js和3Dmol；本轮没有覆盖生产dist。
- 分组为单列标题分段，依全局元素顺序展示；同组不连续时重复组标题，不暗中改变顺序。不做拖拽/多列/自动AI编排；compact/digits等旧预留options仍保留，UI只提供本阶段明确功能。
- 旧隐藏图序号/重复任务名不猜测映射，请人工选择；旧完整报告本身仍按原key读取。整份组合DELETE保留文件但没有恢复API/UI，本阶段恢复是元素恢复，UI不提供整份删除按钮。
- 文件与目录权限边界按现有授权项目；拒绝越项目/符号链接和>24MiB单个读取文件。进程内锁沿用单后端writer假设，不支持多进程共享写。
- 下一条动作：用户若要求部署，先按process生产流程备份、隔离候选检查并同时构建主前端/报告运行时，再重启唯一服务、验证完整报告/R1/专题报告；未授权不自行部署/推送、不进入下一阶段。

生产只读核对：vasp-manager.service active，PID2409520，启动仍2026-10-19 23:56:56 CST。用户两处文档删除未纳入本轮，data/配置/密钥/dist/备份不进Git。
