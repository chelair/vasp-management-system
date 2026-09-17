# 跨机器迁移交接文档（Windows → Linux）

> 适用版本：**v0.8.3**（2026-09-17）· 维护：开发助手（Codex）
> 用途：把 VASP 项目管理系统**连代码、项目信息、巡检/报告/辅助分子等运行时数据**整体搬到一台 Linux 服务器，按本文档做完即可正常跑起来。
> 相关文档：`process.md`（架构与改动史）、`README.md`（模块说明）、`DEPENDENCIES.md`（依赖）、`TODO.md`

---

## 0. 先理解：这套系统由三块组成

| 块 | 在哪 | 说明 | 迁移时 |
| --- | --- | --- | --- |
| **代码** | 仓库（git 跟踪 154 个文件） | React 前端源码 + FastAPI 后端 + `scripts/` 工具 + `public/3dmol` 本地库 | 重新 clone / 解压，然后在目标机 build |
| **运行时数据 `data/`** | 仓库下 `data/`（**被 .gitignore 忽略**，不能靠 git 带走） | 项目/任务主库、巡检归档、报告、辅助分子、配置、备份、审计日志 | **必须单独打包**（当前 54.6 MB） |
| **远端 HPC** | `hpc.xmu.edu.cn`（LSF） | 真正的计算目录/作业；系统只通过 SSH 访问 | 不用搬，但要保证**新机器的 SSH 私钥能登录** |

一句话：**代码靠 git，数据靠拷 `data/`，HPC 靠 SSH 私钥。** 三者到位就能跑。

---

## 1. 需要打包（带走）的东西

| 路径 | 必需 | 说明 |
| --- | :---: | --- |
| 仓库跟踪文件（`git archive` 或 `git clone`） | ✅ | `backend/` `src/` `scripts/` `public/3dmol` `*.md` `package.json` / `package-lock.json` / `requirements.txt` / `vite.config.ts` / `tsconfig*.json` / `index.html` |
| **`data/`** 整个目录 | ✅ | 见下方明细；这是唯一真相，丢了要重来 |
| SSH 私钥（如 `C:\Users\<你>\.ssh\id_rsa`） | ✅ | 系统用 `servers.json.key_path`（当前 `~/.ssh/id_rsa`）登录 HPC；也可在 Linux 上新生成并把公钥加到 HPC |
| `data/config/servers.json` | ✅ | 已含在 `data/` 里（HPC host/user/remote_base/查询命令），**全部是远端路径，不用改** |
| `data/config/settings.json` | ✅ | 巡检/报告开关、阈值等（里面 `vesta_path` 是 Windows 路径，已停用，可留空） |
| `data/config/path_mapping.json` | ✅ | 本地/远端根映射（注意下面的坑） |
| `backend/defaults/*.json` | ✅ | 已随 git；仅在新机器缺 `data/config/*` 时作为模板 |

`data/` 明细（都建议带，`trash/` 可选）：

| 子目录/文件 | 大小 | 作用 |
| --- | --- | --- |
| `projects.json` | 0.4 MB | **项目/任务主库**（4 个项目、120 个可见任务、含续算目录共 240 条任务记录） |
| `projects/` | 22.3 MB | 本地项目镜像（`files/` 输入文件、`inputs/` 参数快照、`reports/` 结构 CIF） |
| `checks/` | 21.5 MB | 巡检归档（`check_results_*.json`、`runs.json`；报告/总览/巡检页都读它） |
| `backups/` | 6.4 MB | `projects.json` 自动备份（20 份）+ 迁移前备份 |
| `reports/` | 2.6 MB | 分项目报告（`report.json` / `report.md` / `charts/*.svg` + `index.json`） |
| `config/` | <1 MB | `servers.json` / `settings.json` / `task_registry.json` / `path_mapping.json` / `check_registry.json` / `report_rules.json` |
| `aux_molecules/` + `aux_molecules.json` | <1 MB | 自由能路径用的全局辅助分子（H2/N2/O2/CO2） |
| `dashboard/core_history.json` | <1 MB | 总览「近 7 天核数趋势」采样历史 |
| `audit_submit.log` | 0.1 MB | 提交/上传/续算操作审计 |
| `trash/` | 1.4 MB | 删除任务的本地回收站（可选，不带走也行） |

