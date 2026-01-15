"""
OpenTimelineIO-compatible Pydantic models for timeline representation.

This module implements a comprehensive timeline data model inspired by the
OpenTimelineIO (OTIO) specification. It supports:
- Full OTIO hierarchy: Timeline -> Stack -> Tracks -> Clips/Gaps/Transitions
- Nested compositions (Stacks within Tracks)
- Effects, markers, and metadata
- Time-based operations with RationalTime and TimeRange

Reference: https://opentimelineio.readthedocs.io/
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# =============================================================================
# ENUMS
# =============================================================================


class TrackKind(str, Enum):
    """Type of track content."""
    VIDEO = "Video"
    AUDIO = "Audio"


class MarkerColor(str, Enum):
    """Standard marker colors (OTIO spec)."""
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
    """Common transition types."""
    SMPTE_DISSOLVE = "SMPTE_Dissolve"
    CUSTOM = "Custom"
    FADE_IN = "FadeIn"
    FADE_OUT = "FadeOut"
    WIPE = "Wipe"
    SLIDE = "Slide"


# =============================================================================
# CORE TIME TYPES
# =============================================================================


class RationalTime(BaseModel):
    """
    Represents a point in time with a rational number (value/rate).
    
    This is the fundamental time unit in OTIO. Time is represented as a
    rational number to avoid floating-point precision issues common in
    video editing (e.g., 24fps, 29.97fps, etc.).
    
    Examples:
        - Frame 100 at 24fps: RationalTime(value=100, rate=24)
        - 5 seconds at 24fps: RationalTime(value=120, rate=24)
        - Timecode 00:00:01:00 at 30fps: RationalTime(value=30, rate=30)
    """
    OTIO_SCHEMA: Literal["RationalTime.1"] = "RationalTime.1"
    value: float = Field(description="Time value (typically frame number)")
    rate: float = Field(default=24.0, gt=0, description="Rate (frames per second)")

    def to_seconds(self) -> float:
        """Convert to seconds."""
        return self.value / self.rate

    def to_frames(self, target_rate: float | None = None) -> float:
        """Convert to frame count at target rate (or same rate if None)."""
        if target_rate is None:
            return self.value
        return self.value * target_rate / self.rate

    def to_milliseconds(self) -> float:
        """Convert to milliseconds."""
        return (self.value / self.rate) * 1000

    def rescaled_to(self, new_rate: float) -> RationalTime:
        """Return new RationalTime at different rate, preserving actual time."""
        return RationalTime(
            value=self.value * new_rate / self.rate,
            rate=new_rate
        )

    def __add__(self, other: RationalTime) -> RationalTime:
        """Add two RationalTimes (converts to same rate first)."""
        if self.rate == other.rate:
            return RationalTime(value=self.value + other.value, rate=self.rate)
        # Convert other to self's rate
        other_rescaled = other.rescaled_to(self.rate)
        return RationalTime(value=self.value + other_rescaled.value, rate=self.rate)

    def __sub__(self, other: RationalTime) -> RationalTime:
        """Subtract two RationalTimes."""
        if self.rate == other.rate:
            return RationalTime(value=self.value - other.value, rate=self.rate)
        other_rescaled = other.rescaled_to(self.rate)
        return RationalTime(value=self.value - other_rescaled.value, rate=self.rate)

    def __mul__(self, scalar: float) -> RationalTime:
        """Multiply by scalar."""
        return RationalTime(value=self.value * scalar, rate=self.rate)

    def __eq__(self, other: object) -> bool:
        """Compare equality (considers rate conversion)."""
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
        """Create RationalTime from seconds."""
        return cls(value=seconds * rate, rate=rate)

    @classmethod
    def from_milliseconds(cls, ms: float, rate: float = 24.0) -> RationalTime:
        """Create RationalTime from milliseconds."""
        return cls(value=(ms / 1000) * rate, rate=rate)

    @classmethod
    def from_frames(cls, frames: float, rate: float = 24.0) -> RationalTime:
        """Create RationalTime from frame count."""
        return cls(value=frames, rate=rate)


class TimeRange(BaseModel):
    """
    Represents a range of time with a start point and duration.
    
    Used to define:
    - Source ranges (in/out points) for clips
    - Available ranges for media references
    - Marked ranges for markers
    
    Note: The end time is exclusive (start_time + duration).
    """
    OTIO_SCHEMA: Literal["TimeRange.1"] = "TimeRange.1"
    start_time: RationalTime = Field(description="Start of the range")
    duration: RationalTime = Field(description="Duration of the range")

    @property
    def end_time_exclusive(self) -> RationalTime:
        """Get the exclusive end time (start + duration)."""
        return self.start_time + self.duration

    @property
    def end_time_inclusive(self) -> RationalTime:
        """Get the inclusive end time (last valid frame)."""
        return RationalTime(
            value=self.start_time.value + self.duration.value - 1,
            rate=self.start_time.rate
        )

    def contains(self, time: RationalTime) -> bool:
        """Check if a time point falls within this range."""
        return self.start_time <= time < self.end_time_exclusive

    def overlaps(self, other: TimeRange) -> bool:
        """Check if this range overlaps with another."""
        return (
            self.start_time < other.end_time_exclusive and
            other.start_time < self.end_time_exclusive
        )

    def contains_range(self, other: TimeRange) -> bool:
        """Check if this range fully contains another range."""
        return (
            self.start_time <= other.start_time and
            self.end_time_exclusive >= other.end_time_exclusive
        )

    def extended_by(self, other: TimeRange) -> TimeRange:
        """Return a new range that encompasses both ranges."""
        new_start = min(self.start_time, other.start_time)
        new_end = max(self.end_time_exclusive, other.end_time_exclusive)
        return TimeRange(
            start_time=new_start,
            duration=new_end - new_start
        )

    def clamped_to(self, other: TimeRange) -> TimeRange | None:
        """Return intersection of ranges, or None if no overlap."""
        if not self.overlaps(other):
            return None
        new_start = max(self.start_time, other.start_time)
        new_end = min(self.end_time_exclusive, other.end_time_exclusive)
        return TimeRange(
            start_time=new_start,
            duration=new_end - new_start
        )

    def to_milliseconds(self) -> tuple[float, float]:
        """Convert to (start_ms, duration_ms) tuple."""
        return (self.start_time.to_milliseconds(), self.duration.to_milliseconds())

    @classmethod
    def from_start_end(
        cls,
        start: RationalTime,
        end: RationalTime
    ) -> TimeRange:
        """Create TimeRange from start and end times."""
        return cls(start_time=start, duration=end - start)

    @classmethod
    def from_milliseconds(
        cls,
        start_ms: float,
        duration_ms: float,
        rate: float = 24.0
    ) -> TimeRange:
        """Create TimeRange from millisecond values."""
        return cls(
            start_time=RationalTime.from_milliseconds(start_ms, rate),
            duration=RationalTime.from_milliseconds(duration_ms, rate)
        )


# =============================================================================
# MEDIA REFERENCES
# =============================================================================


class ExternalReference(BaseModel):
    """
    Reference to external media stored as an asset.
    
    This is the primary media reference type, pointing to assets in
    the assets table via asset_id.
    """
    OTIO_SCHEMA: Literal["ExternalReference.1"] = "ExternalReference.1"
    asset_id: UUID = Field(description="Reference to assets table")
    available_range: TimeRange | None = Field(
        default=None,
        description="Full range of media available in the asset"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratorReference(BaseModel):
    """
    Reference to procedurally generated media.
    
    Used for solid colors, test patterns, tone generators, etc.
    """
    OTIO_SCHEMA: Literal["GeneratorReference.1"] = "GeneratorReference.1"
    generator_kind: str = Field(
        description="Type of generator: SolidColor, Bars, Tone, Slug, etc."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Generator parameters, e.g., {'color': '#000000'}"
    )
    available_range: TimeRange | None = Field(
        default=None,
        description="Available range (often unlimited for generators)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissingReference(BaseModel):
    """
    Placeholder for missing or offline media.
    
    Used when the actual media is unavailable but we want to
    preserve the timeline structure.
    """
    OTIO_SCHEMA: Literal["MissingReference.1"] = "MissingReference.1"
    name: str = Field(default="", description="Name of missing media")
    available_range: TimeRange | None = Field(
        default=None,
        description="Expected range if known"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# Union type for all media references
MediaReference = Annotated[
    Union[ExternalReference, GeneratorReference, MissingReference],
    Field(discriminator="OTIO_SCHEMA")
]


# =============================================================================
# EFFECTS
# =============================================================================


class Effect(BaseModel):
    """
    Base effect class for audio/video effects on clips or tracks.
    """
    OTIO_SCHEMA: Literal["Effect.1"] = "Effect.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(description="Effect identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinearTimeWarp(BaseModel):
    """
    Linear time warp effect (speed change).
    
    time_scalar controls playback speed:
    - 1.0 = normal speed
    - 2.0 = 2x speed (fast motion)
    - 0.5 = half speed (slow motion)
    - -1.0 = reverse playback
    """
    OTIO_SCHEMA: Literal["LinearTimeWarp.1"] = "LinearTimeWarp.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(default="LinearTimeWarp")
    time_scalar: float = Field(
        default=1.0,
        description="Speed multiplier (1.0 = normal, 2.0 = 2x speed)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class FreezeFrame(BaseModel):
    """
    Freeze frame effect - holds a single frame.
    """
    OTIO_SCHEMA: Literal["FreezeFrame.1"] = "FreezeFrame.1"
    name: str = Field(default="", description="Display name")
    effect_name: str = Field(default="FreezeFrame")
    metadata: dict[str, Any] = Field(default_factory=dict)


# Union type for effects
EffectType = Annotated[
    Union[Effect, LinearTimeWarp, FreezeFrame],
    Field(discriminator="OTIO_SCHEMA")
]


# =============================================================================
# MARKERS
# =============================================================================


class Marker(BaseModel):
    """
    A marker/annotation at a specific point or range on the timeline.
    
    Markers can be used for:
    - Notes and comments
    - Chapter markers
    - Review notes
    - Sync points
    """
    OTIO_SCHEMA: Literal["Marker.1"] = "Marker.1"
    name: str = Field(default="", description="Marker label")
    marked_range: TimeRange = Field(description="Range this marker covers")
    color: MarkerColor = Field(
        default=MarkerColor.RED,
        description="Visual color for the marker"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# COMPOSABLE ITEMS (Track children)
# =============================================================================


class Clip(BaseModel):
    """
    A clip of media on the timeline.
    
    Clips reference media through media_reference and define which
    portion of that media to use via source_range.
    """
    OTIO_SCHEMA: Literal["Clip.1"] = "Clip.1"
    name: str = Field(default="", description="Clip name")
    source_range: TimeRange = Field(
        description="Portion of source media to use (in/out points)"
    )
    media_reference: MediaReference = Field(
        description="Reference to the source media"
    )
    effects: list[EffectType] = Field(
        default_factory=list,
        description="Effects applied to this clip"
    )
    markers: list[Marker] = Field(
        default_factory=list,
        description="Markers on this clip"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        """Get the duration of this clip on the timeline."""
        return self.source_range.duration


class Gap(BaseModel):
    """
    Empty space on the timeline.
    
    Gaps are transparent - content from lower tracks shows through.
    Use a Clip with GeneratorReference for solid colors.
    """
    OTIO_SCHEMA: Literal["Gap.1"] = "Gap.1"
    name: str = Field(default="", description="Gap name")
    source_range: TimeRange = Field(description="Duration of the gap")
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        """Get the duration of this gap."""
        return self.source_range.duration

    @classmethod
    def with_duration(cls, duration: RationalTime, name: str = "") -> Gap:
        """Create a gap with specified duration."""
        return cls(
            name=name,
            source_range=TimeRange(
                start_time=RationalTime(value=0, rate=duration.rate),
                duration=duration
            )
        )


class Transition(BaseModel):
    """
    A transition between two adjacent items on a track.
    
    Transitions overlap the end of the outgoing clip and the
    beginning of the incoming clip:
    
    Clip A:     [==========]
    Transition:        [====]
    Clip B:            [==========]
    
    - in_offset: frames from outgoing clip used in transition
    - out_offset: frames from incoming clip used in transition
    
    The transition duration = in_offset + out_offset
    """
    OTIO_SCHEMA: Literal["Transition.1"] = "Transition.1"
    name: str = Field(default="", description="Transition name")
    transition_type: TransitionType = Field(
        default=TransitionType.SMPTE_DISSOLVE,
        description="Type of transition effect"
    )
    in_offset: RationalTime = Field(
        description="Duration into outgoing clip"
    )
    out_offset: RationalTime = Field(
        description="Duration from incoming clip"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        """Total duration of the transition."""
        return self.in_offset + self.out_offset

    @classmethod
    def dissolve(
        cls,
        duration_frames: float = 24,
        rate: float = 24.0
    ) -> Transition:
        """Create a standard dissolve transition."""
        half = RationalTime(value=duration_frames / 2, rate=rate)
        return cls(
            name="Dissolve",
            transition_type=TransitionType.SMPTE_DISSOLVE,
            in_offset=half,
            out_offset=half
        )


# =============================================================================
# COMPOSITIONS (Containers)
# =============================================================================


# Forward reference for nested compositions
class Stack(BaseModel):
    """
    Parallel container - children are layered/composited.
    
    In a Stack, all children exist at the same time and are
    composited together (like video layers in Photoshop).
    Higher indexed children are rendered on top.
    
    The Stack's duration is the maximum duration of its children.
    """
    OTIO_SCHEMA: Literal["Stack.1"] = "Stack.1"
    name: str = Field(default="", description="Stack name")
    source_range: TimeRange | None = Field(
        default=None,
        description="Optional trim of the stack"
    )
    children: list[Track | Stack] = Field(
        default_factory=list,
        description="Child tracks or nested stacks"
    )
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def duration(self) -> RationalTime:
        """Calculate duration as max of children durations."""
        if not self.children:
            return RationalTime(value=0, rate=24.0)
        
        max_duration = RationalTime(value=0, rate=24.0)
        for child in self.children:
            child_dur = child.duration()
            if child_dur > max_duration:
                max_duration = child_dur
        
        # Apply source_range trim if present
        if self.source_range:
            return self.source_range.duration
        return max_duration

    def trimmed_range(self) -> TimeRange:
        """Get the range after trimming."""
        dur = self.duration()
        if self.source_range:
            return self.source_range
        return TimeRange(
            start_time=RationalTime(value=0, rate=dur.rate),
            duration=dur
        )


# TrackItem union - what can go in a Track
# Note: Stack can be nested in Track for compound clips
TrackItem = Annotated[
    Union[Clip, Gap, Transition, Stack],
    Field(discriminator="OTIO_SCHEMA")
]


class Track(BaseModel):
    """
    Sequential container - items play one after another.
    
    Items in a Track are arranged sequentially in time.
    The Track's duration is the sum of its children's durations.
    
    Transitions overlap adjacent items and don't add to duration.
    """
    OTIO_SCHEMA: Literal["Track.1"] = "Track.1"
    name: str = Field(default="", description="Track name")
    kind: TrackKind = Field(
        default=TrackKind.VIDEO,
        description="Track type (Video or Audio)"
    )
    source_range: TimeRange | None = Field(
        default=None,
        description="Optional trim of the track"
    )
    children: list[TrackItem] = Field(
        default_factory=list,
        description="Clips, gaps, transitions, or nested stacks"
    )
    effects: list[EffectType] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def duration(self) -> RationalTime:
        """
        Calculate total duration of track.
        
        Transitions don't add to duration - they overlap adjacent items.
        """
        if not self.children:
            return RationalTime(value=0, rate=24.0)
        
        total = RationalTime(value=0, rate=24.0)
        for child in self.children:
            if isinstance(child, Transition):
                # Transitions overlap, don't add to duration
                continue
            if hasattr(child, 'duration'):
                child_dur = child.duration() if callable(child.duration) else child.duration
                total = total + child_dur
        
        # Apply source_range trim if present
        if self.source_range:
            return self.source_range.duration
        return total

    def trimmed_range(self) -> TimeRange:
        """Get the range after trimming."""
        dur = self.duration()
        if self.source_range:
            return self.source_range
        return TimeRange(
            start_time=RationalTime(value=0, rate=dur.rate),
            duration=dur
        )

    def range_of_child(self, index: int) -> TimeRange | None:
        """
        Get the time range of a child item within this track.
        
        Returns None if index is out of bounds.
        """
        if index < 0 or index >= len(self.children):
            return None
        
        # Calculate start time by summing previous items
        start = RationalTime(value=0, rate=24.0)
        for i, child in enumerate(self.children):
            if i == index:
                if isinstance(child, Transition):
                    # Transitions don't have a simple range
                    return None
                dur = child.duration() if callable(getattr(child, 'duration', None)) else child.duration
                return TimeRange(start_time=start, duration=dur)
            
            if not isinstance(child, Transition):
                dur = child.duration() if callable(getattr(child, 'duration', None)) else child.duration
                start = start + dur
        
        return None

    def child_at_time(self, time: RationalTime) -> tuple[int, TrackItem] | None:
        """
        Find the child item at a specific time.
        
        Returns (index, item) or None if time is outside track.
        """
        current_time = RationalTime(value=0, rate=time.rate)
        
        for i, child in enumerate(self.children):
            if isinstance(child, Transition):
                continue
            
            dur = child.duration() if callable(getattr(child, 'duration', None)) else child.duration
            end_time = current_time + dur
            
            if current_time <= time < end_time:
                return (i, child)
            
            current_time = end_time
        
        return None


# Update Stack.children type after Track is defined
Stack.model_rebuild()


# =============================================================================
# TOP-LEVEL TIMELINE
# =============================================================================


class Timeline(BaseModel):
    """
    Top-level timeline object - the root of the composition tree.
    
    A Timeline contains a Stack of Tracks. The Stack allows for
    multiple video/audio layers that are composited together.
    """
    OTIO_SCHEMA: Literal["Timeline.1"] = "Timeline.1"
    name: str = Field(description="Timeline name")
    global_start_time: RationalTime | None = Field(
        default=None,
        description="Timeline start time (e.g., 01:00:00:00)"
    )
    tracks: Stack = Field(
        default_factory=lambda: Stack(name="tracks"),
        description="Root stack containing all tracks"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> RationalTime:
        """Get the total duration of the timeline."""
        return self.tracks.duration()

    @property
    def video_tracks(self) -> list[Track]:
        """Get all video tracks."""
        return [
            t for t in self.tracks.children
            if isinstance(t, Track) and t.kind == TrackKind.VIDEO
        ]

    @property
    def audio_tracks(self) -> list[Track]:
        """Get all audio tracks."""
        return [
            t for t in self.tracks.children
            if isinstance(t, Track) and t.kind == TrackKind.AUDIO
        ]

    def find_clips(self) -> list[Clip]:
        """Find all clips in the timeline (recursive)."""
        clips: list[Clip] = []
        self._find_clips_recursive(self.tracks, clips)
        return clips

    def _find_clips_recursive(
        self,
        item: Stack | Track | TrackItem,
        clips: list[Clip]
    ) -> None:
        """Recursively find clips."""
        if isinstance(item, Clip):
            clips.append(item)
        elif isinstance(item, (Stack, Track)):
            for child in item.children:
                self._find_clips_recursive(child, clips)

    def find_gaps(self) -> list[Gap]:
        """Find all gaps in the timeline."""
        gaps: list[Gap] = []
        self._find_items_recursive(self.tracks, Gap, gaps)
        return gaps

    def find_transitions(self) -> list[Transition]:
        """Find all transitions in the timeline."""
        transitions: list[Transition] = []
        self._find_items_recursive(self.tracks, Transition, transitions)
        return transitions

    def _find_items_recursive(
        self,
        item: Stack | Track | TrackItem,
        item_type: type,
        results: list
    ) -> None:
        """Recursively find items of a specific type."""
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
        global_start_time: RationalTime | None = None
    ) -> Timeline:
        """Create an empty timeline with default structure."""
        return cls(
            name=name,
            global_start_time=global_start_time,
            tracks=Stack(name="tracks", children=[]),
            metadata={"default_rate": rate}
        )


# =============================================================================
# TIMELINE SETTINGS (Project-level configuration)
# =============================================================================


class TimelineSettings(BaseModel):
    """
    Project-level timeline settings.
    
    Stores default values and project configuration.
    """
    default_framerate: float = Field(
        default=24.0,
        gt=0,
        description="Default framerate for the timeline"
    )
    resolution_width: int = Field(
        default=1920,
        gt=0,
        description="Output resolution width"
    )
    resolution_height: int = Field(
        default=1080,
        gt=0,
        description="Output resolution height"
    )
    sample_rate: int = Field(
        default=48000,
        gt=0,
        description="Audio sample rate (Hz)"
    )
    pixel_aspect_ratio: float = Field(
        default=1.0,
        gt=0,
        description="Pixel aspect ratio (1.0 for square pixels)"
    )
    audio_channels: int = Field(
        default=2,
        gt=0,
        description="Number of audio channels"
    )


# =============================================================================
# API RESPONSE MODELS
# =============================================================================


class CheckpointSummary(BaseModel):
    """Summary of a timeline checkpoint (for history lists)."""
    checkpoint_id: UUID
    version: int
    parent_version: int | None
    description: str
    created_by: str
    created_at: str  # ISO format
    is_approved: bool


class TimelineWithVersion(BaseModel):
    """Timeline snapshot with version info."""
    timeline: Timeline
    version: int
    checkpoint_id: UUID


class TimelineDiff(BaseModel):
    """Diff between two timeline versions."""
    from_version: int
    to_version: int
    tracks_added: list[str] = Field(default_factory=list)
    tracks_removed: list[str] = Field(default_factory=list)
    clips_added: list[dict[str, Any]] = Field(default_factory=list)
    clips_removed: list[dict[str, Any]] = Field(default_factory=list)
    clips_modified: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = Field(default="", description="Human-readable summary")


class TimelineOperationRecord(BaseModel):
    """Record of an operation performed on the timeline."""
    operation_id: UUID
    operation_type: str
    operation_data: dict[str, Any]
    created_at: str  # ISO format


# =============================================================================
# REQUEST MODELS
# =============================================================================


class CreateTimelineRequest(BaseModel):
    """Request to create a new timeline."""
    name: str
    settings: TimelineSettings | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddTrackRequest(BaseModel):
    """Request to add a track."""
    name: str
    kind: TrackKind = TrackKind.VIDEO
    index: int | None = Field(
        default=None,
        description="Insert position (None = append)"
    )


class AddClipRequest(BaseModel):
    """Request to add a clip."""
    asset_id: UUID
    source_range: TimeRange
    name: str | None = None
    insert_index: int | None = Field(
        default=None,
        description="Position in track (None = append)"
    )


class TrimClipRequest(BaseModel):
    """Request to trim a clip."""
    new_source_range: TimeRange


class MoveClipRequest(BaseModel):
    """Request to move a clip."""
    to_track_index: int
    to_clip_index: int


class SlipClipRequest(BaseModel):
    """Request to slip a clip (change source while keeping duration)."""
    offset: RationalTime


class AddGapRequest(BaseModel):
    """Request to add a gap."""
    duration: RationalTime
    insert_index: int | None = None


class AddTransitionRequest(BaseModel):
    """Request to add a transition."""
    position: int = Field(description="Insert between [position-1] and [position]")
    transition_type: TransitionType = TransitionType.SMPTE_DISSOLVE
    in_offset: RationalTime | None = None
    out_offset: RationalTime | None = None


class ModifyTransitionRequest(BaseModel):
    """Request to modify a transition."""
    transition_type: TransitionType | None = None
    in_offset: RationalTime | None = None
    out_offset: RationalTime | None = None


class NestClipsRequest(BaseModel):
    """Request to nest clips as a stack."""
    start_index: int
    end_index: int  # Inclusive
    stack_name: str


class RollbackRequest(BaseModel):
    """Request to rollback to a version."""
    # Note: version is in URL path


class AddMarkerRequest(BaseModel):
    """Request to add a marker."""
    marked_range: TimeRange
    name: str = ""
    color: MarkerColor = MarkerColor.RED


class AddEffectRequest(BaseModel):
    """Request to add an effect."""
    effect: EffectType


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class TimelineResponse(BaseModel):
    """Response containing timeline data."""
    ok: bool = True
    timeline: Timeline
    version: int
    checkpoint_id: UUID | None = None


class TimelineMutationResponse(BaseModel):
    """Response after mutating the timeline."""
    ok: bool = True
    checkpoint: CheckpointSummary
    timeline: Timeline


class CheckpointListResponse(BaseModel):
    """Response containing checkpoint history."""
    ok: bool = True
    checkpoints: list[CheckpointSummary]
    total: int


class TimelineDiffResponse(BaseModel):
    """Response containing diff between versions."""
    ok: bool = True
    diff: TimelineDiff
