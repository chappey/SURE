# EasyLearn — Audit Handoff (2026-08-21) — AUDIT COMPLETE, refactor not started

All findings from the full security/hardening audit are below (entrypoint/config/Docker
pass + three module deep-dives). Nothing has been changed in app code yet.

## Confirmed findings (Windows-side pass)

### Architecture / entrypoint (`main.py`)
1. **Module-aliasing hack** (lines 9–12): `sys.modules["pylti1p3.contrib.fastapi"] = app.lti`
   registers a custom adapter globally before routers import. Fragile and order-dependent;
   any module importing pylti1p3 *before* main.py gets the real adapter. Refactor: use
   pylti1p3's documented FastAPI adapter registration/config mechanism instead.
2. **Duplicate unhandled-exception handling**: BOTH `log_requests` middleware (lines 117–124)
   and the `Exception` handler (49–61) catch unhandled errors, returning different bodies
   (`{"error": ...}` vs `{"detail": ...}`). Consolidate into one path.
3. **`handle_invalid_token` is `def` (sync)** and calls `try_refresh(request)` which performs
   a blocking outbound HTTP token refresh — blocks the event loop. Make async / run in
   threadpool. Also mutates the session inside an exception handler (works, but implicit).
4. **CSRF middleware** (64–87): string-equality of full Origin against
   `EASYLEARN_PUBLIC_URL`. Breaks silently if deployed behind a proxy that alters Host, and
   requests with *neither* Origin nor Referer are rejected only by accident of logic
   (origin_ok False, ref_ok False → rejected — OK, but verify intent). Consider also
   requiring the check on non-/api state-changing routes if any exist.
5. **`readyz`** (180–213) publicly enumerates which config pieces are missing
   (`reasons` list). Low risk, but consider gating detail behind auth or trimming reasons.

### Config (`app/config.py`)
6. **Dual source of truth**: `settings` object AND ~15 module-level re-exports
   (175–189). Code imports both styles (`from app.config import X` vs `config.X`). Drift
   risk; refactor to read from `settings` everywhere.
7. **`CREDS_DIR = cache/credentials`** (168): credentials live under `cache/`. Ensure
   gitignored (verify) and consider a dedicated, tighter-permission directory.
8. No assertion that `EASYLEARN_PUBLIC_URL` is https in production deployments.

### Deployment
9. **Dockerfile runs as root** — add a non-root `USER`.
10. **`COPY config ./config`** bakes the real `config/lti_config.json` (and anything else
    in `config/`) into image layers even though compose mounts it ro afterward. Copy only
    `ai_models.json` (+ example), mount the rest.
11. Compose publishes `0.0.0.0:${PORT}` — bind `127.0.0.1:` when running behind the
    Cloudflare tunnel profile.
12. Healthcheck spawns `uv run python -c ...` per probe (heavy); use a plain
    `python -c` or curl/wget one-liner.

### LLM layer
13. `fallback.py`: `generate_json_with_fallback` and `generate_text_with_fallback` are
    near-identical loops → extract shared runner.
14. `openrouter.py`: uses **sync OpenAI client**; confirm callers wrap in
    `run_in_executor`/threadpool, else event-loop blocking. `LLM_TIMEOUT_SECONDS = 300`
    is very long — consider per-attempt timeout + overall budget. Silent schema→json_object
    fallback doubles cost/latency on persistent failures; log rate-limit it.
15. `extraction.py` (PDF/PPTX/OCR) is CPU-heavy sync code — same threading question.
16. `_iter_shapes` broad `except Exception` swallows real errors silently.

### Repo hygiene (to verify in WSL where git works)
17. Confirm `.env`, `keys/*.key`, `cache/**`, `config/lti_config.json` are NOT tracked in
    git history (`git ls-files | grep -E '^\.env$|^keys/|^cache/'`) and grep history for
    leaked secrets if ever committed.
18. `pyproject.toml` project name is `"sure"` not `easylearn` — cosmetic mismatch.

## Completed deep-dive #2: API router + services (full findings)

### Critical
- **C1. Missing import breaks approve endpoint** — `app/routers/api.py:738` calls
  `update_quiz_submission_comments(...)` which is never imported in api.py → `NameError`
  → 500 on every `POST /api/quizzes/{quiz_id}/agentic-feedback/approve`, *after* partial
  Canvas writes (loop at 730–745 already pushed some submissions; `update_quiz_draft` at
  747 never runs). Fix import + make the loop transactional/ordered.