**不要打包**（在目标机重建，或本来就没用）：

| 路径 | 原因 |
| --- | --- |
| `node_modules/` | 平台相关（Windows 原生模块），目标机用 `npm ci` 重装 |
| `dist/` | 前端构建产物，目标机 `npm run build` 重新生成（后端只在 `dist/index.html` 存在时托管页面） |
| `__pycache__/`、`*.pyc` | Python 缓存 |
| `*.log`（`backend_server.log` / `vite*.log`） | 运行日志 |
| `start.bat` / `start-backend.bat` / `start-frontend.bat` | Windows 专用启动脚本，Linux 用 systemd（见 §5） |

---

## 2. 旧机（Windows）这边要做的

1. **停掉后端进程**（关键）：`data/` 同一时刻只能被一个后端写。任务管理器结束 `python backend/run.py`，或直接跑一次 `start-backend.bat` 的窗口关掉。
   - 停之前记下当前状态：（可选）页面顶部「上次巡检时间 / 下次巡检时间」，迁移后对照。
2. **确认没有正在写的操作**：不要有正在跑的手动巡检 / 续算 / 生成报告。
3. （可选，推荐）**归一化遗留绝对路径**：`python scripts/migrate_paths.py --apply`
   - 会把 `data/aux_molecules.json`（4 个分子的 dir/opt_dir/frac_dir）与 `data/reports/index.json`（4 份报告的 directory）里的 `D:\...` 改写成相对路径，原文件备份到 `data/backups/migration_<时间>/`。
   - 这步在本次交接前**已经跑过一次**（16 处已归一化）。
4. **打包**（任选一种）：
   ```powershell
   # A. 代码：远端仓库就是权威，Linux 上直接 clone（推荐）
   git -C D:\Skill\vasp-project-manager-web log --oneline -1     # 记下提交号，应为 v0.8.3

   # B. 数据：单独压缩（不要在代码包里夹 node_modules/dist）
   Compress-Archive -Path D:\Skill\vasp-project-manager-web\data -DestinationPath D:\vasp-data-20260917.zip -Force
   ```
5. **单独安全传输 SSH 私钥**（U 盘 / scp），不要放进 git 仓库。

---

## 3. 目标机（Linux）准备

```bash
# 系统依赖（Debian/Ubuntu 系；CentOS 用 dnf 对应包名）
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm rsync unzip
sudo timedatectl set-timezone Asia/Shanghai          # 重要：巡检/报告按本地时间
python3 --version   # 需 ≥ 3.11（推荐 3.12）
node -v && npm -v   # 需 Node ≥ 20.19（Vite 7 要求），推荐 22/24
```

代码与依赖：

```bash
sudo mkdir -p /opt && cd /opt
git clone git@github.com:chelair/vasp-management-system.git vasp-manager   # 或解压代码包
cd vasp-manager
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip

# 最小依赖（够跑全部核心功能）
pip install fastapi "uvicorn[standard]" paramiko
# 需要「后续功能」（POTCAR 拼接 pymatgen / ASE / APScheduler / openai）才装全部：
#   pip install -r requirements.txt     # 会装 numpy/scipy/matplotlib/pandas 等，100+ MB

npm ci          # 按 package-lock.json 安装
npm run build   # 生成 dist/（后端 3001 会托管它；不 build 就只能用 dev 模式）
```

放数据：

```bash
rsync -av /path/to/vasp-data/ /opt/vasp-manager/data/      # 保留目录结构，末尾斜杠别丢
# 或：unzip /media/usb/vasp-data-20260917.zip -d /opt/vasp-manager
```

