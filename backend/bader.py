"""Bader 电荷分析链路（2026-10-14 新建）：远端算 → 回传 `ACF.dat` → 本地解析。

用户口径（2026-10-14）：

- **同差分电荷，Bader 也在远端算**，入口同样在巡检详情的「电子结构分析 → Bader」标签；
- 链路：① 检查 `AECCAR0/1/2` 是否存在、**大小是否相差 < 1%** →
  ② 远端 `chgsum.pl AECCAR0 AECCAR2` 生成 `CHGCAR_sum`（已有就跳过）→
  ③ 远端 `bader CHGCAR -ref CHGCAR_sum`（**耗时可能较长**）生成关键文件 `ACF.dat` →
  ④ 回传 `ACF.dat` 并解析；
- 本轮只做**处理链路**（算 + 回传 + 解析）；净电荷（要 POTCAR 的 ZVAL）、按元素/原子分组、
  图表与报告属于**分析链路**，下一轮再做。

远端前提（2026-10-14 只读侦察确认）：

- `bader` 可执行文件在 `/data/gpfs03/mdye/projects/potcar/bader`（**不在 PATH 里**），
  版本是 Fortran 版（`-h` 报 1.05 08/19/23）；可用 `data/servers.json: bader_exe` 覆盖。
  默认**不写体积文件**（`AVF.dat` 要显式 `-p` 才写），只出 `ACF.dat` + `BCF.dat`。
- `chgsum.pl` 在 VTST 目录（`ele_diff.vtst_dir`，差分电荷那条链路已经在用）。
- `AECCAR0/1/2` 由 INCAR 的 `LAECHG=.TRUE.` 产生（写在同一 FFT 网格上，所以三者大小应当一致）。

本地产物（`<ele 任务目录>/bader/`）：

    ACF.dat     远端回传的 Bader 原子电荷表
    meta.json   最近一次链路运行的状态（跨重启保留失败原因）

异步模型与 `charge_diff.py` / `pdos.py` 一致：`start()` 起后台线程返回 `run_id`，
`status()` 轮询，同一任务已有 run 在跑时复用。
"""

from __future__ import annotations

import base64
from collections import Counter
import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ssh
from dates import now_iso
from ele_diff import vtst_dir
from paths import to_local_rel
from storage import db_transaction
from task_paths import local_files_dir, task_dir, task_remote_dir

#: AECCAR 三个文件（完整结构 + 芯 + 价；Bader 用 AECCAR0 + AECCAR2 的和做参考电荷）
AECCAR_FILES: Tuple[str, ...] = ("AECCAR0", "AECCAR1", "AECCAR2")
#: 三个 AECCAR 的大小差别阈值（同差分电荷口径：**< 1%**）
SIZE_TOLERANCE = 0.01
#: 远端 bader 可执行文件（不在 PATH 里；`servers.json: bader_exe` 可覆盖）
BADER_DEFAULT_EXE = "/data/gpfs03/mdye/projects/potcar/bader"
#: 本地目录 / 文件名
DIR_NAME = "bader"
ACF_NAME = "ACF.dat"
META_JSON = "meta.json"
#: 远端中间产物名（VTST chgsum.pl 约定）
CHG_SUM_NAME = "CHGCAR_sum"
#: Bader **自己的**参考电荷文件名（2026-10-15 修）。
#: 为什么不能直接用 `CHGCAR_sum`：`chgsum.pl` 把输出名写死成 `CHGCAR_sum`，
#: 差分电荷链路跑的是 `chgsum.pl 1/CHGCAR 2/CHGCAR …`（分块和），Bader 要的是
#: `chgsum.pl AECCAR0 AECCAR2`（芯+价的和）—— 两者撞名。现场就踩到了：
#: FS_Kaolin/model2 等目录里那份 `CHGCAR_sum` 的头是 `Fe S / 24 32`（分块），
#: 而 AECCAR/CHGCAR 是 `Fe S O H / 24 33 5 1`，拿它当 `-ref` 会算出错的 Bader 电荷。
#: 现在 Bader 在专用子目录 `.bader_sum/` 里跑 chgsum（不碰那份遗留文件），再 mv 成
#: `CHGCAR_sum_aec`；复用它之前会**校验头部+行数与 AECCAR0 一致**。
CHG_SUM_AEC_NAME = "CHGCAR_sum_aec"
#: chgsum 的临时工作目录（放 AECCAR 的软链，输出落在里面，避免覆盖遗留的 CHGCAR_sum）
SUM_WORK_DIR = ".bader_sum"
#: 远端伪势文件（只 grep TITEL/ZVAL 两行拿每种元素的 ZVAL；**不下载、不用 pymatgen**）
POTCAR_NAME = "POTCAR"
#: 电荷密度文件（bader 的输入；**它的头部元素顺序 = ACF.dat 的原子行序**，v0.9.75 起在探测时记下来）
CHGCAR_NAME = "CHGCAR"
#: 分析时冻结的结构文件（v0.9.75）：远端 CONTCAR（缺则 POSCAR）拷进 `<任务>/bader/`，
#: 之后本地镜像被后续运行覆盖，Bader 的表/3D 仍与这次分析的电荷一致
FROZEN_STRUCTURE = "CONTCAR"
FROZEN_CIF = "structure.cif"

#: 阶段名 → 前端展示文案
STAGE_LABELS = {
    "checking": "远端校验 AECCAR 文件（大小差别应 < 1%）",
    "summing": "远端 chgsum.pl AECCAR0 + AECCAR2 生成 CHGCAR_sum",
    "bader": "远端 bader 分析（耗时较长）",
    "downloading": "回传 ACF.dat",
    "parsing": "解析 ACF.dat",
    "done": "已完成",
}

#: 远端探测缓存：task_id → (时间戳, 结果)
_PROBE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PROBE_TTL_SECONDS = 120.0
#: run 状态（进程内）
_RUNS: Dict[str, Dict[str, Any]] = {}
_TASK_RUN: Dict[str, str] = {}
#: 全局串行：bader 很吃 CPU/IO，一次只跑一条（同差分电荷的取舍）
_JOB_LOCK = threading.Lock()
_LOCK = threading.Lock()

_LOG = Path(__file__).resolve().parent.parent / "data" / "bader.log"


