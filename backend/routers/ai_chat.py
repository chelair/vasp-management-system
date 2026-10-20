"""AI 工作台：账号私有的连接、会话、任务快照和流式回答。"""
from __future__ import annotations

import asyncio
from functools import wraps
import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import ai_chat_service as service
import ai_chat_store as store
import ai_workspace as workspace
from dates import now_iso
from envelope import fail, ok
import permissions
from storage import load_db
from task_paths import is_auxiliary_task, is_continuation_task


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/ai/chat", tags=["ai-chat"], dependencies=[Depends(private_response)])


def actor(request: Request) -> tuple[dict, str]:
    user = getattr(request.state, "user", None) or {}
    if not user.get("user_id") or user.get("role") == "agent":
        raise permissions.PermissionDenied("AI 工作台仅供已登录的用户使用")
    return user, str(user["user_id"])


def guard(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except permissions.PermissionDenied:
            raise
        except ValueError as exc:
            return JSONResponse(status_code=400, content=fail(service.clean(str(exc))), headers={"Cache-Control": "no-store"})
        except (OSError, sqlite3.Error):
            return JSONResponse(status_code=503, content=fail("AI 私有存储暂不可用，请检查磁盘权限或稍后重试"), headers={"Cache-Control": "no-store"})
        except Exception:
            return JSONResponse(status_code=500, content=fail("AI 请求未完成，请稍后重试"), headers={"Cache-Control": "no-store"})
    return wrapped


class ConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=512)
    max_tokens: int = Field(default=2048, ge=128, le=32768)
    is_default: bool = False
    thinking_mode: Literal["default", "enabled", "disabled"] = "default"
    reasoning_api: Literal["auto","openai","deepseek"] = "auto"
    reasoning_effort: Literal["default","none","minimal","low","medium","high","xhigh","max"] = "default"


class ConversationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新会话", min_length=1, max_length=120)
    task_id: str | None = Field(default=None, max_length=160)
    project_id: str | None = Field(default=None, max_length=160)
    connection_id: str | None = Field(default=None, max_length=64)


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    connection_id: str | None = Field(default=None, max_length=64)
    prompt: str = Field(default="", max_length=8000)
    workspace_enabled: bool | None = None


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=16000)
    retry: bool = False
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/connections")
@guard
def list_connections(request: Request):
    _, owner = actor(request)
    return ok("查询成功", {"items": store.connections(owner)})


def connection_values(body: ConnectionBody):
    values = body.model_dump()
    for field in ("reasoning_api","reasoning_effort"):
        if field not in body.model_fields_set:values.pop(field,None)
    values["base_url"] = service.normalize_url(body.base_url)
    for key in ("name", "model"):
        values[key] = values[key].strip()
        if not values[key] or any(ord(c) < 32 for c in values[key]):
            raise ValueError("连接名称与模型名称不能为空或包含控制字符")
    if values["api_key"] is not None:
        values["api_key"] = values["api_key"].strip()
        if any(ord(c) < 33 or ord(c) > 126 for c in values["api_key"]):
            raise ValueError("API Key 格式不合法")
    return values


@router.get("/reasoning-capabilities")
@guard
def reasoning_capabilities(request:Request,base_url:str='',model:str='',reasoning_api:Literal['auto','openai','deepseek']='auto'):
    actor(request)
    if len(base_url)>2000 or len(model)>200:raise ValueError('接口地址或模型名过长')
    import ai_reasoning
    return ok('本地能力定义',ai_reasoning.capabilities({'base_url':base_url,'model':model,'reasoning_api':reasoning_api}))


@router.post("/connections")
@guard
def create_connection(request: Request, body: ConnectionBody):
    _, owner = actor(request)
    secure_key_transport(request)
    return ok("连接已保存", store.save_connection(owner, connection_values(body)))


@router.put("/connections/{item_id}")
@guard
def update_connection(item_id: str, request: Request, body: ConnectionBody):
    _, owner = actor(request)
    if body.api_key:
        secure_key_transport(request)
    return ok("连接已更新", store.save_connection(owner, connection_values(body), item_id))


