"""R2-B 隔离测试：两模型最小闭环（候选 → 证据冻结 → 组合保存/编辑/隐藏 → 自包含 HTML）。

必须在**独立进程**里运行：

    .venv/bin/python -m unittest discover -s tests -p 'test_report_compositions.py' -v

不连 SSH、不生成本地完整报告、不改真实数据；所有文件落在临时 DATA_DIR。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_DATA = tempfile.TemporaryDirectory(prefix="vasp-r2b-")
os.environ["VASP_WEB_DATA_DIR"] = _DATA.name
os.environ.pop("VASP_SSH_MOCK", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import r2_fixtures as fixtures  # noqa: E402


def _blocks_for_loop(blocks, first: str = "task_opt_01", second: str = "task_opt_02"):
    """两个模型 → 两个能量结果 → 参数对照 → 一张曲线 → 一段文字。"""
    return [
        {"type": "task.summary", "task_id": first},
        {"type": "task.energy_force", "task_id": first},
        {"type": "task.energy_force", "task_id": second},
        {"type": "task.params", "task_id": first},
        {"type": "task.convergence_curve", "task_id": first},
        {"type": "task.params", "task_id": second},
        {"type": "text.analysis", "text": "两个模型的能量差约 1 eV，**仅作展示**，未做参考态换算。"},
    ]


class ReportCompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import config

        if Path(config.DATA_DIR).resolve() != Path(_DATA.name).resolve():
            raise unittest.SkipTest(
                "test_report_compositions 需要独立进程运行（VASP_WEB_DATA_DIR 已被固定）"
            )
        import report_blocks
        import report_compositions

        cls.blocks = report_blocks
        cls.compositions = report_compositions
        config.ensure_data_dirs()
        cls.project = fixtures.seed(Path(_DATA.name))

    def setUp(self) -> None:
        import report_blocks

        self.merged = report_blocks.merged_results(force=True)

    def save(self, payload, **kwargs):
        return self.compositions.save(self.project, payload, merged=self.merged, **kwargs)

    # ---------------------------------------------------------------- 闭环

    def test_two_model_closed_loop_shares_evidence(self):
        doc = self.save({"title": "两模型对照", "blocks": _blocks_for_loop(self.blocks)})
        self.assertEqual(doc["revision"], 1)
        self.assertEqual(len(doc["blocks"]), 7)
        # 同一任务的 energy_force 与 convergence_curve 共用一条 Evidence，payload 只存一次
        first_energy = doc["evidence"][
            self.blocks.evidence_id(doc["project_id"], "task.energy", task_id="task_opt_01")
        ]
        self.assertEqual(first_energy["kind"], "task.energy")
        refs = [
            block["source_refs"][0]["evidence_id"]
            for block in doc["blocks"]
            if block["type"] in ("task.energy_force", "task.convergence_curve")
        ]
        self.assertEqual(len(set(refs)), 2, "两个任务的能量元素各一条证据（曲线共用）")
        self.assertEqual(len(doc["evidence"]), 5, "fact + 2×energy + 2×params")
        # 文本元素没有证据引用
        text_block = next(item for item in doc["blocks"] if item["type"] == "text.analysis")
        self.assertEqual(text_block["source_refs"], [])

    def test_reorder_and_rename_keep_block_identity(self):
        first = self.save({"title": "顺序 A", "blocks": _blocks_for_loop(self.blocks)})
        ids = [block["block_id"] for block in first["blocks"]]
        reversed_blocks = []
        for block in reversed(first["blocks"]):
            item = {
                "type": block["type"],
                "task_id": block["task_id"],
                "block_id": block["block_id"],
                "source_refs": block["source_refs"],
                "title": f"改名-{block['title']}",
            }
            if block["type"] == "text.analysis":
                item["text"] = block["text"]
            reversed_blocks.append(item)
        second = self.save(
            {
                "title": "顺序 B",
                "blocks": reversed_blocks,
                "expected_revision": 1,
                "hidden_block_ids": [ids[0]],
            },
            composition_id=first["composition_id"],
            expected_revision=1,
        )
        self.assertEqual(second["revision"], 2)
        self.assertEqual(sorted(block["block_id"] for block in second["blocks"]), sorted(ids))
        self.assertEqual([block["block_id"] for block in second["blocks"]], list(reversed(ids)))
        self.assertEqual(second["hidden_block_ids"], [ids[0]])
        self.assertTrue(all(block["title"].startswith("改名-") for block in second["blocks"]))

    def test_soft_delete_and_restore_keeps_evidence(self):
        first = self.save({"title": "删除恢复", "blocks": _blocks_for_loop(self.blocks)})
        target = first["blocks"][1]["block_id"]
        removed = self.save(
            {
                "title": "删除恢复",
                "blocks": first["blocks"],
                "deleted_block_ids": [target],
            },
            composition_id=first["composition_id"],
            expected_revision=1,
        )
        self.assertEqual(removed["deleted_block_ids"], [target])
        self.assertIn(target, [block["block_id"] for block in removed["blocks"]])
        restored = self.save(
            {"title": "删除恢复", "blocks": first["blocks"], "deleted_block_ids": []},
            composition_id=first["composition_id"],
            expected_revision=2,
        )
        self.assertEqual(restored["deleted_block_ids"], [])
        self.assertIn(target, [block["block_id"] for block in restored["blocks"]])

    # ---------------------------------------------------------------- 版本与并发

    def test_revision_conflict_is_reported(self):
        first = self.save({"title": "并发", "blocks": _blocks_for_loop(self.blocks)})
        with self.assertRaises(self.compositions.RevisionConflict) as ctx:
            self.save(
                {"title": "并发 2", "blocks": first["blocks"], "expected_revision": 99},
                composition_id=first["composition_id"],
                expected_revision=99,
            )
        self.assertEqual(ctx.exception.current, 1)

    def test_evidence_change_requires_explicit_refresh(self):
        first = self.save({"title": "版本", "blocks": _blocks_for_loop(self.blocks)})
        fixtures.rewrite_checks(
            Path(_DATA.name),
            lambda entries: [
                entry.update({"force_max": 9.99})
                for entry in entries
                if entry["task_id"] == "task_opt_01"
            ],
        )
        import report_blocks

        fresh = report_blocks.merged_results(force=True)
        with self.assertRaises(self.compositions.EvidenceStale) as ctx:
            self.compositions.save(
                self.project,
                {"title": "版本", "blocks": first["blocks"]},
                composition_id=first["composition_id"],
                expected_revision=1,
                merged=fresh,
            )
        self.assertTrue(ctx.exception.changes)
        refreshed = self.compositions.save(
            self.project,
            {"title": "版本", "blocks": first["blocks"], "refresh_evidence": True},
            composition_id=first["composition_id"],
            expected_revision=1,
            merged=fresh,
        )
        new_version = refreshed["evidence"][
            report_blocks.evidence_id(first["project_id"], "task.energy", task_id="task_opt_01")
        ]["version"]
        old_version = first["evidence"][
            report_blocks.evidence_id(first["project_id"], "task.energy", task_id="task_opt_01")
        ]["version"]
        self.assertNotEqual(new_version, old_version)

    # ---------------------------------------------------------------- 拒绝伪造

    def test_forged_block_id_rejected(self):
        wrong = self.blocks.block_id(
            "p_r2", "task.energy_force", task_id="task_opt_01"
        )
        with self.assertRaises(ValueError):
            self.save(
                {
                    "title": "伪造",
                    "blocks": [
                        {
                            "type": "task.energy_force",
                            "task_id": "task_opt_02",
                            "block_id": wrong,
                        }
                    ],
                }
            )

    def test_unknown_type_option_and_long_text_rejected(self):
        with self.assertRaises(ValueError):
            self.save({"title": "类型", "blocks": [{"type": "task.unknown", "task_id": "task_opt_01"}]})
        with self.assertRaises(ValueError):
            self.save(
                {
                    "title": "选项",
                    "blocks": [
                        {"type": "task.summary", "task_id": "task_opt_01",
                         "options": {"cmd": "ls"}}
                    ],
                }
            )
        with self.assertRaises(ValueError):
            self.save(
                {"title": "长文", "blocks": [{"type": "text.analysis", "text": "x" * 5000}]}
            )
        with self.assertRaises(ValueError):
            self.save({"title": "空", "blocks": []})

    def test_unsupported_evidence_rejected_without_silent_success(self):
        with self.assertRaises(ValueError):
            self.save(
                {
                    "title": "未接入",
                    "blocks": [{"type": "ele.pdos", "task_id": "task_opt_01"}],
                }
            )

    # ---------------------------------------------------------------- 导出

    def test_export_is_self_contained_and_escaped(self):
        payload = {
            "title": "导出测试",
            "blocks": [
                {"type": "task.energy_force", "task_id": "task_opt_01"},
                {"type": "task.convergence_curve", "task_id": "task_opt_01"},
                {"type": "task.params", "task_id": "task_opt_01"},
                {
                    "type": "text.analysis",
                    "text": "危险 <script>alert(1)</script> 与 ![外部图](http://evil.example/x.png)",
                },
            ],
            "hidden_block_ids": [],
        }
        doc = self.save(payload)
        html_text = self.compositions.render_html(doc)
        self.assertIn("<svg", html_text, "曲线必须内联 SVG")
        self.assertIn("<table", html_text, "参数必须渲染成表格")
        self.assertNotIn("<script>alert", html_text, "文本必须转义，不能注入脚本")
        self.assertIn("&lt;script&gt;", html_text)
        self.assertNotIn("http://evil.example", html_text, "分析文本不能自动加载外部图片")
        self.assertIn("证据版本", html_text)
        self.assertIn(doc["composition_id"], html_text)

    def test_export_respects_hidden_blocks(self):
        first = self.save({"title": "隐藏", "blocks": _blocks_for_loop(self.blocks)})
        hidden = first["blocks"][0]["block_id"]
        doc = self.save(
            {
                "title": "隐藏",
                "blocks": first["blocks"],
                "hidden_block_ids": [hidden],
            },
            composition_id=first["composition_id"],
            expected_revision=1,
        )
        html_text = self.compositions.render_html(doc)
        self.assertNotIn(f"id='{hidden}'", html_text)
        self.assertIn("id='%s'" % first["blocks"][1]["block_id"], html_text)

    # ---------------------------------------------------------------- 存储与权限

    def test_storage_is_isolated_from_full_report_index(self):
        doc = self.save({"title": "隔离", "blocks": _blocks_for_loop(self.blocks)})
        root = Path(_DATA.name) / "reports"
        self.assertTrue((root / "compositions" / fixtures.PROJECT_NAME / f"{doc['composition_id']}.json").is_file())
        self.assertFalse((root / "index.json").exists(), "不能写完整报告索引")

    def test_list_and_soft_delete(self):
        doc = self.save({"title": "列表", "blocks": _blocks_for_loop(self.blocks)})
        items = self.compositions.list_for(self.project)
        self.assertIn(doc["composition_id"], [item["composition_id"] for item in items])
        self.assertTrue(self.compositions.delete(self.project, doc["composition_id"]))
        self.assertNotIn(
            doc["composition_id"],
            [item["composition_id"] for item in self.compositions.list_for(self.project)],
        )
        with self.assertRaises(ValueError):
            self.save(
                {"title": "列表", "blocks": self.compositions.load(self.project, doc["composition_id"])["blocks"]},
                composition_id=doc["composition_id"],
                expected_revision=None,
            )

    def test_router_requires_project_ownership(self):
        from routers import report_compositions as router_module

        owner = SimpleNamespace(state=SimpleNamespace(user={"username": fixtures.OWNER, "role": "user"}))
        stranger = SimpleNamespace(state=SimpleNamespace(user={"username": "someone", "role": "user"}))
        admin = SimpleNamespace(state=SimpleNamespace(user={"username": "root", "role": "admin"}))

        self.assertEqual(router_module._authorized(fixtures.PROJECT_ID, owner)["name"], fixtures.PROJECT_NAME)
        self.assertEqual(router_module._authorized(fixtures.PROJECT_ID, admin)["name"], fixtures.PROJECT_NAME)
        with self.assertRaises(Exception) as ctx:
            router_module._authorized(fixtures.PROJECT_ID, stranger)
        self.assertIn("无权", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
