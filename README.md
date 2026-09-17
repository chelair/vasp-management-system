# VASP 计算项目管理系统 · 前端框架

基于 **React 18 + TypeScript + Vite 7 + Ant Design 5 + Framer Motion** 的 VASP 第一性原理计算项目管理系统前端。

当前版本（v0.8.4）：四个核心模块（总览 / 巡检中心 / 作业管理 / 智能报告）+ SSH 连接配置界面；
**项目 CRUD、巡检、作业提交/停止/续算、文件构建、SSH 连接池、结构 3D 视图与分项目报告生成均已接入真实后端**
（Python + FastAPI + Paramiko，流程对齐参考实现 `add_project.py` / `check_remote.py`），
总览页已是集群实时视图（bjobs 作业、blimits 核数配额、bhosts/bqueues 节点队列、df 存储），
**前端不再有 Mock 数据**（`src/data/mock/` 仅保留编辑器默认参数与 VASP 输入文件模板）。

> 跨窗口交接看 `process.md`（版本、改动记录、已知坑、待办）；`TODO.md` 为历史清单，个别条目已过时。
> **换机器/换系统（Windows → Linux）看 [`MIGRATION.md`](MIGRATION.md)**：要打包什么、迁移后改哪 11 项、怎么验收。

> 注意：本项目放在 `D:\Skill\vasp-project-manager-web`。旧项目 `vasp-project-manager` 仅作为**功能迁移参考**，
> **运行时不依赖旧项目目录**——真实数据（项目库、配置、本地项目目录、备份、巡检结果）已全部迁入本项目
> `data/`，系统自包含，打包部署不会漏文件。

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 框架 | React 18 + TypeScript |
| 构建 | Vite 7（已配置 `host: true`，支持局域网访问） |
| UI | Ant Design 5 + 自定义设计令牌（主色 `#5B8DEF`，辅助色 `#67C6B0`） |
| 图表 | ECharts 6（按需注册：圆环/折线/柱/散点，见 `src/components/dashboard/useEcharts.ts`） |
| 动画 | Framer Motion（页面切换淡入淡出 + 卡片悬停上浮） |
| 路由 | React Router 7 |
| 后端 | Python + FastAPI（Uvicorn 运行，端口 3001，自带 Swagger 文档 `/docs`） |
| SSH | Paramiko（密钥认证远程目录同步） |
| 存储 | 文件型 JSON：`data/projects.json` + 本地目录 + 自动备份（不用数据库） |
| 数据 | 项目 / 巡检 / 作业 / SSH 走真实后端（`data/` 文件型 JSON）；仅智能报告为 Mock（`src/data/mock/`） |

## 开发约定

### SSH：统一走连接池，禁止自行创建客户端

所有远端命令 / 文件操作（执行命令、上传、下载、递归建目录）**必须**通过统一 SSH 模块
`backend/ssh.py` 的连接池完成，禁止在业务代码里直接 `paramiko.SSHClient()`：

- `run_remote(server, cmd, timeout)`：执行远端命令，返回 `{stdout, stderr, exit_code}`；
- `upload_file` / `download_file` / `mkdir_remote`：文件传输与建目录；
- 连接池行为：常驻连接 + 每 30s 传输层 keepalive + 每 60s 应用层保活（echo ok 实测
  往返延迟，经 `/api/ssh/status` 的 `latencyMs` 实时回传前端展示）+ 空闲 5 分钟自动回收
  + 断线自动重连（3 次重试），
  同一服务器命令串行化（避免并发抢占一条连接）；
  `upload_file` / `download_file` / `mkdir_remote` 与命令执行共用同一条常驻连接，
  **不要**自行新建/关闭连接（早期版本每次新建连接，单次上传就要 3s 左右）。

新增任何需要访问远端的功能（巡检、续算、提交、停止、文件构建等）都必须复用 `ssh.py`，
不要在各自模块里另起连接逻辑。

### 批量远端操作：合并为一次 exec

实测 HPC 登录节点每条 `exec_command` 通道都有约 1.3-2s 的 shell 启动开销（即使命令只是
`true`）。因此**多步远端文件操作必须合并进单次调用**，不要把“查目录 → 检查文件 → 复制 →
回传内容 → 列目录”拆成多次 SSH。参考实现：`continuation.py` 用
`_remote_script(server, bash_script)` 把整段 bash 脚本 base64 后一次执行，脚本内用
`===STATE===` / `===FILES===` 等标记输出分段，本地解析后再用池化 SFTP 上传修改后的文件
（续算实测从 10-15s 降到约 3.5s）。

### 远端命令写法

- **默认使用 `bash -c`（非登录 shell）**；不要用 `bash -lc`——登录 shell 会加载用户
  `.bashrc` 等环境，实测慢 4 秒以上且带出 conda 等噪音输出。
