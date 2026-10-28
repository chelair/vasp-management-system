# 科学分析功能接入规范

维护日期：2026-10-20。适用于已有结果的性质计算、比较和报告；不因新增分析而创建/提交 HPC 作业。新增功能先读相关源码，按需填写 [设计模板](docs/templates/analysis-feature.md)，不另建聊天/报告/任务状态体系。

## 统一链路

**用户问题 → AI 理解与角色映射 → 只读数据发现 → PropertyRecipe 检查与 Python 运算 → R2 ReportBlock/Evidence → 原 AI 文字 → 独立 topic 保存 → 读回实际正文核对 → 编辑、导出。**

各性质共用报告读写：`list_topic_reports` 找原报告，`get_topic_report` 读取当前正文与冻结数据，`update_topic_report` 修改同一修订的分析重点、结论和建议。正文从预览/导出的同一渲染器提取，包含人工编辑；DOS等曲线可按图表编号读取冻结数据。性质计算仍各用原有配方，不把NEB检查套到吸附能或DOS。

默认简明报告由 create_topic_report 一次服务调用完成；不是强制模型分四轮 prepare/plan/write/save。高级分步入口仍兼容。[报告说明](docs/reports.md)

## 初步计算与正式验证

- 用户口语、别名、当前或历史给定能量是合法输入，AI 可自行理解/绑定授权任务；无需用户原话中出现精确 task_id，也无需先建气体任务。
- 保存每项来源：计算记录、用户给定、AI解释/假设分别标记。用户给定不冒充已验证计算，AI建议不冒充用户陈述。
- 吸附能初步计算只要求三个有限能量及角色明确；收敛、K点、理论设置、结构/证据缺失为风险，不阻断已有数值。风险可隐藏展示，底层记录保留。
- 真正缺必需数值、无法确定角色或公式未支持时，给出精确缺口和操作建议；不填假数字、不生成看不懂的空草案。
- 严格性质验证按各配方核对科学前提；不充分时不能出正式结论。它与初步算术是不同入口，不用统一硬门槛覆盖用户授权的初步报告。
- 程序结束、SCF收敛、离子收敛、数值精度和科学适用性分别记录；未验证条件保留，不能把计算PASS等同论文结论。

## PropertyRecipe 合同

`backend/properties.py` 注册 `property_id / version / definition / scope / required_inputs / optional_inputs / required_checks / calculation_function / formula / output_units / missing_data_policy`。公式由固定Python函数实现，LLM不手算最终数值，不接受任意表达式/代码。改变公式/科学含义/检查要升级版本，旧报告仍用原版本。

| 配方 | 定义与范围 |
| --- | --- |
| oxygen_vacancy.neutral_single | 中性单O空位；E_f=E_defect−E_pristine+μ_O |
| relative_energy | 相同组成/可比条件下 E_model−E_reference |
| adsorption.simple | 正式核对组成、结构关系和理论条件的单中性吸附物电子吸附能 |
| adsorption.estimate | adsorption.minimum.1.1.0；三个已有/给定能量的初步吸附能，质量问题提示 |
| neb.barrier | 已有完整NEB路径 E_a=max(E_images)−E_initial，差值有明确反应/方向 |
| work_function.difference | 可比真空方向/表面侧和平台条件下已有功函数之差 |

以 `/api/properties/recipes` 实际注册表为准，未知性质返回 UNSUPPORTED。DOS/PDOS比较可复用已有图，不为展示虚构派生公式。

吸附能固定为 `E_complex−E_surface−E_adsorbate`，不是含温熵/溶剂/电位/BSSE的自由能。简明入口接受 eV、Ha/Hartree、Ry、kJ/mol，由Python转换并保存原值/单位/原话；有限数检查拒绝NaN/无穷/bool。多个真实位点不随机取第一个。

中性单O空位须核对原始/缺陷对应、只少一个O、位点、晶胞/组成、电荷、收敛、能量定义、泛函/U/POTCAR/ENCUT/KPOINTS和氧参考。不能因名字含“vacancy”而确认关系。μ_O须有每O数值、来源与适用条件；缺μ_O不能给绝对值，但同参考且其他条件成立时可给 B−A，说明消去项。带电缺陷列出费米能级、带边、势对齐和有限尺寸修正等需求，不套中性公式。

## 来源与发现

复用项目/任务、原始巡检 `collect_task_observations`、task context、AI规范化和科学分析器。跨项目先逐项目鉴权，再读数据；限制候选/项目/读取大小，截断明确说明，不假装无数据。

输入状态用 AVAILABLE/MISSING/INCOMPLETE/INVALID/STALE/AMBIGUOUS/UNKNOWN，区分缺失、不收敛、无效和过期。任务名产生候选，AI语义映射可确定业务角色，但不能冒充结构关系证据；真实歧义在对话选择并支持自定义。

计算记录绑定 project/task、目录conN、job/observation、指纹、实际参数和能量定义。不同来源可以作为声明清楚的初步输入，不拼成“同一次已验证快照”。当前镜像不能填历史观测缺口。用户外部给定值可以没有task/observation，来源字段必须如实。

正式R3输入采样随正常巡检固定目录执行，不新增SSH轮询：保留结构/INCAR/KPOINTS、POTCAR数据集摘要/ZVAL、OUTCAR必要回显与OSZICAR周期。TOTEN与最后完整周期核对，哈希明确full/头尾样本。旧档案不自动回填成已验证证据。

正式结构/理论检查目前有VASP5格式、自动网格、原子顺序映射和有界采样等限制。表面/复合模型同晶胞与原子对应、periodic严格同网格或显式isolated_molecule参考各有前提；缺证时保留限制，不按名字推断等效性。

## 实现分层

1. **科学层**：`property_science.py`、`adsorption_science.py` 等纯Python检查/数值函数，不访问SSH/提交/模型。
2. **数据层**：R3授权/输入适配、`topic_discovery.py`、专项如 `adsorption_discovery.py`；简明能量来源与用户值在 `adsorption_minimum.py`。
3. **协议层**：必要字段同步更新 `topic_tools/property_tools`、服务/API和前端；不能只改prompt。用户给定值的业务工具与严格R3 selector不同，不要求所有接口都接受任意替代能量。
4. **证据与展示层**：选已有白名单block，记录选择原因/章节/顺序/必要性，后端校验权限、存在、来源、相关性和可用性。模型不生成任意HTML/JS。
5. **保存层**：独立topic/性质报告ID、公式版本、来源/参考态、结果、验证状态和未知条件冻结；文字与事实分离，修订冲突409，普通编辑不重读。重新生成失败保留原稿，导出与保存版本一致。

部分结果可成立时独立列出，缺一个目标不抹去另一个目标的有效结果。补算只建议，不因报告请求自动建作业。

## 必要验证与文档

按本次实际改变选最少验证：独立已知数值/单位/符号；缺输入与可成立部分；多位点/歧义；质量问题警告不挡初步值；用户外部能量；权限/冻结/模型失败；涉及编辑导出才验证对应交互。不要默认跑全矩阵、全量报告回归或为低影响文案写镜像测试。

测试使用临时数据/密钥和Mock；改前端才做相关类型/隔离构建和必要浏览器验证。不得把合成值说成真实LMR/PMS结论，未运行不记通过。

只更新相关权威文档：本规范/模板、API、对应专题与必要交接摘要。不再为每项分析复制README、AGENTS、工作区、审阅、进度七八份同样状态。发布遵守 [开发准则](AGENTS.md) 和 [运维](process.md#发布与回滚)，不做不必要备份。完成本轮范围后停止。
