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
from council import keys as keys_cli
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


# ------------------------------------------------------------------ key manager
FAKE_PROV = "sk-or-v1-PROVISIONING-not-real"
KEY_INFO = {"hash": "abc123", "name": "friend", "usage": 1.5, "limit": 5, "disabled": False}


class TestKeys(unittest.TestCase):
    def run_keys(self, argv, response=None):
        """Run `python -m council.keys ARGV` against a mocked network."""
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(keys_cli, "load_api_key", return_value=FAKE_PROV),
            mock.patch.object(
                openrouter.requests, "request", return_value=response
            ) as request,
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = keys_cli.main(argv)
        return code, out.getvalue(), err.getvalue(), request

    def test_list_shows_name_hash_spend_and_limit(self):
        code, out, _, request = self.run_keys(
            ["list"], fake_response(200, {"data": [KEY_INFO]})
        )
        self.assertEqual(code, 0)
        self.assertIn("friend", out)
        self.assertIn("abc123", out)
        self.assertIn("$1.50 of $5.00", out)
        method, url = request.call_args.args
        self.assertEqual((method, url), ("GET", "https://openrouter.ai/api/v1/keys"))
        kwargs = request.call_args.kwargs
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {FAKE_PROV}")

    def test_create_sends_name_and_limit_and_shows_secret_once(self):
        body = {"data": KEY_INFO, "key": "sk-or-v1-NEW"}
        code, out, _, request = self.run_keys(
            ["create", "friend", "--limit", "5"], fake_response(201, body)
        )
        self.assertEqual(code, 0)
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertEqual(request.call_args.kwargs["json"], {"name": "friend", "limit": 5.0})
        self.assertEqual(out.count("sk-or-v1-NEW"), 1)

    def test_limit_none_removes_the_cap(self):
        _, _, _, request = self.run_keys(
            ["limit", "abc123", "none"], fake_response(200, {"data": KEY_INFO})
        )
        self.assertEqual(request.call_args.args, ("PATCH", "https://openrouter.ai/api/v1/keys/abc123"))
        self.assertEqual(request.call_args.kwargs["json"], {"limit": None})

    def test_disable_and_enable(self):
        for command, flag in (("disable", True), ("enable", False)):
            _, _, _, request = self.run_keys(
                [command, "abc123"], fake_response(200, {"data": KEY_INFO})
            )
            self.assertEqual(request.call_args.kwargs["json"], {"disabled": flag})

    def test_delete_needs_yes_and_sends_nothing_without_it(self):
        code, _, err, request = self.run_keys(["delete", "abc123"])
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        request.assert_not_called()

    def test_delete_with_yes(self):
        code, _, _, request = self.run_keys(
            ["delete", "abc123", "--yes"], fake_response(200, {"data": {"success": True}})
        )
        self.assertEqual(code, 0)
        self.assertEqual(request.call_args.args[0], "DELETE")

    def test_bad_hash_never_reaches_the_url(self):
        code, _, err, request = self.run_keys(["disable", "../../credits"])
        self.assertEqual(code, 1)
        self.assertIn("Not a key hash", err)
        request.assert_not_called()

    def test_provisioning_key_is_redacted_from_errors(self):
        body = {"error": {"code": 401, "message": f"bad key {FAKE_PROV}"}}
        code, _, err, _ = self.run_keys(["list"], fake_response(401, body))
        self.assertEqual(code, 1)
        self.assertNotIn(FAKE_PROV, err)
        self.assertIn("[REDACTED]", err)

    def test_no_provisioning_key_is_a_clean_error(self):
        err = io.StringIO()
        with (
            mock.patch.object(keys_cli, "load_api_key", return_value=None),
            mock.patch.object(openrouter.requests, "request") as request,
            redirect_stderr(err),
        ):
            self.assertEqual(keys_cli.main(["list"]), 1)
        request.assert_not_called()
        self.assertIn("OPENROUTER_PROVISIONING_KEY", err.getvalue())

    def test_chat_key_is_never_used_as_the_provisioning_key(self):
        with mock.patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "chat-key"}, clear=True
        ), mock.patch.object(cfg, "read_env_file", return_value={}):
            self.assertIsNone(cfg.load_api_key(cfg.PROVISIONING_KEY_NAMES))


if __name__ == "__main__":
    unittest.main()
