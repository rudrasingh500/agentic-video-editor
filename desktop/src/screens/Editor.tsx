import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from 'react'
import {
  Home,
  Film,
  Settings,
  Play,
  Upload,
  Mic,
  Captions,
  Trash2,
  ChevronRight,
  Download,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize2,
  Grid3X3,
  List,
} from 'lucide-react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { loadAssetCache, saveAssetCache, type AssetCacheIndex } from '../lib/assetCache'
import { loadSessionId, saveSessionId } from '../lib/chatSessions'
import Modal from '../components/Modal'
import OutputPanel from '../components/OutputPanel'
import ChatSidebar from '../components/ChatSidebar'
import type {
  Asset,
  EditPatchSummary,
  EditSessionDetail,
  EditSessionPendingPatch,
  EditSessionSummary,
  Project,
} from '../lib/types'

type EditorProps = {
  project: Project
  config: AppConfig
  onBack: () => void
  onOpenSettings: () => void
}

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

type RenderState = {
  jobId?: string
  status?: string
  progress?: number
  outputPath?: string
}

type UploadResult = {
  sizeBytes: number
}

type RenderJobSummary = {
  job_id: string
  status: string
  job_type?: string
  progress?: number
  execution_mode?: string | null
  timeline_version?: number
  metadata?: Record<string, unknown>
}

const buildStandardPreset = (useGpu: boolean) => ({
  name: useGpu ? 'Standard Export (GPU)' : 'Standard Export',
  quality: 'standard',
  video: {
    codec: 'h264',
    width: null,
    height: null,
    framerate: null,
    bitrate: null,
    crf: 23,
    preset: 'medium',
    pixel_format: 'yuv420p',
  },
  audio: {
    codec: 'aac',
    bitrate: '192k',
    sample_rate: 48000,
    channels: 2,
  },
  use_gpu: useGpu,
})

const toFileUrl = (filePath: string) => {
  const normalized = filePath.replace(/\\/g, '/')
  const prefix = normalized.startsWith('/') ? '' : '/'
  return encodeURI(`file://${prefix}${normalized}`)
}

