import { create } from 'zustand'

import type { AppConfig } from '../lib/config'
import type { Project } from '../lib/types'

export type ProjectStoreState = {
  activeProject: Project | null
  config: AppConfig | null
  setActiveProject: (project: Project | null) => void
  setConfig: (config: AppConfig) => void
  clear: () => void
}

export const useProjectStore = create<ProjectStoreState>((set) => ({
  activeProject: null,
  config: null,

  setActiveProject: (activeProject) => set({ activeProject }),

  setConfig: (config) => set({ config }),

  clear: () => {
    set({
      activeProject: null,
      config: null,
    })
  },
}))
