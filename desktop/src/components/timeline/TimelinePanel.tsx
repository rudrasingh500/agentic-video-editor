import { Minus, Plus } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from 'react'

import {
  DEFAULT_TIMELINE_RATE,
  formatTimecode,
  makeRationalTime,
  secondsToTime,
  timeToSeconds,
} from '../../lib/timeUtils'
import type {
  Clip,
  RationalTime,
  Stack,
  TimeRange,
  Timeline,
  Track,
  TrackItem,
} from '../../lib/timelineTypes'
import { usePlaybackStore } from '../../stores/playbackStore'
import { useUiStore } from '../../stores/uiStore'

const TRACK_LABEL_WIDTH = 156
const BASE_PIXELS_PER_SECOND = 90
const MIN_TIMELINE_WIDTH = 760
const MIN_TIMELINE_SECONDS = 12
const TRANSITION_MIN_WIDTH = 12

type VisualTrackItem = {
  itemIndex: number
  startSeconds: number
  durationSeconds: number
  item: TrackItem
  displayLabel: string
}

type TrackLayout = {
  track: Track
  trackIndex: number
  items: VisualTrackItem[]
  durationSeconds: number
}

type TrimEdge = 'start' | 'end'

type TrimDragState = {
  trackIndex: number
  clipIndex: number
  edge: TrimEdge
  initialClientX: number
  clip: Clip
  initialSourceRange: TimeRange
}

const isTrack = (item: Track | Stack): item is Track => item.OTIO_SCHEMA === 'Track.1'

const isFinitePositive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0

const readDurationSeconds = (time: RationalTime): number => {
  const seconds = timeToSeconds(time)
  if (!Number.isFinite(seconds) || seconds < 0) {
    return 0
  }
  return seconds
}

const stackDurationSeconds = (stack: Stack): number => {
  if (stack.source_range) {
    return readDurationSeconds(stack.source_range.duration)
  }

  let maxDuration = 0
  for (const child of stack.children) {
    const childDuration = isTrack(child) ? trackDurationSeconds(child) : stackDurationSeconds(child)
    if (childDuration > maxDuration) {
      maxDuration = childDuration
    }
  }
  return maxDuration
}

const itemDurationSeconds = (item: TrackItem): number => {
  if (item.OTIO_SCHEMA === 'Clip.1' || item.OTIO_SCHEMA === 'Gap.1') {
    return readDurationSeconds(item.source_range.duration)
  }
  if (item.OTIO_SCHEMA === 'Transition.1') {
    return readDurationSeconds(item.in_offset) + readDurationSeconds(item.out_offset)
  }
  return stackDurationSeconds(item)
}

const trackDurationSeconds = (track: Track): number => {
  if (track.source_range) {
    return readDurationSeconds(track.source_range.duration)
  }

  let total = 0
  for (const item of track.children) {
    if (item.OTIO_SCHEMA === 'Transition.1') {
      continue
    }
    total += itemDurationSeconds(item)
  }
  return total
}

const itemRate = (item: TrackItem): number | null => {
  if (item.OTIO_SCHEMA === 'Clip.1' || item.OTIO_SCHEMA === 'Gap.1') {
    return item.source_range.duration.rate
  }
  if (item.OTIO_SCHEMA === 'Transition.1') {
    return item.in_offset.rate
  }

  if (item.source_range) {
    return item.source_range.duration.rate
  }

  for (const child of item.children) {
    if (isTrack(child)) {
      for (const childItem of child.children) {
        const childRate = itemRate(childItem)
        if (isFinitePositive(childRate)) {
          return childRate
        }
      }
      continue
    }

    if (child.source_range) {
      return child.source_range.duration.rate
    }
  }

  return null
}

const resolveTimelineRate = (timeline: Timeline | null, tracks: Track[]): number => {
  const metadataRate = timeline?.metadata?.default_rate
  if (isFinitePositive(metadataRate)) {
    return metadataRate
  }

  for (const track of tracks) {
    for (const item of track.children) {
      const rate = itemRate(item)
      if (isFinitePositive(rate)) {
        return rate
      }
    }
  }

  if (timeline?.global_start_time && isFinitePositive(timeline.global_start_time.rate)) {
    return timeline.global_start_time.rate
  }

  return DEFAULT_TIMELINE_RATE
}

const itemLabel = (item: TrackItem) => {
  if (item.OTIO_SCHEMA === 'Clip.1') {
    return item.name || 'Clip'
  }
  if (item.OTIO_SCHEMA === 'Gap.1') {
    return 'Gap'
  }
  if (item.OTIO_SCHEMA === 'Transition.1') {
    return item.transition_type
  }
  return item.name || 'Stack'
}

const buildTrackLayouts = (tracks: Track[]): TrackLayout[] => {
  return tracks.map((track, trackIndex) => {
    let cursorSeconds = 0
    const items: VisualTrackItem[] = []

    track.children.forEach((item, itemIndex) => {
      const durationSeconds = itemDurationSeconds(item)
      items.push({
        itemIndex,
        startSeconds: cursorSeconds,
        durationSeconds,
        item,
        displayLabel: itemLabel(item),
      })

      if (item.OTIO_SCHEMA !== 'Transition.1') {
        cursorSeconds += durationSeconds
      }
    })

    return {
      track,
      trackIndex,
      items,
      durationSeconds: trackDurationSeconds(track),
    }
  })
}

