import { create } from 'zustand'

export type AssetTab = 'assets' | 'media' | 'audio' | 'graphics' | 'people'

export type AssetViewMode = 'grid' | 'list'

export type EditorTool = 'select' | 'razor' | 'slip' | 'hand'

export type TimelineSelection =
  | { type: 'clip'; trackIndex: number; itemIndex: number }
  | { type: 'gap'; trackIndex: number; itemIndex: number }
  | { type: 'transition'; trackIndex: number; itemIndex: number }
  | { type: 'track'; trackIndex: number }
  | null

export type UiStoreState = {
  sidebarOpen: boolean
  outputPanelOpen: boolean
  inspectorOpen: boolean
  activeAssetTab: AssetTab
  assetViewMode: AssetViewMode
  activeTool: EditorTool
  timelineZoom: number
  timelineSnapEnabled: boolean
  timelineSnapStrength: number
  timelineScrollX: number
  timelineScrollY: number
  selection: TimelineSelection
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
  setOutputPanelOpen: (open: boolean) => void
  toggleOutputPanel: () => void
  setInspectorOpen: (open: boolean) => void
  setActiveAssetTab: (tab: AssetTab) => void
  setAssetViewMode: (mode: AssetViewMode) => void
  setActiveTool: (tool: EditorTool) => void
  setTimelineZoom: (zoom: number) => void
  setTimelineSnapEnabled: (enabled: boolean) => void
  toggleTimelineSnapEnabled: () => void
  setTimelineSnapStrength: (strength: number) => void
  setTimelineScroll: (x: number, y: number) => void
  setSelection: (selection: TimelineSelection) => void
  clearSelection: () => void
  clear: () => void
}

const clampZoom = (zoom: number) => {
  if (!Number.isFinite(zoom)) {
    return 1
  }
  return Math.max(0.1, Math.min(8, zoom))
}

const clampSnapStrength = (strength: number) => {
  if (!Number.isFinite(strength)) {
    return 10
  }
  return Math.max(2, Math.min(40, Math.round(strength)))
}

export const useUiStore = create<UiStoreState>((set) => ({
  sidebarOpen: true,
  outputPanelOpen: false,
  inspectorOpen: true,
  activeAssetTab: 'assets',
  assetViewMode: 'grid',
  activeTool: 'select',
  timelineZoom: 1,
  timelineSnapEnabled: true,
  timelineSnapStrength: 10,
  timelineScrollX: 0,
  timelineScrollY: 0,
  selection: null,

  setSidebarOpen: (open) => set({ sidebarOpen: open }),

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

  setOutputPanelOpen: (open) => set({ outputPanelOpen: open }),

  toggleOutputPanel: () => set((state) => ({ outputPanelOpen: !state.outputPanelOpen })),

  setInspectorOpen: (open) => set({ inspectorOpen: open }),

  setActiveAssetTab: (tab) => set({ activeAssetTab: tab }),

  setAssetViewMode: (mode) => set({ assetViewMode: mode }),

  setActiveTool: (tool) => set({ activeTool: tool }),

  setTimelineZoom: (zoom) => set({ timelineZoom: clampZoom(zoom) }),

  setTimelineSnapEnabled: (enabled) => set({ timelineSnapEnabled: enabled }),

  toggleTimelineSnapEnabled: () =>
    set((state) => ({ timelineSnapEnabled: !state.timelineSnapEnabled })),

  setTimelineSnapStrength: (strength) =>
    set({ timelineSnapStrength: clampSnapStrength(strength) }),

  setTimelineScroll: (x, y) => {
    const nextX = Number.isFinite(x) ? Math.max(0, x) : 0
    const nextY = Number.isFinite(y) ? Math.max(0, y) : 0
    set({ timelineScrollX: nextX, timelineScrollY: nextY })
  },

  setSelection: (selection) => set({ selection }),

  clearSelection: () => set({ selection: null }),

  clear: () => {
    set({
      sidebarOpen: true,
      outputPanelOpen: false,
      inspectorOpen: true,
      activeAssetTab: 'assets',
      assetViewMode: 'grid',
      activeTool: 'select',
      timelineZoom: 1,
      timelineSnapEnabled: true,
      timelineSnapStrength: 10,
      timelineScrollX: 0,
      timelineScrollY: 0,
      selection: null,
    })
  },
}))
