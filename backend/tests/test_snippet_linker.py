from types import SimpleNamespace
from uuid import uuid4

from agent.asset_processing import snippet_linker
from database.models import SnippetIdentityLink


class _FakeQuery:
    def __init__(self, first_result):
        self._first_result = first_result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_result


class _FakeSession:
    def __init__(self, query_results=None):
        self._query_results = list(query_results or [])
        self.added = []

    def query(self, *args, **kwargs):
        first_result = self._query_results.pop(0) if self._query_results else None
        return _FakeQuery(first_result)

    def add(self, obj):
        self.added.append(obj)


def _build_snippet(snippet_type: str = "face", embedding: list[float] | None = None):
    return SimpleNamespace(
        snippet_id=uuid4(),
        project_id=uuid4(),
        snippet_type=snippet_type,
        embedding=embedding,
        quality_score=0.99,
        source_ref={"verification": {"label": "face", "confidence": 0.99}},
    )


def _build_identity():
    return SimpleNamespace(
        identity_id=uuid4(),
        canonical_snippet_id=None,
        prototype_embedding=None,
        updated_at=None,
    )


def test_strict_auto_link_skips_person_context_snippets():
    snippet = _build_snippet(snippet_type="person", embedding=[0.1, 0.2, 0.3])

    result = snippet_linker.strict_auto_link_snippet(_FakeSession(), snippet)

    assert result["decision"] == "skipped"
    assert result["reason"] == "snippet_type_not_auto_linked:person"


def test_strict_auto_link_returns_new_identity_for_missing_embedding():
    snippet = _build_snippet(snippet_type="face", embedding=None)

    result = snippet_linker.strict_auto_link_snippet(_FakeSession(), snippet)

    assert result["decision"] == "new_identity"
    assert result["reason"] == "missing_embedding"


def test_strict_auto_link_skips_unverified_face_snippet():
    snippet = _build_snippet(snippet_type="face", embedding=[0.3, 0.2, 0.1])
    snippet.source_ref = {}

    result = snippet_linker.strict_auto_link_snippet(_FakeSession(), snippet)

    assert result["decision"] == "skipped"
    assert result["reason"] == "face_verification_missing"


def test_strict_auto_link_skips_low_quality_face_snippet():
    snippet = _build_snippet(snippet_type="face", embedding=[0.3, 0.2, 0.1])
    snippet.quality_score = 0.5

    result = snippet_linker.strict_auto_link_snippet(_FakeSession(), snippet)

    assert result["decision"] == "skipped"
    assert result["reason"] == "face_quality_below_threshold"


def test_strict_auto_link_auto_attaches_without_metadata_arg_mismatch(monkeypatch):
    identity = _build_identity()
    db = _FakeSession(query_results=[identity, None])
    snippet = _build_snippet(snippet_type="face", embedding=[0.1, 0.2, 0.3])

    monkeypatch.setattr(
        snippet_linker,
        "_find_identity_candidates",
        lambda **kwargs: [
            {"identity_id": identity.identity_id, "similarity": 0.99},
            {"identity_id": uuid4(), "similarity": 0.95},
        ],
    )

    result = snippet_linker.strict_auto_link_snippet(db, snippet)

    assert result["decision"] == "auto_attached"
    assert result["identity_id"] == str(identity.identity_id)
    assert any(isinstance(item, SnippetIdentityLink) for item in db.added)


def test_strict_auto_link_new_identity_path_attaches_link(monkeypatch):
    identity = _build_identity()
    db = _FakeSession(query_results=[None])
    snippet = _build_snippet(snippet_type="face", embedding=[0.3, 0.2, 0.1])

    monkeypatch.setattr(snippet_linker, "_find_identity_candidates", lambda **kwargs: [])
    monkeypatch.setattr(
        snippet_linker,
        "_create_identity_for_snippet",
        lambda _db, _snippet: identity,
    )

    result = snippet_linker.strict_auto_link_snippet(db, snippet)

    assert result["decision"] == "new_identity"
    assert result["identity_id"] == str(identity.identity_id)
    assert any(isinstance(item, SnippetIdentityLink) for item in db.added)
    assert identity.prototype_embedding == snippet.embedding
