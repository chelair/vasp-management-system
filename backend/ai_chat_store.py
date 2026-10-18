"""AI 工作台私有存储；不写项目库。密钥密文与主密钥分开保存。"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from cryptography.fernet import Fernet, InvalidToken

from config import DATA_DIR
from dates import now_iso
from permissions import PermissionDenied

AI_DIR = DATA_DIR / "ai"
KEY_PATH = Path(os.environ.get("VASP_AI_KEY_FILE", str(Path.home() / ".config/vasp-manager/ai.key")))
_INIT_LOCK = threading.Lock()
_KEY_LOCK = threading.Lock()


def uid() -> str:
    return uuid.uuid4().hex


@contextmanager
def database():
    with _INIT_LOCK:
        AI_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        AI_DIR.chmod(0o700)
        db = sqlite3.connect(AI_DIR / "chat.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS connections (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                base_url TEXT NOT NULL, model TEXT NOT NULL, secret TEXT NOT NULL,
                max_tokens INTEGER NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, task_id TEXT,
                title TEXT NOT NULL, connection_id TEXT, prompt TEXT NOT NULL DEFAULT '',
                prompt_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL, request_id TEXT NOT NULL,
                status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL, connection_name TEXT NOT NULL,
                prompt_version INTEGER NOT NULL, snapshot TEXT NOT NULL,
                usage TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, finished_at TEXT,
                UNIQUE(owner, request_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(conversation_id)
                WHERE status IN ('queued', 'running');
            CREATE INDEX IF NOT EXISTS conversation_owner ON conversations(owner, updated_at);
            CREATE INDEX IF NOT EXISTS message_conversation ON messages(conversation_id, seq);
        """)
        # 已有连接原地升级，保留密文、会话关联和用户配置。
        columns = {row[1] for row in db.execute("PRAGMA table_info(connections)")}
        if "thinking_mode" not in columns:
            db.execute("ALTER TABLE connections ADD COLUMN thinking_mode TEXT NOT NULL DEFAULT 'default'")
        conversation_columns = {row[1] for row in db.execute("PRAGMA table_info(conversations)")}
        if "project_id" not in conversation_columns:
            db.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        if "workspace_enabled" not in conversation_columns:
            db.execute("ALTER TABLE conversations ADD COLUMN workspace_enabled INTEGER NOT NULL DEFAULT 0")
        run_columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
        if "tool_events" not in run_columns:
            db.execute("ALTER TABLE runs ADD COLUMN tool_events TEXT NOT NULL DEFAULT '[]'")
        for path in AI_DIR.glob("chat.sqlite3*"):
            path.chmod(0o600)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _cipher() -> Fernet:
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_EXCL 避免并发初始化覆盖已有主密钥；已有文件不可读时直接失败。
    try:
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(Fernet.generate_key())
    KEY_PATH.chmod(0o600)
    return Fernet(KEY_PATH.read_bytes().strip())


def encrypt(key: str) -> str:
    with _KEY_LOCK:
        return _cipher().encrypt(key.encode()).decode()


def decrypt(secret: str) -> str:
    try:
        with _KEY_LOCK:
            if not KEY_PATH.is_file():
                raise ValueError("主密钥文件缺失")
            return _cipher().decrypt(secret.encode()).decode()
    except (InvalidToken, OSError, ValueError):
        raise ValueError("模型密钥无法解密，请检查主密钥文件或重新配置连接") from None


def owned(db, table: str, item_id: str, owner: str) -> dict:
    assert table in ("connections", "conversations", "runs")
    row = db.execute(f"SELECT * FROM {table} WHERE id=? AND owner=?", (item_id, owner)).fetchone()
    if row is None:
        raise PermissionDenied("记录不存在或无权访问")
    return dict(row)


def public_connection(row) -> dict:
    return {**{k: row[k] for k in ("id", "name", "base_url", "model", "max_tokens", "thinking_mode", "created_at", "updated_at")},
            "is_default": bool(row["is_default"]), "key_configured": bool(row["secret"])}


def connections(owner: str) -> list:
    with database() as db:
        return [public_connection(r) for r in db.execute(
            "SELECT * FROM connections WHERE owner=? ORDER BY is_default DESC, created_at", (owner,))]


def save_connection(owner: str, values: dict, item_id: str | None = None) -> dict:
    with database() as db:
        old = owned(db, "connections", item_id, owner) if item_id else None
        if old and not values.get("api_key"):
            if values["base_url"] != old["base_url"]:
                raise ValueError("更换 API 地址时请重新输入密钥，避免将原密钥发送给其他服务")
            secret = old["secret"]
        else:
            if not values.get("api_key"):
                raise ValueError("请输入 API Key")
            secret = encrypt(values["api_key"])
        item_id = item_id or uid()
        default = bool(values.get("is_default")) or not db.execute(
            "SELECT 1 FROM connections WHERE owner=?", (owner,)).fetchone()
        if default:
            db.execute("UPDATE connections SET is_default=0 WHERE owner=?", (owner,))
        now = now_iso()
        db.execute("""INSERT INTO connections
            (id,owner,name,base_url,model,secret,max_tokens,is_default,created_at,updated_at,thinking_mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, base_url=excluded.base_url,
            model=excluded.model, secret=excluded.secret, max_tokens=excluded.max_tokens,
            is_default=excluded.is_default, updated_at=excluded.updated_at, thinking_mode=excluded.thinking_mode""",
            (item_id, owner, values["name"], values["base_url"], values["model"], secret,
             values["max_tokens"], int(default), old["created_at"] if old else now, now, values.get("thinking_mode", "default")))
        return public_connection(owned(db, "connections", item_id, owner))


