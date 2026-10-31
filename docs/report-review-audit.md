# 完整报告批注：调用链调查、定向修复及验收

日期：2026-10-31。基线提交 `0eca689`；开发分支 `codex/report-review-todo-20261031`，修复提交 `fc507d7` 已合入 main 并部署。用户要求完成当前 `待办.md` 的两项事项；工作区原有 AGENTS、待办修改和测试文件/问题文档删除未夹带提交。

## 调查结论

“让AI处理”使用的是 `backend/report_review.py:16` 的局部编辑 PROMPT，**不是** `report_ai_notes.py:22` 的科研审查/Results/Discussion PROMPT。原实现没有间接触发完整科研分析或重写报告的调用；不能因 import 了整个模块而判断旧提示词在执行。

问题的根因有四个：

1. `Report.tsx` 原先将 `aiNotesEnabled` 放入 ReportAIProvider 的 React key，开关变化会重建整棵报告 DOM；Report 本身没有重建，挂载图表/3D的 effect 依赖不变，portal仍指向已移除的宿主，故屏幕只剩旧静态三视图。
2. 批注 PROMPT 和后端 calculate 白名单都只允许 relative_energy / adsorption.estimate，尽管 R3 注册表已经有 oxygen_vacancy.neutral_single；氧空位请求因此被导向“未支持/缺少资料”的文字答复。
3. 原 calculate 虽保存 calculations，但真正展示的是写入 texts 的普通 Markdown；没有独立的公式/结果元素身份，无法可靠局部编辑卡片。
4. 批注上下文夹带项目目标、预期、已有科研注解，原文字动作也只支持“补充解释”。这不会执行旧审查 Prompt，但容易让模型将一次计算/排版请求扩展成科研分析。旧回复允许8000字符，也未强制简短执行确认。Unicode `−` 未被参考能量解析器识别，会把负号丢掉。

## 实际调用链

下列行号对应本次实现；历史行为由基线源码核对。

| 节点 | 文件、函数与行号 | 上下游关系 |
|---|---|---|
| 点击按钮 | `src/components/reports/ReportReview.tsx:94`，process | 发送 action=comment、report_id、comment_id，使用选中的私人连接 |
| 前端请求 | `src/components/reports/ReportWorkContext.tsx:102`，start | POST `/api/reports/assistant/{project_id}`；带 request_id、connection_id |
| 路由 | `backend/routers/report_assistant.py:46`，start_work | actor鉴权，WorkBody校验，然后 work.start |
| 后台运行 | `backend/report_background.py:100`，start | 原 conversations/messages/runs 保存 report_job；启动原 `_generate` |
| 执行分流 | `backend/ai_chat_service.py:719`，_generate | 有 report_job 时直接 execute 并 return，不走通用聊天模型轮 |
| 批注执行 | `backend/report_background.py:297`，execute → `:285`，comment | 读取授权项目报告，传当前修订与 WorkControl.model 给 report_review.process |
| 实际提示词 | `backend/report_review.py:300`，process；`:16`，PROMPT | 一次 readonly_json_completion；输入 comment、局部正文/元素目录、冻结facts、结构组成及配对候选 |
| 模型调用 | `backend/ai_chat_service.py:519`，readonly_json_completion；`:487`，completion_payload | 连接必须属于当前用户；运行时取该连接的 model/base_url/预算/推理配置，没有硬编码模型。兼容流式 /chat/completions，拒绝工具调用、不完整JSON及截断响应 |
| 结果解析/科学运算 | `backend/report_review.py:212`，apply_actions；`backend/report_review_elements.py:85`，calculate | JSON `{reply,status,actions}`；白名单结构动作与事实绑定，固定Python计算，不执行模型公式/代码 |
| 保存 | `backend/report_review.py:300`，process；`backend/report_store.py:142`，save_review | 写入前重查权限、AI开关、来源指纹、revision、取消；整份计划验证后原子替换edits侧文件；记录history、回复、来源与状态 |
| 页面刷新 | `src/components/reports/ReportWorkContext.tsx:97` 完成监听；`src/pages/Report.tsx:912`，reloadBackgroundReport | 完成SSE后重新取报告详情，读取有效的局部修改 |
| 页面呈现 | `backend/routers/project_reports.py:178`，project_report_detail；`backend/report_review.py:119`，effective | sections写稳定挂点，structured.review_elements保存卡片；review_elements_html由共享Python渲染器生成 |
| 3D与卡片 | `src/pages/Report.tsx:430`，renderedSections；`src/utils/markdown.ts:85` 挂点解析 | 卡片使用服务端渲染HTML；原图表/3D继续原portal组件，AI开关只刷新设置，不销毁报告 |
| 导出 | `backend/routers/project_reports.py:279/:315`，Markdown/HTML；`backend/report_export.py:458`，widget_renderer_for | 同一effective文档；卡片Markdown与HTML都由report_review_elements产生，PDF打印同一HTML |

