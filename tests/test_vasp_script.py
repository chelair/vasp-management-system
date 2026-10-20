"""vasp.lsf 后端渲染/解析：八段模板与前端 `src/utils/vaspLsf.ts` 的漂移检查。"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend")]

import vasp_script  # noqa: E402


class VaspScriptTests(unittest.TestCase):
    def test_render_roundtrip(self):
        text = vasp_script.render(queue="normal_2week", cores=96, cores_per_node=48,
                                  walltime_hours=24, job_name="managed_test")
        facts = vasp_script.parse(text)
        self.assertEqual(facts["issues"], [])
        self.assertEqual(facts["queue"], "normal_2week")
        self.assertEqual(facts["cores"], 96)
        self.assertEqual(facts["ptile"], 48)
        self.assertEqual(facts["walltime"], 24.0)
        self.assertTrue(facts["soft_kill"])
        self.assertEqual(facts["warn_minutes"], 50)

    def test_soft_kill_off_removes_watcher_and_directives(self):
        text = vasp_script.render(queue="ocean_530_1day", cores=24, cores_per_node=24,
                                  walltime_hours=24, job_name="managed_test", soft_kill=False)
        self.assertNotIn("#BSUB -wt", text)
        self.assertNotIn("#BSUB -wa", text)
        self.assertNotIn("lsf_watcher", text)
        self.assertNotIn("kill $WATCHER_PID", text)
        facts = vasp_script.parse(text)
        self.assertFalse(facts["soft_kill"])
        self.assertEqual(facts["issues"], [])

    def test_parse_accepts_soft_end_flags_it_was_previously_rejected(self):
        text = "\n".join(["#!/bin/bash", "#BSUB -J t", "#BSUB -q q", "#BSUB -W 12:00",
                          "#BSUB -wt 50", "#BSUB -wa URG", "#BSUB -n 48",
                          '#BSUB -R "span[ptile=48]"', "echo hi"])
        facts = vasp_script.parse(text)
        self.assertEqual(facts["issues"], [])
        self.assertTrue(facts["soft_kill"])
        self.assertEqual(facts["warn_minutes"], 50)

    def test_parse_reports_unknown_and_duplicate_flags(self):
        text = "\n".join(["#BSUB -q q", "#BSUB -n 24", "#BSUB -W 1:00", "#BSUB -B 5", "#BSUB -n 48"])
        issues = vasp_script.parse(text)["issues"]
        self.assertTrue(any("不支持的 BSUB" in i for i in issues), issues)
        self.assertTrue(any("重复的 BSUB" in i for i in issues), issues)

    def test_mismatch_is_detected(self):
        text = vasp_script.render(queue="q1", cores=48, cores_per_node=48, walltime_hours=2, job_name="t")
        self.assertEqual(vasp_script.check(text, expected_cores=48, expected_walltime=2, expected_queue="q1"), [])
        self.assertTrue(vasp_script.check(text, expected_cores=24))
        self.assertTrue(vasp_script.check(text, expected_queue="q2"))

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(vasp_script.ScriptError):
            vasp_script.render(queue="bad queue", cores=24, cores_per_node=24, walltime_hours=2, job_name="t")
        with self.assertRaises(vasp_script.ScriptError):
            vasp_script.render(queue="q", cores=0, cores_per_node=24, walltime_hours=2, job_name="t")
        with self.assertRaises(vasp_script.ScriptError):
            vasp_script.render(queue="q", cores=24, cores_per_node=24, walltime_hours=0, job_name="t")

    def test_no_drift_against_frontend_template(self):
        """前端模板是权威来源：这里检查固定段/常量仍与后端渲染一致。"""
        source = (ROOT / "src" / "utils" / "vaspLsf.ts").read_text(encoding="utf-8")
        constants = dict(re.findall(r"const (VASP_BIN|PSXEVARS) = '([^']+)'", source))
        self.assertEqual(constants.get("VASP_BIN"), vasp_script.VASP_BIN)
        self.assertEqual(constants.get("PSXEVARS"), vasp_script.PSXEVARS)
        text = vasp_script.render(queue="q1", cores=24, cores_per_node=24, walltime_hours=24, job_name="t")
        for line in ("#!/bin/bash", "source " + vasp_script.PSXEVARS, "module load impi",
                     "export I_MPI_HYDRA_BOOTSTRAP=lsf", "export I_MPI_FABRICS=shm:ofi",
                     "rm -f STOPCAR", "mpiexec.hydra -genvall -n $NPROCS $VASP_BIN >> result 2>&1",
                     "START=$(date +%s)", "exit $RC", "    while true; do sleep 60; done"):
            self.assertIn(line, text, line)
        # 前端注释规定：软结束两条指令必须插在 -W 与 -n 之间。
        order = [m.group(1) for m in re.finditer(r"^#BSUB (-[a-zA-Z]+)", text, re.MULTILINE)]
        self.assertEqual(order, ["-J", "-q", "-o", "-e", "-W", "-wt", "-wa", "-n", "-R"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
