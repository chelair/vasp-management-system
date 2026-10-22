# 当前状态、接手与运维

维护日期：2026-10-21。应用版本 **1.1.4**（package.json），完整报告 schema 1.2.0、R2 schema r2.1.0 是独立版本体系。长期准则见 [AGENTS](AGENTS.md)，重要发布结果见 [变更摘要](docs/changelog.md)，完整历史查 Git。

## 当前状态

- 2026-10-22人工停止补齐“无匹配作业”回执：bkill明确不存在时收尾本地状态/台账，不再错误提示停止失败；记录NOT_FOUND，原结束原因未知，不当作计算完成/收敛。SSH/权限/命令错误保持阻塞；停止不新增LSF轮询，重提仍检查活跃作业。6项相关隔离用例通过。
- 已发布AI按需结构工具：原工作台新增结构概览、局部环境、结构对比；复用原VASP5解析与项目鉴权，Python处理斜晶胞/周期映像，返回文件指纹及来源，本地/远端只读，不预载整个项目坐标。10项专项、1项原聊天结构工具闭环、1项原文件工具回归通过；FS@Kaolin本地124原子真实结构只读验证通过，模型/远端为Mock。类型检查/临时目录构建与上线health/hash资源核对通过，前端工具名与后端已发布；未触发HPC操作或付费模型请求。详见[结构工具](docs/structure-tools.md)。
- 2026-10-21已发布离子步总能取数修复（移除历史更正）：保留OUTCAR离子步总能识别，排除电子迭代TOTEN；新巡检下次上传修复脚本。按用户最新要求移除历史摘要自动更正及energy_correction，历史查询直接返回归档原值，不重解析、不回填。FS@Kaolin con8的21:50记录原值仍为−803.03211069 eV（已核对该值取自后续SCF；同次第54步总能为−819.90785191 eV），待实际新巡检更新。未改远端计算文件、收敛判定或HPC执行链；本次15项相关隔离测试通过，已重启后端并通过health检查，前端产物保持不变。
- 2026-10-21已发布文件结构显示修复：概览只读实际本地文件清单，区分已有、空文件、缺失和读取失败，保留待生效草稿；不再用本地缓存推断远端“最新/过时”。vasp.lsf按实际文件识别，可手动刷新，巡检返回更新；提交、续算、巡检和同步核心未改。类型检查、专项浏览器隔离验证（含无远端操作、无轮询、迟到响应保护）、临时目录构建和上线health/静态资源核对通过；仅切换前端，未重启后端。
- 2026-10-21已发布NEB力收敛修复（随前轮文档整理一起推送）：中间映像正常结束且末步力/RMS满足实际计算目录INCAR阈值才标完成；超限为unconverged，缺证明确提示。优先NEB优化力摘要，旧输出无摘要时按OPT固定原子/合力口径统计。现有历史归档不批量改写，下轮巡检上传新脚本后更新。
- 项目/巡检/提交续算/分析与完整报告已接真实后端；不是 Mock 演示应用。资源采集失败时某些界面仍可显示明确标记的模拟/旧数据，这些不能用于自动执行。
- AI 简明报告支持自然语言、别名、用户历史给定能量和可隐藏风险；吸附能三个能量即可给初步值。严格性质验证与高级分步工具保留，不能覆盖默认简明入口。[报告](docs/reports.md)
- 模型思考深度已上线，发送键左侧可调整；DeepSeek工具轮不再强制关闭思考。[工作台](docs/ai-workspace.md)
- 托管 M0 `34e3801` 已发布：计划/优先级/资源评分/脚本预览；**项目计划自动执行未接通**。不要把 active 或 preview 当成已提交。[托管现状](docs/managed-compute.md)
- 最近已确认发布记录包括 `8803136` 的报告页AI开关迁移，以及 `6a6fe24`（文档 `bd8761a`）的托管并入自动化：`/automation` 两标签默认托管，暂只对管理员开放，原 `/managed` 独立入口移除。本次文档整理不负责发布其他工作区变动。
- 本文不固定 PID、项目/任务数量、授权数量或实时开关值。需要时读取当前服务与授权配置，历史快照不能代替实时状态。

## 接手顺序与剩余工作

先看 `git status --short`、`git log -5 --oneline`、本次用户需求，再读相关源码与专题。保留用户/其他工作区已存在的修改，不恢复删除文件或夹带提交。

当前明确的托管后续为：整轮巡检候选仲裁、ready首提、规则识别运行中异常、最小AI决策和去重、资源预留→旧执行核心接线、多队列/软结束兼容、持久委托、观察/修复分账。详见 [托管执行提示词](docs/templates/managed-compute.md)。先完成已有模型/输入的最小链路，不自动建模或上通用DAG。

单 OPT 仍受会话寿命、观察步数、固定原子和有限输入格式等约束，真实项目无人值守尚未完整验收。COHP、复杂带电缺陷/自由能等没有因为旧TODO或prompt出现就实现；性质支持以 recipe registry 为准。未被当前用户选中的历史想法不继续当活动任务。

## 环境与数据

生产目录 `/home/zouyuxi/projects/vasp-manager`；服务 `vasp-manager.service`，运行用户 zouyuxi，默认端口 3001。局域网 `http://192.168.1.20:3001`，ZeroTier `http://10.147.20.10:3001`；`/docs`、`/openapi.json` 需要认证。

```bash
systemctl status vasp-manager --no-pager
journalctl -u vasp-manager -n 80 --no-pager
curl -fsS http://127.0.0.1:3001/api/health
```

