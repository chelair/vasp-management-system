"""动作目录：四个动作的 preflight 与执行实现。

统一模式：preflight 检查 → 执行 → 写审计（审计由调度层统一写）。
执行**复用现有业务实现**（`routers.jobs.core_*`），不在自动化里重写业务逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storage import load_db
from task_paths import free_energy_frac_task, is_continuation_task


def _jobs():
    """延迟导入 jobs 路由模块（避免 import 期循环依赖）。"""
    from routers import jobs as jobs_router

    return jobs_router


def load_task(task_id: str) -> tuple:
    """按 task_id 重新读库拿 (project, task)（执行前重新读状态，不用旧快照）。"""
    db = load_db()
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if str(task.get("task_id")) == str(task_id):
                return project, task
    raise _jobs().ActionError(404, f"任务不存在：{task_id}")


def _guard_task(project: Dict[str, Any], task: Dict[str, Any], *, allow_archived: bool = False) -> None:
    if not allow_archived and str(task.get("status") or "") == "archived":
        raise _jobs().ActionError(400, "任务已关闭（归档），请先重新打开")


@dataclass
class ActionSpec:
    """动作元数据 + 两个实现。"""

    name: str
    label: str
    description: str
    long_running: bool = False
    requires_task: bool = True
    params_help: Dict[str, str] = field(default_factory=dict)

    def preflight(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def execute(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


# ------------------------------------------------------------------ 具体动作


class _Continuation(ActionSpec):
    def preflight(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        if is_continuation_task(task):
            raise _jobs().ActionError(400, "续算子任务不支持再续算，请对原始任务操作")
        if task.get("task_type") not in ("opt", "neb"):
            raise _jobs().ActionError(400, "仅结构优化（opt）与 NEB 任务支持同类型续算")
        return {
            "ok": True,
            "task_id": task_id,
            "project": project.get("name"),
            "task_type": task.get("task_type"),
            "status": task.get("status"),
            "will_do": "在远端最新目录旁创建 con(N+1)、搬运 WAVECAR 并登记隐藏续算子任务",
            "note": "执行时会重新读远端目录状态判断（running / input_incomplete 等不会真的创建）",
        }

    def execute(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        result = _jobs().core_continuation(project, task)
        return {"action": result.get("action"), **result}


class _Submit(ActionSpec):
    def preflight(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_submit(project, task, dry_run=True)

    def execute(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_submit(project, task)


class _FracCreate(ActionSpec):
    def preflight(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_create_frac(project, task, params, dry_run=True)

    def execute(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_create_frac(project, task, params)


def _neb_payload(project: Dict[str, Any], task: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """NEB 参数补全：没显式给初末态时，从同组任务里按 group_role 推导。"""
    payload = dict(params or {})
    if payload.get("initial_opt_task_id") and payload.get("final_opt_task_id"):
        return payload
    group_id = (task.get("group") or {}).get("group_id")
    members = [
        t
        for t in project.get("tasks", [])
        if group_id and (t.get("group") or {}).get("group_id") == group_id
    ]
    initial = next(
        (t for t in members if (t.get("group") or {}).get("group_role") == "initial_opt"), None
    )
    final = next(
        (t for t in members if (t.get("group") or {}).get("group_role") == "final_opt"), None
    )
    if initial is not None:
        payload.setdefault("initial_opt_task_id", initial.get("task_id"))
    if final is not None:
        payload.setdefault("final_opt_task_id", final.get("task_id"))
    return payload


class _NebCreate(ActionSpec):
    def preflight(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_create_neb(project, task, _neb_payload(project, task, params), dry_run=True)

    def execute(self, task_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        project, task = load_task(task_id)
        _guard_task(project, task)
        return _jobs().core_create_neb(project, task, _neb_payload(project, task, params))


ACTIONS: Dict[str, ActionSpec] = {
    "task.continuation": _Continuation(
        name="task.continuation",
        label="创建续算",
        description="为 opt / neb 任务在远端创建 conN 续算目录并登记隐藏子任务；"
        "只有返回 action=created 才算真的创建成功。",
    ),
    "task.submit": _Submit(
        name="task.submit",
        label="提交作业",
        description="输入文件非空检查通过后执行 bsub < vasp.lsf（NEB 额外检查各映像 POSCAR）。",
    ),
    "frac.create": _FracCreate(
        name="frac.create",
        label="创建频率矫正文件",
        description="从结构优化最新输出生成 frac 输入文件（CONTCAR→POSCAR / POTCAR / KPOINTS）。",
        long_running=True,
    ),
    "neb.create": _NebCreate(
        name="neb.create",
        label="创建 NEB 计算文件",
        description="初末态都收敛后用 nebmake.pl 生成 NEB 映像文件；参数缺省时按组内 role 推导。",
        long_running=True,
        params_help={
            "initial_opt_task_id": "初态 opt 任务（缺省按组内 group_role=initial_opt 推导）",
            "final_opt_task_id": "末态 opt 任务（缺省按组内 group_role=final_opt 推导）",
            "num_images": "映像数，默认 3",
        },
    ),
}


def get(name: str) -> ActionSpec:
    spec = ACTIONS.get(str(name))
    if spec is None:
        raise KeyError(f"未知动作：{name}（可用：{', '.join(ACTIONS)}）")
    return spec


def catalog() -> List[Dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "label": spec.label,
            "description": spec.description,
            "long_running": spec.long_running,
            "requires_task": spec.requires_task,
            "params_help": spec.params_help,
        }
        for spec in ACTIONS.values()
    ]
