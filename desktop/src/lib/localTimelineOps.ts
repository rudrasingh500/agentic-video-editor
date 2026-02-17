/**
 * Pure client-side timeline mutation functions.
 *
 * Each function takes an immutable Timeline (plus operation params), deep-clones
 * it, applies the edit, and returns the updated Timeline.  These mirror the
 * backend's `timeline_editor.py` so the editor can work fully offline.
 */

import type {
    AddClipRequest,
    AddEffectRequest,
    AddGapRequest,
    AddTrackRequest,
    AddTransitionRequest,
    Clip,
    EffectType,
    Gap,
    ModifyTransitionRequest,
    RationalTime,
    Stack,
    Timeline,
    TimeRange,
    Track,
    TrackItem,
    Transition,
} from './timelineTypes'
import { DEFAULT_TIMELINE_RATE, makeRationalTime, makeTimeRange } from './timeUtils'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const isTrack = (child: Track | Stack): child is Track =>
    child.OTIO_SCHEMA === 'Track.1'

const getTrack = (timeline: Timeline, trackIndex: number): Track => {
    const children = timeline.tracks.children
    if (trackIndex < 0 || trackIndex >= children.length) {
        throw new Error(`Track index ${trackIndex} out of range (0..${children.length - 1})`)
    }
    const child = children[trackIndex]
    if (!isTrack(child)) {
        throw new Error(`Item at index ${trackIndex} is not a Track`)
    }
    return child
}

const getItem = (track: Track, itemIndex: number): TrackItem => {
    if (itemIndex < 0 || itemIndex >= track.children.length) {
        throw new Error(`Item index ${itemIndex} out of range (0..${track.children.length - 1})`)
    }
    return track.children[itemIndex]
}

const assertClip = (item: TrackItem): Clip => {
    if (item.OTIO_SCHEMA !== 'Clip.1') {
        throw new Error(`Expected Clip.1 but got ${item.OTIO_SCHEMA}`)
    }
    return item
}

const assertGap = (item: TrackItem): Gap => {
    if (item.OTIO_SCHEMA !== 'Gap.1') {
        throw new Error(`Expected Gap.1 but got ${item.OTIO_SCHEMA}`)
    }
    return item
}

const assertTransition = (item: TrackItem): Transition => {
    if (item.OTIO_SCHEMA !== 'Transition.1') {
        throw new Error(`Expected Transition.1 but got ${item.OTIO_SCHEMA}`)
    }
    return item
}

const makeEmptyTrack = (name: string, kind: 'Video' | 'Audio'): Track => ({
    OTIO_SCHEMA: 'Track.1',
    name,
    kind,
    children: [],
    effects: [],
    markers: [],
    metadata: {},
})

const resolveRate = (timeline: Timeline): number => {
    const metaRate = timeline.metadata?.default_rate
    if (typeof metaRate === 'number' && Number.isFinite(metaRate) && metaRate > 0) {
        return metaRate
    }
    return timeline.global_start_time?.rate ?? DEFAULT_TIMELINE_RATE
}

// ---------------------------------------------------------------------------
// Timeline creation
// ---------------------------------------------------------------------------

export const createEmptyTimeline = (name = 'Timeline 1'): Timeline => ({
    OTIO_SCHEMA: 'Timeline.1',
    name,
    global_start_time: makeRationalTime(0, DEFAULT_TIMELINE_RATE),
    tracks: {
        OTIO_SCHEMA: 'Stack.1',
        name: 'Tracks',
        children: [
            makeEmptyTrack('Video 1', 'Video'),
            makeEmptyTrack('Audio 1', 'Audio'),
        ],
        effects: [],
        markers: [],
        metadata: {},
    },
    metadata: { default_rate: DEFAULT_TIMELINE_RATE },
})

// ---------------------------------------------------------------------------
// Track operations
// ---------------------------------------------------------------------------

export const addTrack = (timeline: Timeline, request: AddTrackRequest): Timeline => {
    const tl = clone(timeline)
    const track = makeEmptyTrack(request.name, request.kind)
    const children = tl.tracks.children
    if (request.index == null || request.index >= children.length) {
        children.push(track)
    } else {
        const idx = Math.max(0, request.index)
        children.splice(idx, 0, track)
    }
    return tl
}

