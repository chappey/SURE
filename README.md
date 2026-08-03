# EasyLearn

**EasyLearn** is an LTI 1.3 web application for Canvas LMS that enables instructors to generate, customize, and deploy structured quizzes from Canvas course materials (PDF/PPTX) using AI models (Google Gemini or OpenRouter).

Instructors launch EasyLearn directly from the Canvas course navigation sidebar, authorize per-professor OAuth access, pick module materials, preview/edit AI-generated quiz drafts, and deploy them into Canvas modules.

---

## Key Features

- **LTI 1.3 & Canvas Native Integration**: Launches directly inside Canvas with course context and instructor roles.
- **Per-Professor OAuth2 Authorization**: Strictly scoped per-instructor access without shared global API tokens.
- **Multi-Format Material Extraction**: Extracts text from PDF and PPTX slide decks attached to Canvas course modules.
- **Configurable Quiz Generation**: Generates Multiple Choice, True/False, and Matching questions using Google Gemini or OpenRouter.
- **Direct Canvas Deployment**: Deploys structured quizzes straight back into Canvas course modules for immediate student use.
- **DevOps Readiness**: Includes container health endpoints (`/healthz` and `/readyz`) and Docker Compose deployment configs.

---

## Repository Map

| Directory / File | Purpose |
|------------------|---------|
| `main.py` | FastAPI application entrypoint, middleware, health routes |
| `app/` | Core application logic (Canvas API, LTI 1.3 adapter, quiz generation, disk storage) |
| `app/routers/` | FastAPI route modules (`api`, `lti_routes`, `oauth`, `pages`) |
| `templates/` & `static/` | Dashboard HTML SPA templates, CSS styles, and JavaScript client logic |
| `config/` | LTI tool registration configuration (`lti_config.json`) |
| `keys/` | RSA keypair directory (`private.key`, `public.key`) for LTI signing |
| `cache/` | Local file cache and saved quiz drafts |
| `utils/` | Setup tools (`configure_lti.py`, `configure_oauth.py`) |
| `docs/deployment.md` | Comprehensive DevOps Deployment & Canvas Registration Guide |

---

## Quickstart & Deployment

For full deployment instructions, Canvas LTI 1.3 / OAuth Developer Key setup, and Docker Compose configurations, see the **[DevOps Deployment Guide](docs/deployment.md)**.

### Local Development

1. **Install Dependencies**:
   ```bash
   uv sync
   ```

2. **Configure Environment & Keys**:
   ```bash
   cp .env.example .env
   cp config/lti_config.example.json config/lti_config.json
   ```

3. **Generate RSA Signing Keys**:
   ```bash
   mkdir -p keys
   openssl genrsa -out keys/private.key 2048
   openssl rsa -pubout -in keys/private.key -out keys/public.key
   ```

4. **Run Application**:
   ```bash
   uv run main.py
   ```

   The app will run on `http://localhost:8000`. Launch EasyLearn from Canvas course navigation as an instructor.

---

## Documentation

- **DevOps Deployment Guide**: [docs/deployment.md](docs/deployment.md)
- **Agent Guardrails**: [AGENTS.md](AGENTS.md)
