"""
Entity linking module for cross-asset element matching.

Creates entities for detected faces, objects, speakers, and locations,
then computes similarity scores between entities of the same type.

The system does NOT auto-merge entities. Instead, it:
1. Creates a ProjectEntity for each detected element
2. Computes similarity scores between entities of the same type
3. Stores potential matches in EntitySimilarity table
4. Agent/user can then confirm or reject matches
"""

import logging
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import Assets, ProjectEntity, EntitySimilarity
from utils.embeddings import get_embedding

logger = logging.getLogger(__name__)

# Similarity threshold for flagging potential matches
SIMILARITY_THRESHOLD = 0.70

# Entity type configurations
ENTITY_CONFIGS = {
    "face": {
        "source_field": "asset_faces",
        "embedding_fields": ["description", "notable_features", "clothing_visible"],
        "name_field": "description",
    },
    "object": {
        "source_field": "asset_objects",
        "embedding_fields": ["name", "description", "brand"],
        "name_field": "name",
    },
    "speaker": {
        "source_field": "asset_speakers",
        "embedding_fields": ["description", "voice_characteristics", "role"],
        "name_field": "description",
    },
    "location": {
        "source_field": "asset_scenes",
        "embedding_fields": ["location", "description", "mood"],
        "name_field": "location",
    },
}


def link_asset_entities(asset: Assets, db: Session) -> dict:
    """
    Main entry point: Extract entities from asset metadata and compute similarities.

    This function:
    1. Extracts faces, objects, speakers, locations from asset metadata
    2. Creates a ProjectEntity for each detected element
    3. Computes similarity with existing entities of the same type
    4. Stores potential matches (similarity >= 0.70) in EntitySimilarity

    Args:
        asset: The Assets model instance with metadata populated
        db: SQLAlchemy database session

    Returns:
        dict with counts of entities created and similarities found
    """
    entities_created = 0
    similarities_found = 0

    project_id = str(asset.project_id)
    asset_id = str(asset.asset_id)

    # Process each entity type
    for entity_type, config in ENTITY_CONFIGS.items():
        source_field = config["source_field"]
        source_data = getattr(asset, source_field, None)

        if not source_data:
            continue

        # Handle both list and dict formats
        items = source_data if isinstance(source_data, list) else [source_data]

        for item in items:
            if not item or not isinstance(item, dict):
                continue

            try:
                entity = _create_entity_from_detection(
                    project_id=project_id,
                    asset_id=asset_id,
                    entity_type=entity_type,
                    detection_data=item,
                    config=config,
                    db=db,
                )

                if entity:
                    entities_created += 1

                    # Compute similarities with existing entities
                    sim_count = _compute_similarities_for_entity(entity, db)
                    similarities_found += sim_count

            except Exception as e:
                logger.warning(
                    "Failed to create entity for %s in asset %s: %s",
                    entity_type,
                    asset_id,
                    str(e),
                )
                continue

    db.commit()

    return {
        "entities_created": entities_created,
        "similarities_found": similarities_found,
    }


def _create_entity_from_detection(
    project_id: str,
    asset_id: str,
    entity_type: str,
    detection_data: dict,
    config: dict,
    db: Session,
) -> ProjectEntity | None:
    """
    Create a ProjectEntity from a single detection (face, object, etc.).

    Args:
        project_id: Project UUID
        asset_id: Asset UUID where detection occurred
        entity_type: Type of entity (face, object, speaker, location)
        detection_data: Raw detection data from AI analysis
        config: Entity type configuration
        db: Database session

    Returns:
        Created ProjectEntity or None if creation failed
    """
    # Generate entity name
    name = _generate_entity_name(entity_type, detection_data, config)
    if not name:
        logger.debug("Could not generate name for %s entity, skipping", entity_type)
        return None

    # Build description for embedding
    description = _build_embedding_text(entity_type, detection_data, config)

    # Generate embedding
    embedding = None
    if description:
        embedding = get_embedding(description)
        if not embedding:
            logger.debug("Could not generate embedding for %s entity", entity_type)

    # Create entity
    entity = ProjectEntity(
        entity_id=uuid4(),
        project_id=project_id,
        asset_id=asset_id,
        entity_type=entity_type,
        name=name[:255],  # Truncate to fit column
        description=description[:2000] if description else None,
        embedding=embedding,
        source_data=detection_data,
    )

    db.add(entity)
    db.flush()  # Get entity_id assigned

    logger.debug(
        "Created %s entity: %s (id=%s)",
        entity_type,
        name[:50],
        entity.entity_id,
    )

    return entity