class BaderError(RuntimeError):
    """链路错误：`status` = 建议的 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _log_line(message: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


# ------------------------------------------------------------------ 路径/配置


def local_dir(project_name: str, task: Dict[str, Any]) -> Path:
    return task_dir(project_name, task) / DIR_NAME


def acf_path(project_name: str, task: Dict[str, Any]) -> Path:
    return local_dir(project_name, task) / ACF_NAME


def meta_path(project_name: str, task: Dict[str, Any]) -> Path:
    return local_dir(project_name, task) / META_JSON


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_meta(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(meta_path(project_name, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember_zval(
    project_name: str,
    task: Dict[str, Any],
    zval: Dict[str, float],
    charge_header: Optional[Dict[str, Any]] = None,
) -> None:
    """把探测到的 ZVAL 合并进本地 `meta.json`（不动其它字段）。

    为什么要缓存：`load_data()` 是**纯本地**接口（不连远端），净电荷要用 ZVAL；
    对"ACF.dat 早就下载好、但 meta 里还没有 ZVAL"的任务（升级前算的），
    前端探一次远端状态就能把 ZVAL 补进 meta，之后一直可用。

    `charge_header`（v0.9.75）：远端 `CHGCAR` 头部记下的元素/计数顺序 —— 同样合并进 meta，
    以后标注 `ACF.dat` 原子元素就以它为准（**但只在"本地还没有该次分析记录"时写**，
    避免后续运行的头部覆盖掉分析时的顺序：meta 里已有 charge_header 就不动）。
    """
    meta = read_meta(project_name, task)
    changed = False
    if zval and meta.get("zval") != zval:
        meta["zval"] = zval
        meta["zval_at"] = now_iso()
        changed = True
    if charge_header and not meta.get("charge_header"):
        meta["charge_header"] = charge_header
        meta["charge_header_at"] = now_iso()
        changed = True
    if not changed:
        return
    try:
        _write_json(meta_path(project_name, task), meta)
    except Exception as e:  # noqa: BLE001 - 缓存失败不影响链路
        _log_line(f"[warn] 缓存 ZVAL / 电荷密度头部失败：{e}")


def bader_exe(server: str) -> str:
    """远端 bader 可执行文件：`servers.json: bader_exe` → 默认路径。"""
    from config import load_servers

    configured = str(load_servers().get(server, {}).get("bader_exe") or "").strip()
    return configured or BADER_DEFAULT_EXE


def has_local(project_name: str, task: Dict[str, Any]) -> bool:
    path = acf_path(project_name, task)
    return path.is_file() and path.stat().st_size > 0


def frozen_cif_path(project_name: str, task: Dict[str, Any]) -> Path:
    """分析时冻结的结构 CIF（`<任务>/bader/structure.cif`）：Bader 的表/3D 用它，避免错配。"""
    return local_dir(project_name, task) / FROZEN_CIF


def report_cif(project_name: str, task: Dict[str, Any]) -> Optional[str]:
    """报告用 CIF：**优先分析时冻结的那份**（与 ACF.dat 同一次分析）。

    老数据（v0.9.75 之前分析的）没有冻结文件 → 若本地 `CONTCAR`/`POSCAR` 的**元素顺序与
    分析时记录的一致**，就地补一份冻结（转 CIF 缓存）；顺序不一致（镜像已被新运行覆盖）
    则返回 None，让调用方退回本地镜像（并在数据里留 `cif_source`）。
    """
    path = frozen_cif_path(project_name, task)
    if path.is_file() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8", errors="replace")
    if _backfill_frozen(project_name, task):
        if path.is_file() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8", errors="replace")
    return None


def _analysis_element_order(meta: Dict[str, Any]) -> List[str]:
    """分析时的元素顺序：优先 CHGCAR 头部，其次 POTCAR（zval 键顺序）。"""
    header = meta.get("charge_header") or {}
    elements = [str(el) for el in (header.get("elements") or [])]
    if elements:
        return elements
    return [str(el) for el in (meta.get("zval") or {})]


def _backfill_frozen(project_name: str, task: Dict[str, Any]) -> bool:
    """老数据补冻结结构：本地 CONTCAR/POSCAR 与分析时元素顺序一致时才认。"""
    meta = read_meta(project_name, task)
    order = _analysis_element_order(meta)
    if not order:
        return False
    from task_paths import task_files_dir

    files_dir = task_files_dir(project_name, task)
    for name in ("CONTCAR", "POSCAR"):
        src = files_dir / name
        if not (src.is_file() and src.stat().st_size > 0):
            continue
        local_order: List[str] = []
        for element in poscar_atom_elements(src):
            if not local_order or local_order[-1] != element:
                local_order.append(element)
        if local_order != order:
            continue
        target = local_dir(project_name, task) / FROZEN_STRUCTURE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(src, target)
            import cif_convert

            return bool(
                cif_convert.convert_structure_to_cif(
                    target, frozen_cif_path(project_name, task), overwrite=True
                )
            )
        except Exception as e:  # noqa: BLE001 - 补冻结失败就退回本地镜像
            _log_line(f"[warn] 补冻结结构失败：{e}")
            return False
    return False


def _freeze_structure(
    server: str, ele_remote: str, project_name: str, task: Dict[str, Any]
) -> Optional[str]:
    """把**这次分析用的结构**（远端 CONTCAR，缺则 POSCAR）拷进 `<任务>/bader/` 并转 CIF。

    为什么：`ACF.dat` 属于"那一次"电荷密度/结构；本地 `files/CONTCAR` 之后可能被新运行覆盖，
    那样表格里的元素顺序、3D 结构都会对不上（2026-10-16 PMS@model1 就是这个坑）。
    失败不影响分析结果，只返回 None（报告那边退回本地镜像的 CIF）。
    """
    target_dir = local_dir(project_name, task)
    target_dir.mkdir(parents=True, exist_ok=True)
    src = target_dir / FROZEN_STRUCTURE
    for name in ("CONTCAR", "POSCAR"):
        tmp = src.with_name(src.name + ".tmp")
        try:
            ok = ssh.download_file(server, f"{ele_remote}/{name}", str(tmp))
            if ok and tmp.is_file() and tmp.stat().st_size > 0:
                tmp.replace(src)
                break
        except Exception as e:  # noqa: BLE001 - 冻结失败不影响分析
            _log_line(f"[warn] 冻结结构失败（{name}）：{e}")
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        src = src  # 继续试下一个来源
    if not (src.is_file() and src.stat().st_size > 0):
        return None
    out = frozen_cif_path(project_name, task)
    try:
        import cif_convert

        if not cif_convert.convert_structure_to_cif(src, out, overwrite=True):
            return None
    except Exception as e:  # noqa: BLE001 - 转换失败不影响分析
        _log_line(f"[warn] 冻结结构转 CIF 失败：{e}")
        return None
    return str(out)


# ------------------------------------------------------------------ 元素 / ZVAL


def poscar_atom_elements(path: Path) -> List[str]:
    """本地 POSCAR → **逐原子元素列表**（VASP5 第 6 行元素、第 7 行计数，按序展开）。

    用来把 `ACF.dat` 的原子行（行序 = POSCAR 原子序）对上元素；读的是本地小文件，零负担。
    VASP4（第 6 行是数字）拿不到元素名 → 返回空列表，后续按"没有 ZVAL"降级处理。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = [fh.readline() for _ in range(7)]
    except OSError:
        return []
    if len(lines) < 7:
        return []
    symbols = lines[5].split()
    counts = lines[6].split()
    if not symbols or not counts:
        return []
    if all(re.fullmatch(r"\d+", s) for s in symbols):  # VASP4：第 6 行是计数
        return []
    try:
        nums = [int(c) for c in counts]
    except ValueError:
        return []
    if len(symbols) != len(nums):
        return []
    out: List[str] = []
    for symbol, count in zip(symbols, nums):
        out.extend([symbol] * count)
    return out


