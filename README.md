# VASP Manager

管理 VASP 项目、巡检、作业、科学分析和科研报告的 Web 应用。仓库：[chelair/vasp-management-system](https://github.com/chelair/vasp-management-system)。当前应用版本 **1.1.4**；源码和发布状态见 [交接与运维](process.md)，历史见 [主要变更](docs/changelog.md)。

## 现有功能

| 入口 | 能做什么 |
| --- | --- |
| 总览 | 项目进度、交付风险、真实集群作业/额度/节点/队列/存储 |
| 巡检中心 | 自动/手动巡检、能量力曲线、收敛和异常、NEB/自由能及分析详情 |
| 作业管理 | 输入查看/参数草稿、已有构型续算、脚本生成/写入、提交/停止及参数来源记录 |
| 智能报告 | 完整项目报告、人工元素组合、科学性质验证、独立 AI 专题与 HTML/PDF |
| AI 工作台 | 用户私有模型连接、思考深度、项目会话、按需查证、报告和托管计划工具 |
| 自动化/项目托管 | 固定规则动作；M0 项目目标/阶段/任务优先级、资源评分及脚本预览 |

**项目托管 M0 尚未接通自动执行**，保存计划或启用计划不等于自动提交。已有单 OPT 有限执行循环需单独授权，真实无人值守项目验收仍有边界，详见 [托管](docs/managed-compute.md) 和 [执行](docs/execution.md)。

## 一句话生成报告

在 AI 工作台的项目会话中提出问题，例如：“看看 PMS 在 model1 上的吸附能，生成报告。”AI 自动理解别名、找任务与能量，必要时给出选择或接受自定义回答。

吸附能有基底、吸附质、完整构型三个能量即可计算初步结果。你也可以直接告诉 AI 以前算过的气体能量，不必先创建气体任务。未收敛/设置差异等会提示风险，缺数值会说清缺什么，不生成虚构结果。

报告包含结果与计算方式、构型/能量/收敛信息，可编辑标题/文字、排序删除元素、隐藏风险提示，保存后预览与导出保持一致。底层计算与来源不会被文字编辑改变。[报告说明](docs/reports.md)

## 启动与开发

前端使用 React 18、TypeScript、Vite 7、Ant Design 5、ECharts；后端为 Python/FastAPI/Paramiko，项目与巡检主要为 JSON 文件，AI 私有会话为 SQLite。

需要 Node.js ≥20.19（或符合 Vite 要求的 22.x）和 Python ≥3.11。先在独立开发目录安装：

```bash
npm ci
python3 -m venv .venv
.venv/bin/pip install 'fastapi>=0.115' 'uvicorn[standard]>=0.32' 'paramiko>=3.4' 'cryptography>=43'
```

后端可用 `--data-dir` 隔离数据；生产目录已有服务时，不要再启动写同一 data 的实例。

```bash
PORT=3002 .venv/bin/python backend/run.py --data-dir /tmp/vasp-manager-dev-data
```

前端开发运行 `npm run dev`（默认 5173）；若后端用独立端口，使用 `VITE_API_TARGET=http://localhost:3002 npm run dev` 指定代理目标。正式构建 `npm run build` 生成 dist 和报告交互运行时；日常验证须构建到临时目录，详见 [运维](process.md)。

默认后端端口 3001，同时提供 API 与 dist 单端口页面。首次初始化的管理员信息以启动日志/账号工具为准；API 和文档访问需登录。模型服务请求由原工作台后端执行，不依赖 openai SDK。外部分析器和 VESTA 等按需安装，见 [依赖](DEPENDENCIES.md)。

## 目录

```text
backend/          API、SSH、巡检、自动化、性质计算与报告
src/              页面、现有交互组件与报告运行时
scripts/          转换、分析、构建与账号工具
tests/           隔离测试、Mock证据与必要浏览器用例
docs/             专题说明、变更摘要和功能模板
data/             运行时数据（不进Git；knowledge例外）
```

本地/远端具体任务路径以 `backend/task_paths.py`、`backend/paths.py` 和当前数据为准；AI 工作区地图见 [工作台](docs/ai-workspace.md)，不要从模型名称猜科学关系。

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [开发准则](AGENTS.md) | 用户偏好、最小开发/验证、发布与文档维护规则 |
| [交接与运维](process.md) | 当前能力、未完成项、服务、数据、发布和排查 |
| [API](API.md) | HTTP 合同和工具边界；在线 OpenAPI 以当前代码为准 |
| [依赖](DEPENDENCIES.md) | 核心/可选依赖及远端科学工具、VESTA/Xvfb经验 |
| [AI工作台](docs/ai-workspace.md) | 会话、模型深度、文件/巡检/参数证据 |
| [科研报告](docs/reports.md) | 简明报告、R1/R2/R4、冻结证据和导出 |
| [科学分析规范](ANALYSIS_FEATURES.md) | 配方/公式、初步与正式验证、输入发现和接入模板 |
| [受控执行](docs/execution.md) | 自动化、预算、幂等、对账与单OPT边界 |
| [项目托管](docs/managed-compute.md) | M0已实现内容、执行缺口及后续构建提示词 |
| [主要变更](docs/changelog.md) | 重要发布结果；完整历史使用Git |

文档以当前行为为中心，不维护多份阶段任务书或相互矛盾的待办。代码和数据变动不因文档描述自动生效。
