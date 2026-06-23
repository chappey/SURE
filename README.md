# EasyLearn

EasyLearn is an LTI 1.3 compliant web application and suite of CLI tools designed to generate structured quizzes from Canvas course exports and slide decks (PDF/PPTX) using configurable AI models (Google Gemini and OpenRouter), and deploy them directly back to Canvas courses.

The project features a FastAPI-based dashboard backend and integration with Canvas using the LTI 1.3 Advantage protocol.

---

## Quickstart

### Running the Web Application

#### 1. Prerequisites
- Python >= 3.14
- `uv` package manager
- `openssl` (for generating LTI keys)

#### 2. Install Dependencies
Initialize the Python virtual environment and install packages defined in [pyproject.toml](./pyproject.toml):
```bash
uv sync
```

#### 3. Configure Environment Variables
Create a `.env` file in the project root:
```ini
# Canvas API Config
CANVAS_API_URL=https://canvas.instructure.com
CANVAS_API_TOKEN=your_canvas_api_token
CANVAS_COURSE_ID=123456

# Gemini LLM Config (Google AI Studio — default model in config/ai_models.json)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

# OpenRouter (optional fallback models — see config/ai_models.json)
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_HTTP_REFERER=https://your-app-domain.com
OPENROUTER_APP_NAME=EasyLearn

# Path to local offline course export directory (relative to project root or absolute)
COURSE_EXPORT_DIR=Spring-2026-COMPUTER-SCIENCE-PRINCIPLES-CS-10051-600--2026-May-27_17-59-33-518

# Starlette session encryption key
SESSION_SECRET_KEY=generate-a-secure-random-string
```

#### 4. Generate RSA Keypair
Canvas LTI 1.3 authentication requires an RSA keypair. Generate them in the `keys` directory:
```bash
mkdir -p keys
openssl genrsa -out keys/private.key 2048
openssl rsa -pubout -in keys/private.key -out keys/public.key
```

#### 5. Configure LTI Tool JSON
Update the [config/lti_config.json](./config/lti_config.json) configuration mapping. Set the correct `client_id` and `deployment_ids` generated during the Canvas installation process:
```json
{
  "https://canvas.instructure.com": [
    {
      "default": true,
      "client_id": "YOUR_DEVELOPER_KEY_CLIENT_ID",
      "auth_login_url": "https://canvas.instructure.com/api/lti/authorize_redirect",
      "auth_token_url": "https://canvas.instructure.com/login/oauth2/token",
      "key_set_url": "https://canvas.instructure.com/api/lti/security/jwks",
      "private_key_file": "../keys/private.key",
      "public_key_file": "../keys/public.key",
      "deployment_ids": ["YOUR_DEPLOYMENT_ID"]
    }
  ]
}
```

#### 6. Start the Web Server
Launch the FastAPI application:
```bash
uv run main.py
```
The server will bind to `http://0.0.0.0:8000`.

---

### Installing the LTI Tool in Canvas

To deploy this application as an external tool inside Canvas:

#### 1. Register an LTI Developer Key
1. Log in to your Canvas instance as an administrator (or sub-account admin).
2. Go to **Admin** > **Developer Keys**.
3. Select **+ Developer Key** > **+ LTI Key**.
4. Configure the following parameters:
   - **Key Name**: EasyLearn Quiz Generator
   - **Owner Email**: admin@yourdomain.com
   - **Method**: Manual Entry
   - **Redirect URIs**: `https://<your-tool-domain>/launch`
   - **Target Link URI**: `https://<your-tool-domain>/launch`
   - **OpenID Connect Initiation Url**: `https://<your-tool-domain>/login`
   - **JWK Method**: Public JWK URL
   - **Public JWK URL**: `https://<your-tool-domain>/jwks`
   - **Placements**: Course Navigation (or Account Navigation)
5. Save the configuration and set the key state toggle to **ON**.
6. Copy the numeric **Client ID** listed under the *Details* column.