- 需要 LSF 环境（`bsub` / `bkill` / `bjobs`）时显式 `source <profile.lsf>`（路径取
  `servers.json` 的 `lsf_profile`，缺省 `/opt/ibm/lsfsuite/lsf/conf/profile.lsf`）。
- **远端路径必须统一正斜杠**：Windows 上 `str(Path(...))` 会输出反斜杠，远程命令会把它
  当成文件名字符（曾导致服务器误建 `\data\...` 目录）；统一用
  `resolve_remote_path(server, rel)` 解析，必要时 `.replace("\\", "/")`。
- 命令通过 `exec_command` 按 UTF-8 编码发送，输出按 UTF-8 解码，中文路径/输出安全。

## 快速开始

环境要求：**Node.js ≥ 20.19**（开发机当前为 Node 24）+ **Python ≥ 3.11**（开发机为 3.12）。

```bash
cd vasp-project-manager-web
npm install
npm run server    # 终端 1：启动后端 API（端口 3001）
npm run dev       # 终端 2：启动前端开发服务器（端口 5173）
```

浏览器打开 http://localhost:5173 即可使用。「新增项目」会真实调用后端完成校验、优先级计算、本地目录创建与数据库写入。

真实数据已迁移到本项目 `data/`（`projects.json` + `config/` + `projects/` + `backups/` + `checks/`），
默认 `npm run server` 即为真实数据模式：总览 / 巡检 / 新增项目都作用于真实项目（如 Ag_20260830）。

> 数据目录可用 `python backend/run.py --data-dir <目录>` 覆盖（测试隔离 / 其他机器部署时使用）。
> `data/` 为运行时数据（已 gitignore），**打包部署时需连同 `data/` 一起复制或单独备份**，否则会丢失项目数据。

首次使用后端前安装 Python 依赖（核心依赖 fastapi / uvicorn / paramiko）：

```bash
python -m pip install -r requirements.txt
```

后端启动时会**在后台检查依赖**：核心依赖缺失会提示安装命令，可选依赖（pymatgen / ase /
apscheduler / openai）缺失只提示、不影响当前功能；前端顶部也会显示同样的提示条。

> 未启动后端时页面显示空数据（已清理演示项目，不再回退 Mock 项目/巡检数据）。
> 后端在线时可直接打开 http://localhost:3001/docs 查看 FastAPI 自动生成的接口文档。

## 在 A 电脑运行，B 电脑通过局域网访问

1. 在 A 电脑启动 `npm run dev`（Vite 已配置监听 `0.0.0.0`，启动时会打印 Network 地址）。
2. 在 A 电脑查询局域网 IP：

   ```powershell
   ipconfig
   ```

   例如本机局域网 IP 为 `172.18.83.222`，则启动日志会显示：

   ```text
   Local:   http://localhost:5173/
   Network: http://172.18.83.222:5173/
   ```

3. B 电脑（同一局域网 / 同一 Wi-Fi，且未开启访客网络隔离）直接访问：

   ```text
   http://172.18.83.222:5173
   ```

4. 如果 B 电脑无法访问，通常是 Windows 防火墙拦截了 Node.js。在 A 电脑以管理员身份打开 PowerShell，放行 5173 端口：

   ```powershell
   netsh advfirewall firewall add rule name="VASP Web 5173" dir=in action=allow protocol=TCP localport=5173
   ```

   或者：防火墙 → 允许应用通过防火墙 → 勾选 Node.js（专用网络）。

## 不在同一局域网时：内网穿透

任选一种工具，把 A 电脑的 5173 端口映射为公网地址，B 电脑通过公网地址访问：

**cpolar**（推荐，国内访问快）

```bash
cpolar http 5173
```

**ngrok**

```bash
ngrok http 5173
```

**frp（自建服务器）**

frpc.ini：

```ini
[common]
server_addr = 你的服务器IP
server_port = 7000

[vasp-web]
type = tcp
local_ip = 127.0.0.1
local_port = 5173
remote_port = 5173
```

> 安全提示：当前为演示版本、无用户认证，公网暴露时建议仅临时使用，或为隧道增加访问密码 / 认证。

## 构建与部署（生产模式）

```bash
npm run build       # 产出 dist/
npm run server      # FastAPI 同时托管 API 和 dist/，单端口 3001 访问
```

此时浏览器直接访问 http://localhost:3001 或局域网 `http://<本机IP>:3001`；
也可用 `npm run preview` 只预览前端（4173 端口），或将 `dist/` 放到 Nginx / IIS 托管并单独反代 `/api`。

## 目录结构

