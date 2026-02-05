/// <reference types="vite-plugin-electron/electron-env" />

declare namespace NodeJS {
  interface ProcessEnv {
    /**
     * The built directory structure
     *
     * ```tree
     * ├─┬─┬ dist
     * │ │ └── index.html
     * │ │
     * │ ├─┬ dist-electron
     * │ │ ├── main.js
     * │ │ └── preload.js
     * │
     * ```
     */
    APP_ROOT: string
    /** /dist/ or /public/ */
    VITE_PUBLIC: string
  }
}

// Used in Renderer process, expose in `preload.ts`
interface Window {
  desktopApi: {
    selectFiles: () => Promise<string[]>
    getPaths: () => Promise<{
      userData: string
      videos: string
      documents: string
      temp: string
    }>
    getGpuInfo: () => Promise<{ available: boolean; detail: string }>
    cacheAsset: (args: { assetId: string; sourcePath: string }) => Promise<{ path: string }>
    downloadAsset: (args: {
      assetId: string
      url: string
      filename?: string
    }) => Promise<{ path: string }>
    fileExists: (args: { path: string }) => Promise<boolean>
    startRender: (args: {
      jobId: string
      projectId: string
      manifest: Record<string, unknown>
      outputName?: string
    }) => Promise<{ outputPath: string }>
    uploadRenderOutput: (args: {
      filePath: string
      uploadUrl: string
      contentType?: string
    }) => Promise<{ sizeBytes: number }>
    onRenderProgress: (callback: (event: {
      jobId: string
      outputPath: string
      payload: {
        status?: string
        progress?: number
        message?: string
        error_message?: string
        output_url?: string | null
        output_size_bytes?: number | null
      }
    }) => void) => () => void
    onRenderLog: (callback: (payload: { jobId: string; message: string }) => void) => () => void
    onRenderComplete: (callback: (payload: {
      jobId: string
      outputPath: string
      code: number | null
    }) => void) => () => void
  }
}
