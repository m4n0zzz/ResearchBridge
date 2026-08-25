# Security notes

ResearchBridge is a local hackathon prototype, not a hardened multi-tenant service. Do not expose it directly to the public internet.

## Data handling

- Live ingestion sends parsed artifact text to the Gemini Developer API for extraction and embeddings.
- Validated raw text, evidence, entities, relationships, and embeddings are retained in the local SQLite database.
- Repository files with secret-like names or high-confidence credential patterns are excluded before any model request.
- Delete `data/researchbridge.db` to remove locally retained artifacts.

Do not upload confidential, regulated, or export-controlled material without an appropriate data-processing review.

## Protections in this prototype

- Aggregate request, file-count, file-size, PDF page/text, ZIP entry, declared-size, compression-ratio, member-size, and extracted-text limits
- ZIP traversal rejection and streamed member reads without filesystem extraction
- Filename and content-based secret rejection
- Structured model output, endpoint-type validation, evidence excerpt verification, and recorded source offsets
- Server-side API key, escaped browser output, parameterized SQL, atomic artifact writes, and rate limits on expensive endpoints
- Dependency advisory scan in CI

## Production requirements

Before production deployment, add identity-aware authentication and tenant authorization, distributed rate limiting, malware scanning, encrypted object storage, retention/deletion policy, audit logging with redaction, asynchronous isolated parsers, and managed secret delivery. Disable synthetic demo mutation and API documentation outside development.

Report vulnerabilities privately to the repository owner rather than opening an issue that contains exploit details or secrets.

