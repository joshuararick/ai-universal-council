"""Command line.

python -m council "your question"            ask the default roster
python -m council --roster free "question"   free models, no credits needed
python -m council --roster local "question"  models on this PC via Ollama, no key at all
python -m council --roster local --pull      download the local models now (else: on first question)
python -m council --check                    verify every model ID (no key, $0)

With no --roster and no OpenRouter key anywhere, the local roster is used.
"""

import argparse
import os
import sys

import requests

from . import ollama
from .config import (
    PROVIDERS,
    ConfigError,
    all_model_ids,
    load_api_key,
    load_config,
    load_raw,
    provider_of,
)
from .council import Council, validate_question
from .openrouter import OpenRouterClient, OpenRouterError, list_models


def find_missing_models(
    rosters: dict[str, list[str]], available: set[str]
) -> dict[str, list[str]]:
    """{roster: [model IDs OpenRouter doesn't offer]} for rosters with gaps."""
    missing = {}
    for roster, ids in rosters.items():
        gone = [m for m in dict.fromkeys(ids) if m not in available]
        if gone:
            missing[roster] = gone
    return missing


def check_local(raw: dict) -> None:
    """Local rosters: report which models are downloaded. Never fails the check."""
    local = {n: r for n, r in raw["rosters"].items() if provider_of(r) == "ollama"}
    if not local:
        return
    have = ollama.list_models() if ollama.is_running() else None
    for roster, r in local.items():
        seats = [("Chair", r["chair"]), *((m["name"], m["model"]) for m in r["members"])]
        for name, mid in seats:
            status = "?" if have is None else "OK" if mid in have else "NOT PULLED"
            print(f"[{roster}] {status:<7} {name:<15} {mid}")
        if have is None:
            print(f"          (Ollama not running here, skipped. Pull with: --roster {roster} --pull)")


def check() -> int:
    raw = load_raw()
    for roster, r in raw["rosters"].items():  # a typo here must fail CI, not slip past both checks
        if provider_of(r) not in PROVIDERS:
            raise ConfigError(
                f"Roster '{roster}' has unknown provider '{provider_of(r)}'. Use: {', '.join(PROVIDERS)}"
            )
    available = list_models()
    remote = {n: r for n, r in raw["rosters"].items() if provider_of(r) == "openrouter"}
    rosters = all_model_ids({"rosters": remote})
    missing = find_missing_models(rosters, available)
    for roster, r in remote.items():
        seats = [
            ("Chair", r["chair"]),
            *((m["name"], m["model"]) for m in r["members"]),
        ]
        for name, mid in seats:
            status = "MISSING" if mid in missing.get(roster, []) else "OK"
            print(f"[{roster}] {status:<7} {name:<15} {mid}")
            if status == "MISSING":
                vendor = mid.split("/")[0] + "/"
                options = sorted(m for m in available if m.startswith(vendor))[-6:]
                print(
                    f"          try one of: {', '.join(options) or '(none from this vendor)'}"
                )
    check_local(raw)
    print(
        "\nAll model IDs are live."
        if not missing
        else "\nSome model IDs are gone - update council.toml."
    )
    return 1 if missing else 0


def pick_roster(requested: str | None) -> str:
    """No roster asked for and no OpenRouter key anywhere -> run locally, no key needed."""
    if requested:
        return requested
    if load_api_key():
        return "default"
    print("No OpenRouter key found - using the local roster (Ollama, no key).", file=sys.stderr)
    return "local"


def make_client(config):
    if config.provider == "ollama":
        ollama.ensure_running()
        models = [config.chair.model, *(s.model for s in config.members)]
        if set(models) - ollama.list_models():
            print("Downloading local models (one time, a few GB)...", file=sys.stderr)
            ollama.pull_missing(models)
        return ollama.OllamaClient(
            config.timeout_seconds, config.max_tokens, unload_after=config.max_parallel == 1
        )
    return OpenRouterClient(config.api_key, config.timeout_seconds, config.max_tokens)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="council", description="Ask the AI Universal Council."
    )
    p.add_argument("question", nargs="*", help="What to ask")
    p.add_argument(
        "--roster",
        default=os.getenv("COUNCIL_ROSTER"),
        help="Roster from council.toml (default, free, local)",
    )
    p.add_argument(
        "--pull",
        action="store_true",
        help="Download the roster's local models (local rosters only)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Verify every model ID exists on OpenRouter (no key needed)",
    )
    p.add_argument(
        "--verdict-only", action="store_true", help="Hide individual member answers"
    )
    args = p.parse_args(argv)

    try:
        if args.check:
            return check()
        config = load_config(pick_roster(args.roster))
        if args.pull:
            if config.provider != "ollama":
                raise ConfigError(f"--pull is for local rosters; '{config.roster}' runs on OpenRouter.")
            make_client(config)  # starts Ollama and downloads anything missing
            print("Local models ready.")
            return 0
        # Check the question first: a bad one must not trigger a multi-GB download.
        question = validate_question(
            " ".join(args.question) or input("Ask the Council: "), config.max_prompt_chars
        )
        client = make_client(config)
        names = ", ".join(s.name for s in config.members)
        print(f"Convening the {config.roster} council: {names}...\n", file=sys.stderr)
        result = Council(config, client).convene(question)
    except requests.RequestException as e:
        print(
            f"ERROR: can't reach OpenRouter or the local Ollama server ({type(e).__name__}). "
            "Check your internet connection, or that Ollama is running.",
            file=sys.stderr,
        )
        return 1
    except (ConfigError, OpenRouterError, ollama.OllamaError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not args.verdict_only:
        for o in result.opinions:
            print(f"\n=== {o.seat.name} ({o.seat.model}) ===")
            print(o.answer if o.answer else f"[failed] {o.error}")
    print("\n" + "=" * 60 + "\nCOUNCIL VERDICT\n" + "=" * 60)
    print(result.verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
