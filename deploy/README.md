# Deployment

Production deployment uses **Docker Compose** at the repository root.

```bash
cp .env.example .env          # fill secrets
cp config/lti_config.example.json config/lti_config.json
docker compose up -d --build
```

Public ingress via Cloudflare Tunnel:

```bash
# TUNNEL_TOKEN in .env, then:
docker compose --profile tunnel up -d --build
```

Full guide: [docs/deployment.md](../docs/deployment.md).
