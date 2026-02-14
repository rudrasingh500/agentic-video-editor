import { create } from 'zustand'

import { api } from '../lib/api'
import type { AppConfig } from '../lib/config'
import type {
  AddClipRequest,
  AddEffectRequest,
  AddGapRequest,
  AddMarkerRequest,
  AddTrackRequest,
  AddTransitionRequest,
  ModifyTransitionRequest,
  MoveClipRequest,
  NestClipsRequest,
  RationalTime,
  SplitClipRequest,
  Timeline,
  TimelineMutationResponse,
  TimelineResponse,
  TrimClipRequest,
} from '../lib/timelineTypes'

const applyTimelineResponse = (
  set: (partial: Partial<TimelineStoreState>) => void,
  response: TimelineResponse,
) => {
  set({
    timeline: response.timeline,
    version: response.version,
    checkpointId: response.checkpoint_id ?? null,
    error: null,
  })
}

const applyTimelineMutation = (
  set: (partial: Partial<TimelineStoreState>) => void,
  response: TimelineMutationResponse,
) => {
  set({
    timeline: response.timeline,
    version: response.checkpoint.version,
    checkpointId: response.checkpoint.checkpoint_id,
    error: null,
  })
}

type MutationRunner = (expectedVersion: number) => Promise<TimelineMutationResponse>