const Editor = ({ project, config, onBack, onOpenSettings }: EditorProps) => {
  const [assets, setAssets] = useState<Asset[]>([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [assetsError, setAssetsError] = useState<string | null>(null)
  const [timelineVersion, setTimelineVersion] = useState<number | null>(null)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [pendingPatches, setPendingPatches] = useState<EditPatchSummary[]>([])
  const [gpuInfo, setGpuInfo] = useState<{ available: boolean; detail: string } | null>(
    null,
  )
  const [renderState, setRenderState] = useState<RenderState>({})
  const [renderLogs, setRenderLogs] = useState<string[]>([])
  const [previewPath, setPreviewPath] = useState<string | null>(null)
  const [previewKey, setPreviewKey] = useState(0)
  const [assetCache, setAssetCache] = useState<AssetCacheIndex>(() => loadAssetCache())
  const assetsRef = useRef<Asset[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const agentRenderRef = useRef<{ running: boolean; lastJobId: string | null }>({
    running: false,
    lastJobId: null,
  })
  const [sessions, setSessions] = useState<EditSessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [assetToDelete, setAssetToDelete] = useState<Asset | null>(null)

  // UI state for collapsible panels
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [outputPanelOpen, setOutputPanelOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'assets' | 'media' | 'audio' | 'graphics'>('assets')
  const [assetViewMode, setAssetViewMode] = useState<'grid' | 'list'>('grid')

  const mapSessionMessages = (session: EditSessionDetail): ChatMessage[] =>
    (session.messages || []).map((message, index) => ({
      id: message.created_at ?? `${session.session_id}-${index}`,
      role: message.role === 'assistant' ? 'assistant' : 'user',
      content: message.content ?? '',
    }))

  const mapPendingPatches = (
    patches: EditSessionPendingPatch[] | undefined,
  ): EditPatchSummary[] =>
    (patches || []).map((patch) => ({
      patch_id: patch.patch_id,
      agent_type: patch.agent_type ?? 'edit_agent',
      operation_count: patch.patch?.operations?.length ?? 0,
      description: patch.patch?.description ?? '',
      created_at: patch.created_at ?? new Date().toISOString(),
    }))

  const loadSession = useCallback(
    async (nextSessionId: string) => {
      setSessionsError(null)
      const detail = await api.getEditSession(
        config,
        project.project_id,
        nextSessionId,
      )
      setSessionId(detail.session_id)
      saveSessionId(project.project_id, detail.session_id)
      setMessages(mapSessionMessages(detail))
      setPendingPatches(mapPendingPatches(detail.pending_patches))
    },
    [config, project.project_id],
  )

  const refreshSessions = useCallback(
    async (selectSessionId?: string | null) => {
      setSessionsLoading(true)
      setSessionsError(null)
      try {
        const response = await api.listEditSessions(config, project.project_id)
        setSessions(response.sessions || [])
        const stored = loadSessionId(project.project_id)
        const nextSessionId = selectSessionId || stored || response.sessions?.[0]?.session_id
        if (nextSessionId) {
          await loadSession(nextSessionId)
        } else {
          setSessionId(null)
          setMessages([])
          setPendingPatches([])
        }
      } catch (error) {
        setSessionsError((error as Error).message)
      } finally {
        setSessionsLoading(false)
      }
    },
    [config, project.project_id, loadSession],
  )

  const handleNewSession = useCallback(() => {
    setSessionId(null)
    setMessages([])
    setPendingPatches([])
    saveSessionId(project.project_id, null)
  }, [project.project_id])

  const updateAssetCache = useCallback(
    (assetId: string, path: string) => {
      setAssetCache((prev) => {
        const next = { ...prev, [assetId]: path }
        saveAssetCache(next)
        return next
      })
    },
    [],
  )

  const removeAssetCacheEntry = useCallback(
    (assetId: string) => {
      setAssetCache((prev) => {
        if (!prev[assetId]) {
          return prev
        }
        const next = { ...prev }
        delete next[assetId]
        saveAssetCache(next)
        return next
      })
    },
    [],
  )

  const fetchAssets = useCallback(
    async (silent = false) => {
      if (!silent) {
        setAssetsLoading(true)
      }
      setAssetsError(null)
      try {
        const response = await api.listAssets(config, project.project_id)
        const nextAssets = response.assets ?? []
        assetsRef.current = nextAssets
        setAssets(nextAssets)
      } catch (error) {
        setAssetsError((error as Error).message)
      } finally {
        if (!silent) {
          setAssetsLoading(false)
        }
      }
    },
    [config, project.project_id],
  )

  const handleDeleteAsset = useCallback(
    async (target: Asset) => {
      setAssetsError(null)
      try {
        await api.deleteAsset(config, project.project_id, target.asset_id)
        removeAssetCacheEntry(target.asset_id)
        setAssets((prev) => {
          const next = prev.filter((asset) => asset.asset_id !== target.asset_id)
          assetsRef.current = next
          return next
        })
      } catch (error) {
        setAssetsError((error as Error).message)
      }
    },
    [config, project.project_id, removeAssetCacheEntry],
  )

  useEffect(() => {
    let mounted = true
    fetchAssets().catch(() => {})

    const interval = window.setInterval(() => {
      if (!mounted) {
        return
      }
      const hasPending = assetsRef.current.some(
        (asset) =>
          asset.indexing_status === 'pending' ||
          asset.indexing_status === 'processing',
      )
      if (hasPending) {
        fetchAssets(true).catch(() => {})
      }
    }, 4000)

    return () => {
      mounted = false
      window.clearInterval(interval)
    }
  }, [fetchAssets])

  useEffect(() => {
    refreshSessions().catch(() => {})
  }, [refreshSessions])

  useEffect(() => {
    let active = true
    const loadTimeline = async () => {
      try {
        const response = await api.getTimeline(config, project.project_id)
        if (active) {
          setTimelineVersion(response.version ?? null)
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
  }, [config, project.project_id])

  useEffect(() => {
    let active = true
    const loadGpu = async () => {
      try {
        const result = await window.desktopApi.getGpuInfo()
        if (active) {
          setGpuInfo(result)
        }
      } catch (error) {
        if (active) {
          setGpuInfo({ available: false, detail: 'GPU detection failed' })
        }
      }
    }
    loadGpu()
    return () => {
      active = false
    }
  }, [])

  const uploadRenderOutput = useCallback(
    async (jobId: string, outputPath: string) => {
      try {
        const filename = outputPath.split(/[\\/]/).pop() || `${jobId}.mp4`
        const uploadInfo = await api.getOutputUploadUrl(
          config,
          project.project_id,
          filename,
          'video/mp4',
        )

        const uploadResult = (await window.desktopApi.uploadRenderOutput({
          filePath: outputPath,
          uploadUrl: uploadInfo.upload_url,
          contentType: 'video/mp4',
        })) as UploadResult

        await api.shareOutput(config, project.project_id, uploadInfo.gcs_path, null)

        await api.reportRenderProgress(config, project.project_id, jobId, {
          job_id: jobId,
          status: 'completed',
          progress: 100,
          output_url: uploadInfo.gcs_path,
          output_size_bytes: uploadResult.sizeBytes,
        })

        setRenderState((prev) => ({
          ...prev,
          status: 'completed',
        }))
      } catch (error) {
        setRenderState((prev) => ({
          ...prev,
          status: 'failed',
        }))
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: `Render upload failed: ${(error as Error).message}`,
          },
        ])
      }
    },
    [config, project.project_id],
  )

  useEffect(() => {
    const unsubscribeProgress = window.desktopApi.onRenderProgress((event) => {
      if (event.jobId !== renderState.jobId) {
        return
      }
      const payload = event.payload
      setRenderState((prev) => ({
        ...prev,
        status: payload.status ?? prev.status,
        progress: payload.progress ?? prev.progress,
        outputPath: event.outputPath,
      }))
      // Auto-open output panel when rendering starts
      if (payload.status === 'rendering' || payload.status === 'processing') {
        setOutputPanelOpen(true)
      }
      if (payload.status) {
        api.reportRenderProgress(
          config,
          project.project_id,
          event.jobId,
          payload as Record<string, unknown>,
        ).catch(() => {})
      }
    })

    const unsubscribeComplete = window.desktopApi.onRenderComplete((event) => {
      if (event.jobId !== renderState.jobId) {
        return
      }
      setRenderState((prev) => ({
        ...prev,
        status: event.code === 0 ? 'uploading' : 'failed',
        outputPath: event.outputPath,
      }))
      setPreviewPath(event.outputPath)
      setPreviewKey((prev) => prev + 1)
      if (event.code === 0) {
        void uploadRenderOutput(event.jobId, event.outputPath)
      }
    })

    const unsubscribeLogs = window.desktopApi.onRenderLog((event) => {
      if (event.jobId !== renderState.jobId) {
        return
      }
      const lines = event.message.split(/\r?\n/).filter(Boolean)
      if (lines.length === 0) {
        return
      }
      setRenderLogs((prev) => {
        const next = [...prev, ...lines]
        return next.length > 200 ? next.slice(next.length - 200) : next
      })
    })

    return () => {
      unsubscribeProgress()
      unsubscribeComplete()
      unsubscribeLogs()
    }
  }, [config, project.project_id, renderState.jobId, uploadRenderOutput])

  const prepareLocalManifest = useCallback(
    async (
      manifestData: Record<string, unknown>,
      presetOverride?: Record<string, unknown>,
    ) => {
      const assetMap =
        (manifestData.asset_map as Record<string, string> | undefined) ?? {}
      const updatedAssetMap: Record<string, string> = {}

      for (const assetId of Object.keys(assetMap)) {
        const cachedPath = assetCache[assetId]
        if (cachedPath) {
          const exists = await window.desktopApi.fileExists({ path: cachedPath })
          if (exists) {
            updatedAssetMap[assetId] = cachedPath
            continue
          }
        }

        const download = await api.getAssetDownloadUrl(
          config,
          project.project_id,
          assetId,
        )
        const assetInfo = assetsRef.current.find((asset) => asset.asset_id === assetId)
        const cached = await window.desktopApi.downloadAsset({
          assetId,
          url: download.url,
          filename: assetInfo?.asset_name,
        })
        updatedAssetMap[assetId] = cached.path
        updateAssetCache(assetId, cached.path)
      }

      return {
        ...manifestData,
        asset_map: updatedAssetMap,
        preset: presetOverride ?? (manifestData.preset as Record<string, unknown>),
        execution_mode: 'local',
      }
    },
    [assetCache, config, project.project_id, updateAssetCache],
  )

  useEffect(() => {
    let active = true

    const pollQueuedRenders = async () => {
      if (!active || agentRenderRef.current.running) {
        return
      }

      const status = renderState.status
      if (status && !['completed', 'failed', 'cancelled'].includes(status)) {
        return
      }

      agentRenderRef.current.running = true
      let candidate: RenderJobSummary | undefined

      try {
        const response = await api.listRenderJobs(
          config,
          project.project_id,
          'queued',
          10,
          0,
        )
        const jobs = (response.jobs || []) as RenderJobSummary[]

        candidate = jobs.find((job) => {
          const metadata = job.metadata ?? {}
          const createdBy =
            typeof metadata['created_by'] === 'string' ? metadata['created_by'] : ''
          const executionMode = job.execution_mode ?? 'local'
          return (
            job.job_type === 'preview' &&
            executionMode === 'local' &&
            createdBy.startsWith('agent:')
          )
        })

        if (!candidate || agentRenderRef.current.lastJobId === candidate.job_id) {
          return
        }

        agentRenderRef.current.lastJobId = candidate.job_id
        setRenderLogs([])
        setRenderState({
          jobId: candidate.job_id,
          status: candidate.status,
          progress: candidate.progress ?? 0,
        })
        setOutputPanelOpen(true)

        const manifestResponse = await api.getRenderManifest(
          config,
          project.project_id,
          candidate.job_id,
        )
        const manifestData = await fetch(manifestResponse.manifest_url).then((res) =>
          res.json(),
        )

        const updatedManifest = await prepareLocalManifest(manifestData)
        const outputName = `${project.project_name.replace(/\s+/g, '_')}_preview.mp4`
        const renderResult = await window.desktopApi.startRender({
          jobId: candidate.job_id,
          projectId: project.project_id,
          manifest: updatedManifest,
          outputName,
        })

        setRenderState((prev) => ({
          ...prev,
          outputPath: renderResult.outputPath,
        }))
      } catch (error) {
        if (candidate?.job_id) {
          agentRenderRef.current.lastJobId = null
        }
      } finally {
        agentRenderRef.current.running = false
      }
    }

    void pollQueuedRenders()
    const interval = window.setInterval(() => {
      void pollQueuedRenders()
    }, 5000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [config, project.project_id, project.project_name, prepareLocalManifest, renderState.status])

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) {
      return
    }

    for (const file of Array.from(files)) {
      try {
        const response = await api.uploadAsset(config, project.project_id, file)
      setAssets((prev) => {
        const next = [response.asset, ...prev]
        assetsRef.current = next
        return next
      })

        const localPath = (file as File & { path?: string }).path
        if (localPath) {
          const cached = await window.desktopApi.cacheAsset({
            assetId: response.asset.asset_id,
            sourcePath: localPath,
          })
          updateAssetCache(response.asset.asset_id, cached.path)
        }
      } catch (error) {
        setAssetsError((error as Error).message)
      }
    }

    event.target.value = ''
  }

  const handleSendMessage = async () => {
    const trimmed = chatInput.trim()
    if (!trimmed) {
      return
    }

    const newMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: trimmed,
    }
    setMessages((prev) => [...prev, newMessage])
    setChatInput('')

    try {
      const response = await api.sendEditRequest(
        config,
        project.project_id,
        trimmed,
        sessionId,
      )
      if (response.session_id && response.session_id !== sessionId) {
        setSessionId(response.session_id)
        saveSessionId(project.project_id, response.session_id)
      }
      setPendingPatches(response.pending_patches ?? [])
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.message,
        },
      ])
      refreshSessions(response.session_id).catch(() => {})
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `There was an error: ${(error as Error).message}`,
        },
      ])
    }
  }

  const handleApplyPatches = async () => {
    if (!sessionId || pendingPatches.length === 0) {
      return
    }

    try {
      const response = await api.applyPatches(
        config,
        project.project_id,
        sessionId,
        pendingPatches.map((patch) => patch.patch_id),
      )
      if (response.new_version) {
        setTimelineVersion(response.new_version)
      }
      setPendingPatches([])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Apply failed: ${(error as Error).message}`,
        },
      ])
    }
  }

  const handleSessionChange = (value: string) => {
    if (!value) {
      handleNewSession()
      return
    }
    loadSession(value).catch((error) => {
      setSessionsError((error as Error).message)
    })
  }

  const handleRender = async () => {
    const useGpu = gpuInfo?.available ?? false
    setOutputPanelOpen(true)
    try {
      const jobResponse = await api.createRenderJob(config, project.project_id, {
        job_type: 'export',
        execution_mode: 'local',
        preset: buildStandardPreset(useGpu),
        output_filename: `${project.project_name.replace(/\s+/g, '_')}.mp4`,
      })

      const jobId = jobResponse.job.job_id
      setRenderLogs([])
      setRenderState({ jobId, status: 'queued', progress: 0 })

      const manifestResponse = await api.getRenderManifest(
        config,
        project.project_id,
        jobId,
      )
      const manifestData = await fetch(manifestResponse.manifest_url).then((res) =>
        res.json(),
      )

      const updatedManifest = await prepareLocalManifest(
        manifestData,
        buildStandardPreset(useGpu),
      )

      const renderResult = await window.desktopApi.startRender({
        jobId,
        projectId: project.project_id,
        manifest: updatedManifest,
        outputName: `${project.project_name.replace(/\s+/g, '_')}_export.mp4`,
      })

      setRenderState((prev) => ({ ...prev, outputPath: renderResult.outputPath }))
    } catch (error) {
      setRenderState((prev) => ({
        ...prev,
        status: 'failed',
      }))
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Render failed: ${(error as Error).message}`,
        },
      ])
    }
  }

  const previewUrl = useMemo(() => {
    if (!previewPath) {
      return null
    }
    return toFileUrl(previewPath)
  }, [previewPath])

  const tabs = [
    { id: 'assets', label: 'All Assets' },
    { id: 'media', label: 'Video' },
    { id: 'audio', label: 'Audio' },
    { id: 'graphics', label: 'Graphics' },
  ] as const

  return (
    <div className="flex h-screen flex-col bg-neutral-950">
      {/* Header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-neutral-800 px-4">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors"
          >
            <Home className="h-4 w-4" />
          </button>
          <ChevronRight className="h-4 w-4 text-neutral-700" />
          <div className="flex items-center gap-2">
            <Film className="h-4 w-4 text-accent-400" />
            <span className="text-sm font-medium text-neutral-200">
              {project.project_name}
            </span>
          </div>
          <span className="rounded bg-neutral-800 px-2 py-0.5 text-2xs font-mono text-neutral-500">
            v{timelineVersion ?? '-'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-2xs text-neutral-500 mr-2">
            {gpuInfo?.available ? 'GPU Accelerated' : 'CPU Mode'}
          </span>
          <button
            onClick={onOpenSettings}
            className="rounded-lg p-2 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors"
          >
            <Settings className="h-4 w-4" />
          </button>
          <button
            onClick={handleRender}
            className="flex items-center gap-2 rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-accent-600 transition-colors"
          >
            <Download className="h-4 w-4" />
            Export
          </button>
        </div>
      </header>

      {/* Main content area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Main workspace (preview + assets) */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Upper section: Preview */}
          <div className="flex flex-1 min-h-0">
            {/* Video Preview - takes up most of the space */}
            <div className="flex-1 flex flex-col bg-neutral-900 border-r border-neutral-800">
              {/* Preview area */}
              <div className="flex-1 flex items-center justify-center p-4 bg-neutral-950/50">
                <div className="relative w-full h-full max-w-full max-h-full flex items-center justify-center">
                  {previewUrl ? (
                    <video
                      key={previewKey}
                      src={previewUrl}
                      controls
                      className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-4 text-neutral-600">
                      <div className="w-full max-w-2xl aspect-video rounded-xl border-2 border-dashed border-neutral-800 flex flex-col items-center justify-center bg-neutral-900/50">
                        <Film className="h-16 w-16 mb-4 text-neutral-700" />
                        <span className="text-sm text-neutral-500">No preview available</span>
                        <span className="text-xs text-neutral-600 mt-1">
                          Export or render a preview to see it here
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Playback controls */}
              <div className="shrink-0 border-t border-neutral-800 bg-neutral-900 px-4 py-3">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1">
                    <button className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors">
                      <SkipBack className="h-4 w-4" />
                    </button>
                    <button className="rounded-lg bg-neutral-800 p-2 text-neutral-200 hover:bg-neutral-700 transition-colors">
                      <Play className="h-4 w-4" />
                    </button>
                    <button className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors">
                      <SkipForward className="h-4 w-4" />
                    </button>
                  </div>

                  <span className="text-xs tabular-nums text-neutral-500 w-16">00:00:00</span>

                  <div className="flex-1 mx-2">
                    <div className="h-1 w-full rounded-full bg-neutral-800 overflow-hidden cursor-pointer hover:h-1.5 transition-all">
                      <div className="h-full w-0 rounded-full bg-accent-500" />
                    </div>
                  </div>

                  <span className="text-xs tabular-nums text-neutral-500 w-16 text-right">--:--:--</span>

                  <div className="flex items-center gap-2 ml-2">
                    <button className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors">
                      <Volume2 className="h-4 w-4" />
                    </button>
                    <button className="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors">
                      <Maximize2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Assets Panel - Right side */}
            <div className="w-80 flex flex-col bg-neutral-900 border-r border-neutral-800">
              {/* Assets header */}
              <div className="shrink-0 border-b border-neutral-800 p-3">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-medium text-neutral-200">Media</h2>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setAssetViewMode('grid')}
                      className={`rounded p-1.5 transition-colors ${
                        assetViewMode === 'grid'
                          ? 'bg-neutral-800 text-neutral-200'
                          : 'text-neutral-500 hover:text-neutral-300'
                      }`}
                    >
                      <Grid3X3 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => setAssetViewMode('list')}
                      className={`rounded p-1.5 transition-colors ${
                        assetViewMode === 'list'
                          ? 'bg-neutral-800 text-neutral-200'
                          : 'text-neutral-500 hover:text-neutral-300'
                      }`}
                    >
                      <List className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex gap-2">
                  <button
                    onClick={handleUploadClick}
                    className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs font-medium text-neutral-300 hover:border-neutral-600 hover:bg-neutral-700 transition-colors"
                  >
                    <Upload className="h-3.5 w-3.5" />
                    Import
                  </button>
                  <button className="rounded-lg border border-neutral-700 bg-neutral-800 p-2 text-neutral-400 hover:border-neutral-600 hover:bg-neutral-700 hover:text-neutral-300 transition-colors">
                    <Mic className="h-3.5 w-3.5" />
                  </button>
                  <button className="rounded-lg border border-neutral-700 bg-neutral-800 p-2 text-neutral-400 hover:border-neutral-600 hover:bg-neutral-700 hover:text-neutral-300 transition-colors">
                    <Captions className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Tabs */}
              <div className="shrink-0 flex border-b border-neutral-800">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex-1 px-2 py-2 text-xs font-medium transition-colors relative ${
                      activeTab === tab.id
                        ? 'text-neutral-200'
                        : 'text-neutral-500 hover:text-neutral-400'
                    }`}
                  >
                    {tab.label}
                    {activeTab === tab.id && (
                      <div className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent-500 rounded-full" />
                    )}
                  </button>
                ))}
              </div>

              {/* Assets list */}
              <div className="flex-1 overflow-auto p-3 scrollbar-thin">
                {assetsError && (
                  <div className="mb-3 rounded-lg border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-500">
                    {assetsError}
                  </div>
                )}

                {assetsLoading && assets.length === 0 ? (
                  <div className="flex items-center justify-center py-8 text-neutral-600">
                    <span className="text-xs">Loading assets...</span>
                  </div>
                ) : assets.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <div className="rounded-full bg-neutral-800 p-3 mb-3">
                      <Upload className="h-5 w-5 text-neutral-500" />
                    </div>
                    <p className="text-xs text-neutral-400 mb-1">No assets yet</p>
                    <p className="text-2xs text-neutral-600">
                      Import media to get started
                    </p>
                  </div>
                ) : assetViewMode === 'grid' ? (
                  <div className="grid grid-cols-2 gap-2">
                    {assets.map((asset) => (
                      <div
                        key={asset.asset_id}
                        className="group rounded-lg border border-neutral-800 bg-neutral-850 overflow-hidden hover:border-neutral-700 transition-colors"
                      >
                        <div className="aspect-video bg-neutral-800 flex items-center justify-center relative">
                          <Film className="h-5 w-5 text-neutral-600" />
                          <button
                            type="button"
                            aria-label={`Delete ${asset.asset_name}`}
                            onClick={() => setAssetToDelete(asset)}
                            className="absolute top-1 right-1 rounded p-1 bg-neutral-900/80 text-neutral-500 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 hover:text-error-400 transition-all"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                        <div className="p-2">
                          <div className="truncate text-2xs font-medium text-neutral-300">
                            {asset.asset_name}
                          </div>
                          <div className="text-2xs text-neutral-600 mt-0.5">
                            {asset.indexing_status ?? 'ready'}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-1">
                    {assets.map((asset) => (
                      <div
                        key={asset.asset_id}
                        className="group flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-850 p-2 hover:border-neutral-700 transition-colors"
                      >
                        <div className="w-12 h-8 rounded bg-neutral-800 flex items-center justify-center shrink-0">
                          <Film className="h-4 w-4 text-neutral-600" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="truncate text-xs font-medium text-neutral-300">
                            {asset.asset_name}
                          </div>
                          <div className="text-2xs text-neutral-600">
                            {asset.indexing_status ?? 'ready'}
                          </div>
                        </div>
                        <button
                          type="button"
                          aria-label={`Delete ${asset.asset_name}`}
                          onClick={() => setAssetToDelete(asset)}
                          className="rounded p-1.5 text-neutral-600 opacity-0 group-hover:opacity-100 hover:bg-neutral-700 hover:text-error-400 transition-all"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Output Panel (bottom, collapsible) */}
          <OutputPanel
            isOpen={outputPanelOpen}
            onToggle={() => setOutputPanelOpen(!outputPanelOpen)}
            logs={renderLogs}
            renderStatus={renderState}
            onClear={() => setRenderLogs([])}
          />
        </div>

        {/* Chat Sidebar (right, collapsible) */}
        <ChatSidebar
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
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
          gpuAvailable={gpuInfo?.available}
        />
      </div>

      {/* Delete asset confirmation modal */}
      <Modal
        open={Boolean(assetToDelete)}
        title="Delete Asset"
        onClose={() => setAssetToDelete(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-neutral-400">
            Delete {assetToDelete ? `"${assetToDelete.asset_name}"` : 'this asset'}?
            This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setAssetToDelete(null)}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (assetToDelete) {
                  void handleDeleteAsset(assetToDelete)
                }
                setAssetToDelete(null)
              }}
              className="rounded-lg bg-error-500 px-4 py-2 text-sm font-medium text-white hover:bg-error-600 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </Modal>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={handleFileChange}
      />
    </div>
  )
}

export default Editor
