"""受控动作及预算的单文件事务台账；不迁移项目库。

授权、动作与预留量在同一次原子替换中提交，避免跨文件预算半提交。
坏文件必须阻止执行，不能按空台账重建。锁复用 automation.store。
"""
import copy
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager

from automation import store
from config import DATA_DIR
from dates import now_iso

FILE = DATA_DIR / 'agent_execution.json'
UNRESOLVED = {'prepared', 'running', 'unknown', 'interrupted'}


def read():
    if not FILE.exists():
        return {'version': 1, 'enabled': False, 'grants': {}, 'actions': {}}
    doc = json.loads(FILE.read_text(encoding='utf-8'))
    if doc.get('version') != 1 or not isinstance(doc.get('grants'), dict) or not isinstance(doc.get('actions'), dict):
        raise ValueError('执行台账损坏或版本不兼容，已阻止自动执行')
    if 'opt_runs' in doc and not isinstance(doc['opt_runs'], dict):
        raise ValueError('OPT运行台账损坏，已阻止自动执行')
    return doc


def write(doc):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.agent_execution-', dir=FILE.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, FILE)
        fd_dir = os.open(FILE.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def transaction():
    with store._locked():
        doc = read()
        before = copy.deepcopy(doc)
        yield doc
        if doc != before:
            write(doc)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def new_id(prefix='act'):
    return prefix + '_' + uuid.uuid4().hex


def update(action_id, **fields):
    with transaction() as doc:
        item = doc['actions'][action_id]
        item.update(fields, updated_at=now_iso())
        item.setdefault('events', []).append({'at': now_iso(), 'status': item['status'], 'reason': item.get('reason', '')})
    return copy.deepcopy(item)


def get(action_id):
    with store._locked():
        return copy.deepcopy(read()['actions'].get(action_id))


def process_token(pid):
    try:
        from pathlib import Path
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def owner_alive(record):
    pid = record.get('owner_pid')
    token = record.get('owner_token')
    return bool(pid and token and process_token(pid) == token)
