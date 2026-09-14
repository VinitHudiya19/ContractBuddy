# Contract Buddy

Upload a contract, ask questions about it, and get an answer that tells you
which page it came from.

I built this because I wanted to understand RAG properly instead of just calling
an LLM API and trusting whatever came back. The part that took the most work is
retrieval: a semantic search and a keyword search run at the same time, the two
result lists get merged, a reranker sorts them, and only the top few chunks go
to the model. Answers come back with `[S1]` markers you can click to see the
exact text they came from.

Each account only sees its own documents.

```
upload  ->  parse pages  ->  chunk  ->  embed  ->  store vectors

question  ->  vector search  --\
                                >--  RRF merge  ->  rerank  ->  LLM  ->  answer + citations
          ->  keyword search --/
```

---

## Running it

No Docker, no database server, no API key needed:

```bash
cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload
```

Use `source .venv/bin/activate` on macOS or Linux. Open
<http://localhost:8000>, create an account, and upload something. There's a
sample contract in `samples/` if you don't have one to hand.

First start takes a minute or two while it downloads the embedding and reranker
models (~275 MB). That only happens once.

It runs with nothing installed because each external service has a fallback:

| Service | Set with | Without it |
|---|---|---|
| PostgreSQL | `DATABASE_URL` | SQLite, tables created on startup |
| Qdrant | `QDRANT_URL` | vectors in a table, searched with NumPy |
| Redis | `REDIS_URL` | no rate limiting, status read from the database |
| LLM | `GROQ_API_KEY` | answers are quoted from the sources, not generated |

