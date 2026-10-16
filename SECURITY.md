# Security Policy

## Reporting a vulnerability
Please report privately via **GitHub → Security → Report a vulnerability** on this repo.
Do not open a public issue for security problems.

## Secrets
- No API keys are stored in this repository. The OpenRouter key is read at runtime from the
  `OPENROUTER_API_KEY` environment variable, a git-ignored `.env`, or `~/.secrets/api-keys.env`.
- Secret scanning with push protection is enabled, and CI runs gitleaks on every push and PR.
- If a key is ever exposed, revoke it at openrouter.ai → Keys immediately; deleting it from git is not enough.

## Supply chain
- Python dependencies are exact-pinned with hashes (`pip --require-hashes`) and audited with `pip-audit` in CI.
- The Docker base image is pinned by digest; GitHub Actions are pinned by commit SHA.
- Dependabot proposes updates for pip, Docker, and Actions weekly.
