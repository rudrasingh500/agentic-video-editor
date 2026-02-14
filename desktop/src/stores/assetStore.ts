import { create } from 'zustand'

import { api } from '../lib/api'
import { loadAssetCache, saveAssetCache, type AssetCacheIndex } from '../lib/assetCache'
import type { AppConfig } from '../lib/config'
import type { Asset } from '../lib/types'

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
  updateAsset: (assetId: string, patch: Partial<Asset>) => void
  removeAsset: (assetId: string) => void
  rememberAssetPath: (assetId: string, path: string) => void
  getAssetPath: (assetId: string) => string | undefined
  loadAssets: (config: AppConfig, projectId: string) => Promise<void>
  uploadAsset: (config: AppConfig, projectId: string, file: File) => Promise<Asset>
  deleteAsset: (config: AppConfig, projectId: string, assetId: string) => Promise<void>
}

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

  getAssetPath: (assetId) => get().assetCache[assetId],

  loadAssets: async (config, projectId) => {
    set({ assetsLoading: true, assetsError: null })
    try {
      const response = await api.listAssets(config, projectId)
      set({ assets: response.assets || [], assetsError: null })
    } catch (error) {
      set({ assetsError: (error as Error).message })
      throw error
    } finally {
      set({ assetsLoading: false })
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
    await api.deleteAsset(config, projectId, assetId)
    set((state) => {
      const nextAssets = state.assets.filter((asset) => asset.asset_id !== assetId)
      const nextCache = { ...state.assetCache }
      delete nextCache[assetId]
      saveAssetCache(nextCache)

      const nextProgress = { ...state.uploadProgress }
      delete nextProgress[assetId]

      return {
        assets: nextAssets,
        assetCache: nextCache,
        uploadProgress: nextProgress,
      }
    })
  },
}))
