export type TrackKind = 'Video' | 'Audio'

export type MarkerColor =
  | 'RED'
  | 'ORANGE'
  | 'YELLOW'
  | 'GREEN'
  | 'CYAN'
  | 'BLUE'
  | 'PURPLE'
  | 'MAGENTA'
  | 'WHITE'
  | 'BLACK'

export const TRANSITION_TYPES = [
  'SMPTE_Dissolve',
  'Custom',
  'custom',
  'FadeIn',
  'FadeOut',
  'Wipe',
  'Slide',
  'fade',
  'wipeleft',
  'wiperight',
  'wipeup',
  'wipedown',
  'slideleft',
  'slideright',
  'slideup',
  'slidedown',
  'circlecrop',
  'rectcrop',
  'distance',
  'fadeblack',
  'fadewhite',
  'radial',
  'smoothleft',
  'smoothright',
  'smoothup',
  'smoothdown',
  'circleopen',
  'circleclose',
  'vertopen',
  'vertclose',
  'horzopen',
  'horzclose',
  'dissolve',
  'pixelize',
  'diagtl',
  'diagtr',
  'diagbl',
  'diagbr',
  'hlslice',
  'hrslice',
  'vuslice',
  'vdslice',
  'hblur',
  'fadegrays',
  'wipetl',
  'wipetr',
  'wipebl',
  'wipebr',
  'squeezeh',
  'squeezev',
  'zoomin',
  'fadefast',
  'fadeslow',
  'hlwind',
  'hrwind',
  'vuwind',
  'vdwind',
  'coverleft',
  'coverright',
  'coverup',
  'coverdown',
  'revealleft',
  'revealright',
  'revealup',
  'revealdown',
] as const

export type TransitionType = (typeof TRANSITION_TYPES)[number]

export type RationalTime = {
  OTIO_SCHEMA: 'RationalTime.1'
  value: number
  rate: number
}

export type TimeRange = {
  OTIO_SCHEMA: 'TimeRange.1'
  start_time: RationalTime
  duration: RationalTime
}

export type ExternalReference = {
  OTIO_SCHEMA: 'ExternalReference.1'
  asset_id: string
  available_range?: TimeRange | null
  metadata: Record<string, unknown>
}

export type GeneratorKind =
  | 'Caption'
  | 'Title'
  | 'LowerThird'
  | 'Watermark'
  | 'CallOut'
  | 'ProgressBar'
  | 'AnimatedText'
  | 'Shape'
  | 'SolidColor'
  | 'Bars'
  | string

export type GeneratorReference = {
  OTIO_SCHEMA: 'GeneratorReference.1'
  generator_kind: GeneratorKind
  parameters: Record<string, unknown>
  available_range?: TimeRange | null
  metadata: Record<string, unknown>
}

export type MissingReference = {
  OTIO_SCHEMA: 'MissingReference.1'
  name: string
  available_range?: TimeRange | null
  metadata: Record<string, unknown>
}

export type MediaReference = ExternalReference | GeneratorReference | MissingReference

export type Effect = {
  OTIO_SCHEMA: 'Effect.1'
  name: string
  effect_name: string
  metadata: Record<string, unknown>
}

export type LinearTimeWarp = {
  OTIO_SCHEMA: 'LinearTimeWarp.1'
  name: string
  effect_name: 'LinearTimeWarp'
  time_scalar: number
  metadata: Record<string, unknown>
}

export type FreezeFrame = {
  OTIO_SCHEMA: 'FreezeFrame.1'
  name: string
  effect_name: 'FreezeFrame'
  metadata: Record<string, unknown>
}

export type EffectType = Effect | LinearTimeWarp | FreezeFrame

export type Marker = {
  OTIO_SCHEMA: 'Marker.1'
  name: string
  marked_range: TimeRange
  color: MarkerColor
  metadata: Record<string, unknown>
}

