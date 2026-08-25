from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai import AIProvider, local_embedding
from app.config import Settings
from app.models import ExtractedGraph
from app.store import GraphStore


class FakeAI(AIProvider):
    def __init__(self, graph: ExtractedGraph | None = None, fail: bool = False):
        self.graph = graph
        self.fail = fail
        self.seen_text = ""

    def extract(self, text: str, filename: str, artifact_type: str) -> ExtractedGraph:
        self.seen_text = text
        if self.fail:
            raise RuntimeError("simulated API outage")
        assert self.graph is not None
        return self.graph

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        if self.fail:
            raise RuntimeError("simulated API outage")
        return [local_embedding(text) for text in texts]

    def answer(self, question: str, evidence: str) -> str:
        if self.fail:
            raise RuntimeError("simulated API outage")
        return "Grounded fake answer [E1]"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "test.db", gemini_api_key=None,
                    overlap_semantic_threshold=.76, collaboration_topic_threshold=.4)


@pytest.fixture
def store(settings: Settings) -> GraphStore:
    return GraphStore(settings.database_path)


@pytest.fixture
def sample_text() -> str:
    return "# Water Study\nAsha Lee studies water quality using linear regression."


@pytest.fixture
def sample_graph(sample_text: str) -> ExtractedGraph:
    return ExtractedGraph.model_validate({
        "document": {"title": "Water Study", "summary": "A study of water quality."},
        "entities": [
            {"local_id": "doc", "type": "DOCUMENT", "name": "Water Study", "canonical_name": " Water   Study ", "description": "A paper.", "confidence": .99, "evidence": [{"quote": "Water Study", "location": "heading"}]},
            {"local_id": "author", "type": "RESEARCHER", "name": "Asha Lee", "canonical_name": "ASHA LEE", "description": "Researcher.", "confidence": .95, "evidence": [{"quote": "Asha Lee", "location": "line 2"}]},
            {"local_id": "method", "type": "METHOD", "name": "Linear regression", "canonical_name": "linear regression", "description": "Statistical method.", "confidence": .92, "evidence": [{"quote": "linear regression", "location": "line 2"}]},
        ],
        "relationships": [
            {"source_local_id": "doc", "target_local_id": "author", "type": "AUTHORED_BY", "confidence": .95, "evidence": [{"quote": "Asha Lee", "location": "line 2"}]},
            {"source_local_id": "doc", "target_local_id": "method", "type": "USES_METHOD", "confidence": .92, "evidence": [{"quote": "linear regression", "location": "line 2"}]},
        ],
    })


def make_pdf(text: str) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter, pageCompression=0)
    pdf.drawString(60, 740, text)
    pdf.save()
    return output.getvalue()

