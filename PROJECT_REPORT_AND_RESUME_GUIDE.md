# Project Comprehensive Report & Interview Guide: ContractBuddy & DocuIntel RAG Platform

This document provides a thorough, clear, and easy-to-understand breakdown of the entire working system. It explains the project architecture, how each feature works step-by-step, how the frontend and backend interact, how to run and test it, and ATS-optimized bullet points for your resume and interview preparation.

---

## 1. Executive Summary & Architecture Overview

**ContractBuddy & DocuIntel** is an enterprise AI-powered Contract Management & Retrieval-Augmented Generation (RAG) platform. It allows users to upload PDF and Word (`.docx`) contracts/documents, extract structured legal metadata and risk scores, perform hybrid vector + keyword search, chat with documents via LLMs with exact page-level inline citations (`[S1]`, `[S2]`), and trigger automated transactional email notifications via **SendGrid**.

### High-Level System Architecture Diagram

```
                                +-------------------------------------------+
                                |  Vanilla HTML5 / CSS3 / ES6 Web Frontend  |
                                |   (Glassmorphism UI, SSE Stream, JS API)  |
                                +---------------------+---------------------+
                                                      |
                                           HTTP / REST / SSE Stream
                                                      |
                                                      v
                                +---------------------+---------------------+
                                |      FastAPI ASGI Server (Python 3.12)    |
                                |     Serves both API Routes and Frontend   |
                                +----------+-------------------+------------+
                                           |                   |
                     +---------------------+                   +---------------------+
                     |                                                               |
                     v                                                               v
   +-----------------+-----------------+                           +-----------------+-----------------+
   |      Contract & Ingestion Engine   |                           |    Hybrid Retrieval & AI Engine    |
   | Parse -> Chunk -> Local Embedder  |                           |  Dense Vector + Postgres BM25   |
   +-----------------+-----------------+                           +-----------------+-----------------+
                     |                                                               |
          +----------+----------+                                         +----------+----------+
          |                     |                                         |                     |
          v                     v                                         v                     v
   +--------------+      +--------------+                          +--------------+      +--------------+
   | SQLite / PG  |      | Vector DB    |                          | Groq / Gemini|      | SendGrid API |
   | Metadata     |      | (Qdrant)     |                          | LLM API      |      | Transaction  |
   +--------------+      +--------------+                          +--------------+      | Email Alerts |
                                                                                         +--------------+
```

---

## 2. Complete Technology Stack & Tools

### Backend Framework
* **Python 3.12:** Clean modern Python type hints (`list[str]`, `UUID`, `ConfigDict`).
* **FastAPI:** Async web framework supporting fast endpoints, dependency injection, and SSE (Server-Sent Events) streaming.
* **Uvicorn:** High-performance ASGI web server.
* **Pydantic v2 & Pydantic-Settings:** Type-safe data validation and environment variable parsing (`.env`).

### Database & Storage Stack
* **SQLite / PostgreSQL (Dual Compatible):** Flexible storage for users, contracts, contract versions, documents, chunks, and message logs. Configured with SQLAlchemy 2.0 Async (`AsyncSession`) and Alembic migrations.
* **Qdrant Vector Database:** Stores 384-dimensional dense vector embeddings generated from document chunks with payload filters (`user_id`, `document_id`, `page_number`).
* **Redis 7:** Supports token blacklisting on logout and sliding-window rate limiting.

