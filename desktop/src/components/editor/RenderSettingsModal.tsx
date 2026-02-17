import Modal from '../Modal'
import type { GpuInfo } from '../../stores/renderStore'

export type RenderQuality = 'draft' | 'standard' | 'high' | 'maximum'

export type RenderCodec = 'h264' | 'h265'

export type RenderResolution = 'source' | '720p' | '1080p' | '1440p' | '2160p'

export type RenderFrameRate = 'source' | '24' | '30' | '60'

export type RenderSettingsState = {
  outputFilename: string
  quality: RenderQuality
  codec: RenderCodec
  resolution: RenderResolution
  frameRate: RenderFrameRate
  useGpu: boolean
}

export const RENDER_QUALITY_DEFAULTS: Record<
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

export const RENDER_RESOLUTION_DIMENSIONS: Record<
  RenderResolution,
  { width: number | null; height: number | null }
> = {
  source: { width: null, height: null },
  '720p': { width: 1280, height: 720 },
  '1080p': { width: 1920, height: 1080 },
  '1440p': { width: 2560, height: 1440 },
  '2160p': { width: 3840, height: 2160 },
}

export const buildDefaultRenderSettings = (projectName: string): RenderSettingsState => ({
  outputFilename: `${projectName.replace(/\s+/g, '_')}.mp4`,
  quality: 'standard',
  codec: 'h264',
  resolution: 'source',
  frameRate: 'source',
  useGpu: true,
})

export const normalizeOutputFilename = (rawFilename: string, projectName: string) => {
  const fallback = `${projectName.replace(/\s+/g, '_')}.mp4`
  const candidate = rawFilename.trim() || fallback
  const sanitized = candidate.replace(/[\\/:*?"<>|]+/g, '_')
  return sanitized.toLowerCase().endsWith('.mp4') ? sanitized : `${sanitized}.mp4`
}

export const buildRenderPreset = (settings: RenderSettingsState, gpuInfo: GpuInfo | null) => {
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

const formatGpuBackendLabel = (backend: GpuInfo['backend']) => {
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

type RenderSettingsModalProps = {
  open: boolean
  onClose: () => void
  settings: RenderSettingsState
  onSettingsChange: React.Dispatch<React.SetStateAction<RenderSettingsState>>
  gpuInfo: GpuInfo | null
  projectName: string
}

const RenderSettingsModal = ({
  open,
  onClose,
  settings,
  onSettingsChange,
  gpuInfo,
  projectName,
}: RenderSettingsModalProps) => (
  <Modal open={open} title="Render Settings" onClose={onClose}>
    <div className="space-y-4">
      <label className="block space-y-1">
        <span className="text-xs text-neutral-400">Output Filename</span>
        <input
          type="text"
          value={settings.outputFilename}
          onChange={(event) =>
            onSettingsChange((prev) => ({
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
            value={settings.quality}
            onChange={(event) =>
              onSettingsChange((prev) => ({
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
            value={settings.codec}
            onChange={(event) =>
              onSettingsChange((prev) => ({
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
            value={settings.resolution}
            onChange={(event) =>
              onSettingsChange((prev) => ({
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
            value={settings.frameRate}
            onChange={(event) =>
              onSettingsChange((prev) => ({
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
          checked={settings.useGpu}
          onChange={(event) =>
            onSettingsChange((prev) => ({
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
            onSettingsChange({
              ...buildDefaultRenderSettings(projectName),
              useGpu: gpuInfo?.available ?? false,
            })
          }
          className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800"
        >
          Reset
        </button>
        <button
          onClick={onClose}
          className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600"
        >
          Done
        </button>
      </div>
    </div>
  </Modal>
)

export default RenderSettingsModal
