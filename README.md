# Contract Buddy

A document Q&A system. Sign up, upload a contract, ask questions in plain
English, and get answers that cite the exact page they came from. Every account
sees only its own documents.

The interesting part is the retrieval: instead of plain vector search, it runs
**dense semantic search and lexical keyword search in parallel**, fuses the two
ranked lists with **Reciprocal Rank Fusion**, and re-scores the survivors with a
**cross-encoder** before anything reaches the language model.

```
┌────────────┐   ┌─────────────────────────────────────────┐   ┌────────────┐
│  PDF/DOCX  │──▶│  parse → chunk → embed → index          │──▶│  Vectors   │
└────────────┘   └─────────────────────────────────────────┘   │  + Chunks  │
                                                               └──────┬─────┘
┌────────────┐   ┌──────────────┐                                     │
│  Question  │──▶│  dense leg   │──┐                                  │
└────────────┘   └──────────────┘  │   ┌─────┐   ┌───────────┐   ┌────▼────┐
                 ┌──────────────┐  ├──▶│ RRF │──▶│ Reranker  │──▶│   LLM   │
                 │ keyword leg  │──┘   └─────┘   └───────────┘   └────┬────┘
                 └──────────────┘                                     │
                                                        answer + [S1] citations
```

---

## Run it

**No Docker, no API key, no database server.** From a clean checkout:

```bash
cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload
```

On macOS/Linux use `source .venv/bin/activate` instead. Then open
<http://localhost:8000> and create an account — sign-up is open, and a new
account starts empty.

That works because every external dependency has a built-in fallback:

| Dependency | Configured by | Fallback when absent |
|---|---|---|
| PostgreSQL | `DATABASE_URL` | SQLite file, tables auto-created |
| Qdrant | `QDRANT_URL` | `chunk_vectors` table + NumPy dot product |
| Redis | `REDIS_URL` | rate limiting fails open, status read from the database |
| LLM | `GROQ_API_KEY` | extractive answers quoted from the sources |

