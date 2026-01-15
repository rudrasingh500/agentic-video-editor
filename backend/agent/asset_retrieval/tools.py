from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from database.models import Assets
from utils.embeddings import get_query_embedding

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_assets_summaries",
            "description": (
                "Get summaries of all assets in the project. "
                "CALL THIS FIRST to understand what content is available before searching. "
                "Returns asset IDs, names, types, summaries, and tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "enum": ["video", "audio", "image"],
                        "description": "Filter by media type (video, audio, or image)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_details",
            "description": (
                "Get full metadata for a specific asset including transcript, "
                "events, faces, objects, scenes, and technical details. "
                "Use this to drill into a specific asset after reviewing summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "UUID of the asset to retrieve",
                    },
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_tags",
            "description": (
                "Find assets that match specific tags. "
                "Use this to filter assets by content type, mood, style, or subject matter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tags to search for",
                    },
                    "match_all": {
                        "type": "boolean",
                        "description": (
                            "If true, assets must have ALL specified tags. "
                            "If false, assets with ANY of the tags will match. (default: false)"
                        ),
                    },
                },
                "required": ["tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_transcript",
            "description": (
                "Full-text search within transcripts to find spoken content. "
                "Returns matching segments with timestamps. "
                "Use this to find specific words, phrases, or topics discussed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for transcript content",
                    },
                    "speaker_id": {
                        "type": "string",
                        "description": "Optional: filter to segments from a specific speaker",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_faces_speakers",
            "description": (
                "Find assets containing specific faces or speakers. "
                "Returns timestamps where each person appears or speaks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "face_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of face IDs to search for",
                    },
                    "speaker_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of speaker IDs to search for",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_events_scenes",
            "description": (
                "Search for specific events or scenes within assets. "
                "Events include key moments, transitions, actions. "
                "Scenes are continuous segments with consistent setting/mood."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "description": (
                            "Type of event to search for "
                            "(e.g., 'transition', 'highlight', 'action', 'speech')"
                        ),
                    },
                    "description_query": {
                        "type": "string",
                        "description": "Text to search for in event/scene descriptions",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_objects",
            "description": (
                "Find assets containing specific objects or visual elements. "
                "Returns timestamps and positions where objects appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of object names to search for (e.g., 'car', 'phone', 'laptop')",
                    },
                    "prominence": {
                        "type": "string",
                        "enum": ["primary", "secondary", "background"],
                        "description": "Filter by object prominence in the frame",
                    },
                },
                "required": ["object_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": (
                "Search assets using natural language semantic similarity. "
                "Finds assets conceptually related to your query, even without exact keyword matches. "
                "Best for conceptual queries like 'energetic footage', 'calm nature scenes', "
                "'professional interview setup', or 'upbeat music'. "
                "Returns assets ranked by semantic similarity to your description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what you're looking for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10)",
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum similarity score between 0 and 1 (default 0.5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    project_id: str,
    db: Session,
) -> dict[str, Any]:
    tool_map = {
        "list_assets_summaries": _list_assets_summaries,
        "get_asset_details": _get_asset_details,
        "search_by_tags": _search_by_tags,
        "search_transcript": _search_transcript,
        "search_faces_speakers": _search_faces_speakers,
        "search_events_scenes": _search_events_scenes,
        "search_objects": _search_objects,
        "semantic_search": _semantic_search,
    }

    tool_fn = tool_map.get(tool_name)
    if not tool_fn:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return tool_fn(project_id=project_id, db=db, **arguments)
    except Exception as e:
        return {"error": str(e)}


def _list_assets_summaries(
    project_id: str,
    db: Session,
    asset_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_summary,
        Assets.asset_tags,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    if asset_type:
        type_prefix = f"{asset_type}/"
        query = query.filter(Assets.asset_type.startswith(type_prefix))
    query = query.limit(limit)
    results = query.all()
    return {
        "count": len(results),
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "tags": row.asset_tags or [],
            }
            for row in results
        ],
    }


def _get_asset_details(
    project_id: str,
    db: Session,
    asset_id: str,
) -> dict[str, Any]:
    asset = (
        db.query(Assets)
        .filter(
            Assets.asset_id == asset_id,
            Assets.project_id == project_id,
            Assets.indexing_status == "completed",
        )
        .first()
    )
    if not asset:
        return {"error": f"Asset not found: {asset_id}"}
    return {
        "asset_id": str(asset.asset_id),
        "name": asset.asset_name,
        "type": asset.asset_type,
        "summary": asset.asset_summary,
        "tags": asset.asset_tags or [],
        "transcript": asset.asset_transcript,
        "events": asset.asset_events,
        "notable_shots": asset.notable_shots,
        "scenes": asset.asset_scenes,
        "faces": asset.asset_faces,
        "speakers": asset.asset_speakers,
        "objects": asset.asset_objects,
        "audio_features": asset.audio_features,
        "audio_structure": asset.audio_structure,
        "colors": asset.asset_colors,
        "technical": asset.asset_technical,
    }


def _search_by_tags(
    project_id: str,
    db: Session,
    tags: list[str],
    match_all: bool = False,
) -> dict[str, Any]:
    if not tags:
        return {"error": "No tags provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_summary,
        Assets.asset_tags,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    if match_all:
        query = query.filter(Assets.asset_tags.op("?&")(tags))
    else:
        query = query.filter(Assets.asset_tags.op("?|")(tags))
    results = query.all()
    return {
        "count": len(results),
        "query_tags": tags,
        "match_mode": "all" if match_all else "any",
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "matched_tags": [t for t in (row.asset_tags or []) if t in tags],
            }
            for row in results
        ],
    }


def _search_transcript(
    project_id: str,
    db: Session,
    query: str,
    speaker_id: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        return {"error": "Empty search query", "assets": []}
    ts_query = func.plainto_tsquery("english", query)
    db_query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_transcript,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
        Assets.transcript_tsv.op("@@")(ts_query),
    )
    results = db_query.all()
    output_assets = []
    for row in results:
        transcript = row.asset_transcript or {}
        segments = transcript.get("segments", [])
        if speaker_id:
            segments = [s for s in segments if s.get("speaker") == speaker_id]
        query_lower = query.lower()
        matching_segments = []
        for seg in segments:
            seg_text = seg.get("text", "")
            if query_lower in seg_text.lower():
                matching_segments.append(
                    {
                        "t0": seg.get("timestamp_ms", seg.get("start_ms", 0)),
                        "t1": seg.get("end_ms", seg.get("timestamp_ms", 0) + 5000),
                        "text": seg_text,
                        "speaker": seg.get("speaker"),
                    }
                )
        if matching_segments:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "segments": matching_segments,
                }
            )
    return {
        "count": len(output_assets),
        "query": query,
        "speaker_filter": speaker_id,
        "assets": output_assets,
    }


