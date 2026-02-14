import { create } from 'zustand'

import {
  DEFAULT_TIMELINE_RATE,
  addTimes,
  clampTime,
  makeRationalTime,
  subtractTimes,
} from '../lib/timeUtils'
import type { RationalTime } from '../lib/timelineTypes'

export type LoopRange = {
  inPoint: RationalTime
  outPoint: RationalTime
}

export type PlaybackStoreState = {
  currentTime: RationalTime
  duration: RationalTime
  playing: boolean
  playbackRate: number
  volume: number
  muted: boolean
  loopRange: LoopRange | null
  setDuration: (duration: RationalTime) => void
  setCurrentTime: (time: RationalTime) => void
  seekFrames: (frames: number) => void
  seekSeconds: (seconds: number) => void
  play: () => void
  pause: () => void
  togglePlayback: () => void
  setPlaybackRate: (rate: number) => void
  setVolume: (volume: number) => void
  setMuted: (muted: boolean) => void
  toggleMuted: () => void
  setLoopRange: (loopRange: LoopRange | null) => void
  clear: () => void
}

const DEFAULT_TIME = makeRationalTime(0, DEFAULT_TIMELINE_RATE)

export const usePlaybackStore = create<PlaybackStoreState>((set, get) => ({
  currentTime: DEFAULT_TIME,
  duration: DEFAULT_TIME,
  playing: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  loopRange: null,

  setDuration: (duration) => {
    set((state) => ({
      duration,
      currentTime: clampTime(state.currentTime, makeRationalTime(0, duration.rate), duration),
    }))
  },

  setCurrentTime: (time) => {
    const { duration } = get()
    const bounded = clampTime(time, makeRationalTime(0, duration.rate), duration)
    set({ currentTime: bounded })
  },

  seekFrames: (frames) => {
    const { currentTime, duration } = get()
    const delta = makeRationalTime(frames, currentTime.rate)
    const nextTime = addTimes(currentTime, delta)
    set({ currentTime: clampTime(nextTime, makeRationalTime(0, duration.rate), duration) })
  },

  seekSeconds: (seconds) => {
    const { currentTime, duration } = get()
    const delta = makeRationalTime(seconds * currentTime.rate, currentTime.rate)
    const nextTime = addTimes(currentTime, delta)
    set({ currentTime: clampTime(nextTime, makeRationalTime(0, duration.rate), duration) })
  },

  play: () => set({ playing: true }),

  pause: () => set({ playing: false }),

  togglePlayback: () => set((state) => ({ playing: !state.playing })),

  setPlaybackRate: (rate) => {
    const normalized = Number.isFinite(rate) && rate > 0 ? rate : 1
    set({ playbackRate: normalized })
  },

  setVolume: (volume) => {
    const normalized = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 1
    set({ volume: normalized })
  },

  setMuted: (muted) => set({ muted }),

  toggleMuted: () => set((state) => ({ muted: !state.muted })),

  setLoopRange: (loopRange) => {
    if (!loopRange) {
      set({ loopRange: null })
      return
    }

    const ordered =
      loopRange.inPoint.value <= loopRange.outPoint.value
        ? loopRange
        : {
            inPoint: loopRange.outPoint,
            outPoint: loopRange.inPoint,
          }

    set({ loopRange: ordered })
  },

  clear: () => {
    set({
      currentTime: DEFAULT_TIME,
      duration: DEFAULT_TIME,
      playing: false,
      playbackRate: 1,
      volume: 1,
      muted: false,
      loopRange: null,
    })
  },
}))

export const advancePlaybackFrame = (frames: number) => {
  const state = usePlaybackStore.getState()
  const delta = makeRationalTime(frames, state.currentTime.rate)
  const nextTime = addTimes(state.currentTime, delta)

  if (state.loopRange) {
    const wouldPassLoopEnd = nextTime.value > state.loopRange.outPoint.value
    if (wouldPassLoopEnd) {
      usePlaybackStore.setState({ currentTime: state.loopRange.inPoint })
      return
    }
  }

  const bounded = clampTime(nextTime, makeRationalTime(0, state.duration.rate), state.duration)
  usePlaybackStore.setState({ currentTime: bounded })
}

export const rewindPlaybackFrame = (frames: number) => {
  const state = usePlaybackStore.getState()
  const delta = makeRationalTime(frames, state.currentTime.rate)
  const nextTime = subtractTimes(state.currentTime, delta)
  const bounded = clampTime(nextTime, makeRationalTime(0, state.duration.rate), state.duration)
  usePlaybackStore.setState({ currentTime: bounded })
}
