# EasyLearn

EasyLearn is an LTI 1.3 compliant web application and suite of CLI tools designed to generate structured quizzes from Canvas course exports and slide decks (PDF/PPTX) using Gemini LLMs, and deploy them directly back to Canvas courses.

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

# Gemini LLM Config
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

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
EasyLearn is built on a modern Python stack centered around ASGI web serving, LTI handshake, and structured LLM integrations:

- **Web Server & Routing**: [main.py](./main.py) uses **FastAPI** to implement high-performance async endpoints. Route handling includes:
  - `/login` (`lti_login`) redirects authentication initiation to Canvas OIDC.
  - `/launch` (`lti_launch`) validates incoming signed POST claims.
  - `/jwks` (`get_jwks`) serves the public JSON Web Key Set matching the RSA keys.
  - `/` (`get_dashboard`) serves the dark-themed HTML/JS interactive dashboard.
- **LTI FastAPI Adapter**: [pylti1p3_fastapi.py](./pylti1p3_fastapi.py) extends `pylti1p3` classes to support FastAPI context. Key adaptations:
  - `FastAPIRequest` wrappers mapping FastAPI HTTP Request parameters.
  - `FastAPICookieService` and `FastAPIRedirect` handling cookie propagation and redirect structures under ASGI.
  - `InMemoryDataStorage` handling basic session states during OIDC transactions.
- **Structured Content Generation**: Uses the `google-genai` SDK via [scripts/quiz_generate.py](./scripts/quiz_generate.py) to interact with `gemini-2.5-flash`. The LLM's response schema is explicitly constrained using Pydantic models defined in [scripts/quiz_schema.py](./scripts/quiz_schema.py):
  - `WeeklyQuiz` holds a collection of `GeneratedQuestion` models containing multiple-choice or true-false questions and `GeneratedAnswer` objects.
- **Document Text Extraction**: Course materials are parsed using specialized libraries in [scripts/material_extract.py](./scripts/material_extract.py):
  - `pypdf` (`extract_pdf_text`) extracts text from PDFs.
  - `python-pptx` (`extract_pptx_text`) compiles paragraphs and shapes slide-by-slide from PowerPoints.

---

### Command-Line Interface Utilities
A suite of CLI tools exists under the `scripts/` directory to manage and verify offline course exports and API connectivity.

- **[scripts/verify_canvas.py](./scripts/verify_canvas.py)**: Test your Canvas API endpoint and credentials set in `.env`.
- **[scripts/create_course_from_export.py](./scripts/create_course_from_export.py)**: Recreates Canvas course modules and uploads slide and PDF attachments parsing the offline export `course-data.js` mapping.
  - Usage: `uv run scripts/create_course_from_export.py [--dry-run] [--course-id <id>]`
- **[scripts/generate_weekly_quiz.py](./scripts/generate_weekly_quiz.py)**: The complete quiz generation pipeline. Extracts text for a selected week, validates text length, generates a quiz with Gemini structured JSON outputs, validates question rules, and publishes it to the specified Canvas course module.
  - Usage: `uv run scripts/generate_weekly_quiz.py --week <number_or_label> [--dry-run]`
