import type { RationalTime, TimeRange } from './timelineTypes'

export const DEFAULT_TIMELINE_RATE = 24

export const makeRationalTime = (value: number, rate: number = DEFAULT_TIMELINE_RATE): RationalTime => ({
  OTIO_SCHEMA: 'RationalTime.1',
  value,
  rate,
})

export const makeTimeRange = (startFrames: number, durationFrames: number, rate: number = DEFAULT_TIMELINE_RATE): TimeRange => ({
  OTIO_SCHEMA: 'TimeRange.1',
  start_time: makeRationalTime(startFrames, rate),
  duration: makeRationalTime(durationFrames, rate),
})

export const timeToSeconds = (time: RationalTime): number => {
  if (time.rate <= 0) {
    return 0
  }
  return time.value / time.rate
}

export const secondsToTime = (seconds: number, rate: number = DEFAULT_TIMELINE_RATE): RationalTime =>
  makeRationalTime(seconds * rate, rate)

export const timeToFrames = (time: RationalTime, targetRate?: number): number => {
  if (!targetRate || targetRate === time.rate) {
    return time.value
  }
  return (time.value * targetRate) / time.rate
}

export const timeToMilliseconds = (time: RationalTime): number => timeToSeconds(time) * 1000

export const millisecondsToTime = (milliseconds: number, rate: number = DEFAULT_TIMELINE_RATE): RationalTime =>
  makeRationalTime((milliseconds / 1000) * rate, rate)

export const rescaleTime = (time: RationalTime, newRate: number): RationalTime => {
  if (newRate <= 0) {
    return makeRationalTime(time.value, time.rate)
  }
  if (time.rate === newRate) {
    return makeRationalTime(time.value, time.rate)
  }
  return makeRationalTime((time.value * newRate) / time.rate, newRate)
}

export const addTimes = (a: RationalTime, b: RationalTime): RationalTime => {
  if (a.rate === b.rate) {
    return makeRationalTime(a.value + b.value, a.rate)
  }
  const bScaled = rescaleTime(b, a.rate)
  return makeRationalTime(a.value + bScaled.value, a.rate)
}

export const subtractTimes = (a: RationalTime, b: RationalTime): RationalTime => {
  if (a.rate === b.rate) {
    return makeRationalTime(a.value - b.value, a.rate)
  }
  const bScaled = rescaleTime(b, a.rate)
  return makeRationalTime(a.value - bScaled.value, a.rate)
}

export const rangeEndExclusive = (range: TimeRange): RationalTime =>
  addTimes(range.start_time, range.duration)

export const clampTime = (time: RationalTime, min: RationalTime, max: RationalTime): RationalTime => {
  const timeSeconds = timeToSeconds(time)
  const minSeconds = timeToSeconds(min)
  const maxSeconds = timeToSeconds(max)
  if (timeSeconds < minSeconds) {
    return rescaleTime(min, time.rate)
  }
  if (timeSeconds > maxSeconds) {
    return rescaleTime(max, time.rate)
  }
  return time
}

export const formatTimecode = (time: RationalTime): string => {
  const fps = Math.max(1, Math.round(time.rate))
  const totalFrames = Math.max(0, Math.round(timeToFrames(time, fps)))
  const frames = totalFrames % fps
  const totalSeconds = Math.floor(totalFrames / fps)
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  const minutes = totalMinutes % 60
  const hours = Math.floor(totalMinutes / 60)

  return [hours, minutes, seconds, frames]
    .map((segment) => String(segment).padStart(2, '0'))
    .join(':')
}

export const compareTimes = (a: RationalTime, b: RationalTime): number => {
  const aSeconds = timeToSeconds(a)
  const bSeconds = timeToSeconds(b)
  if (aSeconds < bSeconds) {
    return -1
  }
  if (aSeconds > bSeconds) {
    return 1
  }
  return 0
}
