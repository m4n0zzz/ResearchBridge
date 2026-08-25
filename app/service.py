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


def _join_names(values: list[str]) -> str:
    if not values:
        return "the supplied evidence"
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"


def _insight_evidence(store: GraphStore, document_ids: list[int], keywords: list[str], limit: int = 4) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in document_ids)
    rows = store.rows(
        f"""SELECT DISTINCT ev.excerpt,ev.location,d.title document_title,ev.document_id,
                   COALESCE(e.type,'') entity_type
            FROM evidence ev JOIN documents d ON d.id=ev.document_id
            LEFT JOIN entities e ON e.id=ev.entity_id
            WHERE ev.document_id IN ({placeholders})""",
        tuple(document_ids),
    )
    terms = [value.casefold() for value in keywords if value]

    def rank(row: dict[str, Any]) -> tuple[int, int]:
        excerpt = row["excerpt"].casefold()
        matches = sum(term in excerpt for term in terms)
        feature_bonus = 2 if row["entity_type"] in {"TOPIC", "METHOD", "DATASET", "SOFTWARE"} else 0
        useful_length = 1 if 20 <= len(row["excerpt"]) <= 500 else 0
        return matches * 10 + feature_bonus + useful_length, len(row["excerpt"])

    ranked = sorted(rows, key=rank, reverse=True)
    selected: list[dict[str, Any]] = []
    for document_id in document_ids:
        candidate = next((row for row in ranked if row["document_id"] == document_id), None)
        if candidate and candidate not in selected:
            selected.append(candidate)
    selected.extend(row for row in ranked if row not in selected)
    selected = selected[:limit]
    for index, row in enumerate(selected, start=1):
        row["reference"] = f"E{index}"
        row.pop("entity_type", None)
    return selected


def _preset_graph_answer(store: GraphStore, question: str) -> dict[str, Any] | None:
    normalized = " ".join(re.findall(r"[a-z0-9]+", question.casefold()))
    insight_type = None
    if "collaborat" in normalized and any(word in normalized for word in ("who", "which", "should")):
        insight_type = "COLLABORATION_OPPORTUNITY"
    elif "overlap" in normalized:
        insight_type = "POTENTIAL_OVERLAP"

    if insight_type:
        rows = store.rows(
            """SELECT i.*,s.title source_title,t.title target_title
               FROM insights i JOIN documents s ON s.id=i.source_document_id
               JOIN documents t ON t.id=i.target_document_id
               WHERE i.insight_type=? ORDER BY i.score DESC,i.id LIMIT 1""",
            (insight_type,),
        )
        if not rows:
            return None
        insight = rows[0]
        features = json.loads(insight["evidence"])
        if insight_type == "COLLABORATION_OPPORTUNITY":
            keywords = [*features.get("shared_topics", []), *features.get("left_complements", []),
                        *features.get("right_complements", [])]
            evidence = _insight_evidence(
                store, [insight["source_document_id"], insight["target_document_id"]], keywords,
            )
            references = " ".join(f"[{row['reference']}]" for row in evidence)
            answer = (
                f"The strongest collaboration match is {insight['source_title']} with "
                f"{insight['target_title']} ({insight['score']:.0%} score). Both address "
                f"{_join_names(features.get('shared_topics', []))}. The first contributes "
                f"{_join_names(features.get('left_complements', []))}; the second contributes "
                f"{_join_names(features.get('right_complements', []))}. {references}"
            )
        else:
            keywords = features.get("shared_evidence", [])
            evidence = _insight_evidence(
                store, [insight["source_document_id"], insight["target_document_id"]], keywords,
            )
            references = " ".join(f"[{row['reference']}]" for row in evidence)
            answer = (
                f"The strongest review signal is between {insight['source_title']} and "
                f"{insight['target_title']} ({insight['score']:.0%} score). They explicitly share "
                f"{_join_names(keywords)}. This signals possible research overlap for coordination, "
                f"not plagiarism or misconduct. {references}"
            )
        return {
            "answer": answer, "relevant_nodes": [], "paths": [], "evidence": evidence,
            "caveats": ["Deterministic answer generated from scored graph insights and verified source evidence."],
        }

    if "dataset" in normalized and any(word in normalized for word in ("shared", "same", "which", "use")):
        datasets = store.rows(
            """SELECT e.id,e.display_name,COUNT(DISTINCT de.document_id) document_count
               FROM entities e JOIN document_entities de ON de.entity_id=e.id
               WHERE e.type='DATASET' GROUP BY e.id,e.display_name
               HAVING COUNT(DISTINCT de.document_id)>1
               ORDER BY document_count DESC,e.display_name LIMIT 1"""
        )
        if not datasets:
            return None
        dataset = datasets[0]
        documents = store.rows(
            """SELECT d.id,d.title FROM document_entities de JOIN documents d ON d.id=de.document_id
               WHERE de.entity_id=? ORDER BY d.title""",
            (dataset["id"],),
        )
        evidence = store.rows(
            """SELECT DISTINCT ev.excerpt,ev.location,d.title document_title,ev.document_id
               FROM evidence ev JOIN documents d ON d.id=ev.document_id
               WHERE ev.entity_id=? ORDER BY d.title LIMIT 6""",
            (dataset["id"],),
        )
        for index, row in enumerate(evidence, start=1):
            row["reference"] = f"E{index}"
        references = " ".join(f"[{row['reference']}]" for row in evidence)
        answer = (
            f"{dataset['display_name']} is shared by {dataset['document_count']} artifacts: "
            f"{_join_names([row['title'] for row in documents])}. {references}"
        )
        return {
            "answer": answer, "relevant_nodes": [], "paths": [], "evidence": evidence,
            "caveats": ["Deterministic answer generated from dataset-to-document graph links."],
        }
    return None


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
    preset = _preset_graph_answer(store, question)
    if preset:
        return preset
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
