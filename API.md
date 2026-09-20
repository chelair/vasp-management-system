# 接口文档（API.md）

> 面向**自动化 / 智能体接入**的接口清单与调用约定。
> 基准版本：**v0.8.9** · 维护：本文档由开发助手随版本更新；**与代码不一致时以代码 + 在线 Swagger（`/docs`）为准**。
> 相关：`process.md`（交接文档）、`TODO.md` §13（智能体闭环）/ §14（账号与鉴权）。
> 快速文档：`http://<host>:3001/docs`（Swagger UI）、`http://<host>:3001/openapi.json`。

---

## 1. 基础约定

| 项 | 说明 |
| --- | --- |
| Base URL | `http://192.168.1.20:3001/api`（局域网）· `http://10.147.20.10:3001/api`（ZeroTier） |
| 请求/响应 | JSON（`Content-Type: application/json`）；统一信封 `{"success": bool, "message": str, "data": {...}}` |
| 失败 | HTTP 4xx/5xx 且 `success=false`；`data.errors` 可带明细（例：提交前非空检查会返回缺失文件名） |
| 常见状态码 | `400` 参数/前置不满足 · `404` 任务/项目不存在 · `409` 重复操作（如重复提交、重复 conN） · `500` 服务端异常（含远端命令失败） |
| 时间 | ISO 字符串（服务器时区 `Asia/Shanghai`） |
| 任务状态 | `pending / queued / running / completed / unconverged / zombied / archived` |
| 巡检状态 | `normal / warning / error / low_precision / pending / archived` |
| 认证 | **现状：无鉴权**（内网/ZeroTier 内可直接调用，切勿暴露到公网）。规划见 §2 与 TODO §14 |
| 阻塞 | 全部为**同步** HTTP；长动作耗时见各行动作表（最重 `create-neb-files` ≈ 300s、`create-frac` ≈ 180s） |
| 幂等 | 目前仅 `submit`（重复提交 409）与 `continuation`（重复 conN 409）自带保护；**其余动作重复调用可能重复建目录/重复提交** |
| 审计 | `data/audit_submit.log` 文本行（`_audit_log`），**只覆盖部分动作**（submit / continuation / create-frac / create-neb / upload-* / archive 等） |

```bash
# 通用调用形态
curl -s -X POST http://192.168.1.20:3001/api/jobs/tasks/<task_id>/submit
curl -s http://192.168.1.20:3001/api/projects | jq '.data.projects[0].tasks[0]'
```

---

## 2. 认证与授权（规划中，尚未实现）

> 目标（用户要求）：**先登录才能调用系统**；**每个账号只能管理/查看自己创建的项目**。
> 方案与实施清单见 [`TODO.md` §14](TODO.md)；落地后本文档所有接口都会多出下述约束。

| 接口 | 说明 |
| --- | --- |
| `POST /api/auth/login` | `{username, password}` → `{token, expires_at, user:{name, role}}` |
| `POST /api/auth/logout` | 使当前 token 失效 |
| `GET /api/auth/me` | 当前用户（前端启动时校验登录态） |
| `POST /api/auth/tokens` | 生成**长期 token**（智能体/脚本专用，可设名称、有效期、scope） |
| `GET/DELETE /api/auth/tokens` | 列出/吊销自己的 token |

- 调用方（含智能体）统一带 `Authorization: Bearer <token>`；缺失/过期 → `401`；越权访问他人项目 → `403`。
- 白名单（无需登录）：`POST /api/auth/login`、`GET /api/health`、前端静态资源。
- 所有列表类接口按**项目归属**过滤；单对象接口校验 `project.owner == 当前用户`（`role=admin` 可看全部）。
- HPC 侧仍是同一个 SSH 账号（`mdye@hpc.xmu.edu.cn`），鉴权只控制"谁看/改哪些项目"，不改变算力归属。

---

## 3. 只读接口（观测面）

### 3.1 项目 / 任务

