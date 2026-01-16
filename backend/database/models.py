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
    scopes = Column(ARRAY(String), nullable=False, default=[])
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
