"""巡检保留策略：真实文件裁剪、历史检索、派生视图与日统计一致性。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import tarfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import checks_store as store


class CheckRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vasp-retention-")
        self.root = Path(self.temp.name)
        self.patcher = patch.object(store, "CHECKS_DIR", self.root)
        self.patcher.start()
        store.invalidate_cache()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()
        store.invalidate_cache()

    def write(self, name, entries, day):
        path = self.root / f"check_results_{name}_server.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        stamp = 1767225600 + day * 86400
        os.utime(path, (stamp, stamp))
        return path

    def record(self, tid, day, **values):
        return {"task_id": tid, "project_name": "project", "checked_at": f"2026-01-{day:02}T12:00:00",
                "status": "running", "force_history": [], "force_max": None,
                "remote_dir": f"/remote/{tid}", "current_output": {"latest_dir": f"con{day}"}, **values}

    def test_mixed_batches_retain_five_per_task_without_erasing_other_task(self):
        first = None
        for day in range(1, 8):
            entries = [self.record("a", day)]
            if day <= 3:
                entries.append(self.record("b", day))
            path = self.write(str(day), entries, day)
            if day == 1:
                first = path
        mtime = first.stat().st_mtime_ns
        before_latest = store.collect_results()
        summary = store.enforce_retention()
        self.assertEqual(summary["removed_records"], 2)
        self.assertEqual([r["checked_at"][8:10] for r in store.collect_task_history("a", limit=100)], ["07", "06", "05", "04", "03"])
        self.assertEqual(len(store.collect_task_history("b")), 3)
        self.assertEqual(first.stat().st_mtime_ns, mtime)
        self.assertEqual([r["task_id"] for r in json.loads(first.read_text())], ["b"])
        self.assertEqual(store.collect_results(), before_latest)
        self.assertEqual(store.enforce_retention()["removed_records"], 0)

    def test_latest_inherited_results_and_historical_day_stats_survive_pruning(self):
        for day in range(1, 8):
            self.write(str(day), [self.record("a", day, status="completed" if day == 1 else "running",
                force_max=0.01 if day == 1 else None, force_converged=True if day == 1 else None,
                force_history=[{"step": 23}] if day == 1 else [], error_messages=["old failure"] if day == 2 else [])], day)
        latest, days = store.collect_results(), store.daily_summary()
        store.enforce_retention()
        self.assertEqual(store.collect_results(), latest)
        self.assertEqual(store.daily_summary(), days)
        self.assertEqual(store.collect_results()["a"]["force_history"], [{"step": 23}])
        self.assertFalse((self.root / "check_results_1_server.json").exists())
        # 此后再巡检仍保留派生数据，原始历史只留下五次。
        store.archive_results([self.record("a", 8)], "server", "new")
        self.assertEqual(len(store.collect_task_history("a", limit=50)), 5)
        self.assertEqual(store.collect_results()["a"]["force_max"], 0.01)
        self.assertEqual(store.daily_summary()["2026-01-02"]["completed"], ["a"])

    def test_checked_time_and_older_task_search_do_not_depend_on_file_scan_cap(self):
        self.write("a", [self.record("old", 1)], 1)
        for day in range(2, 9):
            self.write(str(day), [self.record("new", day)], day)
        self.assertEqual(len(store.collect_task_history("old", scan_files=1)), 1)
        # 老记录文件被重新复制、mtime较新，也不取代实际较新的巡检。
        self.write("copied", [self.record("new", 1)], 20)
        store.enforce_retention()
        self.assertEqual([r["checked_at"][8:10] for r in store.collect_task_history("new")], ["08", "07", "06", "05", "04"])

    def test_concurrent_archives_keep_cap_and_valid_json(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda day: store.archive_results([self.record("a", day), self.record("b", day)], "server", str(day)), range(1, 13)))
        self.assertEqual(len(store.collect_task_history("a", limit=99)), 5)
        self.assertEqual(len(store.collect_task_history("b", limit=99)), 5)
        self.assertEqual(store.collect_task_history("a")[0]["checked_at"], "2026-01-12T12:00:00")
        for path in self.root.glob("*.json"):
            json.loads(path.read_text())

    def test_failed_checkpoint_does_not_remove_raw_archives(self):
        for day in range(1, 8):
            self.write(str(day), [self.record("a", day)], day)
        original = store._atomic_json
        def fail_daily(path, value, **kwargs):
            if path.name == "daily_summary.json":
                raise OSError("simulated full disk")
            return original(path, value, **kwargs)
        with patch.object(store, "_atomic_json", side_effect=fail_daily):
            with self.assertRaises(OSError):
                store.enforce_retention()
        self.assertEqual(len(list(self.root.glob("check_results_*.json"))), 7)
        self.assertEqual(store.enforce_retention()["retained_records"], 5)

    def test_same_directory_overwrites_even_if_job_and_parameters_change(self):
        for day in range(1, 8):
            store.archive_results([self.record("a", day, current_output={"latest_dir": "con1"},
                job_id=str(day), incar={"ENCUT": 400+day})], "server", str(day))
        history = store.collect_task_observations("a")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["data"]["job_id"], "7")
        self.assertEqual(history[0]["data"]["incar"]["ENCUT"], 407)
        raw = [row for p in self.root.glob("check_results_*.json") for row in json.loads(p.read_text())]
        self.assertEqual(len(raw), 1)
        previous_id = history[0]["observation_id"]
        store.archive_results([self.record("a", 8, current_output={"latest_dir": "con1"})], "server", "8")
        self.assertNotEqual(store.collect_task_observations("a")[0]["observation_id"], previous_id)

    def test_directory_aliases_main_unknown_and_five_recent_directory_limit(self):
        for day in range(1, 9):
            self.write(str(day), [self.record("a", day)], day)
        self.write("update2", [self.record("a", 9, current_output={"latest_dir": "/remote/a/con2/"})], 9)
        store.enforce_retention()
        rows = store.collect_task_observations("a")
        self.assertEqual([r["directory"]["path"] for r in rows], ["/remote/a/con2", "/remote/a/con8", "/remote/a/con7", "/remote/a/con6", "/remote/a/con5"])
        for day, output in ((1, "MAIN"), (2, ""), (3, "."), (4, None)):
            self.write(f"b{day}", [self.record("b", day, current_output={"latest_dir": output})], day)
        store.enforce_retention()
        rows = store.collect_task_observations("b")
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]["directory"]["known"])
        self.assertEqual(rows[1]["directory"]["path"], "/remote/b")

    def test_backup_restores_distinct_directories_without_regressing_latest(self):
        old = self.write("old", [self.record("a", 1), self.record("a", 2)], 2)
        backup_path = self.root / "rollback.tar.gz"
        with tarfile.open(backup_path, "w:gz") as archive:
            archive.add(old, arcname="checks/" + old.name)
        old.unlink()
        store.archive_results([self.record("a", 7, current_output={"latest_dir": "con2"}, force_max=0.01)], "server", "latest")
        latest = store.collect_results()
        result = store.enforce_retention(backup_path)
        self.assertEqual(result["restored_records"], 1)
        self.assertEqual([r["data"]["checked_at"][8:10] for r in store.collect_task_observations("a")], ["07", "01"])
        self.assertEqual(store.collect_results(), latest)
        self.assertEqual(store.enforce_retention(backup_path)["restored_records"], 0)


if __name__ == "__main__":
    unittest.main()