export const removeTrack = (timeline: Timeline, trackIndex: number): Timeline => {
    const tl = clone(timeline)
    getTrack(tl, trackIndex) // validate
    tl.tracks.children.splice(trackIndex, 1)
    return tl
}

export const renameTrack = (
    timeline: Timeline,
    trackIndex: number,
    newName: string,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    track.name = newName
    return tl
}

export const reorderTracks = (timeline: Timeline, newOrder: number[]): Timeline => {
    const tl = clone(timeline)
    const children = tl.tracks.children
    if (newOrder.length !== children.length) {
        throw new Error(
            `newOrder length (${newOrder.length}) does not match track count (${children.length})`,
        )
    }
    const sorted = [...newOrder].sort((a, b) => a - b)
    for (let i = 0; i < sorted.length; i++) {
        if (sorted[i] !== i) {
            throw new Error('newOrder must be a permutation of [0..N-1]')
        }
    }
    tl.tracks.children = newOrder.map((i) => children[i])
    return tl
}

export const clearTrack = (timeline: Timeline, trackIndex: number): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    track.children = []
    return tl
}

// ---------------------------------------------------------------------------
// Clip operations
// ---------------------------------------------------------------------------

export const addClip = (
    timeline: Timeline,
    trackIndex: number,
    request: AddClipRequest,
): Timeline => {
    const tl = clone(timeline)

    // Auto-create first track if timeline is empty and trackIndex is 0
    if (tl.tracks.children.length === 0 && trackIndex === 0) {
        tl.tracks.children.push(makeEmptyTrack('Video 1', 'Video'))
    }

    const track = getTrack(tl, trackIndex)

    const clip: Clip = {
        OTIO_SCHEMA: 'Clip.1',
        name: request.name ?? 'Clip',
        source_range: request.source_range,
        media_reference: {
            OTIO_SCHEMA: 'ExternalReference.1',
            asset_id: request.asset_id,
            metadata: {},
        },
        effects: [],
        markers: [],
        metadata: {},
    }

    if (request.insert_index != null && request.insert_index < track.children.length) {
        track.children.splice(Math.max(0, request.insert_index), 0, clip)
    } else {
        track.children.push(clip)
    }

    return tl
}

export const removeClip = (
    timeline: Timeline,
    trackIndex: number,
    clipIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, clipIndex)
    assertClip(item)
    track.children.splice(clipIndex, 1)
    return tl
}

export const trimClip = (
    timeline: Timeline,
    trackIndex: number,
    clipIndex: number,
    newSourceRange: TimeRange,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, clipIndex)
    const clip = assertClip(item)
    clip.source_range = newSourceRange
    return tl
}

export const splitClip = (
    timeline: Timeline,
    trackIndex: number,
    clipIndex: number,
    splitOffset: RationalTime,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, clipIndex)
    const clip = assertClip(item)

    const origStart = clip.source_range.start_time
    const origDuration = clip.source_range.duration
    const rate = origDuration.rate

    if (splitOffset.value <= 0 || splitOffset.value >= origDuration.value) {
        throw new Error(
            `Split offset (${splitOffset.value}) must be between 0 and clip duration (${origDuration.value})`,
        )
    }

    // First half: same start, shorter duration
    const firstClip: Clip = clone(clip)
    firstClip.source_range = makeTimeRange(origStart.value, splitOffset.value, rate)

    // Second half: shifted start, remaining duration
    const secondClip: Clip = clone(clip)
    secondClip.source_range = makeTimeRange(
        origStart.value + splitOffset.value,
        origDuration.value - splitOffset.value,
        rate,
    )

    track.children.splice(clipIndex, 1, firstClip, secondClip)
    return tl
}

export const slipClip = (
    timeline: Timeline,
    trackIndex: number,
    clipIndex: number,
    offset: RationalTime,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, clipIndex)
    const clip = assertClip(item)

    const currentStart = clip.source_range.start_time
    const rate = currentStart.rate
    const offsetValue = offset.rate === rate
        ? offset.value
        : (offset.value * rate) / offset.rate

    clip.source_range.start_time = makeRationalTime(
        currentStart.value + offsetValue,
        rate,
    )

    return tl
}

