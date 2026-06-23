# AGENTS.md — EasyLearn

Guide for humans and AI agents working in this repository.

## What this is

**EasyLearn** is an LTI 1.3 web app that generates structured quizzes from Canvas course materials (PDF/PPTX) using Google Gemini, then deploys them back to Canvas. It is not a generic web app — most behavior is tied to Canvas auth, course context, and the LTI launch flow.

## Repo map

| Path | Purpose |
|------|---------|
| `main.py` | FastAPI entrypoint, middleware, router registration |
| `app/routers/` | Route modules (`api`, `oauth`, `lti_routes`, `pages`) |
| `app/dependencies.py` | FastAPI `Depends()` helpers for course ID and Canvas client |
| `app/` | Shared application logic (Canvas, LTI adapter, generation, storage) |
| `app/config.py` | All environment variables — single source of truth |
| `app/lti.py` | FastAPI adapter for `pylti1p3` |
| `app/schemas.py` | Pydantic models (`WeeklyQuiz`, etc.) |
| `config/lti_config.json` | LTI tool registration per Canvas issuer URL |
| `keys/` | RSA keypair for LTI signing (gitignored) |
| `cache/` | Downloaded files and quiz drafts (gitignored) |
| `templates/` | Dashboard HTML |
| `static/` | Favicon, logo |
| `utils/` | CLI utilities (verify Canvas, offline export, batch quiz gen) |
| `docs/embedding.md` | Canvas iframe / cookie integration notes |

## Dev workflow

```bash
uv sync
cp .env.example .env   # fill in tokens/keys
uv run main.py         # http://0.0.0.0:8000
```

- Python >= 3.14, dependencies via **`uv`** only.
- Never commit `.env`, `keys/*.key`, or `cache/` contents.
- See [README.md](./README.md) for LTI key generation and Canvas Developer Key setup.

## Agent guardrails

- Extend logic in `app/`, not a resurrected `scripts/` package.
- Keep routes thin in `main.py`; put business logic in `app/*`.
- New env vars → `app/config.py` + `.env.example`.
- Do not log tokens, OAuth codes, or extracted course text.
- Do not disable LTI/OAuth validation or CSRF checks.
- Do not commit secrets — grep diffs before merge.

## LTI endpoints (do not rename casually)

| Endpoint | Role |
|----------|------|
| `/login` | OIDC login initiation |
| `/launch` | LTI launch handler |
| `/jwks` | Public JWK set for Canvas |
| `/oauth/callback` | Canvas OAuth2 (multi-instructor mode) |

Canvas Developer Key URLs must match the deployed host exactly when going live.

## Future deploy (optional)

Production on a `.edu` subdomain is a **possible future** step, not current scope. When/if IT deploys:

- Session cookies use `same_site=none` + `https_only=True` (required for LTI cross-site POST back from Canvas).
- Prefer a subdomain on the same registrable domain as Canvas for iframe embedding — see [docs/embedding.md](./docs/embedding.md).
- Use env vars for all secrets; mount `keys/` read-only; persist `cache/` on a volume.
- Run a single worker until LTI in-memory storage is replaced — see `.cursor/rules/04-lti-canvas.mdc`.

Checklist placeholder: [deploy/README.md](./deploy/README.md).