export type Clip = {
  OTIO_SCHEMA: 'Clip.1'
  name: string
  source_range: TimeRange
  media_reference: MediaReference
  effects: EffectType[]
  markers: Marker[]
  metadata: Record<string, unknown>
}

export type Gap = {
  OTIO_SCHEMA: 'Gap.1'
  name: string
  source_range: TimeRange
  effects: EffectType[]
  markers: Marker[]
  metadata: Record<string, unknown>
}

export type Transition = {
  OTIO_SCHEMA: 'Transition.1'
  name: string
  transition_type: TransitionType
  in_offset: RationalTime
  out_offset: RationalTime
  metadata: Record<string, unknown>
}

export type Stack = {
  OTIO_SCHEMA: 'Stack.1'
  name: string
  source_range?: TimeRange | null
  children: Array<Track | Stack>
  effects: EffectType[]
  markers: Marker[]
  metadata: Record<string, unknown>
}

export type TrackItem = Clip | Gap | Transition | Stack

export type Track = {
  OTIO_SCHEMA: 'Track.1'
  name: string
  kind: TrackKind
  source_range?: TimeRange | null
  children: TrackItem[]
  effects: EffectType[]
  markers: Marker[]
  metadata: Record<string, unknown>
}

export type Timeline = {
  OTIO_SCHEMA: 'Timeline.1'
  name: string
  global_start_time?: RationalTime | null
  tracks: Stack
  metadata: Record<string, unknown>
}

export type TimelineSettings = {
  default_framerate: number
  resolution_width: number
  resolution_height: number
  sample_rate: number
  pixel_aspect_ratio: number
  audio_channels: number
}

export type CheckpointSummary = {
  checkpoint_id: string
  version: number
  parent_version?: number | null
  description: string
  created_by: string
  created_at: string
  is_approved: boolean
}

export type TimelineWithVersion = {
  timeline: Timeline
  version: number
  checkpoint_id: string
}

export type TimelineDiff = {
  from_version: number
  to_version: number
  tracks_added: string[]
  tracks_removed: string[]
  clips_added: Array<Record<string, unknown>>
  clips_removed: Array<Record<string, unknown>>
  clips_modified: Array<Record<string, unknown>>
  summary: string
}

export type TimelineOperationRecord = {
  operation_id: string
  operation_type: string
  operation_data: Record<string, unknown>
  created_at: string
}

export type TimelineResponse = {
  ok: boolean
  timeline: Timeline
  version: number
  checkpoint_id?: string | null
}

export type TimelineMutationResponse = {
  ok: boolean
  checkpoint: CheckpointSummary
  timeline: Timeline
}

export type CheckpointListResponse = {
  ok: boolean
  checkpoints: CheckpointSummary[]
  total: number
}

export type TimelineDiffResponse = {
  ok: boolean
  diff: TimelineDiff
}

export type AddTrackRequest = {
  name: string
  kind: TrackKind
  index?: number | null
}

export type AddClipRequest = {
  asset_id: string
  source_range: TimeRange
  name?: string | null
  insert_index?: number | null
}

export type TrimClipRequest = {
  new_source_range: TimeRange
}

export type SplitClipRequest = {
  split_offset: RationalTime
}

export type MoveClipRequest = {
  to_track_index: number
  to_clip_index: number
}

export type SlipClipRequest = {
  offset: RationalTime
}

export type AddGapRequest = {
  duration: RationalTime
  insert_index?: number | null
}

export type AddTransitionRequest = {
  position: number
  transition_type: TransitionType
  in_offset?: RationalTime | null
  out_offset?: RationalTime | null
}

export type ModifyTransitionRequest = {
  transition_type?: TransitionType | null
  in_offset?: RationalTime | null
  out_offset?: RationalTime | null
}

export type NestClipsRequest = {
  start_index: number
  end_index: number
  stack_name: string
}

export type AddMarkerRequest = {
  marked_range: TimeRange
  name?: string
  color?: MarkerColor
}

export type AddEffectRequest = {
  effect: EffectType
}
