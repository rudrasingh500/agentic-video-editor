import { useRef, useEffect, useMemo, useState } from 'react'
import {
  MessageSquare,
  ChevronRight,
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Plus,
  Send,
  CheckCircle2,
  Loader2,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type {
  EditPatchSummary,
  EditSessionActivityEvent,
  EditSessionSummary,
} from '../lib/types'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

type ChatSidebarProps = {
  isOpen: boolean
  onToggle: () => void
  messages: ChatMessage[]
  chatInput: string
  onChatInputChange: (value: string) => void
  onSendMessage: () => void
  sessions: EditSessionSummary[]
  sessionId: string | null
  sessionsLoading: boolean
  sessionsError: string | null
  onSessionChange: (sessionId: string) => void
  onNewSession: () => void
  pendingPatches: EditPatchSummary[]
  onApplyPatches: () => void
  activityEvents: EditSessionActivityEvent[]
  agentBusy: boolean
  gpuAvailable?: boolean
}

type TimelineItem = {
  id: string
  label: string
  status: string
}

type TimelineRun = {
  runId: string
  items: TimelineItem[]
  active: boolean
}

const ChatSidebar = ({
  isOpen,
  onToggle,
  messages,
  chatInput,
  onChatInputChange,
  onSendMessage,
  sessions,
  sessionId,
  sessionsLoading,
  sessionsError,
  onSessionChange,
  onNewSession,
  pendingPatches,
  onApplyPatches,
  activityEvents,
  agentBusy,
  gpuAvailable,
}: ChatSidebarProps) => {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [expandedRuns, setExpandedRuns] = useState<Record<string, boolean>>({})

  const timelineRuns = useMemo(() => {
    const includeTypes = new Set([
      'plan',
      'tool_started',
      'tool_completed',
      'warning',
      'error',
      'run_started',
      'run_completed',
      'run_failed',
    ])
    const visibleToolNames = new Set([
      'edit_timeline',
      'render_output',
      'view_render_output',
      'undo_to_version',
      'view_asset',
    ])

    const isVisible = (event: EditSessionActivityEvent) => {
      if (!includeTypes.has(event.event_type) || !event.label?.trim()) {
        return false
      }
      if (event.event_type === 'tool_started' || event.event_type === 'tool_completed') {
        return !!event.tool_name && visibleToolNames.has(event.tool_name)
      }
      return true
    }

    const terminalTypes = new Set(['run_completed', 'run_failed'])
    const runs: TimelineRun[] = []
    let currentRun: TimelineRun | null = null

    for (const event of activityEvents) {
      if (event.event_type === 'run_started') {
        if (currentRun && currentRun.items.length > 0) {
          runs.push(currentRun)
        }
        currentRun = {
          runId: event.event_id,
          items: [],
          active: true,
        }
      }

      if (!currentRun) {
        currentRun = {
          runId: `run-${event.event_id}`,
          items: [],
          active: true,
        }
      }

      if (isVisible(event)) {
        currentRun.items.push({
          id: event.event_id,
          label:
            event.event_type === 'plan' && event.label.startsWith('Plan: ')
              ? event.label.slice(6).trim()
              : event.label,
          status: event.status,
        })
      }

      if (terminalTypes.has(event.event_type)) {
        currentRun.active = false
        if (currentRun.items.length > 0) {
          runs.push(currentRun)
        }
        currentRun = null
      }
    }

    if (currentRun && currentRun.items.length > 0) {
      runs.push(currentRun)
    }

    return runs
  }, [activityEvents])

  const assistantMessageCount = useMemo(
    () => messages.filter((message) => message.role === 'assistant').length,
    [messages],
  )

  const showTimeline = agentBusy || timelineRuns.length > 0

  const toggleRun = (runId: string) => {
    setExpandedRuns((prev) => ({
      ...prev,
      [runId]: !prev[runId],
    }))
  }

  const renderRunBox = (run: TimelineRun) => {
    const isExpanded = !!expandedRuns[run.runId]
    const visibleItems = isExpanded ? run.items.slice(-14) : run.items.slice(-3)

    return (
      <div className="mr-4 rounded-md border border-neutral-700/80 bg-neutral-850/70 px-2.5 py-2">
        <button
          type="button"
          onClick={() => toggleRun(run.runId)}
          className="flex w-full items-center justify-between text-left"
        >
          <span className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-neutral-400">
            {run.active && agentBusy && <Loader2 className="h-3 w-3 animate-spin text-accent-400" />}
            Actions
          </span>
          <span className="text-neutral-500">
            {isExpanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </span>
        </button>
        <div className="mt-2 divide-y divide-neutral-800/80 border-t border-neutral-800/90">
          {visibleItems.map((item) => (
            <div key={item.id} className="flex items-start gap-2 py-1.5 text-[11px] text-neutral-400">
              <span
                className={`mt-1 h-1.5 w-1.5 rounded-full ${
                  item.status === 'failed' ? 'bg-error-500' : 'bg-accent-400/90'
                }`}
              />
              <span>{item.label}</span>
            </div>
          ))}
          {visibleItems.length === 0 && (
            <div className="py-1.5 text-[11px] text-neutral-500">Waiting for agent actions...</div>
          )}
        </div>
      </div>
    )
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  return (
    <>
      {/* Toggle button when sidebar is closed */}
      {!isOpen && (
        <button
          onClick={onToggle}
          className="fixed right-0 top-1/2 -translate-y-1/2 z-20 flex h-24 w-6 items-center justify-center rounded-l-lg bg-neutral-800 border border-r-0 border-neutral-700 hover:bg-neutral-700 transition-colors"
          title="Open chat"
        >
          <ChevronLeft className="h-4 w-4 text-neutral-400" />
        </button>
      )}

      {/* Sidebar panel */}
      <div
        className={`sidebar-slide flex flex-col border-l border-neutral-800 bg-neutral-900 ${
          isOpen ? 'w-80' : 'w-0'
        } overflow-hidden`}
      >
        <div className="flex h-full w-80 flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-accent-400" />
              <span className="text-sm font-medium text-neutral-200">Assistant</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-2xs text-neutral-500">
                {gpuAvailable ? 'GPU' : 'CPU'}
              </span>
              <button
                onClick={onToggle}
                className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300 transition-colors"
                title="Close chat"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Session selector */}
          <div className="border-b border-neutral-800 px-4 py-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-2xs font-medium uppercase tracking-wider text-neutral-500">
                Session
              </span>
              <button
                onClick={onNewSession}
                className="flex items-center gap-1 rounded px-2 py-1 text-2xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors"
              >
                <Plus className="h-3 w-3" />
                New
              </button>
            </div>
            <select
              value={sessionId ?? ''}
              onChange={(e) => onSessionChange(e.target.value)}
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
            >
              <option value="">New session</option>
              {sessions.map((session) => {
                const label =
                  session.title?.trim() ||
                  `Session ${session.session_id.slice(0, 8)}`
                return (
                  <option key={session.session_id} value={session.session_id}>
                    {label}
                  </option>
                )
              })}
            </select>
            {sessionsLoading && (
              <div className="mt-2 flex items-center gap-2 text-2xs text-neutral-500">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading sessions...
              </div>
            )}
            {sessionsError && (
              <div className="mt-2 rounded bg-error-500/10 px-2 py-1 text-2xs text-error-500">
                {sessionsError}
              </div>
            )}
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-auto px-4 py-3 scrollbar-thin">
            {messages.length > 0 ? (
              <div className="space-y-3">
                {messages.map((message, index) => (
                  <div key={message.id} className="space-y-2">
                    {showTimeline && message.role === 'assistant' && (() => {
                      const assistantIndex = messages
                        .slice(0, index + 1)
                        .filter((entry) => entry.role === 'assistant').length - 1
                      const run = timelineRuns[assistantIndex]
                      return run ? renderRunBox(run) : null
                    })()}
                    <div
                      className={`rounded-lg px-3 py-2.5 text-sm leading-relaxed ${
                        message.role === 'user'
                          ? 'bg-accent-500/20 text-neutral-100 ml-4 whitespace-pre-wrap'
                          : 'bg-neutral-800 text-neutral-200 mr-4'
                      }`}
                    >
                      {message.role === 'assistant' ? (
                        <div className="chat-markdown">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                        </div>
                      ) : (
                        message.content
                      )}
                    </div>
                  </div>
                ))}
                {showTimeline && timelineRuns.length > assistantMessageCount && (
                  <div>{renderRunBox(timelineRuns[assistantMessageCount])}</div>
                )}
                <div ref={messagesEndRef} />
              </div>
            ) : (
              <div className="flex h-full items-center justify-center">
                <div className="text-center text-neutral-600">
                  <MessageSquare className="mx-auto h-8 w-8 mb-2 opacity-50" />
                  <p className="text-xs">
                    Ask the assistant to edit your video.
                  </p>
                  <p className="text-2xs mt-1 text-neutral-700">
                    Try "trim pauses" or "create a highlight cut"
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Pending patches */}
          {pendingPatches.length > 0 && (
            <div className="border-t border-neutral-800 px-4 py-3">
              <div className="rounded-lg border border-accent-500/30 bg-accent-500/10 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-accent-300">
                    Pending Changes
                  </span>
                  <span className="text-2xs text-accent-400">
                    {pendingPatches.length} patch{pendingPatches.length > 1 ? 'es' : ''}
                  </span>
                </div>
                <ul className="space-y-1 mb-3">
                  {pendingPatches.slice(0, 3).map((patch) => (
                    <li
                      key={patch.patch_id}
                      className="text-2xs text-neutral-400 truncate"
                    >
                      {patch.description || patch.agent_type} ({patch.operation_count})
                    </li>
                  ))}
                  {pendingPatches.length > 3 && (
                    <li className="text-2xs text-neutral-500">
                      +{pendingPatches.length - 3} more
                    </li>
                  )}
                </ul>
                <button
                  onClick={onApplyPatches}
                  className="w-full flex items-center justify-center gap-2 rounded-lg bg-accent-500 px-3 py-2 text-xs font-medium text-white hover:bg-accent-600 transition-colors"
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Apply Changes
                </button>
              </div>
            </div>
          )}

          {/* Input area */}
          <div className="border-t border-neutral-800 p-4">
            <div className="relative">
              <textarea
                value={chatInput}
                onChange={(e) => onChatInputChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    onSendMessage()
                  }
                }}
                rows={3}
                className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2.5 pr-10 text-sm text-neutral-200 placeholder-neutral-500 resize-none focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
                placeholder="Describe the edit you want..."
              />
              <button
                onClick={onSendMessage}
                disabled={!chatInput.trim()}
                className="absolute right-2 bottom-2 rounded-lg bg-accent-500 p-2 text-white hover:bg-accent-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export default ChatSidebar