| 接口 | 参数 | 关键返回 | 用途 |
| --- | --- | --- | --- |
| `GET /projects` | — | `projects[]`：`id/name/closed/closedAt/progress/tasks[]`；每个任务含 `task_id/model_name/task_type/status/dir_path/remote_dir/job_id/last_energy/last_check_time` 与 **`check{status,message,checked_at,energy,has_inspection}`**（v0.8.8 起，与巡检中心同口径） | 全量盘点、判断"哪些任务该续算/该收尾" |
| `GET /task-types` | — | 四种任务类型与默认参数、子类型 | 校验动作参数 |
| `GET /servers` | — | 服务器名/主机/队列系统/节点分组 | 多服务器扩展 |
| `GET /health` | — | `uptime/startedAt`（判断后端是否已重启） | 健康检查 |
| `GET /deps` | — | 依赖自检 | 运维 |

### 3.2 巡检结果

| 接口 | 参数 | 关键返回 | 用途 |
| --- | --- | --- | --- |
| `GET /inspections` | — | 前端行：`id/project_name/task_name/group_name/task_category/status/message/detail/task_status/has_inspection/last_check_time/...`（状态优先级：错误 > 警告 > 未检 > 正常 > 关闭） | **智能体判断的主输入**（一条任务一行结论） |
| `GET /inspections/meta` | — | 自动巡检开关、间隔、上次/下次执行时间、调度器状态 | 判断巡检节奏 |
| `GET /inspections/{task_id}` | — | 任务 + 巡检原始数据：`force_history[{step,energy,max_force}]`、`neb_barrier.images[]`、`analysis`（结构/CIF）、`frac_sibling`、`precision`、`incar/kpoints` 快照等 | 取详情做更细判断（力震荡、能垒、精度） |
| `GET /free-energy/{group_id}/summary` | — | 自由能台阶数据（中间体 DFT/矫正项/相对能/收敛） | 自由能路径进度判断 |
| `GET /reports/groups`、`GET /reports/groups/{group_id}/data` | — | 组结构化数据（台阶图/能垒图原始值） | 同上 |

> 原始归档：`data/checks/check_results_*.json`（每轮一份）+ `data/checks/runs.json`（每轮摘要）。需要逐字段（`force_converged`、`precision.issues`、`markers`）时可直接读文件，或走 `GET /inspections/{task_id}`。

### 3.3 集群 / 总览

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `GET /dashboard/overview` | `?refresh=1` 强制重采 | 一次返回整页：统计、运行作业、核数、节点/队列/存储、风险、项目进度、趋势 |
| `GET /dashboard/cores-usage` / `cluster-health` / `risk-alerts` / `trend` | `?refresh=1` | 分块数据（风险预警含 `risks[].advice` 与 `actions.items[]`） |
| `GET /jobs/nodes` | `?refresh=1` | 作业管理节点看板数据（与总览共用一次采集 + TTL 缓存，默认 300s） |

### 3.4 任务文件 / 输入状态

| 接口 | 参数 | 说明 |
| --- | --- | --- |
| `GET /jobs/tasks/{task_id}/files` | — | 本地任务目录文件清单（name/size/modified） |
| `GET /jobs/tasks/{task_id}/files/{filename}` | 白名单文本文件 | 读取文件内容（`INCAR/POSCAR/KPOINTS/POTCAR/CONTCAR/OUTCAR/OSZICAR/...`） |
| `GET /jobs/tasks/{task_id}/input` | — | **输入状态**：`source{con,job_id,synced_at}`、`files{INCAR,KPOINTS,POSCAR,CONTCAR}{text,params/mesh/elements...}`、`draft`、`changes`、`last_applied`、`pending`、`poscar_cif/contcar_cif`（纯本地读取，不发 SSH） |

---

## 4. 动作接口（执行面）

### 4.1 五个核心动作（智能体闭环会用到）

#### ① 提交作业

```
POST /api/jobs/tasks/{task_id}/submit        # 无 body
```

