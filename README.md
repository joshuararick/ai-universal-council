# AI Universal Council

Sends one directive to several models via OpenRouter in parallel and prints each answer.

```powershell
.\run.ps1                                   # default roster, readiness-check directive
.\run.ps1 -Roster free "Your question"      # free models (rate-limited, no credits needed)
docker build -t ai-universal-council .
docker run --rm -e OPENROUTER_API_KEY ai-universal-council --roster free "Your question"
```

API key lookup order: `OPENROUTER_API_KEY` env var → project `.env` → `~/.secrets/api-keys.env`.
Rosters, `max_tokens`, and timeout live in `config/council.json`.