def secure_key_transport(request: Request):
    if request.url.scheme != "https" and (not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient")):
        raise ValueError("请通过 HTTPS 或本机端口转发配置密钥")


@router.delete("/connections/{item_id}")
@guard
def delete_connection(item_id: str, request: Request):
    _, owner = actor(request)
    store.delete_connection(owner, item_id)
    return ok("连接已删除", {})


@router.post("/connections/{item_id}/test")
@guard
def test_connection(item_id: str, request: Request):
    _, owner = actor(request)
    return ok("测试完成", service.test_connection(owner, item_id))


@router.get("/targets")
@guard
def targets(request: Request):
    user, _ = actor(request)
    items = []
    for project in permissions.visible_projects(load_db(), user):
        tasks = [{"id": t["task_id"], "name": t.get("model_name") or t["task_id"],
                  "type": t.get("task_type"), "status": t.get("status"), "group": (t.get("group") or {}).get("group_name") or ""}
                 for t in project.get("tasks", []) if not is_auxiliary_task(t) and not is_continuation_task(t)]
        items.append({"id": project["project_id"], "name": project["name"], "closed": bool(project.get("closed")), "tasks": tasks})
    return ok("查询成功", {"items": items})


@router.get("/conversations")
@guard
def list_conversations(request: Request):
    user, owner = actor(request)
    projects = permissions.visible_projects(load_db(), user)
    visible_projects = {p["project_id"] for p in projects}
    visible_tasks = {t["task_id"]: p["project_id"] for p in projects for t in p.get("tasks", [])}
    with store.database() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM conversations WHERE owner=? ORDER BY updated_at DESC", (owner,))]
    items = []
    for row in rows:
        project_id = row.get("project_id") or visible_tasks.get(row["task_id"])
        if (project_id and project_id in visible_projects) or (not row["task_id"] and not row.get("project_id")):
            items.append({**row, "project_id": project_id})
    return ok("查询成功", {"items": items})


@router.post("/conversations")
@guard
def create_conversation(request: Request, body: ConversationBody):
    user, owner = actor(request)
    project_id = body.project_id
    if project_id:
        service.project_for(user, project_id)
    if body.task_id:
        project, _ = service.task_pair(user, body.task_id)
        if project_id and project_id != project["project_id"]:
            raise ValueError("任务不属于所选项目")
        project_id = project["project_id"]
    title = service.clean(body.title.strip())
    if not title:
        raise ValueError("请输入会话名称")
    return ok("会话已创建", store.create_conversation(owner, title, body.task_id, body.connection_id, project_id))


def conversation_for(request, item_id):
    user, owner = actor(request)
    with store.database() as db:
        row = store.owned(db, "conversations", item_id, owner)
    service.ensure_conversation(user, row)
    return user, owner, row


@router.get("/conversations/{item_id}")
@guard
def get_conversation(item_id: str, request: Request, before: int | None = Query(default=None, ge=1)):
    _, owner, row = conversation_for(request, item_id)
    return ok("查询成功", {**store.detail(owner, item_id, before), "project_id": row.get("project_id")})


@router.put("/conversations/{item_id}")
@guard
def update_conversation(item_id: str, request: Request, body: ConversationUpdate):
    _, owner, row = conversation_for(request, item_id)
    with store.database() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')", (item_id,)).fetchone():
            raise ValueError("请先结束当前回答，再修改会话设置")
        if body.connection_id:
            connection = store.owned(db, "connections", body.connection_id, owner)
            key = store.decrypt(connection["secret"])
        else:
            key = ""
        prompt, title = service.clean(body.prompt, (key,)), service.clean(body.title.strip(), (key,))
        if not title:
            raise ValueError("请输入会话名称")
        enabled = bool(row["workspace_enabled"]) if body.workspace_enabled is None else body.workspace_enabled
        if enabled and not row.get("project_id"):
            raise ValueError("请先创建项目会话，再启用工作区")
        db.execute("UPDATE conversations SET title=?,connection_id=?,prompt=?,prompt_version=?,workspace_enabled=?,updated_at=? WHERE id=?",
                   (title, body.connection_id, prompt, row["prompt_version"] + int(prompt != row["prompt"]), int(enabled), now_iso(), item_id))
    return ok("会话设置已保存", store.detail(owner, item_id))


@router.delete("/conversations/{item_id}")
@guard
def delete_conversation(item_id: str, request: Request):
    user, _, conversation = conversation_for(request, item_id)
    project = service.project_for(user, conversation["project_id"]) if conversation.get("project_id") else None
    with store.database() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')", (item_id,)).fetchone():
            raise ValueError("请先停止生成，再删除会话")
        db.execute("DELETE FROM conversations WHERE id=?", (item_id,))
    if project:
        workspace.remove_work(project, conversation)
    return ok("会话已删除", {})


@router.get("/conversations/{item_id}/context")
@guard
def conversation_context(item_id: str, request: Request):
    user, _, row = conversation_for(request, item_id)
    return ok("本地上下文已刷新", service.context_for(user, row["task_id"], project_id=row.get("project_id")))


@router.get("/conversations/{item_id}/workspace")
@guard
def conversation_workspace(item_id: str, request: Request):
    user, _, row = conversation_for(request, item_id)
    if not row.get("project_id"):
        raise ValueError("通用会话没有项目工作区")
    project = service.project_for(user, row["project_id"])
    return ok("目录地图已生成", {**workspace.directory_map(project), "task_locations": workspace.task_locations(project),
                               "enabled": bool(row["workspace_enabled"])})


@router.get("/conversations/{item_id}/workspace/files")
@guard
def workspace_files(item_id: str, request: Request, path: str = Query(default="", max_length=512),
                    offset: int = Query(default=0, ge=0)):
    user, _, row = conversation_for(request, item_id)
    if not row.get("project_id"):
        raise ValueError("通用会话没有项目工作区")
    project = service.project_for(user, row["project_id"])
    context = service.context_for(user, project_id=row["project_id"])
    return ok("查询成功", service.clean(workspace.listing(project, row, context, path, offset)))


@router.get("/conversations/{item_id}/workspace/file")
@guard
def workspace_file(item_id: str, request: Request, path: str = Query(max_length=512),
                   offset: int = Query(default=0, ge=0), tail: bool = False):
    user, _, row = conversation_for(request, item_id)
    if not row.get("project_id"):
        raise ValueError("通用会话没有项目工作区")
    project = service.project_for(user, row["project_id"])
    context = service.context_for(user, project_id=row["project_id"])
    return ok("读取成功", workspace.reading(project, row, context, path, offset, tail))


@router.post("/conversations/{item_id}/messages")
@guard
def send_message(item_id: str, request: Request, body: MessageBody):
    user, owner = actor(request)
    run, _ = service.start_run(user, owner, item_id, body.content, body.retry, body.request_id)
    return ok("回答已开始", run)


def run_for(request, run_id):
    user, owner = actor(request)
    with store.database() as db:
        row = store.owned(db, "runs", run_id, owner)
        conversation = store.owned(db, "conversations", row["conversation_id"], owner)
    service.ensure_conversation(user, conversation)
    return user, owner, row


@router.get("/runs/{run_id}")
@guard
def get_run(run_id: str, request: Request):
    _, _, row = run_for(request, run_id)
    return ok("查询成功", store.public_run(row, snapshot=True))


@router.post("/runs/{run_id}/cancel")
@guard
def cancel_run(run_id: str, request: Request):
    run_for(request, run_id)
    with store.database() as db:
        db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        row = db.execute("SELECT content FROM messages WHERE id=(SELECT message_id FROM runs WHERE id=?)", (run_id,)).fetchone()
    store.update_answer(run_id, row[0] if row else "", status="cancelled")
    service.cancel_stream(run_id)
    return ok("已停止接收回答", {})


@router.get("/runs/{run_id}/events")
@guard
def stream_run(run_id: str, request: Request):
    user, owner, _ = run_for(request, run_id)

    async def events():
        previous = ""
        while not await request.is_disconnected():
            try:
                with store.database() as db:
                    row = store.owned(db, "runs", run_id, owner)
                    conversation = store.owned(db, "conversations", row["conversation_id"], owner)
                    message = db.execute("SELECT * FROM messages WHERE id=?", (row["message_id"],)).fetchone()
                service.ensure_conversation(user, conversation)
                event = json.dumps({"run": store.public_run(row), "message": dict(message)}, ensure_ascii=False)
                if event != previous:
                    yield "data: " + event + "\n\n"
                    previous = event
                else:
                    yield ": heartbeat\n\n"
                if row["status"] not in ("queued", "running"):
                    break
            except Exception:
                yield 'data: {"error":"会话权限已变化或记录不可用，请重新加载"}\n\n'
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
