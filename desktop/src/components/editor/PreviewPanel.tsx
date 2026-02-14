import { Film, Maximize2, Pause, Play, SkipBack, SkipForward, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'

import {
  DEFAULT_TIMELINE_RATE,
  formatTimecode,
  makeRationalTime,
  secondsToTime,
  timeToSeconds,
} from '../../lib/timeUtils'
import { usePlaybackStore } from '../../stores/playbackStore'

type PreviewPanelProps = {
  previewUrl: string | null
  previewKey: number
}

const PreviewPanel = ({ previewUrl, previewKey }: PreviewPanelProps) => {
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const currentTime = usePlaybackStore((state) => state.currentTime)
  const duration = usePlaybackStore((state) => state.duration)
  const playing = usePlaybackStore((state) => state.playing)
  const muted = usePlaybackStore((state) => state.muted)
  const volume = usePlaybackStore((state) => state.volume)
  const setCurrentTime = usePlaybackStore((state) => state.setCurrentTime)
  const setDuration = usePlaybackStore((state) => state.setDuration)
  const seekSeconds = usePlaybackStore((state) => state.seekSeconds)
  const togglePlayback = usePlaybackStore((state) => state.togglePlayback)
  const setVolume = usePlaybackStore((state) => state.setVolume)
  const toggleMuted = usePlaybackStore((state) => state.toggleMuted)

  const currentSeconds = Math.max(0, timeToSeconds(currentTime))
  const durationSeconds = Math.max(0, timeToSeconds(duration))
  const progressPercent = useMemo(() => {
    if (durationSeconds <= 0) {
      return 0
    }
    return Math.max(0, Math.min(100, (currentSeconds / durationSeconds) * 100))
  }, [currentSeconds, durationSeconds])

  useEffect(() => {
    if (!previewUrl) {
      return
    }

    const video = videoRef.current
    if (!video) {
      return
    }

    const handleLoadedMetadata = () => {
      const rate = currentTime.rate > 0 ? currentTime.rate : DEFAULT_TIMELINE_RATE
      if (Number.isFinite(video.duration) && video.duration > 0) {
        setDuration(makeRationalTime(video.duration * rate, rate))
      }
      video.volume = volume
      video.muted = muted
    }

    const handleTimeUpdate = () => {
      const rate = currentTime.rate > 0 ? currentTime.rate : DEFAULT_TIMELINE_RATE
      setCurrentTime(secondsToTime(video.currentTime, rate))
    }

    video.addEventListener('loadedmetadata', handleLoadedMetadata)
    video.addEventListener('timeupdate', handleTimeUpdate)

    handleLoadedMetadata()

    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata)
      video.removeEventListener('timeupdate', handleTimeUpdate)
    }
  }, [currentTime.rate, muted, previewKey, previewUrl, setCurrentTime, setDuration, volume])

  useEffect(() => {
    if (!previewUrl) {
      return
    }

    const video = videoRef.current
    if (!video) {
      return
    }

    if (Math.abs(video.currentTime - currentSeconds) > 0.05) {
      video.currentTime = currentSeconds
    }
  }, [currentSeconds, previewKey, previewUrl])

  useEffect(() => {
    if (!previewUrl) {
      return
    }

    const video = videoRef.current
    if (!video) {
      return
    }

    if (playing) {
      const promise = video.play()
      if (promise) {
        promise.catch(() => {})
      }
      return
    }

    video.pause()
  }, [playing, previewKey, previewUrl])

  useEffect(() => {
    const video = videoRef.current
    if (!video) {
      return
    }
    video.volume = volume
    video.muted = muted
  }, [muted, volume])

  const seekToProgressPosition = (clientX: number, target: HTMLElement) => {
    if (durationSeconds <= 0) {
      return
    }

    const rect = target.getBoundingClientRect()
    const ratio = (clientX - rect.left) / Math.max(1, rect.width)
    const boundedRatio = Math.max(0, Math.min(1, ratio))
    const targetSeconds = durationSeconds * boundedRatio
    setCurrentTime(secondsToTime(targetSeconds, currentTime.rate || DEFAULT_TIMELINE_RATE))
  }

  return (
    <div className="flex flex-1 flex-col border-r border-neutral-800 bg-neutral-900">
      <div className="flex flex-1 items-center justify-center bg-neutral-950/50 p-4">
        <div className="relative flex h-full max-h-full w-full max-w-full items-center justify-center">
          {previewUrl ? (
            <video
              ref={videoRef}
              key={previewKey}
              src={previewUrl}
              className="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
            />
          ) : (
            <div className="flex h-full min-h-0 w-full flex-col items-center justify-center p-4">
              <div className="flex aspect-video max-h-full w-full max-w-2xl flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-neutral-600 bg-neutral-900/80">
                <Film className="h-12 w-12 shrink-0 text-neutral-500" />
                <span className="text-sm text-neutral-400">No preview available</span>
                <span className="text-xs text-neutral-500">
                  Export or render a preview to see it here
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-neutral-800 bg-neutral-900 px-4 py-3">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => seekSeconds(-1)}
              className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
            >
              <SkipBack className="h-4 w-4" />
            </button>

            <button
              type="button"
              onClick={togglePlayback}
              className="rounded-lg bg-neutral-800 p-2 text-neutral-200 transition-colors hover:bg-neutral-700"
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>

            <button
              type="button"
              onClick={() => seekSeconds(1)}
              className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
            >
              <SkipForward className="h-4 w-4" />
            </button>
          </div>

          <span className="w-24 text-xs tabular-nums text-neutral-500">{formatTimecode(currentTime)}</span>

          <div className="mx-2 flex-1">
            <button
              type="button"
              onClick={(event) => seekToProgressPosition(event.clientX, event.currentTarget)}
              className="h-1 w-full cursor-pointer overflow-hidden rounded-full bg-neutral-800 text-left transition-all hover:h-1.5"
            >
              <span
                className="block h-full rounded-full bg-accent-500"
                style={{ width: `${progressPercent}%` }}
              />
            </button>
          </div>

          <span className="w-24 text-right text-xs tabular-nums text-neutral-500">
            {formatTimecode(duration)}
          </span>

          <div className="ml-2 flex items-center gap-2">
            <button
              type="button"
              onClick={toggleMuted}
              className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
            >
              {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
            </button>

            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={volume}
              onChange={(event) => setVolume(Number(event.target.value))}
              className="h-4 w-20 accent-accent-500"
            />

            <button
              type="button"
              onClick={() => {
                const video = videoRef.current
                if (!video || typeof video.requestFullscreen !== 'function') {
                  return
                }
                video.requestFullscreen().catch(() => {})
              }}
              className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PreviewPanel
