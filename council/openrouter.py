"""The only file that talks to the network. Everything else is plain logic."""

import time

import requests

API = "https://openrouter.ai/api/v1"
RETRIES = 3  # free models are often rate-limited (HTTP 429); back off and retry


class OpenRouterError(RuntimeError):
    pass


def list_models(timeout: int = 30) -> set[str]:
    """Every model ID OpenRouter offers right now. Public endpoint: no key sent, $0."""
    resp = requests.get(f"{API}/models", timeout=timeout, allow_redirects=False)
    resp.raise_for_status()
    return {m["id"] for m in resp.json()["data"]}


class OpenRouterClient:
    def __init__(self, api_key: str | None, timeout: int = 120, max_tokens: int = 1000):
        if not api_key:
            raise OpenRouterError(
                "No OpenRouter key found. Put OPENROUTER_API_KEY in .env "
                "(or the environment, or ~/.secrets/api-keys.env)."
            )
        self._key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Universal Council",
        }
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _redact(self, text: str) -> str:
        """Never let the key leak into output, even via an echoed error payload."""
        return text.replace(self._key, "[REDACTED]")

    def chat(self, model: str, messages: list[dict]) -> str:
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens}
        for attempt in range(RETRIES):
            try:
                # No redirects: a redirect must never carry the Authorization header elsewhere.
                resp = requests.post(
                    f"{API}/chat/completions",
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                raise OpenRouterError(
                    self._redact(f"{model}: request failed: {e}")
                ) from None
            if resp.status_code != 429 or attempt == RETRIES - 1:
                break
            time.sleep(5 * (attempt + 1))

        if resp.status_code != 200 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = err.get("code", resp.status_code)
            hint = (
                " (out of credits: add credits or use --roster free)"
                if code == 402
                else ""
            )
            msg = f"{model}: OpenRouter error {code}: {err.get('message', str(data)[:300])}{hint}"
            raise OpenRouterError(self._redact(msg))
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            raise OpenRouterError(
                self._redact(f"{model}: unexpected response {str(data)[:300]}")
            ) from None
        if not text:
            raise OpenRouterError(f"{model}: empty response")
        return text
