# LTI 1.3 and per-professor OAuth

This is the conceptual core of EasyLearn. Canvas integrations involve two
distinct trust mechanisms, and EasyLearn uses both. Understanding why is the
difference between "it works" and "I have no idea why the cookie broke."

---

## The two-keys model

Canvas separates **who launched the tool** from **what the tool may do via the
REST API**. These map to two separate Developer Keys:

| Key | Answers | Backed by | Where configured |
|-----|---------|-----------|------------------|
| **LTI 1.3 key** | "Who is launching, from which course?" | Signed JWT (OIDC) | [config/lti_config.json](../config/lti_config.json) + Canvas LTI registration |
| **API / OAuth2 key** | "May I call the Canvas REST API as this user?" | OAuth2 access token | `CANVAS_CLIENT_ID` / `CANVAS_CLIENT_SECRET` in `.env` |

The LTI launch authenticates the user and hands over course context, but it does
**not** grant REST API access. To create quizzes, EasyLearn needs an API token —
and rather than a shared admin token, each professor authorizes individually so
API calls run with their own Canvas permissions.

This is the standard enterprise LTI pattern:

1. Professor launches EasyLearn via Canvas LTI 1.3.
2. EasyLearn validates the signed LTI JWT.
3. EasyLearn initiates an OAuth2 flow to obtain the professor's Canvas API token.
4. EasyLearn calls the Canvas API as that professor (their permissions).
5. EasyLearn creates quizzes in their courses.

---

## The end-to-end flow

```mermaid
sequenceDiagram
    participant Browser
    participant Canvas
    participant EasyLearn

    Note over Browser,EasyLearn: LTI 1.3 launch (OIDC)
    Browser->>EasyLearn: GET/POST /login (OIDC initiation)
    EasyLearn->>Canvas: redirect to authorize (state + nonce)
    Canvas->>EasyLearn: POST /launch (signed id_token JWT)
    EasyLearn->>EasyLearn: pylti1p3 validates JWT vs Canvas JWKS
    EasyLearn->>Browser: store session (user, role, course); redirect /

    Note over Browser,EasyLearn: Per-professor OAuth2
    Browser->>EasyLearn: GET / (needs API token)
    EasyLearn->>Canvas: redirect /oauth/login (client_id, state, scopes)
    Canvas->>Browser: consent screen
    Browser->>EasyLearn: GET /oauth/callback (code, state)
    EasyLearn->>Canvas: POST token (code -> access+refresh token)
    EasyLearn->>EasyLearn: store tokens in session
    EasyLearn->>Browser: dashboard ready (API calls use professor's token)
```

### LTI launch endpoints

| Endpoint | Role |
|----------|------|
| `/login` | OIDC login initiation |
| `/launch` | Signed JWT launch handler (validated by `pylti1p3`) |
| `/jwks` | Public JWK set Canvas uses to verify the tool |

Implemented in [app/routers/lti_routes.py](../app/routers/lti_routes.py) and the
FastAPI adapter [app/lti.py](../app/lti.py). The launch extracts the user's
name, email, role, `sub`, and `canvas_course_id` (from the custom field
`canvas_course_id=$Canvas.course.id`) into the session. A launch that fails JWT
validation returns `401` rather than proceeding.

### OAuth2 authorization-code flow

| Endpoint | Role |
|----------|------|
| `/oauth/login` | Redirect to Canvas authorize with `state` (CSRF) + optional scopes |
| `/oauth/callback` | Exchange the code for access + refresh tokens |

Implemented in [app/routers/oauth.py](../app/routers/oauth.py) with the token
lifecycle in [app/canvas_oauth.py](../app/canvas_oauth.py). The `state` parameter
is stored in the session and re-checked on callback to prevent CSRF.

### Token refresh

Canvas access tokens are short-lived (~1 hour). On the initial code exchange
Canvas also returns a **refresh token**, which EasyLearn stores in the encrypted
session alongside the access token and its expiry. Tokens are refreshed:

- **Proactively** in `resolve_canvas_client()`
  ([app/dependencies.py](../app/dependencies.py)) when the access token is within
  ~120s of expiry, and
- **Reactively** in the `InvalidAccessToken` handler in [main.py](../main.py),
  which attempts a one-shot refresh before forcing re-authorization.

The refresh token lives only in the encrypted session cookie and is never
logged.

### Scopes

