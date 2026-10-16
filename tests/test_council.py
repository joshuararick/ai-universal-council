"""Offline tests: no network access and no real API key are used."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import council  # noqa: E402

FAKE_KEY = "sk-or-v1-TESTKEY-not-real"


def fake_response(status, body):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = body
    return resp


def ok_body(text):
    return {"choices": [{"message": {"content": text}}]}


class CouncilTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(council, "load_api_key", return_value=FAKE_KEY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.council = council.UniversalCouncil("default")


class TestQueryModel(CouncilTestCase):
    def test_returns_stripped_content(self):
        with mock.patch.object(council.requests, "post", return_value=fake_response(200, ok_body("  hi \n"))):
            self.assertEqual(self.council.query_model("m", "p"), "hi")

    def test_request_is_https_without_redirects(self):
        with mock.patch.object(council.requests, "post", return_value=fake_response(200, ok_body("x"))) as post:
            self.council.query_model("m", "p")
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("https://openrouter.ai/"))
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {FAKE_KEY}")

    def test_key_is_redacted_from_echoed_errors(self):
        body = {"error": {"code": 401, "message": f"bad key {FAKE_KEY}"}}
        with mock.patch.object(council.requests, "post", return_value=fake_response(401, body)):
            out = self.council.query_model("m", "p")
        self.assertNotIn(FAKE_KEY, out)
        self.assertIn("[REDACTED]", out)

    def test_key_is_redacted_from_exceptions(self):
        err = council.requests.ConnectionError(f"failed with {FAKE_KEY}")
        with mock.patch.object(council.requests, "post", side_effect=err):
            out = self.council.query_model("m", "p")
        self.assertNotIn(FAKE_KEY, out)

    def test_out_of_credits_hint(self):
        body = {"error": {"code": 402, "message": "more credits"}}
        with mock.patch.object(council.requests, "post", return_value=fake_response(402, body)):
            self.assertIn("--roster free", self.council.query_model("m", "p"))

    def test_retries_rate_limits_then_succeeds(self):
        responses = [fake_response(429, {"error": {"code": 429, "message": "slow down"}}),
                     fake_response(200, ok_body("done"))]
        with mock.patch.object(council.requests, "post", side_effect=responses) as post, \
                mock.patch.object(council.time, "sleep"):
            self.assertEqual(self.council.query_model("m", "p"), "done")
        self.assertEqual(post.call_count, 2)

    def test_gives_up_after_three_rate_limits(self):
        limited = fake_response(429, {"error": {"code": 429, "message": "slow down"}})
        with mock.patch.object(council.requests, "post", return_value=limited) as post, \
                mock.patch.object(council.time, "sleep"):
            self.assertIn("429", self.council.query_model("m", "p"))
        self.assertEqual(post.call_count, 3)

    def test_no_key_means_no_request(self):
        self.council.api_key = None
        with mock.patch.object(council.requests, "post") as post:
            self.assertIn("No OpenRouter key", self.council.query_model("m", "p"))
        post.assert_not_called()


class TestConfig(unittest.TestCase):
    def test_rosters_are_well_formed(self):
        config = council.load_config()
        self.assertIn("default", config["rosters"])
        for roster, models in config["rosters"].items():
            self.assertTrue(models, roster)
            for name, mid in models.items():
                self.assertRegex(mid, r"^[a-z0-9-]+/[A-Za-z0-9._:-]+$", f"{roster}/{name}")

    def test_unknown_roster_exits(self):
        with mock.patch.object(council, "load_api_key", return_value=None):
            with self.assertRaises(SystemExit):
                council.UniversalCouncil("nope")

    def test_find_missing_models(self):
        config = {"rosters": {"a": {"x": "p/one", "y": "p/two"}, "b": {"z": "p/one"}}}
        self.assertEqual(council.find_missing_models(config, {"p/one"}), {"a": ["p/two"]})


class TestEnvFile(unittest.TestCase):
    def test_parses_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text('# comment\nOPENROUTER_API_KEY="abc"\nOTHER=\'x\'\nbad line\n', encoding="utf-8")
            self.assertEqual(council._read_env_file(path), {"OPENROUTER_API_KEY": "abc", "OTHER": "x"})

    def test_missing_file_is_empty(self):
        self.assertEqual(council._read_env_file(Path("does-not-exist.env")), {})


if __name__ == "__main__":
    unittest.main()
