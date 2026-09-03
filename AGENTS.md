# AGENTS.md — EasyLearn

Context for humans and AI agents working in this repository.

## What this is

EasyLearn is an LTI 1.3 web app. College professors launch it from Canvas,
authorize via per-professor OAuth, select course materials (PDF/PPTX), generate
structured quizzes with Gemini or OpenRouter, and deploy the quizzes back into
Canvas. The RAG/OCR extraction pipeline is intentionally retained.

## Layout

- `main.py` — FastAPI entrypoint, middleware, health endpoints, ops dashboard.
- `app/` — all business logic. Routers in `app/routers/` stay thin; logic lives in `app/*`.
- `app/ops/` — usage ledger, per-user spend caps, model circuit breaker, webhook alerts.
- `app/config.py` — every environment variable. Single source of truth.
- `utils/` — one-off setup tools (LTI/OAuth config). Not importable app code.
- `tests/` — pytest unit tests for pure logic. (Instance-specific and PII-bearing tests live outside this repo.)
- `config/`, `keys/`, `cache/`, `templates/`, `static/`, `docs/` — config, LTI keys, file cache, HTML, assets, deployment docs.

## Dev workflow

```bash
cp .env.example .env
cp config/lti_config.example.json config/lti_config.json
uv sync
uv run --no-sync utils/configure_oauth.py --write-env
docker compose up -d --build      # or: uv run --no-sync main.py
```

Run tests: `uv run --no-sync python -m pytest`

## Rules

- Python >= 3.14; manage deps with `uv` only. Always `uv run --no-sync` — never `python3` or `.venv/bin/python` (the flag avoids costly re-syncs).
- Never commit `.env`, `keys/*.key`, or `cache/`. Grep diffs before merge.
- `CANVAS_API_TOKEN` is CLI-only; the web app uses LTI + per-professor OAuth.
- New env var → add to `app/config.py` and `.env.example`.
- Do not log tokens, OAuth codes, or extracted course text.
- Do not disable LTI/OAuth validation or CSRF checks.
- After edits, run syntax checks before claiming done: `uv run --no-sync python -m py_compile <files>` (Python) and `node -c static/js/*.js` (JS).

## LTI endpoints (do not rename casually)

| Endpoint | Role |
|----------|------|
| `/login` | OIDC login initiation |
| `/launch` | LTI launch handler |
| `/jwks` | Public JWK set for Canvas |
| `/oauth/callback` | Canvas OAuth2 (multi-instructor mode) |

Canvas Developer Key URLs must match the deployed host exactly when going live.

## Deploy

`docker-compose.yml` + `docs/deployment.md`.