#### 2. Install the App in Canvas
1. Go to your Canvas course page (or account level settings).
2. Select **Settings** > **Apps** > **View App Configurations**.
3. Click **+ App**.
4. Set **Configuration Type** to **By Client ID**.
5. Paste your copied **Client ID** and click **Submit**.
6. Click **Install** to confirm.
7. Locate the newly installed app in the list, click the cog icon, choose **Deployment Info**, and copy the **Deployment ID**.
8. Append the Deployment ID to the `"deployment_ids"` list in [config/lti_config.json](./config/lti_config.json).

---

## Technical Details

### Architecture and Technology Stack
EasyLearn is built on a structured Python package architecture centered around FastAPI, the LTI 1.3 Advantage protocol, and pluggable LLM providers:

- **Web Server & Routing**: [main.py](./main.py) uses **FastAPI** to implement high-performance ASGI endpoints. Route handling includes:
  - `/login` redirects authentication initiation to Canvas OIDC.
  - `/launch` validates incoming signed POST claims.
  - `/jwks` serves the public JSON Web Key Set.
  - `/` serves the dark-themed HTML/JS interactive dashboard.
- **Application Package (`app/`)**: Reusable logic is encapsulated cleanly in the `app` package:
  - [app/lti.py](./app/lti.py) extends `pylti1p3` classes to support FastAPI context.
  - [app/config.py](./app/config.py) centralizes settings loaded from `.env`.
  - [app/canvas.py](./app/canvas.py) handles Canvas API client initialization.
  - [app/schemas.py](./app/schemas.py) holds Pydantic schemas (`WeeklyQuiz`, etc.) for structured quiz output.
  - [app/extraction.py](./app/extraction.py) handles document parsing using `pypdf` and `python-pptx`.
  - [app/generation.py](./app/generation.py) routes quiz generation to Gemini or OpenRouter based on the model catalog.
  - [app/llm/](./app/llm/) contains the model catalog loader, provider adapters, and unified error formatting.
  - [app/deployment.py](./app/deployment.py) manages quiz creation and module linkage in Canvas.

### AI model catalog

Quiz generation models are curated in [config/ai_models.json](./config/ai_models.json). Each entry includes:

- `id` — sent by the dashboard when generating (`model_id`)
- `label` — shown in the model dropdown
- `provider` — `gemini` (native Google AI Studio SDK) or `openrouter` (OpenAI-compatible API)
- `model` — provider-specific model string
- `default` — optional; marks the default selection
- `structured_output` — `native` or `best_effort` (internal; controls provider fallback behavior)

Professors pick a model from the dashboard dropdown. If Gemini returns a 503/high-demand error, switch to an OpenRouter fallback (e.g. NVIDIA Nemotron free tier) without redeploying — as long as `OPENROUTER_API_KEY` is configured.

To add a model, edit `config/ai_models.json` and restart the server. Models whose provider API key is missing appear disabled in the UI.

---

### Command-Line Interface Utilities
A suite of CLI tools exists under the `utils/` directory to manage and verify offline course exports and API connectivity.

- **[utils/verify_canvas.py](./utils/verify_canvas.py)**: Test your Canvas API endpoint and credentials.
  - Usage: `uv run utils/verify_canvas.py`
- **[utils/create_course_from_export.py](./utils/create_course_from_export.py)**: Recreates Canvas course modules and uploads slide and PDF attachments parsing the offline export `course-data.js` mapping.
  - Usage: `uv run utils/create_course_from_export.py [--dry-run] [--course-id <id>]`
- **[utils/generate_weekly_quiz.py](./utils/generate_weekly_quiz.py)**: The complete quiz generation pipeline. Extracts text for a selected week, validates text length, generates a quiz with the selected model from the catalog, validates question rules, and publishes it to the specified Canvas course module.
  - Usage: `uv run utils/generate_weekly_quiz.py --week <number_or_label> [--model-id nemotron-3-ultra-free] [--dry-run]`