### High
- **H1. Teacher check is a no-op** — `canvas_courses.py:31-43` unconditionally inserts the
  requested course into the teacher list when `canvas.get_course(id)` succeeds ("admin/dev
  tokens" comment), so `validate_course_access` (`dependencies.py:81-87`) passes for any
  course the token can GET, incl. student enrollments. Canvas enforces per-call perms, but
  the app-level gate is defeated.
- **H2. Path traversal via quiz_id** — `storage.py:62-63` interpolates `quiz_id` into
  `.../quizzes/{quiz_id}.json` unsanitized; `%2F` decodes in path params, enabling
  read/write of arbitrary `.json` files. Fix: validate `^[A-Za-z0-9_-]+$`.
- **H3. Stored XSS surface on deploy** — `schemas.py:160-196` puts client-controlled text
  straight into Canvas `*_html` fields; `validate_questions` runs only at generation
  (`generation.py:175`), not on the deploy path (`deployment.py:37-114`). Re-validate +
  sanitize HTML before deploy.
- **H4. Secrets in logs** — `canvas.py:112-113` and `api.py:286-287` log raw request
  exceptions whose text includes full signed/bearer-bearing Canvas URLs. Violates repo rule.

### Medium
- **M1. Rate limiting**: only `/api/generate-quiz` limited (`rate_limiter.py:38-42`);
  agentic-feedback process/preview and `?refresh=1` unmetered LLM+Canvas heavyweights;
  `_buckets` never evicted (unbounded memory); anonymous callers share one bucket.
- **M2. Threadpool starvation**: long sync handlers (generate ~124 lines of download+
  extract+LLM, feedback process/preview) can exhaust anyio pool (~40 threads) stalling all
  API; per-request `ThreadPoolExecutor(max_workers=6)` shares one canvasapi client across
  threads (`quizzes_service.py:117-118`) — thread-safety not guaranteed.
- **M3. No timeouts/retries on Canvas HTTP**: canvasapi session has no default timeout
  (`canvas.py:18-46`); fallback `file_obj.download()` unbounded; retry/backoff absent;
  private-name access `canvas._Canvas__requester` (`canvas_courses.py:66-67`) is fragile.
- **M4. Draft races**: checkpoint computed outside lock then written twice
  (service persists it, endpoint re-persists popped keys — api.py:572-589 vs
  quizzes_service.py:330-349); concurrent invocations duplicate LLM spend + Canvas writes;
  workspace whole-field replace clobbers concurrent autosave.
- **M5. Confidence classification bug** — `api.py:540` exact-matches `("high","5","4",
  "very high","confident")` against labels like "Very confident"/"Completely confident"
  (`agentic_feedback.py:18-24`) → every row lands in low-confidence; misconception matrix
  misreports everything. Normalize + substring match against CONFIDENCE_LABELS.
- **M6. `/api/session` (api.py:73-76) is the only ungated /api endpoint** — reflects only
  caller cookie, but useful for probing stolen cookies; require launch or trim fields.
- **M7. `source_text` (up to 100k chars of copyrighted extracts) persisted and echoed on
  every quiz GET/workspace load** (api.py:295-297,350; feedback_workspace.py:189). Strip
  from GET responses.

### Low / quality (abridged)
Duplicate imports api.py:19-24 & 35-40; oversized handlers violating "thin routers";
inline request models w/ unvalidated `list[dict]` persisted verbatim; weak typing
(`CanvasClientDep = Annotated[object,...]`, untyped params); unvalidated `int()` coercions
→ 500s; `attempt=1` hard-coded api.py:742 vs service using real attempt; swallowed
exceptions (api.py:235-236, canvas_courses.py:74-76, canvas.py:60-61);
`find_module_by_id_or_name` catches wrong exceptions (ResourceDoesNotExist escapes);
single-split batching fails for very large classes; read paths mkdir side effects;
dev-only Host-header/port-rewrite hacks in production canvas.py.

### Verified solid
Atomic writes w/ fsync+os.replace+RLock; every mutating endpoint except /api/session has
LTI-launch + teacher deps; Canvas client strictly from per-session OAuth token;
html_to_plain_text strips tags/entities before rendering.

## Completed deep-dive #3: LTI/OAuth/auth (full findings)

### High
- **L1. `InMemoryDataStorage` for LTI nonces/states** (`lti.py:19-44, 330-334`):
  process-global dict with no eviction (`exp` ignored; 86400s TTL silently dropped because
  `can_set_keys_expiration()` is False). Consequences: replayable launches, cross-user
  nonce acceptance, unbounded memory growth via unauthenticated `/login?target_link_uri=`
  loop → OOM, and breaks under multi-worker deployment. **Fix: per-session storage keyed by
  the Starlette session (or Redis) with TTL enforcement** — resolves all four at once.
- **L2. `SameSite=None` sessions + Origin/Referer-only CSRF** (`main.py:133-138`,
  `config.py:72`, `main.py:64-87`): no CSRF tokens on state-changing routes; expected
  origin derives solely from EASYLEARN_PUBLIC_URL (proxy misconfig fails all writes);
  Referer-only requests pass. Verify all writers outside /api/*.

### Medium
- **M-L1. Partial LTI session-binding window** (`lti_routes.py:107-109`,
  `session_identity.py:46-64`): old identity/tokens cleared *before* new identity written;
  bare-`except Exception` swallows failure between the two and redirects into the app →
  session flagged launched with cleared/stale identity. Compute new identity fully then
  swap atomically; fail closed.
- **M-L2. Token-refresh stampede** (`canvas_oauth.py:153-174`): `ensure_fresh_token` runs
  unlocked on every request within the 120s leeway → N concurrent refreshes. Add
  per-session single-flight lock.
- **M-L3. Token-endpoint error bodies logged raw** (`canvas_oauth.py:63-65, 85-87`) —
  potential secret echo; also `try_refresh` swallows exceptions silently (186-187) making
  the main.py:141-156 recovery path blind in production.
- **M-L4. Substring role matching gates instructor authz** (`lti_claims.py:12-25`).
- **M-L5. Lazy tool-conf init race + late failure** (`lti_config.py:104-108, 111-114`):
  built on first request touching /jwks//login//launch; concurrent first requests race the
  global; malformed key file surfaces as mid-request 500. Init eagerly in startup behind a
  lock; replace module-level `__getattr__` magic with explicit `get_tool_conf()`.
- **M-L6. `_token_is_expiring` returns False when expiry unknown**
  (`canvas_oauth.py:145-146`) — sessions that lost `canvas_token_expires_at` never
  proactively refresh. Treat "refresh token present but no expiry" as expiring.

### Low
- Non-constant-time state comparison; reflected `error` query param echoed in detail
  (`oauth.py:57-58, 62-64`).
- Latent JS-string injection in dead `FastAPIRedirect.do_js_redirect` (`lti.py:128-131`)
  — escape with json.dumps or delete.
- Dead GET /launch branch (`lti_routes.py:79-111`) — unauthenticated no-op redirect;
  return 405 instead. Post-launch `target_link_uri` deep link is normalized during OIDC
  then discarded at line 111 — persist sanitized target in session and honor it post-auth.
- Dead/duplicate imports: `import sys` lti.py:2; config re-imported 3× in lti_routes.py
  (11, 22-23, 55-57).
- Duplicated redirect-URI logic: `auth.py:56-59` ≈ `config.py:128-132`; consolidate into
  config.py (which already exports an unused precomputed value).
- Hardcoded `"oauth_required": True` / `"lti_required": True` constants (`auth.py:96,98`).
- Type gaps: `CanvasClientDep = Annotated[object,...]`, missing return annotations,
  wrong `RedirectResponse`-only annotations on lti_routes handlers.

### Robustness notes
Sync oauth routes are fine; watch for any future `requests` call added inside async def
routes (30s event-loop stalls). Threadpool (~40) is the effective OAuth concurrency
ceiling. Canvas HTTP has no retry/backoff anywhere.

## Baseline before refactor (WSL session)
- Run `uv run --no-sync python -m pytest` first to establish a green baseline.

## Suggested hardening order (updated)
1. Quick correctness wins: C1 missing import (+ ordered/partial-failure handling), M5
   confidence bug, H4 redact URLs in logged exceptions.
2. H2 quiz_id validation at dependency level.
3. L1 LTI storage replacement (session/Redis-backed, TTL) — biggest security win.
4. H3 re-validate/sanitize on deploy path; H1 replace course_is_teacher fallback.
5. M-L1 atomic session swap; M-L2 refresh single-flight; M-L5 eager tool-conf init.
6. Timeouts/retries on Canvas calls (M3) + rate-limit coverage (M1).
7. Structural cleanup: dedupe config exports & redirect-URI logic, thin routers,
   consolidate exception handling, delete dead code, Dockerfile non-root + config copy fix.
8. L2 CSRF tokens: after storage rework, decide token scheme vs hardened Origin checks.

## Ground rules (from AGENTS.md)
- Python ≥3.14, `uv` only, always `uv run --no-sync`.
- Never commit `.env`, `keys/*.key`, `cache/`. Don't log tokens/OAuth codes/course text.
- Don't disable LTI/OAuth validation or CSRF checks.
- After edits: `uv run --no-sync python -m py_compile <files>`; `node -c static/js/*.js`.
- LTI endpoints `/login /launch /jwks /oauth/callback` — do not rename.