- **行为**：单次 exec 完成「定位最新 conN → 输入文件非空检查 → `bsub < vasp.lsf`」；成功后写 `job_id` + 状态 `queued`（事务内）。
- **前置/守卫**：`job_id` 且状态为 `queued/running` → `409`（勿重复操作）；缺远端目录 → `404`；
  文件检查失败 → **`400` 且不提交**，返回缺失文件名（opt/frac/ele 查 `POSCAR/INCAR/KPOINTS/POTCAR/vasp.lsf`；NEB 查 `INCAR/KPOINTS/POTCAR/vasp.lsf` + 各映像 `POSCAR`）。
- **返回**：`{job_id, new_status, raw_output}`
- **耗时**：1 次 exec（≈1.3–4s）。**幂等**：有 409 保护。**审计**：有。

#### ② 创建续算

```
POST /api/jobs/tasks/{task_id}/continuation   # 无 body
```

- **行为**：远端创建 `con(N+1)`，复制 `CONTCAR→POSCAR`/`POTCAR`/`KPOINTS`/`INCAR`/提交脚本，`WAVECAR` 用 `mv`（移动语义），`INCAR` 改 `ISTART=1/ICHARG=0` 并应用待生效草稿；NEB 走映像续算（带端点 `OUTCAR`、各映像 `WAVECAR`）；登记隐藏续算子任务。
- **前置/守卫**：续算子任务（`dir_path` 带 `conN`）→ `400`；任务类型非 `opt/neb` → `400`；重复 `conN` → `409`；
  **有活跃作业 → 不建目录、不动文件**，正常返回 `action="running"`。
- **返回（关键字段 `action`）**：`created`（真正建了目录）· `running` · `input_complete_but_not_finished` · `input_incomplete`；另有 `con/remote_dir/source_dir/incar_changes/copied_files/warnings`。
  ⚠️ **自动化里必须判 `action`，不要以 HTTP 200 当作"已创建"。**
- **耗时**：单次远端脚本 ≈3.5s。**幂等**：有 409 保护。**审计**：有。

#### ③ 修改 INCAR（4 个粒度，按需选）

| 目的 | 接口 | body | 说明 / 风险 |
| --- | --- | --- | --- |
| 记草稿（**推荐**） | `PUT /api/jobs/tasks/{task_id}/input/draft` | `{file:"INCAR", params:{KEY:"value", ...}}` | 只改本地库，**不碰远端**；下次续算应用，可逐项/整文件撤销。空值 = 撤销该项 |
| 生成到本地 | `PUT /api/jobs/tasks/{task_id}/files/{filename}` | `{content:"..."}` | 只写本地 `files/INCAR`（白名单文件名） |
| 同步到远端 | `POST /api/jobs/tasks/{task_id}/upload-incar` | `{params:{...}}` 或 `{content:"..."}` | 定位最新 conN → 备份 `old_INCAR` → **立即写远端** → 台账标 `applied_in="remote"`；返回 `{dir, backup_file, warnings, applied[], state}` |
| 撤销草稿 | `DELETE /api/jobs/tasks/{task_id}/input/draft/{file_name}` | — | `file_name` = `INCAR` / `KPOINTS`（整文件撤销） |

- 单值参数直接给值；多值参数（如 `MAGMOM = 5*2.0`、`DIPOL = 0.5 0.5 0.18`）**整串保留**；`.T.`/`.TRUE.`、`1E-6`/`1e-6` 视为等价不会误判改动。
- `EFIELD` 按 VASP 定义是**单个数值**（eV/Å），方向由 `IDIPOL` 决定；`NCORE` 默认留空（不写入）。
- 耗时：draft / 本地文件为纯本地 IO（快）；`upload-incar` 走 SSH（≈1.3–4s）。

#### ④ 自由能频率计算生成（frac 输入）

```
POST /api/jobs/tasks/{task_id}/create-frac    # body: {"ibration": 5}（可省，默认 5）
```