def parse_charge_header(text: str) -> Dict[str, Any]:
    """解析 `CHGCAR` 前 7 行里的**元素行 + 计数行**（VASP5）。

    这两行决定 `ACF.dat` 的原子行序 —— 分析时记进 `meta["charge_header"]`，
    之后标注原子元素就以它为准（v0.9.75）。拿不到（VASP4 或文件缺失）返回 `{}`。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return {}
    symbols = lines[0].split()
    counts = lines[1].split()
    if not symbols or not counts:
        return {}
    if all(re.fullmatch(r"\d+", s) for s in symbols):  # VASP4：元素行缺失
        return {}
    if len(symbols) != len(counts):
        return {}
    try:
        nums = [int(c) for c in counts]
    except ValueError:
        return {}
    return {"elements": symbols, "counts": nums, "source": CHGCAR_NAME}


def parse_potcar_zval(text: str) -> Dict[str, float]:
    """从 `grep -E '^ *TITEL|ZVAL' POTCAR` 的输出里解析 **元素 → ZVAL**。

    POTCAR 是各元素块拼接的，每块一行 `TITEL  = PAW_PBE Fe 06Sep2000`（元素名在其中）
    和一行 **`POMASS = 55.845; ZVAL = 8.000    mass and valenz`** —— 注意 ZVAL 与 POMASS
    写在同一行（2026-10-15 在集群真文件上确认），所以用正则从行里取 `ZVAL = <数值>`。
    元素符号取 TITEL 里第一个"不含数字、不是 PAW/PW/US 前缀"的 token（`Fe_pv` 这类后缀不影响判断）。
    """
    result: Dict[str, float] = {}
    pending: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("TITEL"):
            pending = None
            for token in line.split("=", 1)[-1].split():
                if any(ch.isdigit() for ch in token):
                    continue  # 日期 / 版本（06Sep2000、54）
                if token.upper().startswith(("PAW", "PW", "US", "LDA", "GGA")):
                    continue
                m = re.match(r"([A-Za-z]{1,2})", token)
                if m:
                    pending = m.group(1).capitalize()
                    break
        if "ZVAL" in line.upper():
            m = re.search(r"ZVAL\s*=\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE)
            if m:
                try:
                    value = float(m.group(1))
                except ValueError:
                    value = None
                if value is not None:
                    if pending:
                        result[pending] = value
                    pending = None
    return result


# ------------------------------------------------------------------ ACF.dat 解析


def parse_acf(text: str) -> Dict[str, Any]:
    """解析 bader 的 `ACF.dat`（**已按集群上那个 Fortran 版的写出格式对齐**）。

    集群版（`bader -h` 报 1.05 08/19/23，源码 `bader_mod.f90::bader_output`）格式：

        <空行>
            #         X           Y           Z       CHARGE     MIN DIST    ATOMIC VOL
         ----------------------------------------------------------------   ----------------
            1   0.408754   0.107450   0.122784   11.123456      0.567890      12.345678
        ...
         ----------------------------------------------------------------   ----------------
            VACUUM CHARGE:             0.0000
            VACUUM VOLUME:             0.0000
            NUMBER OF ELECTRONS:     620.0000

    老版 C 实现（v1.05）没有 `ATOMIC VOL` 列、页脚是 `N / 总电荷 / 最小距离` 的数字表 ——
    这里两种都认：**原子行 = 以整数开头、后面至少 5 个数字**；页脚按关键字读，
    读不到关键字就把纯数字行存成 `summary_row`。
    """
    atoms: List[Dict[str, Any]] = []
    footer_lines: List[str] = []
    seen_separator = False
    in_footer = False
    has_atomic_vol = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if set(line) <= {"-", " "}:  # 分隔线
            if atoms:
                in_footer = True
            seen_separator = True
            continue
        if line.startswith("#"):
            if "ATOMIC VOL" in line.upper():
                has_atomic_vol = True
            continue
        if not in_footer:
            parts = line.split()
            if len(parts) >= 6 and re.fullmatch(r"\d+", parts[0]):
                try:
                    values = [float(x) for x in parts[1:]]
                except ValueError:
                    footer_lines.append(line)
                    continue
                atom = {
                    "index": int(parts[0]),
                    "x": values[0],
                    "y": values[1],
                    "z": values[2],
                    "charge": values[3],
                    "min_dist": values[4] if len(values) > 4 else None,
                    "atomic_vol": values[5] if len(values) > 5 else None,
                }
                atoms.append(atom)
                continue
            footer_lines.append(line)
        else:
            footer_lines.append(line)

    def _pick(keys: Tuple[str, ...]) -> Optional[float]:
        for line in footer_lines:
            upper = line.upper()
            for key in keys:
                if key in upper:
                    nums = re.findall(r"[-+]?\d+\.\d+|[-+]?\d+", line.split(":", 1)[-1])
                    if nums:
                        try:
                            return float(nums[-1])
                        except ValueError:
                            return None
        return None

    summary_row: Optional[List[float]] = None
    for line in footer_lines:
        if ":" in line:
            continue
        parts = line.split()
        if len(parts) >= 2 and all(re.fullmatch(r"[-+]?\d*\.?\d+", p) for p in parts):
            summary_row = [float(p) for p in parts]
            break

    total_charge = sum(a["charge"] for a in atoms)
    return {
        "n_atoms": len(atoms),
        "atoms": atoms,
        "total_charge": round(total_charge, 6),
        "vacuum_charge": _pick(("VACUUM CHARGE",)),
        "vacuum_volume": _pick(("VACUUM VOLUME",)),
        "n_electrons": _pick(("NUMBER OF ELECTRONS",)),
        "summary_row": summary_row,
        "has_atomic_vol": has_atomic_vol,
        "has_min_dist": any(a["min_dist"] is not None for a in atoms),
        "footer_lines": footer_lines,
        "seen_separator": seen_separator,
    }


def _elements_for_acf(
    meta: Dict[str, Any], local_elements: List[str], n_atoms: int
) -> Tuple[List[str], str, str]:
    """决定 `ACF.dat` 各原子行的元素顺序（v0.9.75）。

    优先级（越靠前越权威）：

    1. **`meta["charge_header"]`** —— 分析时从远端 `CHGCAR` 头部记下的元素/计数行
       （`bader` 就是拿 CHGCAR 算的，**它的行序就是 ACF.dat 的行序**）；
    2. **`meta["zval"]` 的键顺序** —— 分析时 grep 到的 `POTCAR` 顺序（pos2pot 按 POSCAR 拼的，
       所以顺序 = 当时结构的元素顺序）→ 老数据（没有 charge_header）靠这条救回来；
       每种元素的原子数从**本地 POSCAR** 的计数里按元素取（组成必须一致）；
    3. **本地 `files/POSCAR` 的元素行顺序** —— 老行为；本地镜像被后续运行覆盖后会错位，
       所以只在 1、2 都拿不到时使用。

    返回 `(逐原子元素列表, 来源标记, 说明)`；拿不到返回 `([], 来源, 原因)`。
    """
    n_poscar = len(local_elements)
    # 本地 POSCAR 的"元素 → 原子数"（第 1..N 次出现都算同元素）
    counts: Dict[str, int] = {}
    for element in local_elements:
        counts[element] = counts.get(element, 0) + 1

    header = meta.get("charge_header") or {}
    elements = list(header.get("elements") or [])
    numbers = list(header.get("counts") or [])
    if elements and len(elements) == len(numbers) and sum(numbers) == n_atoms:
        out: List[str] = []
        for element, count in zip(elements, numbers):
            out.extend([element] * count)
        note = ""
        if n_poscar and n_poscar == n_atoms and local_elements != out:
            note = (
                "本地 POSCAR 的元素顺序与该次分析的电荷密度（CHGCAR）不同 —— "
                "按分析时记录的顺序标注（本地镜像可能已被后续运行覆盖）"
            )
        return out, "charge-header", note

    zval_order = [str(el) for el in (meta.get("zval") or {})]
    if zval_order and counts and set(zval_order) == set(counts):
        out = []
        for element in zval_order:
            out.extend([element] * counts[element])
        if len(out) == n_atoms:
            note = ""
            if n_poscar == n_atoms and local_elements != out:
                note = (
                    "按分析时 POTCAR 的元素顺序标注（本地 POSCAR 已被后续运行覆盖，顺序不同）"
                )
            return out, "potcar-order", note

    if n_poscar == n_atoms:
        return local_elements, "local-poscar", ""
    if n_poscar:
        return [], "none", (
            f"POSCAR 原子数（{n_poscar}）与 ACF.dat（{n_atoms}）不一致，"
            "不挂净电荷（先确认两边是同一份结构）"
        )
    return [], "none", (
        "本地没有可解析的 POSCAR（VASP5 元素行），算不出逐原子净电荷；"
        "点「同步最新参数」把 POSCAR 取回本地后再看"
    )


def _attach_net_charges(
    parsed: Dict[str, Any],
    project_name: str,
    task: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    """给每个原子补 `element` / `zval` / `net_charge = ZVAL − Bader 电荷`，并算整体统计。

    口径：`ACF.dat` 的行序 = 那次分析的电荷密度（CHGCAR）原子序 → 元素序列按
    `_elements_for_acf()` 的优先级取（分析时冻结的 CHGCAR 头 > 分析时的 POTCAR 顺序 > 本地 POSCAR），
    每种元素的 ZVAL 取**远端 POTCAR 的 TITEL/ZVAL 两行**（探测那一次 exec 里顺手 grep，
    不下载 POTCAR、不用 pymatgen）。任一份缺了就标记 `net_charge_available=false` 并写明原因，
    前端只显示原始 Bader 电荷（不猜）。
    """
    parsed["elements"] = []
    parsed["zval"] = meta.get("zval") or {}
    parsed["net_charge_available"] = False
    poscar = local_files_dir(project_name, task) / "POSCAR"
    local_elements = poscar_atom_elements(poscar)
    elements, element_source, element_note = _elements_for_acf(
        meta, local_elements, int(parsed["n_atoms"])
    )
    parsed["element_source"] = element_source
    if element_note:
        parsed["element_note"] = element_note
    zval: Dict[str, float] = parsed["zval"] or {}
    if not elements:
        parsed["net_charge_reason"] = element_note or "拿不到元素顺序，算不出净电荷"
        return
    if len(elements) != parsed["n_atoms"]:
        parsed["net_charge_reason"] = element_note or "元素顺序长度与 ACF.dat 不一致"
        parsed["elements"] = elements
        return
    if not zval or any(el not in zval for el in set(elements)):
        missing = sorted({el for el in elements if el not in zval})
        parsed["net_charge_reason"] = (
            ("远端 POTCAR 没读到" if not zval else f"POTCAR 里缺 {('、'.join(missing))}")
            + "，算不出净电荷"
        )
        parsed["elements"] = elements
        return

    net_values: List[float] = []
    for atom, element in zip(parsed["atoms"], elements):
        z = float(zval[element])
        atom["element"] = element
        atom["zval"] = round(z, 6)
        atom["net_charge"] = round(z - float(atom["charge"]), 6)
        net_values.append(atom["net_charge"])
    parsed["elements"] = elements
    parsed["net_charge_available"] = True
    zval_total = sum(float(zval[el]) for el in elements)
    net_total = sum(net_values)
    idx_max = max(range(len(net_values)), key=lambda i: net_values[i])
    idx_min = min(range(len(net_values)), key=lambda i: net_values[i])
    parsed["stats"] = {
        "n_atoms": len(net_values),
        "charge_total": round(parsed["total_charge"], 6),
        "zval_total": round(zval_total, 6),
        "net_total": round(net_total, 6),
        "net_mean": round(net_total / len(net_values), 6),
        "net_max": {
            "value": net_values[idx_max],
            "index": parsed["atoms"][idx_max]["index"],
            "element": elements[idx_max],
        },
        "net_min": {
            "value": net_values[idx_min],
            "index": parsed["atoms"][idx_min]["index"],
            "element": elements[idx_min],
        },
    }


def load_data(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """本地 `ACF.dat` → 解析结果（没算过就抛 `BaderError(404)`）。

    一并补上逐原子净电荷与统计（元素序列来自本地 POSCAR、ZVAL 来自远端 POTCAR 的两行 grep，
    缓存在 `meta.json` 里）——**纯本地读文件，不连远端**。
    """
    path = acf_path(project_name, task)
    if not (path.is_file() and path.stat().st_size > 0):
        raise BaderError("本地还没有 Bader 结果（先在巡检详情里点一次「计算 Bader 电荷」）", 404)
    parsed = parse_acf(path.read_text(encoding="utf-8", errors="replace"))
    meta = read_meta(project_name, task)
    _attach_net_charges(parsed, project_name, task, meta)
    parsed["meta"] = meta
    parsed["source"] = to_local_rel(str(path))
    parsed["bytes"] = path.stat().st_size
    parsed["mtime"] = int(path.stat().st_mtime)
    return parsed


def charge_summary(project_name: str, task: Dict[str, Any], atom_indices=None,
                   reference_charge=None) -> Dict[str, Any]:
    """复用分析时的元素/ZVAL口径，返回紧凑原子表和指定片段求和；纯本地只读。"""
    data = load_data(project_name, task)
    atoms = {a["index"]: a for a in data["atoms"]}
    if atom_indices is not None and any(i not in atoms for i in atom_indices):
        raise ValueError("片段原子编号不在该次 Bader 表中")
    selected = [atoms[i] for i in atom_indices] if atom_indices is not None else list(atoms.values())
    element_map = dict(zip(atoms, data.get("elements", [])))
    composition = dict(Counter(element_map.get(a["index"], "unknown") for a in selected))
    electrons = math.fsum(a["charge"] for a in selected)
    available = data["net_charge_available"]
    valence = math.fsum(a["zval"] for a in selected) if available else None
    net = round(valence - electrons, 6) if available else None
    return {
        "task_id": task["task_id"], "name": task.get("model_name"),
        "scope": "selected_atoms" if atom_indices is not None else "whole_system",
        "atom_count": len(selected), "total_atom_count": data["n_atoms"], "composition": composition,
        "bader_electrons": round(electrons, 6),
        "neutral_valence_electrons": round(valence, 6) if available else None,
        "net_charge_e": net, "reference_charge_e": reference_charge,
        "electron_gain_from_reference_e": round(reference_charge - net, 6)
            if reference_charge is not None and available else None,
        "net_charge_available": available, "net_charge_reason": data.get("net_charge_reason"),
        "columns": ["index", "element", "bader_electrons", "net_charge_e", "x_A", "y_A", "z_A"],
        "atoms": [[a["index"], element_map.get(a["index"]), a["charge"], a.get("net_charge"),
                   a["x"], a["y"], a["z"]] for a in selected],
        "zval": data["zval"],
        "source": {"path": data["source"], "mtime": data["mtime"], "bytes": data["bytes"],
                   "analysis_run_id": data["meta"].get("run_id"),
                   "element_source": data["element_source"], "element_note": data.get("element_note")},
        "definition": "净电荷=ΣZVAL−ΣBader电子数，负值表示相对中性原子得电子；"
                      "转移电子数=参考片段净电荷−当前片段净电荷，仅在明确reference_charge时给出。"
                      "坐标和编号来自该次ACF；低电子数本身不证明Bader异常。",
    }


# ------------------------------------------------------------------ 远端探测


def _remote_probe_script(ele_remote: str, exe: str, vtst: str) -> str:
    return "\n".join(
        [
            f'cd "{ele_remote}" 2>/dev/null || {{ echo "@@@NODIR"; exit 3; }}',
            'echo "@@@EXE"',
            f'B="{exe}"',
            '[ -x "$B" ] && echo "R bader ok" || echo "R bader missing"',
            f'[ -x "{vtst}/chgsum.pl" ] && echo "R chgsum ok" || echo "R chgsum missing"',
            'echo "@@@FILES"',
            "for f in " + " ".join(AECCAR_FILES) + f" CHGCAR {CHG_SUM_NAME} {CHG_SUM_AEC_NAME} {ACF_NAME}; do",
            '  if [ -s "$f" ]; then echo "T $f $(wc -c < "$f" | tr -d \' \')"; else echo "T $f 0"; fi',
            "done",
            # Bader 的参考电荷能不能复用：CHGCAR_sum_aec 必须与 AECCAR0 **同结构同网格**。
            # chgsum.pl 把第一个输入的前若干行（元素/计数/坐标/网格行）原样拷进输出，
            # 所以比对这几行 + 总行数就能判定它是不是 AECCAR0+AECCAR2 的和
            # （差分电荷留下的分块和头是分块元素，一定对不上）。
            'echo "@@@SUMAEC"',
            f'if [ -s "{CHG_SUM_AEC_NAME}" ]; then',
            # 只读前 7 行（head 会提前退出）——`sed -n '6,7p'` 会把 94MB 整个读一遍
            f'  _h1=$(head -7 AECCAR0 | tail -2 | tr -s \' \\t\' \' \')',
            f'  _h2=$(head -7 "{CHG_SUM_AEC_NAME}" | tail -2 | tr -s \' \\t\' \' \')',
            f'  _l1=$(wc -l < AECCAR0 | tr -d \' \')',
            f'  _l2=$(wc -l < "{CHG_SUM_AEC_NAME}" | tr -d \' \')',
            '  if [ -n "$_h2" ] && [ "$_h1" = "$_h2" ] && [ "$_l1" = "$_l2" ]; then',
            '    echo "V aec ok"; else echo "V aec mismatch"; fi',
            'else echo "V aec absent"; fi',
            # **电荷密度的元素顺序**（v0.9.75）：bader 拿 CHGCAR 算，ACF.dat 的原子行序 = CHGCAR 头部的
            # 元素/计数顺序。这里把它记下来（只读前 7 行），分析时就冻结在 meta 里 ——
            # 否则本地 `files/POSCAR` 被后续运行覆盖后，元素标注会整排错位
            # （2026-10-16 用户报的 PMS@model1 Fe S H O / Fe S O H 就是这个）。
            'echo "@@@CHGHDR"',
            f'[ -s "{CHGCAR_NAME}" ] && head -7 "{CHGCAR_NAME}" | tail -2 | tr -s \' \\t\' \' \'',
            'echo "@@@CHGHDR_END"',
            # 元素价电子数 ZVAL：只 grep POTCAR 两行（几百字节），不下载 POTCAR、不引依赖
            'echo "@@@POTCAR"',
            f'[ -s "{POTCAR_NAME}" ] && echo "P potcar ok" || echo "P potcar missing"',
            # 注意：真 POTCAR 的 ZVAL 与 POMASS 写在同一行（`POMASS = 26.982; ZVAL = 3.000 mass and valenz`），
            # 所以不能按行首匹配 ZVAL，用 `^ *TITEL|ZVAL` 抓两种行
            f'grep -E \'^ *TITEL|ZVAL\' "{POTCAR_NAME}" 2>/dev/null | head -n 60',
            'echo "@@@POTCAR_END"',
            'echo "@@@END"',
        ]
    )


def _integrity(sizes: Dict[str, int]) -> Dict[str, Any]:
    """AECCAR0/1/2 都要在，且大小差别 < `SIZE_TOLERANCE`。

    三个文件写在同一 FFT 网格上（同差分电荷的分块 CHGCAR 一样），大小应当基本一致；
    差得多说明某一份没写完 / 被截断（LAECHG 写 AECCAR0/1/2 时逐份落盘）。
    """
    missing = [name for name in AECCAR_FILES if not sizes.get(name)]
    values = [sizes[name] for name in AECCAR_FILES if sizes.get(name)]
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "max": max(values) if values else 0,
            "min": min(values) if values else 0,
            "spread": None,
            "reason": "远端缺少 " + "、".join(missing) + "（或大小为 0）"
            + "（需要 INCAR 里 LAECHG=.TRUE. 并重新算一轮）",
        }
    hi, lo = max(values), min(values)
    spread = (hi - lo) / hi if hi else 0.0
    if spread > SIZE_TOLERANCE:
        return {
            "ok": False,
            "missing": [],
            "max": hi,
            "min": lo,
            "spread": round(spread, 4),
            "reason": (
                f"三个 AECCAR 大小差别 {spread * 100:.1f}%（{lo} B ~ {hi} B），"
                f"超过 {SIZE_TOLERANCE * 100:.0f}% 阈值：可能某一份没写完或被截断"
            ),
        }
    return {
        "ok": True,
        "missing": [],
        "max": hi,
        "min": lo,
        "spread": round(spread, 4),
        "reason": f"三个 AECCAR 大小一致（差别 {spread * 100:.2f}%）",
    }


def probe_remote(
    project: Dict[str, Any], task: Dict[str, Any], *, refresh: bool = False
) -> Dict[str, Any]:
    """远端探测（一次 exec，约 0.5–1.5s）：AECCAR 完整性 + bader/chgsum 可用性 + ACF.dat 在不在。"""
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        cached = _PROBE_CACHE.get(task_id)
        if cached and not refresh and time.time() - cached[0] < PROBE_TTL_SECONDS:
            return cached[1]

    server = str(project.get("server") or "")
    ele_remote = task_remote_dir(server, task).rstrip("/")
    result: Dict[str, Any] = {
        "remote_dir": ele_remote,
        "checked_at": now_iso(),
        "ok": False,
        "state": "unknown",
        "reason": "",
        "sizes": {},
        "integrity": None,
        "tools": {},
        "has_sum": False,
        "has_sum_aec": False,
        "sum_aec_valid": False,
        "has_remote_acf": False,
        "bader_exe": bader_exe(server),
    }
    if not ele_remote:
        result["reason"] = "任务缺少远程目录"
        return result

    script = _remote_probe_script(ele_remote, result["bader_exe"], vtst_dir(server))
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    try:
        run = ssh.run_remote(server, f"echo {encoded} | base64 -d | bash", timeout=180)
    except Exception as e:  # noqa: BLE001 - 远端不可达
        result["reason"] = f"远端探测失败：{type(e).__name__}: {e}"
        return result
    raw = f"{run.get('stdout', '')}\n{run.get('stderr', '')}".strip()
    if "@@@NODIR" in raw:
        result["reason"] = f"远端任务目录不存在：{ele_remote}"
        return result

    sizes: Dict[str, int] = {}
    tools: Dict[str, bool] = {}
    sum_aec_state = "absent"
    potcar_text: List[str] = []
    in_potcar = False
    charge_header_text: List[str] = []
    in_charge_header = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "@@@CHGHDR":
            in_charge_header = True
            continue
        if stripped == "@@@CHGHDR_END":
            in_charge_header = False
            continue
        if in_charge_header:
            charge_header_text.append(line)
            continue
        if stripped == "@@@POTCAR":
            in_potcar = True
            continue
        if stripped == "@@@POTCAR_END":
            in_potcar = False
            continue
        if in_potcar:
            potcar_text.append(line)
            continue
        line = stripped
        if line.startswith("T "):
            parts = line[2:].split(" ", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                sizes[parts[0]] = int(parts[1].strip())
        elif line.startswith("R "):
            parts = line[2:].split(" ", 1)
            if len(parts) == 2:
                tools[parts[0]] = parts[1].strip() == "ok"
        elif line.startswith("V aec "):
            sum_aec_state = line[len("V aec "):].strip()

    result["sizes"] = sizes
    result["tools"] = tools
    result["has_sum"] = bool(sizes.get(CHG_SUM_NAME))
    result["has_sum_aec"] = bool(sizes.get(CHG_SUM_AEC_NAME))
    result["sum_aec_valid"] = sum_aec_state == "ok"
    result["has_remote_acf"] = bool(sizes.get(ACF_NAME))
    result["integrity"] = _integrity(sizes)
    result["zval"] = parse_potcar_zval("\n".join(potcar_text))
    # 电荷密度的元素/计数顺序（ACF.dat 的行序）——分析时冻结，供元素标注用
    result["charge_header"] = parse_charge_header("\n".join(charge_header_text))
    result["has_potcar"] = any(
        ln.strip().startswith("P potcar ok") for ln in potcar_text
    )
    legacy_note = (
        f"（注：目录里另有一份 `{CHG_SUM_NAME}`，那是差分电荷的分块和，Bader 不用它）"
        if result["has_sum"]
        else ""
    )

    if result["has_remote_acf"]:
        result.update({"ok": True, "state": "remote_acf",
                       "reason": "远端已有 ACF.dat（可直接回传，不必重算）"})
    elif not result["integrity"]["ok"]:
        result.update({"state": "incomplete", "reason": result["integrity"]["reason"]})
    elif not tools.get("bader"):
        result.update({"state": "no_bader",
                       "reason": f"远端找不到 bader 可执行文件：{result['bader_exe']}"
                                 "（可用 servers.json: bader_exe 覆盖）"})
    elif not tools.get("chgsum"):
        result.update({"state": "no_chgsum",
                       "reason": f"远端找不到 chgsum.pl：{vtst_dir(server)}"
                                 "（可用 servers.json: vtst_dir 覆盖）"})
    elif sizes.get("CHGCAR", 0) <= 0:
        result.update({"state": "incomplete", "reason": "远端缺少 CHGCAR（bader 的待分析电荷）"})
    else:
        if result["sum_aec_valid"]:
            note = (
                f"远端已有 Bader 自己的参考电荷 {CHG_SUM_AEC_NAME}"
                f"（校验过与 AECCAR0 同结构同网格），跳过 chgsum"
            )
        else:
            note = f"可计算（先在 .bader_sum/ 里跑 chgsum.pl AECCAR0 AECCAR2 → {CHG_SUM_AEC_NAME}）"
        note += legacy_note
        result.update({"ok": True, "state": "ready", "reason": note})
    with _LOCK:
        _PROBE_CACHE[task_id] = (time.time(), result)
    # 顺手把 ZVAL 缓进本地 meta（给纯本地的 load_data 用；探测一次就够）
    _remember_zval(
        str(project.get("name") or ""),
        task,
        result.get("zval") or {},
        result.get("charge_header") or {},
    )
    return result


# ------------------------------------------------------------------ 状态查询


def local_status(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """只看本地（零 SSH）：有没有 ACF.dat。"""
    path = acf_path(project_name, task)
    has = path.is_file() and path.stat().st_size > 0
    return {
        "has_acf": has,
        "acf_path": str(path) if has else "",
        "acf_bytes": path.stat().st_size if has else 0,
        "acf_mtime": int(path.stat().st_mtime) if has else 0,
        "meta": read_meta(project_name, task),
    }


def status(
    project_name: str,
    task: Dict[str, Any],
    run_id: str = "",
    *,
    remote: bool = False,
    project: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """链路状态：本地 + 当前/最近一次 run（`remote=True` 时附带远端探测）。"""
    task_id = str(task.get("task_id") or "")
    local = local_status(project_name, task)
    with _LOCK:
        rid = run_id or _TASK_RUN.get(task_id, "")
        if not rid:
            latest = [r for r in _RUNS.values() if r.get("task_id") == task_id]
            rid = latest[-1]["run_id"] if latest else ""
        run = dict(_RUNS.get(rid) or {})
    meta = local.get("meta") or {}
    if not run:
        run = {
            "run_id": rid,
            "status": "failed" if meta.get("status") == "failed" else (
                "done" if local["has_acf"] else "idle"
            ),
            "error": meta.get("error"),
            "stage": meta.get("stage"),
            "finished_at": meta.get("finished_at"),
        }
    run["stage_label"] = STAGE_LABELS.get(str(run.get("stage") or ""), "")
    run["local"] = {k: v for k, v in local.items() if k != "meta"}
    run["meta"] = meta
    if remote and project is not None:
        run["remote"] = probe_remote(project, task)
    return run


# ------------------------------------------------------------------ 异步链路


def start(project: Dict[str, Any], task: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """触发链路：已有在跑的 run 就复用，否则起后台线程。"""
    task_id = str(task.get("task_id") or "")
    if not task_remote_dir(str(project.get("server") or ""), task):
        raise BaderError("任务缺少远程目录", 400)
    with _LOCK:
        current = _TASK_RUN.get(task_id)
        if current and _RUNS.get(current, {}).get("status") == "running":
            return {"run_id": current, "status": "running", "reused": True}
        run_id = f"bader_{int(time.time() * 1000)}"
        _RUNS[run_id] = {
            "run_id": run_id,
            "task_id": task_id,
            "status": "running",
            "stage": "checking",
            "started_at": now_iso(),
        }
        _TASK_RUN[task_id] = run_id
    threading.Thread(
        target=_background,
        args=(dict(project), dict(task), run_id, bool(force)),
        name=f"bader-{task_id}",
        daemon=True,
    ).start()
    return {"run_id": run_id, "status": "running", "reused": False}


def _set_stage(run_id: str, stage: str, **extra: Any) -> None:
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update({"stage": stage, **extra})


def _run_capture(server: str, script: str, *, timeout: int) -> Dict[str, Any]:
    """跑一段远端 bash（专用连接：bader 可能跑很久，别占常驻池的串行锁）。"""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return ssh.run_remote(
        server, f"echo {encoded} | base64 -d | bash", timeout=timeout, dedicated=True
    )


def _remote_compute_script(ele_remote: str, exe: str, vtst: str, reuse_sum: bool) -> str:
    """远端：`chgsum.pl AECCAR0 AECCAR2` →（Bader 自己的）`CHGCAR_sum_aec`；再 bader 出 `ACF.dat`。

    `reuse_sum=True` 表示探测阶段已经**校验过** `CHGCAR_sum_aec` 与 AECCAR0 同结构同网格，
    可以直接复用；否则在子目录 `.bader_sum/` 里跑 chgsum（软链到 AECCAR0/AECCAR2），
    输出 mv 成 `CHGCAR_sum_aec` —— **不碰**目录里那份可能是差分电荷留下的 `CHGCAR_sum`。
    """
    lines = [
        f'cd "{ele_remote}" || {{ echo "@@@NODIR"; exit 3; }}',
        f'B="{exe}"',
        '[ -x "$B" ] || { echo "@@@NOBADER=$B"; exit 4; }',
        f'[ -x "{vtst}/chgsum.pl" ] || {{ echo "@@@NOSCRIPT"; exit 5; }}',
        "for f in AECCAR0 AECCAR2 CHGCAR; do",
        '  [ -s "$f" ] || { echo "@@@MISSING=$f"; exit 6; }',
        "done",
    ]
    if reuse_sum:
        lines.append(
            f'[ -s "{CHG_SUM_AEC_NAME}" ] || {{ echo "@@@MISSING={CHG_SUM_AEC_NAME}"; exit 6; }}'
        )
        lines.append('echo "@@@SUM_REUSED"')
    else:
        lines += [
            f'mkdir -p "{SUM_WORK_DIR}"',
            f'ln -sf "$PWD/AECCAR0" "$PWD/AECCAR2" "{SUM_WORK_DIR}/"',
            f'if ! ( cd "{SUM_WORK_DIR}" && "{vtst}/chgsum.pl" AECCAR0 AECCAR2 '
            '> chgsum.log 2>&1 ); then '
            f'echo "@@@CHGSUM_FAIL"; tail -n 20 "{SUM_WORK_DIR}/chgsum.log"; exit 7; fi',
            f'[ -s "{SUM_WORK_DIR}/{CHG_SUM_NAME}" ] || {{ echo "@@@NO_SUM"; exit 8; }}',
            f'mv -f "{SUM_WORK_DIR}/{CHG_SUM_NAME}" "{CHG_SUM_AEC_NAME}"',
            'echo "@@@SUM_OK"',
        ]
    lines += [
        # Bader 本体：默认不写体积文件（AVF.dat 要 -p 才写），只出 ACF.dat / BCF.dat
        'if ! "$B" CHGCAR -ref ' + CHG_SUM_AEC_NAME + ' > bader.log 2>&1; then '
        'echo "@@@BADER_FAIL"; tail -n 30 bader.log; exit 9; fi',
        f'[ -s "{ACF_NAME}" ] || {{ echo "@@@NO_ACF"; tail -n 20 bader.log; exit 10; }}',
        f'echo "@@@ACF_BYTES=$(wc -c < {ACF_NAME} | tr -d \' \')"',
        'echo "@@@BADER_TAIL"',
        'tail -n 8 bader.log || true',
        'echo "@@@END"',
    ]
    return "\n".join(lines)


def _parse_markers(raw: str) -> Dict[str, Any]:
    acf_bytes = 0
    m = re.search(r"@@@ACF_BYTES=(\d+)", raw)
    if m:
        acf_bytes = int(m.group(1))
    tail = ""
    if "@@@BADER_TAIL" in raw:
        tail = raw.split("@@@BADER_TAIL", 1)[1].split("@@@END", 1)[0].strip()
    return {"acf_bytes": acf_bytes, "bader_tail": tail[-800:]}


def _fail(
    project_name: str,
    task: Dict[str, Any],
    run_id: str,
    stage: str,
    message: str,
    started: str,
) -> None:
    meta = read_meta(project_name, task)
    meta.update(
        {
            "task_id": str(task.get("task_id") or ""),
            "project_name": project_name,
            "run_id": run_id,
            "status": "failed",
            "stage": stage,
            "error": message,
            "started_at": started,
            "finished_at": now_iso(),
        }
    )
    try:
        _write_json(meta_path(project_name, task), meta)
    except Exception as e:  # noqa: BLE001
        _log_line(f"[warn] 写 meta 失败：{e}")
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            run.update(
                {
                    "status": "failed",
                    "stage": stage,
                    "error": message,
                    "finished_at": meta["finished_at"],
                }
            )
    _log_line(f"[fail] {project_name}/{task.get('task_id')} stage={stage} {message}")


def _record_task_bader(project_name: str, task_id: str, payload: Optional[Dict[str, Any]]) -> None:
    """把结果记到 ele 主任务 `task["bader"]`（巡检详情 / 报告以后读这个字段）。"""
    try:
        with db_transaction() as db:
            proj = next(
                (p for p in db.get("projects", []) if p.get("name") == project_name), None
            )
            task = (
                next((t for t in proj.get("tasks", []) if t.get("task_id") == task_id), None)
                if proj
                else None
            )
            if task is not None:
                if payload is None:
                    task.pop("bader", None)
                else:
                    task["bader"] = {**payload, "synced_at": now_iso()}
    except Exception as e:  # noqa: BLE001
        _log_line(f"[warn] 写回 bader 台账失败（{project_name}/{task_id}）：{e}")


def _background(
    project: Dict[str, Any], task: Dict[str, Any], run_id: str, force: bool
) -> None:
    """后台线程：校验 → chgsum → bader → 回传 → 解析 → 写台账。"""
    project_name = str(project.get("name") or "")
    server = str(project.get("server") or "")
    task_id = str(task.get("task_id") or "")
    started = now_iso()
    t0 = time.time()
    stage = "checking"
    with _JOB_LOCK:
        try:
            ele_remote = task_remote_dir(server, task).rstrip("/")
            if not ele_remote:
                raise BaderError("任务缺少远程目录", 400)

            local_has = has_local(project_name, task)
            probe: Dict[str, Any] = {"state": "local", "reason": "本地已有 ACF.dat，只重新解析"}
            compute: Dict[str, Any] = {"acf_bytes": 0, "bader_tail": "", "sum_reused": False}
            target = acf_path(project_name, task)
            remote_acf = f"{ele_remote}/{ACF_NAME}"
            # 中断补偿：本地已有结果且不是强制重算 → 完全不碰远端，只重新解析
            if not local_has or force:
                _set_stage(run_id, "checking")
                probe = probe_remote(project, task, refresh=True)
                if not probe.get("ok") and not probe.get("has_remote_acf"):
                    raise BaderError(f"远端文件校验未通过：{probe.get('reason') or '未知原因'}", 400)
                # 远端已有 ACF.dat（且不是强制重算）→ 只回传，不重跑 chgsum/bader
                if force or not probe.get("has_remote_acf"):
                    # 只有在探测里**校验通过**（与 AECCAR0 同结构同网格）才复用 Bader 自己的和；
                    # 目录里那份 `CHGCAR_sum` 可能是差分电荷留下的分块和 —— 一律不认。
                    _set_stage(
                        run_id, "bader" if probe.get("sum_aec_valid") else "summing"
                    )
                    script = _remote_compute_script(
                        ele_remote,
                        bader_exe(server),
                        vtst_dir(server),
                        reuse_sum=bool(probe.get("sum_aec_valid")),
                    )
                    run = _run_capture(server, script, timeout=3600)
                    raw = f"{run.get('stdout', '')}\n{run.get('stderr', '')}".strip()
                    if int(run.get("exit_code") or 0) != 0 or "@@@END" not in raw:
                        detail = " / ".join(
                            line.strip() for line in raw.splitlines() if line.strip()
                        )[-500:]
                        for marker, message in (
                            ("@@@NOBADER=", "远端找不到 bader 可执行文件"),
                            ("@@@NOSCRIPT", "远端找不到 chgsum.pl"),
                            ("@@@MISSING=", "远端缺少文件"),
                            ("@@@CHGSUM_FAIL", "chgsum.pl 执行失败"),
                            ("@@@NO_SUM", "chgsum.pl 跑完但没有生成 CHGCAR_sum"),
                            ("@@@BADER_FAIL", "bader 执行失败"),
                            ("@@@NO_ACF", "bader 跑完但没有生成 ACF.dat"),
                        ):
                            if marker in raw:
                                extra = ""
                                if marker.endswith("="):
                                    extra = "：" + raw.split(marker, 1)[1].split("\n", 1)[0].strip()
                                raise BaderError(
                                    f"{message}{extra}；远端输出：{detail}"
                                    if detail
                                    else f"{message}{extra}",
                                    502,
                                )
                        raise BaderError(
                            f"远端计算失败（exit={run.get('exit_code')}）：{detail}", 502
                        )
                    compute = _parse_markers(raw)
                    compute["sum_reused"] = "@@@SUM_REUSED" in raw

                stage = "downloading"
                _set_stage(run_id, "downloading")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not ssh.download_file(server, remote_acf, str(target)):
                    raise BaderError("ACF.dat 回传失败（远端下载不到）", 502)
            if not (target.is_file() and target.stat().st_size > 0):
                raise BaderError("本地没有 ACF.dat（回传失败？）", 502)

            stage = "parsing"
            _set_stage(run_id, "parsing")
            parsed = parse_acf(target.read_text(encoding="utf-8", errors="replace"))
            if parsed["n_atoms"] <= 0:
                raise BaderError("ACF.dat 解析不出原子行（格式不认识？）", 500)

            payload = {
                "ok": True,
                "n_atoms": parsed["n_atoms"],
                "total_charge": parsed["total_charge"],
                "n_electrons": parsed["n_electrons"],
                "vacuum_charge": parsed["vacuum_charge"],
                "vacuum_volume": parsed["vacuum_volume"],
                "has_atomic_vol": parsed["has_atomic_vol"],
                "has_min_dist": parsed["has_min_dist"],
                "local_path": to_local_rel(str(target)),
                "remote_path": remote_acf,
                "bytes": target.stat().st_size,
                "elapsed_seconds": round(time.time() - t0, 1),
                "sum_reused": bool(compute.get("sum_reused")),
                "bader_exe": bader_exe(server),
                "integrity": probe.get("integrity"),
                "has_potcar": bool(probe.get("has_potcar")),
                "bader_tail": compute.get("bader_tail") or "",
            }
            # 冻结"这次分析用的结构"（v0.9.75）：与 ACF.dat 同源，之后本地镜像被覆盖也不影响
            frozen = _freeze_structure(server, ele_remote, project_name, task)
            if frozen:
                payload["structure_cif"] = to_local_rel(frozen)
            meta = {
                "task_id": task_id,
                "project_name": project_name,
                "run_id": run_id,
                "status": "done",
                "stage": "done",
                "started_at": started,
                "finished_at": now_iso(),
                "elapsed_seconds": payload["elapsed_seconds"],
                "remote": {
                    "state": probe.get("state"),
                    "reason": probe.get("reason"),
                    "remote_dir": probe.get("remote_dir") or ele_remote,
                },
                # 元素价电子数（远端 POTCAR 两行 grep 的结果）——load_data 用它算净电荷
                "zval": probe.get("zval") or {},
                # **这次分析**用的电荷密度头部（元素/计数顺序 = ACF.dat 的行序，v0.9.75）：
                # 与 zval 一起冻结，之后本地 POSCAR 被后续运行覆盖也不会标错元素
                "charge_header": probe.get("charge_header") or {},
                "result": payload,
            }
            _write_json(meta_path(project_name, task), meta)
            _record_task_bader(project_name, task_id, payload)
            with _LOCK:
                run_state = _RUNS.get(run_id)
                if run_state is not None:
                    run_state.update(
                        {
                            "status": "done",
                            "stage": "done",
                            "finished_at": meta["finished_at"],
                            "elapsed_seconds": payload["elapsed_seconds"],
                            "result": payload,
                        }
                    )
            _log_line(
                f"[ok] {project_name}/{task_id} atoms={payload['n_atoms']} "
                f"electrons={payload['n_electrons']} bytes={payload['bytes']} "
                f"sum_reused={payload['sum_reused']} elapsed={payload['elapsed_seconds']}s"
            )
        except BaderError as exc:
            _fail(project_name, task, run_id, stage, str(exc), started)
        except Exception as exc:  # noqa: BLE001 - 线程里不能抛
            _fail(project_name, task, run_id, stage, f"{type(exc).__name__}: {exc}", started)
        finally:
            with _LOCK:
                if _TASK_RUN.get(task_id) == run_id:
                    _TASK_RUN.pop(task_id, None)


def clear(project_name: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """清除本地 Bader 结果（ACF.dat + meta），远端文件不动。"""
    removed: List[str] = []
    for path, label in ((acf_path(project_name, task), "ACF.dat"),
                        (meta_path(project_name, task), "meta.json")):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(label)
    task_id = str(task.get("task_id") or "")
    with _LOCK:
        _PROBE_CACHE.pop(task_id, None)
        rid = _TASK_RUN.pop(task_id, "")
        if rid:
            _RUNS.pop(rid, None)
    _record_task_bader(project_name, task_id, None)
    return {"removed": removed, "dir": str(local_dir(project_name, task))}
