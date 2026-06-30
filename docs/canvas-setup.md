# Canvas setup (fresh local instance)

This guide stands up a local Canvas LMS, creates the credentials EasyLearn needs,
and points you at the next steps. It assumes the official Instructure
[`canvas-lms`](https://github.com/instructure/canvas-lms) repository checked out
locally (commonly checked out at a path like `~/canvas-lms` or `/opt/canvas-lms`).

If you already have a Canvas instance and an admin account, skip to
[Create an admin API token](#2-create-an-admin-api-token).

---

## 1. Start Canvas with Docker

Canvas ships a Docker Compose development stack. The bundled
`docker-compose.yml` + `docker-compose.override.yml` define a `web` service that
binds container port 80 to host port 3000, so Canvas is reachable at
`http://localhost:3000`.

First-time bring-up (builds images, creates the database, seeds an admin user):

```bash
cd /path/to/your/canvas-lms
./script/docker_dev_setup.sh
```

The setup script is interactive and will prompt you to create the initial site
admin login (email + password). Note these — they are your Canvas admin
credentials.

On subsequent runs, just start the core services:

```bash
cd /path/to/your/canvas-lms
docker compose up -d web jobs postgres redis
```

Open `http://localhost:3000` and log in as the admin account.

> Notes
> - First build is slow (Rails + Postgres + Redis + asset compilation).
> - `jobs` runs the delayed-job worker; some Canvas actions (emails, exports)
>   need it running.
> - The override file also sets `VIRTUAL_HOST=.canvas.docker`, which enables the
>   `canvas.docker` hostname used for iframe-friendly local testing. See
>   [lti-and-oauth.md](./lti-and-oauth.md) for when to prefer `localhost:3000`
>   vs `canvas.docker:3000`.

---

## 2. Create an admin API token

EasyLearn's CLI utilities use a Canvas admin API token (server-side, not per-professor).

1. In Canvas, click your **Account** -> **Settings**.
2. Under **Approved Integrations**, click **+ New Access Token**.
3. Give it a purpose (e.g. `EasyLearn dev`) and leave the expiry blank for local
   use.
4. Copy the token immediately — Canvas only shows it once.

Put it in EasyLearn's `.env`:

```ini
CANVAS_API_URL=http://localhost:3000
CANVAS_API_TOKEN=<the token you just copied>
```

> This admin token is for CLI utilities only (`utils/configure_lti.py`,
> `utils/configure_oauth.py`). The web app uses per-professor OAuth tokens — see
> [lti-and-oauth.md](./lti-and-oauth.md).

---

## 3. Create a course (or generate one)

You need at least one published course with PDF/PPTX material in modules for
EasyLearn to quiz on.

Option A — generate a fully populated demo course with AI (recommended for demos):

```bash
uv run utils/generate_demo_course.py --topic "Introduction to Databases" --modules 4
```

This creates the course, modules, and uploaded slide decks in one step. See
[demo.md](./demo.md).

Option B — create a course manually in the Canvas UI (**+ Course**), publish it,
then add modules and upload PDF/PPTX files.

Either way, note the numeric **course id** from the course URL (`/courses/<id>`)
for CLI tools that take `--course-id`.

---

## 4. Create the two Developer Keys

EasyLearn uses **two separate** Canvas Developer Keys. This is a Canvas design
decision, not ours — the LTI launch and the REST API are different trust
mechanisms. See [lti-and-oauth.md](./lti-and-oauth.md) for the full rationale.

Replace `<tool>` below with EasyLearn's browser-facing base URL
(`http://localhost:8000` for the simplest local setup, or
`http://canvas.docker:8000` when using the `canvas.docker` host).

### 4a. LTI 1.3 key (the launch)

1. **Admin** -> **Developer Keys** -> **+ Developer Key** -> **+ LTI Key**.
2. Configure:
   - **Key Name**: `EasyLearn`
   - **Redirect URIs**: `<tool>/launch`
   - **Target Link URI**: `<tool>/launch`
   - **OpenID Connect Initiation Url**: `<tool>/login`
   - **JWK Method**: **Public JWK URL** -> `<tool>/jwks`
   - **Placements**: **Course Navigation**
   - **Custom Fields**:
     ```
     canvas_course_id=$Canvas.course.id
     ```
3. Save, then toggle the key state to **ON**.
4. Copy the numeric **Client ID** from the Details column.

Install it in a course (or account):

1. Course **Settings** -> **Apps** -> **View App Configurations** -> **+ App**.
2. **Configuration Type**: **By Client ID**, paste the Client ID, **Submit** ->
   **Install**.
3. Open the installed app's settings -> **Deployment Info** and copy the
   **Deployment ID**.

Record both values in [config/lti_config.json](../config/lti_config.json) under
your Canvas issuer URL (e.g. `http://localhost:3000` for local dev, or
`https://canvas.example.com` for a public hostname):

> **Custom domains:** Canvas OIDC login sends `iss=https://canvas.instructure.com`
> even when the browser uses your own hostname. EasyLearn adds that issuer
> automatically from your HTTPS `CANVAS_PUBLIC_URL` registration — you do not
> need a separate Canvas Developer Key for it.

```json
{
  "http://localhost:3000": [
    {
      "default": true,
      "client_id": "<LTI client id>",
      "auth_login_url": "http://localhost:3000/api/lti/authorize_redirect",
      "auth_token_url": "http://localhost:3000/login/oauth2/token",
      "key_set_url": "http://localhost:3000/api/lti/security/jwks",
      "private_key_file": "../keys/private.key",
      "public_key_file": "../keys/public.key",
      "deployment_ids": ["<deployment id>"]
    }
  ]
}
```

### 4b. API / OAuth2 key (the per-professor token)

Automated (recommended):

```bash
uv run utils/configure_oauth.py --write-env
```

This creates an **API Developer Key** named `EasyLearn API`, sets the OAuth redirect
URI to `<EASYLEARN_PUBLIC_URL>/oauth/callback`, and turns the key **ON** for your
account. It does **not** enable “Enforce Scopes” by default — leave
`CANVAS_OAUTH_SCOPES` empty in `.env` unless you pass `--enforce-scopes`.

Manual alternative (Canvas UI):

1. **Admin** -> **Developer Keys** -> **+ Developer Key** -> **+ API Key**.
2. **Key Name**: `EasyLearn API`
3. **Redirect URIs**: `<tool>/oauth/callback`
4. Save, toggle **ON**, copy **Client ID** and **Client Secret** into `.env`:

```ini
CANVAS_CLIENT_ID=<API client id>
CANVAS_CLIENT_SECRET=<API client secret>
CANVAS_OAUTH_REDIRECT_URI=<tool>/oauth/callback
```

Optional hardening: run `uv run utils/configure_oauth.py --enforce-scopes --write-env`
and set `CANVAS_OAUTH_SCOPES` to the space-separated list printed by the script
(see [app/canvas_oauth_scopes.py](../app/canvas_oauth_scopes.py)).

---

## 5. Verify

From the EasyLearn repo root, with `keys/` generated (see the
[README](../README.md) quickstart):

```bash
uv run utils/check_setup.py
```

This confirms your `.env`, RSA keys, `lti_config.json` issuer match, JWKS
generation, Canvas connectivity, and OAuth mode. Resolve any `FAIL` lines before
launching.

---

## Next steps

- Sync the LTI registration URLs and enable new-tab launch:
  `uv run utils/configure_lti.py` (see [cli.md](./cli.md)).
- Understand the launch + auth flow: [lti-and-oauth.md](./lti-and-oauth.md).
- Run a live demo: [demo.md](./demo.md).
- Test with multiple users: [testing.md](./testing.md).
