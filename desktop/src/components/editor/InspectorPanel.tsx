import { ChevronLeft, ChevronRight, SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { TRANSITION_TYPES } from '../../lib/timelineTypes'
import type {
  Clip,
  RationalTime,
  TimeRange,
  Timeline,
  Track,
  TrackItem,
  Transition,
  TransitionType,
} from '../../lib/timelineTypes'
import type { TimelineSelection } from '../../stores/uiStore'

type InspectorPanelProps = {
  isOpen: boolean
  onToggle: () => void
  timeline: Timeline | null
  selection: TimelineSelection
  saving?: boolean
  onRenameTrack: (trackIndex: number, newName: string) => void
  onTrimClip: (payload: {
    trackIndex: number
    clipIndex: number
    newSourceRange: TimeRange
  }) => void
  onSlipClip: (payload: {
    trackIndex: number
    clipIndex: number
    offset: RationalTime
  }) => void
  onSplitClip: (payload: {
    trackIndex: number
    clipIndex: number
    splitOffset: RationalTime
  }) => void
  onAddClipEffect: (payload: {
    trackIndex: number
    clipIndex: number
    effectName: string
  }) => void
  onRemoveClipEffect: (payload: {
    trackIndex: number
    clipIndex: number
    effectIndex: number
  }) => void
  onModifyTransition: (payload: {
    trackIndex: number
    transitionIndex: number
    transitionType: TransitionType
    inOffset: RationalTime
    outOffset: RationalTime
  }) => void
}

const isTrack = (value: Track | { OTIO_SCHEMA: string }): value is Track =>
  value.OTIO_SCHEMA === 'Track.1'

const toInteger = (value: string, fallback: number) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return fallback
  }
  return Math.round(parsed)
}

const clipAtSelection = (track: Track | null, selection: TimelineSelection): Clip | null => {
  if (!track || selection?.type !== 'clip') {
    return null
  }

  const item = track.children[selection.itemIndex] as TrackItem | undefined
  return item?.OTIO_SCHEMA === 'Clip.1' ? item : null
}

const transitionAtSelection = (
  track: Track | null,
  selection: TimelineSelection,
): Transition | null => {
  if (!track || selection?.type !== 'transition') {
    return null
  }

  const item = track.children[selection.itemIndex] as TrackItem | undefined
  return item?.OTIO_SCHEMA === 'Transition.1' ? item : null
}