- **行为**：从 opt 任务最新输出生成频率矫正（frac）输入：`CONTCAR→POSCAR`、复制 `POTCAR/KPOINTS`，默认 `ISYM=0/SIGMA=0.05/NSW=1/IBRION=5/NFREE=2/POTIM=0.015`；回填 frac 子任务的 `input_source/notes`。
- **前置**：任务必须是 `opt`（否则 `400`）；必须已存在 `<结构目录>/frac` 子任务（自由能组创建时自动登记，否则 `404`）。
- **返回**：`{frac_dir, source_dir, latest_dir, incar_changes, copied_files}`
- **耗时**：远端 bash **timeout 180s**。**审计**：`create-frac`。

#### ⑤ NEB 创建计算文件

```
POST /api/jobs/tasks/{task_id}/create-neb-files
body: {
  "initial_opt_task_id": "...",     # 必填，必须是 opt
  "final_opt_task_id": "...",       # 必填，必须是 opt
  "num_images": 3,
  "params": {"IOPT":3,"LCLIMB":".TRUE.","ICHAIN":0,"SPRING":-5,"MAXMOVE":0.2,"POTIM":0}
}
```

- **行为**：以 IS INCAR 为基底只改 NEB 参数 → 远端 `nebmake.pl` 线性插值生成 `00..NN` 映像目录与文件。
- **前置**：任务必须是 `neb`（否则 `400`）；初/末态任务必须存在、类型为 `opt`（否则 `404`/`400`）；
  **初/末态必须 `status=completed`**，否则 `400`（"优化未收敛，请先完成结构优化"）。
- **返回**：`{neb_dir, source_is, source_fs, num_images, images[], incar_changes, copied_files}`
- **耗时**：远端 `nebmake.pl` **timeout 300s（最重）**。**审计**：`create-neb images=N`。

### 4.2 巡检动作

| 接口 | body | 说明 |
| --- | --- | --- |
| `POST /inspections/run` | `{project_name?: str, task_id?: str}` | 立即巡检（可限定项目/任务）；返回 `{run_id, checked_at, inspected, updated, unchanged, warnings, rejected, skipped_projects, failed_batches, archived_files, scope}`；全局巡检约 75–90s |
| `POST /inspections/run-single/{task_id}` | — | 单任务巡检（约 12–15s）；归档任务返回 `400` |
| `PUT /inspections/auto` | `{enabled: bool, interval_hours?: number}` | 自动巡检开关（写 `settings.json`，后台 60s 轮询判定） |

### 4.3 其他写接口（简表）

| 分类 | 接口 | 备注 |
| --- | --- | --- |
| 作业 | `POST /jobs/tasks/{id}/stop` | `bkill`；"already finished" 按成功处理；**高风险** |
| 作业 | `POST /jobs/tasks/{id}/archive` · `/unarchive` | 归档/重开（自由能主任务连带 frac） |
| 作业 | `POST /jobs/tasks/{id}/build-ele-inputs` | ele 输入（`{source_type:"opt"/"external", source_task_id?, ...}`） |
| 作业 | `POST /jobs/tasks/{id}/selective-dynamics` | 固定原子生成新 POSCAR（`{manual/indices/elements/z_range/..., sync_remote?}`） |
| 作业 | `POST /jobs/tasks/{id}/upload-poscar` · `/upload-kpoints` · `/upload-submit-script` · `/generate-potcar` | 写远端最新目录，同名先备份 `old_*` |
| 作业 | `POST /jobs/tasks/{id}/input/sync` | 从远端重新取回四件套（1 exec + 4 SFTP；会覆盖本地镜像，有草稿的文件跳过） |
| 作业 | `PATCH /jobs/tasks/{id}` · `DELETE /jobs/tasks/{id}` | 重命名 / 删除（本地进回收站，**远端不删**） |
| 项目 | `POST /projects` · `POST /projects/{id}/close` · `/reopen` · `DELETE /projects/{id}` | 关闭要求可见任务全部归档 |
| 组 | `POST /groups` · `POST /groups/{id}/structures` · `POST /groups/tasks` | 建自由能/NEB 组、加结构、建独立任务 |
| 报告 | `POST /reports/project/generate` (`{project_id?, all?}`) · `GET /reports/project/list` · `/{id}` · `/{id}/structured` · `/{id}/markdown` · `/{id}/export.html` · `DELETE /{id}` | 分项目报告（同项目重生成覆盖） |
| 配置 | `PUT /settings/root-paths` · `PUT /path-mapping` · `POST /path-mapping/rebase` · `PUT /ssh/config` · `POST /ssh/test` | 运维类，**权限敏感** |
| 分析 | `POST /jobs/tasks/{id}/analysis/pdos` · `/calculate-correction` | PDOS / 自由能矫正项 |

