from agent.asset_processing import analyzers


class _PayloadTooLargeError(Exception):
    status_code = 413


class _FakeCompletions:
    @staticmethod
    def create(*args, **kwargs):
        raise _PayloadTooLargeError("413 Payload Too Large")


class _FakeChat:
    completions = _FakeCompletions()


class _FakeClient:
    chat = _FakeChat()


def test_build_media_part_prefers_source_url_for_large_content(monkeypatch):
    monkeypatch.setattr(analyzers, "MAX_INLINE_MEDIA_BYTES", 5)

    part = analyzers._build_media_part(
        media_field="video_url",
        content=b"0123456789",
        content_type="video/mp4",
        source_url="https://example.com/signed.mp4",
    )

    assert part is not None
    assert part["type"] == "video_url"
    assert part["video_url"]["url"] == "https://example.com/signed.mp4"


def test_build_media_part_rejects_large_inline_without_url(monkeypatch):
    monkeypatch.setattr(analyzers, "MAX_INLINE_MEDIA_BYTES", 5)

    part = analyzers._build_media_part(
        media_field="video_url",
        content=b"0123456789",
        content_type="video/mp4",
        source_url=None,
    )

    assert part is None


def test_analyze_video_falls_back_on_413(monkeypatch):
    monkeypatch.setattr(analyzers, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        analyzers,
        "_build_media_part",
        lambda media_field, content, content_type, source_url: {
            "type": media_field,
            media_field: {"url": "https://example.com/video.mp4"},
        },
    )
    monkeypatch.setattr(
        analyzers,
        "_fallback_video_metadata",
        lambda content, content_type: {"summary": "fallback", "technical": {}},
    )

    result = analyzers.analyze_video(b"video-bytes", "video/mp4")

    assert result["summary"] == "fallback"
