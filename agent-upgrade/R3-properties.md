# R3：科学性质定义、数据发现与计算验证

2026-10-20 开始；用户授权开发，完成后停止。生产仍为 v1.1.2，本轮不部署或推送。

目标：以 LMR 与 LIC@LMR 中性单氧空位形成能比较为主验收，实现轻量 PropertyRecipe、只读候选发现、精确任务/观测绑定、缺口报告、Python 确定性运算及冻结来源。支持相对能量、简单吸附能、已有NEB能垒、功函数差异。未知性质返回 UNSUPPORTED；模型不得提交公式或替代能量数值。

边界：不建模、不触发分析计算/SSH/巡检、不创建或提交HPC任务、不接自主执行。跨项目逐个鉴权；名称只提供候选。历史巡检没有可靠结构/POTCAR/收敛证据时保留缺口，不用当前镜像填历史记录。新增巡检元数据只读采样固定文件，同一工作目录，不改变状态和结构同步条件。

本地实现与隔离验收已完成；未部署、未提交/推送，完成本阶段后停止。

## 实现合同

- 注册表 `backend/properties.py:PropertyRecipe` 为五个固定配方：`oxygen_vacancy.neutral_single`、`relative_energy`、`adsorption.simple`、`neb.barrier`、`work_function.difference`。公式/版本/单位/检查和缺失策略可查询；不接受自定义公式、函数名或替代任务能量。未注册性质为 `UNSUPPORTED`。
- 发现服务按1–8个项目逐项鉴权；按模型名/类型查候选，或task_id绑定。名称即使唯一也不自动建立结构关系。每项输入记录 AVAILABLE/MISSING/INCOMPLETE/INVALID/STALE/AMBIGUOUS/UNKNOWN；多conN需observation_id。更新/淘汰的ID拒绝使用，旧目录/过期观测不拼到当前状态。
- 复用原始 `collect_task_observations`、`ai_inspections.query_inspections/participation`、完整INCAR解析、VASP5布局解析、既有功函数解析器和平台规则、R2候选目录及项目权限。没有新增状态库、调度器、模型连接或HPC通道。
- `batch_check.py` 新增固定目录只读科学采样，随原巡检批次归档；不新增SSH调用、不改巡检状态/结构同步条件。采集POSCAR/INCAR/KPOINTS、逐元素POTCAR哈希与ZVAL、OUTCAR必要回显/能量/结束标记及OSZICAR电子周期。OUTCAR保留筛选后的科学行，哈希标明全文件或头尾样本；不保存POTCAR原文。文件稳定性及输入晚于输出均检查；不回退主目录补conN证据。
- 数值统一为 `VASP.free_energy.TOTEN` (eV)，与最后完整OSZICAR F核对。电子收敛采用最后周期dE/dε、EDIFF和NELM；离子力收敛、正常退出、既有精度失败分别检查。NSW=0只可解释为固定几何电子能，单独记录未验证弛豫条件。数值网格收敛研究、基态/磁态及物理适用性仍为NOT_TESTED，不自动升级为正式科学结论。
- 中性用运行时NELECT与POTCAR ZVAL/组成核对；单O缺失检查组成、相同晶胞（1e-5Å）、按原输入顺序逐原子坐标/约束对应（1e-4Å），返回移除O序号/分数坐标。多个任务/位点保持候选；`removed_oxygen_index`只能缩小可证明的位点。模型名完全不参与缺陷判定。带电模型阻断，并列出费米能级、带边、势对齐、有限尺寸修正等需求。
- 理论设置比较ENCUT、泛函、全元素LDAU/U/J、共同元素POTCAR数据集哈希、完整k网格/模式/位移，以及自旋、色散、杂化/电场/偶极等设置；显式关键输入必须有OUTCAR运行时回显。不推测不同k网格或不同晶胞等效性。
- `mu_O`必须由人工API/页面明确设置每个O的数值、来源和适用条件。聊天工具不提供这个数值字段。缺mu_O时没有绝对形成能；用户声明共同参考条件且四个任务全部通过时，Python计算 B−A，说明mu_O消去。每个可独立验证的体系仍可单独形成结果；缺一个模型不会抹掉另一体系已通过的绝对结果。
- 相对能量要求相同组成；简单吸附能要求复合体系=洁净表面+一个吸附物的组成平衡，不冒充含温熵/溶剂/电位修正的自由能。NEB要求IMAGES+2完整连续映像、每映像的同次证据/收敛/能量核对；路径比较需要明确反应/方向/端态对应和可比设置。功函数复用已有电位曲线，核对目录/时间、真空轴和用户明确的表面侧，至少5点平台极差≤0.05eV、真空−费米能级与已有功函数一致。
- 每份派生报告保存到独立 `data/reports/properties/prop_<uuid>.json`，原子写入（临时文件0600），包含原始观测冻结副本、输入/来源哈希、公式版本、单位、参考态、数值和条件。读取重新鉴权全部项目；不覆盖原始数据或旧报告。模型返回紧凑摘要，完整证据留在报告，不把大原子数组塞进每轮上下文。

