# Nginx (production)

The production reverse-proxy config — TLS termination, serving the built
frontend, proxying `/api` to the backend, and critically `proxy_buffering
off` on the SSE chat endpoint — is added in Step 13 (Deployment and
demo-proofing) alongside `infra/docker-compose.prod.yml`. The Step 1
development stack (`infra/docker-compose.yml`) talks to the Vite dev server
and FastAPI directly and does not need Nginx.