export const moveClip = (
    timeline: Timeline,
    fromTrackIndex: number,
    clipIndex: number,
    toTrackIndex: number,
    toClipIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const srcTrack = getTrack(tl, fromTrackIndex)
    const item = getItem(srcTrack, clipIndex)
    assertClip(item)

    // Remove from source
    srcTrack.children.splice(clipIndex, 1)

    const dstTrack = getTrack(tl, toTrackIndex)

    // Adjust destination index if same track and source was before destination
    let destIdx = toClipIndex
    if (fromTrackIndex === toTrackIndex && clipIndex < toClipIndex) {
        destIdx = Math.max(0, destIdx - 1)
    }
    destIdx = Math.max(0, Math.min(destIdx, dstTrack.children.length))

    dstTrack.children.splice(destIdx, 0, item)

    return tl
}

export const replaceClipMedia = (
    timeline: Timeline,
    trackIndex: number,
    clipIndex: number,
    newAssetId: string,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, clipIndex)
    const clip = assertClip(item)

    clip.media_reference = {
        OTIO_SCHEMA: 'ExternalReference.1',
        asset_id: newAssetId,
        metadata: {},
    }

    return tl
}

// ---------------------------------------------------------------------------
// Gap operations
// ---------------------------------------------------------------------------

export const addGap = (
    timeline: Timeline,
    trackIndex: number,
    request: AddGapRequest,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)

    const gap: Gap = {
        OTIO_SCHEMA: 'Gap.1',
        name: '',
        source_range: makeTimeRange(0, request.duration.value, request.duration.rate),
        effects: [],
        markers: [],
        metadata: {},
    }

    if (request.insert_index != null && request.insert_index < track.children.length) {
        track.children.splice(Math.max(0, request.insert_index), 0, gap)
    } else {
        track.children.push(gap)
    }

    return tl
}

export const removeGap = (
    timeline: Timeline,
    trackIndex: number,
    gapIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, gapIndex)
    assertGap(item)
    track.children.splice(gapIndex, 1)
    return tl
}

// ---------------------------------------------------------------------------
// Transition operations
// ---------------------------------------------------------------------------

const validateTransitionPosition = (track: Track, position: number): void => {
    const children = track.children
    if (position < 1 || position >= children.length) {
        throw new Error(
            `Transition position ${position} out of range (must be 1..${children.length - 1})`,
        )
    }
    if (children[position - 1].OTIO_SCHEMA === 'Transition.1') {
        throw new Error('Previous item is already a transition')
    }
    if (children[position].OTIO_SCHEMA === 'Transition.1') {
        throw new Error('Next item is already a transition')
    }
}

export const addTransition = (
    timeline: Timeline,
    trackIndex: number,
    request: AddTransitionRequest,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const rate = resolveRate(tl)
    const defaultFrames = Math.round(rate / 2) // 12 frames at 24fps

    validateTransitionPosition(track, request.position)

    const transition: Transition = {
        OTIO_SCHEMA: 'Transition.1',
        name: request.transition_type,
        transition_type: request.transition_type,
        in_offset: request.in_offset ?? makeRationalTime(defaultFrames, rate),
        out_offset: request.out_offset ?? makeRationalTime(defaultFrames, rate),
        metadata: {},
    }

    track.children.splice(request.position, 0, transition)

    return tl
}

export const removeTransition = (
    timeline: Timeline,
    trackIndex: number,
    transitionIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, transitionIndex)
    assertTransition(item)
    track.children.splice(transitionIndex, 1)
    return tl
}

export const modifyTransition = (
    timeline: Timeline,
    trackIndex: number,
    transitionIndex: number,
    request: ModifyTransitionRequest,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, transitionIndex)
    const transition = assertTransition(item)

    if (request.transition_type != null) {
        transition.transition_type = request.transition_type
        transition.name = request.transition_type
    }
    if (request.in_offset != null) {
        transition.in_offset = request.in_offset
    }
    if (request.out_offset != null) {
        transition.out_offset = request.out_offset
    }

    return tl
}

// ---------------------------------------------------------------------------
// Nesting operations
// ---------------------------------------------------------------------------

