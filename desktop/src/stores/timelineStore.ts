import { create } from 'zustand'

import { api } from '../lib/api'
import type { AppConfig } from '../lib/config'
import * as local from '../lib/localTimelineOps'
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
import { useConnectionStore } from '../hooks/useConnectionStatus'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
    pendingSync: false,
  })
}

const isOnline = (): boolean => useConnectionStore.getState().state === 'online'

type MutationRunner = (expectedVersion: number) => Promise<TimelineMutationResponse>

// ---------------------------------------------------------------------------
// Store type
// ---------------------------------------------------------------------------

export type TimelineStoreState = {
  timeline: Timeline | null
  version: number | null
  checkpointId: string | null
  loading: boolean
  saving: boolean
  error: string | null

  /** Incremented on every local (offline) mutation. */
  localVersion: number
  /** True when local edits exist that have not been synced to the backend. */
  pendingSync: boolean
  /** True when the timeline was created locally (no backend counterpart yet). */
  isOfflineTimeline: boolean

  clear: () => void
  setVersion: (version: number | null) => void
  setSnapshot: (timeline: Timeline, version: number, checkpointId?: string | null) => void
  loadTimeline: (config: AppConfig, projectId: string, version?: number) => Promise<void>
  /** Create an empty local timeline (offline fallback). */
  createLocalTimeline: (name?: string) => void
  runMutation: (runner: MutationRunner) => Promise<TimelineMutationResponse>
  /** Apply a local mutation, bump localVersion, set pendingSync. */
  applyLocal: (mutator: (tl: Timeline) => Timeline) => void
  /** Push the full local timeline to the backend (on reconnect). */
  syncToBackend: (config: AppConfig, projectId: string) => Promise<void>
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

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  timeline: null,
  version: null,
  checkpointId: null,
  loading: false,
  saving: false,
  error: null,
  localVersion: 0,
  pendingSync: false,
  isOfflineTimeline: false,

  clear: () => {
    set({
      timeline: null,
      version: null,
      checkpointId: null,
      loading: false,
      saving: false,
      error: null,
      localVersion: 0,
      pendingSync: false,
      isOfflineTimeline: false,
    })
  },

  setVersion: (version) => {
    set({ version })
  },

  setSnapshot: (timeline, version, checkpointId = null) => {
    set({ timeline, version, checkpointId, error: null })
  },

  createLocalTimeline: (name) => {
    const tl = local.createEmptyTimeline(name)
    set({
      timeline: tl,
      version: 0,
      localVersion: 1,
      checkpointId: null,
      pendingSync: true,
      isOfflineTimeline: true,
      error: null,
    })
  },

  loadTimeline: async (config, projectId, version) => {
    set({ loading: true, error: null })
    try {
      const response = await api.getTimeline(config, projectId, version)
      applyTimelineResponse(set, response)
      set({ isOfflineTimeline: false })
    } catch (error) {
      // If offline and no timeline loaded yet, don't throw — caller can
      // use createLocalTimeline as a fallback.
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

  applyLocal: (mutator) => {
    const { timeline, localVersion } = get()
    if (!timeline) {
      throw new Error('No timeline to mutate')
    }
    const updated = mutator(timeline)
    set({
      timeline: updated,
      localVersion: localVersion + 1,
      pendingSync: true,
      error: null,
    })
  },

  syncToBackend: async (config, projectId) => {
    const { timeline, pendingSync, version } = get()
    if (!timeline || !pendingSync) {
      return
    }

    set({ saving: true, error: null })
    try {
      // Use replaceTimeline API to push the full local state.
      // If this is a brand-new offline timeline (version 0), we first need
      // to create it on the backend, then replace.  For simplicity we use
      // version 0 which the backend interprets as "create if not exists".
      const expectedVersion = typeof version === 'number' ? version : 0
      const response = await api.replaceTimeline(
        config,
        projectId,
        timeline,
        expectedVersion,
        'Sync local edits to backend',
      )
      set({
        timeline: response.timeline,
        version: response.checkpoint.version,
        checkpointId: response.checkpoint.checkpoint_id,
        pendingSync: false,
        isOfflineTimeline: false,
        error: null,
      })
    } catch (error) {
      set({ error: (error as Error).message })
      throw error
    } finally {
      set({ saving: false })
    }
  },

  // -------------------------------------------------------------------
  // Rollback (online only — no local equivalent)
  // -------------------------------------------------------------------

  rollbackToVersion: async (config, projectId, targetVersion) => {
    if (!isOnline()) {
      throw new Error('Rollback requires a backend connection')
    }
    await get().runMutation((expectedVersion) =>
      api.rollbackTimelineVersion(config, projectId, targetVersion, expectedVersion),
    )
  },

  // -------------------------------------------------------------------
  // Track operations
  // -------------------------------------------------------------------

  addTrack: async (config, projectId, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineTrack(config, projectId, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addTrack(tl, request))
    }
  },

  removeTrack: async (config, projectId, trackIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.removeTimelineTrack(config, projectId, trackIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.removeTrack(tl, trackIndex))
    }
  },

  renameTrack: async (config, projectId, trackIndex, newName) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.renameTimelineTrack(config, projectId, trackIndex, newName, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.renameTrack(tl, trackIndex, newName))
    }
  },

  reorderTracks: async (config, projectId, newOrder) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.reorderTimelineTracks(config, projectId, newOrder, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.reorderTracks(tl, newOrder))
    }
  },

  clearTrack: async (config, projectId, trackIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.clearTimelineTrack(config, projectId, trackIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.clearTrack(tl, trackIndex))
    }
  },

  // -------------------------------------------------------------------
  // Clip operations
  // -------------------------------------------------------------------

  addClip: async (config, projectId, trackIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineClip(config, projectId, trackIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addClip(tl, trackIndex, request))
    }
  },

  removeClip: async (config, projectId, trackIndex, clipIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.removeTimelineClip(config, projectId, trackIndex, clipIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.removeClip(tl, trackIndex, clipIndex))
    }
  },

  trimClip: async (config, projectId, trackIndex, clipIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.trimTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) =>
        local.trimClip(tl, trackIndex, clipIndex, request.new_source_range),
      )
    }
  },

  splitClip: async (config, projectId, trackIndex, clipIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.splitTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) =>
        local.splitClip(tl, trackIndex, clipIndex, request.split_offset),
      )
    }
  },

  moveClip: async (config, projectId, trackIndex, clipIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.moveTimelineClip(config, projectId, trackIndex, clipIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) =>
        local.moveClip(tl, trackIndex, clipIndex, request.to_track_index, request.to_clip_index),
      )
    }
  },

  slipClip: async (config, projectId, trackIndex, clipIndex, offset) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.slipTimelineClip(config, projectId, trackIndex, clipIndex, offset, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.slipClip(tl, trackIndex, clipIndex, offset))
    }
  },

  replaceClipMedia: async (config, projectId, trackIndex, clipIndex, newAssetId) => {
    if (isOnline() && !get().isOfflineTimeline) {
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
    } else {
      get().applyLocal((tl) => local.replaceClipMedia(tl, trackIndex, clipIndex, newAssetId))
    }
  },

  // -------------------------------------------------------------------
  // Gap operations
  // -------------------------------------------------------------------

  addGap: async (config, projectId, trackIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineGap(config, projectId, trackIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addGap(tl, trackIndex, request))
    }
  },

  removeGap: async (config, projectId, trackIndex, gapIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.removeTimelineGap(config, projectId, trackIndex, gapIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.removeGap(tl, trackIndex, gapIndex))
    }
  },

  // -------------------------------------------------------------------
  // Transition operations
  // -------------------------------------------------------------------

  addTransition: async (config, projectId, trackIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineTransition(config, projectId, trackIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addTransition(tl, trackIndex, request))
    }
  },

  removeTransition: async (config, projectId, trackIndex, transitionIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.removeTimelineTransition(config, projectId, trackIndex, transitionIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.removeTransition(tl, trackIndex, transitionIndex))
    }
  },

  modifyTransition: async (config, projectId, trackIndex, transitionIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
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
    } else {
      get().applyLocal((tl) =>
        local.modifyTransition(tl, trackIndex, transitionIndex, request),
      )
    }
  },

  // -------------------------------------------------------------------
  // Nesting operations
  // -------------------------------------------------------------------

  nestItems: async (config, projectId, trackIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.nestTimelineItems(config, projectId, trackIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) =>
        local.nestItems(tl, trackIndex, request.start_index, request.end_index, request.stack_name),
      )
    }
  },

  flattenStack: async (config, projectId, trackIndex, stackIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.flattenTimelineStack(config, projectId, trackIndex, stackIndex, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.flattenStack(tl, trackIndex, stackIndex))
    }
  },

  // -------------------------------------------------------------------
  // Marker operations
  // -------------------------------------------------------------------

  addMarker: async (config, projectId, trackIndex, itemIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineMarker(config, projectId, trackIndex, itemIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addMarker(tl, trackIndex, itemIndex, request))
    }
  },

  removeMarker: async (config, projectId, trackIndex, itemIndex, markerIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
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
    } else {
      get().applyLocal((tl) => local.removeMarker(tl, trackIndex, itemIndex, markerIndex))
    }
  },

  // -------------------------------------------------------------------
  // Effect operations
  // -------------------------------------------------------------------

  addEffect: async (config, projectId, trackIndex, itemIndex, request) => {
    if (isOnline() && !get().isOfflineTimeline) {
      await get().runMutation((expectedVersion) =>
        api.addTimelineEffect(config, projectId, trackIndex, itemIndex, request, expectedVersion),
      )
    } else {
      get().applyLocal((tl) => local.addEffect(tl, trackIndex, itemIndex, request))
    }
  },

  removeEffect: async (config, projectId, trackIndex, itemIndex, effectIndex) => {
    if (isOnline() && !get().isOfflineTimeline) {
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
    } else {
      get().applyLocal((tl) => local.removeEffect(tl, trackIndex, itemIndex, effectIndex))
    }
  },
}))
