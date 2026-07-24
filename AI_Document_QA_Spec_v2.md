# AI Document Q&A System — Build Specification (v2)
**RAG-Based Multi-User Document Intelligence Platform**
Prepared for: Vinit Hudiya | Placement Portfolio Project | RCOEM Nagpur

---

## 1. Why This Project

Most "chat with your PDF" projects on GitHub are a LangChain quickstart wrapped in a Streamlit UI. This spec is deliberately not that — it's a multi-tenant, production-shaped system that touches almost every line item in a current SDE/Full Stack/Data JD in one coherent codebase:

- **Backend:** FastAPI, async Python, REST API design
- **Databases:** PostgreSQL (relational), Qdrant (vector)
- **Retrieval:** Hybrid search (vector + BM25) with reranking — not toy vector-only RAG
- **Caching/Infra:** Redis, rate limiting, Docker, CI-ready structure
- **AI/ML:** embeddings, chunking strategy, hybrid retrieval, multi-provider LLM integration, grounded citations
- **Security:** JWT auth, RBAC, input validation, secrets management
- **Observability:** latency, cost, and error metrics — most portfolio projects skip this entirely
- **Product thinking:** admin dashboard, usage analytics, multi-user isolation, feedback loop

**The interview story:** "I built a RAG system from scratch — hybrid retrieval with reranking, multi-document search, a provider-agnostic LLM layer, and an observability dashboard, not just an API wrapper." Paired with your MySQL-based MarketHub project, this also shows database breadth.

---

## 2. Database Decision: PostgreSQL over MySQL

You used MySQL for MarketHub — use **PostgreSQL** here instead, on purpose:

| Reason | Detail |
|---|---|
| JSONB support | Citations (`[{document, page, snippet}]`) stored per message as queryable JSONB — MySQL's JSON type is weaker for this |
| Async driver maturity | `asyncpg` + SQLAlchemy async is the standard FastAPI pairing |
| Full-text search | Postgres `tsvector`/`ts_rank` gives you a free BM25-style keyword index for hybrid search — no separate keyword engine needed |
| pgvector talking point | "I evaluated pgvector vs a dedicated vector DB and chose Qdrant because payload filtering scales better for multi-tenant isolation" — genuine architecture-tradeoff answer |
| Resume breadth | MySQL (MarketHub) + PostgreSQL (this project) shows you aren't a one-database developer |

---

## 3. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend API | FastAPI (Python 3.11+) | Async-first, auto OpenAPI docs |
| Relational DB | PostgreSQL 15 | JSONB, async support, native full-text search for BM25 leg of hybrid search |
| Cache / Rate Limiter | Redis 7 | Sliding-window rate limiting, token blacklist, metrics counters |
| Vector DB | Qdrant (self-hosted via Docker) | Payload filtering enables clean multi-tenant isolation |
| Keyword Search | Postgres `tsvector` (or `rank_bm25` in-process for small scale) | BM25 leg of hybrid retrieval — free, no extra service |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (local, free, via `sentence-transformers`) | Reranks merged hybrid results — zero API cost |
| Embeddings | **Pluggable** — see §3.1 | Cost-flexible; swappable without touching business logic |
| LLM | **Pluggable** — see §3.1 | Cost-flexible; provider abstraction is itself a talking point |
| Auth | JWT (access + refresh) + bcrypt | Stateless, rotation-based, RBAC-ready |
| File Parsing | PyMuPDF (PDF), `python-docx` (DOCX) | Reliable text + page-level extraction for citations |
| Frontend | See §3.2 — two options, pick one | |
| Observability | Prometheus client + `/metrics` endpoint, or simple Postgres-logged metrics + Recharts | Free, self-hosted, no external APM needed |
| Deployment | Docker Compose → Railway (backend) + Vercel (frontend) | Free-tier friendly |

### 3.1 LLM / Embedding Provider Options (free-first, swappable via `.env`)

Don't hardcode OpenAI. Build one `LLMProvider` interface and one `EmbeddingProvider` interface, then implement adapters. Switch providers with a single env var — this is a stronger interview story than "I used OpenAI."

