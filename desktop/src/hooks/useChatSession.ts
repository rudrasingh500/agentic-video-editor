import { useCallback, useEffect, useState } from 'react'
import type { AppConfig } from '../lib/config'
import { api } from '../lib/api'
import { loadSessionId, saveSessionId } from '../lib/chatSessions'
import type {
  EditPatchSummary,
  EditSessionActivityEvent,
  EditSessionDetail,
  EditSessionPendingPatch,
  EditSessionSummary,
} from '../lib/types'

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

type UseChatSessionOptions = {
  config: AppConfig
  projectId: string
  setTimelineVersion: (version: number | null) => void
  refreshTimelineSnapshot: (version?: number) => Promise<unknown>
  fetchAssets: (silent?: boolean) => Promise<void>
}

const useChatSession = ({
  config,
  projectId,
  setTimelineVersion,
  refreshTimelineSnapshot,
  fetchAssets,
}: UseChatSessionOptions) => {
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [pendingPatches, setPendingPatches] = useState<EditPatchSummary[]>([])
  const [activityEvents, setActivityEvents] = useState<EditSessionActivityEvent[]>([])
  const [agentBusy, setAgentBusy] = useState(false)
  const [sessions, setSessions] = useState<EditSessionSummary[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [sessionsError, setSessionsError] = useState<string | null>(null)

  const appendMessage = useCallback((role: 'user' | 'assistant', content: string) => {
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role,
        content,
      },
    ])
  }, [])

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
        projectId,
        nextSessionId,
      )
      setSessionId(detail.session_id)
      saveSessionId(projectId, detail.session_id)
      setMessages(mapSessionMessages(detail))
      setPendingPatches(mapPendingPatches(detail.pending_patches))
      setActivityEvents(mapActivityEvents(detail.activity_events))
    },
    [config, projectId],
  )

  const refreshSessions = useCallback(
    async (selectSessionId?: string | null) => {
      setSessionsLoading(true)
      setSessionsError(null)
      try {
        const response = await api.listEditSessions(config, projectId)
        setSessions(response.sessions || [])
        const stored = loadSessionId(projectId)
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
    [config, projectId, loadSession],
  )

  const handleNewSession = useCallback(() => {
    setSessionId(null)
    setMessages([])
    setPendingPatches([])
    setActivityEvents([])
    saveSessionId(projectId, null)
  }, [projectId])

  // Load sessions on mount / project change
  useEffect(() => {
    refreshSessions().catch(() => {})
  }, [refreshSessions])

  const handleSendMessage = useCallback(async () => {
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
        projectId,
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
            saveSessionId(projectId, resultSessionId)
          }
          setPendingPatches(resultPatches)
          if (resultVersion) {
            setTimelineVersion(resultVersion)
            refreshTimelineSnapshot(resultVersion).catch(() => {})
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
  }, [
    chatInput,
    config,
    fetchAssets,
    projectId,
    refreshSessions,
    refreshTimelineSnapshot,
    sessionId,
    setTimelineVersion,
  ])

  const handleApplyPatches = useCallback(async () => {
    if (!sessionId || pendingPatches.length === 0) {
      return
    }

    try {
      const response = await api.applyPatches(
        config,
        projectId,
        sessionId,
        pendingPatches.map((patch) => patch.patch_id),
      )
      if (response.new_version) {
        setTimelineVersion(response.new_version)
        refreshTimelineSnapshot(response.new_version).catch(() => {})
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
  }, [
    config,
    fetchAssets,
    pendingPatches,
    projectId,
    refreshTimelineSnapshot,
    sessionId,
    setTimelineVersion,
  ])

  const handleSessionChange = useCallback(
    (value: string) => {
      if (!value) {
        handleNewSession()
        return
      }
      loadSession(value).catch((error) => {
        setSessionsError((error as Error).message)
      })
    },
    [handleNewSession, loadSession],
  )

  return {
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
  }
}

export default useChatSession
