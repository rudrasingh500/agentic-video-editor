import type { AppConfig } from './config'
import type {
  Asset,
  EditPatchSummary,
  EditSessionDetail,
  EditSessionSummary,
  Project,
} from './types'

const normalizeBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, '')

const apiFetch = async <T>(
  config: AppConfig,
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const url = `${normalizeBaseUrl(config.baseUrl)}${path}`
  const headers = new Headers(options.headers ?? {})

  if (config.devToken) {
    headers.set('Authorization', `Bearer ${config.devToken}`)
  }

  const isFormData = options.body instanceof FormData
  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const data = await response.json()
      detail = data.detail ?? JSON.stringify(data)
    } catch (error) {
      // Ignore JSON parsing errors.
    }
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

export const api = {
  health: (config: AppConfig) => apiFetch<{ status: string }>(config, '/health/'),
  listProjects: (config: AppConfig) =>
    apiFetch<{ ok: boolean; projects: Project[] }>(config, '/projects/'),
  createProject: (config: AppConfig, name: string) =>
    apiFetch<{ ok: boolean; project_id: string; project_name: string }>(
      config,
      '/projects/',
      {
        method: 'POST',
        body: JSON.stringify({ name }),
      },
    ),
  getProject: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; project_id: string; project_name: string }>(
      config,
      `/projects/${projectId}`,
    ),
  deleteProject: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean }>(config, `/projects/${projectId}`, {
      method: 'DELETE',
    }),
  listAssets: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; assets: Asset[] }>(
      config,
      `/projects/${projectId}/assets`,
    ),
  uploadAsset: (config: AppConfig, projectId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiFetch<{ ok: boolean; asset: Asset }>(
      config,
      `/projects/${projectId}/assets`,
      {
        method: 'POST',
        body: formData,
      },
    )
  },
  getAssetDownloadUrl: (config: AppConfig, projectId: string, assetId: string) =>
    apiFetch<{ ok: boolean; url: string; expires_in: number }>(
      config,
      `/projects/${projectId}/assets/${assetId}/download`,
    ),
  deleteAsset: (config: AppConfig, projectId: string, assetId: string) =>
    apiFetch<{ ok: boolean }>(
      config,
      `/projects/${projectId}/assets/${assetId}`,
      { method: 'DELETE' },
    ),
  getTimeline: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; timeline: Record<string, unknown>; version: number }>(
      config,
      `/projects/${projectId}/timeline`,
    ),
  sendEditRequest: (
    config: AppConfig,
    projectId: string,
    message: string,
    sessionId?: string | null,
  ) =>
    apiFetch<{
      ok: boolean
      session_id: string
      message: string
      pending_patches: EditPatchSummary[]
      warnings: string[]
      applied: boolean
      new_version: number | null
      }>(config, `/projects/${projectId}/edit`, {
        method: 'POST',
        body: JSON.stringify({ message, session_id: sessionId }),
      }),
  listEditSessions: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; sessions: EditSessionSummary[]; total: number }>(
      config,
      `/projects/${projectId}/edit/sessions`,
    ),
  getEditSession: (config: AppConfig, projectId: string, sessionId: string) =>
    apiFetch<{ ok: boolean } & EditSessionDetail>(
      config,
      `/projects/${projectId}/edit/sessions/${sessionId}`,
    ),
  applyPatches: (
    config: AppConfig,
    projectId: string,
    sessionId: string,
    patchIds: string[],
  ) =>
    apiFetch<{
      ok: boolean
      new_version: number | null
      operations_applied: number
      errors: string[]
    }>(config, `/projects/${projectId}/edit/sessions/${sessionId}/apply`, {
      method: 'POST',
      body: JSON.stringify({ patch_ids: patchIds, description: 'Applied AI edits' }),
    }),
  createRenderJob: (
    config: AppConfig,
    projectId: string,
    payload: Record<string, unknown>,
  ) =>
    apiFetch<{ ok: boolean; job: { job_id: string; status: string } }>(
      config,
      `/projects/${projectId}/render`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  listRenderJobs: (
    config: AppConfig,
    projectId: string,
    status?: string,
    limit: number = 10,
    offset: number = 0,
  ) => {
    const params = new URLSearchParams()
    if (status) {
      params.set('status', status)
    }
    params.set('limit', String(limit))
    params.set('offset', String(offset))
    const query = params.toString()
    const suffix = query ? `?${query}` : ''
    return apiFetch<{ ok: boolean; jobs: Record<string, unknown>[]; total: number }>(
      config,
      `/projects/${projectId}/renders${suffix}`,
    )
  },
  getRenderManifest: (config: AppConfig, projectId: string, jobId: string) =>
    apiFetch<{ ok: boolean; manifest_url: string; expires_in: number }>(
      config,
      `/projects/${projectId}/renders/${jobId}/manifest`,
    ),
  reportRenderProgress: (
    config: AppConfig,
    projectId: string,
    jobId: string,
    payload: Record<string, unknown>,
  ) =>
    apiFetch<{ ok: boolean }>(
      config,
      `/projects/${projectId}/renders/${jobId}/webhook`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: config.renderWebhookSecret
          ? { 'X-Render-Webhook-Secret': config.renderWebhookSecret }
          : undefined,
      },
    ),
  getOutputUploadUrl: (
    config: AppConfig,
    projectId: string,
    filename: string,
    contentType?: string,
  ) =>
    apiFetch<{ ok: boolean; upload_url: string; gcs_path: string; expires_in?: number }>(
      config,
      `/projects/${projectId}/outputs/upload-url`,
      {
        method: 'POST',
        body: JSON.stringify({ filename, content_type: contentType }),
      },
    ),
  shareOutput: (
    config: AppConfig,
    projectId: string,
    gcsPath: string,
    changes?: Record<string, unknown> | null,
  ) =>
    apiFetch<{
      ok: boolean
      video_id: string
      video_url: string
      version: number
      created_at: string
    }>(config, `/projects/${projectId}/outputs`, {
      method: 'POST',
      body: JSON.stringify({ gcs_path: gcsPath, changes }),
    }),
}
