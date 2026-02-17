import { useEffect } from 'react'
import { DEFAULT_TIMELINE_RATE, makeRationalTime } from '../lib/timeUtils'
import { usePlaybackStore } from '../stores/playbackStore'
import { useUiStore } from '../stores/uiStore'
import type { Clip } from '../lib/timelineTypes'

type SelectedClipContext = {
  trackIndex: number
  clipIndex: number
  clip: Clip
  startSeconds: number
  durationSeconds: number
} | null

type SplitPayload = {
  trackIndex: number
  clipIndex: number
  splitOffset: { OTIO_SCHEMA: 'RationalTime.1'; value: number; rate: number }
}

type UseEditorKeyboardOptions = {
  selectedClipContext: SelectedClipContext
  onSplitClip: (payload: SplitPayload) => void
  onDeleteSelection: () => void
}

const useEditorKeyboard = ({
  selectedClipContext,
  onSplitClip,
  onDeleteSelection,
}: UseEditorKeyboardOptions) => {
  const playbackCurrentTime = usePlaybackStore((state) => state.currentTime)
  const playbackDuration = usePlaybackStore((state) => state.duration)
  const setPlaybackCurrentTime = usePlaybackStore((state) => state.setCurrentTime)
  const seekPlaybackFrames = usePlaybackStore((state) => state.seekFrames)
  const seekPlaybackSeconds = usePlaybackStore((state) => state.seekSeconds)
  const togglePlayback = usePlaybackStore((state) => state.togglePlayback)
  const setTimelineZoom = useUiStore((state) => state.setTimelineZoom)
  const timelineZoom = useUiStore((state) => state.timelineZoom)
  const setActiveTool = useUiStore((state) => state.setActiveTool)

  useEffect(() => {
    const isTypingTarget = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) {
        return false
      }

      const tag = target.tagName.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        return true
      }

      return target.isContentEditable
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) {
        return
      }

      if (event.code === 'Space') {
        event.preventDefault()
        togglePlayback()
        return
      }

      if (event.code === 'ArrowLeft') {
        event.preventDefault()
        if (event.shiftKey) {
          seekPlaybackSeconds(-1)
        } else {
          seekPlaybackFrames(-1)
        }
        return
      }

      if (event.code === 'ArrowRight') {
        event.preventDefault()
        if (event.shiftKey) {
          seekPlaybackSeconds(1)
        } else {
          seekPlaybackFrames(1)
        }
        return
      }

      if (event.code === 'Home') {
        event.preventDefault()
        setPlaybackCurrentTime(makeRationalTime(0, playbackCurrentTime.rate || DEFAULT_TIMELINE_RATE))
        return
      }

      if (event.code === 'End') {
        event.preventDefault()
        setPlaybackCurrentTime(playbackDuration)
        return
      }

      if ((event.ctrlKey || event.metaKey) && (event.key === '=' || event.key === '+')) {
        event.preventDefault()
        setTimelineZoom(timelineZoom + 0.1)
        return
      }

      if ((event.ctrlKey || event.metaKey) && event.key === '-') {
        event.preventDefault()
        setTimelineZoom(timelineZoom - 0.1)
        return
      }

      if (event.key.toLowerCase() === 'v') {
        event.preventDefault()
        setActiveTool('select')
        return
      }

      if (event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setActiveTool('razor')
        return
      }

      if (event.key.toLowerCase() === 'y') {
        event.preventDefault()
        setActiveTool('slip')
        return
      }

      if (!event.ctrlKey && !event.metaKey && event.key.toLowerCase() === 's' && selectedClipContext) {
        event.preventDefault()
        const rate = selectedClipContext.clip.source_range.duration.rate
        const playheadSeconds =
          playbackCurrentTime.rate > 0
            ? playbackCurrentTime.value / playbackCurrentTime.rate
            : 0
        const offsetSeconds = playheadSeconds - selectedClipContext.startSeconds
        const splitFrames = Math.round(offsetSeconds * rate)

        if (splitFrames > 0 && splitFrames < selectedClipContext.clip.source_range.duration.value) {
          onSplitClip({
            trackIndex: selectedClipContext.trackIndex,
            clipIndex: selectedClipContext.clipIndex,
            splitOffset: {
              OTIO_SCHEMA: 'RationalTime.1',
              value: splitFrames,
              rate,
            },
          })
        }
        return
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault()
        onDeleteSelection()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [
    onDeleteSelection,
    onSplitClip,
    playbackCurrentTime,
    playbackDuration,
    seekPlaybackFrames,
    seekPlaybackSeconds,
    selectedClipContext,
    setActiveTool,
    setPlaybackCurrentTime,
    setTimelineZoom,
    timelineZoom,
    togglePlayback,
  ])
}

export default useEditorKeyboard
