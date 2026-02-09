from uuid import uuid4
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Index,
    ForeignKey,
    Computed,
    Boolean,
    Float,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY, TSVECTOR
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from database.base import Base

EMBEDDING_DIMENSIONS = 1536


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID, primary_key=True, default=uuid4)
    secret_hash = Column(String(64), nullable=False)
    user_id = Column(UUID, ForeignKey("users.session_id"), nullable=True)
    scopes = Column(ARRAY(String), nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (Index("ix_sessions_expires_at", expires_at),)


class User(Base):
    __tablename__ = "users"

    session_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    last_activity = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return f"<User session_id={self.session_id} last_activity={self.last_activity} created_at={self.created_at}>"


class Project(Base):
    __tablename__ = "projects"

    project_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_name = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    owner_id = Column(UUID, ForeignKey("users.session_id"), nullable=False)

    def __repr__(self):
        return f"<Project project_id={self.project_id} project_name={self.project_name} created_at={self.created_at} updated_at={self.updated_at} owner_id={self.owner_id}>"


class Assets(Base):
    __tablename__ = "assets"

    asset_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    asset_name = Column(String, nullable=False)
    asset_type = Column(String, nullable=False)
    asset_url = Column(String, nullable=False)
    uploaded_at = Column(DateTime, nullable=False)
    project_id = Column(UUID, ForeignKey("projects.project_id"), nullable=False)

    asset_summary = Column(String, nullable=False)
    asset_tags = Column(JSONB, nullable=True)

    asset_transcript = Column(JSONB, nullable=True)

    asset_events = Column(JSONB, nullable=True)
    notable_shots = Column(JSONB, nullable=True)
    asset_scenes = Column(JSONB, nullable=True)

    audio_features = Column(JSONB, nullable=True)
    audio_structure = Column(JSONB, nullable=True)

    asset_faces = Column(JSONB, nullable=True)
    asset_objects = Column(JSONB, nullable=True)
    asset_colors = Column(JSONB, nullable=True)

    asset_technical = Column(JSONB, nullable=True)

    asset_speakers = Column(JSONB, nullable=True)

    indexing_status = Column(String, nullable=False, default="pending")
    indexing_error = Column(String, nullable=True)
    indexing_started_at = Column(DateTime, nullable=True)
    indexing_completed_at = Column(DateTime, nullable=True)
    indexing_attempts = Column(Integer, nullable=False, default=0)

    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    transcript_tsv = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', COALESCE(asset_transcript->>'text', ''))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_assets_embedding",
            embedding,
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_assets_transcript_tsv",
            transcript_tsv,
            postgresql_using="gin",
        ),
    )

    def __repr__(self):
        return f"<Assets asset_id={self.asset_id} asset_name={self.asset_name} asset_type={self.asset_type} project_id={self.project_id}>"


class VideoOutput(Base):
    __tablename__ = "video_outputs"

    video_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(UUID, ForeignKey("projects.project_id"), nullable=False)
    video_url = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    version = Column(Integer, nullable=False)
    changes = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<VideoOutput video_id={self.video_id} project_id={self.project_id} video_url={self.video_url} created_at={self.created_at} version={self.version} changes={self.changes}>"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(UUID, ForeignKey("projects.project_id"), nullable=False)
    trace = Column(JSONB, nullable=False)
    analysis_segments = Column(JSONB, nullable=False)

    def __repr__(self):
        return f"<AgentRun run_id={self.run_id} project_id={self.project_id} trace={self.trace} analysis_segments={self.analysis_segments}>"


class Timeline(Base):
    __tablename__ = "timelines"

    timeline_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name = Column(String, nullable=False)
    global_start_time = Column(JSONB, nullable=True)
    settings = Column(JSONB, nullable=False, default=dict)
    timeline_metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    current_version = Column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_timelines_project_id", project_id),)

    def __repr__(self):
        return (
            f"<Timeline timeline_id={self.timeline_id} "
            f"project_id={self.project_id} name={self.name} "
            f"current_version={self.current_version}>"
        )


