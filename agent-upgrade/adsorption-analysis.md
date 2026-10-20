# 中性单吸附物电子吸附能：接入与验收

2026-10-20，用户授权补齐吸附能及统一分析模板，并部署推送R4和增量为v1.1.4。本地实现/隔离验收完成，2026-10-20 17:37:55 CST已随v1.1.4上线，实际发布结果见PROGRESS §25。

本功能遵循 [分析接入规范](../ANALYSIS_FEATURES.md) 与 [模板](../docs/templates/analysis-feature.md)。现有R3已经有三能量公式/手工角色绑定；本轮扩展实际缺失的结构关系、分子参考取样、多体系差值、自动只读发现和原AI专题链路，不新建聊天、模型构造或HPC动作。

## 科学合同

- `property_id: adsorption.simple`，配方/公式校验版本 `adsorption.1.1.0`。
- `E_ads = E_complex - E_surface - E_adsorbate`，单位eV，每组一个完整的中性吸附物参考。负值表示在该电子能参考下放热，不等同吸附自由能。
- 对同一个吸附物参考计算及同一观测：`ΔE_ads = (E_complex_B - E_surface_B) - (E_complex_A - E_surface_A)`，后者减前者，参考项精确消去。
- 必要输入：复合体系、洁净表面、一个吸附物参考的精确任务/观测；必须有完整结构/参数/输出及能量定义。名称只给候选，不能证明吸附关系或参考相。
- 核对中性、SCF/离子收敛、TOTEN口径、泛函/U/POTCAR/ENCUT等一致性；complex组成=surface+一个adsorbate，complex/surface同晶胞，输入表面原子按序核对元素/坐标/固定标志。坐标容差1e-4Å，晶胞分量1e-5Å；映射不唯一则AMBIGUOUS。
- `adsorbate_reference_type=periodic`为默认严格取样模式，三个计算要求相同k网格/模式/偏移。`isolated_molecule`须用户明确孤立/气相/分子参考，分子可不同晶胞与Gamma 1×1×1无偏移；只放开分子k点/盒差异，其余哈密顿量设置仍校验。
- 参考态冻结为绑定计算的source/composition/energy/reference_type/conditions，不接受LLM提供数值。共同参考必须同项目/任务/观测/原始行哈希；不同参考不默认等价，保留单独结果并说明不可直接比较。
- 缺任何参考能量不计算对应E_ads，也不使用μ_O、半个分子、猜测数值代替。健康体系可保留部分结果。无参考条件时只称电子能；温压、ZPE、熵、电位、溶剂、BSSE不计算。

## 数据发现、AI与报告

`adsorption_science.py`提供纯关系/兼容性检查；`adsorption_discovery.py`在有界候选中识别唯一完整三元关系。每个表面查询匹配已有surface/complex候选，`adsorbate_query`单独匹配参考。最多24任务、每目标24个展示关系并保留total/truncated，输入映射最多2000原子。多位点/参考不自动选，人工在专题编辑器选择，旧快照保留。

请求示例（原AI项目会话中）：

> 比较 LMR 和 LIC@LMR 对气相 H2 分子的吸附能，生成科研报告。

模型先调用原 `prepare_topic_report`：

```json
{
  "property_id": "adsorption.simple",
  "model_queries": ["LMR", "LIC@LMR"],
  "adsorbate_query": "H2",
  "adsorbate_reference_type": "isolated_molecule"
}
```

随后使用原plan/write/save工具。复用R2 `task.summary/task.params/task.energy_force/task.structure`，结构镜像仅补充，输入关系以R3观测为准；不添加无关DOS/NEB/资源统计。结果/公式/参考态/条件固定保存，AI数值只能使用服务端Fxx引用，用户文字不能改底层计算。原科学性质面板也可逐角色手工绑定和选择参考类型。

原三查询词形式（complex、surface、adsorbate）继续兼容；多个表面比较使用`adsorbate_query`形式避免角色混淆。没有明确吸附物名称就出缺口，不能假定吸附物。原聊天模型不得替用户选择位点或未经确认的参考类型。

## 验收与范围

合成参考数据：两个表面能量−100/−150，对应复合体系−105/−156，共用H2参考−3eV，应得到−2、−3及B−A=−1eV。数据是测试向量，不是真实LMR结论。

专项覆盖：完整数据/来源/版本、自动三角色/冻结报告、多个位点显式选择及历史、缺参考/未指定吸附物、气相分子独立Gamma网格、组成/原子映射/晶胞错误、带电/SCF失败/ENCUT不兼容、不同参考不消去、旧三查询与公式注入。真实HTTP/SSE与浏览器补齐自然语言吸附比较、缺参考、多位点、人工参考类型确认。

首版不支持重新排序/预弛豫表面的隐式映射，不把组成相等当作充分关系；超过预算或缺历史输入需补证。不支持多个吸附物/分数参考/带电吸附/吸附自由能。Gamma并不能证明孤立分子盒收敛、正确分子构型或自旋基态；表面积/覆盖度/固定层/磁态可比性仍需科研复核。数值校验通过仍不自动授予正式科学结论。真实项目和真实外部模型科学验收未执行。


## 本轮实际验证

330项Python回归通过（吸附专项10、R3 35、R4单元17/真实HTTP-SSE10、聊天22、R2四套及呈现66、其余既有科学/参数/网关/OPT回归170；精确逐套计数见PROGRESS）。类型检查、/tmp/vasp-v1.1.4-stage前端及报告runtime构建通过。R4浏览器新增吸附完整数据、多个位点选择、气相参考人工确认，零页面错误；既有R2与R3两套浏览器也均通过。

专项另实测跨项目分子参考：两个授权项目可复用参考；权限撤销后在任何科学读取前拒绝。首版不自动使用无项目归属的全局aux_molecules库，避免绕过授权项目及原始观测校验；该库如需支持，应按同一模板增加明确权限/来源适配器。
