"""R2-A 隔离测试：完整候选目录、稳定 ID、来源与状态（availability/validation/freshness）。

必须在**独立进程**里运行（数据目录由环境变量在 import 前固定）：

    .venv/bin/python -m unittest discover -s tests -p 'test_report_blocks.py' -v

覆盖：10 个 OPT 任务（完整报告不再限制展示数量）、未收敛、有文件未解析、完全无数据、
同名任务、辅助 conN 任务、ID 与数据版本分离、UNKNOWN 不冒充 PASS。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_DATA = tempfile.TemporaryDirectory(prefix="vasp-r2a-")
os.environ["VASP_WEB_DATA_DIR"] = _DATA.name
os.environ.pop("VASP_SSH_MOCK", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import r2_fixtures as fixtures  # noqa: E402


class ReportBlocksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import config

        if Path(config.DATA_DIR).resolve() != Path(_DATA.name).resolve():
            raise unittest.SkipTest(
                "test_report_blocks 需要独立进程运行（VASP_WEB_DATA_DIR 已被固定）"
            )
        import report_blocks

        cls.blocks = report_blocks
        config.ensure_data_dirs()
        cls.project = fixtures.seed(Path(_DATA.name))
        cls.catalog = report_blocks.list_candidates(cls.project, force=True)

    def candidates(self, block_type: str):
        return [item for item in self.catalog["candidates"] if item["type"] == block_type]

    def by_task(self, block_type: str, task_id: str):
        for item in self.candidates(block_type):
            if item["task_id"] == task_id:
                return item
        self.fail(f"找不到 {block_type} / {task_id}")

    # ---------------------------------------------------------------- 目录

    def test_catalog_covers_every_task_without_report_limit(self):
        summaries = self.candidates("task.summary")
        self.assertEqual(len(summaries), fixtures.OPT_COUNT, "10 个 OPT 任务都应出现在候选目录")
        self.assertIsNone(self.catalog["evidence_task_limit"])
        self.assertEqual(self.by_task("task.summary", "task_opt_10")["full_report_visibility"], "shown")
        self.assertEqual(self.by_task("task.summary", "task_opt_07")["full_report_visibility"], "shown")
        self.assertEqual(self.by_task("task.summary", fixtures.NO_CHECK_TASK)["full_report_visibility"], "omitted_no_history")
        self.assertEqual(self.by_task("task.summary", "task_opt_01")["full_report_visibility"], "shown")

    def test_auxiliary_continuation_task_is_not_a_candidate(self):
        task_ids = {item["task_id"] for item in self.catalog["candidates"]}
        self.assertNotIn("task_opt_01_con1", task_ids)

    def test_unconverged_is_kept_but_marked(self):
        summary = self.by_task("task.summary", fixtures.UNCONVERGED_TASK)
        self.assertEqual(summary["full_report_visibility"], "omitted_unconverged")
        energy = self.by_task("task.energy_force", fixtures.UNCONVERGED_TASK)
        self.assertEqual(energy["availability"], "available", "未收敛不等于没有数据")
        self.assertEqual(energy["validation"]["status"], "FAIL")

    def test_file_without_archive_is_unparsed_not_missing(self):
        energy = self.by_task("task.energy_force", fixtures.NO_CHECK_TASK)
        self.assertEqual(energy["availability"], "unparsed")
        self.assertIn("尚未解析", energy["detail"])

    def test_no_data_is_missing_and_unknown(self):
        energy = self.by_task("task.energy_force", fixtures.NO_DATA_TASK)
        self.assertEqual(energy["availability"], "missing")
        self.assertEqual(energy["validation"]["status"], "UNKNOWN")

    def test_same_model_name_does_not_collide(self):
        first = self.by_task("task.summary", "task_opt_04")
        second = self.by_task("task.summary", fixtures.SHARED_NAME_TASK)
        self.assertEqual(first["title"], second["title"], "两个任务同名")
        self.assertNotEqual(first["block_id"], second["block_id"], "ID 必须按任务区分，不能只按标题")
        self.assertNotEqual(first["evidence_id"], second["evidence_id"])

    def test_legacy_hidden_aliases_do_not_guess_ambiguous_names_or_ordinals(self):
        first = self.by_task("task.energy_force", "task_opt_01")
        self.assertIn("task:science:Model01", first["legacy_hidden_keys"])
        for tid in ("task_opt_04", fixtures.SHARED_NAME_TASK):
            keys = self.by_task("task.energy_force", tid)["legacy_hidden_keys"]
            self.assertNotIn("task:science:Model04", keys)
            self.assertFalse(any(key.startswith("figure:") for key in keys))

    def test_catalog_is_deterministic(self):
        again = self.blocks.list_candidates(self.project, force=True)
        self.assertEqual(
            [item["block_id"] for item in again["candidates"]],
            [item["block_id"] for item in self.catalog["candidates"]],
        )
        # ID 不含标题/数值：改标题不改变 ID
        renamed = dict(self.project)
        renamed["tasks"] = [
            {**task, "model_name": "Renamed"} if task["task_id"] == "task_opt_01" else task
            for task in self.project["tasks"]
        ]
        renamed_catalog = self.blocks.list_candidates(renamed, force=True)
        old = self.by_task("task.summary", "task_opt_01")["block_id"]
        new = next(
            item["block_id"]
            for item in renamed_catalog["candidates"]
            if item["type"] == "task.summary" and item["task_id"] == "task_opt_01"
        )
        self.assertEqual(old, new)

    def test_project_comparison_counts_only_energy_rows(self):
        evidence = self.blocks.resolve_evidence(
            self.project, "project.comparison", force=True
        )
        expected = len([t for t in self.project["tasks"] if t.get("last_energy") is not None
                        and t["task_id"] != "task_opt_01_con1"])
        self.assertEqual(len(evidence["payload"]["rows"]), expected)

    # ---------------------------------------------------------------- 证据

    def test_resolve_returns_provenance_and_freshness(self):
        evidence = self.blocks.resolve_evidence(
            self.project, "task.energy_force", task_id="task_opt_01", force=True
        )
        self.assertTrue(evidence["version"].startswith("sha256:"))
        source = evidence["provenance"][0]
        self.assertEqual(source["task_id"], "task_opt_01")
        self.assertEqual(source["attempt"], "con1")
        self.assertTrue(source["parsed_at"])
        self.assertEqual(evidence["freshness"]["state"], "fresh")
        self.assertEqual(evidence["payload"]["units"]["final_energy_ev"], "eV")
        self.assertEqual(len(evidence["payload"]["series"]), 3)

    def test_block_id_stable_when_data_changes_but_version_is_not(self):
        before = self.blocks.resolve_evidence(
            self.project, "task.energy_force", task_id="task_opt_02", force=True
        )
        fixtures.rewrite_checks(
            Path(_DATA.name),
            lambda entries: [
                entry.update({"force_max": 9.99})
                for entry in entries
                if entry["task_id"] == "task_opt_02"
            ],
        )
        after = self.blocks.resolve_evidence(
            self.project, "task.energy_force", task_id="task_opt_02", force=True
        )
        self.assertEqual(self.by_task("task.energy_force", "task_opt_02")["block_id"],
                         self.blocks.block_id(
                             self.catalog["project_id"],
                             "task.energy_force",
                             task_id="task_opt_02",
                         ))
        self.assertNotEqual(before["version"], after["version"], "数据变了版本必须变")

        # 只改观测时间：版本不能变（生成/观测时间不能冒充数据版本）
        fixtures.rewrite_checks(
            Path(_DATA.name),
            lambda entries: [
                entry.update({"checked_at": "2026-01-01T00:00:00+08:00"})
                for entry in entries
                if entry["task_id"] == "task_opt_02"
            ],
        )
        after_time = self.blocks.resolve_evidence(
            self.project, "task.energy_force", task_id="task_opt_02", force=True
        )
        self.assertEqual(after["version"], after_time["version"])
        self.assertEqual(after_time["freshness"]["state"], "stale")

    def test_unsupported_type_refuses_instead_of_faking(self):
        with self.assertRaises(self.blocks.UnsupportedEvidence):
            self.blocks.resolve_evidence(
                self.project, "ele.pdos", task_id="task_opt_01", force=True
            )

    def test_text_block_ids_are_random(self):
        first = self.blocks.new_text_block_id()
        second = self.blocks.new_text_block_id()
        self.assertTrue(first.startswith("blk_txt_"))
        self.assertNotEqual(first, second)

    def test_options_whitelist(self):
        self.assertEqual(self.blocks.normalize_options(None), {})
        self.assertEqual(self.blocks.normalize_options({"compact": True}), {"compact": True})
        with self.assertRaises(ValueError):
            self.blocks.normalize_options({"command": "rm -rf /"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