## 使用入口

智能报告选择项目 → **科学性质**。默认LMR与LIC@LMR两个目标；检索可添加跨项目范围，按模型名搜索全部候选，逐角色选择任务。第一次验证若发现多个计算目录，可继续选择观测ID。明确共同氧参考条件或设置mu_O后再验证。可以添加体系/不同位点，查看部分结果、逐项缺口、必要补证/补算建议，下载同一冻结JSON。改输入后旧结果保留但标记需重验，禁止下载为当前结果。

AI工作台（项目文件工具已启用）：`get_property_recipes` → `discover_property_tasks` → `evaluate_property`。本轮用户、当前会话项目和任务每次重查；聊天不跨项目，不接受mu_O/公式/能量覆盖。跨项目使用人工科学性质面板/API。工具不创建任务、不提交作业。

报告元素列表来自现有R2候选目录，另外提供冻结R3结果JSON产物；没有宣称新增R2 `property.result`渲染器，没有自动将性质结果插入专题报告。

## API

- `GET /api/properties/recipes`
- `GET /api/properties/discover?project_ids=<id>&query=<model>&task_type=opt&task_id=<id>`（project_ids可重复；最多100候选，超出可按模型名继续检索）
- `POST /api/properties/evaluate`：人工登录，计算及保存派生报告。
- `GET /api/properties/reports/{report_id}`：读取冻结报告，每个关联项目重新校验权限。

```json
{
  "property_id": "oxygen_vacancy.neutral_single",
  "project_ids": ["PROJECT_ID"],
  "targets": [
    {"label":"LMR", "pristine":{"task_id":"PRISTINE_A"}, "defect":{"task_id":"DEFECT_A"}},
    {"label":"LIC@LMR", "pristine":{"task_id":"PRISTINE_B"}, "defect":{"task_id":"DEFECT_B"}}
  ],
  "common_oxygen_reference": true
}
```

绝对形成能另加 `mu_O: {value_ev, source, conditions}`（每O，不是O2总能量）。跨项目selector可带project_id且必须在project_ids中；多个目录另带observation_id。所有未知字段/公式/能量覆盖返回400；无权限403；未登录401。结果报告状态为AVAILABLE/PARTIAL/BLOCKED，未注册配方UNSUPPORTED；输入状态与科学结论验证状态分开。

## 明确限制

