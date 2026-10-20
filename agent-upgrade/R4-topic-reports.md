# R4：AI工作台自然语言专题科研报告

2026-10-20完成隔离验收；后经用户明确授权，于17:37随v1.1.4与吸附能增量一起部署。发布/推送记录见PROGRESS §25，完成后停止。

R3已按用户明确确认的v1.1.3发布：main `918030e` 与 `v1.1.3` 已推送，远端标签解引用同一提交；生产单writer PID3068101。R4在 `/home/zouyuxi/projects/vasp-manager-r4`、分支 `codex/r4-topic-reports` 独立工作树开发；仅复用依赖，不接生产DATA_DIR/AI密钥，初轮保持1.1.3；本次合并增量发布v1.1.4，不移动旧标签。

## 已实现流程与使用

在AI工作台原有项目会话、启用工作区并选择自己的模型连接后，可输入“比较 LMR 和 LIC@LMR 的氧空位形成能，生成一份科研报告”。服务端和受限工具依次执行：

1. 模型解析目标/性质，默认当前项目；可查授权项目并在最多4项目内检索。
2. `prepare_topic_report`：只读任务/原始巡检/已有科学分析，唯一结构关系才自动绑定，R3先检查和固定Python计算，随后枚举/冻结相关R2 ReportBlock。没有调用完整项目报告构建器或剪裁Markdown。
3. `plan_topic_report`：模型选择已有block_id及理由、章节、顺序、必要/补充标记。服务端检查所有者/逐项目权限、实际冻结目录、可用性、性质相关性；结构镜像仅补充证据。默认8章节允许调整，空章节不渲染。
4. `write_topic_draft`：检查/计划完成后才组织AI文字；解释与假设分开，数字必须引用服务端事实。缺数据生成精确需求说明，不用虚构数值补齐。
5. `save_topic_report`：独立topic ID保存，对话侧栏“专题报告”可重新打开。原project_full及其他专题不受影响。

当前5种科学配方复用R3：中性单O空位、相对能量、简单吸附能、已有NEB能垒、功函数差。另有 `dos.comparison`，仅已有DOS/PDOS可视化/费米能级/计算条件，不计算未注册的DOS派生指标。其他性质UNSUPPORTED，不临时生成公式。

模型名仅产生候选，单O关系来自POSCAR证据；同名多任务或多个位点保留候选。编辑器可选择明确位点/已有人工氧参考，DOS多任务也可明确绑定。选择更新生成新证据版本并重置当前文字/计划，旧版本可经GET revision读取；可在原会话继续组织报告。不能从名称直接认定缺陷，不能随机选一个位置。

氧参考仅复用相同任务绑定和理论设置的已有R3人工参考记录；唯一且由当前用户明确设置时自动使用，多条需确认。没有氧参考不能给绝对形成能；共同参考仅作为差值成立的待确认条件，固定保留消去项、适用条件、未验证项。不允许模型设置mu_O数值。

## 数据、编辑与保存

`topic.1.0.0`文档位于 `data/reports/topics/<owner_hash>/topic_<uuid>.json`，0600文件/0700目录、原子写、文件锁及expected_revision；历史位于同目录history。记录原始用户问题（聊天运行提供，模型不能改写）、项目/性质、时间、R3输入原始观测/公式版本/单位/参考态/数值/检查、R2 Evidence版本、元素计划、AI原文和用户编辑文本。

编辑器支持删除/恢复、隐藏/显示、添加相关冻结元素与文字、顺序/章节/标题调整、文字编辑、原连接单段重生成、保存预览、HTML下载与浏览器PDF打印。预览/导出使用同一已保存内容，未保存修改时禁用导出。AI文字与用户编辑分开保存，PUT拒绝科学数据/renderer/组件字段。

`[[F01]]`由Python展开为冻结值、单位、验证状态；`[F01]`仅引用来源。文字编辑可用事实选择器插入数值；不接受自行填数字、未知引用、替代公式或无效数据引用。原始无效能量可在来源表追溯，不能作为科学段落数值结论。服务端固定保留科学局限页脚，隐藏元素不能抹掉条件。

R2原有能量字段来自任务库，专题使用只读适配视图把能量/目录/作业/状态绑定到**所选的同一次原始观测**，避免混用live任务与不同conN的参数。显式旧conN选择也遵循同一来源；同任务不同观测不能在一个专题内复用同一个R2 block_id。没有观测时不回退任务能量补造结果。

普通读取、编辑和导出均保留证据；新巡检、任务/输入身份变化、4小时时效以及R2本地分析文件版本变化只提示可能过期，不自动刷新旧数值。段落模型失败/格式无效/修订冲突均保留原草案；重生成再次鉴权并校验revision后才原子保存。

## 安全和成本

沿用原人工登录与项目权限；每次访问重新校验报告所有者和全部关联项目，Agent不能用topic接口。专题工具只可访问当前对话报告；跨项目先逐项鉴权。没有新增SSH/Shell、输入修改、结构生成或HPC提交，补算只出建议。原工作区既有固定范围只读补证能力保持原规则。

