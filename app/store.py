from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, filename TEXT NOT NULL, artifact_type TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE, title TEXT NOT NULL, summary TEXT NOT NULL,
  raw_text TEXT NOT NULL, embedding TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY, type TEXT NOT NULL, canonical_name TEXT NOT NULL,
  display_name TEXT NOT NULL, description TEXT NOT NULL, confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
  embedding TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(type, canonical_name)
);
CREATE TABLE IF NOT EXISTS relationships (
  id INTEGER PRIMARY KEY, source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  relationship_type TEXT NOT NULL, confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
  explanation TEXT NOT NULL, derived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source_entity_id, target_entity_id, relationship_type)
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
  relationship_id INTEGER REFERENCES relationships(id) ON DELETE CASCADE,
  excerpt TEXT NOT NULL, location TEXT NOT NULL,
  CHECK(entity_id IS NOT NULL OR relationship_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS document_entities (
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  PRIMARY KEY(document_id, entity_id)
);
CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY, insight_type TEXT NOT NULL,
  source_document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  target_document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  score REAL NOT NULL CHECK(score BETWEEN 0 AND 1), explanation TEXT NOT NULL,
  evidence TEXT NOT NULL, UNIQUE(insight_type, source_document_id, target_document_id)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_relationship ON evidence(relationship_id);
"""


class DuplicateDocumentError(ValueError):
    pass


class GraphStore:
    """Storage boundary designed to be replaceable by an AlloyDB implementation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    def clear(self) -> None:
        with self.connection() as connection:
            for table in ("evidence", "relationships", "document_entities", "insights", "entities", "documents"):
                connection.execute(f"DELETE FROM {table}")

    def persist_graph(self, *, document: dict[str, Any], entities: list[dict[str, Any]],
                      relationships: list[dict[str, Any]]) -> int:
        """Persist one extracted artifact atomically so a failed edge cannot strand a partial document."""
        try:
            with self.connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO documents(filename,artifact_type,content_hash,title,summary,raw_text,embedding) VALUES(?,?,?,?,?,?,?)",
                    (document["filename"], document["artifact_type"], document["content_hash"], document["title"],
                     document["summary"], document["raw_text"], json.dumps(document["embedding"])),
                )
                document_id = int(cursor.lastrowid)
                local_to_global: dict[str, int] = {}
                for entity in entities:
                    connection.execute(
                        """INSERT INTO entities(type,canonical_name,display_name,description,confidence,embedding)
                           VALUES(?,?,?,?,?,?) ON CONFLICT(type,canonical_name) DO UPDATE SET
                           display_name=excluded.display_name,
                           description=CASE WHEN length(excluded.description)>length(entities.description) THEN excluded.description ELSE entities.description END,
                           confidence=max(entities.confidence, excluded.confidence),
                           embedding=CASE WHEN entities.embedding IS NULL THEN excluded.embedding ELSE entities.embedding END""",
                        (entity["type"], entity["canonical_name"], entity["display_name"], entity["description"],
                         entity["confidence"], json.dumps(entity["embedding"])),
                    )
                    row = connection.execute(
                        "SELECT id FROM entities WHERE type=? AND canonical_name=?",
                        (entity["type"], entity["canonical_name"]),
                    ).fetchone()
                    entity_id = int(row["id"])
                    local_to_global[entity["local_id"]] = entity_id
                    connection.execute("INSERT OR IGNORE INTO document_entities VALUES(?,?)", (document_id, entity_id))
                    for item in entity["evidence"]:
                        connection.execute(
                            "INSERT INTO evidence(document_id,entity_id,relationship_id,excerpt,location) VALUES(?,?,NULL,?,?)",
                            (document_id, entity_id, item["excerpt"], item["location"]),
                        )
                for relationship in relationships:
                    source_id = local_to_global[relationship["source_local_id"]]
                    target_id = local_to_global[relationship["target_local_id"]]
                    connection.execute(
                        """INSERT INTO relationships(source_entity_id,target_entity_id,relationship_type,confidence,explanation,derived)
                           VALUES(?,?,?,?,?,0) ON CONFLICT(source_entity_id,target_entity_id,relationship_type) DO UPDATE SET
                           confidence=max(relationships.confidence, excluded.confidence), explanation=excluded.explanation""",
                        (source_id, target_id, relationship["type"], relationship["confidence"], relationship["explanation"]),
                    )
                    row = connection.execute(
                        "SELECT id FROM relationships WHERE source_entity_id=? AND target_entity_id=? AND relationship_type=?",
                        (source_id, target_id, relationship["type"]),
                    ).fetchone()
                    relationship_id = int(row["id"])
                    for item in relationship["evidence"]:
                        connection.execute(
                            "INSERT INTO evidence(document_id,entity_id,relationship_id,excerpt,location) VALUES(?,NULL,?,?,?)",
                            (document_id, relationship_id, item["excerpt"], item["location"]),
                        )
                return document_id
        except sqlite3.IntegrityError as exc:
            if "content_hash" in str(exc).casefold() or "documents.content_hash" in str(exc).casefold():
                raise DuplicateDocumentError("This exact artifact has already been ingested.") from exc
            raise

    def add_document(self, *, filename: str, artifact_type: str, content_hash: str, title: str,
                     summary: str, raw_text: str, embedding: list[float]) -> int:
        try:
            with self.connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO documents(filename,artifact_type,content_hash,title,summary,raw_text,embedding) VALUES(?,?,?,?,?,?,?)",
                    (filename, artifact_type, content_hash, title, summary, raw_text, json.dumps(embedding)),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            if "content_hash" in str(exc).casefold() or "unique" in str(exc).casefold():
                raise DuplicateDocumentError("This exact artifact has already been ingested.") from exc
            raise

    def add_entity(self, *, entity_type: str, canonical_name: str, display_name: str,
                   description: str, confidence: float, embedding: list[float]) -> int:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO entities(type,canonical_name,display_name,description,confidence,embedding)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(type,canonical_name) DO UPDATE SET
                   display_name=excluded.display_name,
                   description=CASE WHEN length(excluded.description)>length(entities.description) THEN excluded.description ELSE entities.description END,
                   confidence=max(entities.confidence, excluded.confidence),
                   embedding=CASE WHEN entities.embedding IS NULL THEN excluded.embedding ELSE entities.embedding END""",
                (entity_type, canonical_name, display_name, description, confidence, json.dumps(embedding)),
            )
            row = connection.execute(
                "SELECT id FROM entities WHERE type=? AND canonical_name=?", (entity_type, canonical_name)
            ).fetchone()
            return int(row["id"])

    def link_document_entity(self, document_id: int, entity_id: int) -> None:
        with self.connection() as connection:
            connection.execute("INSERT OR IGNORE INTO document_entities VALUES(?,?)", (document_id, entity_id))

    def add_relationship(self, *, source_id: int, target_id: int, relationship_type: str,
                         confidence: float, explanation: str, derived: bool = False) -> int:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO relationships(source_entity_id,target_entity_id,relationship_type,confidence,explanation,derived)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(source_entity_id,target_entity_id,relationship_type) DO UPDATE SET
                   confidence=max(relationships.confidence, excluded.confidence), explanation=excluded.explanation""",
                (source_id, target_id, relationship_type, confidence, explanation, int(derived)),
            )
            row = connection.execute(
                "SELECT id FROM relationships WHERE source_entity_id=? AND target_entity_id=? AND relationship_type=?",
                (source_id, target_id, relationship_type),
            ).fetchone()
            return int(row["id"])

    def add_evidence(self, *, document_id: int, excerpt: str, location: str,
                     entity_id: int | None = None, relationship_id: int | None = None) -> None:
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM evidence WHERE document_id=? AND entity_id IS ? AND relationship_id IS ? AND excerpt=?",
                (document_id, entity_id, relationship_id, excerpt),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO evidence(document_id,entity_id,relationship_id,excerpt,location) VALUES(?,?,?,?,?)",
                    (document_id, entity_id, relationship_id, excerpt, location),
                )

    def replace_insights(self, insights: list[dict[str, Any]]) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM insights")
            for item in insights:
                source, target = sorted((item["source_document_id"], item["target_document_id"]))
                connection.execute(
                    "INSERT INTO insights(insight_type,source_document_id,target_document_id,score,explanation,evidence) VALUES(?,?,?,?,?,?)",
                    (item["insight_type"], source, target, item["score"], item["explanation"], json.dumps(item["evidence"])),
                )

    def replace_derived_relationships(self, insights: list[dict[str, Any]]) -> None:
        """Mirror document-level insights into graph edges between their DOCUMENT entities."""
        with self.connection() as connection:
            connection.execute("DELETE FROM relationships WHERE derived=1")
            for item in insights:
                entity_rows = []
                for document_id in (item["source_document_id"], item["target_document_id"]):
                    row = connection.execute(
                        """SELECT e.id FROM document_entities de JOIN entities e ON e.id=de.entity_id
                           WHERE de.document_id=? AND e.type='DOCUMENT' ORDER BY e.id LIMIT 1""", (document_id,)
                    ).fetchone()
                    entity_rows.append(int(row["id"]) if row else None)
                if all(entity_rows):
                    connection.execute(
                        """INSERT INTO relationships(source_entity_id,target_entity_id,relationship_type,confidence,explanation,derived)
                           VALUES(?,?,?,?,?,1) ON CONFLICT(source_entity_id,target_entity_id,relationship_type) DO UPDATE SET
                           confidence=excluded.confidence, explanation=excluded.explanation, derived=1""",
                        (entity_rows[0], entity_rows[1], item["insight_type"], item["score"], item["explanation"]),
                    )

    def rows(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def graph(self) -> dict[str, Any]:
        nodes = self.rows("""SELECT e.id,e.type,e.canonical_name,e.display_name,e.description,e.confidence,e.created_at,
                           COUNT(DISTINCT de.document_id) document_count
                           FROM entities e LEFT JOIN document_entities de ON de.entity_id=e.id GROUP BY e.id ORDER BY e.id LIMIT 2000""")
        edges = self.rows("SELECT id,source_entity_id,target_entity_id,relationship_type,confidence,explanation,derived,created_at FROM relationships ORDER BY id LIMIT 5000")
        documents = self.rows("SELECT id,filename,artifact_type,title,summary,created_at FROM documents ORDER BY id LIMIT 1000")
        insights = self.rows("""SELECT i.*, a.title source_title, b.title target_title
                              FROM insights i JOIN documents a ON a.id=i.source_document_id
                              JOIN documents b ON b.id=i.target_document_id ORDER BY i.score DESC""")
        for item in insights:
            item["evidence"] = json.loads(item["evidence"])
        return {"nodes": nodes, "edges": edges, "documents": documents, "insights": insights}

    def details(self, kind: str, item_id: int) -> dict[str, Any] | None:
        if kind == "node":
            rows = self.rows("SELECT id,type,canonical_name,display_name,description,confidence,created_at FROM entities WHERE id=?", (item_id,))
            evidence = self.rows("""SELECT ev.*, d.title document_title FROM evidence ev
                                  JOIN documents d ON d.id=ev.document_id WHERE ev.entity_id=?""", (item_id,))
        elif kind == "edge":
            rows = self.rows("""SELECT r.*, s.display_name source_name, t.display_name target_name
                              FROM relationships r JOIN entities s ON s.id=r.source_entity_id
                              JOIN entities t ON t.id=r.target_entity_id WHERE r.id=?""", (item_id,))
            evidence = self.rows("""SELECT ev.*, d.title document_title FROM evidence ev
                                  JOIN documents d ON d.id=ev.document_id WHERE ev.relationship_id=?""", (item_id,))
        elif kind == "insight":
            rows = self.rows("""SELECT i.*, a.title source_title, b.title target_title FROM insights i
                              JOIN documents a ON a.id=i.source_document_id JOIN documents b ON b.id=i.target_document_id
                              WHERE i.id=?""", (item_id,))
            evidence = []
            if rows:
                rows[0]["evidence"] = json.loads(rows[0]["evidence"])
        else:
            return None
        return {"item": rows[0], "evidence": evidence} if rows else None

    def stats(self) -> dict[str, int]:
        with self.connection() as connection:
            return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in ("documents", "entities", "relationships", "insights")}