```text
vasp-project-manager-web/
├── index.html
├── vite.config.ts          # host:true（局域网）+ /api 代理 + 分包优化
├── package.json
├── requirements.txt        # Python 依赖（核心 + 可选，运行时检查缺失）
├── backend/                # ★ 后端 API（Python + FastAPI）
│   ├── run.py              #   启动入口：python backend/run.py
│   ├── main.py             #   FastAPI 应用（统一信封/错误翻译/静态托管 dist）
│   ├── routers/            #   /api/projects、/api/servers、/api/task-types、/api/deps
│   │                       #   + /api/ssh/config、/api/inspections
│   ├── models.py           #   Pydantic 输入模型（对齐 schemas.py 校验规则）
│   ├── priority.py         #   工作量/紧急度/优先级象限（对齐 priority.py）
│   ├── storage.py          #   文件型数据库（原子写入 + 自动备份 20 份）
│   │                       #   + 任务状态机（对齐 project_db.py）
│   ├── ssh.py              #   远程执行/上传/下载（Paramiko，含本地模拟模式）
│   ├── batch_check.py      #   服务器端批量检查脚本（自动上传，解析 bjobs/OUTCAR/力收敛）
│   ├── inspection_runner.py#   巡检编排（筛选→上传→远程解析→回填→归档）
│   ├── checks_store.py     #   巡检结果存取（data/checks/）与前端行映射
│   ├── dependencies.py     #   运行时依赖检查（后台执行 + 提示安装）
│   └── defaults/           #   服务器/设置/任务类型默认配置
├── data/                   # ★ 运行时数据（默认空库，不再写入演示项目；已 gitignore）
│   ├── projects.json       #   项目数据库（存在 project_db.json 时优先读真实系统库）
│   ├── config/             #   servers.json / settings.json / task_registry.json
│   ├── projects/           #   每个项目的本地目录结构
│   ├── backups/            #   数据库自动备份（保留 20 份）
│   └── checks/             #   巡检结果 check_results_*.json + runs.json
├── scripts/
│   └── make_mock_fixtures.py # 生成本地模拟远程目录夹具（离线测试巡检用）
└── src/
    ├── main.tsx            # 入口（ConfigProvider + Router + 动画容器）
    ├── App.tsx             # 路由 + AnimatePresence 页面切换动画
    ├── styles/global.css   # 全局设计令牌与样式（颜色/字体/间距/响应式）
    ├── theme/index.ts      # Ant Design 5 主题令牌
    ├── types/index.ts      # 类型定义（与后端字段对齐）+ 文案映射
    ├── utils/format.ts
    ├── hooks/              # useClock（顶栏时钟）
    ├── context/SSHContext.tsx  # SSH 全局状态（连接/测试/配置，供顶栏实时联动）
    ├── api/                # ★ 数据访问层：项目/巡检/作业/报告/SSH 全部走真实后端
    │   ├── client.ts       #   统一延迟/请求封装位置
    │   ├── projects.ts
    │   ├── inspections.ts
    │   ├── reports.ts
    │   └── ssh.ts          #   SSH 服务器配置 + 真实握手测试（POST /api/ssh/test）
    ├── data/mock/          # ★ 编辑器默认参数 + VASP 输入文件模板（无业务 Mock 数据）
    ├── components/
    │   ├── layout/         # 侧边栏、顶栏、整体布局、Logo
    │   ├── common/         # 统计卡片、状态标签、进度条、页面头等
    │   └── dashboard/      # 总览：运行任务/核数圆环/集群健康/风险预警/趋势/项目四象限（useEcharts）
    └── pages/              # 模块页面
        ├── Dashboard.tsx   # 总览
        ├── Inspection.tsx  # 巡检中心
        ├── Jobs.tsx        # 作业管理
        ├── Report.tsx      # 智能报告
        └── SSH.tsx         # SSH 连接配置
```

## 模块说明

### 总览 Dashboard

v0.6.0 按「状态 → 资源 → 趋势 → 明细」四层重构，数据全部来自真实后端 `/api/dashboard/*`：

- **顶部状态栏**：项目总数 / 异常警告项（点卡片跳巡检中心）/ 今日完成（含较昨日）/ 运行中任务（点卡片展开下方列表）
- **快捷操作**：新建项目、触发全局巡检、刷新集群状态（强制重新 SSH 查询，带 loading 反馈）
- **运行中任务**（核心新增）：`bjobs` 实时作业表——任务名 / 所属项目 / 队列 / 核数（悬停看节点分布）/ 作业号 / 状态，点行跳转 `/jobs?task=`
  ；表格**固定高度 320px 内部滚动**（作业变多不会把模块撑高）
- **核数占用**：ECharts 圆环，中心 `已用 / 总核数`（如 `144 / 200`）+ 剩余核数，外圈按项目着色，
  使用率 ≥90% 橙色、≥100% 红色闪烁；上限取 `blimits` 配额（`settings.json: dashboard_total_cores` 可手动覆盖），
  取不到时退回 bjobs 汇总
- **计算资源趋势（近 7 天）**：核数占用（面积线，左轴）+ 运行中任务（线，右轴）+ 每日提交作业数（柱）
- **集群健康与资源**：节点状态灯（正常 / 满载 / 关闭 / 宕机）、队列拥堵（PEND/RUN + 占比条）、
  项目根所在文件系统容量（剩余 <15% 变红告警）
