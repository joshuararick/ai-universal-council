"""Loads the roster (council.toml) and finds the API key."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "council.toml"
KEY_NAMES = ("OPENROUTER_API_KEY", "OPENROUTER_KEY")


@dataclass
class Seat:
    name: str
    model: str
    role: str = ""


@dataclass
class Config:
    roster: str
    chair: Seat
    members: list[Seat]
    timeout_seconds: int = 120
    max_tokens: int = 1000
    max_prompt_chars: int = 8000
    api_key: str | None = field(default=None, repr=False)  # never printed


class ConfigError(ValueError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    """Tiny .env reader so we don't need an extra dependency."""
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


def load_api_key() -> str | None:
    """Environment first, then project .env, then ~/.secrets/api-keys.env."""
    sources = [
        dict(os.environ),
        read_env_file(ROOT / ".env"),
        read_env_file(Path.home() / ".secrets" / "api-keys.env"),
    ]
    for source in sources:
        for name in KEY_NAMES:
            if source.get(name):
                return source[name]
    return None


def load_raw(path: Path = CONFIG_PATH) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def all_model_ids(raw: dict) -> dict[str, list[str]]:
    """{roster: [every model ID it uses, chair included]}"""
    return {
        name: [r["chair"], *(m["model"] for m in r["members"])]
        for name, r in raw["rosters"].items()
    }


def load_config(roster: str = "default", path: Path = CONFIG_PATH) -> Config:
    raw = load_raw(path)
    rosters = raw["rosters"]
    if roster not in rosters:
        raise ConfigError(
            f"Unknown roster '{roster}'. Choose from: {', '.join(rosters)}"
        )
    r = rosters[roster]
    settings = raw.get("settings", {})
    return Config(
        roster=roster,
        chair=Seat("Chair", r["chair"]),
        members=[Seat(**m) for m in r["members"]],
        timeout_seconds=settings.get("timeout_seconds", 120),
        max_tokens=settings.get("max_tokens", 1000),
        max_prompt_chars=settings.get("max_prompt_chars", 8000),
        api_key=load_api_key(),
    )
