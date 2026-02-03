type SessionIndex = Record<string, string | null>

const STORAGE_KEY = 'granite-edit-session-index'

const loadIndex = (): SessionIndex => {
  if (typeof window === 'undefined') {
    return {}
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return {}
    }
    return JSON.parse(raw) as SessionIndex
  } catch (error) {
    return {}
  }
}

const saveIndex = (index: SessionIndex) => {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(index))
}

export const loadSessionId = (projectId: string): string | null => {
  const index = loadIndex()
  return index[projectId] ?? null
}

export const saveSessionId = (projectId: string, sessionId: string | null) => {
  const index = loadIndex()
  if (!sessionId) {
    delete index[projectId]
  } else {
    index[projectId] = sessionId
  }
  saveIndex(index)
}
