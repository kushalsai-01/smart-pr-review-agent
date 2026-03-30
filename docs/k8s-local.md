# Local Kubernetes Verification (kind)

## Prerequisites

- Docker Desktop running
- `kubectl` installed
- `kind` installed

## 1) Build the backend Docker image

Tag it locally so kind can load it without pulling from GHCR:

```bash
docker build -f backend/Dockerfile -t pr-review-agent-backend:local .
```

## 2) Create a local kind cluster

```bash
kind create cluster
```

## 3) Load the image into the kind cluster

```bash
kind load docker-image pr-review-agent-backend:local
```

## 4) Create Kubernetes Secrets for runtime env vars

Create the backend app secret referenced by `k8s/deployment.yaml`:

```bash
kubectl create secret generic smart-pr-review-bot-secrets \
  --from-literal=GROQ_API_KEY="YOUR_GROQ_API_KEY" \
  --from-literal=GITHUB_APP_ID="3222129" \
  --from-literal=GITHUB_PRIVATE_KEY="$(cat path/to/private-key.pem)" \
  --from-literal=GITHUB_WEBHOOK_SECRET="YOUR_WEBHOOK_SECRET" \
  --from-literal=DATABASE_URL="" \
  --from-literal=LANGCHAIN_API_KEY="YOUR_LANGCHAIN_API_KEY" \
  --from-literal=LANGSMITH_PROJECT="smart-pr-review-agent" \
  --from-literal=CHROMA_PERSIST_DIR="/app/chroma" \
  --from-literal=GITHUB_MCP_URL="https://api.githubcopilot.com/mcp/" \
  --from-literal=FRONTEND_URL="http://localhost:5173"
```

## 5) Apply Kubernetes manifests

Update the image tag for local testing:

```bash
kubectl -n default set image deployment/smart-pr-review-bot-api api=pr-review-agent-backend:local
```

Then apply:

```bash
kubectl -n default apply -f k8s/service.yaml
kubectl -n default apply -f k8s/deployment.yaml
```

## 6) Validate `/health`

Get the pod name:

```bash
kubectl -n default get pods -l app=smart-pr-review-bot-api
```

Forward a local port:

```bash
kubectl -n default port-forward svc/smart-pr-review-bot-api 8000:80
```

Test:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

## Notes

- `/review` requires valid GitHub App keys and `GROQ_API_KEY`.
- If `DATABASE_URL` is empty, the backend falls back to in-memory checkpointing, which is fine for smoke testing.