type TimelinePanelProps = {
  timeline: Timeline | null
  onDropAsset?: (assetId: string) => void
  onMoveClip?: (payload: {
    fromTrackIndex: number
    clipIndex: number
    toTrackIndex: number
    toClipIndex: number
  }) => void
  onTrimClip?: (payload: {
    trackIndex: number
    clipIndex: number
    newSourceRange: TimeRange
  }) => void
  onSplitClip?: (payload: {
    trackIndex: number
    clipIndex: number
    splitOffset: RationalTime
  }) => void
}

const TimelinePanel = ({
  timeline,
  onDropAsset,
  onMoveClip,
  onTrimClip,
  onSplitClip,
}: TimelinePanelProps) => {
  const rulerCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)

  const [scrubbing, setScrubbing] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [clipDropIndicator, setClipDropIndicator] = useState<{
    trackIndex: number
    insertIndex: number
    x: number
  } | null>(null)
  const [trimDrag, setTrimDrag] = useState<TrimDragState | null>(null)
  const [trimPreview, setTrimPreview] = useState<{
    trackIndex: number
    clipIndex: number
    sourceRange: TimeRange
  } | null>(null)
  const [snapGuideX, setSnapGuideX] = useState<number | null>(null)

  const timelineZoom = useUiStore((state) => state.timelineZoom)
  const setTimelineZoom = useUiStore((state) => state.setTimelineZoom)
  const timelineScrollX = useUiStore((state) => state.timelineScrollX)
  const timelineScrollY = useUiStore((state) => state.timelineScrollY)
  const setTimelineScroll = useUiStore((state) => state.setTimelineScroll)
  const selection = useUiStore((state) => state.selection)
  const setSelection = useUiStore((state) => state.setSelection)
  const activeTool = useUiStore((state) => state.activeTool)
  const timelineSnapEnabled = useUiStore((state) => state.timelineSnapEnabled)
  const toggleTimelineSnapEnabled = useUiStore((state) => state.toggleTimelineSnapEnabled)
  const timelineSnapStrength = useUiStore((state) => state.timelineSnapStrength)
  const setTimelineSnapStrength = useUiStore((state) => state.setTimelineSnapStrength)

  const currentTime = usePlaybackStore((state) => state.currentTime)
  const setCurrentTime = usePlaybackStore((state) => state.setCurrentTime)
  const duration = usePlaybackStore((state) => state.duration)
  const setDuration = usePlaybackStore((state) => state.setDuration)

  useEffect(() => {
    if (!timelineSnapEnabled) {
      setSnapGuideX(null)
    }
  }, [timelineSnapEnabled])

  const tracks = useMemo(() => {
    if (!timeline) {
      return []
    }
    return timeline.tracks.children.filter(isTrack)
  }, [timeline])

  const timelineRate = useMemo(() => resolveTimelineRate(timeline, tracks), [timeline, tracks])

  const trackLayouts = useMemo(() => buildTrackLayouts(tracks), [tracks])

  const totalDurationSeconds = useMemo(() => {
    let maxDuration = 0
    for (const layout of trackLayouts) {
      if (layout.durationSeconds > maxDuration) {
        maxDuration = layout.durationSeconds
      }
    }
    return maxDuration
  }, [trackLayouts])

  const displayDurationSeconds = Math.max(totalDurationSeconds, MIN_TIMELINE_SECONDS)
  const pixelsPerSecond = BASE_PIXELS_PER_SECOND * timelineZoom
  const timelineWidth = Math.max(MIN_TIMELINE_WIDTH, displayDurationSeconds * pixelsPerSecond)
  const contentWidth = TRACK_LABEL_WIDTH + timelineWidth
  const playheadSeconds = Math.max(0, Math.min(timeToSeconds(currentTime), totalDurationSeconds))
  const playheadX = TRACK_LABEL_WIDTH + playheadSeconds * pixelsPerSecond

  useEffect(() => {
    const nextFrames = Math.round(totalDurationSeconds * timelineRate)
    setDuration(makeRationalTime(nextFrames, timelineRate))
  }, [setDuration, timelineRate, totalDurationSeconds])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    if (Math.abs(viewport.scrollLeft - timelineScrollX) > 1) {
      viewport.scrollLeft = timelineScrollX
    }
    if (Math.abs(viewport.scrollTop - timelineScrollY) > 1) {
      viewport.scrollTop = timelineScrollY
    }
  }, [timelineScrollX, timelineScrollY])

  useEffect(() => {
    const canvas = rulerCanvasRef.current
    if (!canvas) {
      return
    }

    const parent = canvas.parentElement
    if (!parent) {
      return
    }

    const context = canvas.getContext('2d')
    if (!context) {
      return
    }

    const cssWidth = contentWidth
    const cssHeight = parent.clientHeight
    const deviceScale = window.devicePixelRatio || 1

    canvas.width = Math.max(1, Math.floor(cssWidth * deviceScale))
    canvas.height = Math.max(1, Math.floor(cssHeight * deviceScale))
    canvas.style.width = `${cssWidth}px`
    canvas.style.height = `${cssHeight}px`

    context.setTransform(deviceScale, 0, 0, deviceScale, 0, 0)
    context.clearRect(0, 0, cssWidth, cssHeight)

    context.fillStyle = '#09090b'
    context.fillRect(0, 0, cssWidth, cssHeight)

    context.fillStyle = '#111827'
    context.fillRect(0, 0, TRACK_LABEL_WIDTH, cssHeight)

    context.strokeStyle = '#27272a'
    context.beginPath()
    context.moveTo(TRACK_LABEL_WIDTH + 0.5, 0)
    context.lineTo(TRACK_LABEL_WIDTH + 0.5, cssHeight)
    context.moveTo(0, cssHeight - 0.5)
    context.lineTo(cssWidth, cssHeight - 0.5)
    context.stroke()

    const majorTickStepSeconds =
      timelineZoom >= 3 ? 0.5 : timelineZoom >= 1.5 ? 1 : timelineZoom >= 0.75 ? 2 : 5
    const minorTickStepSeconds = majorTickStepSeconds / 4

    context.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace'
    context.textBaseline = 'top'

    for (
      let second = 0;
      second <= displayDurationSeconds + minorTickStepSeconds;
      second += minorTickStepSeconds
    ) {
      const x = TRACK_LABEL_WIDTH + second * pixelsPerSecond
      const roundedX = Math.round(x) + 0.5
      const major = Math.abs((second / majorTickStepSeconds) % 1) < 0.0001

      context.strokeStyle = major ? '#52525b' : '#27272a'
      context.beginPath()
      context.moveTo(roundedX, 0)
      context.lineTo(roundedX, major ? cssHeight : Math.floor(cssHeight * 0.55))
      context.stroke()

      if (major) {
        const labelMinutes = Math.floor(second / 60)
        const labelSeconds = Math.floor(second % 60)
        const label = `${String(labelMinutes).padStart(2, '0')}:${String(labelSeconds).padStart(2, '0')}`
        context.fillStyle = '#a1a1aa'
        context.fillText(label, roundedX + 4, 4)
      }
    }

    context.strokeStyle = '#f43f5e'
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(playheadX + 0.5, 0)
    context.lineTo(playheadX + 0.5, cssHeight)
    context.stroke()
  }, [contentWidth, displayDurationSeconds, pixelsPerSecond, playheadX, timelineZoom])

  const seekFromClientX = useCallback(
    (clientX: number) => {
      const viewport = viewportRef.current
      if (!viewport) {
        return
      }

      const rect = viewport.getBoundingClientRect()
      const xInViewport = clientX - rect.left
      const xInTimeline = xInViewport + viewport.scrollLeft - TRACK_LABEL_WIDTH
      const clampedX = Math.max(0, Math.min(xInTimeline, timelineWidth))
      const seconds = clampedX / pixelsPerSecond
      const clampedSeconds = Math.max(0, Math.min(seconds, totalDurationSeconds))
      setCurrentTime(secondsToTime(clampedSeconds, timelineRate))
    },
    [pixelsPerSecond, setCurrentTime, timelineRate, timelineWidth, totalDurationSeconds],
  )

  useEffect(() => {
    if (!scrubbing) {
      return
    }

    const onMove = (event: MouseEvent) => {
      seekFromClientX(event.clientX)
    }

    const onUp = () => {
      setScrubbing(false)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)

    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [scrubbing, seekFromClientX])

  const handleScrubStart = (clientX: number) => {
    seekFromClientX(clientX)
    setScrubbing(true)
  }

  const extractAssetId = (dataTransfer: DataTransfer): string | null => {
    const assetId = dataTransfer.getData('application/x-auteur-asset-id')
    return assetId || null
  }

  const extractClipPayload = (
    dataTransfer: DataTransfer,
  ): { trackIndex: number; clipIndex: number } | null => {
    const rawPayload = dataTransfer.getData('application/x-auteur-clip')
    if (!rawPayload) {
      return null
    }

    try {
      const parsed = JSON.parse(rawPayload) as { trackIndex?: unknown; clipIndex?: unknown }
      if (
        typeof parsed.trackIndex === 'number' &&
        Number.isInteger(parsed.trackIndex) &&
        parsed.trackIndex >= 0 &&
        typeof parsed.clipIndex === 'number' &&
        Number.isInteger(parsed.clipIndex) &&
        parsed.clipIndex >= 0
      ) {
        return { trackIndex: parsed.trackIndex, clipIndex: parsed.clipIndex }
      }
      return null
    } catch {
      return null
    }
  }

  const acceptsAssetDrop = (dataTransfer: DataTransfer): boolean => {
    if (Array.from(dataTransfer.types).includes('application/x-auteur-asset-id')) {
      return true
    }
    const assetId = extractAssetId(dataTransfer)
    return Boolean(assetId)
  }

  const acceptsClipDrop = (dataTransfer: DataTransfer): boolean => {
    if (Array.from(dataTransfer.types).includes('application/x-auteur-clip')) {
      return true
    }
    return Boolean(extractClipPayload(dataTransfer))
  }

  const computeInsertIndex = (layout: TrackLayout, xInTrackPixels: number): number => {
    const x = Math.max(0, xInTrackPixels)

    for (const visualItem of layout.items) {
      const isTransition = visualItem.item.OTIO_SCHEMA === 'Transition.1'
      const width = isTransition
        ? Math.max(TRANSITION_MIN_WIDTH, visualItem.durationSeconds * pixelsPerSecond * 0.4)
        : Math.max(4, visualItem.durationSeconds * pixelsPerSecond)
      const start = visualItem.startSeconds * pixelsPerSecond
      const midpoint = start + width / 2

      if (x < midpoint) {
        return visualItem.itemIndex
      }
    }

    return layout.track.children.length
  }

  const xForInsertIndex = (layout: TrackLayout, insertIndex: number): number => {
    if (insertIndex <= 0) {
      return 0
    }

    const nextItem = layout.items.find((visualItem) => visualItem.itemIndex === insertIndex)
    if (nextItem) {
      return nextItem.startSeconds * pixelsPerSecond
    }

    return layout.durationSeconds * pixelsPerSecond
  }

  const buildTrackSnapCandidates = useCallback(
    (layout: TrackLayout, includePlayhead: boolean): number[] => {
      const values: number[] = [0, layout.durationSeconds * pixelsPerSecond]

      for (const visualItem of layout.items) {
        if (visualItem.item.OTIO_SCHEMA === 'Transition.1') {
          continue
        }

        const start = visualItem.startSeconds * pixelsPerSecond
        const end = start + visualItem.durationSeconds * pixelsPerSecond
        values.push(start, end)
      }

      if (includePlayhead) {
        values.push(playheadX - TRACK_LABEL_WIDTH)
      }

      return Array.from(new Set(values.map((value) => Math.round(value))))
    },
    [pixelsPerSecond, playheadX],
  )

  const snapTrackX = useCallback(
    (rawTrackX: number, candidates: number[]): { x: number; snapGuideAbsoluteX: number | null } => {
      const bounded = Math.max(0, Math.min(rawTrackX, timelineWidth))

      if (!timelineSnapEnabled) {
        return { x: bounded, snapGuideAbsoluteX: null }
      }

      let best = bounded
      let bestDelta = timelineSnapStrength + 1

      for (const candidate of candidates) {
        const delta = Math.abs(candidate - bounded)
        if (delta < bestDelta) {
          best = candidate
          bestDelta = delta
        }
      }

      if (bestDelta <= timelineSnapStrength) {
        return {
          x: best,
          snapGuideAbsoluteX: TRACK_LABEL_WIDTH + best,
        }
      }

      return { x: bounded, snapGuideAbsoluteX: null }
    },
    [timelineSnapEnabled, timelineSnapStrength, timelineWidth],
  )

  const buildTrimSourceRange = (
    sourceRange: TimeRange,
    edge: TrimEdge,
    deltaFrames: number,
  ): TimeRange => {
    const startValue = sourceRange.start_time.value
    const durationValue = sourceRange.duration.value

    let nextStart = startValue
    let nextDuration = durationValue

    if (edge === 'start') {
      nextStart = startValue + deltaFrames
      nextDuration = durationValue - deltaFrames

      if (nextStart < 0) {
        nextDuration += nextStart
        nextStart = 0
      }
    } else {
      nextDuration = durationValue + deltaFrames
    }

    if (nextDuration < 1) {
      nextDuration = 1
      if (edge === 'start') {
        nextStart = Math.max(0, startValue + (durationValue - 1))
      }
    }

    return {
      OTIO_SCHEMA: 'TimeRange.1',
      start_time: {
        OTIO_SCHEMA: 'RationalTime.1',
        value: nextStart,
        rate: sourceRange.start_time.rate,
      },
      duration: {
        OTIO_SCHEMA: 'RationalTime.1',
        value: nextDuration,
        rate: sourceRange.duration.rate,
      },
    }
  }

  const sourceRangeChanged = (a: TimeRange, b: TimeRange) =>
    a.start_time.value !== b.start_time.value || a.duration.value !== b.duration.value

  const beginTrimDrag = (
    event: ReactMouseEvent,
    trackIndex: number,
    clipIndex: number,
    clip: Clip,
    edge: TrimEdge,
  ) => {
    if (!onTrimClip) {
      return
    }

    event.preventDefault()
    event.stopPropagation()

    setTrimDrag({
      trackIndex,
      clipIndex,
      edge,
      initialClientX: event.clientX,
      clip,
      initialSourceRange: clip.source_range,
    })
    setTrimPreview({
      trackIndex,
      clipIndex,
      sourceRange: clip.source_range,
    })
  }

  useEffect(() => {
    if (!trimDrag || !onTrimClip) {
      return
    }

    const layout = trackLayouts.find((candidate) => candidate.trackIndex === trimDrag.trackIndex)
    const visualItem = layout?.items.find((candidate) => candidate.itemIndex === trimDrag.clipIndex)

    const computeRangeFromClientX = (
      clientX: number,
    ): { range: TimeRange; snapGuideAbsoluteX: number | null } => {
      const deltaPixels = clientX - trimDrag.initialClientX
      let effectiveDeltaPixels = deltaPixels
      let snappedGuideAbsoluteX: number | null = null

      if (layout && visualItem) {
        const clipStartX = visualItem.startSeconds * pixelsPerSecond
        const clipWidth = readDurationSeconds(trimDrag.initialSourceRange.duration) * pixelsPerSecond
        const edgeBaseX = trimDrag.edge === 'start' ? clipStartX : clipStartX + clipWidth
        const edgeTrackX = edgeBaseX + deltaPixels

        const snapCandidates = buildTrackSnapCandidates(layout, true)
        const snapped = snapTrackX(edgeTrackX, snapCandidates)
        if (snapped.snapGuideAbsoluteX !== null) {
          effectiveDeltaPixels = snapped.x - edgeBaseX
          snappedGuideAbsoluteX = snapped.snapGuideAbsoluteX
        }
      }

      const boundedDeltaPixels = Math.max(-timelineWidth, Math.min(timelineWidth, effectiveDeltaPixels))
      const deltaSeconds = boundedDeltaPixels / Math.max(1, pixelsPerSecond)
      const rate = Math.max(1, trimDrag.initialSourceRange.duration.rate)
      const deltaFrames = Math.round(deltaSeconds * rate)

      return {
        range: buildTrimSourceRange(trimDrag.initialSourceRange, trimDrag.edge, deltaFrames),
        snapGuideAbsoluteX: snappedGuideAbsoluteX,
      }
    }

    const onMove = (event: MouseEvent) => {
      const next = computeRangeFromClientX(event.clientX)
      setTrimPreview({
        trackIndex: trimDrag.trackIndex,
        clipIndex: trimDrag.clipIndex,
        sourceRange: next.range,
      })
      setSnapGuideX(next.snapGuideAbsoluteX)
    }

    const onUp = (event: MouseEvent) => {
      const final = computeRangeFromClientX(event.clientX)
      const finalRange = final.range
      if (sourceRangeChanged(trimDrag.initialSourceRange, finalRange)) {
        onTrimClip({
          trackIndex: trimDrag.trackIndex,
          clipIndex: trimDrag.clipIndex,
          newSourceRange: finalRange,
        })
      }

      setTrimDrag(null)
      setTrimPreview(null)
      setSnapGuideX(null)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)

    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [
    buildTrackSnapCandidates,
    onTrimClip,
    pixelsPerSecond,
    snapTrackX,
    timelineWidth,
    trackLayouts,
    trimDrag,
  ])

  const splitClipAtPlayhead = (
    trackIndex: number,
    clipIndex: number,
    visualItem: VisualTrackItem,
    clip: Extract<TrackItem, { OTIO_SCHEMA: 'Clip.1' }>,
  ) => {
    if (!onSplitClip) {
      return
    }

    const clipDurationSeconds = Math.max(0, visualItem.durationSeconds)
    if (clipDurationSeconds <= 0) {
      return
    }

    const localSeconds = playheadSeconds - visualItem.startSeconds
    const frameDurationSeconds = 1 / Math.max(1, clip.source_range.duration.rate)
    const clampedSeconds = Math.max(
      frameDurationSeconds,
      Math.min(clipDurationSeconds - frameDurationSeconds, localSeconds),
    )

    const rate = clip.source_range.duration.rate
    const frameValue = Math.round(clampedSeconds * rate)

    if (frameValue <= 0 || frameValue >= clip.source_range.duration.value) {
      return
    }

    onSplitClip({
      trackIndex,
      clipIndex,
      splitOffset: {
        OTIO_SCHEMA: 'RationalTime.1',
        value: frameValue,
        rate,
      },
    })
  }

  return (
    <section className="shrink-0 border-t border-neutral-800 bg-neutral-900">
      <div className="border-b border-neutral-800 px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-400">Timeline</h2>

          <div className="flex items-center gap-2">
            <span className="text-2xs tabular-nums text-neutral-500">
              {formatTimecode(currentTime)} / {formatTimecode(duration)}
            </span>

            <div className="flex items-center gap-1 rounded border border-neutral-700 bg-neutral-800 p-1">
              <button
                type="button"
                onClick={() => setTimelineZoom(timelineZoom - 0.1)}
                className="rounded p-1 text-neutral-400 transition-colors hover:bg-neutral-700 hover:text-neutral-200"
                aria-label="Zoom out timeline"
              >
                <Minus className="h-3 w-3" />
              </button>
              <input
                type="range"
                min={0.25}
                max={4}
                step={0.05}
                value={timelineZoom}
                onChange={(event) => setTimelineZoom(Number(event.target.value))}
                className="h-4 w-24 accent-accent-500"
              />
              <button
                type="button"
                onClick={() => setTimelineZoom(timelineZoom + 0.1)}
                className="rounded p-1 text-neutral-400 transition-colors hover:bg-neutral-700 hover:text-neutral-200"
                aria-label="Zoom in timeline"
              >
                <Plus className="h-3 w-3" />
              </button>
            </div>

            <span className="text-2xs text-neutral-500">{timelineZoom.toFixed(2)}x</span>

            <div className="flex items-center gap-1 rounded border border-neutral-700 bg-neutral-800 p-1">
              <button
                type="button"
                onClick={toggleTimelineSnapEnabled}
                className={`rounded px-1.5 py-0.5 text-2xs uppercase tracking-wide transition-colors ${
                  timelineSnapEnabled
                    ? 'bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30'
                    : 'bg-neutral-700 text-neutral-400 hover:bg-neutral-600 hover:text-neutral-200'
                }`}
                title="Toggle snapping"
              >
                {timelineSnapEnabled ? 'Snap On' : 'Snap Off'}
              </button>

              <input
                type="range"
                min={2}
                max={40}
                step={1}
                value={timelineSnapStrength}
                onChange={(event) => setTimelineSnapStrength(Number(event.target.value))}
                disabled={!timelineSnapEnabled}
                className="h-4 w-16 accent-emerald-400 disabled:opacity-40"
                title="Snap strength"
              />

              <span className="w-10 text-right text-2xs tabular-nums text-neutral-500">
                {timelineSnapStrength}px
              </span>
            </div>

            <span
              className={`rounded px-1.5 py-0.5 text-2xs uppercase tracking-wide ${
                activeTool === 'razor'
                  ? 'bg-amber-500/20 text-amber-200'
                  : activeTool === 'slip'
                    ? 'bg-sky-500/20 text-sky-200'
                    : 'bg-neutral-800 text-neutral-500'
              }`}
            >
              {activeTool}
            </span>
          </div>
        </div>
      </div>

      <div
        ref={viewportRef}
        className={`max-h-56 overflow-auto select-none ${dragActive ? 'ring-2 ring-accent-400/70' : ''} ${
          activeTool === 'razor' ? 'cursor-crosshair' : ''
        }`}
        onScroll={(event) => {
          const target = event.currentTarget
          setTimelineScroll(target.scrollLeft, target.scrollTop)
        }}
        onDragOver={(event) => {
          const acceptsClip = acceptsClipDrop(event.dataTransfer)
          const acceptsAsset = acceptsAssetDrop(event.dataTransfer)

          if (!acceptsClip && !acceptsAsset) {
            return
          }
          event.preventDefault()
          event.dataTransfer.dropEffect = acceptsClip ? 'move' : 'copy'
          if (acceptsAsset) {
            setSnapGuideX(null)
          }
          if (!dragActive) {
            setDragActive(true)
          }
        }}
        onDragLeave={() => {
          if (dragActive) {
            setDragActive(false)
          }
          if (clipDropIndicator) {
            setClipDropIndicator(null)
          }
          setSnapGuideX(null)
        }}
        onDrop={(event) => {
          const clipPayload = extractClipPayload(event.dataTransfer)
          if (clipPayload) {
            event.preventDefault()
            setDragActive(false)
            setClipDropIndicator(null)
            setSnapGuideX(null)
            return
          }

          if (!onDropAsset) {
            return
          }
          const assetId = extractAssetId(event.dataTransfer)
          if (!assetId) {
            return
          }
          event.preventDefault()
          setDragActive(false)
          setSnapGuideX(null)
          onDropAsset(assetId)
        }}
        onWheel={(event) => {
          if (!event.ctrlKey) {
            return
          }
          event.preventDefault()
          setTimelineZoom(timelineZoom - Math.sign(event.deltaY) * 0.12)
        }}
      >
        <div className="relative" style={{ width: `${contentWidth}px` }}>
          <div
            className="h-10 border-b border-neutral-800 bg-neutral-950/70"
            onMouseDown={(event) => {
              event.preventDefault()
              handleScrubStart(event.clientX)
            }}
          >
            <canvas ref={rulerCanvasRef} className="h-full w-full cursor-ew-resize" />
          </div>

          <div className="pointer-events-none absolute bottom-0 top-10 z-20" style={{ left: `${playheadX}px` }}>
            <div className="h-full w-px bg-rose-500" />
          </div>

          {timelineSnapEnabled && snapGuideX !== null && (
            <div
              className="pointer-events-none absolute bottom-0 top-10 z-30"
              style={{ left: `${snapGuideX}px` }}
            >
              <div className="h-full w-px bg-emerald-400/90 shadow-[0_0_0_1px_rgba(16,185,129,0.35)]" />
            </div>
          )}

          {trackLayouts.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-neutral-500">
              Timeline is empty. Use AI edits or add clips directly from the media panel.
            </div>
          ) : (
            trackLayouts.map((layout) => {
              const trackSelected =
                selection?.type === 'track' && selection.trackIndex === layout.trackIndex

              return (
                <div
                  key={`${layout.trackIndex}-${layout.track.name}`}
                  className="relative h-11 border-b border-neutral-800"
                  onDragOver={(event) => {
                    const clipPayload = extractClipPayload(event.dataTransfer)
                    if (!clipPayload) {
                      return
                    }

                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'move'

                    const rect = event.currentTarget.getBoundingClientRect()
                    const xInTrack = event.clientX - rect.left - TRACK_LABEL_WIDTH
                    const snapCandidates = buildTrackSnapCandidates(layout, true)
                    const snapped = snapTrackX(xInTrack, snapCandidates)
                    const insertIndex = computeInsertIndex(layout, snapped.x)
                    const indicatorX = xForInsertIndex(layout, insertIndex)

                    setClipDropIndicator({
                      trackIndex: layout.trackIndex,
                      insertIndex,
                      x: indicatorX,
                    })
                    setSnapGuideX(snapped.snapGuideAbsoluteX)
                  }}
                  onDrop={(event) => {
                    const clipPayload = extractClipPayload(event.dataTransfer)
                    if (!clipPayload || !onMoveClip) {
                      return
                    }

                    event.preventDefault()
                    event.stopPropagation()
                    setDragActive(false)

                    const rect = event.currentTarget.getBoundingClientRect()
                    const xInTrack = event.clientX - rect.left - TRACK_LABEL_WIDTH
                    const snapCandidates = buildTrackSnapCandidates(layout, true)
                    const snapped = snapTrackX(xInTrack, snapCandidates)
                    const insertIndex = computeInsertIndex(layout, snapped.x)

                    setClipDropIndicator(null)
                    setSnapGuideX(null)

                    if (
                      clipPayload.trackIndex === layout.trackIndex &&
                      clipPayload.clipIndex === insertIndex
                    ) {
                      return
                    }

                    onMoveClip({
                      fromTrackIndex: clipPayload.trackIndex,
                      clipIndex: clipPayload.clipIndex,
                      toTrackIndex: layout.trackIndex,
                      toClipIndex: insertIndex,
                    })
                  }}
                  onDragLeave={(event) => {
                    const nextTarget = event.relatedTarget
                    if (nextTarget && event.currentTarget.contains(nextTarget as Node)) {
                      return
                    }
                    if (clipDropIndicator?.trackIndex === layout.trackIndex) {
                      setClipDropIndicator(null)
                    }
                    setSnapGuideX(null)
                  }}
                  onMouseDown={(event) => {
                    if (event.button !== 0) {
                      return
                    }
                    handleScrubStart(event.clientX)
                  }}
                >
                  <button
                    type="button"
                    onMouseDown={(event) => {
                      event.stopPropagation()
                    }}
                    onClick={() => setSelection({ type: 'track', trackIndex: layout.trackIndex })}
                    className={`absolute bottom-0 left-0 top-0 z-10 w-[156px] border-r border-neutral-800 px-2 text-left transition-colors ${
                      trackSelected
                        ? 'bg-accent-500/20 text-accent-200'
                        : 'bg-neutral-950 text-neutral-300 hover:bg-neutral-850'
                    }`}
                  >
                    <p className="truncate text-xs font-medium">{layout.track.name || `Track ${layout.trackIndex + 1}`}</p>
                    <p className="text-2xs text-neutral-500">{layout.track.kind}</p>
                  </button>

                  <div className="absolute inset-y-0 left-[156px] right-0 bg-neutral-900/70">
                    {clipDropIndicator?.trackIndex === layout.trackIndex && (
                      <div
                        className="pointer-events-none absolute inset-y-0 z-20"
                        style={{ left: `${clipDropIndicator.x}px` }}
                      >
                        <div className="h-full w-[2px] bg-accent-400 shadow-[0_0_0_1px_rgba(99,102,241,0.35)]" />
                      </div>
                    )}

                    {layout.items.map((visualItem) => {
                      const left = visualItem.startSeconds * pixelsPerSecond
                      const isTransition = visualItem.item.OTIO_SCHEMA === 'Transition.1'

                      const clipItem =
                        visualItem.item.OTIO_SCHEMA === 'Clip.1' ? visualItem.item : null
                      const previewSourceRange =
                        trimPreview &&
                        trimPreview.trackIndex === layout.trackIndex &&
                        trimPreview.clipIndex === visualItem.itemIndex
                          ? trimPreview.sourceRange
                          : null
                      const itemDurationSeconds =
                        clipItem && previewSourceRange
                          ? readDurationSeconds(previewSourceRange.duration)
                          : visualItem.durationSeconds

                      const width = isTransition
                        ? Math.max(
                            TRANSITION_MIN_WIDTH,
                            visualItem.durationSeconds * pixelsPerSecond * 0.4,
                          )
                        : Math.max(4, itemDurationSeconds * pixelsPerSecond)

                      const itemSelectionType =
                        visualItem.item.OTIO_SCHEMA === 'Clip.1'
                          ? 'clip'
                          : visualItem.item.OTIO_SCHEMA === 'Gap.1'
                            ? 'gap'
                            : visualItem.item.OTIO_SCHEMA === 'Transition.1'
                              ? 'transition'
                              : null

                      const itemSelected =
                        itemSelectionType &&
                        selection?.type === itemSelectionType &&
                        selection.trackIndex === layout.trackIndex &&
                        selection.itemIndex === visualItem.itemIndex

                      const baseClass = isTransition
                        ? 'bg-amber-500/70 border-amber-300/60 rotate-45'
                        : visualItem.item.OTIO_SCHEMA === 'Gap.1'
                          ? 'border border-dashed border-neutral-600 bg-transparent'
                          : visualItem.item.OTIO_SCHEMA === 'Stack.1'
                            ? 'border border-purple-400/40 bg-purple-500/20'
                            : 'border border-sky-400/30 bg-sky-500/25'

                      return (
                        <button
                          key={`${layout.trackIndex}-${visualItem.itemIndex}-${visualItem.item.OTIO_SCHEMA}`}
                          type="button"
                          draggable={visualItem.item.OTIO_SCHEMA === 'Clip.1'}
                          onDragStart={(event) => {
                            if (visualItem.item.OTIO_SCHEMA !== 'Clip.1') {
                              event.preventDefault()
                              return
                            }
                            event.dataTransfer.setData(
                              'application/x-auteur-clip',
                              JSON.stringify({
                                trackIndex: layout.trackIndex,
                                clipIndex: visualItem.itemIndex,
                              }),
                            )
                            event.dataTransfer.effectAllowed = 'move'
                          }}
                          onDragEnd={() => {
                            setClipDropIndicator(null)
                            setDragActive(false)
                          }}
                          onMouseDown={(event) => {
                            event.stopPropagation()
                          }}
                          onClick={(event) => {
                            event.stopPropagation()

                            if (clipItem && activeTool === 'razor' && onSplitClip) {
                              const durationFrames = clipItem.source_range.duration.value
                              if (durationFrames > 1) {
                                const rect = event.currentTarget.getBoundingClientRect()
                                const ratio =
                                  rect.width > 0
                                    ? (event.clientX - rect.left) / Math.max(1, rect.width)
                                    : 0
                                const rawSplitFrames = Math.round(ratio * durationFrames)
                                const splitFrames = Math.max(
                                  1,
                                  Math.min(durationFrames - 1, rawSplitFrames),
                                )

                                if (splitFrames > 0 && splitFrames < durationFrames) {
                                  onSplitClip({
                                    trackIndex: layout.trackIndex,
                                    clipIndex: visualItem.itemIndex,
                                    splitOffset: {
                                      OTIO_SCHEMA: 'RationalTime.1',
                                      value: splitFrames,
                                      rate: clipItem.source_range.duration.rate,
                                    },
                                  })
                                }
                              }
                              return
                            }

                            if (!itemSelectionType) {
                              return
                            }
                            setSelection({
                              type: itemSelectionType,
                              trackIndex: layout.trackIndex,
                              itemIndex: visualItem.itemIndex,
                            })
                          }}
                          className={`group absolute top-1 h-9 overflow-hidden rounded text-left text-2xs text-neutral-200 transition-colors ${baseClass} ${
                            itemSelected ? 'ring-2 ring-accent-400' : 'hover:brightness-110'
                          } ${
                            clipItem && activeTool === 'razor' ? 'cursor-cell hover:brightness-125' : ''
                          }`}
                          style={{
                            left: `${isTransition ? left - width / 2 : left}px`,
                            width: `${width}px`,
                          }}
                          title={`${visualItem.displayLabel} (${itemDurationSeconds.toFixed(2)}s)`}
                        >
                          {clipItem && onTrimClip && (
                            <>
                              <span
                                onMouseDown={(event) =>
                                  beginTrimDrag(
                                    event,
                                    layout.trackIndex,
                                    visualItem.itemIndex,
                                    clipItem,
                                    'start',
                                  )
                                }
                                className={`absolute inset-y-0 left-0 z-20 w-1.5 cursor-ew-resize bg-accent-300/50 transition-opacity ${
                                  itemSelected ||
                                  (trimDrag?.trackIndex === layout.trackIndex &&
                                    trimDrag?.clipIndex === visualItem.itemIndex)
                                    ? 'opacity-100'
                                    : 'opacity-0 group-hover:opacity-100'
                                }`}
                                title="Drag to trim in"
                              />
                              <span
                                onMouseDown={(event) =>
                                  beginTrimDrag(
                                    event,
                                    layout.trackIndex,
                                    visualItem.itemIndex,
                                    clipItem,
                                    'end',
                                  )
                                }
                                className={`absolute inset-y-0 right-0 z-20 w-1.5 cursor-ew-resize bg-accent-300/50 transition-opacity ${
                                  itemSelected ||
                                  (trimDrag?.trackIndex === layout.trackIndex &&
                                    trimDrag?.clipIndex === visualItem.itemIndex)
                                    ? 'opacity-100'
                                    : 'opacity-0 group-hover:opacity-100'
                                }`}
                                title="Drag to trim out"
                              />
                            </>
                          )}

                          {itemSelected && clipItem && onSplitClip && (
                            <span
                              role="button"
                              tabIndex={0}
                              onMouseDown={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                              }}
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                splitClipAtPlayhead(
                                  layout.trackIndex,
                                  visualItem.itemIndex,
                                  visualItem,
                                  clipItem,
                                )
                              }}
                              onKeyDown={(event) => {
                                if (event.key !== 'Enter' && event.key !== ' ') {
                                  return
                                }
                                event.preventDefault()
                                event.stopPropagation()
                                splitClipAtPlayhead(
                                  layout.trackIndex,
                                  visualItem.itemIndex,
                                  visualItem,
                                  clipItem,
                                )
                              }}
                              className="absolute left-1/2 top-0.5 z-20 -translate-x-1/2 rounded border border-amber-400/50 bg-amber-500/20 px-1 text-[10px] text-amber-100 hover:bg-amber-500/30"
                              title="Split clip at playhead"
                            >
                              Split
                            </span>
                          )}

                          {!isTransition && (
                            <span className="block truncate px-2 py-1">
                              {visualItem.displayLabel}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </section>
  )
}

export default TimelinePanel
