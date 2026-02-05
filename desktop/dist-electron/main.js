import { app as d, BrowserWindow as D, ipcMain as u, dialog as A } from "electron";
import { fileURLToPath as B } from "node:url";
import e from "node:path";
import p from "node:fs";
import { createServer as L } from "node:http";
import { execFile as x, spawn as V } from "node:child_process";
import { promisify as k } from "node:util";
const I = e.dirname(B(import.meta.url)), j = k(x);
process.env.APP_ROOT = e.join(I, "..");
const R = process.env.VITE_DEV_SERVER_URL, q = e.join(process.env.APP_ROOT, "dist-electron"), T = e.join(process.env.APP_ROOT, "dist");
process.env.VITE_PUBLIC = R ? e.join(process.env.APP_ROOT, "public") : T;
let o;
const E = /* @__PURE__ */ new Map(), v = (s) => {
  p.mkdirSync(s, { recursive: !0 });
}, $ = () => {
  const s = [
    process.env.RENDER_JOB_DIR,
    e.resolve(process.env.APP_ROOT, "..", "render-job"),
    e.resolve(process.env.APP_ROOT, "render-job"),
    e.resolve(process.cwd(), "render-job")
  ].filter(Boolean);
  for (const n of s)
    if (p.existsSync(n))
      return n;
  return s[0] ?? e.resolve(process.cwd(), "render-job");
}, _ = () => e.join(d.getPath("userData"), "cache", "assets"), M = () => e.join(d.getPath("userData"), "renders"), G = (s) => e.join(d.getPath("videos"), "Granite Edit", s), J = async (s) => {
  const n = L((c, i) => {
    if (c.method !== "POST" || c.url !== "/render-status") {
      i.statusCode = 404, i.end();
      return;
    }
    let r = "";
    c.on("data", (a) => {
      r += a;
    }), c.on("end", () => {
      try {
        const a = JSON.parse(r);
        s(a), i.statusCode = 200, i.end("ok");
      } catch {
        i.statusCode = 400, i.end("invalid payload");
      }
    });
  });
  await new Promise((c) => {
    n.listen(0, "127.0.0.1", () => c());
  });
  const t = n.address(), l = typeof t == "object" && t ? t.port : 0;
  return { server: n, port: l };
}, W = async () => {
  const s = process.env.FFMPEG_BIN || "ffmpeg";
  try {
    const { stdout: n } = await j(s, ["-hide_banner", "-encoders"]);
    if (n.includes("h264_nvenc") || n.includes("hevc_nvenc"))
      return { available: !0, detail: "NVENC detected via FFmpeg" };
  } catch {
  }
  try {
    const { stdout: n } = await j("nvidia-smi", ["-L"]);
    if (n.toLowerCase().includes("gpu"))
      return { available: !0, detail: "GPU detected via nvidia-smi" };
  } catch {
  }
  return { available: !1, detail: "No NVIDIA GPU detected" };
};
function S() {
  o = new D({
    icon: e.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    width: 1420,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#0b0f1c",
    webPreferences: {
      preload: e.join(I, "preload.mjs"),
      contextIsolation: !0,
      nodeIntegration: !1
    }
  }), o.webContents.on("did-finish-load", () => {
    o == null || o.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
  }), R ? o.loadURL(R) : o.loadFile(e.join(T, "index.html"));
}
d.on("window-all-closed", () => {
  process.platform !== "darwin" && (d.quit(), o = null);
});
d.on("activate", () => {
  D.getAllWindows().length === 0 && S();
});
d.whenReady().then(S);
u.handle("dialog:open-files", async () => {
  if (!o)
    return [];
  const s = await A.showOpenDialog(o, {
    properties: ["openFile", "multiSelections"],
    filters: [
      { name: "Media", extensions: ["mp4", "mov", "mkv", "mp3", "wav", "png", "jpg", "jpeg"] }
    ]
  });
  return s.canceled ? [] : s.filePaths;
});
u.handle("paths:get", async () => ({
  userData: d.getPath("userData"),
  videos: d.getPath("videos"),
  documents: d.getPath("documents"),
  temp: d.getPath("temp")
}));
u.handle("system:gpu", async () => W());
u.handle("fs:exists", async (s, n) => {
  const { path: t } = n;
  return p.existsSync(t);
});
u.handle(
  "assets:cache",
  async (s, n) => {
    const { assetId: t, sourcePath: l } = n, c = _(), i = e.basename(l), r = e.join(c, t), a = e.join(r, i);
    return v(r), p.copyFileSync(l, a), { path: a };
  }
);
u.handle(
  "assets:download",
  async (s, n) => {
    const { assetId: t, url: l, filename: c } = n, i = _(), r = e.join(i, t), a = c ?? e.basename(new URL(l).pathname), m = e.join(r, a);
    v(r);
    const f = await fetch(l);
    if (!f.ok)
      throw new Error(`Failed to download asset: ${f.status}`);
    const P = Buffer.from(await f.arrayBuffer());
    return p.writeFileSync(m, P), { path: m };
  }
);
u.handle("render:start", async (s, n) => {
  const { jobId: t, projectId: l, manifest: c, outputName: i } = n, r = G(l);
  v(r);
  const a = e.join(r, i ?? `${t}.mp4`), m = e.join(M(), t);
  v(m);
  const f = e.join(m, "manifest.json"), P = {
    ...c,
    output_path: a,
    output_bucket: "local",
    input_bucket: "local",
    execution_mode: "local"
  };
  p.writeFileSync(f, JSON.stringify(P, null, 2), "utf-8");
  const { server: O, port: C } = await J((h) => {
    o == null || o.webContents.send("render:progress", {
      jobId: t,
      outputPath: a,
      payload: h
    });
  }), w = $(), N = e.join(w, "entrypoint.py"), U = process.env.PYTHON_BIN || "python", b = e.join(d.getPath("temp"), "granite-render");
  v(b);
  const F = {
    ...process.env,
    CALLBACK_URL: `http://127.0.0.1:${C}/render-status`,
    RENDER_INPUT_DIR: _(),
    RENDER_OUTPUT_DIR: r,
    RENDER_TEMP_DIR: b
  }, g = V(U, [N, "--manifest", f, "--job-id", t], {
    cwd: w,
    env: F,
    stdio: ["ignore", "pipe", "pipe"]
  });
  return E.set(t, g), g.stdout.on("data", (h) => {
    const y = h.toString();
    o == null || o.webContents.send("render:log", { jobId: t, message: y });
  }), g.stderr.on("data", (h) => {
    const y = h.toString();
    o == null || o.webContents.send("render:log", { jobId: t, message: y });
  }), g.on("close", (h) => {
    E.delete(t), O.close(), o == null || o.webContents.send("render:complete", {
      jobId: t,
      outputPath: a,
      code: h
    });
  }), { outputPath: a };
});
u.handle(
  "render:upload-output",
  async (s, n) => {
    const { filePath: t, uploadUrl: l, contentType: c } = n;
    if (!p.existsSync(t))
      throw new Error(`Render output not found: ${t}`);
    const i = p.readFileSync(t), r = await fetch(l, {
      method: "PUT",
      headers: {
        "Content-Type": c || "application/octet-stream"
      },
      body: i
    });
    if (!r.ok) {
      const m = await r.text();
      throw new Error(`Failed to upload output: ${r.status} ${m}`);
    }
    return { sizeBytes: p.statSync(t).size };
  }
);
export {
  q as MAIN_DIST,
  T as RENDERER_DIST,
  R as VITE_DEV_SERVER_URL
};