Add a free [Groq](https://console.groq.com) key to `.env` for generated answers:

```bash
GROQ_API_KEY=gsk_your_key_here
```

### Full stack with Docker

```bash
docker compose up --build
```

Brings up PostgreSQL, Redis, Qdrant and the API together. `docker-compose.yml`
overrides the connection URLs, so the same code picks up the real services.

---

## Deploying

The image is a plain Docker image with no platform-specific configuration, so
anywhere that runs a container will do. There are two shapes:

**Single container.** No external services — SQLite and the built-in vector
store carry the whole app. Good for a demo box or a small VM:

```bash
docker build -f backend/Dockerfile -t contractbuddy .
```

Then run it with the production settings applied:

```bash
docker run -p 8000:8000 -e APP_ENV=production -e JWT_SECRET="$(openssl rand -hex 32)" -e CORS_ORIGINS=https://your-domain.com -e GROQ_API_KEY=gsk_your_key contractbuddy
```

**With managed services.** Point the same image at real infrastructure by
setting `DATABASE_URL`, `REDIS_URL` and `QDRANT_URL`. Nothing else changes —
`docker-compose.yml` is the worked example.

With `APP_ENV=production` the app refuses to start on development defaults: a
`change-me` JWT secret, or a `*` in `CORS_ORIGINS`.
That is deliberate — those defaults exist so a clean checkout runs with no
configuration, and a forgotten environment variable would otherwise ship a
public app with a known signing key.

Against Postgres the entrypoint applies migrations on every start, so a deploy
is just a restart. On SQLite the app creates its own schema instead — the
migration history contains Postgres-only DDL.

**What it needs.** Roughly 600 MB of RAM once the embedding and reranker models
are resident, and a ~2 GB image — CPU torch is most of it. That rules out the
512 MB free tiers. Setting `RERANK_ENABLED=false` drops the cross-encoder and
some of that memory, at a cost in answer quality.

---

## How retrieval works

**1 · Ingestion** — PDF (PyMuPDF) or DOCX (python-docx) is parsed page by page,
split into ~500-token chunks with 50-token overlap, and each chunk remembers the
page it started on. That page number is what makes citations possible.

**2 · Two retrieval legs, run concurrently**

- *Dense* — the question is embedded with `all-MiniLM-L6-v2` (384-dim) and matched
  by cosine similarity. Good at meaning: "cost" finds "pricing".
- *Lexical* — PostgreSQL `tsvector` + GIN index, or per-term matching on SQLite.
  Good at exact strings: contract numbers, party names, `Net 45`.

Neither alone is enough, which is why both run.

**3 · Reciprocal Rank Fusion** — cosine similarity and `ts_rank` live on
completely different scales, so averaging them is meaningless. RRF discards the
scores and uses only rank position:

```
score(d) = Σ  1 / (k + rank(d))        k = 60
          legs
```

A chunk both legs rank second beats one a single leg ranks first — agreement
between independent methods is the signal.

**4 · Cross-encoder rerank** — the bi-encoder above embeds question and chunk
*separately*, which is fast but loses their interaction. `ms-marco-MiniLM-L-6-v2`
reads each (question, chunk) pair *together* with full attention. Much more
accurate, far too slow for the whole corpus — hence retrieve-then-rerank over the
top candidates only.

**5 · Grounded generation** — the surviving chunks are labelled `[S1]…[S5]` and
the model is instructed to cite them inline and to say so when the sources don't
answer the question. Citations are parsed back out and rendered as chips that
open the source snippet.

---

## Account isolation

Every document, chunk and vector carries a `user_id`, and the filter is applied
**before** the similarity search, not after:

- Qdrant — `user_id` payload filter inside the search request
- SQL vector store — `WHERE user_id = ...` before any scoring
- Lexical leg and every repository — `user_id` in the `WHERE` clause
- A document belonging to another account returns **404**, not 403 — the API
  doesn't confirm that it exists

`backend/tests/test_auth.py::TestTenantIsolation` asserts this across documents
and conversations, including that a newly created account sees nothing.

---

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI, Uvicorn, Pydantic v2, SSE for token streaming |
| Data | SQLAlchemy 2 (async), PostgreSQL or SQLite, Alembic |
| Vectors | Qdrant, or the built-in SQL store |
| Models | `all-MiniLM-L6-v2` (embeddings), `ms-marco-MiniLM-L-6-v2` (rerank), Groq `openai/gpt-oss-20b` (generation) |
| Cache | Redis — sliding-window rate limits, JWT revocation, status mirror |
| Frontend | Vanilla HTML/CSS/JS, no build step |
| CI | GitHub Actions — ruff + pytest on every push |

No business logic imports a vendor SDK directly — everything asks
`app/providers/factory.py` for an `LLMProvider`. Groq is the implemented
provider; without a key the factory returns the extractive one instead, which is
what keeps the app usable on a clean checkout. Adding another provider means one
new class behind the same interface, not changes to the call sites.

---

## API

Interactive docs at <http://localhost:8000/docs>.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/register` · `/login` · `/refresh` · `/logout` | JWT with refresh-token rotation |
| `GET` `POST` `DELETE` | `/api/documents` | Upload, list, delete (PDF/DOCX, 20 MB) |
| `GET` | `/api/documents/{id}/status` | Poll ingestion progress |
| `POST` | `/api/documents/{id}/summarize` | Map-reduce summary over all chunks |
| `POST` | `/api/conversations/{id}/messages` | Ask — set `stream:true` for SSE |
| `PATCH` | `/api/conversations/{id}` | Rename, or scope to specific documents |
| `POST` | `/api/contracts` | Upload + structured clause analysis |
| `GET` | `/health` | Per-dependency status |

```bash
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"a-strong-password","full_name":"Your Name"}'
```

---

## Contract analysis

`POST /api/contracts` extracts parties, obligations, payment terms and value, then
scores the contract on how many of ten expected clause types are present
(termination, liability, confidentiality, governing law, dispute resolution, data
protection, IP, service levels, force majeure, payment).

Every response carries `analysis_source`:

- `"llm"` — the model returned JSON, which is then validated and type-coerced
  field by field before it touches the database
- `"rules"` — no LLM configured, so the numbers come from deterministic keyword
  and regex rules over the document text

The UI badges the two differently. Fields the document doesn't state come back as
`null` and render as `—`; nothing is filled in with plausible-looking guesses.

---

## Tests

```bash
cd backend && pytest -q
```

52 tests, no Docker and no network required — the suite runs on SQLite with the
SQL vector store and the extractive provider. It covers RRF fusion, chunk overlap
and page mapping, query tokenising, auth and refresh-token rotation, tenant
isolation, the full upload → index → cited-answer path, and the contract analysis
parsing/coercion layer.

```bash
ruff check app tests
```

---

## Layout

```
backend/app/
  api/v1/        route handlers, one module per resource
  core/          config, security, logging, exceptions
  db/            engine, session, Qdrant client, vector store abstraction
  models/        SQLAlchemy ORM
  repositories/  query layer, keeps SQL out of route handlers
  providers/     LLM + embedding adapters behind one interface
  services/      ingestion, retrieval, generation, summarization, analysis
frontend/        two pages: login and workspace
```

---

## Known limits

Worth being upfront about:

- **The SQL vector store scans every row.** Fine for a demo corpus, O(n) per
  query. Qdrant's HNSW index is the answer at real scale, which is why it's the
  preferred backend.
- **Ingestion runs in a FastAPI background task**, so it dies with the process. A
  production deployment wants Celery or RQ with retries.
- **Chunking is fixed-size.** Splitting on clause boundaries would keep legal
  provisions intact and is the obvious next improvement.
- **No evaluation harness.** Retrieval quality is argued from architecture, not
  measured — a labelled question set with recall@k would make the claims real.
- **Rate limiting fails open** when Redis is down. Reasonable for a demo, wrong
  for a public deployment.

---

## Licence

MIT.
