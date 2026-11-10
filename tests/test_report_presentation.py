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


def make_report(*, statuses=None, merged=None, tasks=None):
    project = {
        "project_id": "proj_test", "name": "ReportTest", "deadline": "2020-01-01", "server": "",
        "tasks": tasks if tasks is not None else [
            {"task_id": str(i), "model_name": f"model{i}", "task_type": "opt", "status": status,
             "last_energy": (merged or {}).get(str(i), {}).get("last_energy"),
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
    def test_neb_endpoints_show_until_their_own_path_has_calculation_data(self):
        import config
        import report_interactive
        config.ensure_data_dirs()
        def task(tid,group,role,kind='opt',status='completed'):
            return {'task_id':tid,'model_name':tid,'task_type':kind,'status':status,
                    'last_energy':-10. if kind=='opt' else None,
                    'dir_path':f'ReportTest/{group}/{tid}',
                    'group':{'group_id':group,'name':group,'group_type':'neb' if group!='free' else 'free_energy','group_role':role}}
        tasks=[task('A_IS','A','initial_opt'),task('A_FS','A','final_opt',status='unconverged'),task('A_NEB','A','neb_images','neb','pending'),
               task('B_IS','B','initial_opt'),task('B_FS','B','final_opt'),task('B_NEB','B','neb_images','neb','running'),
               task('free_opt','free','main_structure')]
        history={'force_converged':False,'force_history':[{'step':1,'energy':-10.,'max_force':.3}]}
        base={t['task_id']:copy.deepcopy(history) for t in tasks if t['task_type']=='opt'}
        base['B_NEB']={'neb_barrier':{'images':[{'label':'00','relative':0.,'energy':-10.},{'label':'01','relative':1.,'energy':-9.}]}}
        cases=[({},True),({'neb_barrier':{'images':[]}},True),
               ({'neb_barrier':{'images':[{'label':'00','energy':None,'relative':None,'max_force':None}]}},True),
               ({'neb_band_steps':1},False),
               ({'neb_barrier':{'images':[{'label':'00','energy':-10.}]}},False),
               ({'neb_barrier':{'images':[{'label':'00','relative':0.,'energy':-10.}]}},False)]
        for observation,show in cases:
            with self.subTest(observation=observation):
                merged={**base,'A_NEB':observation}
                with patch.object(builder,'read_or_convert_cif',return_value='data_saved_endpoint'):
                    doc=make_report(tasks=tasks,merged=merged)
                ids=[r['task_id'] for r in doc['science']['opt']]
                self.assertEqual(ids,['A_IS','A_FS'] if show else [])
                science=next(s['markdown'] for s in doc['markdown_sections'] if s['key']=='science')
                html=render_html(doc,doc['markdown_sections'])
                neb=doc['science']['neb'][0]
                self.assertEqual(neb['stages']['initial_opt']['task_id'],'A_IS')
                self.assertEqual(neb['stages']['final_opt']['status'],'unconverged')
                self.assertEqual(neb['has_calculation_data'],not show)
                for tid in ('A_IS','A_FS'):
                    self.assertNotIn(f'\n##### {tid}\n',science)
                    self.assertNotIn(f'\n#### {tid}\n',science)
                    self.assertNotIn(f'data-task-id="{tid}"',html)
                self.assertEqual('data-task-id="neb_endpoints_A_NEB"' in html,show)
                payload=report_interactive.interactive_payload(doc)
                self.assertEqual('neb_endpoints_A_NEB' in payload['free_energy'],show)
                if show:
                    path=neb['endpoint_path']
                    self.assertEqual([s['display_label'] for s in path['structures']],['初态-IS','末态-FS'])
                    self.assertEqual([s['cif'] for s in path['structures']],['data_saved_endpoint']*2)
                    self.assertLess(science.index('#### A_NEB\n'),science.index('[初态-IS]'))
                    self.assertLess(science.index('[末态-FS]'),science.index('#### B_NEB\n'))
                    self.assertIn('收敛历史',science)
                    self.assertIn('dlg_conv_A_IS',science)
                self.assertNotIn('### 结构优化\n',science)
                self.assertNotIn('#### B_IS\n',science);self.assertNotIn('#### B_FS\n',science)
                self.assertNotIn('#### free_opt\n',science)
                self.assertEqual(set(report_interactive.interactive_payload(doc)['structure']),{'A_IS','A_FS'} if show else set())
                if show:self.assertIn('⚠️ 未收敛',science)

    def test_neb_endpoint_missing_initial_cif_keeps_final_structure_index(self):
        import report_interactive
        doc={'science':{'neb':[{'endpoint_path':{'group_id':'endpoints','structures':[
            {'structure_label':'IS','display_label':'初态-IS','cif':None},
            {'structure_label':'FS','display_label':'末态-FS','cif':'data_final'}]}}]}}
        structures=report_interactive.interactive_payload(doc)['free_energy']['endpoints']
        self.assertEqual(len(structures),2)
        self.assertIsNone(structures[0]['cif'])
        self.assertEqual(structures[1]['display_label'],'末态-FS')
        self.assertEqual(structures[1]['cif'],'data_final')

    def test_unconverged_structures_and_partial_results_remain_in_report(self):
        import config
        config.ensure_data_dirs()
        merged={
            '0':{'force_converged':True,'force_history':[{'step':1,'energy':-10.,'max_force':.01}]},
            '1':{'force_converged':False,'last_energy':-11.,'force_history':[{'step':1,'energy':-11.,'max_force':.3}]},
            '2':{'force_converged':False,'last_energy':-12.,'force_history':[{'step':1,'energy':-12.,'max_force':.2}]},
            '3':{'force_converged':False,'last_energy':-13.},
        }
        with patch.object(builder,'read_or_convert_cif',return_value='data_unconverged_structure'):
            doc=make_report(statuses=['completed','unconverged','running','unconverged','pending'],merged=merged)
        items=doc['science']['opt']
        self.assertEqual([r['task_id'] for r in items],['0','1','2','3'])
        self.assertEqual([r['converged'] for r in items],[True,False,False,False])
        self.assertEqual(doc['science']['opt_skipped_unconverged'],0)
        self.assertEqual(items[3]['final_energy_ev'],-13.)
        self.assertEqual(items[3]['charts'],{})
        self.assertIsNone(items[3]['conv_dialog'])
        science=next(s['markdown'] for s in doc['markdown_sections'] if s['key']=='science')
        self.assertEqual(science.count('⚠️ 未收敛'),3)
        self.assertNotIn('其结构与曲线未纳入',science)
        html=render_html(doc,doc['markdown_sections'])
        for i in range(4):
            self.assertIn(f'#### model{i}\n',science)
            self.assertIn(f'@[structure-3d:{i}]',science)
            self.assertIn(f'model{i}',html)
        self.assertIn('未收敛',html)

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
        self.assertNotRegex(hidden, r"<h5\b[^>]*>A · 功函数</h5>")
        self.assertRegex(hidden, r"<h5\b[^>]*>B · 功函数</h5>")
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