| 数据 | 位置/语义 |
| --- | --- |
| 项目/任务 | data/projects.json 和 data/projects/，路径通过 task_paths/paths 解析 |
| 配置 | data/config/；不同配置的即时生效行为以接口实现为准，不一律靠重启 |
| 巡检 | data/checks/；每任务最近5个目录，每目录一个最新观测 |
| 报告 | data/reports/；完整报告、组合、专题、性质报告独立存储 |
| 登录/授权 | data/users/；执行台账 data/agent_execution.json |
| 托管计划 | data/managed_plan.json；不代替真实作业状态 |
| AI | data/ai/chat.sqlite3、私有workspaces；主密钥独立于data |
| 审计 | 原 automation 审计/动作记录、提交日志等，见执行模块 |

`VASP_WEB_DATA_DIR` 或启动参数 `--data-dir` 可指定隔离数据根；`VASP_AI_KEY_FILE` 指定隔离AI主密钥。不要在测试中读取生产会话/密钥或将Mock写入真实项目。data、配置、凭据、dist不进Git；data/knowledge是人工知识例外。

## 发布与回滚

用户明确“提交=推送=部署”，Git直接main。只审视、改文档或本地开发不自动发布；用户已要求发布时完成授权内步骤，不再次问同一许可。不备份服务器已有计算文件。

1. 核对已有未提交改动，只选择本次文件。必要检查应与改动相关，文档整理只检查引用和差异。
2. 前端及报告运行时在临时目录构建，不在日常验证覆盖生产dist：

```bash
npm run typecheck
npx vite build --outDir /tmp/vasp-release
npx esbuild src/interactive/reportRuntime.ts --bundle --minify --format=iife --target=es2019 --platform=browser --outfile=/tmp/vasp-release/report/report-interactive.js
```

3. 授权发布时复制新资源，保留旧hash资源，一并携带本地3Dmol与report runtime，最后原子切换index。`npm run build`默认直接写dist，只能在确实要切换产物的发布环境使用。
4. 后端有变更时重启原服务；用户明确要求完整重启时按要求执行。仅静态变更不需要启动第二个后端。权限不足如实说明，不创建并行writer绕过。

```bash
sudo systemctl restart vasp-manager
```

5. 检查health、首页引用资源、实际相关页面/API。不把SPA返回200当成功的浏览器业务验收。记录本次确实检查的结果并推送main。
6. 回滚代码/静态产物需采用兼容版本，保留当前业务数据；不要复制早期JSON或删UNKNOWN台账来“回滚”。必要迁移另按用户授权处理，不自动启旧机器并行写。

**一个data只能有一个backend writer。** 独立验证使用临时data、不同端口和Mock SSH/模型，不在生产数据上另起测试服务。

## 输入、巡检与提交要点

- 输入三层：远端当前conN是真实文件，本地files是镜像，input_state.draft是待生效修改。上传/续算应用/成功提交才进入已应用记录，上传不代表VASP重读。
- 普通参数在下次续算生效；不能用同步/自动化覆盖人工待应用草稿。历史多值INCAR可能被旧采集截断，不用当前镜像伪装历史参数。
- 续算复用旧核心，CONTCAR→POSCAR，登记隐藏子任务；WAVECAR沿用**移动**语义，不能误报复制或保证源目录仍有该文件。
- 提交成功只证明LSF受理，PEND不是RUN；程序退出不等于SCF/离子收敛。未知job/状态先对账，查不到不直接重提。
- 人工停止按bkill成功返回同步本地，不另轮询；再次提交仍实时检查LSF，原作业仍活跃则恢复running并拒绝重提。旧记录不能覆盖新job；人工核实旧job入口位于提交报错弹窗。
- 全局巡检跳过pending/archived和关闭项目；结构按既有步数桶/目录变化/完成条件同步，失败保留上次结果。前端重新读取本地结构不等于额外远端巡检。
- 共享资源采集有TTL、stale和error；界面模拟回退不授予执行依据。精确排队时间没有可靠预测器，资源评分只给启发式建议。

## 常见排查

| 现象 | 先检查 |
| --- | --- |
| 修改前端看不到 | 当前dist/index引用是否为新hash，是否漏报告runtime；日常开发用dev服务 |
| 后端改动无效 | 服务WorkingDirectory/ExecStart与实际进程；生产未启reload |
| 导出图表/3D缺失 | 本地3Dmol、report runtime、冻结资源及WebGL；缺数据不补假图 |
| VESTA无头渲染失败 | Xvfb+Mesa软件GL、PNG完整/IEND、窗口/进程组收尾，见DEPENDENCIES §3b |
| SecureLink连接后模型/API掉线 | tun0/默认路由和DNS；HPC需校园VPN，其他流量例外路由按当前主机配置检查，不照抄过期临时修复 |
| Linux目录“文件丢失” | NEB/neb大小写、实际dir_path和任务地图；不要新建空目录掩盖旧数据 |
| 续算或提交被阻止 | 活跃/未知job、台账对账、目录身份、预算、草稿和授权，不先清job_id |
| 找不到python | 使用仓库.venv/bin/python或python3 |

VESTA视角修改应改AXIS_VIEW/SCENE并升级VIEW_VERSION；PNG等待完整再结束渲染，关闭单实例窗口不能杀用户其他窗口。具体安装/脚本见 [依赖](DEPENDENCIES.md)，不另存重复渲染手册。

## 文档维护

只更新本次涉及的权威文档：功能/运维状态在此，接口在API，长期规则在AGENTS，专题在docs，历史只留重要结果。删除的阶段任务书、旧TODO与发布流水账可通过Git恢复查看，不继续复制为“当前接手任务”。本次仅文档整理，未构建、重启、改生产数据或触发HPC操作。
