"""Fixed, bounded companion-file probe; also runs standalone on the remote host.

Never returns POTCAR data, coordinates or arbitrary file contents to the model.
"""
import hashlib
import json
import os
import re
import stat
import sys


def open_directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in os.path.abspath(path).split('/')[1:]:
            if not part:
                continue
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(directory_fd, name):
    limits = {'POSCAR':1048576, 'CONTCAR':1048576, 'INCAR':65536, 'KPOINTS':65536, 'POTCAR':33554432, 'OUTCAR':None}
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        limit = limits[name]
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or (limit and before.st_size > limit):
            raise ValueError('not a nonempty regular file within the size limit')
        if name == 'OUTCAR':
            raw = stream.read(98304)
            basis = 'head_98304_bytes'
        else:
            raw = stream.read(limit + 1)
            basis = 'full_file'
        after = os.fstat(stream.fileno())
    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    identity = lambda s:(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(after) or identity(before) != identity(current):
        raise ValueError('file changed during read')
    if limit and len(raw) != before.st_size:
        raise ValueError('incomplete read')
    meta = {'bytes':before.st_size, 'mtime_ns':before.st_mtime_ns,
            'sha256':hashlib.sha256(raw).hexdigest(), 'hash_basis':basis}
    if name == 'OUTCAR':
        meta['sample_range_bytes'] = [0,len(raw)]
    return raw.decode('utf-8', errors='replace'), meta


def titles(text, pattern):
    return [value[:160] for value in re.findall(pattern, text, re.M)[:64]]


def probe(folder, filename, expected_sha256, *companions):
    fd = open_directory(folder)
    try:
        _, original = read_file(fd, filename)
        if original['sha256'] != expected_sha256:
            raise ValueError('structure changed before companion read')
        result = {}
        for name in companions or ('INCAR', 'KPOINTS', 'POTCAR', 'OUTCAR'):
            try:
                text, meta = read_file(fd, name)
                row = {'status':'AVAILABLE', 'source':meta}
                if name == 'INCAR':
                    # Return only numeric/control settings, never arbitrary input text.
                    keys = {'ENCUT','EDIFF','EDIFFG','IBRION','ISIF','NSW','POTIM','NELM','ISPIN',
                            'MAGMOM','LDAU','LDAUL','LDAUU','LDAUJ','LSORBIT','PREC','ALGO','LREAL',
                            'GGA','IVDW','LDIPOL','IDIPOL','DIPOL','EFIELD','EFIELD_PEAD',
                            'LDAUTYPE','ISMEAR','SIGMA','NELECT','NUPDOWN'}
                    values = {}
                    for line in text.splitlines():
                        for item in re.split(';', re.split('[!#]', line)[0]):
                            pair = item.split('=', 1)
                            if len(pair) == 2 and pair[0].strip().upper() in keys:
                                values[pair[0].strip().upper()] = pair[1].strip()[:512]
                    row['settings'] = values
                elif name == 'KPOINTS':
                    lines = text.splitlines()
                    if len(lines) >= 4 and lines[1].strip() == '0' and lines[2].strip().lower().startswith(('g','m')):
                        grid = [int(x) for x in lines[3].split()]
                        shift = [float(x) for x in lines[4].split()] if len(lines) > 4 else [0.,0.,0.]
                        if len(grid) == len(shift) == 3 and all(0 < x <= 10000 for x in grid) and all(abs(x) <= 1 for x in shift):
                            row['grid'] = {'mesh':grid,'scheme':'Gamma' if lines[2].strip().lower().startswith('g') else 'Monkhorst-Pack','shift':shift}
                    if 'grid' not in row:
                        row.update(status='UNKNOWN', reason='不是可直接比较的自动规则网格，不猜测k点一致')
                elif name == 'POTCAR':
                    row['titles'] = titles(text, r'^\s*TITEL\s*=\s*([^\r\n]+)')
                    row['zval'] = titles(text, r'ZVAL\s*=\s*([0-9.]+)')
                else:
                    # Runtime chemistry comes from the header, not the current INCAR/POTCAR.
                    header = text[:98304]
                    row['potential_titles'] = titles(header, r'^\s*POTCAR:\s*([^\r\n]+)')
                    if not row['potential_titles']:
                        row['potential_titles'] = titles(header, r'^\s*TITEL\s*=\s*([^\r\n]+)')
                    match = re.search(r'ions per type\s*=\s*([0-9 \t]+)', header)
                    row['ions_per_type'] = [int(x) for x in match[1].split()[:64]] if match else None
                    match = re.search(r'NELECT\s*=\s*([0-9.]+)', header)
                    row['nelect'] = float(match[1]) if match else None
                    row['scope'] = 'OUTCAR header only; no assertion of final electronic/ionic convergence'
                result[name] = row
            except (OSError, ValueError) as exc:
                result[name] = {'status':'UNKNOWN', 'reason':str(exc)[:160]}
        _, final = read_file(fd, filename)
        if final != original:
            raise ValueError('structure changed during companion read')
        return result
    finally:
        os.close(fd)


if __name__ == '__main__':
    print(json.dumps(probe(*sys.argv[1:])))
