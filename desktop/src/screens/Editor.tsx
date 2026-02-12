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
  Play,
  Upload,
  Trash2,
  ChevronRight,
  Download,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize2,
  Grid3X3,
  List,
  Sparkles,
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
  EditSessionActivityEvent,
  EditSessionDetail,
  EditSessionPendingPatch,
  EditSessionSummary,
  GenerationCreatePayload,
  GenerationMode,
  GenerationRecord,
  Project,
  Snippet,
} from '../lib/types'

type EditorProps = {
  project: Project
  config: AppConfig
  onBack: () => void
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

type GpuBackend = 'nvidia' | 'amd' | 'apple' | 'none'

type GpuInfo = {
  available: boolean
  detail: string
  backend: GpuBackend
  encoders: {
    h264: boolean
    h265: boolean
  }
}

type GenerationFormState = {
  prompt: string
  mode: GenerationMode
  targetAssetId: string
  frameRangeStart: string
  frameRangeEnd: string
  frameIndices: string
  frameRepeatCount: string
  videoAspectRatio: string
  videoResolution: string
  videoNegativePrompt: string
  referenceSnippetId: string
  referenceAssetId: string
}

type RenderQuality = 'draft' | 'standard' | 'high' | 'maximum'

type RenderCodec = 'h264' | 'h265'

type RenderResolution = 'source' | '720p' | '1080p' | '1440p' | '2160p'

type RenderFrameRate = 'source' | '24' | '30' | '60'

type RenderSettingsState = {
  outputFilename: string
  quality: RenderQuality
  codec: RenderCodec
  resolution: RenderResolution
  frameRate: RenderFrameRate
  useGpu: boolean
}

const RENDER_QUALITY_DEFAULTS: Record<
  RenderQuality,
  { name: string; crf: number; preset: string; audioBitrate: string }
> = {
  draft: {
    name: 'Draft Export',
    crf: 28,
    preset: 'veryfast',
    audioBitrate: '128k',
  },
  standard: {
    name: 'Standard Export',
    crf: 23,
    preset: 'medium',
    audioBitrate: '192k',
  },
  high: {
    name: 'High Quality Export',
    crf: 18,
    preset: 'slow',
    audioBitrate: '320k',
  },
  maximum: {
    name: 'Maximum Quality Export',
    crf: 15,
    preset: 'veryslow',
    audioBitrate: '320k',
  },
}

const RENDER_RESOLUTION_DIMENSIONS: Record<
  RenderResolution,
  { width: number | null; height: number | null }
> = {
  source: { width: null, height: null },
  '720p': { width: 1280, height: 720 },
  '1080p': { width: 1920, height: 1080 },
  '1440p': { width: 2560, height: 1440 },
  '2160p': { width: 3840, height: 2160 },
}

const buildDefaultRenderSettings = (projectName: string): RenderSettingsState => ({
  outputFilename: `${projectName.replace(/\s+/g, '_')}.mp4`,
  quality: 'standard',
  codec: 'h264',
  resolution: 'source',
  frameRate: 'source',
  useGpu: true,
})

const normalizeOutputFilename = (rawFilename: string, projectName: string) => {
  const fallback = `${projectName.replace(/\s+/g, '_')}.mp4`
  const candidate = rawFilename.trim() || fallback
  const sanitized = candidate.replace(/[\\/:*?"<>|]+/g, '_')
  return sanitized.toLowerCase().endsWith('.mp4') ? sanitized : `${sanitized}.mp4`
}

const buildRenderPreset = (settings: RenderSettingsState, gpuInfo: GpuInfo | null) => {
  const defaults = RENDER_QUALITY_DEFAULTS[settings.quality]
  const dimensions = RENDER_RESOLUTION_DIMENSIONS[settings.resolution]
  const frameRate = settings.frameRate === 'source' ? null : Number(settings.frameRate)
  const useGpu = settings.useGpu && Boolean(gpuInfo?.available)
  const gpuBackend =
    gpuInfo?.backend && gpuInfo.backend !== 'none' ? gpuInfo.backend : 'nvidia'

  return {
    name: useGpu ? `${defaults.name} (GPU)` : defaults.name,
    quality: settings.quality,
    video: {
      codec: settings.codec,
      width: dimensions.width,
      height: dimensions.height,
      framerate: frameRate,
      bitrate: null,
      crf: defaults.crf,
      preset: defaults.preset,
      pixel_format: 'yuv420p',
    },
    audio: {
      codec: 'aac',
      bitrate: defaults.audioBitrate,
      sample_rate: 48000,
      channels: 2,
    },
    use_gpu: useGpu,
    gpu_backend: useGpu ? gpuBackend : null,
  }
}

const toFileUrl = (filePath: string) => {
  const normalized = filePath.replace(/\\/g, '/')
  const prefix = normalized.startsWith('/') ? '' : '/'
  return encodeURI(`file://${prefix}${normalized}`)
}

const formatGpuBackendLabel = (backend: GpuBackend) => {
  if (backend === 'nvidia') {
    return 'NVENC'
  }
  if (backend === 'amd') {
    return 'AMD AMF'
  }
  if (backend === 'apple') {
    return 'VideoToolbox'
  }
  return 'Auto'
}

const Editor = ({ project, config, onBack }: EditorProps) => {
  const [assets, setAssets] = useState<Asset[]>([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [assetsError, setAssetsError] = useState<string | null>(null)
  const [timelineVersion, setTimelineVersion] = useState<number | null>(null)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [pendingPatches, setPendingPatches] = useState<EditPatchSummary[]>([])
  const [activityEvents, setActivityEvents] = useState<EditSessionActivityEvent[]>([])
  const [agentBusy, setAgentBusy] = useState(false)
  const [gpuInfo, setGpuInfo] = useState<GpuInfo | null>(null)
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
  const [snippets, setSnippets] = useState<Snippet[]>([])
  const [snippetsLoading, setSnippetsLoading] = useState(false)
  const [generationBusy, setGenerationBusy] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [renderSettingsOpen, setRenderSettingsOpen] = useState(false)
  const [renderSettings, setRenderSettings] = useState<RenderSettingsState>(() =>
    buildDefaultRenderSettings(project.project_name),
  )
  const [generateModalOpen, setGenerateModalOpen] = useState(false)
  const [generationReviewOpen, setGenerationReviewOpen] = useState(false)
  const [pendingGeneration, setPendingGeneration] = useState<GenerationRecord | null>(null)
  const [generationForm, setGenerationForm] = useState<GenerationFormState>({
    prompt: '',
    mode: 'image',
    targetAssetId: '',
    frameRangeStart: '',
    frameRangeEnd: '',
    frameIndices: '',
    frameRepeatCount: '1',
    videoAspectRatio: '16:9',
    videoResolution: '720p',
    videoNegativePrompt: '',
    referenceSnippetId: '',
    referenceAssetId: '',
  })

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

  const mapActivityEvents = (
    events: EditSessionActivityEvent[] | undefined,
  ): EditSessionActivityEvent[] => (events || []).filter((event) => !!event.event_id)

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
      setActivityEvents(mapActivityEvents(detail.activity_events))
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
          setActivityEvents([])
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
    setActivityEvents([])
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

  const upsertAssets = useCallback((incoming: Array<Asset | null | undefined>) => {
    const validIncoming = incoming.filter((item): item is Asset => Boolean(item))
    if (validIncoming.length === 0) {
      return
    }
    setAssets((prev) => {
      const map = new Map(prev.map((asset) => [asset.asset_id, asset]))
      for (const asset of validIncoming) {
        map.set(asset.asset_id, asset)
      }
      const next = Array.from(map.values()).sort((a, b) => {
        const aTime = a.uploaded_at ? Date.parse(a.uploaded_at) : 0
        const bTime = b.uploaded_at ? Date.parse(b.uploaded_at) : 0
        return bTime - aTime
      })
      assetsRef.current = next
      return next
    })
  }, [])

  const loadSnippets = useCallback(async () => {
    setSnippetsLoading(true)
    try {
      const response = await api.listSnippets(config, project.project_id)
      setSnippets(response.snippets ?? [])
    } catch {
      setSnippets([])
    } finally {
      setSnippetsLoading(false)
    }
  }, [config, project.project_id])

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
      fetchAssets(true).catch(() => {})
    }, 6000)

    return () => {
      mounted = false
      window.clearInterval(interval)
    }
  }, [fetchAssets])

  useEffect(() => {
    if (!generateModalOpen) {
      return
    }
    loadSnippets().catch(() => {})
  }, [generateModalOpen, loadSnippets])

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
          setGpuInfo({
            available: false,
            detail: 'GPU detection failed',
            backend: 'none',
            encoders: { h264: false, h265: false },
          })
        }
      }
    }
    loadGpu()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    setRenderSettings(buildDefaultRenderSettings(project.project_name))
  }, [project.project_id, project.project_name])

  useEffect(() => {
    if (gpuInfo?.available === false) {
      setRenderSettings((prev) => (prev.useGpu ? { ...prev, useGpu: false } : prev))
    }
  }, [gpuInfo?.available, project.project_id])

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

  const parseFrameIndices = (raw: string): number[] | null => {
    const items = raw
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    if (items.length === 0) {
      return null
    }
    const numbers = items
      .map((item) => Number(item))
      .filter((value) => Number.isInteger(value) && value >= 0)
      .map((value) => Math.trunc(value))
    if (numbers.length === 0) {
      return null
    }
    return Array.from(new Set(numbers)).sort((a, b) => a - b)
  }

  const openGenerateModal = () => {
    setGenerationError(null)
    setGenerateModalOpen(true)
  }

  const handleCreateGeneration = async () => {
    const prompt = generationForm.prompt.trim()
    if (!prompt) {
      setGenerationError('Prompt is required.')
      return
    }

    const payload: GenerationCreatePayload = {
      prompt,
      mode: generationForm.mode,
      request_context: {
        source: 'desktop_editor',
      },
    }

    if (generationForm.referenceSnippetId) {
      payload.reference_snippet_id = generationForm.referenceSnippetId
    }
    if (generationForm.referenceAssetId) {
      payload.reference_asset_id = generationForm.referenceAssetId
    }

    const isFrameMode =
      generationForm.mode === 'insert_frames' || generationForm.mode === 'replace_frames'
    const isVideoMode = generationForm.mode === 'video'

    if (isVideoMode) {
      payload.model = 'veo-3.1-generate-preview'
      const videoParameters: Record<string, unknown> = {}
      if (generationForm.videoAspectRatio) {
        videoParameters.aspect_ratio = generationForm.videoAspectRatio
      }
      if (generationForm.videoResolution) {
        videoParameters.resolution = generationForm.videoResolution
      }
      const negativePrompt = generationForm.videoNegativePrompt.trim()
      if (negativePrompt) {
        videoParameters.negative_prompt = negativePrompt
      }
      if (Object.keys(videoParameters).length > 0) {
        payload.parameters = {
          ...(payload.parameters ?? {}),
          ...videoParameters,
        }
      }
    }

    if (isFrameMode) {
      if (!generationForm.targetAssetId) {
        setGenerationError('Select a target video asset for frame operations.')
        return
      }
      payload.target_asset_id = generationForm.targetAssetId

      const repeatCountValue = Number(generationForm.frameRepeatCount || '1')
      if (!Number.isInteger(repeatCountValue) || repeatCountValue < 1) {
        setGenerationError('Frame repeat count must be a whole number >= 1.')
        return
      }
      payload.frame_repeat_count = Math.trunc(repeatCountValue)

      const hasRangeStart = generationForm.frameRangeStart.trim().length > 0
      const hasRangeEnd = generationForm.frameRangeEnd.trim().length > 0
      if (hasRangeStart !== hasRangeEnd) {
        setGenerationError('Provide both frame range start and end, or leave both empty.')
        return
      }
      if (hasRangeStart && hasRangeEnd) {
        const startFrame = Number(generationForm.frameRangeStart)
        const endFrame = Number(generationForm.frameRangeEnd)
        if (!Number.isInteger(startFrame) || !Number.isInteger(endFrame)) {
          setGenerationError('Frame range values must be whole numbers.')
          return
        }
        if (startFrame < 0 || endFrame < 0) {
          setGenerationError('Frame range values must be non-negative.')
          return
        }
        payload.frame_range = {
          start_frame: Math.trunc(startFrame),
          end_frame: Math.trunc(endFrame),
        }
      }

      const parsedIndices = parseFrameIndices(generationForm.frameIndices)
      if (parsedIndices && parsedIndices.length > 0) {
        payload.frame_indices = parsedIndices
      }

      if (!payload.frame_range && !payload.frame_indices) {
        setGenerationError('Provide frame range or frame indices for frame operations.')
        return
      }
    }

    setGenerationBusy(true)
    setGenerationError(null)
    try {
      const response = await api.createGeneration(
        config,
        project.project_id,
        payload,
      )
      const generation = response.generation
      setPendingGeneration(generation)
      upsertAssets([generation.generated_asset ?? null, generation.applied_asset ?? null])
      setGenerateModalOpen(false)
      setGenerationReviewOpen(true)
      await fetchAssets(true)
    } catch (error) {
      setGenerationError((error as Error).message)
    } finally {
      setGenerationBusy(false)
    }
  }

  const handleGenerationDecision = async (decision: 'approve' | 'deny') => {
    if (!pendingGeneration) {
      return
    }
    setGenerationBusy(true)
    setGenerationError(null)
    try {
      const response = await api.decideGeneration(
        config,
        project.project_id,
        pendingGeneration.generation_id,
        { decision },
      )
      const generation = response.generation
      upsertAssets([generation.generated_asset ?? null, generation.applied_asset ?? null])
      if (generation.status === 'failed' && generation.error_message) {
        setGenerationError(generation.error_message)
      }
      setGenerationReviewOpen(false)
      setPendingGeneration(null)
      await fetchAssets(true)
    } catch (error) {
      setGenerationError((error as Error).message)
    } finally {
      setGenerationBusy(false)
    }
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
    setAgentBusy(true)

    try {
      let finalEventSeen = false
      await api.streamEditRequest(
        config,
        project.project_id,
        trimmed,
        (event) => {
          setActivityEvents((prev) => {
            const next = [...prev, event]
            return next.length > 300 ? next.slice(next.length - 300) : next
          })

          if (event.event_type !== 'final_result') {
            return
          }

          const meta = event.meta ?? {}
          const resultSessionId =
            typeof meta['session_id'] === 'string' ? meta['session_id'] : null
          const resultMessage =
            typeof meta['message'] === 'string' ? meta['message'] : 'Edit completed.'
          const resultPatches = Array.isArray(meta['pending_patches'])
            ? (meta['pending_patches'] as EditPatchSummary[])
            : []
          const resultVersion =
            typeof meta['new_version'] === 'number' ? meta['new_version'] : null

          finalEventSeen = true
          if (resultSessionId && resultSessionId !== sessionId) {
            setSessionId(resultSessionId)
            saveSessionId(project.project_id, resultSessionId)
          }
          setPendingPatches(resultPatches)
          if (resultVersion) {
            setTimelineVersion(resultVersion)
          }
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: resultMessage,
            },
          ])
        },
        sessionId,
      )

      if (!finalEventSeen) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: 'Edit finished, but no final response payload was received.',
          },
        ])
      }

      refreshSessions().catch(() => {})
      fetchAssets(true).catch(() => {})
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `There was an error: ${(error as Error).message}`,
        },
      ])
    } finally {
      setAgentBusy(false)
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
      fetchAssets(true).catch(() => {})
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
    const outputFilename = normalizeOutputFilename(
      renderSettings.outputFilename,
      project.project_name,
    )
    const preset = buildRenderPreset(renderSettings, gpuInfo)
    setOutputPanelOpen(true)
    try {
      const jobResponse = await api.createRenderJob(config, project.project_id, {
        job_type: 'export',
        execution_mode: 'local',
        preset,
        output_filename: outputFilename,
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
        preset,
      )

      const renderResult = await window.desktopApi.startRender({
        jobId,
        projectId: project.project_id,
        manifest: updatedManifest,
        outputName: outputFilename,
      })

      setRenderSettings((prev) =>
        prev.outputFilename === outputFilename
          ? prev
          : { ...prev, outputFilename },
      )
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

  const imageAssets = useMemo(
    () => assets.filter((asset) => asset.asset_type?.startsWith('image/')),
    [assets],
  )

  const videoAssets = useMemo(
    () => assets.filter((asset) => asset.asset_type?.startsWith('video/')),
    [assets],
  )

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
            {gpuInfo?.available
              ? `GPU (${formatGpuBackendLabel(gpuInfo.backend)})`
              : 'CPU Mode'}
          </span>
          <button
            onClick={() => setRenderSettingsOpen(true)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-xs font-medium text-neutral-300 hover:border-neutral-600 hover:bg-neutral-700 transition-colors"
          >
            Render Settings
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
                    <div className="flex flex-col items-center justify-center w-full h-full min-h-0 p-4">
                      <div className="w-full max-w-2xl max-h-full aspect-video rounded-xl border-2 border-dashed border-neutral-600 flex flex-col items-center justify-center bg-neutral-900/80 gap-3">
                        <Film className="h-12 w-12 text-neutral-500 shrink-0" />
                        <span className="text-sm text-neutral-400">No preview available</span>
                        <span className="text-xs text-neutral-500">
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
                  <button
                    onClick={openGenerateModal}
                    className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs font-medium text-neutral-300 hover:border-neutral-600 hover:bg-neutral-700 transition-colors"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Generate
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
          activityEvents={activityEvents}
          agentBusy={agentBusy}
          gpuAvailable={gpuInfo?.available}
        />
      </div>

      <Modal
        open={renderSettingsOpen}
        title="Render Settings"
        onClose={() => setRenderSettingsOpen(false)}
      >
        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Output Filename</span>
            <input
              type="text"
              value={renderSettings.outputFilename}
              onChange={(event) =>
                setRenderSettings((prev) => ({
                  ...prev,
                  outputFilename: event.target.value,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              placeholder="my_video.mp4"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs text-neutral-400">Quality</span>
              <select
                value={renderSettings.quality}
                onChange={(event) =>
                  setRenderSettings((prev) => ({
                    ...prev,
                    quality: event.target.value as RenderQuality,
                  }))
                }
                className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              >
                <option value="draft">Draft</option>
                <option value="standard">Standard</option>
                <option value="high">High</option>
                <option value="maximum">Maximum</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs text-neutral-400">Video Codec</span>
              <select
                value={renderSettings.codec}
                onChange={(event) =>
                  setRenderSettings((prev) => ({
                    ...prev,
                    codec: event.target.value as RenderCodec,
                  }))
                }
                className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              >
                <option value="h264">H.264</option>
                <option value="h265">H.265</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs text-neutral-400">Resolution</span>
              <select
                value={renderSettings.resolution}
                onChange={(event) =>
                  setRenderSettings((prev) => ({
                    ...prev,
                    resolution: event.target.value as RenderResolution,
                  }))
                }
                className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              >
                <option value="source">Source</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
                <option value="1440p">1440p</option>
                <option value="2160p">4K (2160p)</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs text-neutral-400">Frame Rate</span>
              <select
                value={renderSettings.frameRate}
                onChange={(event) =>
                  setRenderSettings((prev) => ({
                    ...prev,
                    frameRate: event.target.value as RenderFrameRate,
                  }))
                }
                className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              >
                <option value="source">Source</option>
                <option value="24">24 fps</option>
                <option value="30">30 fps</option>
                <option value="60">60 fps</option>
              </select>
            </label>
          </div>

          <label className="flex items-center justify-between rounded border border-neutral-800 bg-neutral-900 px-3 py-2">
            <div>
              <p className="text-sm text-neutral-200">Use GPU acceleration</p>
              <p className="text-2xs text-neutral-500">
                {gpuInfo?.available
                  ? `Available (${formatGpuBackendLabel(gpuInfo.backend)})`
                  : 'Unavailable on this machine'}
              </p>
            </div>
            <input
              type="checkbox"
              checked={renderSettings.useGpu}
              onChange={(event) =>
                setRenderSettings((prev) => ({
                  ...prev,
                  useGpu: event.target.checked,
                }))
              }
              disabled={!gpuInfo?.available}
              className="h-4 w-4 rounded border-neutral-600 bg-neutral-800 text-accent-500 focus:ring-accent-500/50 disabled:opacity-60"
            />
          </label>

          <div className="flex justify-end gap-3">
            <button
              onClick={() =>
                setRenderSettings({
                  ...buildDefaultRenderSettings(project.project_name),
                  useGpu: gpuInfo?.available ?? false,
                })
              }
              className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800"
            >
              Reset
            </button>
            <button
              onClick={() => setRenderSettingsOpen(false)}
              className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600"
            >
              Done
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={generateModalOpen}
        title="Generate Asset"
        onClose={() => {
          if (!generationBusy) {
            setGenerateModalOpen(false)
          }
        }}
      >
        <div className="space-y-4">
          {generationError && (
            <div className="rounded border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-400">
              {generationError}
            </div>
          )}

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Prompt</span>
            <textarea
              rows={3}
              value={generationForm.prompt}
              onChange={(event) =>
                setGenerationForm((prev) => ({ ...prev, prompt: event.target.value }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              placeholder="Describe what to generate"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Mode</span>
            <select
              value={generationForm.mode}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  mode: event.target.value as GenerationMode,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="image">Image Generation</option>
              <option value="video">Video Generation (Veo 3.1)</option>
              <option value="replace_frames">Replace Frames</option>
              <option value="insert_frames">Insert Frames</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Reference Snippet (optional)</span>
            <select
              value={generationForm.referenceSnippetId}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  referenceSnippetId: event.target.value,
                  referenceAssetId: event.target.value ? '' : prev.referenceAssetId,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="">None</option>
              {snippets.map((snippet) => (
                <option key={snippet.snippet_id} value={snippet.snippet_id}>
                  {snippet.snippet_type} - {snippet.snippet_id.slice(0, 8)}
                </option>
              ))}
            </select>
            {snippetsLoading && (
              <p className="text-2xs text-neutral-500">Loading snippets...</p>
            )}
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Reference Image Asset (optional)</span>
            <select
              value={generationForm.referenceAssetId}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  referenceAssetId: event.target.value,
                  referenceSnippetId: event.target.value ? '' : prev.referenceSnippetId,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="">None</option>
              {imageAssets.map((asset) => (
                <option key={asset.asset_id} value={asset.asset_id}>
                  {asset.asset_name}
                </option>
              ))}
            </select>
          </label>

          {(generationForm.mode === 'insert_frames' ||
            generationForm.mode === 'replace_frames') && (
            <>
              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Target Video Asset</span>
                <select
                  value={generationForm.targetAssetId}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      targetAssetId: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="">Select video asset</option>
                  {videoAssets.map((asset) => (
                    <option key={asset.asset_id} value={asset.asset_id}>
                      {asset.asset_name}
                    </option>
                  ))}
                </select>
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1">
                  <span className="text-xs text-neutral-400">Frame Start</span>
                  <input
                    type="number"
                    min={0}
                    value={generationForm.frameRangeStart}
                    onChange={(event) =>
                      setGenerationForm((prev) => ({
                        ...prev,
                        frameRangeStart: event.target.value,
                      }))
                    }
                    className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                    placeholder="e.g. 10"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-neutral-400">Frame End</span>
                  <input
                    type="number"
                    min={0}
                    value={generationForm.frameRangeEnd}
                    onChange={(event) =>
                      setGenerationForm((prev) => ({
                        ...prev,
                        frameRangeEnd: event.target.value,
                      }))
                    }
                    className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                    placeholder="e.g. 20"
                  />
                </label>
              </div>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">
                  Frame Indices (optional, comma-separated)
                </span>
                <input
                  type="text"
                  value={generationForm.frameIndices}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      frameIndices: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="e.g. 12,18,24"
                />
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Frame Repeat Count</span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={generationForm.frameRepeatCount}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      frameRepeatCount: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="1"
                />
                <p className="text-2xs text-neutral-500">
                  Reuse the same generated image across this many consecutive frames per selected frame.
                </p>
              </label>
            </>
          )}

          {generationForm.mode === 'video' && (
            <>
              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Aspect Ratio</span>
                <select
                  value={generationForm.videoAspectRatio}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoAspectRatio: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="16:9">16:9 (Landscape)</option>
                  <option value="9:16">9:16 (Portrait)</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Resolution</span>
                <select
                  value={generationForm.videoResolution}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoResolution: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="720p">720p</option>
                  <option value="1080p">1080p</option>
                  <option value="4k">4K</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Negative Prompt (optional)</span>
                <input
                  type="text"
                  value={generationForm.videoNegativePrompt}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoNegativePrompt: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="e.g. cartoon, low quality"
                />
              </label>
            </>
          )}

          <div className="flex justify-end gap-3">
            <button
              onClick={() => setGenerateModalOpen(false)}
              disabled={generationBusy}
              className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                void handleCreateGeneration()
              }}
              disabled={generationBusy}
              className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 disabled:opacity-60"
            >
              {generationBusy ? 'Generating...' : 'Generate'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={generationReviewOpen && Boolean(pendingGeneration)}
        title="Review Generated Asset"
        onClose={() => {
          if (!generationBusy) {
            setGenerationReviewOpen(false)
            setPendingGeneration(null)
          }
        }}
      >
        <div className="space-y-4">
          {pendingGeneration?.generated_preview_url ? (
            pendingGeneration.generated_asset?.asset_type?.startsWith('video/') ? (
              <video
                src={pendingGeneration.generated_preview_url}
                controls
                className="w-full rounded border border-neutral-700 bg-neutral-950 object-contain"
              />
            ) : (
              <img
                src={pendingGeneration.generated_preview_url}
                alt="Generated preview"
                className="w-full rounded border border-neutral-700 bg-neutral-950 object-contain"
              />
            )
          ) : (
            <div className="rounded border border-neutral-800 bg-neutral-900 px-3 py-8 text-center text-xs text-neutral-500">
              Preview unavailable. You can still approve or deny.
            </div>
          )}

          <div className="rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs text-neutral-400">
            <p className="truncate">Prompt: {pendingGeneration?.prompt}</p>
            <p>Mode: {pendingGeneration?.mode}</p>
            {(pendingGeneration?.mode === 'insert_frames' ||
              pendingGeneration?.mode === 'replace_frames') && (
              <p>Frame repeat count: {pendingGeneration?.frame_repeat_count ?? 1}</p>
            )}
            {pendingGeneration?.mode === 'video' && <p>Model: {pendingGeneration?.model}</p>}
          </div>

          {generationError && (
            <div className="rounded border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-400">
              {generationError}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <button
              onClick={() => {
                void handleGenerationDecision('deny')
              }}
              disabled={generationBusy}
              className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-60"
            >
              Deny
            </button>
            <button
              onClick={() => {
                void handleGenerationDecision('approve')
              }}
              disabled={generationBusy}
              className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 disabled:opacity-60"
            >
              Approve
            </button>
          </div>
        </div>
      </Modal>

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