- **任务健康与风险预警**：未收敛需续算、Zombie 需重新提交、巡检发现异常，点条目跳作业管理 / 巡检中心
- **项目进度**：四象限气泡图（横轴时间进度、纵轴完成度、气泡大小=任务数、对角线为预期进度）+ 进度列表（逾期/落后提示）
  已关闭项目收进「已关闭项目（N）」折叠区（灰显，可重新打开）；项目下可见任务全部归档后可在此「关闭项目」
- **最近更新的任务**：按项目轮转取样，点行跳转作业管理

刷新策略：打开页面加载一次 → 每 30 分钟自动刷新；集群查询在服务端缓存 5 分钟（`settings.json: dashboard_cache_seconds`）。
集群命令可在 `servers.json` 覆盖（`node_status_cmd` / `queue_status_cmd` / `user_used_cores_cmd` /
`user_total_cores_cmd` / `storage_check_cmd`，`{storage_path}` 会替换为项目远程根）。

### 巡检中心 Inspection
- 状态筛选胶囊（全部/正常/警告/错误，带计数）
- 关键词搜索 + 类别筛选（收敛性/资源/文件/SSH/队列）+ **分析范围筛选**（全部 / 需结构分析）
- 「立即巡检」按钮：真实调用后端（筛选任务 → 上传 batch_check → 服务器批量解析 → 状态机回填 → 归档）
- **按项目分块展示**（v0.6.2）：每个项目一个分组表头（错误/警告/未检/状态变化计数），
  组内保持自由能/NEB 组顺序；**已关闭项目排最后、默认折叠、灰显**，点击表头展开
- **排序规则**（v0.6.6）：按状态优先级排（错误 > 警告 > 未检 > 正常 > 关闭）；
  自由能 / NEB 同一组作为一个整体、用组内最高优先级状态参与排序（组员始终相邻）；
  归档任务沉到其他任务下面；同状态内仍是「类别 → 组名 → 组内结构顺序 → 任务名」
- **详情弹窗可直接关闭（归档）任务**（v0.6.3）：footer 提供「关闭（归档）」/「重新打开」，
  未正常结束时弹窗提醒当前状态；自由能主结构归档会**连带归档频率矫正**，频率矫正未完成时额外 ⚠️ 警告（v0.6.4）
- **自动巡检**（v0.6.2）：后端后台线程每 60 秒判定，距上次巡检超过间隔（默认 2 小时）自动执行全局巡检；
  顶部开关可随时启停（写 `settings.json`），旁边显示调度器实时状态（进行中 / 上次 / 下次 / 失败原因）
- **已关闭（归档）任务**（v0.6.5）：状态列显示「关闭」、信息列「任务已关闭（归档）」，
  不计入「未检」计数；「单独巡检」按钮置灰（归档任务需先在作业管理里重新打开才能巡检）
- **INCAR 精度检查**（v0.8.0）：巡检在已读的最新输出目录里顺手读 `INCAR`/`KPOINTS`/`POSCAR`
  （不增加额外 SSH 开销）——**结构优化的力收敛阈值改由 INCAR 的 `EDIFFG` 决定**；
  另按三项要求判精度：k 网格密度系数（k × 晶格常数）**> 20**、力收敛精度 `EDIFFG ≤ -0.02`、
  电子步收敛 `EDIFF ≤ 1E-5`（要求可在 `backend/check_registry.json` 的 `precision` 段调整）。
  任一项不满足 → 显示 **「低精度收敛」**（归档状态 `low_precision`，任务库状态仍记 completed，
  进度口径不变；报告「异常与关注项」会列为 medium 关注项）
- **巡检提速**（v0.8.0）：`bjobs` 从「每任务 2-3 次子进程」降到「每轮 2-3 次」（全量 cwd 表 +
  批量明细 + 缓存）；OUTCAR 不再整文件读入（尾部 8KB 判结束 + 分块计数带阈值提前退出，
  NEB 每映像合并成一次扫描）。实测 45 任务场景 24.8s → 1.3s，判定结果逐字段一致
- 结果表格 + **详情抽屉**：能量 / 最大力随离子步曲线（带收敛阈值基准线）、
  结构分析（**3Dmol 交互结构视图**（并排/叠加/球棍/空间填充/视角/选中联动）、
  力收敛历史表）、收敛判定徽标与分析范围标记；结构 CIF 由 `scripts/vasp2cif.py`
  在巡检触发时生成（每 25 离子步一桶 + 目录变化重置）；
  结构分析按 **ISIF** 智能切换：ISIF=2（默认，晶格固定）显示 POSCAR→CONTCAR
  **原子位移分析**（最大 / RMS / 平均位移），ISIF 为其他值时显示晶格参数与体积对比
