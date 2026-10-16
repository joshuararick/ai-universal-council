# AI Universal Council

Ask one question. Four AI models answer **at the same time**, each from a different seat.
A **Chair** model reads every answer and writes **one verdict**: what they agree on, where
they disagree, and what to do next.

```
            ┌─> Chief of Staff ─┐
question ───┼─> Lead Engineer  ─┼──> Chair ──> VERDICT
            ├─> Architect      ─┤
            └─> Tactician      ─┘
       fan-out (parallel)     fan-in (synthesis)
```

## Quick start (Windows PowerShell)

```powershell
git clone https://github.com/joshuararick/ai-universal-council
cd ai-universal-council
.\setup.ps1                              # one time: venv, deps, key, tests, model check
.\run.ps1 "What should I build next?"
.\run.ps1 -Roster free "Your question"   # free models (rate-limited, no credits needed)
.\run.ps1 --verdict-only "Your question" # just the verdict
```

The key is looked up in this order: `OPENROUTER_API_KEY` env var → project `.env` → `~/.secrets/api-keys.env`.

## Change the models

Edit `council.toml` (rosters, chair, roles, `max_tokens`, timeout), then verify:

```powershell
.\run.ps1 --check     # uses OpenRouter's public model list: no key sent, $0
```

CI runs the same check weekly, so you'll find out when a model is retired.

## Manage API keys (yours and other people's)

An OpenRouter **provisioning key** can make and manage ordinary API keys, but can't call
models itself. Create one at openrouter.ai → Settings → Provisioning API Keys and put it
in `.env` as `OPENROUTER_PROVISIONING_KEY` (kept separate from `OPENROUTER_API_KEY`).

```powershell
python -m council.keys list                       # every key: name, hash, spend, limit
python -m council.keys create "friend" --limit 5  # new key capped at $5; secret shown ONCE
python -m council.keys limit HASH 10              # change a cap ("none" removes it)
python -m council.keys disable HASH               # switch off (enable turns it back on)
python -m council.keys delete HASH --yes          # revoke for good
```

## Files: one job each

| File | Job |
|---|---|
| `council.toml` | Who sits on the council. Change models here, not in code. |
| `council/config.py` | Loads the roster and finds your key. |
| `council/openrouter.py` | The **only** file that touches the network (chat + key management; retries, redaction, no redirects). |
| `council/council.py` | The brain: fan-out to members, fan-in to the Chair. |
| `council/__main__.py` | The command line. |
| `council/keys.py` | Key manager command line (`python -m council.keys`). |
| `tests/` | 32 offline tests: no network, no key, $0. `python -m unittest` |

## Docker

```powershell
docker build -t ai-universal-council .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges `
  -e OPENROUTER_API_KEY ai-universal-council --roster free "Your question"
```

## Security

See [SECURITY.md](SECURITY.md). The short version:
- The key lives in `.env` (git-ignored) and is **redacted** from every error message.
- No key means a clear error. There is no fake "simulation" mode.
- `-e OPENROUTER_API_KEY` (no value) forwards the key without putting it in shell history.
- `setup.ps1` turns on a git hook that blocks commits containing API keys; CI runs gitleaks too.
