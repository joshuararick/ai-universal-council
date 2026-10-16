import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "council.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
KEY_NAMES = ("OPENROUTER_API_KEY", "OPENROUTER_KEY")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _read_env_file(path: Path) -> Dict[str, str]:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def load_api_key() -> Optional[str]:
    """Environment first, then project .env, then ~/.secrets/api-keys.env."""
    sources = [dict(os.environ), _read_env_file(ROOT / ".env"),
               _read_env_file(Path.home() / ".secrets" / "api-keys.env")]
    for source in sources:
        for name in KEY_NAMES:
            if source.get(name):
                return source[name]
    return None


class UniversalCouncil:
    def __init__(self, roster: str = "default"):
        config = load_config()
        if roster not in config["rosters"]:
            raise SystemExit(f"Unknown roster '{roster}'. Choose from: {', '.join(config['rosters'])}")
        self.models: Dict[str, str] = config["rosters"][roster]
        self.max_tokens = config.get("max_tokens", 1000)
        self.timeout = config.get("timeout_seconds", 120)
        self.api_key = load_api_key()

    def query_model(self, model_id: str, prompt: str) -> str:
        result = self._query(model_id, prompt)
        # Never let the key leak into output, even via an echoed error payload.
        return result.replace(self.api_key, "[REDACTED]") if self.api_key else result

    def _query(self, model_id: str, prompt: str) -> str:
        if not self.api_key:
            return "[SIMULATION] No OpenRouter key found (env, .env, or ~/.secrets/api-keys.env)."

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:3080",
            "X-Title": "Joshs Command Center",
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
        }

        for attempt in range(3):
            try:
                # No redirects: a redirect must never carry the Authorization header elsewhere.
                response = requests.post(API_URL, json=payload, headers=headers,
                                         timeout=self.timeout, allow_redirects=False)
                data = response.json()
            except (requests.RequestException, ValueError) as e:
                return f"Request failed: {e}"
            # Free models are often rate-limited upstream; back off briefly and retry.
            if response.status_code != 429 or attempt == 2:
                break
            time.sleep(5 * (attempt + 1))

        if "error" in data:
            err = data["error"]
            hint = " (out of credits: add credits or use --roster free)" if err.get("code") == 402 else ""
            return f"OpenRouter error {err.get('code')}: {err.get('message')}{hint}"
        try:
            return (data["choices"][0]["message"]["content"] or "").strip() or "(empty response)"
        except (KeyError, IndexError, TypeError):
            return f"Unexpected API response: {data}"

    def convene(self, prompt: str) -> Dict[str, str]:
        print(f"[Council] Convening AI Universal Council for directive: '{prompt}'\n" + "-" * 50)
        for name, model_id in self.models.items():
            print(f"-> Consulting {name} ({model_id})...")
        with ThreadPoolExecutor(max_workers=len(self.models)) as pool:
            futures = {name: pool.submit(self.query_model, mid, prompt) for name, mid in self.models.items()}
            return {name: f.result() for name, f in futures.items()}


def find_missing_models(config: dict, available: set) -> Dict[str, list]:
    """Return {roster: [model IDs not offered by OpenRouter]} for rosters with gaps."""
    missing = {}
    for roster, models in config["rosters"].items():
        gone = [mid for mid in models.values() if mid not in available]
        if gone:
            missing[roster] = gone
    return missing


def check_models() -> int:
    """Validate every configured model ID against OpenRouter's public list (no key sent, no credits used)."""
    config = load_config()
    response = requests.get(MODELS_URL, timeout=30, allow_redirects=False)
    response.raise_for_status()
    available = {m["id"] for m in response.json()["data"]}
    missing = find_missing_models(config, available)
    for roster, models in config["rosters"].items():
        for name, mid in models.items():
            status = "MISSING" if mid in missing.get(roster, []) else "ok"
            print(f"[{roster}] {name}: {mid} ... {status}")
    print("All model IDs are live." if not missing else "Some model IDs are not available on OpenRouter.")
    return 1 if missing else 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Ask every council model the same directive.")
    parser.add_argument("directive", nargs="*", help="Prompt to send (default: readiness check)")
    parser.add_argument("--roster", default=os.getenv("COUNCIL_ROSTER", "default"),
                        help="Roster from config/council.json (default, free)")
    parser.add_argument("--check", action="store_true",
                        help="Verify every configured model ID exists on OpenRouter, then exit")
    args = parser.parse_args()

    if args.check:
        sys.exit(check_models())

    directive = " ".join(args.directive) or "Assess system baseline and provide operational readiness report."
    council = UniversalCouncil(args.roster)
    responses = council.convene(directive)
    print("\n=== COUNCIL RESPONSES ===")
    for name, answer in responses.items():
        print(f"\n[{name} - {council.models[name]}]:\n{answer}")


if __name__ == "__main__":
    main()
