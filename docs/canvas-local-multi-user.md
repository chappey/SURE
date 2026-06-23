# EasyLearn — local Canvas multi-user testing

Guide for self-hosted Canvas at `http://localhost:3000` and EasyLearn at `http://localhost:8000`.

---

## 1. Fix LTI sidebar label (“EasyLearn”)

The course nav label comes from the **LTI Registration** in Canvas, not from EasyLearn code.

Your registration was updated via API to:

| Field | Value |
|-------|--------|
| Registration name | EasyLearn |
| Tool title | EasyLearn |
| Course navigation text | **EasyLearn** |

If the sidebar still shows an old name, hard-refresh Canvas or re-open the course. The deployment on course **3** should already show **EasyLearn**.

### Manual UI path (alternative)

1. **Admin** → **Developer Keys** → open the **EasyLearn** LTI key  
2. Or **Admin** → **Settings** → **Apps** → **View App Configurations** → **EasyLearn** → **Settings**  
3. Set **Course navigation** label to `EasyLearn`  
4. Save

### API path (repeatable)

```bash
# From repo root with CANVAS_API_TOKEN in .env
uv run python - <<'PY'
import json, urllib.request
from app import config

with urllib.request.urlopen(
    urllib.request.Request(
        f"{config.CANVAS_API_URL.rstrip('/')}/api/v1/accounts/1/lti_registrations/2?include[]=configuration",
        headers={"Authorization": f"Bearer {config.CANVAS_API_TOKEN}"},
    )
) as r:
    reg = json.load(r)

cfg = reg["configuration"]
cfg["title"] = "EasyLearn"
cfg["launch_settings"]["text"] = "EasyLearn"
for p in cfg["placements"]:
    if p.get("placement") == "course_navigation":
        p["text"] = "EasyLearn"

body = json.dumps({"name": "EasyLearn", "configuration": cfg}).encode()
req = urllib.request.Request(
    f"{config.CANVAS_API_URL.rstrip('/')}/api/v1/accounts/1/lti_registrations/2",
    data=body,
    method="PUT",
    headers={
        "Authorization": f"Bearer {config.CANVAS_API_TOKEN}",
        "Content-Type": "application/json",
    },
)
urllib.request.urlopen(req)
print("Updated LTI registration")
PY
```

Confirm `config/lti_config.json` matches your Canvas instance:

- Issuer: `http://localhost:3000`
- `client_id`: `10000000000003`
- `deployment_ids`: includes `3:d3a2504bba5184799a38f141e8df2335cfa8206d`

---

## 2. Test user accounts

These accounts were created on your instance (course **CS-10051-600**, id **3**):

| Login | Role | Password |
|-------|------|----------|
| `teacher1@example.com` | Teacher | `EasyLearn123!` |
| `teacher2@example.com` | Teacher | `EasyLearn123!` |
| `student1@example.com` | Student | `EasyLearn123!` |
| `admin@example.com` | Admin (existing) | *(your admin password)* |

Re-create or add users anytime:

```bash
uv run utils/setup_canvas_test_users.py --course-id 3 --publish
```

---

## 3. Start EasyLearn

```bash
cp .env.example .env   # if needed
# CANVAS_API_URL=http://localhost:3000
# CANVAS_API_TOKEN=<admin token for server-side Canvas API>
# CANVAS_COURSE_ID=3

uv run main.py
```

EasyLearn must be reachable at the URLs in the LTI key: `http://localhost:8000/login`, `/launch`, `/jwks`.

---

## 4. Test LTI launch (per user)

Use **separate browser profiles or incognito windows** so sessions do not mix.

1. Log into Canvas as `teacher1@example.com`  
2. Open course **Spring 2026 COMPUTER SCIENCE PRINCIPLES**  
3. Click **EasyLearn** in the left course nav  
4. Click **EasyLearn** in the left course nav — it opens in a **new tab** (required for localhost; see [embedding.md](./embedding.md))  
5. Repeat as `teacher2@example.com` and confirm each gets their own session name in the sidebar  

**Students:** `student1@example.com` can open Canvas but should **not** see EasyLearn as a teacher tool if the placement is teacher-only. If they see it, restrict the LTI placement in Canvas to teachers.

---

## 5. Authentication: two Canvas keys

EasyLearn uses **two separate** Canvas developer keys:

| Key | Purpose | Env vars |
|-----|---------|----------|
| **LTI 1.3 key** | Launch from course nav, course context | `config/lti_config.json` + Canvas LTI registration |
| **OAuth API key** | Per-user Canvas REST API token | `CANVAS_CLIENT_ID`, `CANVAS_CLIENT_SECRET`, `CANVAS_OAUTH_REDIRECT_URI` |

### Without OAuth (dev fallback)

| Layer | Behavior |
|-------|----------|
| **LTI launch** | Sets `user_name`, `lti_sub`, `canvas_course_id` in session |
| **Canvas API** | All calls use shared `CANVAS_API_TOKEN` (admin) |
| **UI** | Sidebar shows LTI name; badge says **LTI · dev API key** |

Quiz drafts on disk are **per course**, not per user — teacher1 and teacher2 share the same JSON files until OAuth + per-user storage is added.

### With OAuth (per-user API)

1. Create a **Canvas API Developer Key** (not the LTI key) with redirect:
   `http://canvas.docker:8000/oauth/callback`
2. Set in `.env`:
   ```ini
   CANVAS_CLIENT_ID=<oauth client id>
   CANVAS_CLIENT_SECRET=<secret>
   CANVAS_OAUTH_REDIRECT_URI=http://canvas.docker:8000/oauth/callback
   CANVAS_PUBLIC_URL=http://canvas.docker:3000
   EASYLEARN_PUBLIC_URL=http://canvas.docker:8000
   ```
3. Restart EasyLearn. `CANVAS_API_TOKEN` remains for CLI/utils; dashboard API routes use OAuth tokens only.
4. Launch flow: **LTI login → OAuth consent → dashboard** (two Canvas steps on HTTP dev — expected).
5. Check identity: `GET /api/session` → `auth_mode: "oauth"`, `canvas_api_source: "user_token"`.

---

## 6. Quick verification checklist

- [ ] Course nav shows **EasyLearn** (not “FastAPI Course App”)  
- [ ] `curl http://localhost:8000/jwks` returns JSON keys  
- [ ] Teacher1 launch shows correct name in sidebar profile  
- [ ] Teacher2 in another browser shows a different profile  
- [ ] `GET /api/courses` returns CS-10051 for teachers  
- [ ] Quiz generate + deploy works on course 3  

---

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| LTI validation / cookie errors | Launch in **new tab**; use **`http://localhost:3000`** in Chromium (not `canvas.docker:3000`); see [embedding.md](./embedding.md) |
| Wrong course id | LTI custom field `canvas_course_id=$Canvas.course.id` on developer key |
| Blank course list for teacher | Enroll user as **Teacher**; publish course |
| Still shows wrong name / "Loading…" | Re-launch from Canvas; check `GET /api/session`; profile no longer uses hardcoded placeholder |
| Still admin for everyone | Expected without OAuth — sidebar shows LTI name but API uses admin token |
| OAuth configured but 401 | Complete OAuth after LTI; redirect URI must match `EASYLEARN_PUBLIC_URL/oauth/callback` exactly |

---

## Security note

Never commit `.env` or API tokens. Rotate any token that was shared in chat or logs.