def _search_faces_speakers(
    project_id: str,
    db: Session,
    face_ids: list[str] | None = None,
    speaker_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not face_ids and not speaker_ids:
        return {"error": "No face_ids or speaker_ids provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_faces,
        Assets.asset_speakers,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    output_assets = []
    for row in results:
        faces = row.asset_faces or []
        speakers = row.asset_speakers or []
        matched_faces = []
        matched_speakers = []
        if face_ids:
            for face in faces:
                if face.get("id") in face_ids:
                    matched_faces.append(
                        {
                            "id": face.get("id"),
                            "description": face.get("description"),
                            "appears_at_ms": face.get("appears_at_ms", []),
                            "screen_time_percentage": face.get(
                                "screen_time_percentage"
                            ),
                        }
                    )
        if speaker_ids:
            for speaker in speakers:
                if speaker.get("id") in speaker_ids:
                    matched_speakers.append(
                        {
                            "id": speaker.get("id"),
                            "description": speaker.get("description"),
                            "role": speaker.get("role"),
                            "speaking_time_percentage": speaker.get(
                                "speaking_time_percentage"
                            ),
                        }
                    )
        if matched_faces or matched_speakers:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_faces": matched_faces,
                    "matched_speakers": matched_speakers,
                }
            )
    return {
        "count": len(output_assets),
        "query_face_ids": face_ids or [],
        "query_speaker_ids": speaker_ids or [],
        "assets": output_assets,
    }