SSH 私钥：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
scp 旧机:/c/Users/你/.ssh/id_rsa ~/.ssh/id_rsa   # 或用新生成的密钥
chmod 600 ~/.ssh/id_rsa
ssh -p 22 mdye@hpc.xmu.edu.cn "hostname"          # 先手工验证能登录（接受 host key）
```

---

## 4. 迁移后**必须做**的改动（逐条核对）

| # | 位置 | 要做什么 | 不改的后果 |
| --- | --- | --- | --- |
| 1 | `~/.ssh/id_rsa` + `data/config/servers.json:key_path` | 私钥放到 `key_path` 指定的位置（默认 `~/.ssh/id_rsa`，注意 systemd 以哪个用户跑），`chmod 600` | 巡检/提交/同步全部失败（连接被拒或权限错误） |
| 2 | `data/config/path_mapping.json` | `local_root` 保持相对 `data/projects`（**数据在仓库内**时正确）；若用 `--data-dir` 把数据放到仓库外，必须改成**绝对路径** `/srv/vasp-data/projects` | 任务本地目录解析错位（页面看不到文件、续算找不到目录） |
| 3 | `data/config/settings.json` | `vesta_path` 可留空（VESTA 渲染已停用）；按新机实际调整 `dashboard_total_cores`（核数上限）、`dashboard_cache_seconds`、`auto_inspection_enabled` / `inspection_interval_hours`、`auto_report_enabled` / `report_interval_hours`、`sync_remote_dirs` | 核数看板口径不准；自动巡检/报告的时间策略不合预期 |
| 4 | 时区 | `timedatectl set-timezone Asia/Shanghai`（或 `TZ=Asia/Shanghai`） | 「今日完成」「近 7 天」、巡检时间戳整体偏移 |
| 5 | 编码 | 服务里设 `PYTHONIOENCODING=utf-8` | 日志里 emoji/中文可能抛 `UnicodeEncodeError`（Linux UTF-8 一般没问题，显式设置更稳） |
| 6 | 启动方式 | 用 `python backend/run.py`（可用 `--data-dir`）；`npm run server` 里的 `python` 在 Linux 上可能是 `python3` —— 建议**激活 venv 后**用 `.venv/bin/python backend/run.py`，或把 `npm` 脚本改成 `python3` | 直接跑 `npm run server` 可能报 `python: command not found` |
| 7 | 前端 | `npm run build`（必须） | 3001 上打开是空白页/404（后端只在 `dist/index.html` 存在时托管） |
| 8 | 遗留绝对路径 | `python scripts/migrate_paths.py --apply` | `aux_molecules.json` / `reports/index.json` 里残留旧机绝对路径（运行时有兜底，但文件本身不可移植） |
| 9 | 端口/防火墙 | 后端监听 `0.0.0.0:3001`（前后端同端口）；按需放行 3001，或加 nginx 反代到 80/443 | 其他电脑打不开 |
| 10 | 「打开文件夹」按钮 | Linux 无桌面时 `xdg-open` 无效（按钮无反应，不影响功能） | 只是这个小按钮没用，可忽略 |
| 11 | 自动巡检/报告 | 后端进程必须**常驻**（systemd），否则定时任务不跑 | 巡检/报告只在手动点的时候发生 |

---

## 5. 启动与常驻

先前台试跑，确认没问题再上 systemd：

```bash
cd /opt/vasp-manager
source .venv/bin/activate
python backend/run.py            # 监听 0.0.0.0:3001
# 浏览器打开 http://<服务器IP>:3001   （前端 + /api + /docs 都在这个端口）
```

systemd 常驻（推荐，开机自启）：

```ini
# /etc/systemd/system/vasp-manager.service
[Unit]
Description=VASP Project Manager (FastAPI + 前端静态托管)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vasp
WorkingDirectory=/opt/vasp-manager
Environment=PYTHONIOENCODING=utf-8
Environment=TZ=Asia/Shanghai
ExecStart=/opt/vasp-manager/.venv/bin/python backend/run.py
# 数据放在仓库外时用：ExecStart=/opt/vasp-manager/.venv/bin/python backend/run.py --data-dir /srv/vasp-data
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vasp-manager
systemctl status vasp-manager --no-pager
journalctl -u vasp-manager -n 50 --no-pager     # 看日志（原来放在 *_log.txt，现在进 journal）
```

可选 nginx 反代（80/443 → 3001）：

```nginx
server {
  listen 80;
  server_name _;
  client_max_body_size 200m;         # 上传 POSCAR/INCAR/KPOINTS 用
  location / {
    proxy_pass http://127.0.0.1:3001;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;         # 巡检/续算接口耗时长
  }
}
```

---

## 6. 首次自检（验收清单）

按顺序做一遍，全绿才算迁移成功：

| 检查 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 后端活着 | `curl -s localhost:3001/api/health` | `{"success":true,...,"startedAt":"<本次启动时间>"}` |
| 项目数据 | `curl -s localhost:3001/api/projects \| head -c 300` | 4 个项目：`Ag_20260830`(63) / `Co_260902`(34) / `TMDZYX`(7) / `FS_Kaolin`(16)（数字为可见任务数） |
| 巡检归档 | 页面「巡检中心」 | 列表有数据、状态/详情可打开（读 `data/checks`） |
| 报告 | 页面「智能报告」 | 列表 4 份报告（每项目一份），正文与图表能显示 |
| SSH/集群 | 顶部「SSH 已连接」+ 总览 | 显示实测延迟；核数圆环、运行作业、节点/队列、存储都有数据 |
| 单任务巡检 | 巡检中心 → 取一个任务点「单独巡检」 | 12–15 秒内返回结果（脚本上传+执行+回填） |
| 生成报告 | 报告页 → 选一个项目 → 「生成报告」 | 4–8 秒生成，图表齐全 |
| 输入文件同步 | 作业管理 → 某任务 → INCAR 页 → 「同步最新参数」 | 显示来源 conN/作业号/时间，参数与远端一致 |
| 前端页面 | 浏览器打开 `http://<IP>:3001` | 侧边栏/总览/3D 结构（3Dmol）正常，无控制台报错 |
| 定时任务 | 巡检中心顶部调度器状态 | 显示"上次/下次"时间，开关可用 |