| Provider | Type | Cost | Notes |
|---|---|---|---|
| **Groq** (Llama 3.1/3.3, Mixtral) | LLM | Free tier, very fast (LPU inference) | Best default for a free portfolio demo |
| **Google Gemini** (`gemini-1.5-flash` / `2.0-flash`) | LLM + Embeddings | Generous free tier | Good second option, also has free embeddings |
| **Ollama** (Llama 3, Phi-3, Mistral — local) | LLM + Embeddings | Fully free, runs on your machine/Docker | Works offline, good "no vendor lock-in" story, slower on CPU |
| **OpenAI** (`gpt-4o-mini`, `text-embedding-3-small`) | LLM + Embeddings | Cheap but paid | Keep as one pluggable option, not the only one |
| **Anthropic Claude Haiku** | LLM | Paid | Already planned as alt — keep |
| **`sentence-transformers`** (`all-MiniLM-L6-v2`, local) | Embeddings | Fully free, local | Best default embedding — no API key needed at all |

**Recommended default for a zero-cost demo:** `sentence-transformers` for embeddings + Groq (or Ollama) for generation. Keep OpenAI/Anthropic wired in as alternates so you can say "provider-agnostic by design" truthfully.

```
app/providers/
├── llm/
│   ├── base.py          # LLMProvider ABC: generate(), stream()
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── groq_provider.py
│   ├── gemini_provider.py
│   └── ollama_provider.py
├── embeddings/
│   ├── base.py           # EmbeddingProvider ABC: embed(texts) -> vectors
│   ├── openai_embed.py
│   ├── gemini_embed.py
│   └── local_embed.py    # sentence-transformers
└── factory.py            # reads PROVIDER env vars, returns configured instance
```

### 3.2 Frontend — Pick One

| Option | When to use |
|---|---|
| **A. Next.js 15 + TypeScript + Tailwind** | If you want SSR, matches your QuickToolz stack, more "production" on resume |
| **B. Plain React (Vite, no Next) + Tailwind** | Faster to build, still resume-worthy as "React SPA", skip SSR complexity |
| **C. Plain HTML + CSS + vanilla JS (fetch + EventSource for SSE)** | Fastest MVP, zero build tooling, fine for a 4-week solo timeline if frontend isn't the focus |

Recommendation: start with **Option C** to get the full pipeline working end-to-end fast, then upgrade to **Option B** once backend is stable, only moving to Next.js if you specifically want the SSR/Vercel story. Don't let frontend choice block backend progress — this project's interview value is 80% backend/RAG/infra.

---

## 4. System Architecture

```
                          ┌─────────────────────┐
                          │  Frontend (A/B/C)     │
                          └──────────┬───────────┘
                                     │ HTTPS
                          ┌──────────▼───────────┐
                          │   FastAPI Backend     │
                          │  ┌─────────────────┐  │
                          │  │ Auth Middleware  │  │
                          │  │ Rate Limiter     │──┼──► Redis (limits, blacklist, metrics)
                          │  │ Error Handler    │  │
                          │  │ Telemetry Hook   │──┼──► /metrics (Prometheus format)
                          │  └────────┬────────┘  │
                          └───────────┼────────────┘
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            Upload Flow         Query Flow         Admin Flow
                    │                 │                 │
        File → Parse → Chunk   Embed question    Aggregate queries,
        → Embed → Store        + BM25 query           costs, latency
                    │                 │                 │
        ┌───────────┼─────┐    ┌──────┴──────┐          ▼
        ▼           ▼     ▼    ▼             ▼      Dashboard
   Postgres     Qdrant  Postgres  Qdrant    Postgres
   (metadata)  (vectors) (FTS)  (vector    (keyword
                                  search)    search)
                                     │             │
                                     └──────┬──────┘
                                            ▼
                                     Merge + Rerank
                                  (cross-encoder, local)
                                            │
                                            ▼
                                  Build context (multi-doc,
                                  filtered by user_id + optional
                                  document_id[] scope)
                                            │
                                            ▼
                                  LLM Provider (pluggable)
                                            │
                                            ▼
                             Answer + citations + cost/latency log
                                  → saved to Postgres
```

---

## 5. Project Structure

