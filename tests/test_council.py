"""Offline tests: no network access and no real API key are used.  Run: python -m unittest -v"""

import io
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import requests

from council import __main__ as cli
from council import config as cfg
from council import openrouter
from council.config import Config, Seat
from council.council import Council
from council.openrouter import OpenRouterClient, OpenRouterError

FAKE_KEY = "sk-or-v1-TESTKEY-not-real"


# ------------------------------------------------------------------ helpers
def fake_response(status, body):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = body
    return resp


def ok_body(text):
    return {"choices": [{"message": {"content": text}}]}


class FakeClient:
    """Stands in for OpenRouterClient so the Council logic runs without a network."""

    def __init__(self, broken=()):
        self.broken = set(broken)
        self.calls = []
        self.lock = threading.Lock()

    def chat(self, model, messages):
        with self.lock:
            self.calls.append((model, messages))
        if model in self.broken:
            raise OpenRouterError(f"{model}: OpenRouter error 404: model not found")
        if model == "chair/model":
            return "VERDICT: " + messages[-1]["content"][-40:]
        return f"answer from {model}"


def make_config():
    return Config(
        roster="test",
        chair=Seat("Chair", "chair/model"),
        members=[
            Seat("A", "a/model", "role a"),
            Seat("B", "b/model"),
            Seat("C", "c/model"),
        ],
        max_prompt_chars=100,
    )


# ------------------------------------------------------------------ council logic
class TestCouncil(unittest.TestCase):
    def test_every_member_answers_and_chair_sees_them(self):
        client = FakeClient()
        result = Council(make_config(), client).convene("What should we build?")
        self.assertEqual(
            [o.answer for o in result.opinions],
            ["answer from a/model", "answer from b/model", "answer from c/model"],
        )
        self.assertEqual(client.calls[-1][0], "chair/model")
        chair_prompt = client.calls[-1][1][0]["content"]
        for m in ("a/model", "b/model", "c/model"):
            self.assertIn(m, chair_prompt)
        self.assertTrue(result.verdict.startswith("VERDICT"))

    def test_role_becomes_system_message(self):
        client = FakeClient()
        Council(make_config(), client).convene("hi")
        a_msgs = next(msgs for model, msgs in client.calls if model == "a/model")
        self.assertEqual(a_msgs[0]["role"], "system")
        self.assertIn("role a", a_msgs[0]["content"])

    def test_one_broken_member_does_not_sink_the_council(self):
        result = Council(make_config(), FakeClient(broken={"b/model"})).convene("hi")
        self.assertIsNone(result.opinions[1].answer)
        self.assertIn("404", result.opinions[1].error)
        self.assertTrue(result.verdict.startswith("VERDICT"))

    def test_all_members_broken_is_a_loud_error(self):
        client = FakeClient(broken={"a/model", "b/model", "c/model"})
        with self.assertRaisesRegex(RuntimeError, "No council member"):
            Council(make_config(), client).convene("hi")

    def test_broken_chair_still_returns_member_answers(self):
        result = Council(make_config(), FakeClient(broken={"chair/model"})).convene(
            "hi"
        )
        self.assertIn("Chair failed", result.verdict)
        self.assertTrue(all(o.answer for o in result.opinions))

    def test_rejects_empty_or_oversized_questions(self):
        for q in ("", "   ", "x" * 101):
            with self.subTest(q=q[:5]), self.assertRaises(ValueError):
                Council(make_config(), FakeClient()).convene(q)


# ------------------------------------------------------------------ OpenRouter client
class TestClient(unittest.TestCase):
    def setUp(self):
        self.client = OpenRouterClient(FAKE_KEY)

    def chat_with(self, **post_kwargs):
        with (
            mock.patch.object(openrouter.requests, "post", **post_kwargs) as post,
            mock.patch.object(openrouter.time, "sleep"),
        ):
            try:
                return self.client.chat("m", [{"role": "user", "content": "p"}]), post
            except OpenRouterError as e:
                return e, post

    def test_returns_stripped_content(self):
        out, _ = self.chat_with(return_value=fake_response(200, ok_body("  hi \n")))
        self.assertEqual(out, "hi")

    def test_request_is_https_without_redirects(self):
        _, post = self.chat_with(return_value=fake_response(200, ok_body("x")))
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("https://openrouter.ai/"))
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(kwargs["json"]["max_tokens"], 1000)

    def test_key_is_redacted_from_echoed_errors(self):
        body = {"error": {"code": 401, "message": f"bad key {FAKE_KEY}"}}
        err, _ = self.chat_with(return_value=fake_response(401, body))
        self.assertIsInstance(err, OpenRouterError)
        self.assertNotIn(FAKE_KEY, str(err))
        self.assertIn("[REDACTED]", str(err))

    def test_key_is_redacted_from_exceptions(self):
        err, _ = self.chat_with(
            side_effect=requests.ConnectionError(f"failed with {FAKE_KEY}")
        )
        self.assertIsInstance(err, OpenRouterError)
        self.assertNotIn(FAKE_KEY, str(err))

    def test_out_of_credits_hint(self):
        body = {"error": {"code": 402, "message": "more credits"}}
        err, _ = self.chat_with(return_value=fake_response(402, body))
        self.assertIn("--roster free", str(err))

    def test_retries_rate_limits_then_succeeds(self):
        limited = fake_response(429, {"error": {"code": 429, "message": "slow down"}})
        out, post = self.chat_with(
            side_effect=[limited, fake_response(200, ok_body("done"))]
        )
        self.assertEqual(out, "done")
        self.assertEqual(post.call_count, 2)

    def test_gives_up_after_three_rate_limits(self):
        limited = fake_response(429, {"error": {"code": 429, "message": "slow down"}})
        err, post = self.chat_with(return_value=limited)
        self.assertIn("429", str(err))
        self.assertEqual(post.call_count, 3)

    def test_missing_key_fails_loudly_instead_of_faking(self):
        with self.assertRaisesRegex(OpenRouterError, "No OpenRouter key"):
            OpenRouterClient(None)


