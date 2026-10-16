"""Offline tests: no network access and no real API key are used.  Run: python -m unittest -v"""

import io
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import requests

from council import __main__ as cli
from council import config as cfg
from council import ollama, openrouter
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
        self.assertIn("local", raw["rosters"])
        id_format = {
            "openrouter": r"^[a-z0-9-]+/[A-Za-z0-9._:-]+$",  # vendor/model
            "ollama": r"^[a-z0-9._-]+(:[A-Za-z0-9._-]+)?$",  # model:tag
        }
        for roster, ids in cfg.all_model_ids(raw).items():
            provider = cfg.provider_of(raw["rosters"][roster])
            self.assertIn(provider, cfg.PROVIDERS, roster)
            self.assertGreaterEqual(len(ids), 3, roster)
            for mid in ids:
                self.assertRegex(mid, id_format[provider], roster)

    def test_local_roster_needs_no_key(self):
        with mock.patch.object(cfg, "load_api_key", return_value=FAKE_KEY):
            c = cfg.load_config("local")
        self.assertEqual(c.provider, "ollama")
        self.assertIsNone(c.api_key)  # the OpenRouter key never goes near localhost
        self.assertEqual(c.max_parallel, 1)
        self.assertGreater(c.timeout_seconds, 120)

    def test_unknown_provider_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            path.write_text(
                '[rosters.x]\nprovider = "nope"\nchair = "a"\n'
                '[[rosters.x.members]]\nname = "A"\nmodel = "a"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(cfg.ConfigError, "unknown provider"):
                cfg.load_config("x", path)

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


    def test_check_ignores_local_rosters_when_ollama_is_absent(self):
        live = {m for r, ids in cfg.all_model_ids(cfg.load_raw()).items() if r != "local" for m in ids}
        out = io.StringIO()
        with (
            mock.patch.object(cli, "list_models", return_value=live),
            mock.patch.object(ollama, "is_running", return_value=False),
            redirect_stdout(out),
        ):
            self.assertEqual(cli.main(["--check"]), 0)
        self.assertIn("Ollama not running", out.getvalue())

    def test_check_rejects_unknown_provider(self):
        raw = {"rosters": {"x": {"provider": "olama", "chair": "a", "members": []}}}
        err = io.StringIO()
        with (
            mock.patch.object(cli, "load_raw", return_value=raw),
            mock.patch.object(cli, "list_models") as remote,
            redirect_stderr(err),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["--check"]), 1)
        remote.assert_not_called()
        self.assertIn("unknown provider", err.getvalue())

    def test_bad_question_is_rejected_before_any_download(self):
        with (
            mock.patch.object(cli, "load_api_key", return_value=None),
            mock.patch.object(cli, "make_client") as make,
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["--roster", "local", "   "]), 1)
        make.assert_not_called()

    def test_no_key_and_no_roster_falls_back_to_local(self):
        with (
            mock.patch.object(cli, "load_api_key", return_value=None),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(cli.pick_roster(None), "local")
        with mock.patch.object(cli, "load_api_key", return_value=FAKE_KEY):
            self.assertEqual(cli.pick_roster(None), "default")
        self.assertEqual(cli.pick_roster("free"), "free")  # an explicit choice always wins


# ------------------------------------------------------------------ Ollama (local) client
class TestOllama(unittest.TestCase):
    unload = False

    def chat_with(self, **post_kwargs):
        client = ollama.OllamaClient(timeout=5, max_tokens=50, unload_after=self.unload)
        with mock.patch.object(ollama._http, "post", **post_kwargs) as post:
            try:
                return client.chat("m:1b", [{"role": "user", "content": "p"}]), post
            except ollama.OllamaError as e:
                return e, post

    def test_talks_only_to_localhost_without_a_key(self):
        out, post = self.chat_with(
            return_value=fake_response(200, {"message": {"content": " hi "}})
        )
        self.assertEqual(out, "hi")
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("http://127.0.0.1:11434/"))
        self.assertNotIn("headers", kwargs)
        self.assertIs(kwargs["json"]["stream"], False)
        self.assertEqual(kwargs["json"]["options"]["num_predict"], 50)

    def test_never_uses_proxy_settings_for_localhost(self):
        self.assertIs(ollama._http.trust_env, False)

    def test_unload_after_answering_when_asked(self):
        self.unload = True
        _, post = self.chat_with(return_value=fake_response(200, {"message": {"content": "x"}}))
        self.assertEqual(post.call_args.kwargs["json"]["keep_alive"], 0)
        self.unload = False
        _, post = self.chat_with(return_value=fake_response(200, {"message": {"content": "x"}}))
        self.assertNotIn("keep_alive", post.call_args.kwargs["json"])

    def test_pull_has_a_finite_stall_timeout(self):
        resp = mock.MagicMock(status_code=200)
        resp.__enter__.return_value = resp
        resp.iter_lines.return_value = [b'{"status":"success"}']
        with mock.patch.object(ollama._http, "post", return_value=resp) as post:
            ollama.pull("m:1b", out=io.StringIO())
        connect, read = post.call_args.kwargs["timeout"]
        self.assertIsNotNone(read)

    def test_strips_thinking(self):
        body = {"message": {"content": "<think>\nhmm\n</think>\n\nAnswer."}}
        out, _ = self.chat_with(return_value=fake_response(200, body))
        self.assertEqual(out, "Answer.")

    def test_missing_model_says_how_to_pull(self):
        body = {"error": "model 'm:1b' not found"}
        err, _ = self.chat_with(return_value=fake_response(404, body))
        self.assertIsInstance(err, ollama.OllamaError)
        self.assertIn("--pull", str(err))

    def test_connection_failure_is_a_seat_error(self):
        err, _ = self.chat_with(side_effect=requests.ConnectionError("refused"))
        self.assertIsInstance(err, ollama.OllamaError)

    def test_not_installed_says_how_to_install(self):
        with (
            mock.patch.object(ollama, "is_running", return_value=False),
            mock.patch.object(ollama.shutil, "which", return_value=None),
            self.assertRaisesRegex(ollama.OllamaError, "ollama.com"),
        ):
            ollama.ensure_running()

    def test_starts_ollama_when_installed_but_stopped(self):
        with (
            mock.patch.object(ollama, "is_running", side_effect=[False, False, True]),
            mock.patch.object(ollama.shutil, "which", return_value="/usr/bin/ollama"),
            mock.patch.object(ollama.subprocess, "Popen") as popen,
            mock.patch.object(ollama.time, "sleep"),
        ):
            ollama.ensure_running()
        self.assertEqual(popen.call_args[0][0], ["/usr/bin/ollama", "serve"])

    def test_pull_missing_skips_models_already_here(self):
        with (
            mock.patch.object(ollama, "list_models", return_value={"a:1b"}),
            mock.patch.object(ollama, "pull") as pull,
        ):
            pulled = ollama.pull_missing(["a:1b", "b:2b", "b:2b"])
        self.assertEqual(pulled, ["b:2b"])
        pull.assert_called_once()

    def test_max_parallel_caps_the_fan_out(self):
        config = make_config()
        config.max_parallel = 1
        with mock.patch("council.council.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as pool:
            Council(config, FakeClient()).convene("hi")
        self.assertEqual(pool.call_args.kwargs["max_workers"], 1)


if __name__ == "__main__":
    unittest.main()
