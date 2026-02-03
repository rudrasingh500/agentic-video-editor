import { ipcRenderer, contextBridge } from 'electron'

type RenderProgressEvent = {
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
}

contextBridge.exposeInMainWorld('desktopApi', {
  selectFiles: () => ipcRenderer.invoke('dialog:open-files'),
  getPaths: () => ipcRenderer.invoke('paths:get'),
  getGpuInfo: () => ipcRenderer.invoke('system:gpu'),
  cacheAsset: (args: { assetId: string; sourcePath: string }) =>
    ipcRenderer.invoke('assets:cache', args),
  downloadAsset: (args: { assetId: string; url: string; filename?: string }) =>
    ipcRenderer.invoke('assets:download', args),
  fileExists: (args: { path: string }) => ipcRenderer.invoke('fs:exists', args),
  startRender: (args: {
    jobId: string
    projectId: string
    manifest: Record<string, unknown>
    outputName?: string
  }) => ipcRenderer.invoke('render:start', args),
  uploadRenderOutput: (args: { filePath: string; uploadUrl: string; contentType?: string }) =>
    ipcRenderer.invoke('render:upload-output', args),
  onRenderProgress: (callback: (event: RenderProgressEvent) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: RenderProgressEvent) => {
      callback(payload)
    }
    ipcRenderer.on('render:progress', listener)
    return () => ipcRenderer.off('render:progress', listener)
  },
  onRenderLog: (callback: (payload: { jobId: string; message: string }) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: { jobId: string; message: string }) => {
      callback(payload)
    }
    ipcRenderer.on('render:log', listener)
    return () => ipcRenderer.off('render:log', listener)
  },
  onRenderComplete: (callback: (payload: { jobId: string; outputPath: string; code: number | null }) => void) => {
    const listener = (
      _event: Electron.IpcRendererEvent,
      payload: { jobId: string; outputPath: string; code: number | null },
    ) => {
      callback(payload)
    }
    ipcRenderer.on('render:complete', listener)
    return () => ipcRenderer.off('render:complete', listener)
  },
})
