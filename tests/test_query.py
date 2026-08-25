from app.ai import local_embedding
from app.service import query_graph


def test_query_evidence_is_restricted_to_vector_selected_documents(store):
    for index in range(10):
        relevant = index == 9
        text = "orchid blight sentinel finding" if relevant else f"unrelated archive item {index}"
        document_id = store.add_document(
            filename=f"{index}.md", artifact_type="markdown", content_hash=str(index), title=f"Study {index}",
            summary=text, raw_text=text, embedding=local_embedding(text),
        )
        entity_id = store.add_entity(
            entity_type="DOCUMENT", canonical_name=f"study {index}", display_name=f"Study {index}",
            description=text, confidence=1, embedding=local_embedding(text),
        )
        store.link_document_entity(document_id, entity_id)
        store.add_evidence(document_id=document_id, entity_id=entity_id, excerpt=text, location="body")
    result = query_graph(store, "orchid blight sentinel")
    assert "orchid blight sentinel finding" in result["answer"]
    assert all("embedding" not in item for item in result["relevant_nodes"])


def test_graph_api_does_not_expose_embeddings(store):
    entity_id = store.add_entity(entity_type="TOPIC", canonical_name="safe", display_name="Safe",
                                 description="Safe", confidence=1, embedding=[1.0, 0.0])
    assert entity_id
    assert all("embedding" not in node for node in store.graph()["nodes"])
