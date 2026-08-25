from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .ai import AIProvider, AIProviderError, cosine_similarity, local_embedding
from .config import Settings
from .insights import calculate_insights
from .models import ExtractedGraph
from .parsers import ParsedArtifact
from .store import GraphStore


class ExtractionValidationError(ValueError):
    pass


def _verified_location(source_text: str, quote: str, claimed_location: str) -> str:
    parts = quote.split()
    pattern = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(pattern, source_text, flags=re.IGNORECASE)
    if not match:
        raise ExtractionValidationError(f"Evidence excerpt was not found in source: {quote[:80]}")
    return f"{claimed_location}; verified chars {match.start()}-{match.end()}"


def validate_evidence(graph: ExtractedGraph, source_text: str) -> None:
    for owner in [*graph.entities, *graph.relationships]:
        for evidence in owner.evidence:
            _verified_location(source_text, evidence.quote, evidence.location)


def ingest_artifact(store: GraphStore, provider: AIProvider, artifact: ParsedArtifact,
                    settings: Settings, pre_extracted: ExtractedGraph | None = None,
                    use_local_embeddings: bool = False) -> int:
    graph = pre_extracted or provider.extract(artifact.text, artifact.filename, artifact.artifact_type)
    validate_evidence(graph, artifact.text)
    document_embedding_text = (
        "\n".join(
            f"{entity.type}: {entity.canonical_name}"
            for entity in graph.entities if entity.type.value in {"TOPIC", "METHOD", "DATASET", "SOFTWARE"}
        )
        if use_local_embeddings else
        f"{graph.document.title}\n{graph.document.summary}\n{artifact.text[:12000]}"
    )
    texts = [document_embedding_text] + [
        f"{entity.type}: {entity.name}. {entity.description}" for entity in graph.entities
    ]
    embeddings = [local_embedding(text) for text in texts] if use_local_embeddings else provider.embed(texts)
    if len(embeddings) != len(texts):
        raise ExtractionValidationError("Embedding response count did not match request count.")
    content_hash = hashlib.sha256(artifact.text.encode("utf-8")).hexdigest()
    entity_payloads = []
    for entity, embedding in zip(graph.entities, embeddings[1:]):
        entity_payloads.append({
            "local_id": entity.local_id, "type": entity.type.value, "canonical_name": entity.canonical_name,
            "display_name": entity.name, "description": entity.description, "confidence": entity.confidence,
            "embedding": embedding,
            "evidence": [{"excerpt": item.quote, "location": _verified_location(artifact.text, item.quote, item.location)}
                         for item in entity.evidence],
        })
    relationship_payloads = [{
        "source_local_id": relationship.source_local_id, "target_local_id": relationship.target_local_id,
        "type": relationship.type.value, "confidence": relationship.confidence,
        "explanation": f"Explicitly extracted from {graph.document.title}",
        "evidence": [{"excerpt": item.quote, "location": _verified_location(artifact.text, item.quote, item.location)}
                     for item in relationship.evidence],
    } for relationship in graph.relationships]
    document_id = store.persist_graph(
        document={"filename": artifact.filename, "artifact_type": artifact.artifact_type,
                  "content_hash": content_hash, "title": graph.document.title, "summary": graph.document.summary,
                  "raw_text": artifact.text, "embedding": embeddings[0]},
        entities=entity_payloads, relationships=relationship_payloads,
    )
    insights = calculate_insights(store, settings)
    store.replace_insights(insights)
    store.replace_derived_relationships(insights)
    return document_id


def query_graph(store: GraphStore, question: str, provider: AIProvider | None = None) -> dict[str, Any]:
    query_vector = provider.embed([question], task_type="RETRIEVAL_QUERY")[0] if provider else local_embedding(question)
    candidates: list[tuple[float, dict[str, Any], str]] = []
    for document in store.rows("SELECT id,title,summary,embedding FROM documents"):
        score = cosine_similarity(query_vector, json.loads(document["embedding"] or "[]"))
        candidates.append((score, document, "document"))
    for entity in store.rows("SELECT id,type,display_name,description,embedding FROM entities"):
        score = cosine_similarity(query_vector, json.loads(entity["embedding"] or "[]"))
        candidates.append((score, entity, "entity"))
    candidates.sort(key=lambda item: item[0], reverse=True)
    top = candidates[:8]
    entity_ids = [item[1]["id"] for item in top if item[2] == "entity"]
    paths = []
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        paths = store.rows(f"""SELECT r.id,r.relationship_type,r.confidence,s.display_name source,t.display_name target
                              FROM relationships r JOIN entities s ON s.id=r.source_entity_id JOIN entities t ON t.id=r.target_entity_id
                              WHERE r.source_entity_id IN ({placeholders}) OR r.target_entity_id IN ({placeholders}) LIMIT 20""",
                           tuple(entity_ids + entity_ids))
    relevant_document_ids = {item[1]["id"] for item in top if item[2] == "document"}
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        relevant_document_ids.update(row["document_id"] for row in store.rows(
            f"SELECT DISTINCT document_id FROM document_entities WHERE entity_id IN ({placeholders})", tuple(entity_ids)
        ))
    evidence_rows = []
    if relevant_document_ids:
        document_placeholders = ",".join("?" for _ in relevant_document_ids)
        evidence_rows = store.rows(
            f"""SELECT DISTINCT ev.excerpt,ev.location,d.title document_title,ev.document_id
                FROM evidence ev JOIN documents d ON d.id=ev.document_id
                WHERE ev.document_id IN ({document_placeholders}) ORDER BY ev.id LIMIT 120""",
            tuple(sorted(relevant_document_ids)),
        )
    terms = set(re.findall(r"[a-z0-9]{3,}", question.casefold()))
    evidence_rows.sort(key=lambda row: sum(term in row["excerpt"].casefold() for term in terms), reverse=True)
    selected_evidence = evidence_rows[:10]
    for index, row in enumerate(selected_evidence, start=1):
        row["reference"] = f"E{index}"
    evidence_text = "\n".join(f"[E{index}] {row['document_title']} ({row['location']}): {row['excerpt']}"
                              for index, row in enumerate(selected_evidence, start=1))
    if not selected_evidence:
        answer = "There is not enough ingested evidence to answer this question."
        caveats = ["No matching evidence was found."]
    elif provider:
        try:
            answer = provider.answer(question, evidence_text)
        except AIProviderError:
            answer = ""
        citations = {int(value) for value in re.findall(r"\[E(\d+)\]", answer)}
        if not answer or not citations or any(value < 1 or value > len(selected_evidence) for value in citations):
            excerpts = " ".join(
                f"[E{index}] {row['document_title']}: {row['excerpt']}"
                for index, row in enumerate(selected_evidence[:3], start=1)
            )
            answer = f"A fully cited synthesis was unavailable. Verified evidence: {excerpts}"
            caveats = ["Safe extractive fallback shown; no unavailable or uncited Gemini claims were returned."]
        else:
            caveats = ["Answer generated by Gemini strictly from retrieved graph evidence."]
    else:
        labels = "; ".join(f"{row['document_title']}: {row['excerpt']}" for row in selected_evidence[:3])
        answer = f"Local evidence retrieval found: {labels}"
        caveats = ["Gemini is not configured; this is an extractive local fallback, not an AI-generated synthesis."]
    relevant = [{"score": round(score, 3), "kind": kind,
                 **{key: value for key, value in item.items() if key != "embedding"}}
                for score, item, kind in top]
    return {"answer": answer, "relevant_nodes": relevant, "paths": paths,
            "evidence": selected_evidence, "caveats": caveats}