### AI & NLP Pipeline
* **Local Embeddings (`SentenceTransformers`):** Runs `all-MiniLM-L6-v2` locally on CPU to embed text chunks into 384-dimensional vectors without external API latency or cost.
* **Local Reranker (`CrossEncoder`):** Runs `ms-marco-MiniLM-L-6-v2` to score joint query-document pairs and select top relevant context.
* **LLM Generation (Groq & Google Gemini):** Pluggable integration supporting Groq (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`) and Google Gemini (`gemini-1.5-flash`) for streaming answers.
* **SendGrid API:** Transactional email delivery service for automated response notifications.

### Frontend Interface
* **HTML5 / CSS3 / Vanilla JavaScript:** Zero build-tool overhead. Uses native `fetch` and SSE `ReadableStream` reader.
* **Glassmorphic UI Design System:** Custom dark theme featuring CSS variables, smooth gradient glows, responsive flexbox/grid layouts, micro-animations, document manager modal with drag-and-drop upload, and citations slide-out drawer.

---

## 3. End-to-End How It Works (Step-by-Step)

### Step 1: User Registration & Authentication
1. The user opens the frontend at `http://127.0.0.1:8000/`.
2. The browser loads `index.html` directly served by FastAPI.
3. Upon registration/login, the frontend sends a `POST` request to `/api/auth/register` or `/api/auth/login`.
4. FastAPI validates credentials, generates JWT `access_token` and `refresh_token`, and returns them.
5. `api.js` stores tokens in `localStorage` and automatically attaches `Authorization: Bearer <token>` to all subsequent requests.

### Step 2: Document & Contract Ingestion
1. In `app.html`, the user drags & drops a PDF or DOCX file into the Document Manager modal.
2. The file is sent via `POST /api/documents` or `POST /api/contracts`.
3. PyMuPDF or `python-docx` extracts raw text page-by-page.
4. Text is chunked into ~500 token windows with a 50-token overlap, preserving exact page numbers.
5. Local `SentenceTransformer` embeds chunks into 384-d vectors, which are saved in Qdrant, while text metadata is saved in SQLite/PostgreSQL.

### Step 3: Hybrid Retrieval & Grounded Q&A Chat
1. In the chat interface, the user asks a question.
2. The system executes dual-leg retrieval:
   - **Semantic Leg:** Qdrant vector search for conceptual matches.
   - **Lexical Leg:** Full-text keyword search (`content_tsv` / SQL search) for exact terms and IDs.
3. Candidate matches are fused using **Reciprocal Rank Fusion (RRF)**:
   $$\text{Score}(c) = \sum \frac{1}{60 + \text{rank}}$$
4. The local **Cross-Encoder reranker** scores top candidates to choose the top 5 most relevant context snippets.
5. The LLM (Groq or Gemini) streams answer tokens via SSE, inserting exact page-level inline citations (e.g. `[S1]`, `[S2]`).

### Step 4: Transactional Email Notification
1. Important summaries or generated answers can be emailed directly to the user using the **SendGrid** integration (`POST /generate-and-email`).
2. The backend formats the LLM output into plain text or HTML and dispatches it via SendGrid's API.

---

## 4. How to Run & Verify the Project

### Prerequisites
- Python 3.10+ installed
- Local environment or virtualenv (`backend/.venv`)

### Commands
```bash
# 1. Navigate to backend
cd backend

# 2. Run Database Migrations
python -m alembic upgrade head

# 3. Run Automated Pytest Suite
pytest

# 4. Start Full-Stack Server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### URLs
- **Web App UI:** `http://127.0.0.1:8000/`
- **Workspace:** `http://127.0.0.1:8000/app.html`
- **Admin Dashboard:** `http://127.0.0.1:8000/admin.html`
- **Swagger API Docs:** `http://127.0.0.1:8000/docs`

---

## 5. ATS Resume Bullets & Interview Guide

### Resume Bullet Points
* **Full-Stack AI Contract & RAG Management Platform:** Engineered an end-to-end Python FastAPI service integrating Qdrant Vector DB, Groq LLaMA-3 / Gemini APIs, and SendGrid for automated document intelligence and transactional email notifications.
* **Hybrid Retrieval & Reranking Pipeline:** Combined dense vector embeddings (`SentenceTransformers`) with lexical keyword search, fused candidate rankings via Reciprocal Rank Fusion (RRF), and applied a local Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) for sub-second grounded context selection.
* **Production-Grade Async Architecture:** Implemented JWT access/refresh token rotation, Redis sliding-window rate limiting, Pydantic v2 schemas, and Alembic database migrations.
* **Human-Crafted Web Frontend:** Designed a responsive glassmorphism UI using vanilla HTML5, CSS3, and ES6 JavaScript, supporting SSE token streaming and drag-and-drop file ingestion.

### Interview Technical Talk-Track
1. **Why FastAPI over Django?** Async performance for high-concurrency API calls and SSE streaming.
2. **Why Hybrid Search & RRF?** Dense vectors capture meaning; lexical search captures specific terms and numbers. RRF merges their different score scales reliably.
3. **Why Local Embeddings on 8 GB RAM?** Local MiniLM embeddings use ~100MB RAM, allowing full offline chunk vectorization without external API cost or latency.
4. **How SendGrid & LLMs Integrate?** A single async endpoint receives a prompt, fetches the LLM response from Groq/Gemini via `httpx`, and dispatches the formatted output to SendGrid's API.