- **NEB 能垒看板**（v0.6.8 重做）：顶部统计卡（映像数 / 能垒 Ea / 最大受力 / 末态相对能）+
  能垒曲线（相对能垒直线连接不插值、鞍点红色标注、渐变面积、悬停按映像出信息卡）+
  映像明细列表（初态/中间态/鞍点/末态徽标）；曲线从左绘制、数据点依次弹出、列表错峰入场
- **NEB 映像结构分析**（v0.6.9）：IS → 中间态 → FS **横向 3D 对比**（只展示优化后结构，
  优先 CONTCAR），拖动/滚轮联动所有面板视角，支持球棍/空间填充、自动旋转、缩放、重置与元素图例，
  鞍点映像高亮；结构由巡检按与结构优化相同的「25 离子步一桶」规则自动从远端抓取并转 CIF
- 结果持久化：每次巡检归档到 `data/checks/check_results_*.json`，**重新打开网站无需重新巡检即显示上次结果**
- **自由能路径看板**（v0.6.7 重做）：点巡检列表里自由能组的组名打开——顶部统计卡（中间体数 / 矫正完成度 /
  收敛情况 / 最高相对能）+ **相对能台阶图**（渐变台阶与面积、未收敛/未矫正琥珀色标记、缺数据灰色虚线、
  悬停浮起与信息卡、点击台阶或明细行直达该结构巡检详情）+ 中间体明细列表（DFT / 矫正项 / 自由能 / 相对 ΔE / 状态徽标）；
  入场有台阶依次滑入、连接线淡入、列表错峰上浮动画（`prefers-reduced-motion` 下自动关闭）

### 作业管理 Jobs
- 左侧项目列表（进度、子任务数、剩余时间），右侧子任务表格
- **关闭（归档）/ 重新打开**：任务快捷操作区可关闭任务（未正常结束时弹窗提醒；关闭只改状态、不动文件），
  已归档任务可「重新打开」恢复到归档前状态；**自由能结构优化主任务与频率矫正成对归档/恢复**（v0.6.4）
- **已关闭项目排到最后**（v0.6.2）：灰色显示且不提供新建入口；项目下可见任务全部归档后，
  可在总览「项目进度」里关闭项目
  已关闭项目**默认折叠**（子树不展开，可手动展开）
- 每项展示本地路径 / 远程路径 / 作业号 / 最近能量 / 状态
- 右侧标签页：概览 / POSCAR / INCAR / KPOINTS / 提交脚本（真实读写本地 `files/`；POTCAR 仍占位）
- **输入文件参数自动同步（v0.8.2）**：提交作业后后台自动从远端最新 conN 取回
  INCAR / KPOINTS / POSCAR / CONTCAR（1 次 exec + 4 次小文件下载），也可手动「同步最新参数」；
  页面顶部显示来源（conN · 作业号 · 同步时间）
- **改参数不碰远端（v0.8.2）**：编辑器默认只读，点「修改参数」解锁 → 「确认修改」才记为**待生效修改**
  （高亮 + 原值提示 + 可逐项撤销），**只在下次续算时写入新 conN**（不写注释）；POSCAR 永不覆盖（续算 POSCAR 来自 CONTCAR）。
  **只有真的改了参数才会写文件**：上传远端前先与本次计算的快照比对，一致就跳过
- **POSCAR 页（v0.8.2 重构 / v0.8.3 增强）**：460px 3Dmol 大窗口，可切换**输入结构（POSCAR）/
  最新结果（CONTCAR）**且**切换保持同一视角**；**单击选中原子**、**Ctrl/⌘ 多选**、**Shift 拖拽框选**
  （Ctrl/⌘+Shift 并入），选中标签按 POSCAR 序号自动合并区间（`Al1-3 Al6-7`，序号与 POSCAR 坐标行一致、从 1 开始）；
  另有结构数据（元素组成/原子数/晶格）+ 球棍/空间填充、原子缩放、自动旋转、a/b/c 视角、重置视角。
  POSCAR **不参与远端修改**（后续只有"固定原子"会写它，功能搁置）
- **KPOINTS 页（v0.8.2）**：直接改 k1/k2/k3（同样只读闸门 + 确认 + 待生效高亮），
  并显示网格密度系数 k×a（巡检精度检查要求 > 20）
- **概览的「文件结构」= 同步状态（v0.8.3）**：最新（绿，与本次计算的提交目录一致）/ 过时（黄，只在本地）/
  有修改待提交（高亮）；POTCAR 与 submit.sh 标注"不参与同步"，不再显示 WAVECAR
- **参数识别（v0.8.3）**：布尔支持 `.T./.F.` 等等价写法（`LWAVE = .T.` 会正确勾选、且不会误判为已修改）；
  含空格的参数值（`DIPOL = 0.5 0.5 0.18`、`MAGMOM = 5*2.0`）完整保留
