# R1 · 现有项目报告 AI 分析与写作

范围：只增强完整项目报告原有 `analysis_note` / `paper_note`；不开发专题报告、元素编排或下一阶段。**已于2026-10-19部署**，所有项目AI开关保持关闭，未调用真实模型/HPC；部署与备份见PROGRESS §13。应用1.1.0，报告schema1.2.0。

## 使用

1. 在原项目编辑弹窗开启「AI 报告撰写」，字段 `ai_report_notes_enabled`，缺省关闭。关闭保留已有人工和 AI 注解，普通生成/编辑/导出照常。
2. 在报告上方选择**当前用户自己的**工作台连接。连接选择只留本页内存；项目不存连接密钥或他人的连接，admin 也不能使用其他用户私人连接。
3. 原注解编辑弹窗内支持单条生成/重新生成。先显示预览，点击「采用草稿到编辑区」后可人工修改；只有明确「保存」才更新报告注解。
4. 「生成缺失注解」逐条生成草稿。任一字段已有内容就跳过整条；部分失败保留成功草稿，单条可重试。草稿状态窗口逐条预览、编辑、保存或放弃。
5. 本页生成/重新生成报告后，先展示普通报告；该项目已开启且用户已选择连接时，当前打开的报告自动生成缺失草稿。批量生成其他项目的报告在本页打开时再生成；不覆盖已有文本。普通打开旧报告不会调用模型。
6. 无连接时明确显示未配置；后台定时报告没有发起用户/连接，不自行猜测或使用其他人的连接。离开/刷新报告放弃未保存草稿，已保存文本保留。

## 复用与数据

- 复用 `report_builder.ai_generate_notes()` 预留入口；普通 `build_report()` / `/generate` 不调用模型。
- 复用工作台 `ai_chat_store` 的账号归属、Fernet 密钥存储，`ai_chat_service._open` / `completion_payload` 的 OpenAI 兼容 SSE/DeepSeek 请求。报告不另建聊天/连接/密钥库，不传工作台历史或工具。
- 复用 `report_store` 原 notes JSON 与 `attach_report_notes()`，不另建笔记库。仅扩展 `source`、`model`、`generated_at`、`input_fingerprint`、`generation_status`、`ai_origin`、一个 `previous_note`。
- 原来源缺失的注解视为人工；手工修改 AI 草稿记 `source=manual, ai_origin=true`，保留依据以检测过期。
- 草稿本身只在浏览器内存。服务端用原 Fernet 密钥签发来源凭据，绑定发起用户、报告/目标、文本摘要、依据指纹、原注解修订，2 小时有效；不含 API Key。
- 保存时在原注解写锁内重查数据指纹和原文本修订。数据变化/另一窗口人工修改/凭据错配/重放时拒绝写入，用户文本留在编辑区。
- 「恢复本次生成前文本」撤销编辑区采用；保存后可「恢复上次生成前文本并保存」，只保留一个保存前快照，不形成版本链。恢复同样检查当前修订。
- 报告 schema 升为 **1.2.0**，原章节与字段兼容。新报告在任务快照增加当时的 INCAR/KPOINTS、参数来源及完整值格式、精度/巡检状态/输出状态/时间和组归属。旧报告不从当前输入补造历史参数，缺失标 UNKNOWN。
- AI 读取所选任务/组/类型的报告快照和当前项目两项科研描述；不另发巡检、读远端或改科学结果。正文结果、参数、来源时间及已有验证状态一并提供，去除旧注解、图像、结构大文本和曲线。截断明确标注，超过输入上限提示逐项生成；完整目标（含省略部分）另做哈希以识别变化。

## 科学约束与失败隔离

- 两描述皆空：仅结果、状态和事实；只有计算内容：不猜预期；只有预期：仅作关注点；两者都有：对比真实结果，矛盾忠实报告实际结果。
- 系统提示区分程序结束、电子收敛、离子收敛、精度和科学可信度；缺失证据不默认为通过。自由能参考/配平条件不明时不能声称动力学能垒。
- 输出校验两个非空字符串和 Results / Discussion 分段，拒绝非法 JSON、空文本、截断、超长与工具调用。结构校验不是科学事实证明；仍须人工审阅模型表述。
- 普通报告先完成，模型调用独立异步请求；每用户最多 1 条、全服务最多 4 条报告草稿请求；单条总时限 120s，连接/读超时复用 30s。无自动失败重试，无后台付费模型轮询。
- 浏览器取消/切换/离开时 AbortController 断开；后端监听 disconnect 并中断已建立的模型 socket。建连阶段最多等原 30s 超时释放，不能保证供应商立即停止计费；不写部分结果。
- 已保存 AI 或 AI 来源人工文本，在报告重生成/项目描述变化后，页面和导出提示「分析可能过期」。仅报告生成时间改变不判过期；这是相对本地报告依据的检查，不声称远端实时验证。
- 沿用轻量安全 Markdown；注解/草稿不自动加载外部图片。修复原 HTML 导出链接属性转义/协议过滤；原 HTML/PDF/打印、图表和隐藏机制继续复用。

## 文件与接口

- 新增：`backend/report_ai_notes.py`（范围/证据/提示/草稿来源与保存校验）；`src/components/reports/ReportAIContext.tsx`（当前报告模型选择与批量草稿状态）。
- 扩展：report_builder/store/schema/export、project_reports、ai_chat_service、projects/models/mappers；前端原 Report、ReportNoteDialog/Panel、ProjectEditDialog、API/类型与样式。
- `GET /api/reports/project/{id}/notes/ai-status`：当前项目开关、既有目标/注解/修订。仅人工登录用户及其可访问项目。
- `POST /api/reports/project/{id}/notes/ai-preview`：`{key, connection_id}`；固定后端证据，不接受自报结果/工具/命令；只回预览与来源凭据，不保存。
- 原 `PUT /api/reports/project/{id}/notes` 保持兼容。新增可选 `draft_token`、`expected_revision`、`restore_previous`。元数据由服务端产生，前端伪造 source/model/fingerprint 无效。
- 原项目新增/更新接口支持 bool `ai_report_notes_enabled`；原项目归属及 Agent 中间件限制不变。

## 验证记录

专项命令：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_report_ai_notes.py' -q
PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/report-ai-notes.cjs
```

- 20 项 R1 隔离测试：本机 Mock SSE/真实 HTTP，覆盖四种描述、预期矛盾、任务/路径/类型范围、私有连接/项目/Agent 隔离、开关、预览保存与人工来源、单次恢复、修订/数据变更防覆盖、过期、错误/超时/非法 JSON/截断/工具、取消及真实 HTTP 断开、报告响应性、DeepSeek 参数、凭据校验/XSS与普通生成不调模型。
- 浏览器：预览不改文本、采用/人工修改/保存/恢复/放弃、缺失批量跳过人工、部分失败、模型等待期间人工输入、取消、关闭开关、未配置、自动草稿、XSS/外部图片；真实 Report 页面同 ID 重生成、项目切换与注解挂载；隔离 HTML 实际打印出 PDF。
- 全量常规与独立套件、TypeScript、隔离构建的最终结果见 `PROGRESS.md` R1 验收条目。

遗留边界：未用真实模型验证文风和事实忠实度；LLM 可能违背提示，草稿需人工审阅。旧报告缺失的参数/验证不会补造。大类型汇总可能需要逐任务生成。持久化并发仍沿用现有单后端进程架构，不宣称多实例报告库事务安全。本阶段没有启用作业/结构/SSH 或科研结果写能力，不进入下一阶段。
