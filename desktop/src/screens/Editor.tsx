import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { DEFAULT_TIMELINE_RATE, makeTimeRange } from '../lib/timeUtils'
import useChatSession from '../hooks/useChatSession'
import useConnectionStatus from '../hooks/useConnectionStatus'
import { useConnectionStore } from '../hooks/useConnectionStatus'
import useEditorKeyboard from '../hooks/useEditorKeyboard'
import useRenderPipeline from '../hooks/useRenderPipeline'
import HeaderBar from '../components/editor/HeaderBar'
import GenerateModal from '../components/editor/GenerateModal'
import RenderSettingsModal from '../components/editor/RenderSettingsModal'
import InspectorPanel from '../components/editor/InspectorPanel'
import MediaPanel from '../components/editor/MediaPanel'
import PeoplePanel from '../components/editor/PeoplePanel'
import PreviewPanel from '../components/editor/PreviewPanel'
import Modal from '../components/Modal'
import OutputPanel from '../components/OutputPanel'
import ChatSidebar from '../components/ChatSidebar'
import TimelinePanel from '../components/timeline/TimelinePanel'
import { useAssetStore } from '../stores/assetStore'
import { usePlaybackStore } from '../stores/playbackStore'
import { useRenderStore } from '../stores/renderStore'
import { useTimelineStore } from '../stores/timelineStore'
import { useUiStore } from '../stores/uiStore'
import type {
  Asset,
  Project,
} from '../lib/types'
import type {
  RationalTime,
  TimeRange,
  Track,
  TrackItem,
  TransitionType,
} from '../lib/timelineTypes'

type EditorProps = {
  project: Project
  config: AppConfig
  onBack: () => void
}

const isTrackNode = (value: Track | { OTIO_SCHEMA: string }): value is Track =>
  value.OTIO_SCHEMA === 'Track.1'

const trackItemDurationSeconds = (item: TrackItem): number => {
  if (item.OTIO_SCHEMA === 'Clip.1' || item.OTIO_SCHEMA === 'Gap.1') {
    if (item.source_range.duration.rate <= 0) {
      return 0
    }
    return item.source_range.duration.value / item.source_range.duration.rate
  }

  if (item.OTIO_SCHEMA === 'Transition.1') {
    const inSec = item.in_offset.rate > 0 ? item.in_offset.value / item.in_offset.rate : 0
    const outSec = item.out_offset.rate > 0 ? item.out_offset.value / item.out_offset.rate : 0
    return inSec + outSec
  }

  if (item.source_range?.duration.rate && item.source_range.duration.rate > 0) {
    return item.source_range.duration.value / item.source_range.duration.rate
  }

  return 0
}

