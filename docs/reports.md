# 科研报告与可复用元素

维护日期：2026-10-27。本文件合并 R1/R2/R4、PMS 空草案修复、报告审阅和简明报告说明；性质公式与接入规则见 [科学分析规范](../ANALYSIS_FEATURES.md)。接口细节见 [API](../API.md)。

## 用户的默认使用路径

用户一句话 → 原 AI 会话理解语义/找数据 → Python 确定性计算 → 选择已有报告元素 → 保存独立专题 → 查看、编辑和导出。

AI 是用户与报告之间的翻译官。名称无需规范，AI 可自行绑定授权任务/角色；真正不确定才在原对话给少量选择或接受自定义回答。用户当前或历史给定的参考能量可以使用，即使没有对应气体任务。用户要求的标题、分析重点和风险展示优先于模板。

默认吸附能使用 `adsorption.estimate`（`adsorption.minimum.1.1.0`）：有基底、吸附质、完整构型三个有限能量即可由 Python 计算 `E_ads = E_complex - E_surface - E_adsorbate`。收敛、K 点、来源/结构缺失等在对话中简短总结，不放报告，不阻止初步值；不得宣称正式科学验证通过。缺必要能量时在对话中询问，支持选择和自定义回答，不把报错、缺项清单或补充说明堆进报告。

报告核心为吸附能和代入公式色块、三个构型的 3D/能量/收敛情况。其他信息按需补充，数据来源折叠，避免向用户堆内部 ID、标签和校验表。

## 以研究目标为导向的断键路径诊断

NEB/断键问题先读取项目计算内容与预期，优先核对端点反应键、片段骨架和 O–Li 接触变化，再看约束和参数；默认 `neb.barrier` 简明报告生成结构诊断，不要求先通过正式能垒数值配方。报告突出关键结论，按问题、影响、解决办法组织，并复用冻结 R2 结构添加距离标注。

目标反应键、研究范围有歧义时，在原对话确认；回答继续原 AI 对话，已有结构证据保持冻结。两端总能或位移不能拆出形变能/脱配位能；不为填满报告编造数值。详见 [断键路径诊断](reaction-diagnosis.md)。

## 三类报告各自保存

| 类型 | 用途与存储 |
| --- | --- |
| project_full | 完整项目报告，沿用旧报告根目录和每项目最新一份的清理语义 |
| composition（R2） | 人工挑选可复用元素，`data/reports/compositions/<项目>/<id>.json` |
| topic | AI 专题，`data/reports/topics/<用户摘要>/<topic_id>.json`，每份独立 ID |

专题/组合不能进入完整报告单份清理逻辑，同一项目多份专题互不覆盖。旧报告保留原配方与证据版本，不批量重新计算。普通编辑不重读当前上游数据；重新生成简明报告产生新 ID，问答补齐产生同一报告新修订。

## ReportBlock / Evidence 合同

R2 schema `r2.1.0`，实现于 `backend/report_blocks.py`、`report_block_science.py`、`report_compositions.py` 及 `routers/report_compositions.py`。以实际模块和 `/api/reports/blocks/schema` 为准。

- **Evidence** 保存一次科学 payload，包含稳定 `evidence_id`、内容 version、任务/组/项目、来源目录/attempt、观测/文件与 hash_scope、availability、validation 和 freshness。
- **ReportBlock** 保存稳定 `block_id`、type/title、source_refs、白名单 renderer/options；不复制科学数据。标题、排序、隐藏不改 ID；数据变化改 version，不用采集时刻冒充数据版本。
- **Composition/topic** 保存块顺序、分组、隐藏/删除与证据映射。正文、AI 原文、用户编辑和计算结果分离。
- 候选从全部授权任务发现，不能从完整报告 Markdown 或其前六个结构模型反推“没有数据”。名称匹配不证明科学关系。
- 首批 14 类适配覆盖基本信息、参数、能量力、曲线、结构、自由能、NEB、PDOS、Bader、功函数、差分图、比较、分析文字与方法来源；仅解析本地已有结果，不触发 SSH 或分析作业。
- 缺失、未解析、未收敛、正文限额省略、隐藏、过期分开表达；不能用 `bool(None)` 把未知变成验证通过。
- 参数对照可选 2–12 个任务；ID variant 由规范任务集合生成。同一 Evidence 可被多个块引用。

## 编辑、修订和新鲜度

简明专题默认先显示结果，进入编辑后可改标题、关键结论、建议、结构顺序和删除。报错、必要缺项和非必要警告留在对话，预览与 HTML/PDF 一致；不删除底层警告、来源和计算记录。旧 `show_warnings` 参数保留兼容，不再给客户报告添加警告栏。

更新必须提供整数 `expected_revision`；冲突返回 409 和当前版本，不能覆盖别人的新编辑。客户端不得写入伪造 Evidence、计算值、renderer 或任意路径。组合只有显式 `refresh_evidence=true` 才更新证据；上游改变时原快照仍保留。

`availability=available/missing/unparsed/unknown`，科学验证和 freshness 另列。参与自动巡检的实时证据采用后端时效规则；不参与或来源无法确认时明确 unknown。不要宣称每种报告都已覆盖全部实时过期检测，具体见各类型的 freshness 实现。

## 导出与交互

站内预览、HTML 下载与浏览器打印 PDF 使用同一保存版本。R2/topic 冻结 PDOS 数据，不能在导出时按 task_id 偷读最新曲线；交互实例按 block_id 定位，避免同任务不同元素串数据。

`src/interactive/reportRuntime.ts` 打包为 `dist/report/report-interactive.js`，由后端内联。部署需一并携带本地 3Dmol 和运行时；缺运行时允许静态降级，不声称交互完整。3D 需要 WebGL，PDF 以已有 PNG/静态图为准，缺图不生成假结构。

所有模型/用户文字转义或用现有安全 Markdown/SVG 路径，禁止模型生成任意 HTML/JS 组件。导出不携带被隐藏/删除块的独占证据。

## 完整项目报告 AI 注解

“AI 报告撰写”开关现在位于**智能报告页**，按当前项目保存 `ai_report_notes_enabled`，默认关闭；项目编辑弹窗不再维护该开关。普通报告生成不等待模型，AI 注解独立预览/编辑/保存，可恢复一次原文字。

复用用户私有连接，但固定报告证据请求不授予聊天/HPC 工具。模型失败不破坏原注解。保留原 `notes/edits` 和旧报告 schema 的兼容读取。

## 历史问题与维护边界

PMS 曾只停在 prepared，候选匹配又遗漏 `PMS@model1`，导致空草案；这些问题已修复。默认简明工具直接构建并保存，无需模型连续跑 prepare→plan→write→save；高级旧流程仍存在，不能当作默认必经步骤。正文中的 DSML 等伪工具指令不执行，也不能冒充保存成功。

相关源码：`topic_simple.py/topic_tools.py/topic_reports.py/adsorption_minimum.py`；前端 `src/components/reports/TopicReportEditor.tsx`、原 Report 页面和报告交互运行时。只改涉及的层，必要验证参考 `test_minimum_report.py`、`test_topic_reports.py`、R2 测试和对应浏览器用例，不为每次改动重跑全部报告套件。