- INCAR 编辑器：分类表单 + **其他参数**（不在预设表单里的参数，来自本次计算的 INCAR）+ 低/中/高精度 + 上传远端
- 「续算」确认操作（占位）
- 续算（opt/NEB，真实创建 conN）、create-frac、创建 NEB 文件、ele 输入构建

### 智能报告 Report（v0.8.0：排版重构 + 看板与巡检详情同版式）
- **以单个项目为报告单位**，后端生成三份产物：结构化数据 `report.json`（schema 1.1.0，可直接喂大模型）
  + Markdown `report.md` + SVG 图表 `charts/*.svg`，按项目分目录存 `data/reports/`，索引 `data/reports/index.json`；
  **同项目重新生成直接覆盖旧报告**（报告 ID 稳定为 `rpt_<project_id>`，索引里只保留一条）
- **正文章节 4 章**：基本信息（项目 / 时间 / 状态色标 / **分块项目进度条** + 一句话概览）/ 重点科学结果分析 /
  异常与关注项（模板生成，最多 6 条）/ 下一步建议（最多 5 条）；
  其余数据（tasks / resources / risks / llm_context / appendix）保留在结构化数据里供大模型消费
- **项目进度按任务类型分块**：块宽 = 该类型任务**当量占比**（结构优化/频率矫正 1、NEB 5、电子结构 0.4），
  块内显示该类型自身完成比例；上方另有一条**当量加权主进度**（大数字 + 进度条）
- **重点科学结果分析**（看板版式与巡检详情页一致）：
  结构优化只统计**独立** opt 任务，每个任务出**一张横向面板图**（左侧 a/b/c 三视图 + 右侧能量与最大力双纵轴曲线，同一基线对齐）；
  自由能按路径出**自由能路径看板**（统计卡 + 相对能台阶图 + 中间体表：DFT 能量 / 矫正项 / 自由能 / 相对 ΔE / 状态）；
  NEB 按组出**能垒看板**（统计卡 + 能垒曲线 + 映像明细表 + 映像结构对比矩阵）；电子结构为占位说明
- **风险规则外置**（`data/config/report_rules.json`，默认模板在 `backend/defaults/`）：声明式条件 + 严重程度 + 建议模板，
  当前 13 条规则（未收敛、异常中断、续算过多、输出缺失、频率矫正缺失、电子结构未分析、逾期、进度落后、存储不足、核数超限、队列拥堵、依赖未完成）
- 图表为纯 Python 生成的 SVG（零第三方依赖，本机无 matplotlib 且不引入），数据同时以数组提供
- **每天自动生成**：复用巡检调度线程（`auto_report_enabled` + `report_interval_hours`，默认 24h），
  可在巡检中心开关与调整间隔
- **工作量与工期按当量折算**：1 当量 = 600 核时，有效算力 = 200 核 × 24h × 70%
  （`settings.json` 的 `core_hours_per_weight` / `cluster_max_cores` / `cluster_utilization`），
  主进度 = 完成当量 / 总当量，**预计完成 = 今天 + 剩余核时 ÷ 有效算力**
- 前端：按项目生成 / 一键生成所有项目、项目报告列表（每项目一份）、章节导航、
  **正文只渲染图片（报告所见即所得，不再有交互式 3D 与结构化数据视图）**、
  **导出按钮在「报告内容」标题行**，点击后才展开章节勾选（如取消风险分析），
  可导出 HTML（自包含、图表内联）与 PDF（浏览器打印，按勾选章节）
- **已关闭项目的报告折叠**到列表底部（默认折叠、灰显、带「已关闭」标签），与总览 / 巡检中心 / 作业管理一致

### SSH 连接 SSH
- 服务器列表：连接状态指示、主机/端口/用户名、认证方式、延迟、测试/连接/编辑/删除
- 新建 / 编辑弹窗：主机、端口、用户名、认证方式（密钥文件 / 密码）、队列系统、
  **项目远程根目录**（后续新增项目都建在此根目录下）、高级设置（用户主目录）
- 「测试连接」：真实 SSH 握手（`POST /api/ssh/test`），返回实测延迟并写入最近测试时间
- 「连接 / 断开」：同一时间仅一个服务器处于连接状态，顶部状态栏实时联动
- 配置（含项目远程根目录）**实时同步到后端** `data/config/servers.json`；连接/延迟等 UI 状态保存在浏览器

## 后续如何接入真实后端

**已完成：新增项目**

- 后端：`backend/`（Python + FastAPI），`POST /api/projects` 复刻 `add_project.py` 全流程——
  输入校验 → 服务器/任务类型配置校验 → 工作量/紧急度/优先级象限计算 →
  本地目录创建（失败回滚）→ 可选远程同步目录 → 原子写库 + 自动备份
- 数据：`data/projects.json`（真实库已迁移自旧项目）+ `data/projects/` 目录结构 +
  `data/backups/`（保留 20 份），`data/config/` 存放服务器/设置/任务类型配置
