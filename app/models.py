from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EntityType(StrEnum):
    DOCUMENT = "DOCUMENT"
    RESEARCHER = "RESEARCHER"
    DEPARTMENT = "DEPARTMENT"
    TOPIC = "TOPIC"
    METHOD = "METHOD"
    DATASET = "DATASET"
    SOFTWARE = "SOFTWARE"
    PUBLICATION = "PUBLICATION"


class ExtractedRelationshipType(StrEnum):
    AUTHORED_BY = "AUTHORED_BY"
    AFFILIATED_WITH = "AFFILIATED_WITH"
    STUDIES = "STUDIES"
    USES_METHOD = "USES_METHOD"
    USES_DATASET = "USES_DATASET"
    IMPLEMENTS = "IMPLEMENTS"
    CITES = "CITES"
    RELATED_TO = "RELATED_TO"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=3, max_length=1500)
    location: str = Field(min_length=1, max_length=200)


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=400)
    summary: str = Field(min_length=1, max_length=1200)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_id: str = Field(min_length=1, max_length=80)
    type: EntityType
    name: str = Field(min_length=1, max_length=300)
    canonical_name: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=10)

    @field_validator("canonical_name")
    @classmethod
    def normalize_canonical(cls, value: str) -> str:
        return " ".join(value.strip().casefold().split())


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_local_id: str = Field(min_length=1, max_length=80)
    target_local_id: str = Field(min_length=1, max_length=80)
    type: ExtractedRelationshipType
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=10)


class ExtractedGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: ExtractedDocument
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=120)
    relationships: list[ExtractedRelationship] = Field(default_factory=list, max_length=240)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [entity.local_id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("entity local_id values must be unique")
        known = set(ids)
        entity_types = {entity.local_id: entity.type for entity in self.entities}
        if EntityType.DOCUMENT not in entity_types.values():
            raise ValueError("a DOCUMENT entity is required")
        endpoint_rules = {
            ExtractedRelationshipType.AUTHORED_BY: ({EntityType.DOCUMENT, EntityType.PUBLICATION}, {EntityType.RESEARCHER}),
            ExtractedRelationshipType.AFFILIATED_WITH: ({EntityType.RESEARCHER}, {EntityType.DEPARTMENT}),
            ExtractedRelationshipType.STUDIES: ({EntityType.DOCUMENT, EntityType.PUBLICATION, EntityType.RESEARCHER, EntityType.DEPARTMENT}, {EntityType.TOPIC}),
            ExtractedRelationshipType.USES_METHOD: ({EntityType.DOCUMENT, EntityType.PUBLICATION, EntityType.RESEARCHER, EntityType.SOFTWARE}, {EntityType.METHOD}),
            ExtractedRelationshipType.USES_DATASET: ({EntityType.DOCUMENT, EntityType.PUBLICATION, EntityType.RESEARCHER, EntityType.SOFTWARE}, {EntityType.DATASET}),
            ExtractedRelationshipType.IMPLEMENTS: ({EntityType.DOCUMENT, EntityType.PUBLICATION, EntityType.SOFTWARE}, {EntityType.SOFTWARE, EntityType.METHOD}),
            ExtractedRelationshipType.CITES: ({EntityType.DOCUMENT, EntityType.PUBLICATION}, {EntityType.DOCUMENT, EntityType.PUBLICATION}),
        }
        for relationship in self.relationships:
            if relationship.source_local_id not in known or relationship.target_local_id not in known:
                raise ValueError("relationship endpoint is absent")
            if relationship.type in endpoint_rules:
                allowed_sources, allowed_targets = endpoint_rules[relationship.type]
                if (entity_types[relationship.source_local_id] not in allowed_sources or
                        entity_types[relationship.target_local_id] not in allowed_targets):
                    raise ValueError(f"invalid endpoint types for {relationship.type}")
        return self


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=800)
