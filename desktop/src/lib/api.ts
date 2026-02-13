import type { AppConfig } from './config'
import type {
  Asset,
  CharacterModel,
  EditPatchSummary,
  EditSessionActivityEvent,
  EditSessionDetail,
  EditSessionSummary,
  GenerationCreatePayload,
  GenerationDecisionPayload,
  GenerationRecord,
  Project,
  Snippet,
  SnippetIdentity,
  SnippetIdentityWithSnippets,
  SnippetMergeSuggestion,
} from './types'

const normalizeBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, '')

type SessionCreateResponse = {
  ok: boolean
  session_id: string
  user_id: string
  expires_at: string
  session_token: string
  webhook_token: string
}

type SessionValidateResponse = {
  valid: boolean
  user_id?: string | null
  scopes?: string[]
  webhook_token?: string | null
}

const apiFetch = async <T>(
  config: AppConfig,
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const url = `${normalizeBaseUrl(config.baseUrl)}${path}`
  const headers = new Headers(options.headers ?? {})

  if (config.devToken && !config.sessionToken) {
    headers.set('Authorization', `Bearer ${config.devToken}`)
  }

  if (config.sessionToken) {
    headers.set('X-Session-Token', config.sessionToken)
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

type StreamEditEvent = EditSessionActivityEvent

const streamNdjson = async (
  response: Response,
  onEvent: (event: StreamEditEvent) => void,
) => {
  if (!response.body) {
    throw new Error('Streaming response body is empty')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  let reading = true
  while (reading) {
    const { done, value } = await reader.read()
    if (done) {
      reading = false
      continue
    }
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) {
        continue
      }
      try {
        onEvent(JSON.parse(trimmed) as StreamEditEvent)
      } catch {
        // Ignore malformed event lines.
      }
    }
  }

  const tail = buffer.trim()
  if (tail) {
    try {
      onEvent(JSON.parse(tail) as StreamEditEvent)
    } catch {
      // Ignore malformed tail.
    }
  }
}

export const api = {
  health: (config: AppConfig) => apiFetch<{ status: string }>(config, '/health/'),
  createSession: (config: AppConfig) =>
    apiFetch<SessionCreateResponse>(config, '/auth/session', {
      method: 'POST',
    }),
  validateSession: (config: AppConfig) =>
    apiFetch<SessionValidateResponse>(config, '/auth/session/validate'),
  deleteSession: (config: AppConfig) =>
    apiFetch<{ ok: boolean }>(config, '/auth/session', {
      method: 'DELETE',
    }),
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
  listSnippets: (config: AppConfig, projectId: string, snippetType?: string) =>
    apiFetch<{ ok: boolean; snippets: Snippet[] }>(
      config,
      snippetType
        ? `/projects/${projectId}/snippets?snippet_type=${encodeURIComponent(snippetType)}`
        : `/projects/${projectId}/snippets`,
    ),
  getSnippet: (config: AppConfig, projectId: string, snippetId: string) =>
    apiFetch<{ ok: boolean; snippet: Snippet; preview_url?: string | null }>(
      config,
      `/projects/${projectId}/snippets/items/${snippetId}`,
    ),
  listSnippetIdentities: (
    config: AppConfig,
    projectId: string,
    includeSnippets: boolean = false,
  ) =>
    apiFetch<{ ok: boolean; identities: Array<SnippetIdentity | SnippetIdentityWithSnippets> }>(
      config,
      includeSnippets
        ? `/projects/${projectId}/snippets/identities?include_snippets=true`
        : `/projects/${projectId}/snippets/identities`,
    ),
  updateSnippetIdentity: (
    config: AppConfig,
    projectId: string,
    identityId: string,
    payload: { name?: string; description?: string },
  ) =>
    apiFetch<{ ok: boolean; identity: SnippetIdentity }>(
      config,
      `/projects/${projectId}/snippets/identities/${identityId}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    ),
  mergeSnippetIdentities: (
    config: AppConfig,
    projectId: string,
    payload: { source_identity_ids: string[]; target_identity_id: string; actor?: string; reason?: string },
  ) =>
    apiFetch<{ ok: boolean; identity: SnippetIdentity }>(
      config,
      `/projects/${projectId}/snippets/identities/merge`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  listCharacterModels: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; character_models: CharacterModel[] }>(
      config,
      `/projects/${projectId}/snippets/character-models`,
    ),
  listSnippetMergeSuggestions: (config: AppConfig, projectId: string) =>
    apiFetch<{ ok: boolean; suggestions: SnippetMergeSuggestion[] }>(
      config,
      `/projects/${projectId}/snippets/merge-suggestions`,
    ),
  decideSnippetMergeSuggestion: (
    config: AppConfig,
    projectId: string,
    suggestionId: string,
    decision: 'accepted' | 'rejected',
  ) =>
    apiFetch<{ ok: boolean; suggestion_id: string; decision: string }>(
      config,
      `/projects/${projectId}/snippets/merge-suggestions/${suggestionId}/decision`,
      {
        method: 'POST',
        body: JSON.stringify({ decision, actor: 'user' }),
      },
    ),
  createGeneration: (
    config: AppConfig,
    projectId: string,
    payload: GenerationCreatePayload,
  ) =>
    apiFetch<{ ok: boolean; generation: GenerationRecord }>(
      config,
      `/projects/${projectId}/generations`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  decideGeneration: (
    config: AppConfig,
    projectId: string,
    generationId: string,
    payload: GenerationDecisionPayload,
  ) =>
    apiFetch<{ ok: boolean; generation: GenerationRecord }>(
      config,
      `/projects/${projectId}/generations/${generationId}/decision`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  getGeneration: (config: AppConfig, projectId: string, generationId: string) =>
    apiFetch<{ ok: boolean; generation: GenerationRecord }>(
      config,
      `/projects/${projectId}/generations/${generationId}`,
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
  streamEditRequest: async (
    config: AppConfig,
    projectId: string,
    message: string,
    onEvent: (event: StreamEditEvent) => void,
    sessionId?: string | null,
  ) => {
    const url = `${normalizeBaseUrl(config.baseUrl)}/projects/${projectId}/edit/stream`
    const headers = new Headers()
    if (config.devToken && !config.sessionToken) {
      headers.set('Authorization', `Bearer ${config.devToken}`)
    }
    if (config.sessionToken) {
      headers.set('X-Session-Token', config.sessionToken)
    }
    headers.set('Content-Type', 'application/json')

    const response = await fetch(url, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify({ message, session_id: sessionId }),
    })

    if (!response.ok) {
      let detail = response.statusText
      try {
        const data = await response.json()
        detail = data.detail ?? JSON.stringify(data)
      } catch {
        // Ignore JSON parsing errors.
      }
      throw new Error(detail)
    }

    await streamNdjson(response, onEvent)
  },
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
  ) => {
    const webhookSecret = config.webhookToken || config.renderWebhookSecret
    return apiFetch<{ ok: boolean }>(
      config,
      `/projects/${projectId}/renders/${jobId}/webhook`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: webhookSecret
          ? { 'X-Render-Webhook-Secret': webhookSecret }
          : undefined,
      },
    )
  },
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
