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


class KeyManager:
    """Create, list, limit and revoke API keys with an OpenRouter *provisioning* key."""

    def __init__(self, provisioning_key: str | None, timeout: int = 30):
        if not provisioning_key:
            raise OpenRouterError(
                "No provisioning key found. Make one at openrouter.ai (Settings > "
                "Provisioning API Keys) and put OPENROUTER_PROVISIONING_KEY in .env."
            )
        self._key = provisioning_key
        self._headers = {
            "Authorization": f"Bearer {provisioning_key}",
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            # No redirects: a redirect must never carry the Authorization header elsewhere.
            resp = requests.request(
                method,
                f"{API}/keys{path}",
                json=body,
                headers=self._headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise OpenRouterError(
                f"keys: request failed: {e}".replace(self._key, "[REDACTED]")
            ) from None
        if resp.status_code not in (200, 201) or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = err.get("code", resp.status_code)
            msg = f"keys: OpenRouter error {code}: {err.get('message', str(data)[:300])}"
            raise OpenRouterError(msg.replace(self._key, "[REDACTED]"))
        return data

    def list(self) -> list[dict]:
        return self._call("GET", "")["data"]

    def create(self, name: str, limit: float | None = None) -> tuple[dict, str]:
        """Returns (key info, the secret). OpenRouter shows the secret only this once."""
        body = {"name": name}
        if limit is not None:
            body["limit"] = limit
        data = self._call("POST", "", body)
        return data["data"], data["key"]

    def update(self, key_hash: str, **changes) -> dict:
        """changes: any of name=, limit=, disabled=."""
        return self._call("PATCH", f"/{_checked(key_hash)}", changes)["data"]

    def delete(self, key_hash: str) -> None:
        self._call("DELETE", f"/{_checked(key_hash)}")


def _checked(key_hash: str) -> str:
    """A key hash goes into the URL path, so allow only plain letters and digits."""
    if not key_hash.isascii() or not key_hash.isalnum():
        raise OpenRouterError(f"Not a key hash: {key_hash!r} (see `keys list`)")
    return key_hash