- 历史记录没有R3快照时会显示缺证；不会用现有本地镜像伪造历史结构/参数，也不会自动连远端回填。部署后的正常巡检才开始产生新元数据。
- 首版只验证正单一缩放、元素物种不重复的VASP5结构与自动Gamma/Monkhorst网格；重复元素物种不自动折叠其赝势/U身份。重新排序、预先弛豫/重建导致输入原子无法逐项对应时UNKNOWN；暂不提供任意原子映射确认或结构修改能力。
- 单文件输入64KiB，POTCAR24MiB；OUTCAR头尾各48KiB、OSZICAR头尾各8KiB，NEB最多32映像。必要回显不在样本内、端点缺输出等情况都保留缺口，不伪装已通过。
- POTCAR哈希记录捕获的输入数据集，OUTCAR标题/参数回显与修改时间用于交叉核对；不是VASP启动时对所有输入逐字节的签名证明。没有额外数值收敛/磁态/模型适用性证据时，数值运算PASS仍不授予正式科学结论。
- 仅做规定公式下的电子能性质；不处理带电缺陷修正、自动氧化学势温压建模、复杂吸附计量/自由能、缺失NEB或功函数的计算，也不进入自主执行下一阶段。

## 测试与交付状态

开发和所有验证仅使用临时DATA_DIR、合成结构/输出和Mock模型/SSH；未将合成值当作真实LMR性质。最终实际测试与Git状态见PROGRESS §22。本轮不部署、不重启、不推送，生产v1.1.2和科研数据保持原状态；用户两份文档删除不恢复、不夹带。


### 实际执行结果

- R3专项 **35项通过**，覆盖A–L、五类配方的实际数值、完整U数组/赝势/k位移/运行时精度差异、重复物种防合并、输入稳定性/符号链接、原始文件未变、跨项目预鉴权、冻结读取及真实HTTP401/400/保存读取。
- 独立回归：参数证据26、AI巡检5、结构同步13、R2科学Adapter8、R2元素14、R2组合18、AI聊天22、受控网关58、OPT闭环47、工程基线10，均通过。普通discover显示Ran57 OK、9个独立套件占位skip；专项已独立运行，不将skip或重复执行累加成通过总数。
- R3真实页面+临时认证API浏览器通过：四任务绑定、无mu_O阻断、共享参考仅差值、显式mu_O后两绝对值及差值、同一冻结JSON下载、改输入禁止当前下载，页面异常0。R2真实编辑/API/HTML/PDF/冻结/冲突/电子图表浏览器回归通过。
- TypeScript通过；最终Vite产物在 `/tmp/vasp-r3-final-build`，没有覆盖生产dist；保留原有大chunk提示。Git diff空白检查通过。
- 合成样例E_pristine/defect为(-100,-92)和(-150,-141)eV，人工mu_O=-5eV/O时得到3、4eV及B−A=1eV。缺mu_O并确认共同参考时只得到1eV差值。**这些是测试数值，不是实际LMR/LIC@LMR研究结果。**

### 文件范围

- 新增后端：`backend/properties.py`、`property_science.py`、`property_tools.py`、`routers/properties.py`。
- 修改后端：`batch_check.py`（固定科学元数据）、`main.py`（路由）、`ai_workspace.py`与`ai_chat_service.py`（受限工具与规则）。
- 新增前端：`src/api/properties.ts`、`src/components/reports/ScientificPropertiesPanel.tsx`；修改 `src/pages/Report.tsx` 添加入口。
- 新增测试：`tests/r3_fixtures.py`、`test_properties.py`、`r3_browser_server.py`、`browser/scientific-properties.cjs`；修改 `test_ai_chat.py` 的工具清单合同。
- 文档：本文件、AGENTS、README、API、process、MODEL_WORKSPACE、REPORT_REVIEW及PROGRESS。

### 验收与后续依赖

R3本地阶段验收满足：数据充分按固定公式正确计算，不足给具体缺口，条件成立时独立给部分结果，无法验证的数据不变成正式结论。真实项目科学验收仍依赖用户选择实际任务、可靠R3观测/参数/结构、明确参考条件，以及所需数值收敛/物理模型验证；当前没有声称已完成生产科学验收。后续若部署需要另获授权并沿用单writer及隔离构建流程；本阶段不继续研发下一阶段。

Git交付：基线HEAD为 `922677b`；R3代码/文档留在工作区待审阅，未创建提交、标签、推送或部署。用户原有 `待办.md`、`问题.md` 删除保持原状。
