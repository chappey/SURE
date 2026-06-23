# Embedding EasyLearn in Canvas (iFrame & Cookies)

Modern browsers restrict third-party cookies (cookies set by an iframe from a domain different from the parent window). Because of this, embedding an LTI tool inside a Canvas iframe will block the OIDC state/nonce cookies and FastAPI session cookies, causing validation to fail with the error:

> Your browser prohibits to save cookies in the iframes. Click here to open content in the new tab.

To address this, apply one of the following integration methods:

---

## Method 1: Load in a New Tab / Window (Recommended)

**Use this for local development** (`localhost:3000` Canvas + `localhost:8000` EasyLearn). Different ports are different sites — browsers block the session cookies LTI needs inside an iframe.

By configuring the LTI Developer Key to launch in a new browser tab, EasyLearn runs first-party and the OIDC handshake succeeds.

### Canvas Configuration Steps:
1. Log in to Canvas as an Administrator.
2. Go to **Admin** > **Developer Keys** (or **Apps** > **EasyLearn** > **Settings**).
3. Edit the **EasyLearn** LTI registration.
4. Under **Course Navigation** placement, set **Window Target** to **New Tab** / `_blank`.
5. Save.

Or from the repo (with `CANVAS_API_TOKEN` in `.env`):

```bash
uv run utils/configure_lti_new_tab.py
```

6. Click **EasyLearn** in the course sidebar — Canvas opens EasyLearn in a new tab instead of an iframe.

---

## Method 2: Configure Same-Domain Hosting (Production Embedding)

If you require the application to be embedded inside the Canvas iframe directly:
1. Host the EasyLearn application on a subdomain of your institution's main Canvas domain.
   * *Example:* If Canvas is hosted on `canvas.university.edu`, host the LTI tool on `easylearn.university.edu`.
2. Because they share the same top-level domain (`university.edu`), browsers will categorize the cookies under first-party context policies and allow them.

---

## Method 3: Docker Canvas (`canvas.docker`)

Use **`http://canvas.docker:3000`** for Canvas and **`http://canvas.docker:8000`** for EasyLearn (add `127.0.0.1 canvas.docker` to `/etc/hosts`).

1. Run `uv run utils/configure_lti_local_dev.py` to sync the Canvas LTI key URLs
2. Restart EasyLearn (`uv run main.py`)
3. Hard-refresh Canvas, click **EasyLearn** in course nav (opens new tab)
4. You may see a brief Canvas login prompt (`prompt=login`) — sign in if asked

EasyLearn rewrites `localhost:8000` LTI URLs to `canvas.docker:8000` and uses `prompt=login` on HTTP so Chromium can complete OIDC ( `prompt=none` fails when Canvas session cookies are `SameSite=Strict` across ports).

---

## Method 4: Local Browser Exceptions (not recommended for production)

If you must use Chrome with iframe embedding on localhost:
* **Chrome:** Go to `chrome://settings/cookies` and choose **"Allow third-party cookies"** (or add `localhost` to the allow list).
* **Safari:** Go to **Preferences** > **Privacy** and disable **"Prevent cross-site tracking"**.

> Do not ask students or teachers to lower browser privacy settings in production. Use Method 1 or Method 2 instead.
