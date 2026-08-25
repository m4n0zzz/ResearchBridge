# ResearchBridge

> ResearchBridge converts university papers and repositories into an evidence-backed knowledge graph that reveals cross-department collaboration opportunities and potentially overlapping research.

ResearchBridge is a fully working **local hackathon prototype**. It does not claim that Vertex AI, AlloyDB, or Cloud Run are running. Those services are the target production architecture; this build uses the Gemini Developer API and SQLite because no GCP project, billing, credentials, or infrastructure were supplied.

## What works

- Text PDF, UTF-8 Markdown, and safely inspected repository ZIP ingestion
- Gemini structured extraction validated with Pydantic
- Exact source-evidence checks before data is persisted
- Gemini `gemini-embedding-001` embeddings stored locally as JSON
- SQLite node/edge graph with evidence, provenance, confidence, and duplicate protection
- Deterministic collaboration and potential-overlap scoring
- Vector retrieval, connected paths, evidence retrieval, and grounded Gemini answers
- Bundled, CDN-free interactive SVG graph
- Synthetic demonstration data that works without a Gemini key
- Responsive, keyboard-accessible UI with live status announcements

Potential overlap is always presented as a review signal. It is never described as plagiarism, misconduct, or confirmed redundancy.

## Run locally

Use Python 3.11–3.13 (3.12 recommended).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

For live ingestion and generated answers, edit `.env` locally and set `GEMINI_API_KEY`. Never put the key in browser code, source control, logs, or chat. The app is still fully explorable with **Load synthetic demo data** when the key is absent.

Start with one command:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Gemini smoke test

After adding the server-side key:

```powershell
.\.venv\Scripts\python.exe -m app.smoke
```

The command performs one real structured extraction and embedding request. It tries `GEMINI_MODEL` first (default `gemini-2.5-flash`) and then two Flash fallbacks, printing which model passed. No smoke-test content is persisted.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

All automated tests use deterministic local fakes. Mock output is never shown as live AI output.

## Container

```powershell
docker build -t researchbridge .
docker run --rm -p 8000:8000 --env-file .env -v researchbridge-data:/app/data researchbridge
```

The key remains server-side. The mounted volume persists the graph.

## Architecture

```text
Browser (bundled HTML/CSS/JS)
        │ upload / query / inspect
        ▼
FastAPI application (single container)
   ├── SafeParser: PDF / Markdown / ZIP, never executes content
   ├── AIProvider
   │     └── Gemini Developer API: structured extraction, embeddings, grounded answer
   ├── Validation: Pydantic schema + allowed types + endpoint + evidence checks
   ├── Insight engine: deterministic collaboration / overlap thresholds
   └── GraphStore
         └── SQLite: documents, entities, relationships, evidence, vectors, insights
```

`AIProvider` and `GraphStore` are explicit boundaries, not marketing labels. `GeminiProvider` and SQLite are their current implementations.

### Exact GCP migration path

| Local prototype | Target production deployment |
|---|---|
| Gemini Developer API through `GeminiProvider` | Vertex AI Gemini through a new `VertexAIProvider` |
| SQLite `embedding` JSON text | AlloyDB PostgreSQL vector columns with vector indexes |
| Application-code cosine similarity | AlloyDB vector-distance SQL and indexed nearest-neighbor retrieval |
| SQLite node/edge relational tables | Same relational model in AlloyDB with managed backups and connection pooling |
| Local single container | Cloud Run service with a service account, Secret Manager key/config, and AlloyDB connector |
| Local upload request | Cloud Storage object event or signed upload plus Cloud Run ingestion worker |

Production would additionally add asynchronous jobs, Cloud Logging with redaction, per-tenant authorization, rate limits, malware scanning, monitoring, and deletion/retention controls. None are represented as active here.

## Security choices

- ZIP entries are read in memory and never extracted to disk.
- Absolute, drive-qualified, and `..` ZIP paths are rejected.
- `.git`, dependencies, build output, images, binaries, locks, `.env`, credentials, tokens, key files, and content with high-confidence credential patterns are excluded.
- Aggregate request size, entry count, declared ZIP size, compression ratio, per-entry bytes, total text, upload count, and upload bytes are bounded.
- PDFs must be readable, unencrypted, text-based, and within page/text limits; OCR is outside this MVP.
- Uploaded content is wrapped as untrusted data and never executed.
- Gemini output must pass the schema, allowed enums, semantic endpoint checks, confidence bounds, non-empty evidence, and verified source-offset validation.
- Filenames are sanitized; duplicate content hashes are rejected.
- Browser rendering escapes data-derived strings.
- Artifact graph writes are atomic, and expensive endpoints have single-instance rate limits.

Live ingestion sends parsed artifact text to Gemini and retains validated raw text in local SQLite. See [SECURITY.md](SECURITY.md) before using non-demo material. This local prototype has no authentication and must not be exposed directly to the public internet.

## Insight definitions

Thresholds live in `app/config.py`.

- **COLLABORATION_OPPORTUNITY** requires a shared topic, different researchers or departments, complementary datasets/methods/software, and no represented existing collaboration.
- **POTENTIAL_OVERLAP** requires high semantic document similarity and shared topic/method/dataset evidence. It is a human-review prompt only.

Every insight stores a score, a plain-language “Why this was suggested” explanation, and the contributing features.

## API summary

- `GET /api/health` — configuration-safe status and counts
- `POST /api/ingest` — multipart PDF/Markdown/ZIP ingestion; requires Gemini key
- `POST /api/demo/load` — idempotent synthetic artifact loader; no key required
- `GET /api/graph` — current graph, documents, and insights
- `GET /api/details/{node|edge|insight}/{id}` — provenance/evidence detail
- `POST /api/query` — grounded Gemini response, or clearly labeled local extractive fallback without a key
- `GET /docs` — generated FastAPI API documentation

## Known MVP limits

- No OCR for scanned PDFs.
- Synchronous ingestion; large deployments need a job queue.
- Local deterministic demo embeddings are for the synthetic fallback only, and the UI labels queries accordingly.
- SQLite cosine retrieval scans vectors in application code.
- No authentication or multi-tenancy, intentionally excluded from the two-hour scope.
