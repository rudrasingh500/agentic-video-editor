const STORAGE_KEY = 'granite-asset-cache'

export type AssetCacheIndex = Record<string, string>

export const loadAssetCache = (): AssetCacheIndex => {
  if (typeof window === 'undefined') {
    return {}
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return stored ? (JSON.parse(stored) as AssetCacheIndex) : {}
  } catch (error) {
    return {}
  }
}

export const saveAssetCache = (cache: AssetCacheIndex) => {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cache))
}