class TimelineCheckpoint(Base):
    __tablename__ = "timeline_checkpoints"

    checkpoint_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    timeline_id = Column(
        UUID,
        ForeignKey("timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    parent_version = Column(Integer, nullable=True)
    snapshot = Column(JSONB, nullable=False)
    description = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    is_approved = Column(Boolean, nullable=False, default=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_timeline_checkpoints_timeline_version",
            timeline_id,
            version,
            unique=True,
        ),
        Index("ix_timeline_checkpoints_timeline_id", timeline_id),
        Index("ix_timeline_checkpoints_created_at", created_at),
    )

    def __repr__(self):
        return (
            f"<TimelineCheckpoint checkpoint_id={self.checkpoint_id} "
            f"timeline_id={self.timeline_id} version={self.version} "
            f"description={self.description[:50]}...>"
        )


class TimelineOperation(Base):
    __tablename__ = "timeline_operations"

    operation_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    checkpoint_id = Column(
        UUID,
        ForeignKey("timeline_checkpoints.checkpoint_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_type = Column(String, nullable=False)
    operation_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_timeline_operations_checkpoint_id", checkpoint_id),
        Index("ix_timeline_operations_operation_type", operation_type),
        Index("ix_timeline_operations_created_at", created_at),
    )

    def __repr__(self):
        return (
            f"<TimelineOperation operation_id={self.operation_id} "
            f"operation_type={self.operation_type} "
            f"checkpoint_id={self.checkpoint_id}>"
        )


class EditSession(Base):
    __tablename__ = "edit_sessions"

    session_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_id = Column(
        UUID,
        ForeignKey("timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by = Column(UUID, ForeignKey("users.session_id"), nullable=False)

    title = Column(String, nullable=True)
    messages = Column(JSONB, nullable=False, default=list)
    pending_patches = Column(JSONB, nullable=False, default=list)
    status = Column(String, nullable=False, default="active")

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_edit_sessions_project_id", project_id),
        Index("ix_edit_sessions_timeline_id", timeline_id),
        Index("ix_edit_sessions_status", status),
        Index("ix_edit_sessions_created_at", created_at),
    )

    def __repr__(self):
        return (
            f"<EditSession session_id={self.session_id} "
            f"project_id={self.project_id} status={self.status}>"
        )


class RenderJob(Base):
    __tablename__ = "render_jobs"

    job_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_id = Column(
        UUID,
        ForeignKey("timelines.timeline_id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_version = Column(Integer, nullable=False)

    job_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")

    progress = Column(Integer, nullable=False, default=0)
    current_frame = Column(Integer, nullable=True)
    total_frames = Column(Integer, nullable=True)

    preset = Column(JSONB, nullable=False)

    output_filename = Column(String, nullable=True)
    output_url = Column(String, nullable=True)
    output_size_bytes = Column(Integer, nullable=True)

    error_message = Column(String, nullable=True)
    error_details = Column(JSONB, nullable=True)

    cloud_run_job_name = Column(String, nullable=True)
    cloud_run_execution_id = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    job_metadata = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_render_jobs_project_id", project_id),
        Index("ix_render_jobs_status", status),
        Index("ix_render_jobs_created_at", created_at),
        Index("ix_render_jobs_project_status", project_id, status),
    )

    def __repr__(self):
        return (
            f"<RenderJob job_id={self.job_id} "
            f"project_id={self.project_id} "
            f"status={self.status} progress={self.progress}%>"
        )


class ProjectEntity(Base):
    """
    A detected element (face, object, speaker, location) from an asset.
    Each detection = one entity. Users/agents can merge entities that represent
    the same real-world thing.
    """

    __tablename__ = "project_entities"

    entity_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="CASCADE"),
        nullable=False,
    )

    entity_type = Column(String, nullable=False)  # "face", "object", "speaker", "location"
    name = Column(String, nullable=False)  # Auto-generated, user can edit
    description = Column(String, nullable=True)  # Full description from AI

    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    source_data = Column(JSONB, nullable=False)  # Original detection data (timestamps, etc.)

    # If this entity was merged into another, points to the primary entity
    merged_into_id = Column(
        UUID, ForeignKey("project_entities.entity_id"), nullable=True
    )

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_project_entities_project_id", project_id),
        Index("ix_project_entities_asset_id", asset_id),
        Index("ix_project_entities_type", entity_type),
        Index("ix_project_entities_merged", merged_into_id),
        Index(
            "ix_project_entities_embedding",
            embedding,
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self):
        return (
            f"<ProjectEntity entity_id={self.entity_id} "
            f"type={self.entity_type} name={self.name[:30]}>"
        )


class EntitySimilarity(Base):
    """
    Pre-computed similarity between two entities of the same type.
    Used to surface 'potential matches' to agent/user for verification.
    """

    __tablename__ = "entity_similarities"

    id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )

    entity_a_id = Column(
        UUID,
        ForeignKey("project_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_b_id = Column(
        UUID,
        ForeignKey("project_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )

    similarity_score = Column(Float, nullable=False)  # 0.0 - 1.0

    # Verification status: null=pending, True=confirmed same, False=confirmed different
    is_confirmed = Column(Boolean, nullable=True, default=None)
    confirmed_by = Column(String, nullable=True)  # "user" or "agent"
    confirmed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_entity_similarities_entity_a", entity_a_id),
        Index("ix_entity_similarities_entity_b", entity_b_id),
        Index("ix_entity_similarities_score", similarity_score.desc()),
        Index("ix_entity_similarities_unconfirmed", is_confirmed, postgresql_where=(is_confirmed.is_(None))),
    )

    def __repr__(self):
        return (
            f"<EntitySimilarity {self.entity_a_id} <-> {self.entity_b_id} "
            f"score={self.similarity_score:.2f} confirmed={self.is_confirmed}>"
        )


class Snippet(Base):
    __tablename__ = "snippets"

    snippet_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="CASCADE"),
        nullable=True,
    )

    snippet_type = Column(String, nullable=False)  # face, person, character, item
    source_type = Column(String, nullable=False)  # video_ingest, generated_asset, manual
    source_ref = Column(JSONB, nullable=False, default=dict)

    frame_index = Column(Integer, nullable=True)
    timestamp_ms = Column(Integer, nullable=True)
    bbox = Column(JSONB, nullable=True)

    crop_blob_path = Column(String, nullable=True)
    preview_blob_path = Column(String, nullable=True)

    descriptor = Column(String, nullable=True)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    tags = Column(JSONB, nullable=True)
    notes = Column(String, nullable=True)
    quality_score = Column(Float, nullable=True)

    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_snippets_project_id", project_id),
        Index("ix_snippets_asset_id", asset_id),
        Index("ix_snippets_type", snippet_type),
        Index("ix_snippets_source_type", source_type),
        Index(
            "ix_snippets_embedding",
            embedding,
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SnippetIdentity(Base):
    __tablename__ = "snippet_identities"

    identity_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )

    identity_type = Column(String, nullable=False)  # person, item
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")

    canonical_snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="SET NULL"),
        nullable=True,
    )
    prototype_embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    merged_into_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_snippet_identities_project_id", project_id),
        Index("ix_snippet_identities_type", identity_type),
        Index("ix_snippet_identities_status", status),
        Index("ix_snippet_identities_merged", merged_into_id),
        Index(
            "ix_snippet_identities_embedding",
            prototype_embedding,
            postgresql_using="ivfflat",
            postgresql_ops={"prototype_embedding": "vector_cosine_ops"},
        ),
    )


