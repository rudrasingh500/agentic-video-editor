export type Project = {
  project_id: string
  project_name: string
  updated_at?: string
}

export type Asset = {
  asset_id: string
  asset_name: string
  asset_type?: string
  asset_url?: string
  uploaded_at?: string
  indexing_status?: string
  indexing_error?: string | null
  indexing_attempts?: number
}

export type EditPatchSummary = {
  patch_id: string
  agent_type: string
  operation_count: number
  description: string
  created_at: string
}

export type EditSessionSummary = {
  session_id: string
  title?: string | null
  status: string
  message_count: number
  pending_patch_count: number
  created_at: string
  updated_at: string
}

export type EditSessionMessage = {
  role: string
  content: string
  created_at?: string
}

export type EditSessionPendingPatch = {
  patch_id: string
  agent_type?: string
  patch?: {
    description?: string
    operations?: Array<Record<string, unknown>>
  } | null
  created_at?: string
}

export type EditSessionDetail = {
  session_id: string
  project_id: string
  timeline_id: string
  title?: string | null
  status: string
  messages: EditSessionMessage[]
  pending_patches: EditSessionPendingPatch[]
  created_at: string
  updated_at: string
}

export type Snippet = {
  snippet_id: string
  project_id: string
  asset_id?: string | null
  snippet_type: string
  source_type: string
  source_ref: Record<string, unknown>
  frame_index?: number | null
  timestamp_ms?: number | null
  bbox?: Record<string, unknown> | null
  descriptor?: string | null
  tags: string[]
  notes?: string | null
  quality_score?: number | null
  created_by: string
  created_at: string
}

export type SnippetIdentity = {
  identity_id: string
  project_id: string
  identity_type: string
  name: string
  description?: string | null
  status: string
  canonical_snippet_id?: string | null
  merged_into_id?: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type CharacterModel = {
  character_model_id: string
  project_id: string
  model_type: string
  name: string
  description?: string | null
  canonical_prompt?: string | null
  status: string
  canonical_snippet_id?: string | null
  merged_into_id?: string | null
  created_by: string
  created_at: string
  updated_at: string
}
