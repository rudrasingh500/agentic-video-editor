import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Download, Film, Home, Sparkles, Users } from 'lucide-react'

import type { GpuBackend } from '../../stores/renderStore'
import ConnectionBadge from './ConnectionBadge'

type HeaderBarProps = {
  projectName: string
  timelineVersion: number | null
  gpuAvailable: boolean
  gpuBackend: GpuBackend
  onBack: () => void
  onOpenRenderSettings: () => void
  onRender: () => void
  onOpenPeople: () => void
  onOpenGenerate: () => void
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

const HeaderBar = ({
  projectName,
  timelineVersion,
  gpuAvailable,
  gpuBackend,
  onBack,
  onOpenRenderSettings,
  onRender,
  onOpenPeople,
  onOpenGenerate,
}: HeaderBarProps) => {
  const [toolsOpen, setToolsOpen] = useState(false)
  const toolsRef = useRef<HTMLDivElement>(null)

  const closeTools = useCallback(() => setToolsOpen(false), [])

  useEffect(() => {
    if (!toolsOpen) return
    const handleClick = (event: MouseEvent) => {
      if (toolsRef.current && !toolsRef.current.contains(event.target as Node)) {
        closeTools()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [toolsOpen, closeTools])

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-neutral-800 px-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
        >
          <Home className="h-4 w-4" />
        </button>
        <ChevronRight className="h-4 w-4 text-neutral-700" />
        <div className="flex items-center gap-2">
          <Film className="h-4 w-4 text-accent-400" />
          <span className="text-sm font-medium text-neutral-200">{projectName}</span>
        </div>
        <span className="rounded bg-neutral-800 px-2 py-0.5 text-2xs font-mono text-neutral-500">
          v{timelineVersion ?? '-'}
        </span>
        <ConnectionBadge />
      </div>

      <div className="flex items-center gap-2">
        {/* Tools dropdown */}
        <div ref={toolsRef} className="relative">
          <button
            onClick={() => setToolsOpen((prev) => !prev)}
            className="flex items-center gap-1.5 rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-xs font-medium text-neutral-300 transition-colors hover:border-neutral-600 hover:bg-neutral-700"
          >
            Tools
            <ChevronDown className="h-3 w-3" />
          </button>
          {toolsOpen && (
            <div className="absolute right-0 top-full mt-1 z-50 min-w-[160px] rounded-lg border border-neutral-700 bg-neutral-800 py-1 shadow-lg">
              <button
                onClick={() => {
                  onOpenPeople()
                  closeTools()
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-neutral-300 hover:bg-neutral-700 transition-colors"
              >
                <Users className="h-3.5 w-3.5" />
                People
              </button>
              <button
                onClick={() => {
                  onOpenGenerate()
                  closeTools()
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-neutral-300 hover:bg-neutral-700 transition-colors"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Generate
              </button>
            </div>
          )}
        </div>

        <span className="mr-2 text-2xs text-neutral-500">
          {gpuAvailable ? `GPU (${formatGpuBackendLabel(gpuBackend)})` : 'CPU Mode'}
        </span>
        <button
          onClick={onOpenRenderSettings}
          className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-xs font-medium text-neutral-300 transition-colors hover:border-neutral-600 hover:bg-neutral-700"
        >
          Render Settings
        </button>
        <button
          onClick={onRender}
          className="flex items-center gap-2 rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent-600"
        >
          <Download className="h-4 w-4" />
          Export
        </button>
      </div>
    </header>
  )
}

export default HeaderBar
