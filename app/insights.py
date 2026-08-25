from __future__ import annotations

import itertools
import json
from collections import defaultdict
from typing import Any

from .ai import cosine_similarity
from .config import Settings
from .store import GraphStore


FEATURE_TYPES = {"METHOD", "DATASET", "SOFTWARE"}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _names(values: set[str]) -> str:
    return ", ".join(sorted(values))


def calculate_insights(store: GraphStore, settings: Settings) -> list[dict[str, Any]]:
    documents = store.rows("SELECT id,title,embedding FROM documents ORDER BY id")
    entity_rows = store.rows("""SELECT de.document_id,e.type,e.canonical_name,e.display_name
                              FROM document_entities de JOIN entities e ON e.id=de.entity_id""")
    by_document: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    display: dict[str, str] = {}
    for row in entity_rows:
        by_document[row["document_id"]][row["type"]].add(row["canonical_name"])
        display[row["canonical_name"]] = row["display_name"]
    document_entity_rows = store.rows("""SELECT de.document_id,de.entity_id FROM document_entities de
                                       JOIN entities e ON e.id=de.entity_id WHERE e.type='DOCUMENT'""")
    entity_to_document = {row["entity_id"]: row["document_id"] for row in document_entity_rows}
    represented_collaborations: set[frozenset[int]] = set()
    for row in store.rows("""SELECT source_entity_id,target_entity_id FROM relationships
                           WHERE relationship_type='RELATED_TO' AND derived=0"""):
        source_document = entity_to_document.get(row["source_entity_id"])
        target_document = entity_to_document.get(row["target_entity_id"])
        if source_document and target_document:
            represented_collaborations.add(frozenset((source_document, target_document)))

    results: list[dict[str, Any]] = []
    for left, right in itertools.combinations(documents, 2):
        left_sets, right_sets = by_document[left["id"]], by_document[right["id"]]
        shared_topics = left_sets["TOPIC"] & right_sets["TOPIC"]
        shared_methods = left_sets["METHOD"] & right_sets["METHOD"]
        shared_datasets = left_sets["DATASET"] & right_sets["DATASET"]
        shared_features = shared_methods | shared_datasets
        topic_score = _jaccard(left_sets["TOPIC"], right_sets["TOPIC"])

        left_vector = json.loads(left["embedding"] or "[]")
        right_vector = json.loads(right["embedding"] or "[]")
        semantic = max(0.0, cosine_similarity(left_vector, right_vector))

        different_people = bool(left_sets["RESEARCHER"] and right_sets["RESEARCHER"] and
                                left_sets["RESEARCHER"].isdisjoint(right_sets["RESEARCHER"]))
        different_departments = bool(left_sets["DEPARTMENT"] and right_sets["DEPARTMENT"] and
                                     left_sets["DEPARTMENT"].isdisjoint(right_sets["DEPARTMENT"]))
        existing_collaboration = bool(left_sets["RESEARCHER"] & right_sets["RESEARCHER"]) or \
            frozenset((left["id"], right["id"])) in represented_collaborations
        left_complement = set().union(*(left_sets[k] - right_sets[k] for k in FEATURE_TYPES))
        right_complement = set().union(*(right_sets[k] - left_sets[k] for k in FEATURE_TYPES))

        if (shared_topics and topic_score >= settings.collaboration_topic_threshold and
                (different_people or different_departments) and not existing_collaboration and
                left_complement and right_complement):
            score = min(0.99, 0.40 + 0.25 * topic_score + 0.15 * semantic + 0.10 * min(1, len(left_complement)) + 0.10 * min(1, len(right_complement)))
            topic_names = {display[name] for name in shared_topics}
            left_names = {display[name] for name in left_complement}
            right_names = {display[name] for name in right_complement}
            results.append({
                "insight_type": "COLLABORATION_OPPORTUNITY", "source_document_id": left["id"],
                "target_document_id": right["id"], "score": round(score, 3),
                "explanation": f"Why this was suggested: both studies address {_names(topic_names)}, while '{left['title']}' contributes {_names(left_names)} and '{right['title']}' contributes {_names(right_names)} across different research groups.",
                "evidence": {"shared_topics": sorted(topic_names), "left_complements": sorted(left_names),
                             "right_complements": sorted(right_names), "semantic_similarity": round(semantic, 3)},
            })

        overlap_basis = shared_topics | shared_methods | shared_datasets
        if semantic >= settings.overlap_semantic_threshold and overlap_basis and (shared_methods or shared_datasets):
            score = min(0.99, 0.55 * semantic + 0.20 * min(1, len(shared_topics)) + 0.15 * min(1, len(shared_methods)) + 0.10 * min(1, len(shared_datasets)))
            basis_names = {display[name] for name in overlap_basis}
            results.append({
                "insight_type": "POTENTIAL_OVERLAP", "source_document_id": left["id"],
                "target_document_id": right["id"], "score": round(score, 3),
                "explanation": f"Why this was suggested: semantic similarity is {semantic:.0%} and both artifacts explicitly reference {_names(basis_names)}. This is a review signal, not a finding of plagiarism or misconduct.",
                "evidence": {"semantic_similarity": round(semantic, 3), "shared_evidence": sorted(basis_names)},
            })
    return results