def delete_connection(owner: str, item_id: str):
    with database() as db:
        owned(db, "connections", item_id, owner)
        if db.execute("SELECT 1 FROM runs WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone():
            raise ValueError("请先结束当前回答，再删除连接")
        db.execute("DELETE FROM connections WHERE id=?", (item_id,))
        db.execute("UPDATE conversations SET connection_id=NULL WHERE owner=? AND connection_id=?", (owner, item_id))
        if not db.execute("SELECT 1 FROM connections WHERE owner=? AND is_default=1", (owner,)).fetchone():
            db.execute("UPDATE connections SET is_default=1 WHERE id=(SELECT id FROM connections WHERE owner=? ORDER BY created_at LIMIT 1)", (owner,))


def create_conversation(owner: str, title: str, task_id: str | None, connection_id: str | None, project_id: str | None = None) -> dict:
    with database() as db:
        if connection_id:
            owned(db, "connections", connection_id, owner)
        else:
            row = db.execute("SELECT id FROM connections WHERE owner=? ORDER BY is_default DESC,created_at LIMIT 1", (owner,)).fetchone()
            connection_id = row[0] if row else None
        item_id, now = uid(), now_iso()
        db.execute("""INSERT INTO conversations
            (id,owner,task_id,title,connection_id,prompt,prompt_version,created_at,updated_at,project_id,workspace_enabled)
            VALUES (?,?,?,?,?,?,1,?,?,?,?)""",
                   (item_id, owner, task_id, title, connection_id, "", now, now, project_id, int(bool(project_id))))
        return owned(db, "conversations", item_id, owner)


def public_run(row, *, snapshot: bool = False) -> dict:
    out = {k: row[k] for k in ("id", "conversation_id", "message_id", "status", "model",
           "connection_name", "prompt_version", "error", "created_at", "finished_at")}
    out["usage"] = json.loads(row["usage"])
    out["tool_events"] = json.loads(row["tool_events"])
    if snapshot:
        out["snapshot"] = json.loads(row["snapshot"])
    return out


def append_tool_event(run_id: str, event: dict):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT tool_events FROM runs WHERE id=?", (run_id,)).fetchone()
        if row:
            events = json.loads(row[0])
            events = [e for e in events if e.get("id") != event["id"]]
            events.append(event)
            db.execute("UPDATE runs SET tool_events=? WHERE id=?", (json.dumps(events, ensure_ascii=False), run_id))


def detail(owner: str, item_id: str, before: int | None = None) -> dict:
    with database() as db:
        convo = owned(db, "conversations", item_id, owner)
        messages = list(db.execute("""SELECT * FROM messages WHERE conversation_id=? AND seq<?
            ORDER BY seq DESC LIMIT 80""", (item_id, before or 9223372036854775807)))
        convo["messages"] = [dict(r) for r in reversed(messages)]
        convo["has_more"] = bool(messages and db.execute(
            "SELECT 1 FROM messages WHERE conversation_id=? AND seq<?", (item_id, messages[-1]["seq"])).fetchone())
        ids = [m["id"] for m in messages]
        placeholders = ",".join("?" for _ in ids) or "NULL"
        convo["runs"] = [public_run(r) for r in db.execute(
            f"""SELECT * FROM runs WHERE conversation_id=? AND
                (message_id IN ({placeholders}) OR id IN
                 (SELECT id FROM runs WHERE conversation_id=? ORDER BY created_at DESC LIMIT 30))
                ORDER BY created_at DESC""", (item_id, *ids, item_id))]
        return convo


def update_answer(run_id: str, text: str, *, status: str = "running", error: str = "", usage: dict | None = None):
    with database() as db:
        run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run or run["status"] not in ("queued", "running"):
            return
        terminal = status not in ("queued", "running")
        db.execute("UPDATE messages SET content=?,status=? WHERE id=?", (text, status, run["message_id"]))
        db.execute("UPDATE runs SET status=?,error=?,usage=?,finished_at=? WHERE id=?",
                   (status, error, json.dumps(usage or {}), now_iso() if terminal else None, run_id))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), run["conversation_id"]))


def recover_runs():
    # 仅服务启动时调用，导入模块不触碰数据库；不自动重试可能已经计费的请求。
    with database() as db:
        rows = db.execute("SELECT id,message_id FROM runs WHERE status IN ('queued','running')").fetchall()
        for row in rows:
            tools_row = db.execute("SELECT tool_events FROM runs WHERE id=?", (row["id"],)).fetchone()
            events = json.loads(tools_row[0])
            for event in events:
                if event.get("status") == "running":
                    event["status"] = "interrupted"
                    event["result"] = {"error": "服务重启；文件操作结果需重新核对工作区，不能视为已完成"}
            db.execute("UPDATE runs SET tool_events=? WHERE id=?", (json.dumps(events, ensure_ascii=False), row["id"]))
            db.execute("UPDATE runs SET status='interrupted',error=?,finished_at=? WHERE id=?",
                       ("服务重启导致回答中断，可重新生成", now_iso(), row["id"]))
            db.execute("UPDATE messages SET status='interrupted' WHERE id=?", (row["message_id"],))
