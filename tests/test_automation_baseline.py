"""阶段0基础回归（阶段1修复后的契约）：自动化动作 + 离线HPC夹具。

对应 `agent-upgrade/00-baseline.md` §5「测试基线」。覆盖：

1. `dry_run` 不产生副作用（不 bsub、不改状态）
2. 正常提交：解析 job_id 并把状态置 queued
3. 已提交/运行中再次提交被业务前置条件拦住
4. bsub 被集群拒绝：状态不变、错误原样带回
5. **bsub 已成功但 SSH 响应丢失**：保持UNKNOWN并只读对账，不重复提交
6. 调度层显式幂等键去重
7. **失败也计数**：`max_runs_per_task`限制失败尝试
8. 任务锁：占用中再次提交被 blocked
9. 进程重启：`running`运行记录标interrupted，不盲目重放
10. VASP OUTCAR 正常结束 / 未收敛夹具

运行方式（**必须在独立进程中**，因为要靠环境变量决定数据目录，而 backend
的 `config.DATA_DIR` 在首次 import 时就固定了）：

    .venv/bin/python -m unittest discover -s tests -p 'test_automation_baseline.py' -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_hpc import MockHpc  # noqa: E402  （纯标准库，先于 backend import 无副作用）

_PROJECT = "STAGE0"
_TASK_REL = "STAGE0/T1"


class AutomationBaselineTest(unittest.TestCase):
    """所有用例都在临时数据目录 + 临时 mock 远端树里跑。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._data_tmp = tempfile.TemporaryDirectory(prefix="vasp-stage0-data-")
        cls._remote_tmp = tempfile.TemporaryDirectory(prefix="vasp-stage0-remote-")
        os.environ["VASP_WEB_DATA_DIR"] = cls._data_tmp.name
        os.environ["VASP_SSH_MOCK"] = "1"
        os.environ["VASP_MOCK_REMOTE_ROOT"] = cls._remote_tmp.name
        os.environ.pop("VASP_SYNC_REMOTE_DIRS", None)

        import config

        # 同一进程里若已有别的测试先 import 过 backend，DATA_DIR 就固定不下来，
        # 这时宁可跳过也不能写进别人的数据目录。
        if Path(config.DATA_DIR).resolve() != Path(cls._data_tmp.name).resolve():
            raise unittest.SkipTest(
                "本文件需要在独立进程中运行（VASP_WEB_DATA_DIR 已被固定）；"
                "请单独执行：python -m unittest discover -s tests "
                "-p 'test_automation_baseline.py'"
            )

        import latest_output
        import paths
        import storage
        from automation import scheduler, service, store
        from routers import jobs

        cls.config = config
        cls.latest_output = latest_output
        cls.storage = storage
        cls.scheduler = scheduler
        cls.service = service
        cls.store = store
        cls.jobs = jobs

        config.ensure_data_dirs()
        # 远端根目录以默认 path_mapping.json 为准（remote_root 优先读它，而不是 servers.json）
        cls.hpc = MockHpc(Path(cls._remote_tmp.name), remote_base=paths.remote_root("server1"))
        scheduler.start()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.scheduler.stop()
        except Exception:  # noqa: BLE001 - 清理阶段不抛
            pass
        cls._data_tmp.cleanup()
        cls._remote_tmp.cleanup()

    # ---------------------------------------------------------------- 夹具

    def setUp(self) -> None:
        from automation import ledger
        ledger.FILE.unlink(missing_ok=True)
        self.hpc.reset()
        self.hpc.write_inputs(_TASK_REL)
        self._write_db()
        # 清空调度层历史（冷却/计数/幂等指纹/规则失败数）
        for path in (self.store.HISTORY_FILE, self.store.RUNS_FILE):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in (self.store.AUTOMATION_FILE,):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _write_db(self, *, status: str = "pending", job_id=None) -> None:
        db = {
            "projects": [
                {
                    "name": _PROJECT,
                    "server": "server1",
                    "owner": "tester",
                    "status": "active",
                    "tasks": [
                        {
                            "task_id": "task_STAGE0_1",
                            "task_type": "opt",
                            "model_name": "T1",
                            "status": status,
                            "job_id": job_id,
                            "remote_dir": _TASK_REL,
                            "dir_path": "STAGE0/T1",
                            "group": None,
                            "input_state": {},
                        }
                    ],
                }
            ]
        }
        self.storage.save_db(db, backup=False)

    def _project_task(self):
        db = self.storage.load_db()
        project = db["projects"][0]
        return project, project["tasks"][0]

    def _task_status(self) -> str:
        return str(self._project_task()[1].get("status") or "")

    # ---------------------------------------------------------------- 1. dry_run

    def test_dry_run_has_no_side_effect(self) -> None:
        project, task = self._project_task()
        result = self.jobs.core_submit(project, task, dry_run=True)

        self.assertTrue(result.get("dry_run"))
        self.assertTrue(result.get("will_submit"))
        self.assertEqual(self.hpc.submit_count(), 0, "dry_run 不允许真的调用 bsub")
        self.assertEqual(self._task_status(), "pending", "dry_run 不允许改状态")

    # ---------------------------------------------------------------- 2. 正常提交

    def test_submit_records_job_id(self) -> None:
        project, task = self._project_task()
        result = self.jobs.core_submit(project, task)

        self.assertEqual(result.get("job_id"), "230001")
        self.assertEqual(self._task_status(), "queued")
        self.assertEqual(self.hpc.submit_count(), 1)

    # ---------------------------------------------------------------- 3. 重复提交

    def test_second_submit_rejected_by_business_check(self) -> None:
        project, task = self._project_task()
        self.jobs.core_submit(project, task)

        project, task = self._project_task()  # 锁外重新读：模拟第二次请求
        with self.assertRaises(self.jobs.ActionError) as ctx:
            self.jobs.core_submit(project, task)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.hpc.submit_count(), 1, "重复请求不允许产生第二个 LSF 作业")

    # ---------------------------------------------------------------- 4. bsub 被拒

    def test_bsub_rejected_keeps_status(self) -> None:
        self.hpc.install_bsub(mode="reject")
        project, task = self._project_task()

        with self.assertRaises(self.jobs.ActionError) as ctx:
            self.jobs.core_submit(project, task)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bsub 提交被集群拒绝", ctx.exception.message)
        self.assertEqual(self._task_status(), "pending")
        self.assertEqual(self.hpc.submit_count(), 1)

    # ---------------------------------------------------------------- 5. 响应丢失

    def test_bsub_success_but_response_lost(self) -> None:
        """阶段1回归：丢响应保留UNKNOWN，通过唯一标识只读对账。"""
        project, task = self._project_task()
        real_run_remote = self.jobs.ssh.run_remote

        def lost_after_submit(server, command, timeout=60, **kwargs):
            import base64
            script = base64.b64decode(self.jobs.ssh._MOCK_B64_BASH.search(command).group(1)).decode()
            result = real_run_remote(server, command, timeout=timeout)
            if '@@@BSUB' in script:
                raise TimeoutError("mock: SSH 响应在 bsub 之后丢失")
            return result

        with mock.patch.object(self.jobs.ssh, "run_remote", side_effect=lost_after_submit):
            with self.assertRaises(self.jobs.ActionError) as ctx:
                self.jobs.core_submit(project, task)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(self._task_status(), "pending", "任务科学状态不被传输异常冒充失败")
        self.assertIsNone(self._project_task()[1].get("job_id"), "对账前尚未绑定job_id")
        self.assertEqual(self.hpc.submit_count(), 1, "远端确实已有一个作业在跑")
        from automation import gateway, ledger
        record = next(iter(ledger.read()['actions'].values()))
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(gateway.reconcile(record['id'])[0]['job_id'], '230001')
        self.assertEqual(self.hpc.submit_count(), 1)

    # ---------------------------------------------------------------- 6. 幂等键

    def test_scheduler_idempotency_key_blocks_repeat(self) -> None:
        first = self.scheduler.submit(
            "task.submit", task_id="task_STAGE0_1", idempotency_key="k-stage0", wait=True
        )
        self.assertEqual(first.get("status"), "success", first)
        second = self.scheduler.submit(
            "task.submit", task_id="task_STAGE0_1", idempotency_key="k-stage0", wait=True
        )
        self.assertEqual(second.get("status"), "blocked")
        self.assertEqual(self.hpc.submit_count(), 1)

    # ---------------------------------------------------------------- 7. 失败也计数

    def test_failure_counts_towards_max_runs(self) -> None:
        """阶段1回归：失败尝试也计入上限。"""
        self.hpc.install_bsub(mode="reject")
        guard = {"cooldown_seconds": 0, "max_runs_per_task": 1}

        first = self.scheduler.submit(
            "task.submit", task_id="task_STAGE0_1", guard=guard, wait=True
        )
        second = self.scheduler.submit(
            "task.submit", task_id="task_STAGE0_1", guard=guard, wait=True
        )

        self.assertEqual(first.get("status"), "failed")
        self.assertEqual(second.get("status"), "blocked", "失败也必须受max_runs限制")
        self.assertEqual(self.hpc.submit_count(), 1)
        counts = self.store.load_history()["counts"]
        self.assertEqual(counts.get("task_STAGE0_1|task.submit"), 1, "失败尝试计数")

    # ---------------------------------------------------------------- 8. 任务锁

    def test_task_lock_blocks_concurrent_action(self) -> None:
        lock = self.scheduler._acquire_task_lock("task_STAGE0_1")
        try:
            result = self.scheduler.submit(
                "task.submit", task_id="task_STAGE0_1", wait=True
            )
        finally:
            self.scheduler._release_task_lock(lock)

        self.assertEqual(result.get("status"), "blocked")
        self.assertIn("正在执行", str(result.get("reason")))
        self.assertEqual(self.hpc.submit_count(), 0)

    # ---------------------------------------------------------------- 9. 重启恢复

    def test_restart_marks_running_runs_as_interrupted(self) -> None:
        self.store.save_runs(
            {
                "runs": [
                    {
                        "run_id": "run_stage0",
                        "action": "frac.create",
                        "task_id": "task_STAGE0_1",
                        "status": "running",
                        "started_at": "2026-10-19T10:00:00+08:00",
                    }
                ]
            }
        )
        self.service._mark_interrupted_runs()

        runs = self.store.load_runs()["runs"]
        self.assertEqual(runs[0]["status"], "interrupted")
        self.assertIn("重启", runs[0]["reason"])

    # ---------------------------------------------------------------- 10. VASP 夹具

    def test_outcar_fixtures(self) -> None:
        fixtures = Path(__file__).resolve().parent / "fixtures" / "vasp"
        converged = fixtures / "OUTCAR_opt_converged"
        unconverged = fixtures / "OUTCAR_opt_unconverged"

        self.assertTrue(converged.is_file(), "缺少 OUTCAR 夹具")
        self.assertTrue(self.latest_output.ends_normally(converged))
        self.assertFalse(self.latest_output.ends_normally(unconverged))


if __name__ == "__main__":
    unittest.main(verbosity=2)
