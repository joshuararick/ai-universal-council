"""Manage OpenRouter API keys (yours and other people's) with a provisioning key.

python -m council.keys list                       every key: name, hash, spend, limit
python -m council.keys create "friend" --limit 5  new key with a $5 cap (secret shown once)
python -m council.keys limit HASH 10              change a cap ("none" removes it)
python -m council.keys disable HASH               switch a key off (enable turns it back on)
python -m council.keys delete HASH --yes          revoke for good
"""

import argparse
import sys

from .config import PROVISIONING_KEY_NAMES, load_api_key
from .openrouter import KeyManager, OpenRouterError


def money(value) -> str:
    return "no limit" if value is None else f"${value:,.2f}"


def show(key: dict) -> str:
    status = "disabled" if key.get("disabled") else "active"
    spent = f"{money(key.get('usage', 0))} of {money(key.get('limit'))}"
    return f"{key.get('name', '?'):<20} {key['hash']}  {spent:<24} {status}"


def parse_limit(text: str) -> float | None:
    if text.lower() == "none":
        return None
    value = float(text)
    if value < 0:
        raise ValueError("a limit can't be negative")
    return value


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="council.keys", description="Manage OpenRouter API keys."
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show every key")
    c = sub.add_parser("create", help="Make a new key")
    c.add_argument("name")
    c.add_argument("--limit", type=parse_limit, help="Spending cap in USD")
    lim = sub.add_parser("limit", help="Change a key's spending cap")
    lim.add_argument("hash")
    lim.add_argument("usd", type=parse_limit, help='USD, or "none"')
    for name in ("disable", "enable"):
        sub.add_parser(name, help=f"{name.title()} a key").add_argument("hash")
    d = sub.add_parser("delete", help="Revoke a key permanently")
    d.add_argument("hash")
    d.add_argument("--yes", action="store_true", help="Confirm: this can't be undone")
    args = p.parse_args(argv)

    try:
        keys = KeyManager(load_api_key(PROVISIONING_KEY_NAMES))
        if args.command == "list":
            found = keys.list()
            for key in found:
                print(show(key))
            print(f"\n{len(found)} key(s).")
        elif args.command == "create":
            info, secret = keys.create(args.name, args.limit)
            print(show(info))
            print(f"\nSecret (shown ONCE, store it now): {secret}")
        elif args.command == "limit":
            print(show(keys.update(args.hash, limit=args.usd)))
        elif args.command in ("disable", "enable"):
            print(show(keys.update(args.hash, disabled=args.command == "disable")))
        elif args.command == "delete":
            if not args.yes:
                print("Refusing to delete without --yes (it can't be undone).", file=sys.stderr)
                return 1
            keys.delete(args.hash)
            print(f"Deleted {args.hash}.")
    except OpenRouterError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
