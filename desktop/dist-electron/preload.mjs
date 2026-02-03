"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("desktopApi", {
  selectFiles: () => electron.ipcRenderer.invoke("dialog:open-files"),
  getPaths: () => electron.ipcRenderer.invoke("paths:get"),
  getGpuInfo: () => electron.ipcRenderer.invoke("system:gpu"),
  cacheAsset: (args) => electron.ipcRenderer.invoke("assets:cache", args),
  downloadAsset: (args) => electron.ipcRenderer.invoke("assets:download", args),
  fileExists: (args) => electron.ipcRenderer.invoke("fs:exists", args),
  startRender: (args) => electron.ipcRenderer.invoke("render:start", args),
  uploadRenderOutput: (args) => electron.ipcRenderer.invoke("render:upload-output", args),
  onRenderProgress: (callback) => {
    const listener = (_event, payload) => {
      callback(payload);
    };
    electron.ipcRenderer.on("render:progress", listener);
    return () => electron.ipcRenderer.off("render:progress", listener);
  },
  onRenderLog: (callback) => {
    const listener = (_event, payload) => {
      callback(payload);
    };
    electron.ipcRenderer.on("render:log", listener);
    return () => electron.ipcRenderer.off("render:log", listener);
  },
  onRenderComplete: (callback) => {
    const listener = (_event, payload) => {
      callback(payload);
    };
    electron.ipcRenderer.on("render:complete", listener);
    return () => electron.ipcRenderer.off("render:complete", listener);
  }
});