export type TimelineStoreState = {
  timeline: Timeline | null
  version: number | null
  checkpointId: string | null
  loading: boolean
  saving: boolean
  error: string | null
  clear: () => void
  setVersion: (version: number | null) => void
  setSnapshot: (timeline: Timeline, version: number, checkpointId?: string | null) => void
  loadTimeline: (config: AppConfig, projectId: string, version?: number) => Promise<void>
  runMutation: (runner: MutationRunner) => Promise<TimelineMutationResponse>
  rollbackToVersion: (config: AppConfig, projectId: string, targetVersion: number) => Promise<void>
  addTrack: (config: AppConfig, projectId: string, request: AddTrackRequest) => Promise<void>
  removeTrack: (config: AppConfig, projectId: string, trackIndex: number) => Promise<void>
  renameTrack: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    newName: string,
  ) => Promise<void>
  reorderTracks: (config: AppConfig, projectId: string, newOrder: number[]) => Promise<void>
  clearTrack: (config: AppConfig, projectId: string, trackIndex: number) => Promise<void>
  addClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    request: AddClipRequest,
  ) => Promise<void>
  removeClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
  ) => Promise<void>
  trimClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
    request: TrimClipRequest,
  ) => Promise<void>
  splitClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
    request: SplitClipRequest,
  ) => Promise<void>
  moveClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
    request: MoveClipRequest,
  ) => Promise<void>
  slipClip: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
    offset: RationalTime,
  ) => Promise<void>
  replaceClipMedia: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    clipIndex: number,
    newAssetId: string,
  ) => Promise<void>
  addGap: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    request: AddGapRequest,
  ) => Promise<void>
  removeGap: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    gapIndex: number,
  ) => Promise<void>
  addTransition: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    request: AddTransitionRequest,
  ) => Promise<void>
  removeTransition: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    transitionIndex: number,
  ) => Promise<void>
  modifyTransition: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    transitionIndex: number,
    request: ModifyTransitionRequest,
  ) => Promise<void>
  nestItems: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    request: NestClipsRequest,
  ) => Promise<void>
  flattenStack: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    stackIndex: number,
  ) => Promise<void>
  addMarker: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    itemIndex: number,
    request: AddMarkerRequest,
  ) => Promise<void>
  removeMarker: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    itemIndex: number,
    markerIndex: number,
  ) => Promise<void>
  addEffect: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    itemIndex: number,
    request: AddEffectRequest,
  ) => Promise<void>
  removeEffect: (
    config: AppConfig,
    projectId: string,
    trackIndex: number,
    itemIndex: number,
    effectIndex: number,
  ) => Promise<void>
}

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  timeline: null,
  version: null,
  checkpointId: null,
  loading: false,
  saving: false,
  error: null,

  clear: () => {
    set({
      timeline: null,
      version: null,
      checkpointId: null,
      loading: false,
      saving: false,
      error: null,
    })
  },

  setVersion: (version) => {
    set({ version })
  },

  setSnapshot: (timeline, version, checkpointId = null) => {
    set({ timeline, version, checkpointId, error: null })
  },

  loadTimeline: async (config, projectId, version) => {
    set({ loading: true, error: null })
    try {
      const response = await api.getTimeline(config, projectId, version)
      applyTimelineResponse(set, response)
    } catch (error) {
      set({ error: (error as Error).message })
      throw error
    } finally {
      set({ loading: false })
    }
  },

  runMutation: async (runner) => {
    const expectedVersion = get().version
    if (typeof expectedVersion !== 'number') {
      throw new Error('Timeline version is not loaded yet')
    }

    set({ saving: true, error: null })
    try {
      const response = await runner(expectedVersion)
      applyTimelineMutation(set, response)
      return response
    } catch (error) {
      set({ error: (error as Error).message })
      throw error
    } finally {
      set({ saving: false })
    }
  },

  rollbackToVersion: async (config, projectId, targetVersion) => {
    await get().runMutation((expectedVersion) =>
      api.rollbackTimelineVersion(config, projectId, targetVersion, expectedVersion),
    )
  },

  addTrack: async (config, projectId, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineTrack(config, projectId, request, expectedVersion),
    )
  },

  removeTrack: async (config, projectId, trackIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineTrack(config, projectId, trackIndex, expectedVersion),
    )
  },

  renameTrack: async (config, projectId, trackIndex, newName) => {
    await get().runMutation((expectedVersion) =>
      api.renameTimelineTrack(config, projectId, trackIndex, newName, expectedVersion),
    )
  },

  reorderTracks: async (config, projectId, newOrder) => {
    await get().runMutation((expectedVersion) =>
      api.reorderTimelineTracks(config, projectId, newOrder, expectedVersion),
    )
  },

  clearTrack: async (config, projectId, trackIndex) => {
    await get().runMutation((expectedVersion) =>
      api.clearTimelineTrack(config, projectId, trackIndex, expectedVersion),
    )
  },

  addClip: async (config, projectId, trackIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineClip(config, projectId, trackIndex, request, expectedVersion),
    )
  },

  removeClip: async (config, projectId, trackIndex, clipIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineClip(config, projectId, trackIndex, clipIndex, expectedVersion),
    )
  },

  trimClip: async (config, projectId, trackIndex, clipIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.trimTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
    )
  },

  splitClip: async (config, projectId, trackIndex, clipIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.splitTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
    )
  },

  moveClip: async (config, projectId, trackIndex, clipIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.moveTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
    )
  },

  slipClip: async (config, projectId, trackIndex, clipIndex, offset) => {
    await get().runMutation((expectedVersion) =>
      api.slipTimelineClip(config, projectId, trackIndex, clipIndex, offset, expectedVersion),
    )
  },

  replaceClipMedia: async (config, projectId, trackIndex, clipIndex, newAssetId) => {
    await get().runMutation((expectedVersion) =>
      api.replaceTimelineClipMedia(
        config,
        projectId,
        trackIndex,
        clipIndex,
        newAssetId,
        expectedVersion,
      ),
    )
  },

  addGap: async (config, projectId, trackIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineGap(config, projectId, trackIndex, request, expectedVersion),
    )
  },

  removeGap: async (config, projectId, trackIndex, gapIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineGap(config, projectId, trackIndex, gapIndex, expectedVersion),
    )
  },

  addTransition: async (config, projectId, trackIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineTransition(config, projectId, trackIndex, request, expectedVersion),
    )
  },

  removeTransition: async (config, projectId, trackIndex, transitionIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineTransition(config, projectId, trackIndex, transitionIndex, expectedVersion),
    )
  },

  modifyTransition: async (config, projectId, trackIndex, transitionIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.modifyTimelineTransition(
        config,
        projectId,
        trackIndex,
        transitionIndex,
        request,
        expectedVersion,
      ),
    )
  },

  nestItems: async (config, projectId, trackIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.nestTimelineItems(config, projectId, trackIndex, request, expectedVersion),
    )
  },

  flattenStack: async (config, projectId, trackIndex, stackIndex) => {
    await get().runMutation((expectedVersion) =>
      api.flattenTimelineStack(config, projectId, trackIndex, stackIndex, expectedVersion),
    )
  },

  addMarker: async (config, projectId, trackIndex, itemIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineMarker(config, projectId, trackIndex, itemIndex, request, expectedVersion),
    )
  },

  removeMarker: async (config, projectId, trackIndex, itemIndex, markerIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineMarker(
        config,
        projectId,
        trackIndex,
        itemIndex,
        markerIndex,
        expectedVersion,
      ),
    )
  },

  addEffect: async (config, projectId, trackIndex, itemIndex, request) => {
    await get().runMutation((expectedVersion) =>
      api.addTimelineEffect(config, projectId, trackIndex, itemIndex, request, expectedVersion),
    )
  },

  removeEffect: async (config, projectId, trackIndex, itemIndex, effectIndex) => {
    await get().runMutation((expectedVersion) =>
      api.removeTimelineEffect(
        config,
        projectId,
        trackIndex,
        itemIndex,
        effectIndex,
        expectedVersion,
      ),
    )
  },
}))
