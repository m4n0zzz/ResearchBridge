from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai import AIProviderError, GeminiProvider, MissingAPIKeyError
from .config import Settings, get_settings
from .demo import build_demo_artifacts
from .middleware import InMemoryRateLimitMiddleware, RequestSizeLimitMiddleware
from .models import QueryRequest
from .parsers import ParseError, parse_upload
from .service import ExtractionValidationError, ingest_artifact, query_graph
from .store import DuplicateDocumentError, GraphStore


BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database_path = settings.database_path
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path
    store = GraphStore(database_path)

    app = FastAPI(title="ResearchBridge", version="1.0.0")
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(InMemoryRateLimitMiddleware, limits={
        "/api/ingest": (10, 600), "/api/query": (60, 60), "/api/demo/load": (10, 60),
    })
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    def provider() -> GeminiProvider:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.gemini_embedding_model)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(BASE_DIR / "static" / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "ai_configured": bool(settings.gemini_api_key),
                "ai_model": settings.gemini_model if settings.gemini_api_key else None,
                "storage": "SQLite (local prototype)", "stats": store.stats()}

    @app.get("/api/graph")
    def graph():
        return store.graph()

    @app.get("/api/details/{kind}/{item_id}")
    def details(kind: str, item_id: int):
        result = store.details(kind, item_id)
        if not result:
            raise HTTPException(404, "Graph item not found")
        return result

    @app.post("/api/ingest")
    def ingest(files: list[UploadFile] = File(...)):
        if not files or len(files) > settings.max_upload_files:
            raise HTTPException(400, f"Upload between 1 and {settings.max_upload_files} files.")
        try:
            ai = provider()
        except MissingAPIKeyError as exc:
            raise HTTPException(503, f"{exc} Add it to .env, then restart the server.") from exc
        results = []
        for upload in files:
            filename = upload.filename or "upload"
            try:
                data = upload.file.read(settings.max_upload_bytes + 1)
                artifact = parse_upload(data, filename, settings)
                document_id = ingest_artifact(store, ai, artifact, settings)
                results.append({"filename": artifact.filename, "status": "ingested", "document_id": document_id})
            except (ParseError, DuplicateDocumentError, ExtractionValidationError, AIProviderError) as exc:
                results.append({"filename": filename, "status": "error", "error": str(exc)})
            finally:
                upload.file.close()
        return {"results": results, "stats": store.stats()}

    @app.post("/api/demo/load")
    def load_demo():
        results = []
        for demo in build_demo_artifacts():
            try:
                artifact = parse_upload(demo.data, demo.filename, settings)
                document_id = ingest_artifact(store, None, artifact, settings,
                                              pre_extracted=demo.extraction, use_local_embeddings=True)
                results.append({"filename": demo.filename, "status": "ingested", "document_id": document_id})
            except DuplicateDocumentError:
                results.append({"filename": demo.filename, "status": "already_loaded"})
            except (ParseError, ExtractionValidationError) as exc:
                results.append({"filename": demo.filename, "status": "error", "error": str(exc)})
        return {"synthetic": True, "message": "Synthetic demonstration artifacts loaded.",
                "results": results, "stats": store.stats()}

    @app.post("/api/query")
    def query(request: QueryRequest):
        try:
            ai = provider() if settings.gemini_api_key else None
            return query_graph(store, request.question, ai)
        except AIProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    return app


app = create_app()
