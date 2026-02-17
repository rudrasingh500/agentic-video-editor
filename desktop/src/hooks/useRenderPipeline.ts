import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { buildLocalManifest } from '../lib/buildLocalManifest'
import { useAssetStore } from '../stores/assetStore'
import { useRenderStore } from '../stores/renderStore'
import { useTimelineStore } from '../stores/timelineStore'
import { useUiStore } from '../stores/uiStore'
import { useConnectionStore } from '../hooks/useConnectionStatus'
import {
  buildDefaultRenderSettings,
  buildRenderPreset,
  normalizeOutputFilename,
  type RenderSettingsState,
} from '../components/editor/RenderSettingsModal'

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

const toFileUrl = (filePath: string) => {
  const normalized = filePath.replace(/\\/g, '/')
  const prefix = normalized.startsWith('/') ? '' : '/'
  return encodeURI(`file://${prefix}${normalized}`)
}

type UseRenderPipelineOptions = {
  config: AppConfig
  projectId: string
  projectName: string
  onError: (message: string) => void
}

const useRenderPipeline = ({
  config,
  projectId,
  projectName,
  onError,
}: UseRenderPipelineOptions) => {
  const assetCache = useAssetStore((state) => state.assetCache)
  const rememberAssetPath = useAssetStore((state) => state.rememberAssetPath)
  const gpuInfo = useRenderStore((state) => state.gpuInfo)
  const setGpuInfo = useRenderStore((state) => state.setGpuInfo)
  const renderState = useRenderStore((state) => state.renderState)
  const setRenderState = useRenderStore((state) => state.setRenderState)
  const renderLogs = useRenderStore((state) => state.renderLogs)
  const setRenderLogs = useRenderStore((state) => state.setRenderLogs)
  const appendRenderLog = useRenderStore((state) => state.appendRenderLog)
  const previewPath = useRenderStore((state) => state.previewPath)
  const setPreviewPath = useRenderStore((state) => state.setPreviewPath)
  const previewKey = useRenderStore((state) => state.previewKey)
  const bumpPreviewKey = useRenderStore((state) => state.bumpPreviewKey)
  const setOutputPanelOpen = useUiStore((state) => state.setOutputPanelOpen)

  const [renderSettingsOpen, setRenderSettingsOpen] = useState(false)
  const [renderSettings, setRenderSettings] = useState<RenderSettingsState>(() =>
    buildDefaultRenderSettings(projectName),
  )
  const agentRenderRef = useRef<{ running: boolean; lastJobId: string | null }>({
    running: false,
    lastJobId: null,
  })

  // Load GPU info on mount
  useEffect(() => {
    let active = true
    const loadGpu = async () => {
      try {
        const result = await window.desktopApi.getGpuInfo()
        if (active) {
          setGpuInfo(result)
        }
      } catch {
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
  }, [setGpuInfo])

  // Reset render settings when project changes
  useEffect(() => {
    setRenderSettings(buildDefaultRenderSettings(projectName))
  }, [projectId, projectName])

  // Disable GPU in settings if unavailable
  useEffect(() => {
    if (gpuInfo?.available === false) {
      setRenderSettings((prev) => (prev.useGpu ? { ...prev, useGpu: false } : prev))
    }
  }, [gpuInfo?.available, projectId])

  const uploadRenderOutput = useCallback(
    async (jobId: string, outputPath: string) => {
      try {
        const filename = outputPath.split(/[\\/]/).pop() || `${jobId}.mp4`
        const uploadInfo = await api.getOutputUploadUrl(
          config,
          projectId,
          filename,
          'video/mp4',
        )

        const uploadResult = (await window.desktopApi.uploadRenderOutput({
          filePath: outputPath,
          uploadUrl: uploadInfo.upload_url,
          contentType: 'video/mp4',
        })) as UploadResult

        await api.shareOutput(config, projectId, uploadInfo.gcs_path, null)

        await api.reportRenderProgress(config, projectId, jobId, {
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
        onError(`Render upload failed: ${(error as Error).message}`)
      }
    },
    [config, projectId, setRenderState, onError],
  )

  // Listen for render events from electron
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
      if (payload.status === 'rendering' || payload.status === 'processing') {
        setOutputPanelOpen(true)
      }
      // Only report progress to backend when online
      if (payload.status && useConnectionStore.getState().state === 'online') {
        api.reportRenderProgress(
          config,
          projectId,
          event.jobId,
          payload as Record<string, unknown>,
        ).catch(() => {})
      }
    })

    const unsubscribeComplete = window.desktopApi.onRenderComplete((event) => {
      if (event.jobId !== renderState.jobId) {
        return
      }
      setPreviewPath(event.outputPath)
      bumpPreviewKey()

      const online = useConnectionStore.getState().state === 'online'

      if (event.code === 0 && online) {
        // Online: upload to GCS as before
        setRenderState((prev) => ({
          ...prev,
          status: 'uploading',
          outputPath: event.outputPath,
        }))
        void uploadRenderOutput(event.jobId, event.outputPath)
      } else if (event.code === 0) {
        // Offline: render succeeded, skip upload, queue for later sync
        setRenderState((prev) => ({
          ...prev,
          status: 'completed',
          outputPath: event.outputPath,
        }))
        const filename = event.outputPath.split(/[\\/]/).pop() ?? 'output.mp4'
        useRenderStore.getState().addPendingRenderUpload({
          jobId: event.jobId,
          projectId,
          outputPath: event.outputPath,
          outputFilename: filename,
          completedAt: new Date().toISOString(),
        })
      } else {
        // Render failed
        setRenderState((prev) => ({
          ...prev,
          status: 'failed',
          outputPath: event.outputPath,
        }))
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
      for (const line of lines) {
        appendRenderLog(line)
      }
    })

    return () => {
      unsubscribeProgress()
      unsubscribeComplete()
      unsubscribeLogs()
    }
  }, [
    appendRenderLog,
    bumpPreviewKey,
    config,
    projectId,
    renderState.jobId,
    setOutputPanelOpen,
    setPreviewPath,
    setRenderState,
    uploadRenderOutput,
  ])

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
          projectId,
          assetId,
        )
        const assetInfo = useAssetStore.getState().assets.find((asset) => asset.asset_id === assetId)
        const cached = await window.desktopApi.downloadAsset({
          assetId,
          url: download.url,
          filename: assetInfo?.asset_name,
        })
        updatedAssetMap[assetId] = cached.path
        rememberAssetPath(assetId, cached.path)
      }

      return {
        ...manifestData,
        asset_map: updatedAssetMap,
        preset: presetOverride ?? (manifestData.preset as Record<string, unknown>),
        execution_mode: 'local',
      }
    },
    [assetCache, config, projectId, rememberAssetPath],
  )

  // Poll for agent-queued render jobs
  useEffect(() => {
    let active = true

    const pollQueuedRenders = async () => {
      if (!active || agentRenderRef.current.running) {
        return
      }

      // Skip polling when offline — no backend to check
      if (useConnectionStore.getState().state !== 'online') {
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
          projectId,
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
          projectId,
          candidate.job_id,
        )
        const manifestData = await fetch(manifestResponse.manifest_url).then((res) =>
          res.json(),
        )

        const updatedManifest = await prepareLocalManifest(manifestData)
        const outputName = `${projectName.replace(/\s+/g, '_')}_preview.mp4`
        const renderResult = await window.desktopApi.startRender({
          jobId: candidate.job_id,
          projectId,
          manifest: updatedManifest,
          outputName,
        })

        setRenderState((prev) => ({
          ...prev,
          outputPath: renderResult.outputPath,
        }))
      } catch {
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
  }, [
    config,
    prepareLocalManifest,
    projectId,
    projectName,
    renderState.status,
    setOutputPanelOpen,
    setRenderLogs,
    setRenderState,
  ])

  const handleRender = useCallback(async () => {
    const outputFilename = normalizeOutputFilename(
      renderSettings.outputFilename,
      projectName,
    )
    const preset = buildRenderPreset(renderSettings, gpuInfo)
    setOutputPanelOpen(true)

    const online = useConnectionStore.getState().state === 'online'

    if (online) {
      // ── Online path: create job on backend, fetch manifest, render locally ──
      try {
        const jobResponse = await api.createRenderJob(config, projectId, {
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
          projectId,
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
          projectId,
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
        onError(`Render failed: ${(error as Error).message}`)
      }
    } else {
      // ── Offline path: build manifest client-side, render directly ──
      try {
        const timeline = useTimelineStore.getState().timeline
        if (!timeline) {
          onError('No timeline available to render.')
          return
        }

        const version =
          useTimelineStore.getState().version ??
          useTimelineStore.getState().localVersion

        const jobId = `local:${crypto.randomUUID()}`
        setRenderLogs([])
        setRenderState({ jobId, status: 'queued', progress: 0 })

        const assetCache = useAssetStore.getState().assetCache
        const manifest = buildLocalManifest(
          timeline,
          version,
          projectId,
          jobId,
          preset as Parameters<typeof buildLocalManifest>[4],
          outputFilename,
          assetCache,
        )

        // Resolve asset paths: for offline, all assets must already be cached
        // locally. The manifest already has local paths from assetCache.
        // We still need to verify files exist and resolve any that are cached
        // but at a different path.
        const resolvedAssetMap: Record<string, string> = {}
        for (const [assetId, localPath] of Object.entries(manifest.asset_map)) {
          const exists = await window.desktopApi.fileExists({ path: localPath })
          if (exists) {
            resolvedAssetMap[assetId] = localPath
          }
          // If the file doesn't exist locally, skip it — the renderer will
          // report the missing asset.
        }

        const finalManifest = {
          ...manifest,
          asset_map: resolvedAssetMap,
        }

        const renderResult = await window.desktopApi.startRender({
          jobId,
          projectId,
          manifest: finalManifest as Record<string, unknown>,
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
        onError(`Render failed: ${(error as Error).message}`)
      }
    }
  }, [
    config,
    gpuInfo,
    onError,
    prepareLocalManifest,
    projectId,
    projectName,
    renderSettings,
    setOutputPanelOpen,
    setRenderLogs,
    setRenderState,
  ])

  const syncPendingRenders = useCallback(async () => {
    const online = useConnectionStore.getState().state === 'online'
    if (!online) {
      return
    }

    const pending = useRenderStore.getState().pendingRenderUploads.filter(
      (r) => r.projectId === projectId,
    )
    if (pending.length === 0) {
      return
    }

    for (const entry of pending) {
      try {
        const exists = await window.desktopApi.fileExists({ path: entry.outputPath })
        if (!exists) {
          // File no longer exists — remove from queue
          useRenderStore.getState().removePendingRenderUpload(entry.jobId)
          continue
        }

        const filename = entry.outputFilename
        const uploadInfo = await api.getOutputUploadUrl(
          config,
          projectId,
          filename,
          'video/mp4',
        )

        await window.desktopApi.uploadRenderOutput({
          filePath: entry.outputPath,
          uploadUrl: uploadInfo.upload_url,
          contentType: 'video/mp4',
        })

        await api.shareOutput(config, projectId, uploadInfo.gcs_path, null)

        useRenderStore.getState().removePendingRenderUpload(entry.jobId)
      } catch {
        // Upload failed — will retry on next online transition
      }
    }
  }, [config, projectId])

  const previewUrl = useMemo(() => {
    if (!previewPath) {
      return null
    }
    return toFileUrl(previewPath)
  }, [previewPath])

  return {
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
  }
}

export default useRenderPipeline