For real generated answers, grab a free [Groq](https://console.groq.com) key and
put it in `.env`:

```bash
GROQ_API_KEY=gsk_your_key_here
```

### With Docker

```bash
docker compose up --build
```

Starts PostgreSQL, Redis, Qdrant and the API together. The compose file
overrides the connection URLs, so the same code picks up the real services.

---

## How the retrieval works

This is the part I'd want to talk about.

**Ingestion.** PDFs are read page by page with PyMuPDF, DOCX with python-docx.
The text is split into ~500-token chunks with 50 tokens of overlap, and each
chunk stores the page it started on. That page number is the only reason
citations work later.

(DOCX has no real pages, so for those I group paragraphs and estimate. It's an
approximation and I'd rather say so than pretend otherwise.)

**Two searches, run together.**

- **Vector** — the question is embedded with `all-MiniLM-L6-v2` (384-dim) and
  compared by cosine similarity. This one gets meaning: ask about "cost" and it
  finds a chunk about "pricing". Top 15.
- **Keyword** — Postgres `tsvector` with a GIN index, or per-term matching on
  SQLite. This one gets exact strings: contract numbers, party names, "Net 45".
  Top 15.

Neither is enough alone. Vector search misses exact identifiers, keyword search
misses anything worded differently. That's the whole reason for running both.

**Merging with RRF.** Now there are two ranked lists, but cosine similarity and
`ts_rank` are on totally different scales, so averaging them means nothing. RRF
throws the scores away and uses position only:

```
score = sum over both lists of  1 / (60 + rank)
```

A chunk both searches put second beats one that only a single search put first.
If two independent methods agree, that's a better signal than one being very
confident. Top 30 continue.

**Reranking.** The embedding model encodes the question and the chunk
separately, so it never actually compares them. A cross-encoder
(`ms-marco-MiniLM-L-6-v2`) reads both together, which is much better but far too
slow to run over a whole database. So it runs on those 30 and keeps the best 5.

**Generation.** Those 5 get labelled `[S1]`–`[S5]` and go into the prompt. The
model is told to cite inline and to say so when the sources don't answer the
question. The answer streams back over SSE, citations first, then tokens. I
parse the markers back out and keep only the citations it actually used.

---

## Keeping accounts apart

Every document, chunk and vector stores a `user_id`, and the filter goes inside
the search rather than after it:

- Qdrant — `user_id` payload filter in the search request
- SQL vector store — `WHERE user_id = ...` before anything is scored
- keyword search and every repository — `user_id` in the `WHERE` clause

Filtering afterwards would be worse than it looks. You'd ask for the top 10,
then drop the ones belonging to someone else, and end up with 3 results. Or
none.

Asking for another account's document returns 404 rather than 403, so the API
never confirms it exists.

`backend/tests/test_auth.py::TestTenantIsolation` covers this for documents and
conversations, including that a fresh account sees nothing.

---

## Stack

| Layer | What I used |
|---|---|
| API | FastAPI, Uvicorn, Pydantic v2, SSE for streaming |
| Database | SQLAlchemy 2 (async), PostgreSQL or SQLite, Alembic |
| Vectors | Qdrant, or the built-in SQL store |
| Models | `all-MiniLM-L6-v2` (embeddings), `ms-marco-MiniLM-L-6-v2` (rerank), Groq `openai/gpt-oss-20b` (answers) |
| Redis | rate limiting, JWT revocation on logout, status cache |
| Frontend | plain HTML/CSS/JS, no build step |
| CI | GitHub Actions, ruff and pytest on every push |

Nothing in the routes or services imports an LLM SDK. They ask
`app/providers/factory.py` for an `LLMProvider`. Groq is the only one
implemented right now; with no API key the factory returns the extractive
provider instead, which is what keeps the app usable on a fresh clone. Adding
another means writing one class behind the same interface.

Auth is JWT with 15-minute access tokens and refresh-token rotation, so a
stolen refresh token works at most once. Logout puts the token's `jti` in Redis
until it would have expired anyway.

---

## API

Swagger at <http://localhost:8000/docs>.

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/auth/register` · `/login` · `/refresh` · `/logout` | JWT with refresh rotation |
| `GET` `POST` `DELETE` | `/api/documents` | upload, list, delete (PDF/DOCX, 20 MB) |
| `GET` | `/api/documents/{id}/status` | has indexing finished |
| `POST` | `/api/documents/{id}/summarize` | map-reduce summary of the document |
| `POST` | `/api/conversations/{id}/messages` | ask something, `stream:true` for SSE |
| `PATCH` | `/api/conversations/{id}` | rename, or limit to certain documents |
| `POST` | `/api/contracts` | upload and extract structured fields |
| `GET` | `/health` | status of each dependency |

```bash
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"a-strong-password","full_name":"Your Name"}'
```

---

## Contract analysis

`POST /api/contracts` pulls out parties, obligations, payment terms and value,
and scores the contract on how many of ten expected clause types it can find
(termination, liability, confidentiality, governing law, dispute resolution,
data protection, IP, service levels, force majeure, payment).

The LLM is asked for a fixed JSON schema, and every field is checked and
converted before it reaches the database, because models do return a string
where a number belongs or wrap the JSON in a code fence. With no LLM it falls
back to regex and keyword rules over the text.

Either way the response carries `analysis_source`, set to `"llm"` or
`"rules"`, and the UI badges them differently. Showing regex output and model
output as the same thing felt wrong. Anything the document doesn't mention comes
back `null` and renders as `—`, never a guess.

---

## Tests

```bash
cd backend && pytest -q
```

64 tests, no Docker or network needed. The suite runs on SQLite with the SQL
vector store and the extractive provider, so it works offline and without API
keys. It covers RRF fusion, chunk overlap and page mapping, query tokenising,
auth and refresh rotation, account isolation, the full upload to cited answer
path, and the contract analysis parsing.

```bash
ruff check app tests
```

---

## Deploying

It's an ordinary Docker image with nothing platform-specific in it. Two ways:

**Single container.** SQLite and the built-in vector store handle everything:

```bash
docker build -f backend/Dockerfile -t contractbuddy .
```

```bash
docker run -p 8000:8000 -e APP_ENV=production -e JWT_SECRET="$(openssl rand -hex 32)" -e CORS_ORIGINS=https://your-domain.com -e GROQ_API_KEY=gsk_your_key contractbuddy
```

**With real services.** Same image, set `DATABASE_URL`, `REDIS_URL` and
`QDRANT_URL`. `docker-compose.yml` is the working example.

With `APP_ENV=production` the app refuses to start if the JWT secret is still
`change-me` or `CORS_ORIGINS` still contains `*`. The loose defaults are what
let it run with no config, and forgetting one would mean deploying an app whose
tokens anyone can forge.

Against Postgres the entrypoint runs migrations on every start, so deploying is
a restart. On SQLite it skips them and lets the app build its own tables, since
the first migration creates a GIN index and that's Postgres-only.

Needs about 600 MB of RAM once both models are loaded, in a ~2 GB image, mostly
CPU torch. So 512 MB free tiers won't work. `RERANK_ENABLED=false` drops the
cross-encoder and some memory, at the cost of worse answers.

---

## Layout

```
backend/app/
  api/v1/        route handlers, one file per resource
  core/          config, security, logging, exceptions
  db/            engine, session, Qdrant client, vector store
  models/        SQLAlchemy models
  repositories/  the queries, so routes stay thin
  providers/     LLM and embedding adapters behind one interface
  services/      ingestion, retrieval, generation, summarization, analysis
frontend/        two pages, login and workspace
samples/         a contract to try it with
```

---

## What's missing

- **The SQL vector store checks every row.** O(n) per query. Fine for a demo,
  not for real data, which is what Qdrant's HNSW index is for.
- **Ingestion runs in a FastAPI background task**, so it dies if the process
  restarts mid-upload. Celery or RQ with retries would fix it.
- **Chunking is fixed-size.** Splitting on clause boundaries would keep legal
  provisions in one piece. Next thing I'd do.
- **I haven't measured retrieval quality.** I can explain why the design should
  work, but I don't have numbers. A labelled question set and recall@k would
  settle it either way.
- **Rate limiting fails open** when Redis is down. Fine here, wrong for
  anything public.

---

## Licence

MIT.
