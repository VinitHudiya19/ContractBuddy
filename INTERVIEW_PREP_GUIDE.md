# Contract Buddy — interview guide

Everything here matches the code. If you can't point at the file, don't say it.

---

## The 45-second pitch

> "It's a document Q&A system — you upload a contract and ask questions about it
> in plain English, and every answer cites the page it came from.
>
> The part I'd actually talk about is retrieval. Plain vector search kept missing
> exact strings like contract numbers and 'Net 45', so I run two searches in
> parallel: dense semantic search for meaning, and keyword search for exact
> matches. Merging them is the tricky bit, because cosine similarity and
> Postgres `ts_rank` are on completely different scales — so I use Reciprocal
> Rank Fusion, which throws away the scores and merges on rank position instead.
> Then a cross-encoder reranks the top candidates before they go to the model.
>
> It runs on Postgres, Qdrant and Redis in Docker, but every one of those has a
> fallback, so you can clone it and run it with one command and no API key."

**Then stop talking.** Let them pick the thread.

---

## The five questions you will get

### 1. Why hybrid search instead of just vectors?

Because they fail differently.

Embeddings capture meaning — "cost" matches "pricing" — but they compress text
into 384 floats, so exact tokens get blurred. Ask for contract `CNT-2026-1758`
and a vector search returns things that *look like* contract numbers.

Keyword search is the opposite: perfect on exact strings, useless when the
question and the document use different words for the same thing.

Running both and fusing them means you only lose a chunk when *both* methods
miss it.

📁 `app/services/hybrid_retrieval.py` — `_vector_leg`, `_keyword_leg`, run
concurrently under `asyncio.gather` since only the keyword leg touches the DB
session.

---

### 2. How does RRF work, and why not just average the scores?

Averaging assumes the scores are comparable. They aren't — cosine similarity is
roughly 0–1 with everything bunched near the top; `ts_rank` is unbounded and
depends on term frequency and document length. Whichever leg happens to produce
bigger numbers wins every time, which has nothing to do with relevance.

RRF ignores score magnitude entirely and uses rank position:

```
score(d) = Σ  1 / (k + rank(d))        k = 60
          legs
```

`k = 60` flattens the curve near the top, so rank 1 and rank 2 are worth almost
the same. That's deliberate: it means **agreement across the two legs beats a
strong showing in one**. A chunk both legs rank second outranks a chunk one leg
ranks first.

📁 `app/services/hybrid_retrieval.py` → `_rrf_merge`
🧪 `tests/test_retrieval.py::TestReciprocalRankFusion` — the test asserts exactly
that property.

---

### 3. Why a reranker if you already have embeddings?

Different architecture, different tradeoff.

The embedding model is a **bi-encoder**: it encodes the question and the chunk
*separately*, so chunk vectors are computed once at upload time and reused. That
is what makes search fast — but the two texts never see each other, so their
interaction is lost.

A **cross-encoder** takes `[CLS] question [SEP] chunk [SEP]` as one input and runs
full attention across both. Much more accurate, but it's a forward pass *per
pair* — you can't run it over the whole corpus.

So: cheap method to get from thousands of chunks down to ~30, expensive method to
get from 30 down to 5. That's the whole retrieve-then-rerank pattern.

📁 `app/services/hybrid_retrieval.py` → `_rerank`, wrapped in `asyncio.to_thread`
so the CPU-bound model never blocks the event loop.

---

### 4. How do you stop one user seeing another user's documents?

The filter is applied **before** the similarity search, never after.

- **Qdrant** — `user_id` goes in as a payload filter inside the search request,
  so foreign vectors are never scored, let alone returned.
- **SQL vector store** — `WHERE user_id = ...` before anything is loaded into the
  NumPy matrix.
- **Retrieval entry point** — resolves the user's own `ready` documents first and
  only searches within those ids.
- **404, not 403** — asking for someone else's document tells you nothing about
  whether it exists.

Filtering *after* retrieval would be the bug: you'd fetch the global top 15, then
discard most of them, and a user with lots of data could crowd out everyone
else's results.

📁 `app/db/qdrant_client.py` → `_user_filter`
🧪 `tests/test_auth.py::TestTenantIsolation`

---

### 5. What would you fix first?

Have a real answer ready. Pick one:

- **Retrieval evaluation.** Right now the architecture is justified by reasoning,
  not measurement. I'd label ~50 question/passage pairs and track recall@k, then
  actually verify the reranker earns its latency.
- **Ingestion is a FastAPI background task**, so it dies with the process and has
  no retries. Celery or RQ with a real queue.
- **Clause-aware chunking.** Fixed 500-token windows cut legal provisions in
  half. Splitting on numbered clause boundaries would keep them intact.

