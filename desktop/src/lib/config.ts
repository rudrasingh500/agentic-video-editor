export type AppConfig = {
  baseUrl: string
  devToken: string
}

const STORAGE_KEY = 'granite-config'

const defaultConfig: AppConfig = {
  baseUrl: import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000',
  devToken: import.meta.env.VITE_DEV_TOKEN ?? '',
}

export const loadConfig = (): AppConfig => {
  if (typeof window === 'undefined') {
    return defaultConfig
  }

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (!stored) {
      return defaultConfig
    }
    const parsed = JSON.parse(stored) as Partial<AppConfig>
    return {
      baseUrl: parsed.baseUrl ?? defaultConfig.baseUrl,
      devToken: parsed.devToken ?? defaultConfig.devToken,
    }
  } catch (error) {
    return defaultConfig
  }
}

export const saveConfig = (config: AppConfig) => {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}
