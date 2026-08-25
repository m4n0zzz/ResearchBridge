from __future__ import annotations

from app.ai import local_embedding
from app.demo import build_demo_artifacts
from app.insights import calculate_insights
from app.parsers import parse_upload
from app.service import ingest_artifact


def load_demo(store, settings):
    for demo in build_demo_artifacts():
        artifact = parse_upload(demo.data, demo.filename, settings)
        ingest_artifact(store, None, artifact, settings, pre_extracted=demo.extraction, use_local_embeddings=True)


def test_collaboration_scoring_is_evidence_backed(store, settings):
    load_demo(store, settings)
    insights = store.rows("SELECT * FROM insights WHERE insight_type='COLLABORATION_OPPORTUNITY'")
    assert insights
    assert any("different research groups" in item["explanation"] for item in insights)
    assert all("Why this was suggested" in item["explanation"] for item in insights)


def test_genuine_overlap_scoring_and_derived_edge(store, settings):
    load_demo(store, settings)
    insights = store.rows("SELECT * FROM insights WHERE insight_type='POTENTIAL_OVERLAP'")
    assert insights
    assert any("FieldLeaf-2026" in item["explanation"] and "Resize normalization" in item["explanation"] for item in insights)
    assert store.rows("SELECT * FROM relationships WHERE relationship_type='POTENTIAL_OVERLAP' AND derived=1")
    assert all("not a finding of plagiarism or misconduct" in item["explanation"] for item in insights)


def test_similar_topic_without_shared_method_or_dataset_is_not_overlap(store, settings):
    shared_vector = local_embedding("crop disease classification field images")
    left = store.add_document(filename="a.md", artifact_type="markdown", content_hash="a", title="A", summary="A", raw_text="A", embedding=shared_vector)
    right = store.add_document(filename="b.md", artifact_type="markdown", content_hash="b", title="B", summary="B", raw_text="B", embedding=shared_vector)
    topic = store.add_entity(entity_type="TOPIC", canonical_name="crop disease", display_name="Crop disease", description="topic", confidence=1, embedding=shared_vector)
    method_a = store.add_entity(entity_type="METHOD", canonical_name="cnn", display_name="CNN", description="method", confidence=1, embedding=shared_vector)
    method_b = store.add_entity(entity_type="METHOD", canonical_name="field survey", display_name="Field survey", description="method", confidence=1, embedding=shared_vector)
    for document, entities in ((left, (topic, method_a)), (right, (topic, method_b))):
        for entity in entities: store.link_document_entity(document, entity)
    insights = calculate_insights(store, settings)
    assert not [item for item in insights if item["insight_type"] == "POTENTIAL_OVERLAP"]