---

## 7. 迁移期间 / 之后的注意事项

- **绝对不要两台机器同时跑同一个 `data/`**：定时巡检、自动报告、`projects.json` 原子写会互相覆盖。切机器时先在旧机停掉后端（或彻底停用服务）。
- **`data/` 是唯一真相**：代码可以随便 clone/重建，数据丢了就得重新巡检/重新生成报告。
- 迁移建议"**先复制、再切换**"：旧机数据拷到新机跑通验收清单 → 再停旧机。旧机保留一份完整副本用于回滚。
- `data/backups/` 会自动轮转（20 份）；大版本切换前手动整目录备份一次最稳。
- 磁盘增长点：`data/checks/`（每次巡检追加归档）、`data/reports/`（每个项目一份，覆盖式）、`data/projects/`（本地镜像）。当前合计 55 MB，长期跑建议留意配额。
- 从 HPC 侧看，系统只是"另一个客户端"：`servers.json` 里的 `remote_base` / `batch_check_path` 等**远端路径保持原样**，不要因为换本地机器而改。

---

## 8. 回滚方案

1. 新机验收没过：直接在旧机重新 `python backend/run.py` 即可（数据没动过就行）。
2. 新机已经产生新数据（跑了巡检/报告/续算）而想退回旧机：把新机 `data/` 整个拷回旧机（或反过来继续在新机上修），**不要只拷 `projects.json`**（`checks/`、`reports/`、`projects/` 是配套的）。
3. 迁移前的自动备份：`data/backups/project_db_*.json`（最近 20 份）+ `data/backups/migration_*/`（`migrate_paths.py --apply` 前的原文件）。

---

## 9. 已知的 Windows 痕迹（无害，可忽略）