> 未列全的请求体字段以 `/docs`（Swagger）为准；本文档只覆盖接入常用面。

---

## 5. 智能体闭环：巡检 → 判断 → 执行（建议用法）

目标：**只读为主、动作最少、影响最小**。三个阶段各自的推荐调用：

```text
① 巡检（观测）
   POST /inspections/run                     # 或等自动巡检（默认 2h）
   GET  /inspections                         # 每个任务一行结论（status/message）
   GET  /inspections/{task_id}               # 需要细节时：force_history / neb_barrier / precision

② 判断（零副作用）
   规则化：status 为 unconverged/low_precision/warning → 记录，不动作
            输入文件齐全且 status=completed 且无活跃作业 → 候选"续算"
            opt completed 且自由能组里 frac 未生成 → 候选"create-frac"
            IS/FS 均 completed 且 NEB 无映像文件 → 候选"create-neb-files"
            连续两轮无变化 → 停止跟进而非反复动作

③ 执行（受控）
   POST /jobs/tasks/{id}/continuation        # 看返回的 action 字段判断是否真的创建了 conN
   POST /jobs/tasks/{id}/input/draft         # 改参数优先走草稿（下次续算生效、可撤销）
   POST /jobs/tasks/{id}/submit              # 需要真正占算力时才提交（最需谨慎）
```

**低影响原则（建议写进策略）**

1. 默认**只做只读判断**；动作必须来自白名单（建议：`continuation` / `input/draft` / `create-frac` / `inspection` / `report`），`submit` / `stop` / `delete` / `archive` 需人工确认。
2. 每个任务每轮巡检**最多一个动作**；同一任务两次动作之间设**冷却时间**（建议 ≥ 巡检间隔）。
3. 动作前先做**前置校验**（现有端点自带：文件齐全、初末态收敛、活跃作业拦截）；失败只记录不改状态。
4. 所有动作写**动作台账**（建议 `data/agent/actions.jsonl`：时间 / 触发依据（巡检 run_id + 结论）/ 动作 / 参数 / 结果），便于回放与追责。
5. 幂等：同一 `(task_id, action, 触发证据)` 只执行一次；HTTP 200 不代表成功，必须看业务字段（`action`、`applied`、`failed_batches`）。

**现状缺口（接自动化前需要补）**

| 缺口 | 影响 | 建议 |
| --- | --- | --- |
| 无鉴权 | 谁都能调（含提交/删除） | 先做 TODO §14 的认证；智能体用**独立长期 token**（`role=agent`） |
| 无 dry-run | 动作直接落盘/占算力 | 增加 `?dry_run=1`（只跑 preflight 返回"将会发生什么"） |
| 无幂等键 | 重试可能重复建目录/重复提交 | 加 `Idempotency-Key` 请求头 |
| 长动作同步阻塞 | 300s 占住连接、超时易重试 | 加 `run_id` + 轮询（异步执行） |
| 审计不全 | 追责/回放困难 | 统一动作台账 + 审计带用户名 |
| 无调度触发 | 只能由 UI 触发 | 复用 `inspection_scheduler` 的后台线程模式，新增 `agent_scheduler`（默认关闭，显式开启） |

---

## 6. 维护约定

- 每次版本提交（`process.md` §7 新增条目）时同步更新本文档：新增/变更接口、body 字段、前置条件、耗时与风险级别。
- 本文档只描述**对外可见的 HTTP 面**；内部函数（`inspection_runner`、`continuation`、`input_state` 等）见 `process.md` §4。
- 变更接口时优先改代码 → 再更新本文档；发现不一致以代码 + `/docs` 为准并立即回来修正。