class SnippetIdentityLink(Base):
    __tablename__ = "snippet_identity_links"

    link_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="CASCADE"),
        nullable=False,
    )

    confidence = Column(Float, nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    link_source = Column(String, nullable=False, default="system")
    status = Column(String, nullable=False, default="active")
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_snippet_identity_links_project", project_id),
        Index("ix_snippet_identity_links_snippet", snippet_id),
        Index("ix_snippet_identity_links_identity", identity_id),
    )


class CharacterModel(Base):
    __tablename__ = "character_models"

    character_model_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )

    model_type = Column(String, nullable=False, default="character")  # character, item
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    canonical_prompt = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")

    canonical_snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="SET NULL"),
        nullable=True,
    )
    merged_into_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_character_models_project", project_id),
        Index("ix_character_models_type", model_type),
        Index("ix_character_models_status", status),
        Index("ix_character_models_merged", merged_into_id),
    )


class CharacterModelSnippetLink(Base):
    __tablename__ = "character_model_snippet_links"

    link_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    character_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="CASCADE"),
        nullable=False,
    )
    snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String, nullable=False, default="reference")
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_character_model_snippet_links_model", character_model_id),
        Index("ix_character_model_snippet_links_snippet", snippet_id),
    )


class CharacterModelIdentityLink(Base):
    __tablename__ = "character_model_identity_links"

    link_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    character_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String, nullable=False, default="primary")
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_character_model_identity_links_model", character_model_id),
        Index("ix_character_model_identity_links_identity", identity_id),
    )


