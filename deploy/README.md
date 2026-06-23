# Deploy Checklist (Future — Not Implemented)

This directory is a placeholder for when/if EasyLearn is deployed to a production `.edu` subdomain. **No deploy infrastructure exists yet.**

## Prerequisites

- [ ] Subdomain allocated (e.g. `easylearn.university.edu`)
- [ ] TLS certificate (campus CA or Let's Encrypt)
- [ ] Hosting decision (Docker on VM, etc.)

## Configuration

- [ ] Copy `.env.example` → production env; fill all values
- [ ] Generate strong `SESSION_SECRET_KEY` (not the dev default)
- [ ] Set `CANVAS_OAUTH_REDIRECT_URI` to `https://<subdomain>/oauth/callback`
- [ ] Mount RSA keys from `keys/` (read-only)
- [ ] Persistent storage for `cache/`

## Canvas / LTI

- [ ] Register LTI Developer Key — see [README.md](../README.md)
- [ ] URLs: `https://<subdomain>/login`, `/launch`, `/jwks`
- [ ] Custom field: `canvas_course_id=$Canvas.course.id`
- [ ] Update `config/lti_config.json` with Canvas issuer URL, client ID, deployment ID
- [ ] Review [docs/embedding.md](../docs/embedding.md) for iframe vs new-tab launch

## Smoke tests

- [ ] `curl https://<subdomain>/jwks` returns JWK set
- [ ] LTI launch from a test Canvas course succeeds
- [ ] OAuth flow works (if using multi-instructor mode)
- [ ] Quiz generate + deploy round-trip on test course

## Known constraints

- Run **single worker** until LTI in-memory storage is replaced (see `.cursor/rules/04-lti-canvas.mdc`)
- HTTPS required for session cookies