def _compute_similarities_for_entity(
    entity: ProjectEntity,
    db: Session,
) -> int:
    """
    Find existing entities of same type in project and compute similarity scores.
    Stores results in EntitySimilarity table for matches >= SIMILARITY_THRESHOLD.

    Args:
        entity: The newly created ProjectEntity
        db: Database session

    Returns:
        Count of similarities stored
    """
    if not entity.embedding:
        return 0

    # Find similar entities using vector search
    # Only search within same project and same entity type
    # Exclude the entity itself and any already-merged entities
    results = db.execute(
        text("""
            SELECT
                entity_id,
                1 - (embedding <=> :query_embedding) AS similarity
            FROM project_entities
            WHERE project_id = :project_id
              AND entity_type = :entity_type
              AND entity_id != :current_entity_id
              AND merged_into_id IS NULL
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :query_embedding) >= :threshold
            ORDER BY embedding <=> :query_embedding
            LIMIT 20
        """),
        {
            "query_embedding": str(entity.embedding),
            "project_id": str(entity.project_id),
            "entity_type": entity.entity_type,
            "current_entity_id": str(entity.entity_id),
            "threshold": SIMILARITY_THRESHOLD,
        },
    ).fetchall()

    similarities_created = 0

    for row in results:
        other_entity_id = row.entity_id
        similarity_score = float(row.similarity)

        # Check if similarity already exists (in either direction)
        existing = db.execute(
            text("""
                SELECT id FROM entity_similarities
                WHERE (entity_a_id = :a AND entity_b_id = :b)
                   OR (entity_a_id = :b AND entity_b_id = :a)
                LIMIT 1
            """),
            {
                "a": str(entity.entity_id),
                "b": str(other_entity_id),
            },
        ).fetchone()

        if existing:
            continue

        # Create similarity record
        similarity = EntitySimilarity(
            id=uuid4(),
            entity_a_id=entity.entity_id,
            entity_b_id=other_entity_id,
            similarity_score=similarity_score,
            is_confirmed=None,  # Pending verification
        )

        db.add(similarity)
        similarities_created += 1

        logger.debug(
            "Found potential match: %s <-> %s (score=%.3f)",
            entity.entity_id,
            other_entity_id,
            similarity_score,
        )

    return similarities_created


def _build_embedding_text(entity_type: str, data: dict, config: dict) -> str:
    """
    Build descriptive text for embedding generation from detection data.

    Combines relevant fields into a coherent text description that can be
    embedded for similarity matching.

    Args:
        entity_type: Type of entity
        data: Detection data dictionary
        config: Entity type configuration

    Returns:
        Combined text for embedding
    """
    parts = []

    # Add entity type context
    type_labels = {
        "face": "Person",
        "object": "Object",
        "speaker": "Speaker",
        "location": "Location",
    }
    parts.append(f"{type_labels.get(entity_type, entity_type)}:")

    # Add configured fields
    for field in config.get("embedding_fields", []):
        value = data.get(field)
        if value:
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            parts.append(str(value))

    # Add any additional context fields
    additional_fields = {
        "face": ["expression", "apparent_age_range", "gender_presentation", "position"],
        "object": ["position", "prominence"],
        "speaker": ["speaking_time_percentage"],
        "location": ["key_content"],
    }

    for field in additional_fields.get(entity_type, []):
        value = data.get(field)
        if value:
            parts.append(f"{field}: {value}")

    return " ".join(parts)


def _generate_entity_name(entity_type: str, data: dict, config: dict) -> str:
    """
    Generate a human-readable name from detection data.

    Args:
        entity_type: Type of entity
        data: Detection data dictionary
        config: Entity type configuration

    Returns:
        Generated name string, or empty string if no name can be generated
    """
    name_field = config.get("name_field", "description")
    name = data.get(name_field, "")

    if not name:
        # Fallback to description if primary field is empty
        name = data.get("description", "")

    if not name:
        # Last resort: generate generic name
        type_labels = {
            "face": "Unknown Person",
            "object": "Unknown Object",
            "speaker": "Unknown Speaker",
            "location": "Unknown Location",
        }
        name = type_labels.get(entity_type, "Unknown Entity")

    # Clean up and truncate
    name = str(name).strip()

    # Take first sentence or first 100 chars, whichever is shorter
    if ". " in name:
        name = name.split(". ")[0]

    if len(name) > 100:
        name = name[:97] + "..."

    return name
