# Contract Buddy

Upload a contract, ask questions about it in normal English, and get an answer
that tells you which page it came from.

I built this to learn how RAG actually works end to end, instead of just calling
an LLM API and hoping the answer is right. The part I spent the most time on is
retrieval: it runs a semantic search and a keyword search at the same time,
merges both result lists, reranks them, and only then sends anything to the
model. Every answer comes back with `[S1]` style markers you can click to see
the exact text and page it used.

Each account only sees its own documents.

```
upload  ->  parse pages  ->  chunk  ->  embed  ->  store vectors

question  ->  vector search  --\
                                >--  RRF merge  ->  rerank  ->  LLM  ->  answer + citations
          ->  keyword search --/
```

---

## Running it

You don't need Docker, a database server, or an API key to try it:

```bash
cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload
```

Use `source .venv/bin/activate` on macOS or Linux. Then open
<http://localhost:8000> and create an account. Sign-up is open and a new account
starts empty, so upload something — there's a sample contract in `samples/` if
you don't have one handy.

The first start takes a minute or two because it downloads the embedding and
reranker models (around 275 MB together). That only happens once — they're
cached after that.

This works with no setup because each external service has a fallback:

| Service | Set with | What happens without it |
|---|---|---|
| PostgreSQL | `DATABASE_URL` | SQLite file, tables created automatically |
| Qdrant | `QDRANT_URL` | vectors go in a `chunk_vectors` table, searched with NumPy |
| Redis | `REDIS_URL` | rate limiting is skipped, status read from the database |
| LLM | `GROQ_API_KEY` | answers are quoted straight from the sources instead of generated |

