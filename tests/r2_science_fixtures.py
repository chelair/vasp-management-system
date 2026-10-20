"""Small, synthetic local scientific results. Never calls a model or HPC."""
import json
import struct
import zlib
from pathlib import Path

POSCAR = "H fixture\n1\n4 0 0\n0 4 0\n0 0 4\nH\n1\nDirect\n0.25 0.25 0.25\n"
def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))

PNG = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>2I5B', 16, 16, 8, 2, 0, 0, 0))
       + _chunk(b'IDAT', zlib.compress(b''.join(b'\0'+b''.join(bytes((i*16,j*16,100)) for i in range(16)) for j in range(16))))
       + _chunk(b'IEND', b''))


def seed_science(data, project):
    from task_paths import task_dir, task_files_dir
    import bader
    import pdos
    import work_function
    import charge_diff
    task = {"task_id": "t_ele", "model_name": "Electronic", "task_type": "ele", "subtype": "pdos", "status": "completed",
            "dir_path": project["name"] + "/ele/Electronic", "remote_dir": project["name"] + "/ele/Electronic"}
    project["tasks"].append(task)
    name = project["name"]
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    write(task_dir(name, task) / "files" / "POSCAR", POSCAR)
    write(pdos.data_path(name, task), json.dumps({"metadata": {"energy_grid": [-2, -1, 0, 1, 2], "efermi": 0}, "total_dos": {"total": [0, 1, 3, 1, 0]}}))
    write(work_function.data_path(name, task), "0 5\n1 4\n2 5\n3 6\n")
    write(work_function.meta_path(name, task), json.dumps({"result": {"efermi": 1, "vacuum_level": 6, "work_function": 5, "axis": "c", "points": 4}}))
    write(bader.acf_path(name, task), " # X Y Z CHARGE MIN DIST ATOMIC VOL\n----------------\n 1 1 1 1 0.8 1.0 3.0\n----------------\n VACUUM CHARGE: 0.0\n VACUUM VOLUME: 0.0\n NUMBER OF ELECTRONS: 0.8\n")
    write(bader.meta_path(name, task), json.dumps({"zval": {"H": 1}, "charge_header": {"elements": ["H"], "counts": [1]}}))
    # Frozen CIF can be absent; never silently substitute current mirror.
    for path in charge_diff.image_paths(name, task).values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
    first = project["tasks"][0]
    write(task_files_dir(name, first) / "POSCAR", POSCAR)
    return task