| 位置 | 说明 |
| --- | --- |
| `backend/defaults/settings.json: vesta_path = D:\DFT\...` | VESTA 渲染路线已停用（结构图改由 3Dmol / 纯 Python 生成），该字段不再被使用；新机器保持原样或清空都行 |
| `start.bat` / `start-backend.bat` / `start-frontend.bat` | Windows 专用双击启动脚本；Linux 用 §5 的 systemd |
| `data/checks/runs.json → archived_files` | 历史巡检归档的绝对路径（仅展示用），如需干净可删该字段或整份 `runs.json`（会丢失"上次巡检时间"记录） |
| 运行日志 `*.log` | 已 gitignore，不用带 |

代码本身已经过核对：**没有平台专有依赖**（无 pywin32/winreg/ctypes/signal 专用逻辑）、**本地模块导入无大小写不一致**（Linux 大小写敏感，已全量扫描通过）、**仓库与数据里没有非 ASCII 文件名**（全是 ASCII 目录/文件名，避免编码坑）。

---

## 10. 常见故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `python: command not found` | 系统只有 `python3` | 激活 venv 或改用 `python3 backend/run.py` |
| 页面 404 / 空白 | 没 `npm run build`，或 `dist/` 没带过来 | `npm ci && npm run build` 后重启后端 |
| 顶部显示 SSH 未连接 / 巡检全失败 | 私钥缺失、权限不对（>600）、`key_path` 指错、HPC 换了 host key | `ssh mdye@hpc.xmu.edu.cn` 手工验证；`chmod 600`；必要时 `ssh-keygen -R hpc.xmu.edu.cn` |
| 启动报 `ModuleNotFoundError: fastapi` | venv 没激活 / 装到系统 python | `source .venv/bin/activate && pip install fastapi "uvicorn[standard]" paramiko` |
| 任务文件页显示"没有文件" | `path_mapping.json.local_root` 与数据实际位置不一致（尤其用了 `--data-dir`） | 把它改成 `<数据根>/projects` 的绝对路径 |
| 「打开文件夹」没反应 | 无桌面环境，`xdg-open` 无效 | 忽略，或改用 SFTP/终端查看 |
| 巡检/报告时间戳差 8 小时 | 服务器时区不是 Asia/Shanghai | `sudo timedatectl set-timezone Asia/Shanghai` 后重启后端 |
| `projects.json` 被写坏 | 两个后端同时跑同一 `data/` | 只保留一个进程；用 `data/backups/` 最新备份恢复（`storage.save_db` 覆盖前自动备份） |

---

## 附录 A：`data/` 目录速查

```
data/
├── projects.json              # 项目/任务主库（含 input_state 参数快照与变更台账）
├── projects/<项目>/...        # 本地镜像：files/ 输入文件、inputs/ 参数快照+CIF、reports/ 结构分析
├── checks/                    # 巡检归档（列表/详情/报告/总览都依赖）
├── reports/<项目>/<报告ID>/    # report.json + report.md + charts/*.svg
├── config/                    # servers / settings / task_registry / path_mapping / check_registry / report_rules
├── aux_molecules/<标签>/       # 自由能用的辅助分子（opt|frac）
├── backups/                   # projects.json 自动备份 + 迁移前备份
├── dashboard/core_history.json# 总览趋势采样
├── audit_submit.log           # 提交/上传/续算审计
└── trash/                     # 删除任务回收站（可选）
```

## 附录 B：本次交接前的实测快照（用于迁移后对照）

| 项 | 值 |
| --- | --- |
| 版本 | v0.8.3（提交 `76ef158` + 文档 `190fe23`） |
| 项目 | `Ag_20260830`(63 可见任务) / `Co_260902`(34，已关闭) / `TMDZYX`(7，已关闭) / `FS_Kaolin`(16) |
| 任务记录总数 | 240（含隐藏的续算 `conN` 子任务） |
| 报告 | 4 份（每项目一份，覆盖式） |
| 巡检归档 | `data/checks/` 21.5 MB |
| 辅助分子 | H2 / N2 / O2 / CO2（相对路径，已归一化） |
| `data/` 总大小 | 54.6 MB |
| git 跟踪文件 | 154 个（`public/3dmol/3Dmol-min.js` 已入库，随 clone 带走） |
| 前端构建 | 目标机执行 `npm ci && npm run build`（`dist/` 不随包） |
