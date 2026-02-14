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

export type RenderStoreState = {
  gpuInfo: GpuInfo | null
  renderState: RenderState
  renderLogs: string[]
  previewPath: string | null
  previewKey: number
  setGpuInfo: (info: GpuInfo | null) => void
  setRenderState: (state: RenderState | ((prev: RenderState) => RenderState)) => void
  appendRenderLog: (line: string) => void
  setRenderLogs: (logs: string[]) => void
  clearRenderLogs: () => void
  setPreviewPath: (path: string | null) => void
  bumpPreviewKey: () => void
  clear: () => void
}

export const useRenderStore = create<RenderStoreState>((set) => ({
  gpuInfo: null,
  renderState: {},
  renderLogs: [],
  previewPath: null,
  previewKey: 0,

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

  clear: () => {
    set({
      renderState: {},
      renderLogs: [],
      previewPath: null,
      previewKey: 0,
    })
  },
}))
