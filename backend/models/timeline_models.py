from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field


class TrackKind(str, Enum):
    VIDEO = "Video"
    AUDIO = "Audio"


class MarkerColor(str, Enum):
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    CYAN = "CYAN"
    BLUE = "BLUE"
    PURPLE = "PURPLE"
    MAGENTA = "MAGENTA"
    WHITE = "WHITE"
    BLACK = "BLACK"


class TransitionType(str, Enum):
    SMPTE_DISSOLVE = "SMPTE_Dissolve"
    CUSTOM = "Custom"
    CUSTOM_XFADE = "custom"
    FADE_IN = "FadeIn"
    FADE_OUT = "FadeOut"
    WIPE = "Wipe"
    SLIDE = "Slide"
    FADE = "fade"
    WIPELEFT = "wipeleft"
    WIPERIGHT = "wiperight"
    WIPEUP = "wipeup"
    WIPEDOWN = "wipedown"
    SLIDELEFT = "slideleft"
    SLIDERIGHT = "slideright"
    SLIDEUP = "slideup"
    SLIDEDOWN = "slidedown"
    CIRCLECROP = "circlecrop"
    RECTCROP = "rectcrop"
    DISTANCE = "distance"
    FADEBLACK = "fadeblack"
    FADEWHITE = "fadewhite"
    RADIAL = "radial"
    SMOOTHLEFT = "smoothleft"
    SMOOTHRIGHT = "smoothright"
    SMOOTHUP = "smoothup"
    SMOOTHDOWN = "smoothdown"
    CIRCLEOPEN = "circleopen"
    CIRCLECLOSE = "circleclose"
    VERTOPEN = "vertopen"
    VERTCLOSE = "vertclose"
    HORZOPEN = "horzopen"
    HORZCLOSE = "horzclose"
    DISSOLVE = "dissolve"
    PIXELIZE = "pixelize"
    DIAGTL = "diagtl"
    DIAGTR = "diagtr"
    DIAGBL = "diagbl"
    DIAGBR = "diagbr"
    HLSLICE = "hlslice"
    HRSLICE = "hrslice"
    VUSLICE = "vuslice"
    VDSLICE = "vdslice"
    HBLUR = "hblur"
    FADEGRAYS = "fadegrays"
    WIPETL = "wipetl"
    WIPETR = "wipetr"
    WIPEBL = "wipebl"
    WIPEBR = "wipebr"
    SQUEEZEH = "squeezeh"
    SQUEEZEV = "squeezev"
    ZOOMIN = "zoomin"
    FADEFAST = "fadefast"
    FADESLOW = "fadeslow"
    HLWIND = "hlwind"
    HRWIND = "hrwind"
    VUWIND = "vuwind"
    VDWIND = "vdwind"
    COVERLEFT = "coverleft"
    COVERRIGHT = "coverright"
    COVERUP = "coverup"
    COVERDOWN = "coverdown"
    REVEALLEFT = "revealleft"
    REVEALRIGHT = "revealright"
    REVEALUP = "revealup"
    REVEALDOWN = "revealdown"


