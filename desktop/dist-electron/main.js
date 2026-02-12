import { app, BrowserWindow, ipcMain, dialog, Menu, shell } from "electron";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";
import { createServer } from "node:http";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
const __dirname$1 = path.dirname(fileURLToPath(import.meta.url));
const execFileAsync = promisify(execFile);
process.env.APP_ROOT = path.join(__dirname$1, "..");
const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
const MAIN_DIST = path.join(process.env.APP_ROOT, "dist-electron");
const RENDERER_DIST = path.join(process.env.APP_ROOT, "dist");
process.env.VITE_PUBLIC = VITE_DEV_SERVER_URL ? path.join(process.env.APP_ROOT, "public") : RENDERER_DIST;
let win;
const renderProcesses = /* @__PURE__ */ new Map();
const platformExecutable = (name) => process.platform === "win32" ? `${name}.exe` : name;
const resolveBundledResource = (name) => {
  if (!app.isPackaged) {
    return null;
  }
  const candidates = [
    path.join(process.resourcesPath, "render-bundle", name),
    path.join(process.resourcesPath, name)
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
};
const resolveRendererBinary = () => {
  const override = process.env.RENDERER_BIN;
  if (override && fs.existsSync(override)) {
    return override;
  }
  return resolveBundledResource(platformExecutable("renderer"));
};
const resolveFfmpegBin = () => {
  const override = process.env.FFMPEG_BIN;
  if (override && fs.existsSync(override)) {
    return override;
  }
  return resolveBundledResource(platformExecutable("ffmpeg")) ?? "ffmpeg";
};
const resolveFfprobeBin = () => {
  const override = process.env.FFPROBE_BIN;
  if (override && fs.existsSync(override)) {
    return override;
  }
  return resolveBundledResource(platformExecutable("ffprobe")) ?? "ffprobe";
};
const ensureDir = (target) => {
  fs.mkdirSync(target, { recursive: true });
};
const resolveRenderJobDir = () => {
  const candidates = [
    process.env.RENDER_JOB_DIR,
    path.resolve(process.env.APP_ROOT, "..", "render-job"),
    path.resolve(process.env.APP_ROOT, "render-job"),
    path.resolve(process.cwd(), "render-job")
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0] ?? path.resolve(process.cwd(), "render-job");
};
const getAssetCacheRoot = () => path.join(app.getPath("userData"), "cache", "assets");
const getRenderRoot = () => path.join(app.getPath("userData"), "renders");
const getOutputRoot = (projectId) => path.join(app.getPath("videos"), "Auteur", projectId);
const createProgressServer = async (onPayload) => {
  const server = createServer((req, res) => {
    if (req.method !== "POST" || req.url !== "/render-status") {
      res.statusCode = 404;
      res.end();
      return;
    }
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      try {
        const payload = JSON.parse(body);
        onPayload(payload);
        res.statusCode = 200;
        res.end("ok");
      } catch (error) {
        res.statusCode = 400;
        res.end("invalid payload");
      }
    });
  });
  await new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return { server, port };
};
const detectGpu = async () => {
  const ffmpegBin = resolveFfmpegBin();
  const noGpu = (detail) => ({
    available: false,
    detail,
    backend: "none",
    encoders: { h264: false, h265: false }
  });
  const backendSupport = {
    nvidia: { h264: false, h265: false },
    amd: { h264: false, h265: false },
    apple: { h264: false, h265: false }
  };
  try {
    const { stdout } = await execFileAsync(ffmpegBin, ["-hide_banner", "-encoders"]);
    backendSupport.nvidia = {
      h264: stdout.includes("h264_nvenc"),
      h265: stdout.includes("hevc_nvenc")
    };
    backendSupport.amd = {
      h264: stdout.includes("h264_amf"),
      h265: stdout.includes("hevc_amf")
    };
    backendSupport.apple = {
      h264: stdout.includes("h264_videotoolbox"),
      h265: stdout.includes("hevc_videotoolbox")
    };
    const preferredBackends = process.platform === "darwin" ? ["apple", "nvidia", "amd"] : ["nvidia", "amd", "apple"];
    for (const backend of preferredBackends) {
      const encoders = backendSupport[backend];
      if (!encoders.h264 && !encoders.h265) {
        continue;
      }
      const backendLabel = backend === "nvidia" ? "NVENC" : backend === "amd" ? "AMD AMF" : "VideoToolbox";
      const codecLabel = encoders.h264 && encoders.h265 ? "H.264/H.265" : encoders.h264 ? "H.264" : "H.265";
      return {
        available: true,
        detail: `${backendLabel} detected via FFmpeg (${codecLabel})`,
        backend,
        encoders
      };
    }
  } catch (error) {
  }
  try {
    const { stdout } = await execFileAsync("nvidia-smi", ["-L"]);
    if (stdout.toLowerCase().includes("gpu")) {
      return noGpu("NVIDIA GPU found, but FFmpeg hardware encoders are unavailable");
    }
  } catch (error) {
  }
  return noGpu("No compatible GPU encoder detected");
};
function createWindow() {
  win = new BrowserWindow({
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    width: 1420,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#0b0f1c",
    webPreferences: {
      preload: path.join(__dirname$1, "preload.mjs"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  win.webContents.on("did-finish-load", () => {
    win == null ? void 0 : win.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
  });
  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(RENDERER_DIST, "index.html"));
  }
}
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
    win = null;
  }
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
const createApplicationMenu = () => {
  const template = [
    {
      label: "Help",
      submenu: [
        {
          label: "About",
          click: () => {
            dialog.showMessageBox(win, {
              type: "info",
              title: "About",
              message: "Auteur Video Editor",
              detail: "This software uses libraries from the FFmpeg project under the LGPLv2.1 license.\n\nFFmpeg is a trademark of Fabrice Bellard.\n\nFFmpeg source code is available at:\nhttps://ffmpeg.org/download.html",
              buttons: ["OK", "View License"]
            }).then((result) => {
              if (result.response === 1) {
                shell.openExternal("https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html");
              }
            });
          }
        }
      ]
    }
  ];
  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
};
app.whenReady().then(() => {
  createWindow();
  createApplicationMenu();
});
ipcMain.handle("dialog:open-files", async () => {
  if (!win) {
    return [];
  }
  const result = await dialog.showOpenDialog(win, {
    properties: ["openFile", "multiSelections"],
    filters: [
      { name: "Media", extensions: ["mp4", "mov", "mkv", "mp3", "wav", "png", "jpg", "jpeg"] }
    ]
  });
  if (result.canceled) {
    return [];
  }
  return result.filePaths;
});
ipcMain.handle("paths:get", async () => ({
  userData: app.getPath("userData"),
  videos: app.getPath("videos"),
  documents: app.getPath("documents"),
  temp: app.getPath("temp")
}));
ipcMain.handle("system:gpu", async () => detectGpu());
ipcMain.handle("fs:exists", async (_event, args) => {
  const { path: target } = args;
  return fs.existsSync(target);
});
ipcMain.handle(
  "assets:cache",
  async (_event, args) => {
    const { assetId, sourcePath } = args;
    const cacheRoot = getAssetCacheRoot();
    const fileName = path.basename(sourcePath);
    const destDir = path.join(cacheRoot, assetId);
    const destPath = path.join(destDir, fileName);
    ensureDir(destDir);
    fs.copyFileSync(sourcePath, destPath);
    return { path: destPath };
  }
);
ipcMain.handle(
  "assets:download",
  async (_event, args) => {
    const { assetId, url, filename } = args;
    const cacheRoot = getAssetCacheRoot();
    const destDir = path.join(cacheRoot, assetId);
    const name = filename ?? path.basename(new URL(url).pathname);
    const destPath = path.join(destDir, name);
    ensureDir(destDir);
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to download asset: ${response.status}`);
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    fs.writeFileSync(destPath, buffer);
    return { path: destPath };
  }
);
ipcMain.handle("render:start", async (_event, args) => {
  const { jobId, projectId, manifest, outputName } = args;
  const outputRoot = getOutputRoot(projectId);
  ensureDir(outputRoot);
  const outputPath = path.join(outputRoot, outputName ?? `${jobId}.mp4`);
  const renderRoot = path.join(getRenderRoot(), jobId);
  ensureDir(renderRoot);
  const manifestPath = path.join(renderRoot, "manifest.json");
  const manifestToWrite = {
    ...manifest,
    output_path: outputPath,
    output_bucket: "local",
    input_bucket: "local",
    execution_mode: "local"
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifestToWrite, null, 2), "utf-8");
  const { server, port } = await createProgressServer((payload) => {
    win == null ? void 0 : win.webContents.send("render:progress", {
      jobId,
      outputPath,
      payload
    });
  });
  const renderJobDir = resolveRenderJobDir();
  const entrypoint = path.join(renderJobDir, "entrypoint.py");
  const pythonBin = process.env.PYTHON_BIN || "python";
  const bundledRenderer = resolveRendererBinary();
  const tempDir = path.join(app.getPath("temp"), "auteur-render");
  ensureDir(tempDir);
  const env = {
    ...process.env,
    CALLBACK_URL: `http://127.0.0.1:${port}/render-status`,
    RENDER_INPUT_DIR: getAssetCacheRoot(),
    RENDER_OUTPUT_DIR: outputRoot,
    RENDER_TEMP_DIR: tempDir,
    FFMPEG_BIN: resolveFfmpegBin(),
    FFPROBE_BIN: resolveFfprobeBin()
  };
  const rendererArgs = ["--manifest", manifestPath, "--job-id", jobId];
  let command = pythonBin;
  let commandArgs = [entrypoint, ...rendererArgs];
  let commandCwd = renderJobDir;
  if (bundledRenderer) {
    command = bundledRenderer;
    commandArgs = rendererArgs;
    commandCwd = path.dirname(bundledRenderer);
  } else if (app.isPackaged) {
    throw new Error("Bundled renderer executable not found in resources/render-bundle");
  }
  const child = spawn(command, commandArgs, {
    cwd: commandCwd,
    env,
    stdio: ["ignore", "pipe", "pipe"]
  });
  renderProcesses.set(jobId, child);
  child.stdout.on("data", (data) => {
    const message = data.toString();
    win == null ? void 0 : win.webContents.send("render:log", { jobId, message });
  });
  child.stderr.on("data", (data) => {
    const message = data.toString();
    win == null ? void 0 : win.webContents.send("render:log", { jobId, message });
  });
  child.on("close", (code) => {
    renderProcesses.delete(jobId);
    server.close();
    win == null ? void 0 : win.webContents.send("render:complete", {
      jobId,
      outputPath,
      code
    });
  });
  return { outputPath };
});
ipcMain.handle(
  "render:upload-output",
  async (_event, args) => {
    const { filePath, uploadUrl, contentType } = args;
    if (!fs.existsSync(filePath)) {
      throw new Error(`Render output not found: ${filePath}`);
    }
    const buffer = fs.readFileSync(filePath);
    const response = await fetch(uploadUrl, {
      method: "PUT",
      headers: {
        "Content-Type": contentType || "application/octet-stream"
      },
      body: buffer
    });
    if (!response.ok) {
      const message = await response.text();
      throw new Error(`Failed to upload output: ${response.status} ${message}`);
    }
    const stats = fs.statSync(filePath);
    return { sizeBytes: stats.size };
  }
);
export {
  MAIN_DIST,
  RENDERER_DIST,
  VITE_DEV_SERVER_URL
};
