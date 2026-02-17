import { create } from 'zustand'

export type GpuBackend = 'nvidia' | 'amd' | 'apple' | 'none'

export type GpuInfo = {
  available: boolean
  detail: string
  backend: GpuBackend
  encoders: {
    h264: boolean
    h265: boolean
  }
}

export type RenderState = {
  jobId?: string
  status?: string
  progress?: number
  outputPath?: string
}

/** A local render that completed offline and hasn't been uploaded yet. */
export type PendingRenderUpload = {
  jobId: string
  projectId: string
  outputPath: string
  outputFilename: string
  completedAt: string
}

// ---------------------------------------------------------------------------
// Persistence helpers for pending render uploads
// ---------------------------------------------------------------------------

const PENDING_RENDERS_KEY = 'auteur:pendingRenders'

const loadPendingRenders = (): PendingRenderUpload[] => {
  try {
    const raw = localStorage.getItem(PENDING_RENDERS_KEY)
    return raw ? (JSON.parse(raw) as PendingRenderUpload[]) : []
  } catch {
    return []
  }
}

const savePendingRenders = (renders: PendingRenderUpload[]): void => {
  try {
    localStorage.setItem(PENDING_RENDERS_KEY, JSON.stringify(renders))
  } catch {
    // localStorage full — silently ignore
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export type RenderStoreState = {
  gpuInfo: GpuInfo | null
  renderState: RenderState
  renderLogs: string[]
  previewPath: string | null
  previewKey: number
  pendingRenderUploads: PendingRenderUpload[]
  setGpuInfo: (info: GpuInfo | null) => void
  setRenderState: (state: RenderState | ((prev: RenderState) => RenderState)) => void
  appendRenderLog: (line: string) => void
  setRenderLogs: (logs: string[]) => void
  clearRenderLogs: () => void
  setPreviewPath: (path: string | null) => void
  bumpPreviewKey: () => void
  /** Record a completed offline render for later upload. */
  addPendingRenderUpload: (entry: PendingRenderUpload) => void
  /** Remove a pending render upload (after successful sync). */
  removePendingRenderUpload: (jobId: string) => void
  clear: () => void
}

export const useRenderStore = create<RenderStoreState>((set) => ({
  gpuInfo: null,
  renderState: {},
  renderLogs: [],
  previewPath: null,
  previewKey: 0,
  pendingRenderUploads: loadPendingRenders(),

  setGpuInfo: (gpuInfo) => set({ gpuInfo }),

  setRenderState: (nextState) => {
    if (typeof nextState === 'function') {
      set((state) => ({ renderState: nextState(state.renderState) }))
      return
    }
    set({ renderState: nextState })
  },

  appendRenderLog: (line) => {
    set((state) => {
      const nextLogs = [...state.renderLogs, line]
      if (nextLogs.length > 250) {
        return { renderLogs: nextLogs.slice(nextLogs.length - 250) }
      }
      return { renderLogs: nextLogs }
    })
  },

  setRenderLogs: (renderLogs) => set({ renderLogs }),

  clearRenderLogs: () => set({ renderLogs: [] }),

  setPreviewPath: (previewPath) => set({ previewPath }),

  bumpPreviewKey: () => set((state) => ({ previewKey: state.previewKey + 1 })),

  addPendingRenderUpload: (entry) => {
    set((state) => {
      const next = [...state.pendingRenderUploads, entry]
      savePendingRenders(next)
      return { pendingRenderUploads: next }
    })
  },

  removePendingRenderUpload: (jobId) => {
    set((state) => {
      const next = state.pendingRenderUploads.filter((r) => r.jobId !== jobId)
      savePendingRenders(next)
      return { pendingRenderUploads: next }
    })
  },

  clear: () => {
    set({
      renderState: {},
      renderLogs: [],
      previewPath: null,
      previewKey: 0,
      // Note: pendingRenderUploads are NOT cleared — they persist across project switches
    })
  },
}))

