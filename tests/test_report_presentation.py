"""报告呈现回归：隔离数据，无 SSH、无生产写入。运行 .venv/bin/python -m unittest discover -s tests。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix="vasp-report-test-")
os.environ["VASP_WEB_DATA_DIR"] = _DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import report_builder as builder
import report_rules
import report_store
from report_export import render_html

RULES = json.loads((Path(__file__).resolve().parents[1] / "backend/defaults/report_rules.json").read_text())


def make_report(*, statuses=None, merged=None):
    project = {
        "project_id": "proj_test", "name": "ReportTest", "deadline": "2020-01-01", "server": "",
        "tasks": [
            {"task_id": str(i), "model_name": f"model{i}", "task_type": "opt", "status": status,
             "dir_path": f"ReportTest/opt/model{i}", "remote_dir": f"ReportTest/opt/model{i}"}
            for i, status in enumerate(statuses if statuses is not None else ["archived", "completed", "running"])
        ],
    }
    with patch.object(builder, "load_db", return_value={"projects": [project]}), \
         patch.object(builder, "collect_results", return_value=merged or {}), \
         patch.object(builder, "list_runs", return_value=[]), \
         patch.object(builder, "to_frontend_rows", return_value=[]), \
         patch.object(builder, "load_rules", return_value=RULES), \
         patch.object(builder, "cluster_snapshot", side_effect=AssertionError("unexpected SSH")):
        return builder.build_report("ReportTest")["report"]


def electronic_item(name, task_id):
    return {
        "task_id": task_id, "task_name": name,
        "diff_charge": [{"block": 1, "atoms_count": 1, "status_label": "已完成"}],
        "charge_diff": {"ok": True},
        "bader_summary": {"n_atoms": 1, "net_charge_available": False, "total_charge": 1.0},
        "pdos_summary": {"chart": f"charts/{task_id}_pdos.svg", "efermi": -1.0,
                         "band_centers": [{"name": "Fe d up", "value": -1.25}], "range": [-5, 2]},
        "work_function_summary": {"chart": f"charts/{task_id}_wf.svg", "axis": "c",
                                  "axis_cartesian": "z", "work_function": 5.0, "vacuum_level": 4.0, "efermi": -1.0},
    }


class ReportPresentationTests(unittest.TestCase):
    def test_all_eligible_structures_and_curves_reach_markdown_and_export(self):
        import config
        config.ensure_data_dirs()
        merged = {str(i): {"force_converged": True, "force_history": [
            {"step": 1, "energy": -100.0-i, "max_force": 0.01}]} for i in range(10)}
        doc = make_report(statuses=["completed"]*10, merged=merged)
        self.assertEqual([item["task_id"] for item in doc["science"]["opt"]], [str(i) for i in range(10)])
        self.assertIsNone(doc["appendix"]["generation_params"]["max_structure_tasks"])
        science = next(s["markdown"] for s in doc["markdown_sections"] if s["key"] == "science")
        html = render_html(doc, doc["markdown_sections"])
        for i in range(10):
            self.assertIn(f"#### model{i}\n", science)
            self.assertIn(f"#dlg_conv_{i}", science)
            self.assertIn(f"model{i}", html)
            self.assertIn(f'dlg_conv_{i}', html)
        self.assertNotIn("其余仅保留", science)

    def test_project_progress_and_overdue_use_same_weighted_basis(self):
        doc = make_report()
        self.assertEqual(doc["basic_info"]["weighted_progress_percent"], 66.7)
        self.assertEqual(doc["basic_info"]["progress_percent"], 50.0)  # 保留原有字段语义
        overdue = next(r for r in doc["risks"]["items"] if r["rule_id"] == "R_PROJECT_OVERDUE")
        self.assertIn("66.7%", overdue["description"])
        self.assertIn("项目进度 66.7%", doc["executive_summary"]["summary_text"])
        self.assertIn("任务完成率 50.0%", doc["executive_summary"]["summary_text"])

    def test_old_continuation_rule_requires_evidence_and_keeps_custom_rules(self):
        legacy = next(r for r in RULES["rules"] if r["rule_id"] == "R_TASK_CONTINUATION_MANY")
        rules = {"rules": [legacy, {**legacy, "rule_id": "CUSTOM_COUNT"}]}
        for converged, status, expected in [(True, "running", False), (None, "running", False),
                                             (False, "running", True), (None, "unconverged", True),
                                             (True, "unconverged", False)]:
            with self.subTest(converged=converged, status=status):
                facts = [{"task_id": "t", "task_name": "model", "continuation_count": 4,
                          "converged": converged, "status": status}]
                items = report_rules.evaluate(facts, {}, rules=rules)
                ids = {r["rule_id"] for r in items}
                self.assertEqual("R_TASK_CONTINUATION_MANY" in ids, expected)
                self.assertIn("CUSTOM_COUNT", ids)

    def test_model_grouping_preserves_science_widgets_and_export(self):
        doc = make_report()
        doc["science"]["ele"]["tasks"] = [electronic_item("A", "a"), electronic_item("B", "b")]
        original = copy.deepcopy(doc["science"])
        sections = builder._sections_markdown(doc, {})
        science = next(s["markdown"] for s in sections if s["key"] == "science")
        self.assertIn("关键结果概览", science)
        self.assertIn("-1.25", science)
        self.assertLess(science.index("#### A · 功函数"), science.index("#### B · 差分电荷"))
        for task in ("a", "b"):
            self.assertEqual(science.count(f"@[pdos-chart:{task}]"), 1)
            self.assertEqual(science.count(f"@[work-function-chart:{task}]"), 1)
        self.assertEqual(doc["science"], original)  # 数值与挂点数据不变
        basic = next(s["markdown"] for s in sections if s["key"] == "basic_info")
        self.assertIn("折算工作量", basic)
        self.assertIn("并非实测消耗", basic)
        html = render_html(doc, sections)
        self.assertIn("关键结果概览", html)
        hidden = render_html(doc, sections, hidden={"etask:science:A"})
        self.assertNotIn("<h5>A · 功函数</h5>", hidden)
        self.assertIn("<h5>B · 功函数</h5>", hidden)
        self.assertNotIn('data-label="模型">A</td>', hidden)
        self.assertIn('data-label="模型">B</td>', hidden)

    def test_free_energy_reference_is_explained_without_changing_numbers(self):
        doc = make_report()
        doc["science"]["free_energy"] = [{"group_name": "Path", "group_id": "p", "structure_count": 1,
            "structures": [{"structure_label": "1", "dft_energy_ev": -10.0, "correction_ev": 0.5,
                            "free_energy_ev": -9.5, "converged": True, "corrected": True}]}]
        sections = builder._sections_markdown(doc, {})
        science = next(s["markdown"] for s in sections if s["key"] == "science")
        self.assertIn("参考物种", science)
        self.assertIn("不等同于 NEB", science)
        self.assertIn("-9.5000", science)
        self.assertEqual(doc["science"]["free_energy"][0]["structures"][0]["free_energy_ev"], -9.5)

    def test_hidden_figures_follow_asset_not_position(self):
        def doc(paths):
            return {"markdown_sections": [{"key": "science", "markdown": "\n".join(f"![x]({p})" for p in paths)}]}
        old, new = doc(["a.svg", "b.svg", "a.svg"]), doc(["b.svg", "a.svg", "a.svg"])
        self.assertEqual(report_store._remap_hidden_figures(old, new,
            ["task:science:A", "figure:science:0", "figure:science:1", "figure:science:2"]),
            ["task:science:A", "figure:science:1", "figure:science:0", "figure:science:2"])
        self.assertEqual(report_store._remap_hidden_figures(old, doc(["b.svg"]), ["figure:science:0"]), [])

    def test_regeneration_preserves_notes_and_remaps_persisted_edits(self):
        doc = make_report()
        report_id = doc["metadata"]["report_id"]
        doc["markdown_sections"][1]["markdown"] = "![A](charts/a.svg)\n![B](charts/b.svg)\n"
        charts = {"a.svg": "<svg></svg>", "b.svg": "<svg></svg>"}
        report_store.save_report(doc, "old", charts)
        report_store.save_edits(report_id, ["issues"], ["etask:science:A", "figure:science:0"])
        report_store.save_note(report_id, "type_ele", "分析记录", "论文参考")
        doc["markdown_sections"][1]["markdown"] = "![B](charts/b.svg)\n![A](charts/a.svg)\n"
        entry = report_store.save_report(doc, "new", charts)
        self.assertEqual(report_store.read_edits(report_id)["hidden_elements"],
                         ["etask:science:A", "figure:science:1"])
        self.assertEqual(report_store.read_edits(report_id)["hidden_sections"], ["issues"])
        self.assertEqual(report_store.read_notes(report_id)["type_ele"]["analysis_note"], "分析记录")
        self.assertEqual(entry["weighted_progress_percent"], 66.7)


if __name__ == "__main__":
    unittest.main()
