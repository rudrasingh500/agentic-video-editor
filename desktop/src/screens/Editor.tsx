import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from 'react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { loadAssetCache, saveAssetCache, type AssetCacheIndex } from '../lib/assetCache'
import { loadSessionId, saveSessionId } from '../lib/chatSessions'
import Modal from '../components/Modal'
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

  return (
    <div className="min-h-screen bg-base-900 bg-radial-slate text-ink-100">
      <div className="flex min-h-screen">
        <aside className="flex w-20 flex-col items-center gap-4 border-r border-white/5 bg-base-800/70 py-8">
          <button className="rounded-2xl bg-white/5 p-2" onClick={onBack}>
            <span className="text-lg">🏠</span>
          </button>
          <button className="rounded-2xl bg-white/10 p-2">
            <span className="text-lg">🎬</span>
          </button>
          <button className="rounded-2xl bg-white/5 p-2">
            <span className="text-lg">🧰</span>
          </button>
          <button
            className="rounded-2xl bg-white/5 p-2"
            onClick={onOpenSettings}
          >
            <span className="text-lg">⚙️</span>
          </button>
        </aside>

        <main className="flex flex-1 flex-col gap-4 px-6 py-6">
          <header className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-ink-400">
                Preview
              </div>
              <div className="text-lg font-semibold text-ink-100">
                {project.project_name}
              </div>
              <div className="text-xs text-ink-400">
                Timeline v{timelineVersion ?? '—'}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="rounded-full border border-white/10 px-3 py-1 text-xs text-ink-300">
                Fit
              </div>
              <button
                onClick={handleRender}
                className="rounded-full bg-accent-500 px-4 py-2 text-xs font-semibold text-white shadow-glow hover:bg-accent-600"
              >
                Render
              </button>
            </div>
          </header>

          <section className="flex flex-1 flex-col gap-4">
            <div className="rounded-2xl border border-white/10 bg-panel-glass p-4 shadow-soft">
              <div className="flex h-[360px] items-center justify-center rounded-xl border border-white/5 bg-base-800/40">
                {previewUrl ? (
                  <video
                    key={previewKey}
                    src={previewUrl}
                    controls
                    className="h-full w-full rounded-xl object-contain"
                  />
                ) : (
                  <span className="text-sm text-ink-400">Video Preview</span>
                )}
              </div>
              <div className="mt-4 flex items-center gap-3">
                <button className="rounded-full bg-white/10 px-3 py-1 text-xs text-ink-200">
                  ▶
                </button>
                <div className="h-2 flex-1 rounded-full bg-base-700">
                  <div className="h-2 w-1/2 rounded-full bg-gradient-to-r from-accent-500 to-glow-cyan" />
                </div>
                <span className="text-xs text-ink-400">00:02:43 / 00:15:57</span>
              </div>
              {renderState.status ? (
                <div className="mt-3 flex items-center justify-between text-xs text-ink-300">
                  <span>
                    Render status: {renderState.status}
                  </span>
                  <span>{renderState.progress ?? 0}%</span>
                </div>
              ) : null}
            </div>

            <div className="rounded-2xl border border-white/10 bg-panel-glass p-4 shadow-soft">
              <div className="flex items-center justify-between text-xs text-ink-300">
                <span>Render logs</span>
                {renderLogs.length > 0 ? (
                  <button
                    onClick={() => setRenderLogs([])}
                    className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-ink-300 hover:border-white/30"
                  >
                    Clear
                  </button>
                ) : null}
              </div>
              <div className="mt-3 max-h-40 overflow-auto rounded-lg border border-white/5 bg-base-900/60 px-3 py-2 text-[11px] text-ink-200 font-mono whitespace-pre-wrap break-all">
                {renderLogs.length > 0 ? (
                  renderLogs.map((line, index) => (
                    <div key={`${index}-${line.slice(0, 12)}`}>{line}</div>
                  ))
                ) : (
                  <div className="text-ink-500">No render logs yet.</div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-panel-glass p-4 shadow-soft">
              <div className="flex items-center gap-4 text-xs text-ink-300">
                <button className="text-ink-100">Assets</button>
                <button className="hover:text-ink-100">Media</button>
                <button className="hover:text-ink-100">Audio</button>
                <button className="hover:text-ink-100">Graphics</button>
                <button className="hover:text-ink-100">Captions</button>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={handleUploadClick}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-ink-200 hover:border-white/30"
                >
                  Import
                </button>
                <button className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-ink-200 hover:border-white/30">
                  Record VO
                </button>
                <button className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-ink-200 hover:border-white/30">
                  Generate Captions
                </button>
                {assetsLoading ? (
                  <span className="text-xs text-ink-400">Loading assets…</span>
                ) : null}
              </div>
              {assetsError ? (
                <div className="mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  {assetsError}
                </div>
              ) : null}
              <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
                {assets.map((asset) => (
                  <div
                    key={asset.asset_id}
                    className="rounded-xl border border-white/10 bg-base-800/40 p-3"
                  >
                    <div className="h-16 rounded-lg bg-gradient-to-br from-accent-500/70 via-glow-violet/70 to-glow-magenta/70" />
                    <div className="mt-2 flex items-start justify-between gap-2">
                      <div className="text-xs font-semibold text-ink-100">
                        {asset.asset_name}
                      </div>
                      <button
                        type="button"
                        aria-label={`Delete ${asset.asset_name}`}
                        onClick={() => setAssetToDelete(asset)}
                        className="rounded-full border border-transparent p-1 text-ink-400 transition hover:border-red-400/40 hover:text-red-300"
                      >
                        🗑️
                      </button>
                    </div>
                    <div className="mt-1 text-[11px] text-ink-400">
                      {asset.indexing_status ?? 'ready'}
                    </div>
                  </div>
                ))}
                {assets.length === 0 && !assetsLoading ? (
                  <div className="rounded-xl border border-dashed border-white/20 p-6 text-xs text-ink-400">
                    Drag files here or use Import to add media.
                  </div>
                ) : null}
              </div>
              <div className="mt-4 text-xs text-ink-400">Summary Timeline</div>
              <div className="mt-2 h-2 w-full rounded-full bg-base-700">
                <div className="h-2 w-1/3 rounded-full bg-gradient-to-r from-glow-magenta to-glow-violet" />
              </div>
            </div>
          </section>
        </main>

        <aside className="flex w-[340px] flex-col gap-4 border-l border-white/5 bg-base-800/70 px-4 py-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-ink-400">
                Assistant
              </div>
              <div className="text-xs text-ink-400">
                GPU: {gpuInfo?.available ? 'NVENC ready' : 'CPU only'}
              </div>
            </div>
            <button
              onClick={handleNewSession}
              className="rounded-full border border-white/10 px-3 py-1 text-[11px] text-ink-200 hover:border-white/30"
            >
              New session
            </button>
          </div>

          <div className="rounded-xl border border-white/10 bg-base-900/80 p-3 text-xs text-ink-200">
            <div className="mb-2 flex items-center justify-between text-[11px] text-ink-400">
              <span>Session</span>
              {sessionsLoading ? <span>Loading...</span> : null}
            </div>
            <select
              value={sessionId ?? ''}
              onChange={(event) => handleSessionChange(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-base-800 px-2 py-2 text-xs text-ink-100"
            >
              <option value="">New session</option>
              {sessions.map((session) => {
                const label = session.title?.trim() || `Session ${session.session_id.slice(0, 8)}`
                const status = session.status ? ` - ${session.status}` : ''
                return (
                  <option key={session.session_id} value={session.session_id}>
                    {label}{status}
                  </option>
                )
              })}
            </select>
            {sessionsError ? (
              <div className="mt-2 rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1 text-[11px] text-red-200">
                {sessionsError}
              </div>
            ) : null}
          </div>

          <div className="flex-1 space-y-3 overflow-auto rounded-xl border border-white/5 bg-base-900/60 p-3 text-xs text-ink-200">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`rounded-lg px-3 py-2 ${
                  message.role === 'user'
                    ? 'bg-accent-500/20 text-ink-100'
                    : 'bg-white/5 text-ink-200'
                }`}
              >
                {message.content}
              </div>
            ))}
            {messages.length === 0 ? (
              <div className="text-ink-400">
                Ask the assistant to tighten pacing, add captions, or cut silences.
              </div>
            ) : null}
          </div>

          <div className="rounded-xl border border-white/10 bg-base-900/80 p-3">
            <textarea
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  handleSendMessage()
                }
              }}
              rows={3}
              className="w-full resize-none rounded-lg border border-white/10 bg-base-800 px-3 py-2 text-xs text-ink-100"
              placeholder="Change: remove silence and make it punchier"
            />
            <div className="mt-3 flex items-center justify-between">
              <button
                onClick={handleSendMessage}
                className="rounded-full bg-accent-500 px-3 py-1 text-xs font-semibold text-white shadow-glow hover:bg-accent-600"
              >
                Send
              </button>
            </div>
          </div>

          {pendingPatches.length > 0 ? (
            <div className="rounded-xl border border-white/10 bg-base-900/80 p-3 text-xs text-ink-300">
              <div className="mb-2 font-semibold text-ink-100">Change Set</div>
              <ul className="space-y-1">
                {pendingPatches.map((patch) => (
                  <li key={patch.patch_id}>
                    {patch.description || patch.agent_type} ({patch.operation_count})
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <button className="rounded-full border border-white/10 px-3 py-1 text-xs text-ink-200">
                  Preview Changes
                </button>
                <button
                  onClick={handleApplyPatches}
                  className="rounded-full bg-accent-500 px-3 py-1 text-xs font-semibold text-white"
                >
                  Apply
                </button>
              </div>
            </div>
          ) : null}
        </aside>
      </div>

      <Modal
        open={Boolean(assetToDelete)}
        title="Delete Asset"
        onClose={() => setAssetToDelete(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-ink-300">
            Delete {assetToDelete ? `"${assetToDelete.asset_name}"` : 'this asset'}?
            This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setAssetToDelete(null)}
              className="rounded-full border border-white/10 px-4 py-2 text-xs text-ink-300"
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
              className="rounded-full bg-red-500 px-4 py-2 text-xs font-semibold text-white"
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