def _search_events_scenes(
    project_id: str,
    db: Session,
    event_type: str | None = None,
    description_query: str | None = None,
) -> dict[str, Any]:
    if not event_type and not description_query:
        return {"error": "No event_type or description_query provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_events,
        Assets.asset_scenes,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    output_assets = []
    desc_lower = description_query.lower() if description_query else None
    for row in results:
        events = row.asset_events or []
        scenes = row.asset_scenes or []
        matched_events = []
        matched_scenes = []
        for event in events:
            matches = True
            if event_type and event.get("event_type") != event_type:
                matches = False
            if desc_lower and desc_lower not in event.get("description", "").lower():
                matches = False
            if matches:
                matched_events.append(
                    {
                        "t0": event.get("timestamp_ms", 0),
                        "t1": event.get("timestamp_ms", 0) + 3000,
                        "type": event.get("event_type"),
                        "description": event.get("description"),
                        "importance": event.get("importance"),
                    }
                )
        for scene in scenes:
            matches = True
            if desc_lower:
                scene_desc = (
                    scene.get("description", "") + " " + scene.get("key_content", "")
                )
                if desc_lower not in scene_desc.lower():
                    matches = False
            if matches and (not event_type or desc_lower):
                matched_scenes.append(
                    {
                        "t0": scene.get("start_ms", 0),
                        "t1": scene.get("end_ms", 0),
                        "description": scene.get("description"),
                        "location": scene.get("location"),
                        "mood": scene.get("mood"),
                    }
                )
        if matched_events or matched_scenes:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_events": matched_events,
                    "matched_scenes": matched_scenes,
                }
            )
    return {
        "count": len(output_assets),
        "query_event_type": event_type,
        "query_description": description_query,
        "assets": output_assets,
    }


def _search_objects(
    project_id: str,
    db: Session,
    object_names: list[str],
    prominence: str | None = None,
) -> dict[str, Any]:
    if not object_names:
        return {"error": "No object_names provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_objects,
        Assets.notable_shots,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    search_names = [n.lower() for n in object_names]
    output_assets = []
    for row in results:
        objects = row.asset_objects or []
        notable_shots = row.notable_shots or []
        matched_objects = []
        for obj in objects:
            obj_name = obj.get("name", "").lower()
            if any(search_name in obj_name for search_name in search_names):
                if prominence and obj.get("prominence") != prominence:
                    continue
                matched_objects.append(
                    {
                        "name": obj.get("name"),
                        "description": obj.get("description"),
                        "position": obj.get("position"),
                        "prominence": obj.get("prominence"),
                        "brand": obj.get("brand"),
                    }
                )
        object_timestamps = []
        for shot in notable_shots:
            shot_desc = shot.get("description", "").lower()
            if any(search_name in shot_desc for search_name in search_names):
                object_timestamps.append(
                    {
                        "t0": shot.get("timestamp_ms", 0),
                        "description": shot.get("description"),
                    }
                )
        if matched_objects or object_timestamps:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_objects": matched_objects,
                    "object_timestamps": object_timestamps,
                }
            )
    return {
        "count": len(output_assets),
        "query_objects": object_names,
        "prominence_filter": prominence,
        "assets": output_assets,
    }


def _semantic_search(
    project_id: str,
    db: Session,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.5,
) -> dict[str, Any]:
    """
    Vector similarity search using pgvector.

    Finds assets semantically similar to the query by comparing
    embedding vectors using cosine distance.
    """
    if not query.strip():
        return {"error": "Empty search query", "assets": []}

    # Generate embedding for the query
    query_embedding = get_query_embedding(query)
    if not query_embedding:
        return {
            "error": "Failed to generate query embedding",
            "assets": [],
        }

    # Perform vector similarity search using pgvector's <=> operator (cosine distance)
    # Cosine distance = 1 - cosine_similarity, so we compute similarity as 1 - distance
    results = db.execute(
        text("""
            SELECT
                asset_id,
                asset_name,
                asset_type,
                asset_summary,
                asset_tags,
                1 - (embedding <=> :query_vector) AS similarity
            FROM assets
            WHERE project_id = :project_id
              AND indexing_status = 'completed'
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :query_vector) >= :min_similarity
            ORDER BY embedding <=> :query_vector
            LIMIT :limit
        """),
        {
            "query_vector": str(query_embedding),
            "project_id": project_id,
            "min_similarity": min_similarity,
            "limit": limit,
        },
    ).fetchall()

    return {
        "count": len(results),
        "query": query,
        "min_similarity": min_similarity,
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "tags": row.asset_tags or [],
                "similarity": round(row.similarity, 4),
            }
            for row in results
        ],
    }