兼容接口 `POST /api/reports/project/{id}/review/process`（`project_reports.py:641`）仍直接调用相同 process，保留修订/取消语义；当前页面不走它。原AI工作台的 `report_tools.py:37` dispatch 中 process_project_report_comment 同样复用 work.comment；用户补充先由 reply_project_report_comment 保存真实用户原话，再处理。持续对话会经过原聊天工具轮，然后执行上述独立批注模型请求；按钮首次处理只调用一次批注模型。

## 科研审查和旧功能的实际职责

| 功能 | 真实执行位置 | 本次处理 |
|---|---|---|
| 项目风险/缺项规则、状态与预期对照 | report_builder.build_report → `report_builder.py:2009` evaluate_rules → `report_rules.py:96` evaluate | 活跃功能；生成完整报告时执行，批注不调用 |
| AI结果分析、可信度解释、Results/Discussion | report_background.notes → report_ai_notes.preview → `report_builder.py:1599` ai_generate_notes → `report_ai_notes.py:143` generate_text → 科研PROMPT | 活跃功能；主动生成AI注解/开启撰写的报告生成后调用，草稿须人工保存，保留 |
| 收敛、运行参数、输入输出、组成/电荷、理论兼容验证 | `property_science.py:87` normalize、`:208` compatibility、`:236` vacancy；properties.evaluate | 活跃严格科学性质入口，保留；不是批注必经门槛 |
| 初步科学性质、完整缺口和补算建议 | `properties.py:220` evaluate 的 preliminary 分支及报告输出 | 原topic/性质系统继续使用；批注仅复用相关纯计算/检查，不把整份审查塞入卡片 |
| 报告元素分析/缺失元素 | report_blocks、report_block_science、topic_discovery及各性质适配器 | 原组合/专题仍调用，不改为新平台 |
| 原单条notes/ai-preview API | project_reports.project_report_note_ai_preview | 保留兼容；src/api/reports.ts 的 generateReportNote 定义已无页面调用方，当前页面用后台入口；不是批注误调 |

report_review 单向 import report_ai_notes，实际复用其 digest、scientific_identity、project_for、共享busy锁及 service.readonly_json_completion；原版也使用 compact 压缩旧注解。report_ai_notes 不import report_review。本次移除批注上下文中无关的科研注解、项目目标和预期；保留公共模型/鉴权能力。三个不同Prompt分别承担科研写作、局部修改和后台持续对话职责，没有将它们拼接/覆盖成同一个模型请求，也没有删除仍在用的功能。

## 科学合同与数据绑定

复用 `properties.RECIPES['oxygen_vacancy.neutral_single']` 的版本、`properties.formation` Decimal运算、property_science.vacancy/compatibility、已有 CIF→POSCAR 解析和 provided_energy 单位换算。没有新公式引擎、数据库、Agent或HPC能力。