class RationalTime(BaseModel):
    OTIO_SCHEMA: Literal["RationalTime.1"] = "RationalTime.1"
    value: float = Field(description="Time value (typically frame number)")
    rate: float = Field(default=24.0, gt=0, description="Rate (frames per second)")

    def to_seconds(self) -> float:
        return self.value / self.rate

    def to_frames(self, target_rate: float | None = None) -> float:
        if target_rate is None:
            return self.value
        return self.value * target_rate / self.rate

    def to_milliseconds(self) -> float:
        return (self.value / self.rate) * 1000

    def rescaled_to(self, new_rate: float) -> RationalTime:
        return RationalTime(value=self.value * new_rate / self.rate, rate=new_rate)

    def __add__(self, other: RationalTime) -> RationalTime:
        if self.rate == other.rate:
            return RationalTime(value=self.value + other.value, rate=self.rate)

        other_rescaled = other.rescaled_to(self.rate)
        return RationalTime(value=self.value + other_rescaled.value, rate=self.rate)

    def __sub__(self, other: RationalTime) -> RationalTime:
        if self.rate == other.rate:
            return RationalTime(value=self.value - other.value, rate=self.rate)
        other_rescaled = other.rescaled_to(self.rate)
        return RationalTime(value=self.value - other_rescaled.value, rate=self.rate)

    def __mul__(self, scalar: float) -> RationalTime:
        return RationalTime(value=self.value * scalar, rate=self.rate)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return False
        return abs(self.to_seconds() - other.to_seconds()) < 1e-9

    def __lt__(self, other: RationalTime) -> bool:
        return self.to_seconds() < other.to_seconds()

    def __le__(self, other: RationalTime) -> bool:
        return self.to_seconds() <= other.to_seconds()

    def __gt__(self, other: RationalTime) -> bool:
        return self.to_seconds() > other.to_seconds()

    def __ge__(self, other: RationalTime) -> bool:
        return self.to_seconds() >= other.to_seconds()

    @classmethod
    def from_seconds(cls, seconds: float, rate: float = 24.0) -> RationalTime:
        return cls(value=seconds * rate, rate=rate)

    @classmethod
    def from_milliseconds(cls, ms: float, rate: float = 24.0) -> RationalTime:
        return cls(value=(ms / 1000) * rate, rate=rate)

    @classmethod
    def from_frames(cls, frames: float, rate: float = 24.0) -> RationalTime:
        return cls(value=frames, rate=rate)


class TimeRange(BaseModel):
    OTIO_SCHEMA: Literal["TimeRange.1"] = "TimeRange.1"
    start_time: RationalTime = Field(description="Start of the range")
    duration: RationalTime = Field(description="Duration of the range")

    @property
    def end_time_exclusive(self) -> RationalTime:
        return self.start_time + self.duration

    @property
    def end_time_inclusive(self) -> RationalTime:
        return RationalTime(
            value=self.start_time.value + self.duration.value - 1,
            rate=self.start_time.rate,
        )

    def contains(self, time: RationalTime) -> bool:
        return self.start_time <= time < self.end_time_exclusive

    def overlaps(self, other: TimeRange) -> bool:
        return (
            self.start_time < other.end_time_exclusive
            and other.start_time < self.end_time_exclusive
        )

    def contains_range(self, other: TimeRange) -> bool:
        return (
            self.start_time <= other.start_time
            and self.end_time_exclusive >= other.end_time_exclusive
        )

    def extended_by(self, other: TimeRange) -> TimeRange:
        new_start = min(self.start_time, other.start_time)
        new_end = max(self.end_time_exclusive, other.end_time_exclusive)
        return TimeRange(start_time=new_start, duration=new_end - new_start)

    def clamped_to(self, other: TimeRange) -> TimeRange | None:
        if not self.overlaps(other):
            return None
        new_start = max(self.start_time, other.start_time)
        new_end = min(self.end_time_exclusive, other.end_time_exclusive)
        return TimeRange(start_time=new_start, duration=new_end - new_start)

    def to_milliseconds(self) -> tuple[float, float]:
        return (self.start_time.to_milliseconds(), self.duration.to_milliseconds())

    @classmethod
    def from_start_end(cls, start: RationalTime, end: RationalTime) -> TimeRange:
        return cls(start_time=start, duration=end - start)

    @classmethod
    def from_milliseconds(
        cls, start_ms: float, duration_ms: float, rate: float = 24.0
    ) -> TimeRange:
        return cls(
            start_time=RationalTime.from_milliseconds(start_ms, rate),
            duration=RationalTime.from_milliseconds(duration_ms, rate),
        )


