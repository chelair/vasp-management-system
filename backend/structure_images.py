"""结构三视图（VESTA PNG）的调度与取用（巡检 / 报告共用）。

用户口径（2026-10-07）：
- **什么时候画**：opt 任务**已收敛（completed）或已归档**、自由能组的结构优化任务同理
  （**不含频率矫正 frac**）、NEB 任务**已完成 / 已归档**（按映像画 `images/<映像号>/{a,b,c}.png`）；
- **画到哪**：与 `files/` 同级的 `<任务目录>/images/`（opt = `{poscar,contcar}_{a,b,c}.png`）；
- **覆盖**：同名覆盖，默认"图比结构文件新就复用"（`render_task` / `render_neb_images` 内部判断）；
- **报告**：优先用 `images/` 里的图，没有就跳过（不阻塞报告生成）。

调度：巡检回填后、归档文件同步完成后各触发一次。渲染必须跑在 Xvfb 里
（服务自身没有 DISPLAY，见 DEPENDENCIES.md §3b），所以统一丢后台线程 + `xvfb-run` 子进程，
串行执行、失败只记日志，绝不影响巡检/归档主流程。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import vesta_render
from storage import load_db

#: 已收敛 / 已收尾的任务状态（可出结构图）
READY_STATUSES = ("completed", "archived")

_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_QUEUED: set = set()
_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None
_LOG = Path(__file__).resolve().parent.parent / "data" / "structure_images.log"


def _log(message: str) -> None:
    """渲染日志（失败排查用；不影响主流程）。"""
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{__import__('datetime').datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def should_render(task: Dict[str, Any]) -> bool:
    """这个任务现在该不该出结构图（纯判断，不看文件）。"""
    task_type = str(task.get("task_type") or "")
    status = str(task.get("status") or "")
    if task_type == "frac":
        # 频率矫正：用户明确说不画
        return False
    if task_type not in ("opt", "ele", "neb"):
        return False
    if status in READY_STATUSES:
        return True
    # 归档任务：归档前的状态就是"收尾状态"，completed 才画
    if status == "archived":
        return True
    return False


def _task_dir(project_name: str, task: Dict[str, Any]) -> Path:
    from task_paths import task_dir

    return task_dir(project_name, task)


def task_views(project_name: str, task: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """取任务的 a/b/c 三视图 PNG（opt/ele）：{"contcar": {"a": 路径, ...}}；缺的键不出现。"""
    image_dir = vesta_render.structure_image_dir({"name": project_name}, task)
    result: Dict[str, Dict[str, str]] = {}
    for label in ("poscar", "contcar"):
        views = {}
        for axis in ("a", "b", "c"):
            path = image_dir / f"{label}_{axis}.png"
            if vesta_render._output_ready(path):  # 截断的图不算
                views[axis] = str(path)
        if views:
            result[label] = views
    return result


def neb_views(
    project_name: str, task: Dict[str, Any]
) -> Dict[str, Dict[str, str]]:
    """取 NEB 各映像的三视图：{"00": {"a": 路径, ...}, "01": {...}}；缺的映像不出现。"""
    image_dir = vesta_render.structure_image_dir({"name": project_name}, task)
    result: Dict[str, Dict[str, str]] = {}
    if not image_dir.is_dir():
        return result
    for sub in sorted(
        (p for p in image_dir.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: int(p.name),
    ):
        views = {}
        for axis in ("a", "b", "c"):
            path = sub / f"{axis}.png"
            if vesta_render._output_ready(path):
                views[axis] = str(path)
        if views:
            result[sub.name] = views
    return result


def image_label_key(label: Any) -> str:
    """映像编号归一化：巡检数据里是 `0`/`1`，图目录是 `00`/`01` —— 都归成两位数字。"""
    text = str(label or "").strip()
    if text.isdigit():
        return f"{int(text):02d}"
    return text


# --------------------------------------------------------------------------
# 后台渲染：队列 + xvfb-run 子进程（服务没有 DISPLAY）


_WORKER_SNIPPET = """
import json, sys
sys.path.insert(0, {backend!r})
from structure_images import run_render_job
print(json.dumps(run_render_job(json.loads(sys.argv[1])), ensure_ascii=False))
"""


def _render_one(project_name: str, task: Dict[str, Any], steps: Optional[int]) -> Dict[str, Any]:
    project = {"name": project_name}
    if str(task.get("task_type")) == "neb":
        return vesta_render.render_neb_images(project, task)
    return vesta_render.render_task(project, task, steps=steps)


def run_render_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """在子进程里真正干活（**必须在 xvfb 里跑**）。

    payload 可以带一个任务（`task`）或一批（`tasks`）——批处理只起一次 Vesta/Xvfb，
    巡检一轮要刷几十个任务时差别很大。
    """
    project_name = str(payload.get("project") or "")
    jobs = payload.get("tasks")
    if jobs is None:
        jobs = [{"task": payload.get("task"), "steps": payload.get("steps")}]
    results = []
    for job in jobs:
        task = job.get("task")
        if not task:
            continue
        try:
            out = _render_one(project_name, task, job.get("steps"))
            results.append(
                {
                    "task_id": out.get("task_id"),
                    "images": len(out.get("images") or {}),
                    "warnings": out.get("warnings") or [],
                }
            )
        except Exception as e:  # noqa: BLE001 - 单个任务失败不影响整批
            results.append({"task_id": task.get("task_id"), "error": str(e)})
    return {"project": project_name, "tasks": results}


def render_now(project_name: str, task: Dict[str, Any], steps: Optional[int] = None) -> Dict[str, Any]:
    """同步渲染一个任务（调用者自己保证在 xvfb 里；给测试/脚本用）。"""
    return _render_one(project_name, task, steps)


def _xvfb_command(payload: Dict[str, Any]) -> List[str]:
    backend = str(Path(__file__).resolve().parent)
    return [
        "xvfb-run",
        "-a",
        "-s",
        "-screen 0 1400x1000x24",
        sys.executable,
        "-c",
        _WORKER_SNIPPET.format(backend=backend),
        json.dumps(payload, ensure_ascii=False),
    ]


def _worker_loop() -> None:
    while True:
        job = _QUEUE.get()
        try:
            label = str(job.get("key") or job.get("project") or "")
            env = dict(os.environ, LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe")
            done = subprocess.run(
                _xvfb_command(job),
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )
            tail = (done.stdout or done.stderr or "").strip().splitlines()
            summary = tail[-1] if tail else ""
            _log(f"[ok] {label} rc={done.returncode} {summary[:400]}")
        except Exception as e:  # noqa: BLE001 - 渲染失败不影响主流程
            _log(f"[fail] {job.get('key') or job.get('project')} {e}")
        finally:
            with _LOCK:
                _QUEUED.discard(str(job.get("key") or ""))
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="structure-images", daemon=True)
            _WORKER.start()


def schedule(project_name: str, task: Dict[str, Any], steps: Optional[int] = None) -> bool:
    """把"给这个任务出结构图"排进后台队列（先判断该不该画 + 去重）。返回是否入队。"""
    if not should_render(task):
        return False
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return False
    key = f"{project_name}:{task_id}"
    with _LOCK:
        if key in _QUEUED:
            return False
        _QUEUED.add(key)
    _QUEUE.put(
        {
            "project": project_name,
            "key": key,
            "tasks": [{"task": task, "steps": steps}],
        }
    )
    _ensure_worker()
    return True


def schedule_for_project_tasks(
    project_name: str, task_ids: Optional[List[str]] = None
) -> int:
    """批量排队（巡检结束时调用）：**整批合成一个后台作业**，只起一次 Xvfb。"""
    try:
        db = load_db()
    except Exception as e:  # noqa: BLE001
        _log(f"[fail] 读取数据库失败：{e}")
        return 0
    project = next((p for p in db.get("projects", []) if p.get("name") == project_name), None)
    if project is None:
        return 0
    wanted = set(task_ids or [])
    jobs = []
    for task in project.get("tasks", []):
        if wanted and str(task.get("task_id")) not in wanted:
            continue
        if should_render(task):
            jobs.append({"task": task, "steps": None})
    if not jobs:
        return 0
    key = f"{project_name}:batch"
    with _LOCK:
        if key in _QUEUED:
            return 0
        _QUEUED.add(key)
    _QUEUE.put({"project": project_name, "key": key, "tasks": jobs})
    _ensure_worker()
    return len(jobs)