- 批注只接入 relative_energy、adsorption.estimate、中性单O空位三项。其他注册性质继续由原性质/专题入口使用；未知或未接入计算返回UNSUPPORTED及具体限制。
- 只从当前保存报告取能量和结构，不偷换最新巡检/远端结果。结构目录显示实际原子组成及单O配对候选；模型绑定角色，Python重新核对恰好少一个O。
- 中性单O形成能 `E_defect − E_pristine + μ_O`；用户明确O₂能量时 μ_O=E(O₂)/2，直接声明每O化学势时不再除2。支持原有eV/Ha/Hartree/Ry/kJ/mol换算，保留原值/单位/原话。
- 最新明确的用户氧参考优先旧引用；同一段给出互相冲突的氧参考时询问具体采用值。也可引用报告中经实际组成为O₂确认的分子记录。
- 缺必要能量/结构/参考或确认组成不符、已知带电，只阻止对应组；其他组可独立保留。弛豫后坐标不同不误判组成关系失败。电荷、位点映射、参数与收敛未知时标PRELIMINARY，不宣称通过正式科学验证。
- 保存输入事实、report/project/task、可用的job/目录/时间/参数来源、结构指纹、实际组成、检查、公式版本、用户参考及结果；负形成能保留并提醒核对。

## 结构化编辑与渲染

沿用edits.review，新增 `content[target].elements[id]`；元素type为text/calculation/formula/sources，正文只放 `@[review-element:id]`。完整报告以章节和###/####标题形成稳定模块树，原正文分段形成body元素ID；批注只能修改目标及子模块。目录同时包含原元素和新增卡片，可替换、删除、局部补充；计算卡片的替换只改标题、补充只改说明，Python数值/公式/来源不开放文本修改。

`review_elements`是有效报告的结构化数据；`render_html`和`export_markdown`共享同一元素的Markdown表示。页面从服务端收到可信的card HTML，不接受模型HTML；静态卡片无需3D运行时也能打印。原自由能结构筛选、重排、图表及隐藏图身份映射保留。

原report.json不改；edits原子提交，失败/取消/冲突不覆盖。history记录动作、模型、修订及修改前content；同批注同动作得到相同卡片ID，已完成项不调模型，显式重开也不重复插卡。旧texts/calculations继续兼容，旧计算重新处理时移除同批注旧Markdown结果，避免新旧数值同时出现。

模型成功回复由后端生成一句实际修改确认；blocked仅保留短缺口问题，拒绝长回复。聊天/批注原文保存在原系统记录中，不进入导出；用户参考原话保存在来源审计，卡片仅展示原数值、单位及“用户给定”。

## 文件修改清单

| 文件 | 原因 |
|---|---|
| backend/report_review.py | 专用编辑Prompt、结构/事实/元素上下文、局部动作、短确认、来源与修订历史、旧格式兼容 |
| backend/report_review_elements.py（新增） | 保存报告适配、已注册Python运算、单O组成检查、结构化卡片与共享渲染 |
| backend/report_export.py | 识别新增卡片挂点，直接生成可打印HTML |
| backend/routers/project_reports.py | 详情返回结构化卡片及共享HTML；Markdown展开同一卡片 |
| backend/report_tools.py | AI读取完整报告时展开卡片内容，避免只看到内部挂点 |
| src/pages/Report.tsx | 保持Provider/3D宿主，页面解析卡片挂点 |
| src/components/reports/ReportAIContext.tsx | AI开关变化刷新状态，不重建报告DOM |
| src/utils/markdown.ts、src/types/index.ts | 受信任卡片渲染回调与详情字段类型 |
| tests/test_report_review.py、tests/report_vacancy_fixture.py（新增） | 精确数值、实际组成、来源、编辑/回滚及模型调用链验证；合成结构明确与真实记录分开 |
| tests/test_report_background.py | 沿新增结构化合同核对最终正文 |
| tests/review_browser_server.py、tests/browser/report-review.cjs | 原页面隔离端到端验收、开关3D保持、三组卡片、HTML/PDF取数 |
| docs/reports.md、ANALYSIS_FEATURES.md、API.md、process.md、本审计 | 仅同步涉及的协议、规范、验收和遗留 |
| 待办.md | 仅在本地标记本轮完成，保留用户原始长需求供对照；原有未提交内容不夹带 |