- 前端：`src/api/projects.ts` 的 `createProject` / `fetchProjects` 已接真实接口；
  「新增项目」表单含服务器下拉与子任务动态列表（任务类型 + 模型名）
- **新建项目可直接建组**（v0.8.1）：结构优化 / 电子结构仍是单个任务；**自由能路径 = 组名 + 结构数**
  （每个结构自动登记「结构优化 + 频率矫正」两个任务，频率矫正作为子项），**NEB = 组名 + 映像数**
  （自动登记初态/末态优化 + NEB 计算任务）；提交顺序为"先建项目 → 再逐个建组"
- **INCAR 默认参数**：`IVDW = 11`（DFT-D3(BJ)）；**参数框留空即不写入 INCAR**（如 NCORE 清空后不会生成 `NCORE = `）

**其余模块接入方式**

1. 巡检 / 作业管理 / 智能报告均已接入真实接口（见上），前端无 Mock 数据。
2. **SSH 状态**：`src/context/SSHContext.tsx` 已把连接状态做成全局状态，顶部状态栏实时联动；
   接入后端时替换 `src/api/ssh.ts` 中的 `fetchServerConfigs` / `persistServerConfigs` / `testRemoteConnection`
   为 `GET/PUT /api/ssh/config`、`POST /api/ssh/test` 即可，页面与顶栏无需改动。
3. **自动巡检**：后端定时任务每 2 小时触发巡检脚本，前端巡检页改为从 `/api/inspections` 拉取。
4. **报告增强（后续）**：读取报告结构化数据与 `llm_context`，调用大模型 API 生成增强版风险分析与行动建议，
   并按既定输出结构校验后展示（当前报告的风险与建议由规则引擎 + 模板生成）。

## 新增项目 API 说明

### 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/projects` | 项目列表（含派生字段 progress / remainingHours / local_dir） |
| POST | `/api/projects` | 新增项目（`{action:"add_project", project:{name,deadline,server,tasks,...}}`） |
| GET | `/api/servers` | 服务器下拉选项 |
| GET | `/api/task-types` | 任务类型下拉选项（含 workload_weight） |
| GET | `/api/deps` | 运行时依赖检查（缺失项 + 安装提示） |
| GET/PUT | `/api/ssh/config` | SSH 服务器配置读写（含项目远程根目录） |
| GET | `/api/inspections` | 巡检结果列表（按任务合并最近一次结果） |
| POST | `/api/inspections/run` | 立即巡检（可选 project_name / task_id 限定范围） |
| GET | `/api/inspections/meta` | 自动巡检调度信息（间隔 / 上次 / 下次执行） |
| GET | `/api/inspections/{task_id}` | 单任务巡检详情（力历史 + 结构分析 + 3Dmol 结构视图） |
| GET | `/docs` | FastAPI 自动生成的 Swagger 接口文档 |

### 校验规则（Pydantic 模型，对齐参考实现 `schemas.py`）

- `name`：`^[A-Za-z0-9][A-Za-z0-9_]*$`；`deadline`：`^\d{4}-\d{2}-\d{2}$` 且必须是合法日期
- `server` 必须存在于 `data/config/servers.json`；`task_type` 必须注册于 `task_registry.json`
- `tasks` 至少 1 项，每项含 `task_type`、`model_name`（同 name 规则），状态可选（默认 `pending`）
- `frequency`（频率计算）与 `free_energy` 绑定：**不能在新项目中直接创建**，前端下拉已隐藏，后端也会拒绝
- Web 端扩展字段：`description`、`estimated_hours`（原 Schema `additionalProperties=false` 之外显式放行）

### 优先级计算（与参考实现 `priority.py` 一致）

- 工作量 = 任务权重之和，取自 `data/config/task_registry.json` 的 `workload_weight`：
  `opt=1` / `frac=1` / `neb=5` / `ele=0.4`（自由能由 opt + frac 组合而成，不再单独计权）
- 工作量 ≥ 20 为 `large`，否则 `small`；剩余天数 < 15 为 `urgent`，否则 `not_urgent`
- 优先级象限 = `<urgency>_<workload>`（如 `urgent_large`）

### 远程同步目录

`data/config/settings.json` 中 `sync_remote_dirs: true` 时，创建项目会用 Paramiko（密钥认证）
在服务器上 `mkdir -p` 每个任务目录，失败则回滚本地目录并报错。
**默认关闭**（避免未配置密钥时误连真实集群）；确认 SSH 可用后手动开启，或用环境变量
`VASP_SYNC_REMOTE_DIRS=1` 临时覆盖。

## 巡检系统（已实现，对齐参考实现 check_remote.py）

### 流程

1. 筛选待巡检任务（跳过 `pending` / `archived`），按服务器分组；
2. 自动上传 `backend/batch_check.py` 与 `check_registry.json` 到服务器 `batch_check_path`；
3. 服务器端运行 batch_check：`bjobs -l` 判定队列状态，解析 OUTCAR 能量 / 成功或错误标记 /
   结构优化 TOTAL-FORCE 力收敛历史（阈值 0.02 / 0.01 eV/A）；
