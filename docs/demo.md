# Local demo runbook

A start-to-finish script for demonstrating EasyLearn to a professor on a local
machine: stand up Canvas, generate a realistic course with AI, launch as a
teacher, and generate and deploy a quiz back into Canvas.

Budget ~30 minutes the first time (most of it Canvas's initial build).

---

## Prerequisites

- Canvas running locally and an admin API token — see
  [canvas-setup.md](./canvas-setup.md).
- EasyLearn dependencies installed and `.env` populated — see the
  [README](../README.md) quickstart.
- A model provider key in `.env` (`GEMINI_API_KEY` or `OPENROUTER_API_KEY`).
- Both Developer Keys created (LTI + API/OAuth) — see
  [canvas-setup.md](./canvas-setup.md).

Confirm the environment is healthy:

```bash
uv run utils/check_setup.py
```

---

## Step 1 — create a teacher account

```bash
uv run utils/setup_canvas_test_users.py
```

This creates `teacher1@example.com` (and others). You will log into Canvas as
this teacher for the demo.

## Step 2 — generate a populated demo course

Pick a topic relevant to your audience. This generates the course, modules, and
slide decks, and enrolls the teacher:

```bash
uv run utils/generate_demo_course.py \
  --topic "Introduction to Databases" \
  --modules 4 \
  --enroll-teacher
```

The command prints the new **course id** and URL. Launch EasyLearn from that
course in Canvas (course id comes from the LTI session automatically).

> Preview the generated outline and decks without touching Canvas using
> `--dry-run`; decks are written to `cache/demo_course/`.

## Step 3 — sync the LTI registration

```bash
uv run utils/configure_lti.py
```

This points the registration at `EASYLEARN_PUBLIC_URL` and sets the course-nav
placement to open in a new tab (required for local cross-site cookies).

## Step 4 — start EasyLearn

```bash
docker compose up -d --build
# or: uv run main.py
```

## Step 5 — launch from Canvas as the teacher

1. In a fresh browser profile, log into Canvas as `teacher1@example.com`.
2. Open the generated course and click **EasyLearn** in the course navigation.
3. It opens in a new tab. Approve the Canvas OAuth authorization when prompted.
4. The dashboard loads scoped to the teacher and course.

## Step 6 — generate and deploy a quiz

1. The dashboard lists modules with PDF/PPTX material (the generated decks).
2. Select a module's deck, choose question counts and a model, and **Generate**.
3. Review the draft, then **Deploy** to push it into the Canvas module.
4. Open the quiz in Canvas to show it landed as a real Canvas quiz.

---

## What this demonstrates

- **Enterprise LTI**: the professor launches from their own Canvas course and
  authorizes individually — quizzes are created with their permissions, not a
  shared admin token (see [lti-and-oauth.md](./lti-and-oauth.md)).
- **Material to quiz**: EasyLearn reads real slide content and produces
  structured, type-correct questions.
- **Round trip**: generated quizzes are deployed back into Canvas modules,
  ready to publish.

---

## Reset between runs

- Delete the demo course in Canvas (or generate a new one with a different
  `--topic`).
- Clear local drafts/material: remove the relevant folders under `cache/`.
- Quiz drafts are per course, so a new course id starts clean.