没有删除业务文件；用户原有test目录文件及问题文档删除保持原状态。

## 实际数据只读演算

从 `data/reports/LiMR_InO/rpt_proj_1790442534705/report.json` 的science.opt取数，使用待办中明确给定的−8.3 eV氧参考；没有调用真实付费模型，没有修改这份报告或原计算文件。

| 体系与真实任务映射 | 完整组成 → 缺陷组成 | E_pristine (eV) | E_defect (eV) | E_f (eV) |
|---|---|---:|---:|---:|
| LMR → Ovcc_LMR | Li16Mn8O24 → Li16Mn8O23 | -325.69441924 | -316.81409898 | 4.73032026 |
| model3（LIC@LMR）→ Ovcc_LIC@LMR | Li52Mn14Cl48In8O42 → Li52Mn14Cl48In8O41 | -818.67692987 | -816.27422684 | -1.74729697 |
| model2（In₂O₃@LMR）→ Ovcc_In2O3@LMR | Li36Mn18In32O102 → Li36Mn18In32O101 | -1144.16522448 | -1136.91850842 | 3.09671606 |

同一冻结记录中各配对的组成差唯一且恰好少一个O。数值与待办预期逐位一致。电荷/位点和理论条件的正式验证不因这次算术而自动成立；负形成能保留。本地交付另有同渲染器生成的HTML/PDF/PNG预览。

## 验证与交付状态

- report_review：37项Python/真实本机HTTP测试通过（含继承的原科研注解用例）。新增覆盖独立编辑Prompt、无科研生成、三组精确结果、Unicode负号、μ_O、后续参考覆盖、已知带电/组成错误/缺结构、部分结果、结构化修改/删除/补充、原子回滚、重复处理、修订历史、冻结来源与三种导出。
- report_background：7项通过，包含用户回答→原批注续处理、私人连接/权限、恢复/取消及原报告生成。
- report_presentation：7项通过；properties：35项通过，严格性质原入口保持。
- 真实Report页面→隔离API→本地模型Mock浏览器流程通过，覆盖AI开关保持同一3D宿主、原结构交互、四结构筛选、批注后台处理、三组卡片/层级/表格、刷新恢复/重新打开、HTML下载及手机抽屉。HTML打印实际生成PDF，提取文本核对三组数字与来源。
- TypeScript检查、/tmp前端发布包、独立报告交互运行时构建通过。构建仅有已有大包提示。
- 模型/SSH为Mock；真实数据仅做本地只读演算，不能将此称为真实付费模型端到端验收。无HPC提交、数据迁移或新执行权限。

遗留与限制：真实所选模型的意图识别效果未做付费调用验收；本次批注未扩展NEB/功函数等其余配方；历史卡片仍按兼容格式显示，明确重新处理才生成新卡片。报告中的结构和能量是已保存快照，正式来源一致性/中性等证据不足仍需科研核对。

用户确认“现在部署并推送 main”后，已将修复fc507d7合入main，使用已验证的临时发布包切换生产前端及报告运行时，保留304份旧hash资源，并重启原后端，保持单writer。线上health、首页/报告/AI入口、41份HTTP静态资源hash、后端内联报告运行时/3Dmol/NEB样式及4个私有API的401保护核对通过。/report下的运行时由后端内联读取，不将SPA返回页面的200误认为脚本资源通过。源码及发布记录随本次main提交推送。未调用付费模型、改动原报告或科研计算文件；AGENTS与原有删除项保留原样，待办完成标记仅保留在本地用户原有未提交文档中。
