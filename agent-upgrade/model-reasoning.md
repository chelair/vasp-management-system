# 模型思考深度：工作台前端与真实请求

2026-10-20本地完成，开发分支 `codex/model-reasoning-controls`，工作树 `/home/zouyuxi/projects/vasp-manager-r4`。初轮用户要求前端接入时未部署；随后用户授权推送及部署，并要求直接main。现已于20:44上线v1.1.4/PID3252519，源码9d7dd9b。用户明确取消计算文件备份，已中断并清理不完整归档；上线验证见PROGRESS §27。不是新增科学性质，无需新PropertyRecipe或分析执行链。

## 使用与行为

AI工作台→模型连接→新增/编辑，可按型号选择“思考深度”；聊天窗口模型下方也可快捷调整。调整的是该私有连接的默认值，所有使用该连接的后续请求生效；已有运行按原快照继续，历史不改写。快捷调整不要求重新输入密钥，编辑留空保留密钥，切换地址仍要求重新输入。

默认“自动识别”只识别官方OpenAI/DeepSeek域名。代理、别名及其他兼容服务可以明确选择OpenAI兼容或DeepSeek兼容；未知接口默认不附加思考参数，不能按模型名称偷偷猜测服务能力。选项从后端统一能力表获得，服务商拒绝配置时不自动降低深度或重试。

- 当前DeepSeek Flash/V4：默认、关闭、低、高、最高。实际请求传`reasoning_effort`及一致的`thinking.type`；旧thinking_mode保留，显式新档位优先。旧版deepseek-chat/reasoner不伪造可调深度，保持默认语义。
- OpenAI：已登记o系列与GPT-5/5.1/5.2/5.4/5.5/5.6和GPT-6型号及日期快照，按各型号支持的组合显示none/minimal/low/medium/high/xhigh/max，不认为所有模型都支持全部档位。未知型号自动模式只有默认；显式兼容模式可按服务商声明传递，注明未实测。
- 当前程序使用Chat Completions。GPT-6 Astra/GPT-6.1 Sol在该接口不支持工具调用；GPT-6 Sol/Luna仅none可配工具。前端提示，后端在付费请求前拒绝不支持的组合；不默默关工具或降低深度。可关闭会话工作区做普通聊天。本轮未扩展Responses传输。

DeepSeek工作区不再强制直接回答。工具轮仅在当前运行内存延续必要的reasoning_content，不写SQLite、不进SSE/正文/历史/运行快照。单轮最多20万字符，继承原调用/时限上限。普通聊天和报告JSON也沿用连接配置；报告段落仍最多4096输出tokens/120秒，OPT审阅原1200/90秒约束保持。提高深度不提高权限，也不取消原成本限制；额度不足可能无最终回答，应降低深度或在允许范围提高输出额度。

## 数据和接口

连接增加 `reasoning_api=auto|openai|deepseek`、`reasoning_effort=default|none|minimal|low|medium|high|xhigh|max`。保存时再次按能力表验证组合；旧客户端未发送的新字段保留原值。SQLite原地增加默认列，不替换连接ID、密钥密文或会话关联。旧thinking_mode仍可读取；旧“关闭”界面显示为关闭，旧“启用”未指定深度时仍显示模型默认。

`GET /api/ai/chat/reasoning-capabilities?base_url=...&model=...&reasoning_api=auto` 仅返回本地能力定义，不访问所填地址或发付费请求，沿用人工登录/私有权限/no-store。公开连接返回capabilities和effective_reasoning_effort，不返回secret。`verified`在能力对象中表示内置文档型号匹配，**不代表该账号/代理已经实测可用**。

实际payload由统一 `ai_reasoning.parameters` 创建；聊天运行快照记录连接所选/生效深度。原SSE/连接私有加密/项目上下文/专题工具/报告保存均复用，科学数值仍由Python产生，不给模型增加计算或写入权限。

## 修改映射

- `backend/ai_reasoning.py`：能力档位、校验、旧模式解释、真实参数与Chat工具约束。
- `backend/ai_chat_store.py`、`routers/ai_chat.py`：两列迁移/私有保存与能力接口；旧客户端保留字段。
- `backend/ai_chat_service.py`：统一payload、快照、DeepSeek工具轮内存延续、报告不再强制关闭。
- `src/components/ai/ConnectionSettings.tsx`、`src/pages/AI.tsx`、`src/api/aiChat.ts`：动态型号选项、设置/快捷调整、可读状态、额度/工具限制说明；输入增加明确无障碍名称。
- `tests/test_ai_reasoning.py`、`test_ai_chat.py`、`test_report_ai_notes.py`、`browser/model-reasoning.cjs`、`r4_server.py`：隔离能力/真实HTTP-SSE/JSON/真实React回归。新增测试夹具查询口只在临时测试服务器存在，未加到生产路由。

## 实际验证

127项Python通过：思考能力7、AI聊天26（原22+连接/实际payload/思考工具轮/报告JSON/能力接口及前置阻止，部分合并同一测试）、报告AI注解20、R4单元17/真实HTTP-SSE10、OPT47。全部需隔离的套件独立临时数据/密钥/Mock模型或SSH运行；未请求真实付费模型。

`node tests/browser/model-reasoning.cjs`通过：连接创建/保存/重开、型号切换动态选项、密钥留空保留、聊天快捷调整、OpenAI低/DeepSeek最高实际HTTP-SSE请求、刷新后保留，零页面错误。既有 `node tests/browser/topic-reports.cjs`（包括吸附/DOS/位点/编辑/导出/单段生成）回归通过。

`npm run typecheck`、Vite `/tmp/vasp-reasoning-build` 与报告runtime构建通过；原有大chunk提示保留。`git diff --check`通过。已有Python 3.14 asyncio弃用提示不影响结果。本轮没有重跑全部330项科学/部署套件，不声称已做生产或真实服务商账号验收。

## 官方依据与维护

使用OpenAI Docs技能核对官方文档，日期2026-10-20。能力表是显式文档快照，不是自动探测；新增型号/服务商需同步校验/选项/测试，不能只增加前端选项。

- [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)：Chat Completions的reasoning_effort、型号差异和GPT-6工具限制。
- [GPT-5.1](https://developers.openai.com/api/docs/models/gpt-5.1)、[GPT-5.2](https://developers.openai.com/api/docs/models/gpt-5.2)、[GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4)、[GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5)、[GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)、[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)：各型号档位和接口约束。
- [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completion参数](https://api-docs.deepseek.com/api/create-chat-completion/)：none/low/high/max及思考模式工具轮延续方式。

未宣称思考深度能替代科学校验或保证答案质量；服务商型号可用性、实际费用/速度/答案质量尚未实测。后续若发布，需要按原部署规程备份AI SQLite（两列原地升级）、隔离构建、单writer切换和鉴权/配置/新旧资源验证。本次按后续授权已部署并同步main，不移动发布tag，完成后停止。
