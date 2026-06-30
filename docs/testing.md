# Multi-user testing

How to verify EasyLearn end to end on a local Canvas, including per-professor
isolation. Prerequisites: Canvas running and configured per
[canvas-setup.md](./canvas-setup.md), and `uv run utils/check_setup.py` passing.

---

## 1. Provision test users

Create and enroll teacher/student accounts in a course:

```bash
uv run utils/setup_canvas_test_users.py --course-id <id> --publish
```

This creates the default users below (override the password with `--password`):

| Login | Role |
|-------|------|
| `teacher1@example.com` | Teacher |
| `teacher2@example.com` | Teacher |
| `student1@example.com` | Student |

The default password is defined by `DEFAULT_PASSWORD` in the script. Use
throwaway credentials on local instances only; never reuse real passwords.

---

## 2. Launch as each user

Use **separate browser profiles or incognito windows** so sessions do not mix.

1. Log into Canvas as `teacher1@example.com`.
2. Open the course and click **EasyLearn** in the course navigation.
3. On localhost it opens in a **new tab** (required for cross-site cookies — see
   [lti-and-oauth.md](./lti-and-oauth.md)).
4. If OAuth is configured, approve the Canvas authorization prompt.
5. Repeat as `teacher2@example.com` in a different profile and confirm the
   sidebar shows a different identity.

Students: with a teacher-only placement, `student1@example.com` should not see
EasyLearn. If a student reaches the API, `require_teacher` returns `403`.

---

## 3. Verification checklist

- [ ] `curl http://localhost:8000/jwks` returns a JSON key set.
- [ ] Course navigation shows **EasyLearn**.
- [ ] Teacher1 launch shows Teacher1's name; Teacher2 (other profile) shows
      Teacher2's.
- [ ] `GET /api/session` reports the expected `auth_mode`
      (`oauth` once authorized; `lti_dev` without OAuth).
- [ ] `GET /api/courses` returns the teacher's courses.
- [ ] Generate + deploy a quiz on a module with PDF/PPTX material.

---

## 4. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| "Browser prohibits cookies in iframes" | Launch in a new tab (`utils/configure_lti.py --new-tab-only`); see [lti-and-oauth.md](./lti-and-oauth.md) |
| LTI validation fails on `/launch` | Issuer/`client_id`/`deployment_ids` in `config/lti_config.json` must match the Canvas registration; re-run `utils/check_setup.py` |
| `iss https://canvas.instructure.com not found` | Canvas sends this issuer for custom domains; [app/lti_config.py](../app/lti_config.py) auto-aliases it from your `CANVAS_PUBLIC_URL` entry — restart EasyLearn after profile switch |
| Wrong or missing course id | Add the LTI custom field `canvas_course_id=$Canvas.course.id` to the key |
| Empty course list for a teacher | Enroll the user as **Teacher** and publish the course |
| OAuth configured but `401` | Complete the OAuth consent after launch; `CANVAS_OAUTH_REDIRECT_URI` must exactly equal `<tool>/oauth/callback` |
| `403` on API for a valid user | The session role is not a teaching role; relaunch from Canvas as a teacher |
| Token expired mid-session | Expected after ~1h; EasyLearn refreshes automatically (see [lti-and-oauth.md](./lti-and-oauth.md)) — re-authorize if refresh fails |

---

## Security

Never commit `.env`, API tokens, or `keys/*.key`. Rotate any token or password
that was shared in logs or chat. Treat `cache/` (course material + quiz drafts)
as confidential.