For real generated answers, get a free key from [Groq](https://console.groq.com)
and put it in `.env`:

```bash
GROQ_API_KEY=gsk_your_key_here
```

### With Docker

```bash
docker compose up --build
```

This starts PostgreSQL, Redis, Qdrant and the API together. The compose file
overrides the connection URLs so the same code picks up the real services.

---

## Deploying

The image is a normal Docker image with nothing platform-specific in it, so it
should run anywhere containers run. Two ways to do it:

**One container, nothing else.** SQLite and the built-in vector store handle
everything:

```bash
docker build -f backend/Dockerfile -t contractbuddy .
```

```bash
docker run -p 8000:8000 -e APP_ENV=production -e JWT_SECRET="$(openssl rand -hex 32)" -e CORS_ORIGINS=https://your-domain.com -e GROQ_API_KEY=gsk_your_key contractbuddy
```

**With real services.** Same image, just set `DATABASE_URL`, `REDIS_URL` and
`QDRANT_URL`. `docker-compose.yml` shows what that looks like.

When `APP_ENV=production` is set, the app won't start if the JWT secret is still
`change-me` or if `CORS_ORIGINS` still has a `*` in it. I added that because the
loose defaults are what make the app run with no config, and it would be very
easy to forget one and deploy something anyone can forge tokens for.

With Postgres, the container entrypoint runs migrations on every start, so
deploying is just a restart. On SQLite it skips migrations and lets the app
create its own tables, because the first migration builds a GIN index and that
is Postgres-only.

**Resources:** around 600 MB of RAM once both models are loaded, and roughly a
2 GB image — CPU torch is most of that. So the 512 MB free tiers won't work.
Setting `RERANK_ENABLED=false` skips the cross-encoder and saves some memory,
but answers get worse.

---

## How the retrieval works

**1. Ingestion.** PDFs are read page by page with PyMuPDF, DOCX with
python-docx. The text is split into roughly 500-token chunks with 50 tokens of
overlap, and every chunk stores the page it started on. That stored page number
is the whole reason citations are possible later.

(DOCX files don't really have pages, so for those I group paragraphs and
estimate a page number. It's an approximation.)

**2. Two searches, run at the same time.**

- **Vector search** — the question is embedded with `all-MiniLM-L6-v2` (384
  dimensions) and compared by cosine similarity. This is the one that
  understands meaning, so asking about "cost" can find a chunk that says
  "pricing".
- **Keyword search** — PostgreSQL `tsvector` with a GIN index, or simple
  per-term matching on SQLite. This is the one that finds exact strings:
  contract numbers, party names, "Net 45".

Neither one is enough by itself, which is why I run both. Vector search misses
exact identifiers; keyword search misses anything phrased differently.

**3. Reciprocal Rank Fusion.** Now I have two ranked lists, but cosine
similarity and `ts_rank` are on completely different scales — averaging them
would be meaningless. RRF ignores the scores entirely and only uses position:

```
score = sum over both lists of  1 / (60 + rank)
```

So a chunk that both searches put at rank 2 beats a chunk that only one search
put at rank 1. If both methods agree, that's a stronger signal than one method
being very confident. Top 30 go forward.

**4. Reranking.** The embedding model encodes the question and the chunk
separately, which is fast but means it never actually compares them directly. A
cross-encoder (`ms-marco-MiniLM-L-6-v2`) reads the question and chunk together,
which is much better but far too slow to run over every chunk in the database.
So it runs on the 30 candidates only and keeps the best 5.

**5. Generation.** Those 5 chunks get labelled `[S1]` to `[S5]` and go into the
prompt. The model is told to cite them inline and to say so if the sources don't
answer the question. Afterwards I parse the markers back out of the answer and
only keep the citations it actually used, then the frontend turns them into
clickable chips.

---

## Keeping accounts separate

Every document, chunk and vector stores a `user_id`, and the filter goes *inside*
the search, not after it:

- Qdrant — `user_id` payload filter in the search request itself
- SQL vector store — `WHERE user_id = ...` before anything gets scored
- keyword search and every repository — `user_id` in the `WHERE` clause

This matters more than it looks. If you filter after searching, you ask for the
top 10 and then throw away the ones that belong to someone else — so you can end
up with 2 results, or 0.

Asking for someone else's document returns 404, not 403, so the API never
confirms that it exists.

`backend/tests/test_auth.py::TestTenantIsolation` checks this for documents and
conversations, including that a brand new account can't see anything.

---

## Stack

| Layer | What I used |
|---|---|
| API | FastAPI, Uvicorn, Pydantic v2, SSE for streaming |
| Database | SQLAlchemy 2 (async), PostgreSQL or SQLite, Alembic |
| Vectors | Qdrant, or the built-in SQL store |
| Models | `all-MiniLM-L6-v2` (embeddings), `ms-marco-MiniLM-L-6-v2` (rerank), Groq `openai/gpt-oss-20b` (answers) |
| Redis | sliding-window rate limiting, JWT revocation on logout, ingestion status cache |
| Frontend | plain HTML/CSS/JS, no build step |
| CI | GitHub Actions — ruff and pytest on every push |

Nothing in the services or routes imports an LLM SDK directly. They all ask
`app/providers/factory.py` for an `LLMProvider`. Right now Groq is the only one
implemented — if there's no API key the factory hands back the extractive
provider instead, which is what keeps the app working out of the box. Adding
another provider means writing one class behind the same interface.

---

## API

Swagger docs at <http://localhost:8000/docs>.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/auth/register` · `/login` · `/refresh` · `/logout` | JWT, with refresh-token rotation |
| `GET` `POST` `DELETE` | `/api/documents` | upload, list, delete (PDF/DOCX, 20 MB limit) |
| `GET` | `/api/documents/{id}/status` | check if indexing finished |
| `POST` | `/api/documents/{id}/summarize` | map-reduce summary of the whole document |
| `POST` | `/api/conversations/{id}/messages` | ask a question — `stream:true` for SSE |
| `PATCH` | `/api/conversations/{id}` | rename, or limit it to certain documents |
| `POST` | `/api/contracts` | upload and pull out structured fields |
| `GET` | `/health` | status of each dependency |

```bash
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"a-strong-password","full_name":"Your Name"}'
```

---

## Contract analysis

`POST /api/contracts` pulls out things like the parties, obligations, payment
terms and value, and scores the contract on how many of ten expected clause
types it can find (termination, liability, confidentiality, governing law,
dispute resolution, data protection, IP, service levels, force majeure,
payment).

Every response includes `analysis_source` so you know where the numbers came
from:

- `"llm"` — the model returned JSON, which I then validate and coerce field by
  field before storing it
- `"rules"` — no LLM available, so it fell back to keyword and regex rules over
  the text

The UI badges these differently. I did it this way because it felt wrong to show
regex output and model output as if they were the same thing. Anything the
document doesn't mention comes back as `null` and shows as `—` rather than a
made-up value.

---

## Tests

```bash
cd backend && pytest -q
```

64 tests. No Docker and no network needed — the suite runs on SQLite with the
SQL vector store and the extractive provider, so it works offline and without
API keys. It covers RRF fusion, chunk overlap and page mapping, query
tokenising, auth and refresh-token rotation, account isolation, the whole
upload → index → cited answer path, and the contract analysis parsing.

```bash
ruff check app tests
```

---

## Layout

```
backend/app/
  api/v1/        route handlers, one file per resource
  core/          config, security, logging, exceptions
  db/            engine, session, Qdrant client, vector store
  models/        SQLAlchemy models
  repositories/  all the queries, so routes stay thin
  providers/     LLM and embedding adapters behind one interface
  services/      ingestion, retrieval, generation, summarization, analysis
frontend/        two pages: login and workspace
samples/         a contract you can upload to try it
```

---

## Things I know are missing

- **The SQL vector store checks every row.** It's O(n) per query, which is fine
  for a demo but not for real data. That's what Qdrant's HNSW index is for, and
  why Qdrant is the preferred option.
- **Ingestion runs in a FastAPI background task**, so it dies if the process
  restarts mid-upload. Celery or RQ with retries would be the proper fix.
- **Chunking is fixed-size.** Splitting on clause boundaries instead would keep
  legal provisions in one piece. This is the next thing I'd do.
- **I haven't measured retrieval quality.** I can explain why the architecture
  should work, but I don't have numbers. A labelled set of questions and
  recall@k would settle it.
- **Rate limiting fails open** if Redis is down. Fine for a demo, wrong for
  anything public.

---

## Licence

MIT.