class IdentityMergeEvent(Base):
    __tablename__ = "identity_merge_events"

    event_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="CASCADE"),
        nullable=False,
    )
    reason = Column(String, nullable=True)
    actor = Column(String, nullable=False, default="system")
    confidence = Column(Float, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_identity_merge_events_project", project_id),
        Index("ix_identity_merge_events_source", source_identity_id),
        Index("ix_identity_merge_events_target", target_identity_id),
    )


class CharacterModelMergeEvent(Base):
    __tablename__ = "character_model_merge_events"

    event_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="CASCADE"),
        nullable=False,
    )
    reason = Column(String, nullable=True)
    actor = Column(String, nullable=False, default="system")
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_character_model_merge_events_project", project_id),
        Index("ix_character_model_merge_events_source", source_model_id),
        Index("ix_character_model_merge_events_target", target_model_id),
    )


class SnippetMergeSuggestion(Base):
    __tablename__ = "snippet_merge_suggestions"

    suggestion_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity_score = Column(Float, nullable=False)
    decision = Column(String, nullable=False, default="pending")
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_snippet_merge_suggestions_project", project_id),
        Index("ix_snippet_merge_suggestions_snippet", snippet_id),
        Index("ix_snippet_merge_suggestions_identity", candidate_identity_id),
        Index("ix_snippet_merge_suggestions_decision", decision),
    )


class AssetGeneration(Base):
    __tablename__ = "asset_generations"

    generation_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_id = Column(
        UUID,
        ForeignKey("timelines.timeline_id", ondelete="SET NULL"),
        nullable=True,
    )
    request_origin = Column(String, nullable=False, default="user")
    requestor = Column(String, nullable=False, default="system")
    provider = Column(String, nullable=False, default="openrouter")
    model = Column(String, nullable=False)
    mode = Column(String, nullable=False)  # image, insert_frames, replace_frames
    status = Column(String, nullable=False, default="pending")
    prompt = Column(String, nullable=False)
    parameters = Column(JSONB, nullable=False, default=dict)
    reference_asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="SET NULL"),
        nullable=True,
    )
    reference_snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="SET NULL"),
        nullable=True,
    )
    reference_identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="SET NULL"),
        nullable=True,
    )
    reference_character_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="SET NULL"),
        nullable=True,
    )
    target_asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="SET NULL"),
        nullable=True,
    )
    frame_range = Column(JSONB, nullable=True)
    frame_indices = Column(JSONB, nullable=True)
    generated_asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="SET NULL"),
        nullable=True,
    )
    applied_asset_id = Column(
        UUID,
        ForeignKey("assets.asset_id", ondelete="SET NULL"),
        nullable=True,
    )
    request_context = Column(JSONB, nullable=False, default=dict)
    decision_reason = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    decided_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_asset_generations_project", project_id),
        Index("ix_asset_generations_status", status),
        Index("ix_asset_generations_target_asset", target_asset_id),
        Index("ix_asset_generations_created_at", created_at),
    )


class GenerationReferenceAnchor(Base):
    __tablename__ = "generation_reference_anchors"

    anchor_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_id = Column(
        UUID,
        ForeignKey("timelines.timeline_id", ondelete="SET NULL"),
        nullable=True,
    )
    anchor_type = Column(String, nullable=False)  # snippet, identity, character_model
    snippet_id = Column(
        UUID,
        ForeignKey("snippets.snippet_id", ondelete="SET NULL"),
        nullable=True,
    )
    identity_id = Column(
        UUID,
        ForeignKey("snippet_identities.identity_id", ondelete="SET NULL"),
        nullable=True,
    )
    character_model_id = Column(
        UUID,
        ForeignKey("character_models.character_model_id", ondelete="SET NULL"),
        nullable=True,
    )
    request_context = Column(JSONB, nullable=False, default=dict)
    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_generation_reference_anchors_project", project_id),
        Index("ix_generation_reference_anchors_timeline", timeline_id),
        Index("ix_generation_reference_anchors_type", anchor_type),
    )