R2白名单渲染/安全Markdown、独立iframe和导出CSP复用，模型无法写任意组件或外链图片/XSS。模型输出与原始科学事实分离；假设标注，用户预期不作事实。模型不能替代R3计算和结果校验。

预算：最多4项目/4目标/24任务/24候选，冻结候选总6MiB、单文档12MiB、40展示元素、单段4000字符/每批10段、每用户200份；工具摘要截断大量候选/缺口且保留标记，继承原6轮工具/12次调用/90k字符预算和模型超时。单段重生成每用户1个、全局2个并发。

## 代码映射

| 文件 | 职责与复用 |
| --- | --- |
| backend/topic_discovery.py | 本地有界候选/关系识别；R3 evaluate与R2 list_candidates/build_composition |
| backend/topic_reports.py | 独立文档/历史、计划校验、事实引用、展示编辑、冻结导出、新鲜度和重生成 |
| backend/topic_tools.py | 原AI循环6个专题工具及可信运行问题绑定 |
| backend/routers/topic_reports.py | 原认证之下的topic接口，见API.md |
| backend/ai_workspace.py、ai_chat_service.py、main.py | 原工具循环/运行ID/提示与路由集成 |
| src/api/topicReports.ts、src/components/ai/TopicReportLinks.tsx | 原对话报告目录与API |
| src/components/reports/TopicReportEditor.tsx、src/pages/AI.tsx | 复用工作台及R2样式的专题编辑/导出入口 |
| tests/test_topic_reports.py、test_topic_http.py、r4_server.py、browser/topic-reports.cjs | 独立临时数据/私钥/模型HTTP夹具及真实React浏览器验收 |

## 初轮实际验证（d5edf39）

318项Python通过，无skip充数：R4单元17、真实HTTP/SSE8；R3 35；R2元素14/科学8/组合18/AI注解20/呈现6；AI聊天22/巡检5；参数26/保留8；网关58/OPT47/基线10/力3/结构同步13。每个隔离套件用独立进程运行。首次R2科学回归因工作树缺报告交互runtime失败，补齐隔离构建依赖后8项全部通过。

执行命令：`.venv/bin/python tests/test_topic_reports.py`、`tests/test_topic_http.py`；其余test_*.py逐套独立运行，网关使用 `.venv/bin/python -m unittest discover -s tests -p test_agent_gateway.py`（该文件没有直接执行入口）。

7个验收案例均覆盖单元与真实聊天HTTP/SSE：合成4能量/人工mu下3、4及B−A=1eV；缺参考仅条件差值；多位点不选；DOS仅相关PDOS/参数与能量参考；无数据需求报告；删除/排序/编辑/导出一致；同项目同会话3份独立专题、完整报告文件不变。另覆盖权限撤销/跨项目/私有所有权、伪造元素/数值/公式、XSS、并发冲突、模型503及重生成失败保留、快照更新、新旧conN无混用、预算和未知性质。

`npm run typecheck`、`npx vite build --outDir /tmp/vasp-r4-build` 及esbuild报告runtime通过；已有大chunk提示保留。工作树dist仅链接/tmp构建供测试，不覆盖生产dist。

真实浏览器3套通过：

- `node tests/browser/topic-reports.cjs`：原AI React页面自然语言发送/SSE保存、正确冻结值、编辑/删除/排序/重开、HTML内容与PDF文件、私有连接段落重生成、多位点显式选择、DOS交互widget挂载；零页面错误。
- `PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/report-compositions.cjs`：既有R2完整编辑/导出/离线PDOS与功函数回归通过。
- `node tests/browser/scientific-properties.cjs`：既有R3精确绑定/缺参考/差值/绝对值/冻结导出回归通过。

所有新HTTP/浏览器验证均使用本地确定性Mock模型、临时项目/巡检/本地分析/加密凭据目录，无真实模型请求/生产科研写入或HPC访问。3/4/差1eV是合成夹具结果，不能声称真实LMR科学结论。

## 当前边界与停止点

满足本阶段7个验收案例；R4已随v1.1.4发布。本次吸附能增量与330项回归见adsorption-analysis.md和PROGRESS §25。基于既有项目会话工作区，不向通用聊天自动附加全部项目。首版科学支持沿用R3解析/结构顺序/自动k网格等边界；旧档案缺证需补齐已有巡检/分析，不能用当前镜像冒充历史。DOS是可视化对比，没有新增能隙/积分算法。PDF使用浏览器打印/保存，非独立服务器排版引擎。

真实外部模型多语言/工具兼容性与真实项目科研结果尚未验收；API模型失败已验证，不能据Mock推断科学模型充分。用户可编辑解释文字，语义机制解释仍需科研人员复核，所有未验证条件固定保留。没有开启后续自主阶段或自动补算。用户原有两份文档删除留在生产工作树，未夹带。完成后停止。