**Backend**
```
backend/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py          # env-based settings (pydantic-settings)
│   │   ├── security.py        # JWT, password hashing
│   │   ├── exceptions.py      # custom exception classes
│   │   └── logging.py         # structured logging setup
│   ├── api/v1/
│   │   ├── auth.py
│   │   ├── documents.py
│   │   ├── conversations.py
│   │   ├── admin.py
│   │   ├── health.py          # /health, /metrics
│   │   └── users.py           # /me, /profile, /feedback
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                 # Pydantic request/response schemas
│   ├── providers/               # LLM / embedding adapters (see §3.1)
│   │   ├── llm/
│   │   ├── embeddings/
│   │   └── factory.py
│   ├── repositories/            # DB access layer, isolated from business logic
│   │   ├── document_repo.py
│   │   ├── conversation_repo.py
│   │   └── user_repo.py
│   ├── services/
│   │   ├── ingestion.py
│   │   ├── chunking.py
│   │   ├── hybrid_retrieval.py  # vector + BM25 merge + rerank
│   │   ├── summarization.py     # AI feature: doc/multi-doc summarize
│   │   └── reindex.py           # POST /reindex support
│   ├── dependencies/            # FastAPI Depends() — auth, db session, current_user, rate-limit
│   ├── telemetry/
│   │   ├── metrics.py           # Prometheus counters/histograms
│   │   └── cost_tracker.py      # per-call LLM/embedding token & $ cost logging
│   ├── db/
│   │   ├── session.py
│   │   └── migrations/          # Alembic
│   ├── middleware/
│   │   ├── rate_limit.py
│   │   ├── error_handler.py
│   │   └── telemetry_middleware.py  # request timing → Prometheus
│   ├── tasks/                    # Celery/background tasks
│   │   ├── ingest_document.py
│   │   └── reindex_document.py
│   └── utils/
├── tests/
├── alembic.ini
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

**Frontend** (structure shown for Option B/React; trim for Option C)
```
frontend/
├── src/
│   ├── pages or routes: login, register, documents, chat/[id], admin
│   ├── components/
│   │   ├── chat/ (MessageBubble, CitationChip, StreamingIndicator)
│   │   ├── upload/ (DropzoneUploader, ProgressBar)
│   │   ├── admin/ (MetricsChart, UserTable)
│   │   └── ui/
│   ├── lib/ (api-client.ts, auth.ts)
│   └── types/
```

---

## 6. Database Schema (PostgreSQL)

**users**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | VARCHAR, UNIQUE | |
| hashed_password | VARCHAR | bcrypt |
| full_name | VARCHAR | |
| role | ENUM(user, admin) | default `user` |
| is_active | BOOLEAN | default true |
| created_at | TIMESTAMPTZ | |

**documents**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | cascade delete |
| filename | VARCHAR | |
| file_type | VARCHAR | pdf / docx |
| file_size_bytes | INTEGER | |
| status | ENUM(processing, ready, failed) | |
| page_count | INTEGER | nullable |
| is_shared | BOOLEAN | default false — supports `/documents/{id}/share` |
| uploaded_at | TIMESTAMPTZ | |

**document_chunks**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| document_id | UUID FK → documents | cascade delete |
| chunk_index | INTEGER | |
| content | TEXT | |
| content_tsv | TSVECTOR | generated column, GIN-indexed — powers the BM25/keyword leg of hybrid search |
| token_count | INTEGER | |
| page_number | INTEGER | nullable |
| qdrant_point_id | UUID | links to vector store |

**conversations**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | |
| document_scope | UUID[] | nullable — if set, restricts retrieval to these document IDs (multi-file scoping); null = search across all user's docs |
| title | VARCHAR | auto-generated from first message |
| created_at / updated_at | TIMESTAMPTZ | |

**messages**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| conversation_id | UUID FK → conversations | |
| role | ENUM(user, assistant) | |
| content | TEXT | |
| citations | JSONB | `[{document_id, filename, page, snippet}]` |
| latency_ms | INTEGER | for observability |
| llm_provider | VARCHAR | which provider answered — supports A/B comparisons |
| token_cost | NUMERIC | nullable, $0 for free providers |
| created_at | TIMESTAMPTZ | |

**feedback**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| message_id | UUID FK → messages | |
| user_id | UUID FK → users | |
| rating | ENUM(up, down) | supports `POST /feedback` |
| comment | TEXT | nullable |
| created_at | TIMESTAMPTZ | |

**refresh_tokens**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | |
| token_hash | VARCHAR | never store raw token |
| expires_at | TIMESTAMPTZ | |
| revoked | BOOLEAN | supports logout / rotation |

All FKs use `ON DELETE CASCADE` — deleting a user cleanly removes their documents, chunks, conversations, messages, and feedback.

---

## 7. Redis Key Design

| Key pattern | Purpose | TTL |
|---|---|---|
| `rate_limit:{user_id}:{endpoint}` | Sliding-window request counter | matches window (e.g. 60s) |
| `token_blacklist:{jti}` | Revoked JWT IDs (logout) | matches token expiry |
| `doc_status:{document_id}` | Live processing status for polling | 1 hour |
| `embed_cache:{hash(query)}` | Cache of repeated query embeddings | 24 hours |
| `metrics:requests:{endpoint}:{date}` | Daily request counter per endpoint | 30 days |
| `metrics:latency:{endpoint}` | Rolling latency samples (list, capped) | 1 hour |
| `metrics:llm_cost:{date}` | Running daily LLM/embedding $ cost | 30 days |

---

## 8. Hybrid Retrieval Design (core change from v1)

**Why hybrid, not vector-only:** vector search finds semantically similar chunks but misses exact terms (IDs, error codes, acronyms, names). BM25/keyword search catches exact matches but misses paraphrases. Merging both, then reranking, consistently outperforms either alone — this is the current standard in production RAG, not a stretch goal.

**Pipeline:**
1. **Vector leg:** embed query → Qdrant search, `top_k=15`, filtered by `user_id` (+ `document_id IN (...)` if conversation has a `document_scope`).
2. **Keyword leg:** Postgres `ts_rank` query against `content_tsv`, same filters, `top_k=15`.
3. **Merge:** reciprocal rank fusion (RRF) — simple, no tuning needed, combine both ranked lists into one.
4. **Rerank:** local cross-encoder (`ms-marco-MiniLM-L-6-v2`) scores the merged candidates against the query, take final `top_k=5`. This runs on CPU, no API cost, adds ~100–300ms.
5. **Context assembly:** group by document, include source markers (`[Doc: filename, Page: N]`) so multi-document answers are traceable per-document.

**Multi-file retrieval:** by default, retrieval searches across **all** of a user's `ready` documents, not just one. `conversations.document_scope` lets a user pin a conversation to a subset (e.g. "only these 3 PDFs") via a scope-selection UI. This is a genuine differentiator vs. single-doc chat demos.

---

## 9. Vector DB Design (Qdrant)

- Single collection `document_chunks`, isolation via **payload filtering** (standard multi-tenant pattern).
- Vector size matches whichever embedding provider is active (384 for `all-MiniLM-L6-v2`, 1536 for `text-embedding-3-small`, etc.) — store `embedding_dim` in config so switching providers is a documented, deliberate migration, not silent breakage.
- Payload fields: `user_id`, `document_id`, `chunk_id`, `page_number`, `content_preview`.
- Every query filtered by `user_id` (and optionally `document_id IN [...]`) **before** similarity search — primary privacy control.

---

## 10. RAG Pipeline

**1. Ingestion**
Parse (PyMuPDF/python-docx) → clean text → chunk (~500 tokens, 50-token overlap) → persist chunk rows in Postgres (populates `content_tsv` automatically via generated column) → embed each chunk via active `EmbeddingProvider` → upsert to Qdrant with payload.

**2. Retrieval**
See §8 — hybrid (vector + BM25) → RRF merge → cross-encoder rerank → multi-document context assembly.

**3. Generation**
Prompt template forces the model to cite chunk source per claim → call active `LLMProvider` → parse structured `{answer, sources}` → grounded, traceable answer.

**4. Summarization (new AI feature)**
Separate endpoint: given a `document_id` (or list of them), chunk-map-reduce summarize — summarize each chunk group, then summarize the summaries. Reuses the same pluggable `LLMProvider`. Useful standalone feature beyond Q&A.

**5. Persistence**
Save message + citations JSONB + `latency_ms` + `llm_provider` + `token_cost` to `messages`; update `conversations.updated_at`; push timing/cost samples to Redis for the metrics dashboard.

---

## 11. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Liveness + dependency checks (Postgres, Redis, Qdrant) |
| GET | `/metrics` | — (or admin) | Prometheus-format metrics for scraping |
| POST | `/api/auth/register` | — | Create account |
| POST | `/api/auth/login` | — | Returns access + refresh token |
| POST | `/api/auth/refresh` | Refresh token | Rotates refresh token |
| POST | `/api/auth/logout` | Access token | Blacklists token in Redis |
| GET | `/api/me` | User | Current user profile |
| PATCH | `/api/profile` | User | Update name/preferences |
| POST | `/api/documents/upload` | User | Multipart upload, triggers async processing |
| GET | `/api/documents` | User | List own documents |
| GET | `/api/documents/{id}/status` | User | Poll processing status |
| DELETE | `/api/documents/{id}` | User | Cascade deletes chunks + vectors |
| POST | `/api/documents/{id}/share` | User | Mark shareable / generate share link |
| POST | `/api/documents/{id}/duplicate` | User | Clone document + chunks + vectors |
| POST | `/api/documents/{id}/summarize` | User | AI feature — map-reduce summary |
| POST | `/api/reindex` | User/Admin | Re-chunk + re-embed a document (e.g. after changing embedding provider) |
| POST | `/api/conversations` | User | Start a new conversation (optional `document_scope`) |
| GET | `/api/conversations` | User | List own conversations |
| POST | `/api/conversations/{id}/messages` | User | Ask a question → hybrid retrieval → answer + citations |
| GET | `/api/conversations/{id}/messages` | User | Full history |
| DELETE | `/api/conversations/{id}` | User | Delete conversation |
| POST | `/api/feedback` | User | Thumbs up/down + comment on a message |
| GET | `/api/admin/users` | Admin | List/search all users |
| PATCH | `/api/admin/users/{id}` | Admin | Activate/deactivate |
| GET | `/api/admin/stats` | Admin | Usage analytics |
| GET | `/api/admin/observability` | Admin | Latency, cost, error-rate dashboard data |

---

## 12. Security

**Authentication**
- Passwords hashed with bcrypt (cost factor 12+), never logged, never returned in any response.
- JWT access tokens short-lived (15 min); refresh tokens rotated on use, stored as hashes only.
- Logout blacklists the token `jti` in Redis until natural expiry.
- RBAC middleware — every admin route independently checks `role == admin`.

**Input & File Validation**
- File upload: MIME allow-list (PDF/DOCX only), max size enforced (e.g. 20MB), filename sanitized.
- All request bodies validated via Pydantic schemas.
- SQL injection structurally prevented via SQLAlchemy ORM.
- CORS restricted to known frontend origin(s), not `*`.

**Transport & Secrets**
- HTTPS enforced at the Railway/Vercel edge.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`) via middleware.
- All secrets via environment variables — `.env.example` checked in, `.env` gitignored. This now includes multiple optional provider keys (OpenAI, Anthropic, Groq, Gemini) — document which are required vs optional.

