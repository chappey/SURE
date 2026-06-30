# CLI utilities

Command-line tools under [utils/](../utils/). All load configuration from `.env`
via `app.config` and are run with `uv run`. Most Canvas tools require
`CANVAS_API_URL` and an admin `CANVAS_API_TOKEN`.

---

## Setup and configuration

### `check_setup.py` — preflight doctor

Validates everything a fresh clone needs before launch: `.env`, RSA keys,
`config/lti_config.json` issuer match, JWKS generation, Canvas connectivity, and
OAuth mode. Prints a pass/fail checklist.

```bash
uv run utils/check_setup.py
uv run utils/check_setup.py --skip-canvas   # offline checks only
```

### `configure_lti.py` — sync the LTI registration

Updates the Canvas LTI registration to use `EASYLEARN_PUBLIC_URL` for the tool
URLs and opens the course-navigation placement in a new tab (required for local
cross-site cookies). Requires an admin token.

```bash
uv run utils/configure_lti.py                  # full URL + new-tab sync
uv run utils/configure_lti.py --new-tab-only   # only set windowTarget=_blank
uv run utils/configure_lti.py --registration-id 2 --account-id 1
```

### `configure_oauth.py` — create the OAuth API Developer Key

Creates or updates the **EasyLearn API** Developer Key (separate from LTI),
sets the OAuth redirect URI, and turns the key on for the account. By default
does not enforce scopes — professors get API access matching their Canvas role.

```bash
uv run utils/configure_oauth.py --write-env
uv run utils/configure_oauth.py --enforce-scopes --write-env   # optional least-privilege
```

Requires an admin `CANVAS_API_TOKEN`. See [canvas-setup.md](./canvas-setup.md).

---

## Users and courses

### `setup_canvas_test_users.py` — provision test users

Creates and enrolls default teacher/student accounts in a course.

```bash
uv run utils/setup_canvas_test_users.py --course-id <id> --publish
uv run utils/setup_canvas_test_users.py --password '<custom>'
```

### `generate_demo_course.py` — AI-generated demo course

Generates a structured course outline with the configured LLM, renders one
`.pptx` lecture deck per module, and creates the Canvas course, modules, and file
attachments — leaving material EasyLearn can immediately quiz on. Requires a
model provider key (`GEMINI_API_KEY` or `OPENROUTER_API_KEY`).

```bash
uv run utils/generate_demo_course.py --topic "Introduction to Databases"
uv run utils/generate_demo_course.py --topic "Networking" --modules 4 --enroll-teacher
uv run utils/generate_demo_course.py --topic "Astrophysics" --dry-run   # decks only, no Canvas
uv run utils/generate_demo_course.py --topic "Algorithms" --course-id 5 # populate existing course
```

Key flags: `--modules N`, `--slides-per-module N`, `--model-id <id>`,
`--course-id <id>`, `--enroll-teacher`, `--dry-run`, `-v`.

### `create_course_from_export.py` — import an offline export

Recreates a course's modules and uploads PDF/PPTX attachments from an offline
Canvas export directory.

```bash
uv run utils/create_course_from_export.py path/to/export --dry-run
uv run utils/create_course_from_export.py path/to/export --course-id <id>
uv run utils/create_course_from_export.py path/to/export --skip-empty-modules
```

---

## Quiz generation

### `generate_weekly_quiz.py` — offline quiz pipeline

Extracts text for a selected week/module, generates a quiz with a catalog model,
validates it, and publishes it to a Canvas course module.

```bash
uv run utils/generate_weekly_quiz.py --export-dir path/to/export --week 3 --course-id <id>
uv run utils/generate_weekly_quiz.py --export-dir path/to/export --week 3 --course-id <id> --dry-run
```

---

## Assets

### `generate_logo_assets.py` — raster logo/favicon

Regenerates `static/logo.png` and `static/favicon.ico` from the bundled logo.
Rarely needed.

```bash
uv run utils/generate_logo_assets.py
```
