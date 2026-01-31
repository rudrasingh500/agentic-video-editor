import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { loadAssetCache, saveAssetCache, type AssetCacheIndex } from '../lib/assetCache'
import type { Asset, EditPatchSummary, Project } from '../lib/types'

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
  return `file://${normalized.startsWith('/') ? '' : '/'}${normalized}`
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
  const [previewPath, setPreviewPath] = useState<string | null>(null)
  const [assetCache, setAssetCache] = useState<AssetCacheIndex>(() => loadAssetCache())
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let active = true
    const loadAssets = async () => {
      setAssetsLoading(true)
      setAssetsError(null)
      try {
        const response = await api.listAssets(config, project.project_id)
        if (active) {
          setAssets(response.assets ?? [])
        }
      } catch (error) {
        if (active) {
          setAssetsError((error as Error).message)
        }
      } finally {
        if (active) {
          setAssetsLoading(false)
        }
      }
    }
    loadAssets()
    return () => {
      active = false
    }
  }, [config, project.project_id])

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
        status: event.code === 0 ? 'completed' : 'failed',
        outputPath: event.outputPath,
      }))
      setPreviewPath(event.outputPath)
    })

    return () => {
      unsubscribeProgress()
      unsubscribeComplete()
    }
  }, [config, project.project_id, renderState.jobId])

  const updateAssetCache = (assetId: string, path: string) => {
    setAssetCache((prev) => {
      const next = { ...prev, [assetId]: path }
      saveAssetCache(next)
      return next
    })
  }

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
        setAssets((prev) => [response.asset, ...prev])

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
      setSessionId(response.session_id)
      setPendingPatches(response.pending_patches ?? [])
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: response.message,
        },
      ])
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
      setRenderState({ jobId, status: 'queued', progress: 0 })

      const manifestResponse = await api.getRenderManifest(
        config,
        project.project_id,
        jobId,
      )
      const manifestData = await fetch(manifestResponse.manifest_url).then((res) =>
        res.json(),
      )

      const updatedAssetMap: Record<string, string> = {}
      for (const assetId of Object.keys(
        manifestData.asset_map as Record<string, string>,
      )) {
        if (assetCache[assetId]) {
          updatedAssetMap[assetId] = assetCache[assetId]
          continue
        }

        const download = await api.getAssetDownloadUrl(
          config,
          project.project_id,
          assetId,
        )
        const assetInfo = assets.find((asset) => asset.asset_id === assetId)
        const cached = await window.desktopApi.downloadAsset({
          assetId,
          url: download.url,
          filename: assetInfo?.asset_name,
        })
        updatedAssetMap[assetId] = cached.path
        updateAssetCache(assetId, cached.path)
      }

      const updatedManifest = {
        ...manifestData,
        asset_map: updatedAssetMap,
        preset: buildStandardPreset(useGpu),
        execution_mode: 'local',
      }

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
                    <div className="mt-2 text-xs font-semibold text-ink-100">
                      {asset.asset_name}
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
              <div className="text-sm font-semibold text-ink-100">GPT-4o</div>
              <div className="text-xs text-ink-400">
                GPU: {gpuInfo?.available ? 'NVENC ready' : 'CPU only'}
              </div>
            </div>
            <button className="rounded-full border border-white/10 px-2 py-1 text-xs text-ink-300">
              ⋯
            </button>
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
              <button className="text-xs text-ink-400">Change alias</button>
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-base-900/80 p-3 text-xs text-ink-300">
            <div className="mb-2 font-semibold text-ink-100">Change Set</div>
            {pendingPatches.length > 0 ? (
              <ul className="space-y-1">
                {pendingPatches.map((patch) => (
                  <li key={patch.patch_id}>
                    {patch.description || patch.agent_type} ({patch.operation_count})
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-ink-400">No pending changes.</div>
            )}
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
        </aside>
      </div>

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