const InspectorPanel = ({
  isOpen,
  onToggle,
  timeline,
  selection,
  saving,
  onRenameTrack,
  onTrimClip,
  onSlipClip,
  onSplitClip,
  onAddClipEffect,
  onRemoveClipEffect,
  onModifyTransition,
}: InspectorPanelProps) => {
  const tracks = useMemo(() => {
    if (!timeline) {
      return []
    }
    return timeline.tracks.children.filter(isTrack)
  }, [timeline])

  const selectedTrack =
    selection && 'trackIndex' in selection ? tracks[selection.trackIndex] ?? null : null
  const selectedClip = clipAtSelection(selectedTrack, selection)
  const selectedTransition = transitionAtSelection(selectedTrack, selection)

  const [trackNameDraft, setTrackNameDraft] = useState('')

  const [clipStartFramesDraft, setClipStartFramesDraft] = useState('0')
  const [clipDurationFramesDraft, setClipDurationFramesDraft] = useState('1')
  const [clipSlipFramesDraft, setClipSlipFramesDraft] = useState('0')
  const [splitFramesDraft, setSplitFramesDraft] = useState('1')
  const [newEffectName, setNewEffectName] = useState('Blur')

  const [transitionTypeDraft, setTransitionTypeDraft] = useState<TransitionType>('SMPTE_Dissolve')
  const [transitionInFramesDraft, setTransitionInFramesDraft] = useState('1')
  const [transitionOutFramesDraft, setTransitionOutFramesDraft] = useState('1')

  useEffect(() => {
    if (selectedTrack) {
      setTrackNameDraft(selectedTrack.name)
      return
    }
    setTrackNameDraft('')
  }, [selectedTrack])

  useEffect(() => {
    if (!selectedClip) {
      setClipStartFramesDraft('0')
      setClipDurationFramesDraft('1')
      setClipSlipFramesDraft('0')
      setSplitFramesDraft('1')
      return
    }

    setClipStartFramesDraft(String(Math.round(selectedClip.source_range.start_time.value)))
    const durationFrames = Math.max(1, Math.round(selectedClip.source_range.duration.value))
    setClipDurationFramesDraft(String(durationFrames))
    setClipSlipFramesDraft('0')
    setSplitFramesDraft(String(Math.max(1, Math.round(durationFrames / 2))))
    setNewEffectName('Blur')
  }, [selectedClip])

  useEffect(() => {
    if (!selectedTransition) {
      setTransitionTypeDraft('SMPTE_Dissolve')
      setTransitionInFramesDraft('1')
      setTransitionOutFramesDraft('1')
      return
    }

    setTransitionTypeDraft(selectedTransition.transition_type)
    setTransitionInFramesDraft(String(Math.max(1, Math.round(selectedTransition.in_offset.value))))
    setTransitionOutFramesDraft(String(Math.max(1, Math.round(selectedTransition.out_offset.value))))
  }, [selectedTransition])

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="flex h-24 w-6 items-center justify-center self-center rounded-l-lg border border-r-0 border-neutral-700 bg-neutral-800 text-neutral-400 transition-colors hover:bg-neutral-700 hover:text-neutral-200"
        title="Open inspector"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
    )
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col border-l border-neutral-800 bg-neutral-900">
      <div className="flex items-center justify-between border-b border-neutral-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-accent-400" />
          <span className="text-sm font-medium text-neutral-200">Inspector</span>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-1 text-neutral-500 transition-colors hover:bg-neutral-800 hover:text-neutral-300"
          title="Close inspector"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-auto p-3 scrollbar-thin">
        {!selection && (
          <div className="rounded border border-neutral-800 bg-neutral-850 px-3 py-2 text-xs text-neutral-500">
            Select a track or clip on the timeline to edit properties.
          </div>
        )}

        {selection?.type === 'track' && selectedTrack && (
          <section className="space-y-3 rounded border border-neutral-800 bg-neutral-850 p-3">
            <p className="text-2xs uppercase tracking-wide text-neutral-500">Track</p>
            <div>
              <label className="mb-1 block text-2xs text-neutral-500">Name</label>
              <input
                value={trackNameDraft}
                onChange={(event) => setTrackNameDraft(event.target.value)}
                className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <button
              type="button"
              disabled={saving || !trackNameDraft.trim() || trackNameDraft === selectedTrack.name}
              onClick={() => onRenameTrack(selection.trackIndex, trackNameDraft.trim())}
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Rename Track
            </button>
          </section>
        )}

        {selection?.type === 'clip' && selectedTrack && selectedClip && (
          <section className="space-y-3 rounded border border-neutral-800 bg-neutral-850 p-3">
            <div>
              <p className="text-2xs uppercase tracking-wide text-neutral-500">Clip</p>
              <p className="truncate text-xs font-medium text-neutral-200">{selectedClip.name || 'Untitled clip'}</p>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">Start (frames)</label>
                <input
                  type="number"
                  value={clipStartFramesDraft}
                  onChange={(event) => setClipStartFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">Duration (frames)</label>
                <input
                  type="number"
                  min={1}
                  value={clipDurationFramesDraft}
                  onChange={(event) => setClipDurationFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
            </div>

            <button
              type="button"
              disabled={saving}
              onClick={() => {
                const rate = selectedClip.source_range.duration.rate
                const startValue = Math.max(
                  0,
                  toInteger(clipStartFramesDraft, selectedClip.source_range.start_time.value),
                )
                const durationValue = Math.max(
                  1,
                  toInteger(clipDurationFramesDraft, selectedClip.source_range.duration.value),
                )

                onTrimClip({
                  trackIndex: selection.trackIndex,
                  clipIndex: selection.itemIndex,
                  newSourceRange: {
                    OTIO_SCHEMA: 'TimeRange.1',
                    start_time: {
                      OTIO_SCHEMA: 'RationalTime.1',
                      value: startValue,
                      rate,
                    },
                    duration: {
                      OTIO_SCHEMA: 'RationalTime.1',
                      value: durationValue,
                      rate,
                    },
                  },
                })
              }}
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Apply Trim
            </button>

            <div className="grid grid-cols-[1fr_auto] gap-2">
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">Slip offset (frames)</label>
                <input
                  type="number"
                  value={clipSlipFramesDraft}
                  onChange={(event) => setClipSlipFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  const rate = selectedClip.source_range.duration.rate
                  const offsetFrames = toInteger(clipSlipFramesDraft, 0)
                  onSlipClip({
                    trackIndex: selection.trackIndex,
                    clipIndex: selection.itemIndex,
                    offset: {
                      OTIO_SCHEMA: 'RationalTime.1',
                      value: offsetFrames,
                      rate,
                    },
                  })
                  setClipSlipFramesDraft('0')
                }}
                className="self-end rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Slip
              </button>
            </div>

            <div className="grid grid-cols-[1fr_auto] gap-2">
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">Split offset (frames)</label>
                <input
                  type="number"
                  min={1}
                  max={Math.max(1, selectedClip.source_range.duration.value - 1)}
                  value={splitFramesDraft}
                  onChange={(event) => setSplitFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
              <button
                type="button"
                disabled={saving}
                onClick={() => {
                  const rate = selectedClip.source_range.duration.rate
                  const splitValue = Math.max(
                    1,
                    Math.min(
                      selectedClip.source_range.duration.value - 1,
                      toInteger(splitFramesDraft, Math.round(selectedClip.source_range.duration.value / 2)),
                    ),
                  )
                  onSplitClip({
                    trackIndex: selection.trackIndex,
                    clipIndex: selection.itemIndex,
                    splitOffset: {
                      OTIO_SCHEMA: 'RationalTime.1',
                      value: splitValue,
                      rate,
                    },
                  })
                }}
                className="self-end rounded border border-amber-600/50 bg-amber-600/20 px-2 py-1.5 text-xs text-amber-100 transition-colors hover:bg-amber-600/30 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Split
              </button>
            </div>

            <div>
              <p className="mb-1 text-2xs text-neutral-500">Effects</p>
              <div className="mb-2 grid grid-cols-[1fr_auto] gap-2">
                <select
                  value={newEffectName}
                  onChange={(event) => setNewEffectName(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="Blur">Blur</option>
                  <option value="Sharpen">Sharpen</option>
                  <option value="Vignette">Vignette</option>
                  <option value="Grain">Grain</option>
                  <option value="Glow">Glow</option>
                </select>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() =>
                    onAddClipEffect({
                      trackIndex: selection.trackIndex,
                      clipIndex: selection.itemIndex,
                      effectName: newEffectName,
                    })
                  }
                  className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Add
                </button>
              </div>
              {selectedClip.effects.length === 0 ? (
                <p className="text-xs text-neutral-500">No effects on this clip.</p>
              ) : (
                <ul className="space-y-1">
                  {selectedClip.effects.map((effect, index) => (
                    <li
                      key={`${effect.effect_name}-${index}`}
                      className="flex items-center justify-between gap-2 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-2xs text-neutral-300"
                    >
                      <span className="truncate">{effect.name || effect.effect_name}</span>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() =>
                          onRemoveClipEffect({
                            trackIndex: selection.trackIndex,
                            clipIndex: selection.itemIndex,
                            effectIndex: index,
                          })
                        }
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}

        {selection?.type === 'transition' && selectedTrack && selectedTransition && (
          <section className="space-y-3 rounded border border-neutral-800 bg-neutral-850 p-3">
            <p className="text-2xs uppercase tracking-wide text-neutral-500">Transition</p>

            <div>
              <label className="mb-1 block text-2xs text-neutral-500">Type</label>
              <select
                value={transitionTypeDraft}
                onChange={(event) => setTransitionTypeDraft(event.target.value as TransitionType)}
                className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
              >
                {TRANSITION_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">In offset (frames)</label>
                <input
                  type="number"
                  min={0}
                  value={transitionInFramesDraft}
                  onChange={(event) => setTransitionInFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-2xs text-neutral-500">Out offset (frames)</label>
                <input
                  type="number"
                  min={0}
                  value={transitionOutFramesDraft}
                  onChange={(event) => setTransitionOutFramesDraft(event.target.value)}
                  className="w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                />
              </div>
            </div>

            <button
              type="button"
              disabled={saving}
              onClick={() => {
                const rate = selectedTransition.in_offset.rate
                onModifyTransition({
                  trackIndex: selection.trackIndex,
                  transitionIndex: selection.itemIndex,
                  transitionType: transitionTypeDraft,
                  inOffset: {
                    OTIO_SCHEMA: 'RationalTime.1',
                    value: Math.max(0, toInteger(transitionInFramesDraft, selectedTransition.in_offset.value)),
                    rate,
                  },
                  outOffset: {
                    OTIO_SCHEMA: 'RationalTime.1',
                    value: Math.max(0, toInteger(transitionOutFramesDraft, selectedTransition.out_offset.value)),
                    rate,
                  },
                })
              }}
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Apply Transition
            </button>
          </section>
        )}
      </div>
    </aside>
  )
}

export default InspectorPanel
