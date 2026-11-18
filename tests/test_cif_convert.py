"""CIF caches belong to each task, including flat difference-charge blocks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import cif_convert


def poscar(element):
    return f"{element}\n1\n10 0 0\n0 10 0\n0 0 10\n{element}\n1\nDirect\n0.1 0.2 0.3\n"


class CifConvertTests(unittest.TestCase):
    def test_flat_blocks_ignore_shared_legacy_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / 'reports/structure/POSCAR.cif'
            legacy.parent.mkdir(parents=True)
            legacy.write_text('corrupt shared cache')
            tasks = []
            for index, element in enumerate(('C', 'Ru'), 1):
                folder = root / str(index)
                folder.mkdir()
                (folder / 'POSCAR').write_text(poscar(element))
                tasks.append({'dir_path': str(folder), 'local_layout': 'flat'})
            project = {'name': 'isolated'}
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda task: cif_convert.read_or_convert_cif(project, task, 'POSCAR'), tasks))
            for task, element, result in zip(tasks, ('C', 'Ru'), results):
                expected = Path(task['dir_path']) / 'reports/structure'
                self.assertEqual(cif_convert.structure_report_dir(project, task), expected)
                self.assertIn(f'{element}1   {element} ', result)
                self.assertEqual((expected / 'POSCAR.cif').read_text(), result)
            self.assertEqual(legacy.read_text(), 'corrupt shared cache')

    def test_standard_task_path_does_not_depend_on_files_directory(self):
        with TemporaryDirectory() as tmp:
            task = {'dir_path': tmp}
            expected = Path(tmp) / 'reports/structure'
            for create_files in (False, True):
                if create_files:
                    (Path(tmp) / 'files').mkdir()
                self.assertEqual(cif_convert.structure_report_dir({'name': 'isolated'}, task), expected)

    def test_concurrent_conversions_use_independent_temporary_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [root / name for name in ('POSCAR', 'CONTCAR')]
            for source in sources:
                source.write_text(source.name)
            out = root / 'structure.cif'
            barrier = threading.Barrier(2)
            outputs = []

            def convert(command, **kwargs):
                destination = Path(command[command.index('-o') + 1])
                outputs.append(destination)
                destination.write_text(Path(command[-1]).read_text())
                barrier.wait(timeout=5)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(cif_convert.subprocess, 'run', side_effect=convert):
                with ThreadPoolExecutor(2) as pool:
                    results = list(pool.map(lambda src: cif_convert.convert_structure_to_cif(src, out, overwrite=True), sources))
            self.assertEqual(results, [True, True])
            self.assertEqual(len(set(outputs)), 2)
            self.assertIn(out.read_text(), ('POSCAR', 'CONTCAR'))
            self.assertFalse(list(root.glob('.*.tmp')))


if __name__ == '__main__':
    unittest.main()
