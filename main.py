import sys
import pylti1p3_fastapi
sys.modules['pylti1p3.contrib.fastapi'] = pylti1p3_fastapi

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from pylti1p3.contrib.fastapi import FastAPIOIDCLogin, FastAPILTIRequest
from pylti1p3.tool_config import ToolConfJsonFile
import os

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "some-very-secret-key-change-in-production"),
    same_site="none",
    https_only=True,
)

@app.get("/")
def get_dashboard():
    """Serves the interactive quiz generation dashboard."""
    dashboard_path = os.path.join(os.path.dirname(__file__), 'templates', 'dashboard.html')
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config', 'lti_config.json')
tool_conf = ToolConfJsonFile(CONFIG_PATH)

@app.get("/jwks")
def get_jwks():
    """Exposes the public key block so Canvas can authenticate the tool."""
    return JSONResponse(content=tool_conf.get_jwks())

@app.get("/login")
@app.post("/login")
async def lti_login(request: Request):
    """Step 1: Core OIDC Login Initiation redirection wrapper."""
    form_data = {}
    if request.method == "POST":
        form_data = await request.form()
    request_data = {**request.query_params, **form_data}

    oidc_login = FastAPIOIDCLogin(request, tool_conf, request_data=request_data)
    
    target_link_uri = request.query_params.get('target_link_uri') or request.headers.get('target_link_uri') or request_data.get('target_link_uri')
    if not target_link_uri:
        raise HTTPException(status_code=400, detail="Missing target_link_uri")
        
    return oidc_login.enable_check_cookies().redirect(target_link_uri)

@app.get("/launch")
@app.post("/launch")
async def lti_launch(request: Request):
    """Step 2: Handles the final signed LTI 1.3 Post Launch payload."""
    if request.method == "POST":
        try:
            form_data = await request.form()
            lti_request = FastAPILTIRequest(request, tool_conf, request_data=form_data)
            _ = lti_request.get_launch_data()
        except Exception as e:
            print(f"LTI Validation failed, redirecting anyway: {e}")
            
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