Naming a real limitation is worth more than defending a perfect design.

---

## Things they might poke at

**"Your vector store is a loop over every row."**
Only the SQLite fallback, and yes — O(n). It exists so the project runs with one
command and no Docker. Qdrant is the real path and uses HNSW, an approximate
nearest-neighbour graph. Both sit behind the same `VectorStore` interface, so
nothing above them knows which is active. 📁 `app/db/vector_store.py`

**"What happens with no API key?"**
It falls back to an extractive provider that selects the sentences overlapping
the question and returns them verbatim, with a notice saying generation is
disabled. It does not fabricate an answer and present it as a model's.
📁 `app/providers/llm/extractive_provider.py`

**"How does streaming work?"**
Server-Sent Events via `sse-starlette`. Three event types: `meta` up front with
the citations, `token` per piece of text, `done` with the persisted message id.
SSE rather than WebSockets because it's one-directional — the browser never sends
anything mid-stream, so full duplex buys nothing.
📁 `app/api/v1/conversations.py` → `_stream_answer`

**"Where does the LLM's JSON get validated?"**
`contract_analysis._coerce`. Models return `"$1,250.50"` where a float belongs,
`150` for a 0–100 score, a string where a list belongs, and JSON wrapped in code
fences. Every field is parsed and clamped before it reaches the database.
🧪 `tests/test_contract_analysis.py::TestFieldCoercion`

**"Why repositories instead of querying in the route?"**
So tenant scoping lives in one place. `get_owned(document_id, user_id)` is the
only way a route fetches a document, which makes "did we check ownership?"
answerable by reading one file instead of every handler.

---

## The bug story — your best material

Interviewers like debugging stories more than architecture diagrams. This one is
true and you can walk through it end to end:

**Symptom:** every question returned "I couldn't find anything relevant in your
documents", even though uploads succeeded and chunks were in the database.

**Cause:** two bugs in one function, both hidden by a broad `except Exception`.
The vector leg called `qdrant_client.search_vectors(...)` — the function was
named `search`. It also called `embedder.embed_query(...)` — the method was
`embed_one`. Both raised `AttributeError`, the bare `except` swallowed it and
returned an empty list, which is indistinguishable from "no results". The keyword
leg then fell back to matching the first 30 characters of the question as a
literal substring, which never matches anything.

**Fix:** correct both calls, and stop the handler from lying. It now logs the
exception type and message and states it is falling back to keyword-only, so a
dead leg looks like a dead leg instead of an empty corpus.

**Lesson:** a fallback you can't distinguish from a legitimate empty result isn't
resilience, it's a silent failure. The regression test asserts on the citation
snippet, so it fails if retrieval ever goes dark again.

---

## Numbers you can quote

Measured locally — say "on my laptop", never "in production":

- Warm query, end to end: **~1.2 s** (vector ~100 ms, keyword ~7 ms, rerank
  ~200 ms, the rest is the Groq call)
- SQL vector store on a small corpus: **~25 ms**
- Chunking: ~500 tokens, 50-token overlap
- Embeddings: 384-dim, cosine
- RRF constant: `k = 60`
- Retrieve 15 + 15 → fuse to 30 → rerank to 5

**Never quote a number you haven't measured.** If asked about scale: "I've run it
on tens of documents; the Qdrant path is what I'd use beyond that, and I'd want
to load-test before claiming a figure."

---

## Resume bullets

Each one is defensible against the code:

- Built a multi-tenant RAG document Q&A service (FastAPI, PostgreSQL, Qdrant,
  Redis) with page-level citation grounding and SSE token streaming.
- Implemented hybrid retrieval combining dense vector search with PostgreSQL
  full-text search, fused via Reciprocal Rank Fusion, then reranked with a local
  cross-encoder — no per-query API cost for retrieval.
- Designed a pluggable vector-store abstraction with Qdrant and SQL backends, so
  the system runs either against the full Docker stack or from a clean checkout
  with a single command.
- Enforced tenant isolation with pre-search payload and SQL filters, covered by
  integration tests asserting cross-account access returns 404.
- Wrote 52 pytest unit and integration tests that run without Docker, network or
  API keys, wired into GitHub Actions alongside ruff.

---

## Demo script (3 minutes)

1. Start the server — point out `/health` showing which backends resolved.
2. Log in, upload a contract PDF, show the status go `processing → ready`.
3. Ask "What are the payment terms?" and let the answer stream in.
4. **Click a citation chip.** This is the moment: the exact source snippet and
   page number. That's what separates it from a chatbot.
5. Contracts tab → missing-clause detection and the `analysis_source` badge.
6. Admin tab → per-user document and query counts, i.e. multi-tenancy is real.

Have a contract PDF ready on the desktop. Don't hunt for a file on a call.