---

## 13. Error Handling Strategy

- Custom exception classes per domain (`DocumentNotFoundError`, `UnauthorizedAccessError`, `RateLimitExceededError`, `LLMProviderError`) in `core/exceptions.py`.
- Global FastAPI exception handler maps each to a consistent JSON shape:
  ```json
  { "error": { "code": "DOCUMENT_NOT_FOUND", "message": "...", "request_id": "..." } }
  ```
- Every response includes a `request_id` (correlation ID).
- Structured logging (JSON logs); 4xx as info, 5xx as error with stack trace.
- LLM/embedding calls wrapped with retry-with-backoff (`tenacity`) + circuit breaker → clean `503` instead of hanging. If the active provider fails repeatedly, circuit breaker can **auto-fallback to a secondary configured provider** (e.g. Groq down → fall back to Gemini) — a genuinely useful reliability feature enabled by the provider abstraction.
- Document processing failures update `documents.status = failed` with a reason.

---

## 14. Privacy & Data Protection

- Data isolation is structural: every document/conversation query scoped by `user_id` at the service layer; Qdrant payload filtering enforces the same boundary independently in the vector store.
- **Right to deletion:** deleting a document/account cascades through Postgres (FK `ON DELETE CASCADE`) *and* issues a matching delete against Qdrant points.
- **No document content in logs:** logging middleware excludes request/response bodies for document/chat endpoints.
- **LLM provider data handling:** note in README that API calls (not consumer chat products) are used, which by API terms aren't used for model training — call this out explicitly for local/free providers too (Ollama = fully local, nothing leaves the machine; worth highlighting as a privacy differentiator).
- **Encryption at rest:** Railway's managed Postgres/volumes encrypted at rest by default.

