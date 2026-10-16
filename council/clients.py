"""Picks the roster and builds the right model client (shared by the CLI and the web app)."""

import sys

from . import config as cfg
from . import ollama
from .openrouter import OpenRouterClient


def pick_roster(requested: str | None) -> str:
    """No roster asked for and no OpenRouter key anywhere -> run locally, no key needed."""
    if requested:
        return requested
    if cfg.load_api_key():
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
