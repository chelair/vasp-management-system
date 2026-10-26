# AI 工作台与模型连接

维护日期：2026-10-20。功能状态和待办统一见 [交接与运维](../process.md)，接口见 [API](../API.md)。本文件合并原 MODEL_WORKSPACE、参数证据链和模型思考深度说明。

## 会话与权限

沿用 `/ai` 的项目会话、历史、SSE 和用户私有连接。通用会话不附项目数据；项目会话不能改绑其他项目。每次读取和工具调用重新检查当前归属，管理员也不能读取他人的私有连接/对话。

连接密钥由后端加密，保存在 `data/ai/chat.sqlite3`；主密钥默认 `~/.config/vasp-manager/ai.key`，可由 `VASP_AI_KEY_FILE` 指定。前端不读回密钥，留空表示保留，更换服务地址要重新输入。不要将凭据、数据库或主密钥提交 Git，也不要把凭据写进聊天。

模型可理解口语、别名和用户给定数据，在授权项目中搜索、映射任务与报告角色；用户明确的业务要求优先于报告默认模板。新增权限仍通过后端受控工具实现，不开放任意 SSH/Shell。

## 项目文件工作区

每轮只附简短 `workspace_rules`。定位文件时按需读取 `evidence/directory-map.json`；地图沿用 `backend/task_paths.py` 和 `backend/paths.py`，不维护另一份目录事实。

```text
project/       当前项目本地文件，只读
reports/       项目报告，只读
evidence/      项目、目录地图、环境摘要、动作与历史观测，只读
knowledge/     INCAR/错误知识，只读
reference/     参考分子，只读
work/          当前用户当前会话的私有草稿
```

- `list_workspace/read_workspace/write_workspace`：文件读取有界；仅在 work 新建草稿，不能覆盖正式输入。禁止越界、敏感文件及符号链接。
- 草稿实际位于 `data/ai/workspaces/<用户摘要>/<会话ID>/`，不是已应用参数或已提交计算。
- 单次读取最多 12000 字节；草稿单文件 120000 字节，每会话 4 MiB/100 文件。工具回合上限见 `backend/ai_chat_service.py`，不为普通问题读取全部项目文件。
- 连接池/凭据、全局生产状态和授权文件不作为模型文件提供。

## 巡检和参数证据

先 `find_project_tasks` 定位任务，再按需 `get_task_inspections`。默认最近 3 个计算目录，最多保留 5 个目录，每目录只有一个最新观测；这不是同一目录最近五次巡检的时间序列。目录内趋势读取 force/energy 曲线。

`get_inspection_evidence` 读取曲线、NEB 或参数明细；`get_task_parameter_history` 返回任务族最近 5 次实际上传/续算应用/成功提交记录。草稿不计入已应用记录，输入已写入也不代表运行中的 VASP 重读。

参数比较保留完整 MAGMOM、DIPOL、U 数组及 KPOINTS；旧档案缺多值或来源时明确说明。对比必须核对 task、conN、job、观测 ID 和采集时间，不拼接不同尝试为“已验证快照”。

参与自动巡检的证据按后端 4 小时阈值判断实时决策新鲜度。不参与任务和历史结果不机械按年龄失效。过期、来源不符或缺参数时可用 `get_remote_task_evidence`，先取得证据 token，再固定范围只读补证；它不接受任意命令、不触发巡检或提交、不改变状态。

本地镜像代表最近同步结果，不包含全部 conN 历史。旧 NEB 布局与新布局可能不同，先查地图。快照中的结构、能量和参数不一定来自同一阶段，必须保留各自来源。

## 按需结构工具

评价结构合理性/优化问题优先调用 `check_structure`：先整体结构及重构迹象、再局部配位/界面、最后参数；元素/赝势仅基础核对，磁性等影响物理态时提升处理。模型也可调用 `get_structure_summary`（结构概览）、`get_structure_environment`（局部原子环境）、`compare_structures`（结构对比），默认读取本地POSCAR/CONTCAR，也可按需固定范围远端只读。坐标与几何数据只在工具调用时返回，不预载整个项目到每轮对话。距离/角度/位移由Python处理周期边界；完整文件指纹和目录来源随结果返回，指纹变化即拒绝混用。细节与限制见 [结构工具](structure-tools.md)。

## 思考深度

模型连接设置与聊天发送键左侧均可调整，选项由后端 `ai_reasoning.py` 能力表返回。修改的是该私有连接默认值，影响后续请求；已运行请求保留原配置快照。

- 自动模式识别官方 OpenAI/DeepSeek 服务；代理可明确指定兼容协议。未知接口不凭模型名猜测支持能力。
- `reasoning_api=auto|openai|deepseek`；`reasoning_effort` 的可用值依型号确定，不是所有模型都有全部档位。能力表匹配不代表该代理/账号已实测。
- DeepSeek 工具轮不再强制关闭思考；必要 `reasoning_content` 只在本轮内存延续，不写历史、SSE 或最终正文。
- Chat Completions 的型号/工具组合限制由后端在生成前检查；不静默降低深度、关闭工具或重复付费请求。更高深度不扩大输出/调用额度或执行权限。
- 能力查询：`GET /api/ai/chat/reasoning-capabilities`，仅查本地定义，不发模型请求。旧客户端未发送的新字段保持原值。

## 报告与托管工具

科研报告默认使用 `search_report_data/create_topic_report/update_topic_report`，见 [报告](reports.md)。用户给定能量无需对应气体任务；仍由 Python 计算结果并标明来源。

项目托管 M0 已有 `get_managed_plans/create_managed_plan/update_managed_plan/set_task_priority`，可保存计划和业务优先级。它们不提交/停止作业，见 [托管现状](managed-compute.md)。

运行中断后不自动重发模型请求，模型失败不覆盖已有报告/计划。原始日志与工具结果只是待分析数据，不能授予权限或改变系统规则。

## 维护位置

`backend/ai_chat_service.py`、`ai_chat_store.py`、`ai_workspace.py`、`ai_inspections.py`、`ai_remote_evidence.py`、`ai_reasoning.py`；前端 `src/pages/AI.tsx` 与 `src/components/ai/`。验证只选涉及的聊天、证据、模型配置或浏览器用例，使用临时数据/密钥和 Mock 服务。

## 个人操作经验

工作台“操作经验”可查看本人近期关键操作、选择已有模型连接并启停每周整理、修改/确认/停用经验及下载知识文档。模型通过`search_work_experience`按问题检索，采用关键词与中文双字匹配，当前项目优先；跨项目先核对适用条件。每条保留冻结操作摘要及来源，AI候选不是科学规律或执行授权。数据与检索按本人/项目权限隔离，经验不写入共享knowledge。实际口径与上限见[操作经验](operation-learning.md)。