---

## 15. Admin Dashboard

Pages:
- **Users:** searchable table, activate/deactivate toggle, per-user usage (docs uploaded, queries made).
- **Usage Analytics:** queries/day and uploads/day charts.
- **Observability (new):** latency histograms (p50/p95/p99) per endpoint, LLM/embedding cost over time, error rate %, average retrieval time (vector leg vs. keyword leg vs. rerank step, shown separately so you can point at exactly where latency goes), Qdrant/Redis/Postgres live health pings.
- **Feedback:** thumbs up/down rate per provider — useful if you're comparing free vs. paid LLMs.

---

## 16. Frontend UI Mandates (non-generic)

- Streaming answers token-by-token (SSE), not spinner-then-full-block.
- Citation chips inline in the answer text, clickable to jump to the source page.
- Drag-drop multi-file upload with per-file progress.
- Multi-document scope selector in chat (checkbox list of "which documents to search").
- Skeleton loaders during document processing.
- Optimistic UI when a message is sent.
- (Option C / vanilla JS): same behaviors are achievable with `fetch` + `EventSource` for SSE and plain DOM updates — don't skip streaming just because there's no framework.

---

## 17. Docker & Deployment

`docker-compose.yml` services: `api`, `postgres`, `redis`, `qdrant`, optionally `ollama` (if using local LLM); frontend deployed separately (Vercel) or served as static files if Option C.