If the API Developer Key has **Enforce Scopes** enabled, the authorize request
must include the scopes the key grants. Set them via `CANVAS_OAUTH_SCOPES`
(space-separated) in `.env`; the recommended set for EasyLearn's calls is listed
in [.env.example](../.env.example). Leave it empty when scopes are not enforced —
sending scopes the key does not grant will make Canvas reject the authorize
request.

---

## Session auth modes

[app/auth.py](../app/auth.py) computes an `auth_mode` exposed at `/api/session`
and used by the dashboard. This is the quickest way to diagnose "why can't I see
my courses":

| `auth_mode` | Meaning | API calls use |
|-------------|---------|---------------|
| `oauth` | Launched via LTI, OAuth authorized | Per-professor token |
| `oauth_pending` | Launched via LTI, OAuth not yet authorized | None (redirect to authorize) |
| `anonymous` | No valid session | None |

The web app requires a Canvas LTI launch and per-professor OAuth. The shared
`CANVAS_API_TOKEN` in `.env` is for CLI utilities only — not browser sessions.

Teaching-role enforcement: write/data routes depend on `require_teacher`
([app/dependencies.py](../app/dependencies.py)), which allows `Teacher`,
`Instructor`, and `Teaching Assistant` roles and rejects students with `403`.

---

## Launch context: iframe vs new tab, and third-party cookies

The LTI OIDC handshake relies on cookies (the OIDC `state`/`nonce` and the
FastAPI session). Modern browsers block **third-party cookies** — cookies set by
content inside an iframe whose domain differs from the parent page. Canvas
embeds external tools in an iframe by default, so on a different host (or even a
different port on `localhost`) the handshake cookies are blocked and the launch
fails with:

> Your browser prohibits saving cookies in iframes. Click here to open content
> in a new tab.

Pick one of the following integration methods.

### Method 1 — launch in a new tab (recommended for local dev)

`localhost:3000` (Canvas) and `localhost:8000` (EasyLearn) are different sites,
so iframe cookies are blocked. Configuring the LTI placement to open in a new
tab makes EasyLearn run first-party, and the handshake succeeds.

In the Canvas UI: **Developer Keys** (or **Apps -> EasyLearn -> Settings**) ->
edit the registration -> **Course Navigation** placement -> **Window Target** =
**New Tab** / `_blank`.

Or from the repo (admin token in `.env`):

```bash
uv run utils/configure_lti.py --new-tab-only
```

### Method 2 — same registrable domain (production embedding)

To embed inside the Canvas iframe, host EasyLearn on a subdomain of the Canvas
domain (e.g. Canvas on `canvas.university.edu`, tool on
`easylearn.university.edu`). Sharing the registrable domain (`university.edu`)
lets the browser treat the cookies as first-party. For the public self-hosted
setup, see [deployment.md](./deployment.md).

### Method 3 — the `canvas.docker` host

Use `http://canvas.docker:3000` (Canvas) and `http://canvas.docker:8000`
(EasyLearn); add `127.0.0.1 canvas.docker` to `/etc/hosts`. Then:

```bash
uv run utils/configure_lti.py    # syncs tool URLs to EASYLEARN_PUBLIC_URL + new tab
```

EasyLearn rewrites `localhost:8000` LTI URLs to `canvas.docker:8000` and uses
`prompt=login` on HTTP so Chromium can complete OIDC (`prompt=none` fails when
Canvas session cookies are `SameSite=Strict` across ports). The relevant logic
is in [app/lti.py](../app/lti.py) and [app/config.py](../app/config.py).

### Method 4 — browser cookie exceptions (not for production)

You can allow third-party cookies for `localhost` in Chrome
(`chrome://settings/cookies`) or disable cross-site tracking prevention in
Safari. Never ask real instructors or students to lower browser privacy; use
Method 1 or 2.

### Cookie flags

[app/config.py](../app/config.py) sets session/LTI cookie flags from the scheme:

- **HTTP dev** (`http://`): `SameSite=Lax`, `Secure` omitted (Chromium rejects
  `SameSite=None` without `Secure` on non-localhost HTTP).
- **HTTPS** (production): `SameSite=None` + `Secure`, required for the
  cross-site POST from Canvas to `/launch`.

Behind a TLS-terminating proxy (e.g. Cloudflare Tunnel), the proxy must forward
`X-Forwarded-Proto: https` so `FastAPIRequest.is_secure()` reports secure. See
[deployment.md](./deployment.md).
