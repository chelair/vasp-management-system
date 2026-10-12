"""待确认队列（2026-10-13）：AI 触发的 confirm 级动作**不直接执行**，先入库等人批准。

- `POST /api/pending-actions`（AI 侧，token scope 需 `propose`）→ 入库，状态 `pending`；
- `GET  /api/pending-actions`（人工侧查看）；
- `POST /api/pending-actions/{id}/approve` → **人工**批准后才真正执行（复用 `automation.actions` 的
  preflight + execute，与自动化调度走同一套业务实现）；
- `POST /api/pending-actions/{id}/reject` → 驳回；
- **agent 账号不能批准/驳回自己提的动作**（避免 AI 自审自批）。

落盘：`data/pending_actions.json`（原子写 + 进程内锁，与其它 store 一致）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from dates import now_iso

STORE = DATA_DIR / "pending_actions.json"
LOCK = threading.Lock()

STATUSES = ("pending", "approved", "rejected", "failed")


def _load() -> Dict[str, Any]:
    if not STORE.is_file():
        return {"version": 1, "items": []}
    try:
        doc = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏了当空
        return {"version": 1, "items": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        return {"version": 1, "items": []}
    return doc


def _save(doc: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(STORE.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STORE)


def _next_id(items: List[Dict[str, Any]]) -> str:
    seq = len(items) + 1
    existing = {str(i.get("id") or "") for i in items}
    while f"pa_{seq:05d}" in existing:
        seq += 1
    return f"pa_{seq:05d}"


def _task_of_payload(payload: Dict[str, Any]) -> str:
    return str((payload or {}).get("task_id") or "").strip()


def create(
    *,
    action: str,
    payload: Dict[str, Any],
    reason: str,
    requested_by: str,
    requested_kind: str,
    project_name: str = "",
    task_name: str = "",
) -> Dict[str, Any]:
    """把 AI 的动作提案入库（不执行）。"""
    from automation import actions as action_catalog

    name = str(action or "").strip()
    try:
        spec = action_catalog.get(name)
    except KeyError as e:
        raise ValueError(str(e))
    params = dict(payload or {})
    task_id = _task_of_payload(params)
    if spec.requires_task and not task_id:
        raise ValueError(f"动作 {name} 需要 payload.task_id")
    with LOCK:
        doc = _load()
        item = {
            "id": _next_id(doc["items"]),
            "created_at": now_iso(),
            "status": "pending",
            "action": name,
            "action_label": spec.label,
            "payload": params,
            "reason": str(reason or "").strip(),
            "requested_by": requested_by or "-",
            "requested_kind": requested_kind,
            "project_name": project_name,
            "task_id": task_id,
            "task_name": task_name,
            "decided_at": None,
            "decided_by": None,
            "decision_note": "",
            "result": None,
            "error": None,
        }
        doc["items"].append(item)
        _save(doc)
    return item


def list_items(
    status: Optional[str] = None, project_name: Optional[str] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    """列出待确认动作（新 → 旧）。"""
    doc = _load()
    items = list(reversed(doc.get("items") or []))
    if status:
        wanted = {s.strip() for s in str(status).split(",") if s.strip()}
        items = [i for i in items if str(i.get("status")) in wanted]
    if project_name:
        items = [i for i in items if str(i.get("project_name")) == project_name]
    return items[: max(1, limit)]


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    for item in _load().get("items") or []:
        if str(item.get("id")) == str(item_id):
            return item
    return None


def _decide(item_id: str, *, status: str, decided_by: str, note: str = "") -> Optional[Dict[str, Any]]:
    with LOCK:
        doc = _load()
        for item in doc["items"]:
            if str(item.get("id")) != str(item_id):
                continue
            if str(item.get("status")) != "pending":
                raise ValueError(f"该动作已是 {item.get('status')}，不能重复处理")
            item["status"] = status
            item["decided_at"] = now_iso()
            item["decided_by"] = decided_by or "-"
            item["decision_note"] = note
            _save(doc)
            return dict(item)
    return None


def reject(item_id: str, *, decided_by: str, note: str = "") -> Dict[str, Any]:
    item = _decide(item_id, status="rejected", decided_by=decided_by, note=note)
    if item is None:
        raise LookupError(f"待确认动作不存在：{item_id}")
    return item


def approve(item_id: str, *, decided_by: str, note: str = "") -> Dict[str, Any]:
    """人工批准 → 复用自动化动作实现真正执行；失败标 `failed` 并保留错误。"""
    from automation import actions as action_catalog

    pending = get_item(item_id)
    if pending is None:
        raise LookupError(f"待确认动作不存在：{item_id}")
    if str(pending.get("status")) != "pending":
        raise ValueError(f"该动作已是 {pending.get('status')}，不能重复处理")

    params = dict(pending.get("payload") or {})
    task_id = str(params.get("task_id") or "")
    result: Dict[str, Any] = {}
    error = None
    try:
        spec = action_catalog.get(str(pending.get("action")))
        spec.preflight(task_id, params)
        result = spec.execute(task_id, params)
    except Exception as e:  # noqa: BLE001 - 执行失败要留痕，不能吞
        error = f"{type(e).__name__}: {e}"

    decided = _decide(
        item_id, status="failed" if error else "approved", decided_by=decided_by, note=note
    )
    if decided is None:
        raise LookupError(f"待确认动作不存在：{item_id}")
    with LOCK:
        doc = _load()
        for item in doc["items"]:
            if str(item.get("id")) == str(item_id):
                item["result"] = result or None
                item["error"] = error
                _save(doc)
                return dict(item)
    return decided