# ------------------------------------------------------------------ config + CLI
class TestConfig(unittest.TestCase):
    def test_rosters_are_well_formed(self):
        raw = cfg.load_raw()
        self.assertIn("default", raw["rosters"])
        for roster, ids in cfg.all_model_ids(raw).items():
            self.assertGreaterEqual(len(ids), 3, roster)
            for mid in ids:
                self.assertRegex(mid, r"^[a-z0-9-]+/[A-Za-z0-9._:-]+$", roster)

    def test_every_roster_loads_without_leaking_key(self):
        with mock.patch.object(cfg, "load_api_key", return_value=FAKE_KEY):
            for roster in cfg.load_raw()["rosters"]:
                c = cfg.load_config(roster)
                self.assertTrue(c.chair.model and c.members)
                self.assertNotIn(FAKE_KEY, repr(c))

    def test_unknown_roster_is_an_error(self):
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config("nope")

    def test_env_file_parses_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text(
                "# comment\nOPENROUTER_API_KEY=\"abc\"\nOTHER='x'\nbad line\n",
                encoding="utf-8",
            )
            self.assertEqual(
                cfg.read_env_file(path), {"OPENROUTER_API_KEY": "abc", "OTHER": "x"}
            )

    def test_missing_env_file_is_empty(self):
        self.assertEqual(cfg.read_env_file(Path("does-not-exist.env")), {})

    def test_find_missing_models(self):
        rosters = {"a": ["p/one", "p/two", "p/two"], "b": ["p/one"]}
        self.assertEqual(cli.find_missing_models(rosters, {"p/one"}), {"a": ["p/two"]})

    def test_network_failure_is_a_clean_error(self):
        err = io.StringIO()
        with (
            mock.patch.object(
                openrouter.requests, "get", side_effect=requests.ConnectionError("x")
            ),
            redirect_stderr(err),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["--check"]), 1)
        self.assertIn("can't reach OpenRouter", err.getvalue())

    def test_no_key_is_a_clean_error_and_sends_nothing(self):
        err = io.StringIO()
        with (
            mock.patch.object(cfg, "load_api_key", return_value=None),
            mock.patch.object(openrouter.requests, "post") as post,
            redirect_stderr(err),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["hi"]), 1)
        post.assert_not_called()
        self.assertTrue(re.search("No OpenRouter key", err.getvalue()))


# ------------------------------------------------------------------ scheduled (cron) runs
class TestScheduledRun(unittest.TestCase):
    def run_cli(self, env, argv=()):
        out, err = io.StringIO(), io.StringIO()
        seen = {}

        def fake_convene(council, question):
            seen["question"] = question
            return mock.Mock(opinions=[], verdict="ok")

        with (
            mock.patch.dict("os.environ", env, clear=False),
            mock.patch.object(cfg, "load_api_key", return_value=FAKE_KEY),
            mock.patch.object(cli.Council, "convene", fake_convene),
            mock.patch.object(cli.sys.stdin, "isatty", return_value=False),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli.main(list(argv))
        return code, seen.get("question"), err.getvalue()

    def test_question_comes_from_env(self):
        code, question, _ = self.run_cli({"COUNCIL_QUESTION": "daily report"})
        self.assertEqual((code, question), (0, "daily report"))

    def test_argument_beats_env(self):
        _, question, _ = self.run_cli({"COUNCIL_QUESTION": "env q"}, ["arg", "q"])
        self.assertEqual(question, "arg q")

    def test_no_question_without_keyboard_fails_instead_of_hanging(self):
        with mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
            code, question, err = self.run_cli({"COUNCIL_QUESTION": ""})
        self.assertEqual(code, 1)
        self.assertIsNone(question)
        self.assertIn("COUNCIL_QUESTION", err)


if __name__ == "__main__":
    unittest.main()
