"""Seven-file, read-only synchronization checks. Remote access is explicit only."""
import hashlib
import inspect
import json
import shlex
import time
from pathlib import Path

import ssh
from paths import resolve_remote_path
from task_paths import task_files_dir

NAMES = ('INCAR', 'KPOINTS', 'POSCAR', 'POTCAR', 'CONTCAR', 'OUTCAR', 'OSZICAR')
FULL_LIMIT = 1024 * 1024
SAMPLE_BYTES = 65536
MAX_IMAGES = 64


def scan_files(root, neb=False):
    root = Path(root)
    images_root = root / 'neb_images' if (root / 'neb_images').is_dir() else root
    if root.is_symlink() or images_root.is_symlink():
        raise ValueError('文件目录不可为符号链接')
    images = sorted((p for p in images_root.iterdir() if p.name.isdigit() and p.is_dir()),
                    key=lambda p: int(p.name)) if neb and images_root.is_dir() else []
    result = {'files': {}, 'directory': str(root), 'truncated': len(images) > MAX_IMAGES}
    for name in NAMES:
        paths = [(name, root / name)] if (root / name).exists() else [
            (p.name + '/' + name, p / name) for p in images[:MAX_IMAGES] if (p / name).exists()]
        item = {'paths': {}, 'size': 0, 'error': None}
        for relative, path in paths:
            try:
                if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                    raise ValueError('文件路径不可读取')
                before = path.stat()
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    if before.st_size <= FULL_LIMIT:
                        digest.update(stream.read(FULL_LIMIT + 1))
                        basis = 'full'
                    else:
                        digest.update(stream.read(SAMPLE_BYTES))
                        stream.seek(max(0, before.st_size - SAMPLE_BYTES))
                        digest.update(stream.read(SAMPLE_BYTES))
                        basis = 'head_tail'
                after = path.stat()
                item['paths'][relative] = {
                    'size': before.st_size, 'hash': digest.hexdigest(), 'basis': basis,
                    'stable': (before.st_ino, before.st_size, before.st_mtime_ns) ==
                              (after.st_ino, after.st_size, after.st_mtime_ns)}
                item['size'] += before.st_size
            except (OSError, ValueError) as exc:
                item['error'] = str(exc)[:200]
        result['files'][name] = item
    return result


def compare_file(local, remote, output=False):
    if local.get('error') or remote.get('error'):
        return 'unknown'
    left, right = local['paths'], remote['paths']
    if any(p['size'] == 0 for p in list(left.values()) + list(right.values())):
        return 'empty'
    if not left and not right:
        return 'missing'
    if not left:
        return 'download'
    if not right:
        return 'local_only' if output else 'upload'
    if any(not p['stable'] for p in list(left.values()) + list(right.values())):
        return 'changing'
    if set(left) != set(right):
        return 'different'
    if any(left[k]['size'] != right[k]['size'] or left[k]['hash'] != right[k]['hash'] for k in left):
        return 'different'
    return 'sampled' if any(p['basis'] != 'full' for p in left.values()) else 'synced'


def file_status(project, task, verify_remote=False):
    local = scan_files(task_files_dir(project['name'], task), task.get('task_type') == 'neb')
    remote, error = None, None
    if verify_remote:
        try:
            directory = resolve_remote_path(project['server'], task['remote_dir']).rstrip('/')
            # Same rule as input upload: the greatest conN is the current work directory.
            source = ("import hashlib,json,sys\nfrom pathlib import Path\n"
                      + 'NAMES=' + repr(NAMES) + '\n'
                      + f'FULL_LIMIT={FULL_LIMIT}\nSAMPLE_BYTES={SAMPLE_BYTES}\nMAX_IMAGES={MAX_IMAGES}\n'
                      + inspect.getsource(scan_files)
                      + "\nroot=Path(sys.argv[1])\n"
                      + "cons=sorted((p for p in root.glob('con*') if p.is_dir() and p.name[3:].isdigit()),key=lambda p:int(p.name[3:]))\n"
                      + "root=cons[-1] if cons else root\n"
                      + "if not root.is_dir() or root.is_symlink(): raise ValueError('远端计算目录不存在或不可读取')\n"
                      + "print(json.dumps(scan_files(root,sys.argv[2]=='1')))\n")
            command = ('python3 - ' + shlex.quote(directory) +
                       (' 1' if task.get('task_type') == 'neb' else ' 0') +
                       " <<'VASP_FILE_CHECK'\n" + source + 'VASP_FILE_CHECK')
            response = ssh.run_remote(project['server'], command, timeout=45)
            if response.get('exit_code') != 0:
                raise ValueError('远端核对失败，请检查连接或目录权限')
            remote = json.loads(response['stdout'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error = str(exc)[:200]
        except Exception:
            error = '远端核对失败，请稍后重试'
    files = []
    for name in NAMES:
        left = local['files'][name]
        right = remote['files'][name] if remote else None
        if right is not None:
            status = 'unknown' if local['truncated'] or remote['truncated'] else compare_file(
                left, right, name in ('CONTCAR', 'OUTCAR', 'OSZICAR'))
        elif left['error'] or error:
            status = 'unknown'
        elif not left['paths']:
            status = 'local_missing'
        elif any(p['size'] == 0 for p in left['paths'].values()):
            status = 'empty'
        else:
            status = 'local'
        files.append({'name': name, 'status': status, 'local_size': left['size'],
                      'local_count': len(left['paths']), 'remote_size': right['size'] if right else None,
                      'remote_count': len(right['paths']) if right else None})
    return {'task_id': task['task_id'], 'files': files, 'checked_at': time.time(),
            'remote_checked': remote is not None, 'remote_dir': remote['directory'] if remote else None,
            'error': error}
