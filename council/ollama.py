"""Local models through Ollama (https://ollama.com): no key, no account, no bill.

Talks only to the Ollama server on this machine (localhost). Starts it if it's
installed but not running, and downloads models the roster needs.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

import requests

API = "http://127.0.0.1:11434/api"
INSTALL_HINT = "Install Ollama from https://ollama.com/download (or run .\\setup.ps1 -Local)."
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)  # some models show their scratch work


class OllamaError(RuntimeError):
    pass


def is_running(timeout: float = 2) -> bool:
    try:
        return requests.get(f"{API}/version", timeout=timeout).ok
    except requests.RequestException:
        return False


def _windows_install_path() -> str | None:
    """Where the Windows installer puts it, for shells opened before PATH was updated."""
    path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return path if sys.platform == "win32" and os.path.isfile(path) else None


def ensure_running(wait_seconds: int = 20) -> None:
    """Start `ollama serve` in the background if Ollama is installed but not up."""
    if is_running():
        return
    exe = shutil.which("ollama") or _windows_install_path()
    if not exe:
        raise OllamaError(f"Ollama isn't installed. {INSTALL_HINT}")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )
    for _ in range(wait_seconds * 2):
        if is_running():
            return
        time.sleep(0.5)
    raise OllamaError("Started Ollama but it didn't answer. Try running `ollama serve` yourself.")


def list_models(timeout: int = 10) -> set[str]:
    """Models already downloaded on this machine."""
    resp = requests.get(f"{API}/tags", timeout=timeout)
    resp.raise_for_status()
    names = {m["name"] for m in resp.json().get("models", [])}
    # "llama3.2" and "llama3.2:latest" are the same model.
    return names | {n.removesuffix(":latest") for n in names}


def pull(model: str, out=sys.stderr) -> None:
    """Download one model, showing progress. Safe to re-run: finished files are skipped."""
    with requests.post(
        f"{API}/pull", json={"model": model}, stream=True, timeout=(10, None)
    ) as resp:
        if resp.status_code != 200:
            raise OllamaError(f"{model}: download failed ({resp.status_code}) {resp.text[:200]}")
        last = ""
        for line in resp.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if "error" in msg:
                raise OllamaError(f"{model}: {msg['error']}")
            status = msg.get("status", "")
            if msg.get("total"):
                status = f"{status} {100 * msg.get('completed', 0) // msg['total']}%"
            if status != last:
                print(f"\r  {model}: {status:<40}", end="", file=out, flush=True)
                last = status
        print(file=out)


def pull_missing(models: list[str], out=sys.stderr) -> list[str]:
    """Download every model not already on this machine. Returns what was pulled."""
    have = list_models()
    todo = [m for m in dict.fromkeys(models) if m not in have]
    for m in todo:
        pull(m, out)
    return todo


class OllamaClient:
    """Same .chat(model, messages) shape as OpenRouterClient, so the Council doesn't care."""

    def __init__(self, timeout: int = 600, max_tokens: int = 1000):
        self.timeout = timeout
        self.max_tokens = max_tokens

    def chat(self, model: str, messages: list[dict]) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": self.max_tokens},
        }
        try:
            resp = requests.post(f"{API}/chat", json=payload, timeout=self.timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise OllamaError(f"{model}: local request failed: {e}") from None
        if resp.status_code != 200 or "error" in data:
            err = data.get("error", str(data)[:300]) if isinstance(data, dict) else data
            hint = " (run: python -m council --roster local --pull)" if resp.status_code == 404 else ""
            raise OllamaError(f"{model}: Ollama error {resp.status_code}: {err}{hint}")
        try:
            text = data["message"]["content"] or ""
        except (KeyError, TypeError):
            raise OllamaError(f"{model}: unexpected response {str(data)[:300]}") from None
        text = THINK.sub("", text).strip()
        if not text:
            raise OllamaError(f"{model}: empty response")
        return text
