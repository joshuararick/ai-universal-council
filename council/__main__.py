"""Command line.

python -m council "your question"            ask the default roster
python -m council --roster free "question"   free models, no credits needed
python -m council --check                    verify every model ID (no key, $0)
"""

import argparse
import os
import sys

import requests

from .config import ConfigError, all_model_ids, load_config, load_raw
from .council import Council
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


def check() -> int:
    raw = load_raw()
    available = list_models()
    rosters = all_model_ids(raw)
    missing = find_missing_models(rosters, available)
    for roster, r in raw["rosters"].items():
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
    print(
        "\nAll model IDs are live."
        if not missing
        else "\nSome model IDs are gone - update council.toml."
    )
    return 1 if missing else 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="council", description="Ask the AI Universal Council."
    )
    p.add_argument("question", nargs="*", help="What to ask")
    p.add_argument(
        "--roster",
        default=os.getenv("COUNCIL_ROSTER", "default"),
        help="Roster from council.toml (default, free)",
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
        config = load_config(args.roster)
        client = OpenRouterClient(
            config.api_key, config.timeout_seconds, config.max_tokens
        )
        # Scheduled runs (e.g. Render cron) have no keyboard: take the question from the env.
        question = " ".join(args.question) or os.getenv("COUNCIL_QUESTION", "")
        if not question.strip():
            if not sys.stdin.isatty():
                raise ValueError("No question given. Pass one as an argument or set COUNCIL_QUESTION.")
            question = input("Ask the Council: ")
        names = ", ".join(s.name for s in config.members)
        print(f"Convening the {config.roster} council: {names}...\n", file=sys.stderr)
        result = Council(config, client).convene(question)
    except requests.RequestException as e:
        print(
            f"ERROR: can't reach OpenRouter ({type(e).__name__}). Check your internet connection.",
            file=sys.stderr,
        )
        return 1
    except (ConfigError, OpenRouterError, ValueError, RuntimeError) as e:
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