4. 下载结果 → 按**状态机**回填数据库（非法流转保持原状态并记录警告）；
5. `structure_opt` 到达终态时同步 POSCAR/CONTCAR 到本地 `files/` 并校验非空；
6. 富化（prev_status / observed_changed / analysis_needed）归档到 `data/checks/check_results_*.json`，
   轮次摘要记录到 `runs.json`。

**结构分析范围（analysis_needed，v0.5.0 起）**：仅结构优化任务；按离子步每 25 步一桶
（0-24→桶 0、25-49→桶 1…），同一输出目录需桶号比上次更大才触发，输出目录变化则重置计数。
触发时下载 POSCAR/CONTCAR 并生成 CIF（`scripts/vasp2cif.py`）供前端 3Dmol 结构视图渲染，
避免对未变化的任务重复下载。

**结果保留策略**：同一子项只保留一条最新结果（按 task_id 合并，不删除历史行）；
新一次巡检更新状态 / 能量 / 检查时间，但若本次未下载检查（无新标记 / 力历史），
自动沿用上一次的检查标记、力历史与力统计，避免内容被覆盖丢失。

### 接口

- `POST /api/inspections/run`：立即巡检，请求体 `{"project_name": "Ag_20260830"}` 可限定范围
- `GET /api/inspections`：巡检结果列表（按任务合并最近一次结果）
- `GET /api/inspections/meta`：自动巡检间隔（默认 2 小时）、上次 / 下次执行时间

### 总览接口（v0.6.0）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/dashboard/overview` | 整页聚合：统计 / 运行作业 / 核数 / 集群 / 风险 / 项目进度 / 趋势 / 最近任务 |
| GET | `/api/dashboard/cores-usage` | 核数占用（blimits 配额 + 按项目分组） |
| GET | `/api/dashboard/cluster-health` | 节点状态 / 队列拥堵 / 存储容量 |
| GET | `/api/dashboard/risk-alerts` | 需干预任务（未收敛 / Zombie / 巡检异常）+ 上次巡检时间 |
| GET | `/api/dashboard/trend` | 近 N 天核数占用 / 运行任务 / 提交作业数 |

### 巡检与项目接口（v0.6.2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| PUT | `/api/inspections/auto` | 开启/关闭自动巡检、调整间隔（写入 `settings.json`） |
| GET | `/api/inspections/meta` | 调度状态：开关、间隔、上次/下次执行、是否正在跑、上次错误 |
| POST | `/api/jobs/tasks/{id}/archive` | 关闭（归档）任务，只改状态 |
| POST | `/api/jobs/tasks/{id}/unarchive` | 重新打开，恢复归档前状态 |
| POST | `/api/projects/{id}/close` | 关闭项目（要求可见任务全部归档） |
| POST | `/api/projects/{id}/reopen` | 重新打开项目 |

以上接口都支持 `?refresh=1` 强制重新执行集群查询（默认命中服务端 5 分钟缓存）。
`data/dashboard/core_history.json` 记录每次查询的核数/任务快照，趋势图的核数曲线自 v0.6.0 起累积。

### 本地模拟模式（离线测试）

```powershell
$env:VASP_SSH_MOCK = '1'            # 启用模拟 SSH
$env:VASP_MOCK_REMOTE_ROOT = 'D:\Skill\vasp-project-manager-web\data\mock_remote'
$env:VASP_BATCH_NO_BJOBS = '1'      # 跳过 bjobs
$env:VASP_BATCH_LOCAL_ROOT = $env:VASP_MOCK_REMOTE_ROOT
python scripts/make_mock_fixtures.py   # 生成模拟远程目录夹具
python backend/run.py
```

模拟模式下远程路径原样映射到 `VASP_MOCK_REMOTE_ROOT`，`python3 batch_check ...` 改为本地 Python 执行，
可在不连接真实集群的情况下完整验证巡检流程。

### 真实运行

确认 SSH 密钥可用后（SSH 连接页已能连接），直接在前端巡检中心点「立即巡检」，
或 `POST /api/inspections/run`。测试目录示例：`/data/gpfs03/mdye/projects/test/Ag_20260830`
（对应数据库中 Ag_20260830 项目的 remote_dir）。

## 后续迭代计划（本次未实现）

- ~~后端骨架 + 新增项目~~（已完成）
- ~~项目查询 / 状态更新 / 巡检集成~~（已完成：项目 CRUD、状态机、巡检编排）
- 自动巡检调度（APScheduler 每 2 小时触发，前端展示调度状态）
- 目录同步 / 文件操作 API（作业管理模块）
- 大模型 API 集成与报告生成
- SSH 配置页与后端 `data/config/servers.json` 打通（真实握手测试）
- 用户认证与权限管理（如需要）
