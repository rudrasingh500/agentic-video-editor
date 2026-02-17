import { create } from 'zustand'

import { api } from '../lib/api'
import { loadAssetCache, saveAssetCache, type AssetCacheIndex } from '../lib/assetCache'
import type { AppConfig } from '../lib/config'
import type { Asset } from '../lib/types'
import { useConnectionStore } from '../hooks/useConnectionStatus'

// ---------------------------------------------------------------------------
// Local-asset persistence helpers
// ---------------------------------------------------------------------------

const LOCAL_ASSETS_KEY_PREFIX = 'auteur:localAssets:'

const loadLocalAssets = (projectId: string): Asset[] => {
  try {
    const raw = localStorage.getItem(`${LOCAL_ASSETS_KEY_PREFIX}${projectId}`)
    return raw ? (JSON.parse(raw) as Asset[]) : []
  } catch {
    return []
  }
}

const saveLocalAssets = (projectId: string, assets: Asset[]): void => {
  try {
    const locals = assets.filter((a) => a.localPath && !a.synced)
    localStorage.setItem(`${LOCAL_ASSETS_KEY_PREFIX}${projectId}`, JSON.stringify(locals))
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

const inferAssetType = (filename: string): string => {
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''
  const audioExts = new Set(['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a', 'wma', 'aiff'])
  const imageExts = new Set(['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'tiff'])
  if (audioExts.has(ext)) return 'audio'
  if (imageExts.has(ext)) return 'image'
  return 'video'
}

// ---------------------------------------------------------------------------
// Store types
// ---------------------------------------------------------------------------

type UploadState = 'idle' | 'uploading' | 'uploaded' | 'failed'

export type AssetUploadProgress = {
  assetId: string
  name: string
  state: UploadState
  error?: string
}

export type AssetStoreState = {
  assets: Asset[]
  assetsLoading: boolean
  assetsError: string | null
  assetCache: AssetCacheIndex
  uploadProgress: Record<string, AssetUploadProgress>
  clear: () => void
  setAssets: (assets: Asset[]) => void
  upsertAssets: (incoming: Array<Asset | null | undefined>) => void
  updateAsset: (assetId: string, patch: Partial<Asset>) => void
  removeAsset: (assetId: string) => void
  rememberAssetPath: (assetId: string, path: string) => void
  forgetAssetPath: (assetId: string) => void
  getAssetPath: (assetId: string) => string | undefined
  loadAssets: (config: AppConfig, projectId: string, silent?: boolean) => Promise<void>
  uploadAsset: (config: AppConfig, projectId: string, file: File) => Promise<Asset>
  deleteAsset: (config: AppConfig, projectId: string, assetId: string) => Promise<void>
  /** Import a file from the local filesystem without requiring a backend. */
  addLocalAsset: (projectId: string, filePath: string) => Asset
  /** Upload all unsynced local assets to the backend. */
  syncAssetsToBackend: (config: AppConfig, projectId: string) => Promise<void>
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

export const useAssetStore = create<AssetStoreState>((set, get) => ({
  assets: [],
  assetsLoading: false,
  assetsError: null,
  assetCache: loadAssetCache(),
  uploadProgress: {},

  clear: () => {
    set({
      assets: [],
      assetsLoading: false,
      assetsError: null,
      uploadProgress: {},
    })
  },

  setAssets: (assets) => {
    set({ assets, assetsError: null })
  },

  upsertAssets: (incoming) => {
    const validIncoming = incoming.filter((item): item is Asset => Boolean(item))
    if (validIncoming.length === 0) {
      return
    }
    set((state) => {
      const map = new Map(state.assets.map((asset) => [asset.asset_id, asset]))
      for (const asset of validIncoming) {
        map.set(asset.asset_id, asset)
      }
      const next = Array.from(map.values()).sort((a, b) => {
        const aTime = a.uploaded_at ? Date.parse(a.uploaded_at) : 0
        const bTime = b.uploaded_at ? Date.parse(b.uploaded_at) : 0
        return bTime - aTime
      })
      return { assets: next }
    })
  },

  updateAsset: (assetId, patch) => {
    set((state) => ({
      assets: state.assets.map((asset) =>
        asset.asset_id === assetId ? { ...asset, ...patch } : asset,
      ),
    }))
  },

  removeAsset: (assetId) => {
    set((state) => ({
      assets: state.assets.filter((asset) => asset.asset_id !== assetId),
    }))
  },

  rememberAssetPath: (assetId, path) => {
    set((state) => {
      const nextCache = { ...state.assetCache, [assetId]: path }
      saveAssetCache(nextCache)
      return { assetCache: nextCache }
    })
  },

  forgetAssetPath: (assetId) => {
    set((state) => {
      if (!state.assetCache[assetId]) {
        return state
      }
      const nextCache = { ...state.assetCache }
      delete nextCache[assetId]
      saveAssetCache(nextCache)
      return { assetCache: nextCache }
    })
  },

  getAssetPath: (assetId) => get().assetCache[assetId],

  loadAssets: async (config, projectId, silent = false) => {
    if (!silent) {
      set({ assetsLoading: true, assetsError: null })
    } else {
      set({ assetsError: null })
    }

    // Always load local assets first
    const locals = loadLocalAssets(projectId)

    try {
      const response = await api.listAssets(config, projectId)
      const backendAssets = response.assets || []

      // Merge: backend assets take priority, add any unsynced locals that
      // aren't on the backend yet.
      const backendIds = new Set(backendAssets.map((a) => a.asset_id))
      const unsyncedLocals = locals.filter((a) => !backendIds.has(a.asset_id))
      const merged = [...backendAssets, ...unsyncedLocals]

      set({ assets: merged, assetsError: null })
    } catch (error) {
      // Offline — just show local assets
      if (locals.length > 0) {
        set({ assets: locals, assetsError: null })
      } else {
        set({ assetsError: (error as Error).message })
      }
    } finally {
      if (!silent) {
        set({ assetsLoading: false })
      }
    }
  },

  uploadAsset: async (config, projectId, file) => {
    const tempId = `upload:${crypto.randomUUID()}`
    set((state) => ({
      uploadProgress: {
        ...state.uploadProgress,
        [tempId]: {
          assetId: tempId,
          name: file.name,
          state: 'uploading',
        },
      },
      assetsError: null,
    }))

    try {
      const response = await api.uploadAsset(config, projectId, file)
      const uploaded = response.asset

      set((state) => {
        const nextProgress = { ...state.uploadProgress }
        delete nextProgress[tempId]
        nextProgress[uploaded.asset_id] = {
          assetId: uploaded.asset_id,
          name: uploaded.asset_name,
          state: 'uploaded',
        }

        const exists = state.assets.some((asset) => asset.asset_id === uploaded.asset_id)
        const nextAssets = exists
          ? state.assets.map((asset) =>
              asset.asset_id === uploaded.asset_id ? uploaded : asset,
            )
          : [uploaded, ...state.assets]

        return {
          assets: nextAssets,
          uploadProgress: nextProgress,
        }
      })

      return uploaded
    } catch (error) {
      set((state) => ({
        uploadProgress: {
          ...state.uploadProgress,
          [tempId]: {
            assetId: tempId,
            name: file.name,
            state: 'failed',
            error: (error as Error).message,
          },
        },
        assetsError: (error as Error).message,
      }))
      throw error
    }
  },

  deleteAsset: async (config, projectId, assetId) => {
    const asset = get().assets.find((a) => a.asset_id === assetId)
    const isLocal = asset?.localPath && !asset.synced

    if (!isLocal) {
      await api.deleteAsset(config, projectId, assetId)
    }

    set((state) => {
      const nextAssets = state.assets.filter((a) => a.asset_id !== assetId)
      const nextCache = { ...state.assetCache }
      delete nextCache[assetId]
      saveAssetCache(nextCache)

      const nextProgress = { ...state.uploadProgress }
      delete nextProgress[assetId]

      // Persist updated local list
      saveLocalAssets(projectId, nextAssets)

      return {
        assets: nextAssets,
        assetCache: nextCache,
        uploadProgress: nextProgress,
      }
    })
  },

  addLocalAsset: (projectId, filePath) => {
    const filename = filePath.split(/[/\\]/).pop() ?? 'Untitled'
    const assetType = inferAssetType(filename)
    const assetId = `local:${crypto.randomUUID()}`

    const asset: Asset = {
      asset_id: assetId,
      asset_name: filename,
      asset_type: assetType,
      uploaded_at: new Date().toISOString(),
      localPath: filePath,
      synced: false,
    }

    set((state) => {
      const nextAssets = [asset, ...state.assets]
      saveLocalAssets(projectId, nextAssets)

      // Also remember the path in the cache for preview/render
      const nextCache = { ...state.assetCache, [assetId]: filePath }
      saveAssetCache(nextCache)

      return { assets: nextAssets, assetCache: nextCache }
    })

    return asset
  },

  syncAssetsToBackend: async (config, projectId) => {
    const online = useConnectionStore.getState().state === 'online'
    if (!online) {
      return
    }

    const unsynced = get().assets.filter((a) => a.localPath && !a.synced)
    if (unsynced.length === 0) {
      return
    }

    for (const localAsset of unsynced) {
      try {
        // Read the file from disk via fetch (file:// protocol in Electron)
        const fileUrl = localAsset.localPath!.startsWith('file://')
          ? localAsset.localPath!
          : `file://${localAsset.localPath!}`
        const response = await fetch(fileUrl)
        const blob = await response.blob()
        const file = new File([blob], localAsset.asset_name, { type: blob.type })

        const uploadResponse = await api.uploadAsset(config, projectId, file)
        const uploaded = uploadResponse.asset

        // Replace local asset with the backend version
        set((state) => {
          const nextAssets = state.assets.map((a) =>
            a.asset_id === localAsset.asset_id
              ? { ...uploaded, localPath: localAsset.localPath, synced: true }
              : a,
          )
          saveLocalAssets(projectId, nextAssets)

          // Update cache to point the old local ID to the local path as well
          const nextCache = { ...state.assetCache }
          nextCache[uploaded.asset_id] = localAsset.localPath!
          saveAssetCache(nextCache)

          return { assets: nextAssets, assetCache: nextCache }
        })
      } catch {
        // Skip this asset — will retry on next sync attempt
      }
    }
  },
}))
