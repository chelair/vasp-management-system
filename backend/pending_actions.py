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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from dates import now_iso

STORE = DATA_DIR / "pending_actions.json"
LOCK = threading.Lock()

STATUSES = ("pending", "executing", "approved", "rejected", "failed", "unknown")


@contextmanager
def _locked():
    from automation import store
    with store._locked(), LOCK:
        yield



def _load() -> Dict[str, Any]:
    if not STORE.is_file():
        return {"version": 1, "items": []}
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ValueError("待确认队列损坏，已停止执行")
    return doc


def _save(doc: Dict[str, Any]) -> None:
    from automation.store import _write_json
    _write_json(STORE, doc)


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
    with _locked():
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
        from automation.ledger import fingerprint
        item['proposal_fingerprint'] = fingerprint([name, params, requested_by, requested_kind, task_id])
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
    with _locked():
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
    """批准时重新鉴权并先认领；所有执行进入同一授权/预算网关。"""
    import auth
    import permissions
    from automation import actions, gateway, ledger

    user = auth.find_user(decided_by)
    if not user or not user.get('enabled') or user.get('role') == 'agent':
        raise permissions.PermissionDenied('需要有效人工身份批准')
    with _locked():
        doc = _load()
        pending = next((i for i in doc['items'] if i['id'] == item_id), None)
        if pending is None:
            raise LookupError('待确认动作不存在')
        if pending['status'] != 'pending':
            raise ValueError('该提案已被处理或正在执行，不能重复批准')
        params = dict(pending.get('payload') or {})
        project, task = actions.load_task(str(params.get('task_id') or ''))
        permissions.ensure_project_owner(project, user)
        expected = ledger.fingerprint([pending['action'], params, pending['requested_by'], pending['requested_kind'], task['task_id']])
        if pending.get('proposal_fingerprint') != expected:
            raise ValueError('提案参数已变化或旧提案无参数指纹，请重新创建提案')
        if pending['requested_kind'] == 'agent':
            requester = auth.find_user(pending['requested_by'])
            if not requester or not requester.get('enabled'):
                raise permissions.PermissionDenied('提案者已失效')
            permissions.ensure_project_owner(project, requester)
            grant = ledger.read()['grants'].get(str(params.get('grant_id') or ''))
            if not grant or grant['agent_username'] != permissions.username_of(requester):
                raise permissions.PermissionDenied('提案者与授权不一致')
        # 先持久化认领；重启后不会从pending再次执行。
        pending.update(status='executing', decided_by=decided_by, decided_at=now_iso(), decision_note=note)
        _save(doc)
    try:
        record = gateway.execute(user=user, session=None, grant_id=str(params.get('grant_id') or ''),
                                 action=pending['action'], task_id=task['task_id'],
                                 params={k: v for k, v in params.items() if k not in {'grant_id', 'follow_up'}},
                                 follow_up=params.get('follow_up'), idempotency_key='approval:' + item_id,
                                 trigger='approval', trigger_id=item_id)
        status = 'approved' if record['status'] in {'succeeded', 'skipped'} else 'pending' if record['status'] == 'dry_run' else 'unknown'
        error = None
    except Exception as exc:
        matches = [a for a in ledger.read()['actions'].values() if a.get('trigger') == 'approval' and a.get('trigger_id') == item_id]
        record = matches[-1] if matches else None
        status = 'unknown' if record and record['status'] in {'unknown', 'running', 'interrupted'} else 'failed'
        error = str(exc)
    with _locked():
        doc = _load()
        item = next(i for i in doc['items'] if i['id'] == item_id)
        item.update(status=status, result=record, error=error)
        _save(doc)
        return dict(item)