Required env vars: `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `JWT_SECRET`, `CORS_ORIGINS`, `MAX_UPLOAD_SIZE_MB`, `EMBEDDING_PROVIDER`, `LLM_PROVIDER`, `LLM_FALLBACK_PROVIDER` (optional), plus whichever provider keys are active (`GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OLLAMA_BASE_URL`).

Each service exposes `/health`; Railway healthchecks hit these before routing traffic. `/metrics` exposed for Prometheus scraping (or self-polled into the admin dashboard if you skip a real Prometheus instance).

---

## 18. Build Timeline (4–5 Weeks)

| Week | Focus |
|---|---|
| 1 | Auth (JWT + RBAC) + Postgres schema + Alembic + file upload + parsing + chunking + provider abstraction skeleton (LLM + embedding factories) |
| 2 | Embeddings (start with local `sentence-transformers`) + Qdrant integration + Postgres FTS setup + hybrid retrieval (RRF merge) + basic Q&A endpoint (no streaming, no rerank yet) |
| 3 | Add reranker + multi-file retrieval/scope + conversation history + citations + Redis rate limiting + SSE streaming + summarization endpoint + minimal frontend (Option C) |
| 4 | Telemetry (metrics middleware, cost tracker, `/metrics`) + admin dashboard incl. observability tab + feedback endpoint + error handling/logging polish |
| 5 (buffer) | Docker Compose + deploy (Railway + Vercel) + README + demo video + optional frontend upgrade to Option B/A if time remains |

---

## 19. Interview Talking Points

- **Hybrid retrieval:** why vector-only search misses exact-term queries, how RRF merges vector + BM25 rankings, why the reranker is a separate cheap local step rather than a bigger top_k.
- **Multi-document RAG:** cross-document retrieval by default, with an optional per-conversation document scope — and why that's structurally different from single-PDF-chat demos.
- **Provider abstraction:** one interface, five interchangeable backends (OpenAI, Anthropic, Groq, Gemini, Ollama) — cost/latency/privacy tradeoffs of each, and automatic fallback on provider failure via the circuit breaker.
- **Observability:** what you measure and why (p95 latency per pipeline stage, $ cost per query, error rate) — most portfolio RAG projects have zero visibility into this.
- **Chunking:** why 500 tokens with 50-token overlap, fragmentation-vs-dilution tradeoff.
- **Grounded citations:** answers trace back to a specific chunk → page → document, enforced by prompt structure.
- **Rate limiting design:** sliding-window in Redis, per-user not global.
- **Privacy:** isolation enforced independently at relational and vector layers; local/free providers (Ollama) as a genuine privacy-by-design option.
- **Scale-up path:** Celery for background ingestion at higher load, swap local reranker for a hosted one, add per-document collections if a single tenant's chunk volume gets extreme.

---

## 20. Resume Bullets (ATS-optimized)

- Built a multi-tenant RAG document Q&A platform (FastAPI, PostgreSQL, Redis, Qdrant) with hybrid retrieval (vector + BM25 + cross-encoder reranking) across multiple documents per query, returning LLM-generated answers grounded with page-level citations.
- Designed a provider-agnostic LLM/embedding layer supporting 5 backends (OpenAI, Anthropic, Groq, Gemini, local Ollama) with automatic failover via a retry/circuit-breaker pattern.
- Implemented JWT auth with refresh-token rotation, RBAC, and Redis-backed per-user rate limiting; enforced data isolation across both relational and vector stores.
- Built an observability layer (Prometheus-style metrics, per-query cost/latency tracking) and an admin dashboard surfacing usage, cost, and system health.
- Added document summarization, sharing, duplication, and a feedback loop on top of the core Q&A pipeline; containerized with Docker Compose, deployed on Railway + Vercel.

---

*End of build specification v2.*
