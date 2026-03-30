# Smart PR Review Agent
## Architecture
```mermaid
flowchart TD
    UI["Frontend — React + Vite\nPR URL · Mode selector · Live feed · Diff viewer"]
    API["FastAPI Backend — Render\n/review · /stream · /approve · /health"]
    LG["LangGraph Workflow\nreview_only · human_in_loop · auto_pilot"]
    IDX["Indexer\ntree-sitter + ChromaDB"]
    REV["Reviewer\ninline PR comments"]
    BUG["Bug Hunter\ndeep RAG search"]
    ISS["Issue Raiser\nGitHub issues"]
    FIX["Fix Drafter\npatch + run tests"]
    MCP["GitHub MCP\nremote server"]
    CHROMA["ChromaDB\nvector store"]
    GROQ["Groq LLM\nllama-3.3-70b"]
    SMITH["LangSmith\nfull traces"]
    PG["Supabase\nPostgres checkpoints"]
    GH["GitHub App\nsmart-pr-review-bot"]

    UI -->|SSE / HTTP| API
    API --> LG
    LG --> IDX
    LG --> REV
    LG --> BUG
    LG --> ISS
    LG --> FIX
    IDX --> CHROMA
    REV --> GROQ
    BUG --> CHROMA
    BUG --> GROQ
    FIX --> GROQ
    API --> MCP
    MCP --> GH
    LG --> PG
    REV --> SMITH
    BUG --> SMITH
    FIX --> SMITH

    style UI fill:#185FA5,color:#fff
    style API fill:#0F6E56,color:#fff
    style LG fill:#534AB7,color:#fff
    style IDX fill:#854F0B,color:#fff
    style REV fill:#854F0B,color:#fff
    style BUG fill:#854F0B,color:#fff
    style ISS fill:#854F0B,color:#fff
    style FIX fill:#854F0B,color:#fff
    style MCP fill:#3B6D11,color:#fff
    style CHROMA fill:#3B6D11,color:#fff
    style GROQ fill:#3B6D11,color:#fff
    style SMITH fill:#3B6D11,color:#fff
    style PG fill:#5F5E5A,color:#fff
    style GH fill:#5F5E5A,color:#fff
```

FastAPI backend with LangGraph workflow, GitHub App integration, and a Vite + React UI.

Smart PR review that streams agent progress via SSE and can pause for human approval before drafting and testing fixes.

## Setup
1. Copy `.env.example` to `.env` and set these values:
   - `GROQ_API_KEY`
   - `GITHUB_PRIVATE_KEY` (PEM)
   - `GITHUB_WEBHOOK_SECRET`
   - `DATABASE_URL`
   - `LANGCHAIN_API_KEY`
2. Backend:
   - `pip install -r requirements.txt`
   - `uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`
3. Frontend:
   - `cd frontend`
   - `npm install`
   - `npm run dev`

## API
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health + graph readiness |
| `POST` | `/review` | Starts a review workflow (returns `thread_id`) |
| `GET` | `/stream/{thread_id}` | SSE stream of agent step events |
| `POST` | `/approve` | Approve/reject in `human_in_loop` mode |
| `POST` | `/webhook` | GitHub webhook trigger for PR events |

## Architecture

```mermaid
flowchart TD
  User[User] --> Frontend[Frontend React UI]
  Frontend -->|POST /review| API[FastAPI backend]
  API -->|thread_id| LangGraph[LangGraph workflow]
  LangGraph --> Indexer[Index repository + tree-sitter chunks]
  Indexer --> Chroma[Chroma vector store]
  LangGraph --> Reviewer[Groq PR review + confidence]
  Reviewer -->|low confidence| BugHunter[Groq bug hunting]
  BugHunter --> IssueRaiser[Create GitHub issues]
  IssueRaiser --> Human[Interrupt for human approval]
  Human -->|approved| FixDraft[Groq patch draft + apply + tests]
  Human -->|rejected| End[Stop]
  FixDraft --> Frontend
  API -->|GET /stream/{thread_id}| FrontendStream[SSE events]
```

## Deploy

### Backend (Render)
1. Use `render.yaml` for the `smart-pr-review-bot-api` service.
2. Set Render environment variables matching `.env.example`.
3. Start command is `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.

### Frontend (Vercel)
1. Use `vercel.json` to build from `frontend/` into `frontend/dist`.
2. SPA routing rewrites all routes to `index.html`.

### Backend (Kubernetes via GitHub Actions)

This repo includes a CI/CD pipeline for the backend using Docker + GHCR + Kubernetes:

1. CI on PRs: `.github/workflows/ci.yml`
2. Build + push backend image on `main`: `.github/workflows/build-push.yml`
3. Deploy to Kubernetes on `main`: `.github/workflows/deploy.yml`

Kubernetes manifests:

- Deployment: `k8s/deployment.yaml`
- Service: `k8s/service.yaml`
- Secret template: `k8s/secret.yaml.example`

Secrets to configure in GitHub Actions (for the deploy workflow):

- `KUBECONFIG_B64`: base64-encoded kubeconfig for cluster access
- `GHCR_TOKEN` (optional): token used to create `ghcr-pull-secret` for private image pulls

Kubernetes runtime secrets:

- Create `smart-pr-review-bot-secrets` from `k8s/secret.yaml.example` (or create the Secret manually with the same keys).

About GitHub App attribution in `contributors`:

- `contributors` is derived from commit author identity.
- If the GitHub App creates commits (using its installation token) those commits will attribute to the GitHub App/bot user, and the bot will appear in `contributors`.
- For PR merges, GitHub merge methods can change how authorship is represented in history:
  - “Merge commit” preserves commit authors.
  - “Squash and merge” creates a new commit and typically attributes the squash commit to the merge author instead of individual commit authors.

## Demo

Replace `./docs/demo.gif` with your demo animation.
