import { useEffect, useRef } from 'react'
import {
  ChevronDown,
  ChevronUp,
  Terminal,
  AlertCircle,
  Trash2,
  Loader2,
} from 'lucide-react'

type RenderStatus = {
  jobId?: string
  status?: string
  progress?: number
  outputPath?: string
}

type OutputPanelProps = {
  isOpen: boolean
  onToggle: () => void
  logs: string[]
  renderStatus?: RenderStatus
  onClear: () => void
}

const OutputPanel = ({
  isOpen,
  onToggle,
  logs,
  renderStatus,
  onClear,
}: OutputPanelProps) => {
  const logsEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (isOpen && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, isOpen])

  const isRendering =
    renderStatus?.status &&
    !['completed', 'failed', 'cancelled'].includes(renderStatus.status)

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'text-success-500'
      case 'failed':
        return 'text-error-500'
      case 'cancelled':
        return 'text-neutral-500'
      case 'uploading':
        return 'text-accent-400'
      default:
        return 'text-accent-400'
    }
  }

  return (
    <div className="border-t border-neutral-800 bg-neutral-900">
      {/* Header bar - always visible */}
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-2 hover:bg-neutral-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-medium text-neutral-300">
            <Terminal className="h-3.5 w-3.5" />
            <span>Output</span>
          </div>

          {/* Status indicator */}
          {renderStatus?.status && (
            <>
              <div className="h-3 w-px bg-neutral-700" />
              <div className="flex items-center gap-2">
                {isRendering && (
                  <Loader2 className="h-3 w-3 animate-spin text-accent-400" />
                )}
                <span className={`text-xs ${getStatusColor(renderStatus.status)}`}>
                  {renderStatus.status}
                </span>
                {renderStatus.progress !== undefined && isRendering && (
                  <span className="text-xs text-neutral-500">
                    {renderStatus.progress}%
                  </span>
                )}
              </div>
            </>
          )}

          {/* Log count badge */}
          {logs.length > 0 && (
            <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-2xs text-neutral-400">
              {logs.length}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {logs.length > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onClear()
              }}
              className="rounded p-1 text-neutral-500 hover:bg-neutral-700 hover:text-neutral-300 transition-colors"
              title="Clear logs"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
          {isOpen ? (
            <ChevronDown className="h-4 w-4 text-neutral-500" />
          ) : (
            <ChevronUp className="h-4 w-4 text-neutral-500" />
          )}
        </div>
      </button>

      {/* Collapsible content */}
      <div
        className={`overflow-hidden transition-all duration-300 ease-smooth ${
          isOpen ? 'max-h-64' : 'max-h-0'
        }`}
      >
        {/* Progress bar */}
        {isRendering && renderStatus?.progress !== undefined && (
          <div className="px-4 pb-2">
            <div className="h-1 w-full rounded-full bg-neutral-800 overflow-hidden">
              <div
                className="h-full bg-accent-500 transition-all duration-300 ease-out"
                style={{ width: `${renderStatus.progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Logs container */}
        <div className="h-48 overflow-auto px-4 pb-4 scrollbar-thin">
          {logs.length > 0 ? (
            <div className="space-y-0.5 font-mono text-xs">
              {logs.map((line, index) => (
                <div
                  key={`${index}-${line.slice(0, 12)}`}
                  className={`leading-relaxed ${
                    line.toLowerCase().includes('error')
                      ? 'text-error-500'
                      : line.toLowerCase().includes('warning')
                      ? 'text-warning-500'
                      : 'text-neutral-400'
                  }`}
                >
                  <span className="select-none text-neutral-600 mr-3">
                    {String(index + 1).padStart(3, ' ')}
                  </span>
                  {line}
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="flex flex-col items-center gap-2 text-neutral-600">
                <AlertCircle className="h-5 w-5" />
                <span className="text-xs">No output yet</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default OutputPanel