class ExternalReference(BaseModel):
    OTIO_SCHEMA: Literal["ExternalReference.1"] = "ExternalReference.1"
    asset_id: UUID = Field(description="Reference to assets table")
    available_range: TimeRange | None = Field(
        default=None, description="Full range of media available in the asset"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratorReference(BaseModel):
    OTIO_SCHEMA: Literal["GeneratorReference.1"] = "GeneratorReference.1"
    generator_kind: str = Field(
        description="Type of generator: SolidColor, Bars, Tone, Slug, etc."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Generator parameters, e.g., {'color': '#000000'}",
    )
    available_range: TimeRange | None = Field(
        default=None, description="Available range (often unlimited for generators)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissingReference(BaseModel):
    OTIO_SCHEMA: Literal["MissingReference.1"] = "MissingReference.1"
    name: str = Field(default="", description="Name of missing media")
    available_range: TimeRange | None = Field(
        default=None, description="Expected range if known"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


MediaReference = Annotated[
    Union[ExternalReference, GeneratorReference, MissingReference],
    Field(discriminator="OTIO_SCHEMA"),
]


class Effect(BaseModel):
    OTIO_SCHEMA: Literal["Effect.1"] = "Effect.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(description="Effect identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinearTimeWarp(BaseModel):
    OTIO_SCHEMA: Literal["LinearTimeWarp.1"] = "LinearTimeWarp.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(default="LinearTimeWarp")
    time_scalar: float = Field(
        default=1.0, description="Speed multiplier (1.0 = normal, 2.0 = 2x speed)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class FreezeFrame(BaseModel):
    OTIO_SCHEMA: Literal["FreezeFrame.1"] = "FreezeFrame.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(default="FreezeFrame")
    metadata: dict[str, Any] = Field(default_factory=dict)


EffectType = Annotated[
    Union[Effect, LinearTimeWarp, FreezeFrame], Field(discriminator="OTIO_SCHEMA")
]


class Marker(BaseModel):
    OTIO_SCHEMA: Literal["Marker.1"] = "Marker.1"
    name: str = Field(default="", description="Marker label")
    marked_range: TimeRange = Field(description="Range this marker covers")
    color: MarkerColor = Field(
        default=MarkerColor.RED, description="Visual color for the marker"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class Clip(BaseModel):
    OTIO_SCHEMA: Literal["Clip.1"] = "Clip.1"
    name: str = Field(default="", description="Clip name")
    source_range: TimeRange = Field(
        description="Portion of source media to use (in/out points)"
    )
    media_reference: MediaReference = Field(description="Reference to the source media")
    effects: list[EffectType] = Field(
        default_factory=list, description="Effects applied to this clip"
    )
    markers: list[Marker] = Field(
        default_factory=list, description="Markers on this clip"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        return self.source_range.duration


class Gap(BaseModel):
    OTIO_SCHEMA: Literal["Gap.1"] = "Gap.1"
    name: str = Field(default="", description="Gap name")
    source_range: TimeRange = Field(description="Duration of the gap")
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        return self.source_range.duration

    @classmethod
    def with_duration(cls, duration: RationalTime, name: str = "") -> Gap:
        return cls(
            name=name,
            source_range=TimeRange(
                start_time=RationalTime(value=0, rate=duration.rate), duration=duration
            ),
        )


class Transition(BaseModel):
    OTIO_SCHEMA: Literal["Transition.1"] = "Transition.1"
    name: str = Field(default="", description="Transition name")
    transition_type: TransitionType = Field(
        default=TransitionType.SMPTE_DISSOLVE, description="Type of transition effect"
    )
    in_offset: RationalTime = Field(description="Duration into outgoing clip")
    out_offset: RationalTime = Field(description="Duration from incoming clip")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        return self.in_offset + self.out_offset

    @classmethod
    def dissolve(cls, duration_frames: float = 24, rate: float = 24.0) -> Transition:
        half = RationalTime(value=duration_frames / 2, rate=rate)
        return cls(
            name="Dissolve",
            transition_type=TransitionType.SMPTE_DISSOLVE,
            in_offset=half,
            out_offset=half,
        )


class Stack(BaseModel):
    OTIO_SCHEMA: Literal["Stack.1"] = "Stack.1"
    name: str = Field(default="", description="Stack name")
    source_range: TimeRange | None = Field(
        default=None, description="Optional trim of the stack"
    )
    children: list[Track | Stack] = Field(
        default_factory=list, description="Child tracks or nested stacks"
    )
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def duration(self) -> RationalTime:
        if not self.children:
            return RationalTime(value=0, rate=24.0)

        max_duration = RationalTime(value=0, rate=24.0)
        for child in self.children:
            child_dur = child.duration()
            if child_dur > max_duration:
                max_duration = child_dur

        if self.source_range:
            return self.source_range.duration
        return max_duration

    def trimmed_range(self) -> TimeRange:
        dur = self.duration()
        if self.source_range:
            return self.source_range
        return TimeRange(start_time=RationalTime(value=0, rate=dur.rate), duration=dur)


TrackItem = Annotated[
    Union[Clip, Gap, Transition, Stack], Field(discriminator="OTIO_SCHEMA")
]


class Track(BaseModel):
    OTIO_SCHEMA: Literal["Track.1"] = "Track.1"
    name: str = Field(default="", description="Track name")
    kind: TrackKind = Field(
        default=TrackKind.VIDEO, description="Track type (Video or Audio)"
    )
    source_range: TimeRange | None = Field(
        default=None, description="Optional trim of the track"
    )
    children: list[TrackItem] = Field(
        default_factory=list, description="Clips, gaps, transitions, or nested stacks"
    )
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def duration(self) -> RationalTime:
        if not self.children:
            return RationalTime(value=0, rate=24.0)

        total = RationalTime(value=0, rate=24.0)
        for child in self.children:
            if isinstance(child, Transition):
                continue
            if hasattr(child, "duration"):
                child_dur = (
                    child.duration() if callable(child.duration) else child.duration
                )
                total = total + child_dur

        if self.source_range:
            return self.source_range.duration
        return total

    def trimmed_range(self) -> TimeRange:
        dur = self.duration()
        if self.source_range:
            return self.source_range
        return TimeRange(start_time=RationalTime(value=0, rate=dur.rate), duration=dur)

    def range_of_child(self, index: int) -> TimeRange | None:
        if index < 0 or index >= len(self.children):
            return None

        start = RationalTime(value=0, rate=24.0)
        for i, child in enumerate(self.children):
            if i == index:
                if isinstance(child, Transition):
                    return None
                dur = (
                    child.duration()
                    if callable(getattr(child, "duration", None))
                    else child.duration
                )
                return TimeRange(start_time=start, duration=dur)

            if not isinstance(child, Transition):
                dur = (
                    child.duration()
                    if callable(getattr(child, "duration", None))
                    else child.duration
                )
                start = start + dur

        return None

    def child_at_time(self, time: RationalTime) -> tuple[int, TrackItem] | None:
        current_time = RationalTime(value=0, rate=time.rate)

        for i, child in enumerate(self.children):
            if isinstance(child, Transition):
                continue

            dur = (
                child.duration()
                if callable(getattr(child, "duration", None))
                else child.duration
            )
            end_time = current_time + dur

            if current_time <= time < end_time:
                return (i, child)

            current_time = end_time

        return None


Stack.model_rebuild()


class Timeline(BaseModel):
    OTIO_SCHEMA: Literal["Timeline.1"] = "Timeline.1"
    name: str = Field(description="Timeline name")
    global_start_time: RationalTime | None = Field(
        default=None, description="Timeline start time (e.g., 01:00:00:00)"
    )
    tracks: Stack = Field(
        default_factory=lambda: Stack(name="tracks"),
        description="Root stack containing all tracks",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        return self.tracks.duration()

    @property
    def video_tracks(self) -> list[Track]:
        return [
            t
            for t in self.tracks.children
            if isinstance(t, Track) and t.kind == TrackKind.VIDEO
        ]

    @property
    def audio_tracks(self) -> list[Track]:
        return [
            t
            for t in self.tracks.children
            if isinstance(t, Track) and t.kind == TrackKind.AUDIO
        ]

    def find_clips(self) -> list[Clip]:
        clips: list[Clip] = []
        self._find_clips_recursive(self.tracks, clips)
        return clips

    def _find_clips_recursive(
        self, item: Stack | Track | TrackItem, clips: list[Clip]
    ) -> None:
        if isinstance(item, Clip):
            clips.append(item)
        elif isinstance(item, (Stack, Track)):
            for child in item.children:
                self._find_clips_recursive(child, clips)

    def find_gaps(self) -> list[Gap]:
        gaps: list[Gap] = []
        self._find_items_recursive(self.tracks, Gap, gaps)
        return gaps

    def find_transitions(self) -> list[Transition]:
        transitions: list[Transition] = []
        self._find_items_recursive(self.tracks, Transition, transitions)
        return transitions

    def _find_items_recursive(
        self, item: Stack | Track | TrackItem, item_type: type, results: list
    ) -> None:
        if isinstance(item, item_type):
            results.append(item)
        elif isinstance(item, (Stack, Track)):
            for child in item.children:
                self._find_items_recursive(child, item_type, results)

    @classmethod
    def create_empty(
        cls,
        name: str,
        rate: float = 24.0,
        global_start_time: RationalTime | None = None,
    ) -> Timeline:
        return cls(
            name=name,
            global_start_time=global_start_time,
            tracks=Stack(name="tracks", children=[]),
            metadata={"default_rate": rate},
        )


class TimelineSettings(BaseModel):
    default_framerate: float = Field(
        default=24.0, gt=0, description="Default framerate for the timeline"
    )
    resolution_width: int = Field(
        default=1920, gt=0, description="Output resolution width"
    )
    resolution_height: int = Field(
        default=1080, gt=0, description="Output resolution height"
    )
    sample_rate: int = Field(default=48000, gt=0, description="Audio sample rate (Hz)")
    pixel_aspect_ratio: float = Field(
        default=1.0, gt=0, description="Pixel aspect ratio (1.0 for square pixels)"
    )
    audio_channels: int = Field(default=2, gt=0, description="Number of audio channels")


class CheckpointSummary(BaseModel):
    checkpoint_id: UUID
    version: int
    parent_version: int | None
    description: str
    created_by: str
    created_at: str
    is_approved: bool


class TimelineWithVersion(BaseModel):
    timeline: Timeline
    version: int
    checkpoint_id: UUID


class TimelineDiff(BaseModel):
    from_version: int
    to_version: int
    tracks_added: list[str] = Field(default_factory=list)
    tracks_removed: list[str] = Field(default_factory=list)
    clips_added: list[dict[str, Any]] = Field(default_factory=list)
    clips_removed: list[dict[str, Any]] = Field(default_factory=list)
    clips_modified: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = Field(default="", description="Human-readable summary")


class TimelineOperationRecord(BaseModel):
    operation_id: UUID
    operation_type: str
    operation_data: dict[str, Any]
    created_at: str


class CreateTimelineRequest(BaseModel):
    name: str
    settings: TimelineSettings | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddTrackRequest(BaseModel):
    name: str
    kind: TrackKind = TrackKind.VIDEO
    index: int | None = Field(
        default=None, description="Insert position (None = append)"
    )


class AddClipRequest(BaseModel):
    asset_id: UUID
    source_range: TimeRange
    name: str | None = None
    insert_index: int | None = Field(
        default=None, description="Position in track (None = append)"
    )


class TrimClipRequest(BaseModel):
    new_source_range: TimeRange


class MoveClipRequest(BaseModel):
    to_track_index: int
    to_clip_index: int


class SlipClipRequest(BaseModel):
    offset: RationalTime


class AddGapRequest(BaseModel):
    duration: RationalTime
    insert_index: int | None = None


class AddTransitionRequest(BaseModel):
    position: int = Field(description="Insert between [position-1] and [position]")
    transition_type: TransitionType = TransitionType.SMPTE_DISSOLVE
    in_offset: RationalTime | None = None
    out_offset: RationalTime | None = None


class ModifyTransitionRequest(BaseModel):
    transition_type: TransitionType | None = None
    in_offset: RationalTime | None = None
    out_offset: RationalTime | None = None


class NestClipsRequest(BaseModel):
    start_index: int
    end_index: int
    stack_name: str


class RollbackRequest(BaseModel):
    pass


class AddMarkerRequest(BaseModel):
    marked_range: TimeRange
    name: str = ""
    color: MarkerColor = MarkerColor.RED


class AddEffectRequest(BaseModel):
    effect: EffectType


class TimelineResponse(BaseModel):
    ok: bool = True
    timeline: Timeline
    version: int
    checkpoint_id: UUID | None = None


class TimelineMutationResponse(BaseModel):
    ok: bool = True
    checkpoint: CheckpointSummary
    timeline: Timeline


class CheckpointListResponse(BaseModel):
    ok: bool = True
    checkpoints: list[CheckpointSummary]
    total: int


class TimelineDiffResponse(BaseModel):
    ok: bool = True
    diff: TimelineDiff