export const nestItems = (
    timeline: Timeline,
    trackIndex: number,
    startIndex: number,
    endIndex: number,
    stackName: string,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)

    if (startIndex < 0 || endIndex > track.children.length || startIndex >= endIndex) {
        throw new Error(
            `Invalid nest range [${startIndex}, ${endIndex}) for track with ${track.children.length} items`,
        )
    }

    const extracted = track.children.splice(startIndex, endIndex - startIndex)

    const innerTrack: Track = {
        OTIO_SCHEMA: 'Track.1',
        name: `${stackName} Track`,
        kind: track.kind,
        children: extracted,
        effects: [],
        markers: [],
        metadata: {},
    }

    const stack: Stack = {
        OTIO_SCHEMA: 'Stack.1',
        name: stackName,
        children: [innerTrack],
        effects: [],
        markers: [],
        metadata: {},
    }

    track.children.splice(startIndex, 0, stack as unknown as TrackItem)

    return tl
}

export const flattenStack = (
    timeline: Timeline,
    trackIndex: number,
    stackIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, stackIndex)

    if (item.OTIO_SCHEMA !== 'Stack.1') {
        throw new Error(`Item at index ${stackIndex} is not a Stack`)
    }

    const stack = item as unknown as Stack
    let extractedItems: TrackItem[] = []

    if (stack.children.length > 0) {
        const firstChild = stack.children[0]
        if (isTrack(firstChild)) {
            extractedItems = firstChild.children
        } else {
            // It's a nested Stack — just inline it
            extractedItems = [firstChild as unknown as TrackItem]
        }
    }

    track.children.splice(stackIndex, 1, ...extractedItems)

    return tl
}

// ---------------------------------------------------------------------------
// Marker operations
// ---------------------------------------------------------------------------

export const addMarker = (
    timeline: Timeline,
    trackIndex: number,
    itemIndex: number,
    request: { marked_range: TimeRange; name?: string; color?: string },
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, itemIndex)

    if (!('markers' in item)) {
        throw new Error('Item does not support markers')
    }

    const typedItem = item as { markers: Array<Record<string, unknown>> }
    typedItem.markers.push({
        OTIO_SCHEMA: 'Marker.1',
        name: request.name ?? 'Marker',
        marked_range: request.marked_range,
        color: request.color ?? 'GREEN',
        metadata: {},
    })

    return tl
}

export const removeMarker = (
    timeline: Timeline,
    trackIndex: number,
    itemIndex: number,
    markerIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, itemIndex)

    if (!('markers' in item)) {
        throw new Error('Item does not support markers')
    }

    const typedItem = item as { markers: unknown[] }
    if (markerIndex < 0 || markerIndex >= typedItem.markers.length) {
        throw new Error(
            `Marker index ${markerIndex} out of range (0..${typedItem.markers.length - 1})`,
        )
    }

    typedItem.markers.splice(markerIndex, 1)

    return tl
}

// ---------------------------------------------------------------------------
// Effect operations
// ---------------------------------------------------------------------------

export const addEffect = (
    timeline: Timeline,
    trackIndex: number,
    itemIndex: number,
    request: AddEffectRequest,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, itemIndex)

    if (!('effects' in item)) {
        throw new Error('Item does not support effects')
    }

    const typedItem = item as { effects: EffectType[] }
    typedItem.effects.push(request.effect)

    return tl
}

export const removeEffect = (
    timeline: Timeline,
    trackIndex: number,
    itemIndex: number,
    effectIndex: number,
): Timeline => {
    const tl = clone(timeline)
    const track = getTrack(tl, trackIndex)
    const item = getItem(track, itemIndex)

    if (!('effects' in item)) {
        throw new Error('Item does not support effects')
    }

    const typedItem = item as { effects: unknown[] }
    if (effectIndex < 0 || effectIndex >= typedItem.effects.length) {
        throw new Error(
            `Effect index ${effectIndex} out of range (0..${typedItem.effects.length - 1})`,
        )
    }

    typedItem.effects.splice(effectIndex, 1)

    return tl
}

// ---------------------------------------------------------------------------
// Whole-timeline replace (used by sync)
// ---------------------------------------------------------------------------

export const replaceTimeline = (
    _current: Timeline,
    replacement: Timeline,
): Timeline => clone(replacement)
