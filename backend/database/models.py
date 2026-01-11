from uuid import uuid4
from sqlalchemy import Column, Integer, String, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
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

    asset_transcript = Column(JSONB, nullable=True)
    asset_metadata = Column(JSONB, nullable=False)
    asset_events = Column(JSONB, nullable=True)
    notable_shots = Column(
        JSONB, nullable=True
    )  # timestamps of notable shots worthy of further review
    audio_features = Column(JSONB, nullable=True)
    asset_faces = Column(JSONB, nullable=True)
    asset_summary = Column(String, nullable=False)
    asset_tags = Column(JSONB, nullable=True)

    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    __table_args__ = (
        Index(
            "ix_assets_embedding",
            embedding,
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self):
        return f"<Assets asset_id={self.asset_id} asset_name={self.asset_name} asset_type={self.asset_type} asset_url={self.asset_url} uploaded_at={self.uploaded_at} project_id={self.project_id} asset_transcript={self.asset_transcript} asset_metadata={self.asset_metadata} asset_events={self.asset_events} notable_shots={self.notable_shots} audio_features={self.audio_features} asset_faces={self.asset_faces} asset_summary={self.asset_summary} asset_tags={self.asset_tags} embedding={self.embedding}>"


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