const Editor = ({ project, config, onBack }: EditorProps) => {
  const assets = useAssetStore((state) => state.assets)
  const assetsLoading = useAssetStore((state) => state.assetsLoading)
  const assetsError = useAssetStore((state) => state.assetsError)
  const upsertAssets = useAssetStore((state) => state.upsertAssets)
  const loadAssets = useAssetStore((state) => state.loadAssets)
  const rememberAssetPath = useAssetStore((state) => state.rememberAssetPath)
  const clearAssetStore = useAssetStore((state) => state.clear)
  const timelineVersion = useTimelineStore((state) => state.version)
  const timeline = useTimelineStore((state) => state.timeline)
  const timelineSaving = useTimelineStore((state) => state.saving)
  const addTimelineClip = useTimelineStore((state) => state.addClip)
  const addTimelineTrack = useTimelineStore((state) => state.addTrack)
  const moveTimelineClip = useTimelineStore((state) => state.moveClip)
  const trimTimelineClip = useTimelineStore((state) => state.trimClip)
  const splitTimelineClip = useTimelineStore((state) => state.splitClip)
  const slipTimelineClip = useTimelineStore((state) => state.slipClip)
  const renameTimelineTrack = useTimelineStore((state) => state.renameTrack)
  const modifyTimelineTransition = useTimelineStore((state) => state.modifyTransition)
  const removeTimelineClip = useTimelineStore((state) => state.removeClip)
  const removeTimelineGap = useTimelineStore((state) => state.removeGap)
  const removeTimelineTransition = useTimelineStore((state) => state.removeTransition)
  const addTimelineEffect = useTimelineStore((state) => state.addEffect)
  const removeTimelineEffect = useTimelineStore((state) => state.removeEffect)
  const setTimelineVersion = useTimelineStore((state) => state.setVersion)
  const setTimelineSnapshot = useTimelineStore((state) => state.setSnapshot)
  const createLocalTimeline = useTimelineStore((state) => state.createLocalTimeline)
  const syncTimelineToBackend = useTimelineStore((state) => state.syncToBackend)
  const pendingSync = useTimelineStore((state) => state.pendingSync)
  const clearTimelineStore = useTimelineStore((state) => state.clear)
  const clearRenderStore = useRenderStore((state) => state.clear)
  const clearPlaybackStore = usePlaybackStore((state) => state.clear)
  const reportErrorRef = useRef<(message: string) => void>(() => {})
  const [assetToDelete, setAssetToDelete] = useState<Asset | null>(null)
  const [generateModalOpen, setGenerateModalOpen] = useState(false)
  const [peopleModalOpen, setPeopleModalOpen] = useState(false)

  const sidebarOpen = useUiStore((state) => state.sidebarOpen)
  const toggleSidebar = useUiStore((state) => state.toggleSidebar)
  const outputPanelOpen = useUiStore((state) => state.outputPanelOpen)
  const toggleOutputPanel = useUiStore((state) => state.toggleOutputPanel)
  const inspectorOpen = useUiStore((state) => state.inspectorOpen)
  const setInspectorOpen = useUiStore((state) => state.setInspectorOpen)
  const selection = useUiStore((state) => state.selection)
  const clearSelection = useUiStore((state) => state.clearSelection)
  const clearUiStore = useUiStore((state) => state.clear)

  const connectionState = useConnectionStatus(config)

  // Ref to track previous connection state for auto-sync detection
  const prevConnectionRef = useRef(connectionState)
  const syncAssetsToBackend = useAssetStore((state) => state.syncAssetsToBackend)

  useEffect(() => {
    clearTimelineStore()
    clearRenderStore()
    clearPlaybackStore()
    clearUiStore()
    clearAssetStore()
  }, [
    clearAssetStore,
    clearPlaybackStore,
    clearRenderStore,
    clearTimelineStore,
    clearUiStore,
    project.project_id,
  ])

  const handleRenderError = useCallback((message: string) => {
    reportErrorRef.current(message)
  }, [])

  const {
    gpuInfo,
    renderState,
    renderLogs,
    setRenderLogs,
    previewUrl,
    previewKey,
    renderSettingsOpen,
    setRenderSettingsOpen,
    renderSettings,
    setRenderSettings,
    handleRender,
    syncPendingRenders,
  } = useRenderPipeline({
    config,
    projectId: project.project_id,
    projectName: project.project_name,
    onError: handleRenderError,
  })

  // Auto-sync local timeline edits, unsynced assets, AND pending renders
  // to backend when coming back online.
  useEffect(() => {
    const wasOffline = prevConnectionRef.current !== 'online'
    const isNowOnline = connectionState === 'online'
    prevConnectionRef.current = connectionState

    if (wasOffline && isNowOnline) {
      void (async () => {
        try {
          await syncAssetsToBackend(config, project.project_id)
        } catch {
          // Asset sync failed — will retry on next online transition
        }
        if (pendingSync) {
          try {
            await syncTimelineToBackend(config, project.project_id)
          } catch {
            // Timeline sync failed — will retry on next online transition
          }
        }
        try {
          await syncPendingRenders()
        } catch {
          // Render sync failed — will retry on next online transition
        }
      })()
    }
  }, [connectionState, config, pendingSync, project.project_id, syncTimelineToBackend, syncAssetsToBackend, syncPendingRenders])

  const fetchAssets = useCallback(
    async (silent = false) => {
      try {
        await loadAssets(config, project.project_id, silent)
      } catch {
        // error is already stored in assetStore
      }
    },
    [config, loadAssets, project.project_id],
  )

  const handleDeleteAsset = useCallback(
    async (target: Asset) => {
      try {
        await useAssetStore.getState().deleteAsset(config, project.project_id, target.asset_id)
      } catch (error) {
        // error is already stored in assetStore
      }
    },
    [config, project.project_id],
  )

  const resolveTimelineRate = useCallback(() => {
    const metadataRate = timeline?.metadata?.default_rate
    if (typeof metadataRate === 'number' && Number.isFinite(metadataRate) && metadataRate > 0) {
      return metadataRate
    }

    const firstTrack = timeline?.tracks.children.find((child) => child.OTIO_SCHEMA === 'Track.1')
    if (firstTrack && firstTrack.OTIO_SCHEMA === 'Track.1') {
      const firstItem = firstTrack.children[0]
      if (firstItem?.OTIO_SCHEMA === 'Clip.1' || firstItem?.OTIO_SCHEMA === 'Gap.1') {
        return firstItem.source_range.duration.rate
      }
      if (firstItem?.OTIO_SCHEMA === 'Transition.1') {
        return firstItem.in_offset.rate
      }
    }

    return DEFAULT_TIMELINE_RATE
  }, [timeline])

  const ensureTimelineExists = useCallback(async () => {
    if (timeline && typeof timelineVersion === 'number') {
      return
    }

    const timelineName = `${project.project_name} Timeline`
    const online = useConnectionStore.getState().state === 'online'

    if (online) {
      try {
        const created = await api.createTimeline(config, project.project_id, {
          name: timelineName,
        })
        setTimelineSnapshot(created.timeline, created.version, created.checkpoint_id ?? null)
        return
      } catch {
        try {
          const existing = await api.getTimeline(config, project.project_id)
          setTimelineSnapshot(existing.timeline, existing.version, existing.checkpoint_id ?? null)
          return
        } catch {
          // Backend reachable but both calls failed — fall through to local
        }
      }
    }

    // Offline (or backend unreachable): create a local timeline
    createLocalTimeline(timelineName)
  }, [
    config,
    createLocalTimeline,
    project.project_id,
    project.project_name,
    setTimelineSnapshot,
    timeline,
    timelineVersion,
  ])

  const handleAddAssetToTimeline = useCallback(
    async (asset: Asset) => {
      try {
        await ensureTimelineExists()

        const rate = resolveTimelineRate()
        const defaultDurationFrames = Math.max(1, Math.round(rate * 5))

        // Auto-route: audio assets go to first Audio track, everything else
        // goes to the first Video track.
        const currentTimeline = useTimelineStore.getState().timeline
        const tracks = currentTimeline?.tracks?.children ?? []
        const isAudio = asset.asset_type?.toLowerCase() === 'audio'
        const targetKind = isAudio ? 'Audio' : 'Video'
        let trackIndex = tracks.findIndex(
          (child) => child.OTIO_SCHEMA === 'Track.1' && child.kind === targetKind,
        )
        if (trackIndex < 0) {
          // Fallback: use track 0 (or first available track)
          trackIndex = 0
        }

        await addTimelineClip(config, project.project_id, trackIndex, {
          asset_id: asset.asset_id,
          source_range: makeTimeRange(0, defaultDurationFrames, rate),
          name: asset.asset_name,
        })
      } catch (error) {
        reportErrorRef.current(
          `Could not add "${asset.asset_name}" to timeline: ${(error as Error).message}`,
        )
      }
    },
    [addTimelineClip, config, ensureTimelineExists, project.project_id, resolveTimelineRate],
  )

  const handleAddTrack = useCallback(
    async (kind: 'Video' | 'Audio') => {
      try {
        await ensureTimelineExists()
        const tracks = timeline?.tracks?.children ?? []
        const existingCount = tracks.filter(
          (child) => child.OTIO_SCHEMA === 'Track.1' && child.kind === kind,
        ).length
        await addTimelineTrack(config, project.project_id, {
          name: `${kind} ${existingCount + 1}`,
          kind,
        })
      } catch (error) {
        reportErrorRef.current(
          `Could not add ${kind} track: ${(error as Error).message}`,
        )
      }
    },
    [addTimelineTrack, config, ensureTimelineExists, project.project_id, timeline],
  )

  const handleAssetDragStart = useCallback(
    (event: DragEvent<HTMLElement>, assetId: string) => {
      event.dataTransfer.setData('application/x-auteur-asset-id', assetId)
      event.dataTransfer.effectAllowed = 'copy'
    },
    [],
  )

  const handleDroppedAssetToTimeline = useCallback(
    (assetId: string) => {
      const droppedAsset = useAssetStore.getState().assets.find((asset) => asset.asset_id === assetId)
      if (!droppedAsset) {
        return
      }
      void handleAddAssetToTimeline(droppedAsset)
    },
    [handleAddAssetToTimeline],
  )

  const handleMoveClipOnTimeline = useCallback(
    async (payload: {
      fromTrackIndex: number
      clipIndex: number
      toTrackIndex: number
      toClipIndex: number
    }) => {
      try {
        await moveTimelineClip(
          config,
          project.project_id,
          payload.fromTrackIndex,
          payload.clipIndex,
          {
            to_track_index: payload.toTrackIndex,
            to_clip_index: payload.toClipIndex,
          },
        )
      } catch (error) {
        reportErrorRef.current(`Could not move clip: ${(error as Error).message}`)
      }
    },
    [config, moveTimelineClip, project.project_id],
  )

  const handleTrimClipOnTimeline = useCallback(
    async (payload: { trackIndex: number; clipIndex: number; newSourceRange: TimeRange }) => {
      try {
        await trimTimelineClip(
          config,
          project.project_id,
          payload.trackIndex,
          payload.clipIndex,
          {
            new_source_range: payload.newSourceRange,
          },
        )
      } catch (error) {
        reportErrorRef.current(`Could not trim clip: ${(error as Error).message}`)
      }
    },
    [config, project.project_id, trimTimelineClip],
  )

  const handleSplitClipOnTimeline = useCallback(
    async (payload: { trackIndex: number; clipIndex: number; splitOffset: RationalTime }) => {
      try {
        await splitTimelineClip(
          config,
          project.project_id,
          payload.trackIndex,
          payload.clipIndex,
          {
            split_offset: payload.splitOffset,
          },
        )
      } catch (error) {
        reportErrorRef.current(`Could not split clip: ${(error as Error).message}`)
      }
    },
    [config, project.project_id, splitTimelineClip],
  )

  const handleSlipClipOnTimeline = useCallback(
    async (payload: { trackIndex: number; clipIndex: number; offset: RationalTime }) => {
      try {
        await slipTimelineClip(
          config,
          project.project_id,
          payload.trackIndex,
          payload.clipIndex,
          payload.offset,
        )
      } catch (error) {
        reportErrorRef.current(`Could not slip clip: ${(error as Error).message}`)
      }
    },
    [config, project.project_id, slipTimelineClip],
  )

  const handleRenameTrackOnTimeline = useCallback(
    async (trackIndex: number, newName: string) => {
      try {
        await renameTimelineTrack(config, project.project_id, trackIndex, newName)
      } catch (error) {
        reportErrorRef.current(`Could not rename track: ${(error as Error).message}`)
      }
    },
    [config, project.project_id, renameTimelineTrack],
  )

  const handleModifyTransitionOnTimeline = useCallback(
    async (payload: {
      trackIndex: number
      transitionIndex: number
      transitionType: TransitionType
      inOffset: RationalTime
      outOffset: RationalTime
    }) => {
      try {
        await modifyTimelineTransition(
          config,
          project.project_id,
          payload.trackIndex,
          payload.transitionIndex,
          {
            transition_type: payload.transitionType,
            in_offset: payload.inOffset,
            out_offset: payload.outOffset,
          },
        )
      } catch (error) {
        reportErrorRef.current(`Could not update transition: ${(error as Error).message}`)
      }
    },
    [config, modifyTimelineTransition, project.project_id],
  )

  const handleAddClipEffectOnTimeline = useCallback(
    async (payload: { trackIndex: number; clipIndex: number; effectName: string }) => {
      try {
        await addTimelineEffect(
          config,
          project.project_id,
          payload.trackIndex,
          payload.clipIndex,
          {
            effect: {
              OTIO_SCHEMA: 'Effect.1',
              name: payload.effectName,
              effect_name: payload.effectName,
              metadata: {},
            },
          },
        )
      } catch (error) {
        reportErrorRef.current(`Could not add effect: ${(error as Error).message}`)
      }
    },
    [addTimelineEffect, config, project.project_id],
  )

  const handleRemoveClipEffectOnTimeline = useCallback(
    async (payload: { trackIndex: number; clipIndex: number; effectIndex: number }) => {
      try {
        await removeTimelineEffect(
          config,
          project.project_id,
          payload.trackIndex,
          payload.clipIndex,
          payload.effectIndex,
        )
      } catch (error) {
        reportErrorRef.current(`Could not remove effect: ${(error as Error).message}`)
      }
    },
    [config, project.project_id, removeTimelineEffect],
  )

  const refreshTimelineSnapshot = useCallback(
    async (version?: number) => {
      const response = await api.getTimeline(config, project.project_id, version)
      setTimelineSnapshot(response.timeline, response.version, response.checkpoint_id ?? null)
      return response
    },
    [config, project.project_id, setTimelineSnapshot],
  )

  const {
    chatInput,
    setChatInput,
    messages,
    appendMessage,
    sessionId,
    pendingPatches,
    activityEvents,
    agentBusy,
    sessions,
    sessionsLoading,
    sessionsError,
    handleNewSession,
    handleSendMessage,
    handleApplyPatches,
    handleSessionChange,
  } = useChatSession({
    config,
    projectId: project.project_id,
    setTimelineVersion,
    refreshTimelineSnapshot,
    fetchAssets,
  })

  // Wire up error reporting now that appendMessage is available
  reportErrorRef.current = (message: string) => appendMessage('assistant', message)

  const timelineTracks = useMemo(() => {
    if (!timeline) {
      return []
    }
    return timeline.tracks.children.filter(isTrackNode)
  }, [timeline])

  const selectedClipContext = useMemo(() => {
    if (!selection || selection.type !== 'clip') {
      return null
    }

    const track = timelineTracks[selection.trackIndex]
    if (!track) {
      return null
    }

    const item = track.children[selection.itemIndex]
    if (!item || item.OTIO_SCHEMA !== 'Clip.1') {
      return null
    }

    let startSeconds = 0
    for (let index = 0; index < selection.itemIndex; index += 1) {
      const candidate = track.children[index]
      if (candidate?.OTIO_SCHEMA === 'Transition.1') {
        continue
      }
      startSeconds += trackItemDurationSeconds(candidate)
    }

    const durationRate = item.source_range.duration.rate
    const durationSeconds =
      durationRate > 0 ? item.source_range.duration.value / durationRate : 0

    return {
      trackIndex: selection.trackIndex,
      clipIndex: selection.itemIndex,
      clip: item,
      startSeconds,
      durationSeconds,
    }
  }, [selection, timelineTracks])

  const handleDeleteSelection = useCallback(async () => {
    if (!selection) {
      return
    }

    try {
      if (selection.type === 'clip') {
        await removeTimelineClip(config, project.project_id, selection.trackIndex, selection.itemIndex)
        clearSelection()
        return
      }

      if (selection.type === 'gap') {
        await removeTimelineGap(config, project.project_id, selection.trackIndex, selection.itemIndex)
        clearSelection()
        return
      }

      if (selection.type === 'transition') {
        await removeTimelineTransition(
          config,
          project.project_id,
          selection.trackIndex,
          selection.itemIndex,
        )
        clearSelection()
      }
    } catch (error) {
      reportErrorRef.current(`Could not delete selection: ${(error as Error).message}`)
    }
  }, [
    clearSelection,
    config,
    project.project_id,
    removeTimelineClip,
    removeTimelineGap,
    removeTimelineTransition,
    selection,
  ])

  useEditorKeyboard({
    selectedClipContext,
    onSplitClip: (payload) => void handleSplitClipOnTimeline(payload),
    onDeleteSelection: () => void handleDeleteSelection(),
  })

  useEffect(() => {
    let mounted = true
    fetchAssets().catch(() => {})

    const interval = window.setInterval(() => {
      if (!mounted) {
        return
      }
      fetchAssets(true).catch(() => {})
    }, 6000)

    return () => {
      mounted = false
      window.clearInterval(interval)
    }
  }, [fetchAssets])

  useEffect(() => {
    let active = true
    const loadTimeline = async () => {
      try {
        if (active) {
          await refreshTimelineSnapshot()
        }
      } catch (error) {
        if (active) {
          setTimelineVersion(null)
        }
      }
    }
    loadTimeline()
    return () => {
      active = false
    }
  }, [refreshTimelineSnapshot, setTimelineVersion])

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) {
      return
    }

    const online = useConnectionStore.getState().state === 'online'

    for (const file of Array.from(files)) {
      const localPath = (file as File & { path?: string }).path

      if (online) {
        // Online: upload to backend as before
        try {
          const uploaded = await useAssetStore.getState().uploadAsset(config, project.project_id, file)

          if (localPath) {
            const cached = await window.desktopApi.cacheAsset({
              assetId: uploaded.asset_id,
              sourcePath: localPath,
            })
            rememberAssetPath(uploaded.asset_id, cached.path)
          }
        } catch {
          // error is already stored in assetStore
        }
      } else {
        // Offline: import locally (no backend needed)
        if (localPath) {
          useAssetStore.getState().addLocalAsset(project.project_id, localPath)
        }
      }
    }

    event.target.value = ''
  }

  return (
    <div className="flex h-screen flex-col bg-neutral-950">
      <HeaderBar
        projectName={project.project_name}
        timelineVersion={timelineVersion}
        gpuAvailable={gpuInfo?.available ?? false}
        gpuBackend={gpuInfo?.backend ?? 'none'}
        onBack={onBack}
        onOpenRenderSettings={() => setRenderSettingsOpen(true)}
        onRender={handleRender}
        onOpenPeople={() => setPeopleModalOpen(true)}
        onOpenGenerate={() => setGenerateModalOpen(true)}
      />

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex flex-1 min-h-0">
            <PreviewPanel previewUrl={previewUrl} previewKey={previewKey} />

            <MediaPanel
              assets={assets}
              assetsLoading={assetsLoading}
              assetsError={assetsError}
              timelineSaving={timelineSaving}
              onUploadFiles={handleFileChange}
              onAddToTimeline={handleAddAssetToTimeline}
              onDragStart={handleAssetDragStart}
              onDeleteAsset={handleDeleteAsset}
              assetToDelete={assetToDelete}
              onSetAssetToDelete={setAssetToDelete}
            />
          </div>

          <TimelinePanel
            timeline={timeline}
            onDropAsset={handleDroppedAssetToTimeline}
            onMoveClip={handleMoveClipOnTimeline}
            onTrimClip={handleTrimClipOnTimeline}
            onSplitClip={handleSplitClipOnTimeline}
            onAddTrack={handleAddTrack}
          />

          {/* Output Panel (bottom, collapsible) */}
          <OutputPanel
            isOpen={outputPanelOpen}
            onToggle={toggleOutputPanel}
            logs={renderLogs}
            renderStatus={renderState}
            onClear={() => setRenderLogs([])}
          />
        </div>

        <InspectorPanel
          isOpen={inspectorOpen}
          onToggle={() => setInspectorOpen(!inspectorOpen)}
          timeline={timeline}
          selection={selection}
          saving={timelineSaving}
          onRenameTrack={handleRenameTrackOnTimeline}
          onTrimClip={handleTrimClipOnTimeline}
          onSlipClip={handleSlipClipOnTimeline}
          onSplitClip={handleSplitClipOnTimeline}
          onAddClipEffect={handleAddClipEffectOnTimeline}
          onRemoveClipEffect={handleRemoveClipEffectOnTimeline}
          onModifyTransition={handleModifyTransitionOnTimeline}
        />

        {/* Chat Sidebar (right, collapsible) */}
        <ChatSidebar
          isOpen={sidebarOpen}
          onToggle={toggleSidebar}
          messages={messages}
          chatInput={chatInput}
          onChatInputChange={setChatInput}
          onSendMessage={handleSendMessage}
          sessions={sessions}
          sessionId={sessionId}
          sessionsLoading={sessionsLoading}
          sessionsError={sessionsError}
          onSessionChange={handleSessionChange}
          onNewSession={handleNewSession}
          pendingPatches={pendingPatches}
          onApplyPatches={handleApplyPatches}
          activityEvents={activityEvents}
          agentBusy={agentBusy}
          gpuAvailable={gpuInfo?.available}
        />
      </div>

      <RenderSettingsModal
        open={renderSettingsOpen}
        onClose={() => setRenderSettingsOpen(false)}
        settings={renderSettings}
        onSettingsChange={setRenderSettings}
        gpuInfo={gpuInfo}
        projectName={project.project_name}
      />

      <GenerateModal
        open={generateModalOpen}
        onClose={() => setGenerateModalOpen(false)}
        config={config}
        projectId={project.project_id}
        assets={assets}
        onAssetsUpsert={upsertAssets}
        onAssetsRefresh={() => fetchAssets(true)}
      />

      <Modal
        open={peopleModalOpen}
        title="People"
        onClose={() => setPeopleModalOpen(false)}
        maxWidth="max-w-2xl"
      >
        <div className="max-h-[60vh] overflow-auto scrollbar-thin">
          <PeoplePanel config={config} projectId={project.project_id} />
        </div>
      </Modal>

    </div>
  )
}

export default Editor
