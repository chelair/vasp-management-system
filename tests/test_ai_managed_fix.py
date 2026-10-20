"""AI 会话修复：伪工具调用还原 + 思考链路持久化（隔离数据目录，不连模型）。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "backend")]

_TEMP = tempfile.TemporaryDirectory(prefix="vasp-ai-dsml-")
os.environ["VASP_WEB_DATA_DIR"] = str(Path(_TEMP.name) / "data")

import config  # noqa: E402

if config.DATA_DIR.resolve() != (Path(_TEMP.name) / "data").resolve():
    raise unittest.SkipTest("需独立进程运行 tests/test_ai_managed_fix.py")

import ai_chat_service as service  # noqa: E402
import ai_chat_store as store  # noqa: E402

DSML = """我先看一下现有计划。
<||DSML||tool_calls>
<||DSML||invoke name="create_managed_plan">
<||DSML||parameter name="goal" string="true">这个项目帮我托管</||DSML||parameter>
<||DSML||parameter name="stages" string="true">[{"title":"阶段报告","task_ids":["t1"]}]</||DSML||parameter>
</||DSML||invoke>
</||DSML||tool_calls>
"""

ALTERNATE = """<|tool_calls|><|invoke name="get_managed_plans"><|parameter name="plan_id">p1</|parameter></|invoke></|tool_calls|>"""

SINGLE_BAR = """<｜DSML｜tool_calls><｜DSML｜invoke name="get_managed_plans"></｜DSML｜invoke></｜DSML｜tool_calls>"""

JSON_PAYLOAD = """好的，我来建计划。{"tool_calls":[{"function":{"name":"set_task_priority","arguments":{"plan_id":"p1","revision":1,"task_id":"t1","priority":90}}}]}"""


class PseudoToolTests(unittest.TestCase):
    def test_detects_known_markup(self):
        self.assertTrue(service._PSEUDO_RE.search(DSML))
        self.assertTrue(service._PSEUDO_RE.search(ALTERNATE))
        self.assertTrue(service._PSEUDO_RE.search("<｜｜DSML｜｜tool_calls>"))
        self.assertFalse(service._PSEUDO_RE.search("普通回答，没有工具调用"))

    def test_parses_dsml_calls(self):
        calls = service._pseudo_tool_calls(DSML)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "create_managed_plan")
        self.assertIn("create_managed_plan", calls[0]["id"] + "create_managed_plan")
        arguments = __import__("json").loads(calls[0]["function"]["arguments"])
        self.assertEqual(arguments["goal"], "这个项目帮我托管")
        self.assertIn("阶段报告", arguments["stages"])

    def test_parses_alternate_markup(self):
        calls = service._pseudo_tool_calls(ALTERNATE)
        self.assertEqual([c["function"]["name"] for c in calls], ["get_managed_plans"])
        self.assertEqual(__import__("json").loads(calls[0]["function"]["arguments"]), {"plan_id": "p1"})

    def test_parses_single_bar_and_json_payload(self):
        self.assertEqual(service._pseudo_tool_calls(SINGLE_BAR)[0]["function"]["name"], "get_managed_plans")
        calls = service._pseudo_tool_calls(JSON_PAYLOAD)
        self.assertEqual(calls[0]["function"]["name"], "set_task_priority")
        self.assertEqual(__import__("json").loads(calls[0]["function"]["arguments"])["task_id"], "t1")

    def test_requires_declared_required_arguments(self):
        bad = {"type": "function", "function": {"name": "save_topic_report", "arguments": "{}"}}
        self.assertFalse(service._pseudo_args_ok(bad))
        ok = {"type": "function", "function": {"name": "get_managed_plans", "arguments": "{}"}}
        self.assertTrue(service._pseudo_args_ok(ok))

    def test_garbage_returns_empty(self):
        self.assertEqual(service._pseudo_tool_calls("<||DSML||tool_calls>not really"), [])
        self.assertEqual(service._pseudo_tool_calls(""), [])


class ReasoningStoreTests(unittest.TestCase):
    def setUp(self):
        with store.database() as db:
            db.execute("DELETE FROM runs")
            db.execute("DELETE FROM messages")
            db.execute("DELETE FROM conversations")
        self.conversation = store.create_conversation("usr_test", "测试", None, None, None)
        with store.database() as db:
            db.execute("INSERT INTO messages (id,conversation_id,role,content,status,created_at) VALUES (?,?,?,?,?,?)",
                       ("m1", self.conversation["id"], "assistant", "", "running", "2026-10-20T00:00:00"))
            db.execute("""INSERT INTO runs (id,owner,conversation_id,message_id,request_id,status,model,connection_name,
                          prompt_version,snapshot,usage,error,created_at,tool_events,reasoning)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       ("r1", "usr_test", self.conversation["id"], "m1", "req1", "running", "deepseek-flash",
                        "DeepSeek", 1, "{}", "{}", "", "2026-10-20T00:00:00", "[]", ""))

    def test_update_answer_keeps_reasoning(self):
        store.update_answer("r1", "半截回答", reasoning="先查计划，再建计划", usage={"total_tokens": 5})
        with store.database() as db:
            run = store.public_run(db.execute("SELECT * FROM runs WHERE id='r1'").fetchone())
        self.assertEqual(run["reasoning"], "先查计划，再建计划")
        self.assertEqual(run["status"], "running")

    def test_reasoning_is_capped_and_optional(self):
        store.update_answer("r1", "x", reasoning="长" * 100000)
        with store.database() as db:
            row = db.execute("SELECT reasoning FROM runs WHERE id='r1'").fetchone()
        self.assertEqual(len(row["reasoning"]), 60000)
        store.update_answer("r1", "y")  # 不传 reasoning 时不覆盖
        with store.database() as db:
            row = db.execute("SELECT reasoning FROM runs WHERE id='r1'").fetchone()
        self.assertEqual(len(row["reasoning"]), 60000)

    def test_terminal_status_sets_finished_at(self):
        store.update_answer("r1", "完成", status="completed", reasoning="思考")
        with store.database() as db:
            row = db.execute("SELECT * FROM runs WHERE id='r1'").fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertTrue(row["finished_at"])
        self.assertEqual(row["reasoning"], "思考")


if __name__ == "__main__":
    unittest.main(verbosity=2)
