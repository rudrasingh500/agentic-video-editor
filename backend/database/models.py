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

EMBEDDING_DIMENSIONS = 1536  # OpenAI ada-002 / text-embedding-3-small


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

    # Core metadata fields
    asset_summary = Column(String, nullable=False)
    asset_tags = Column(JSONB, nullable=True)  # Array of searchable tags

    # Transcript - structured format with text, segments, speakers
    asset_transcript = Column(JSONB, nullable=True)

    # Timeline-based data
    asset_events = Column(JSONB, nullable=True)  # Key moments with timestamps
    notable_shots = Column(JSONB, nullable=True)  # Visually interesting frames
    asset_scenes = Column(JSONB, nullable=True)  # Video scene segmentation

    # Audio analysis
    audio_features = Column(JSONB, nullable=True)  # BPM, key, energy, etc.
    audio_structure = Column(JSONB, nullable=True)  # Intro, verse, chorus timestamps

    # Visual analysis
    asset_faces = Column(JSONB, nullable=True)  # Detected people/faces
    asset_objects = Column(JSONB, nullable=True)  # Detected objects with positions
    asset_colors = Column(JSONB, nullable=True)  # Color palette analysis

    # Technical metadata
    asset_technical = Column(JSONB, nullable=True)  # Resolution, quality, etc.

    # Speakers (for audio/video with speech)
    asset_speakers = Column(JSONB, nullable=True)  # Speaker identification and info

    # Indexing status tracking
    indexing_status = Column(
        String, nullable=False, default="pending"
    )  # pending, processing, completed, failed
    indexing_error = Column(String, nullable=True)  # Error message if failed
    indexing_started_at = Column(DateTime, nullable=True)  # When processing began
    indexing_completed_at = Column(DateTime, nullable=True)  # When processing finished
    indexing_attempts = Column(Integer, nullable=False, default=0)  # Retry count

    # Vector embedding for semantic search
    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    # Full-text search vector for transcripts (auto-generated)
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


# =============================================================================
# TIMELINE MODELS (OTIO-inspired)
# =============================================================================


class Timeline(Base):
    """
    Timeline container - one per project.

    Stores the timeline metadata and current version pointer.
    The actual timeline content is stored in TimelineCheckpoint snapshots.
    """

    __tablename__ = "timelines"

    timeline_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    project_id = Column(
        UUID,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One timeline per project
    )
    name = Column(String, nullable=False)
    global_start_time = Column(JSONB, nullable=True)  # RationalTime JSON
    settings = Column(JSONB, nullable=False, default=dict)  # TimelineSettings JSON
    timeline_metadata = Column(
        JSONB, nullable=False, default=dict
    )  # Renamed from 'metadata' (reserved)
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
    """
    Versioned timeline snapshot.

    Each checkpoint stores a complete OTIO-compatible timeline snapshot.
    This enables:
    - Full history of all changes
    - Rollback to any previous version
    - Diffing between versions
    - Branching (via parent_version)
    """

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
    parent_version = Column(
        Integer, nullable=True
    )  # For tracking rollbacks and branches
    snapshot = Column(JSONB, nullable=False)  # Complete Timeline Pydantic model as JSON
    description = Column(String, nullable=False)  # Human-readable change description
    created_by = Column(
        String, nullable=False
    )  # "user:<uuid>", "agent:<name>", "system"
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # Approval workflow (for agent integration)
    is_approved = Column(Boolean, nullable=False, default=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Unique constraint: one version number per timeline
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
    """
    Audit log of operations performed on timelines.

    Each checkpoint has one associated operation record that captures:
    - What type of operation was performed
    - The full parameters of the operation
    - When it was performed

    This is useful for:
    - Debugging and auditing
    - Understanding change patterns
    - Potential undo/redo optimization in the future
    """

    __tablename__ = "timeline_operations"

    operation_id = Column(
        UUID, unique=True, index=True, nullable=False, primary_key=True, default=uuid4
    )
    checkpoint_id = Column(
        UUID,
        ForeignKey("timeline_checkpoints.checkpoint_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_type = Column(
        String, nullable=False
    )  # add_clip, remove_clip, trim_clip, etc.
    operation_data = Column(JSONB, nullable=False)  # Full operation parameters
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


# =============================================================================
# RENDER JOB MODELS
# =============================================================================


class RenderJob(Base):
    """
    Render job tracking.

    Tracks the status and progress of video rendering jobs executed
    via Cloud Run Jobs. Each job renders a specific timeline version
    to a video file stored in GCS.
    """

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

    # Job type and status
    job_type = Column(
        String, nullable=False
    )  # "preview" or "export"
    status = Column(
        String, nullable=False, default="pending"
    )  # pending, queued, processing, uploading, completed, failed, cancelled

    # Progress tracking
    progress = Column(Integer, nullable=False, default=0)  # 0-100
    current_frame = Column(Integer, nullable=True)
    total_frames = Column(Integer, nullable=True)

    # Render settings (stored as JSON)
    preset = Column(JSONB, nullable=False)  # RenderPreset JSON

    # Output details
    output_filename = Column(String, nullable=True)
    output_url = Column(String, nullable=True)  # GCS path to rendered video
    output_size_bytes = Column(Integer, nullable=True)

    # Error handling
    error_message = Column(String, nullable=True)
    error_details = Column(JSONB, nullable=True)

    # Cloud Run integration
    cloud_run_job_name = Column(String, nullable=True)  # Cloud Run Job name
    cloud_run_execution_id = Column(String, nullable=True)  # Execution ID

    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Additional metadata
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
