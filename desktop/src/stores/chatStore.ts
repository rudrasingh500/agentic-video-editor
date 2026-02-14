import { create } from 'zustand'

import type {
  EditPatchSummary,
  EditSessionActivityEvent,
  EditSessionSummary,
} from '../lib/types'

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

export type ChatStoreState = {
  chatInput: string
  messages: ChatMessage[]
  sessionId: string | null
  sessions: EditSessionSummary[]
  sessionsLoading: boolean
  sessionsError: string | null
  pendingPatches: EditPatchSummary[]
  activityEvents: EditSessionActivityEvent[]
  agentBusy: boolean
  setChatInput: (chatInput: string) => void
  pushMessage: (message: ChatMessage) => void
  setMessages: (messages: ChatMessage[]) => void
  setSessionId: (sessionId: string | null) => void
  setSessions: (sessions: EditSessionSummary[]) => void
  setSessionsLoading: (loading: boolean) => void
  setSessionsError: (error: string | null) => void
  setPendingPatches: (patches: EditPatchSummary[]) => void
  setActivityEvents: (events: EditSessionActivityEvent[]) => void
  pushActivityEvent: (event: EditSessionActivityEvent) => void
  setAgentBusy: (agentBusy: boolean) => void
  clear: () => void
}

const MAX_ACTIVITY_EVENTS = 300

export const useChatStore = create<ChatStoreState>((set) => ({
  chatInput: '',
  messages: [],
  sessionId: null,
  sessions: [],
  sessionsLoading: false,
  sessionsError: null,
  pendingPatches: [],
  activityEvents: [],
  agentBusy: false,

  setChatInput: (chatInput) => set({ chatInput }),

  pushMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),

  setMessages: (messages) => set({ messages }),

  setSessionId: (sessionId) => set({ sessionId }),

  setSessions: (sessions) => set({ sessions }),

  setSessionsLoading: (sessionsLoading) => set({ sessionsLoading }),

  setSessionsError: (sessionsError) => set({ sessionsError }),

  setPendingPatches: (pendingPatches) => set({ pendingPatches }),

  setActivityEvents: (activityEvents) =>
    set({
      activityEvents: activityEvents.slice(Math.max(activityEvents.length - MAX_ACTIVITY_EVENTS, 0)),
    }),

  pushActivityEvent: (event) =>
    set((state) => {
      const nextEvents = [...state.activityEvents, event]
      return {
        activityEvents: nextEvents.slice(Math.max(nextEvents.length - MAX_ACTIVITY_EVENTS, 0)),
      }
    }),

  setAgentBusy: (agentBusy) => set({ agentBusy }),

  clear: () => {
    set({
      chatInput: '',
      messages: [],
      sessionId: null,
      sessions: [],
      sessionsLoading: false,
      sessionsError: null,
      pendingPatches: [],
      activityEvents: [],
      agentBusy: false,
    })
  },
}))
