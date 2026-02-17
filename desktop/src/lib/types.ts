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
  /** Absolute local file path (set for locally-imported assets). */
  localPath?: string
  /** Whether this asset has been synced (uploaded) to the backend. */
  synced?: boolean
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

export type EditSessionActivityEvent = {
  event_id: string
  event_type: string
  status: string
  label: string
  created_at?: string | null
  iteration?: number | null
  tool_name?: string | null
  summary?: string | null
  meta?: Record<string, unknown>
}

export type EditSessionDetail = {
  session_id: string
  project_id: string
  timeline_id: string
  title?: string | null
  status: string
  messages: EditSessionMessage[]
  pending_patches: EditSessionPendingPatch[]
  activity_events: EditSessionActivityEvent[]
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
  identity_name?: string | null
  is_identity_poster?: boolean
  display_label?: string | null
  preview_url?: string | null
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

export type SnippetIdentityWithSnippets = SnippetIdentity & {
  snippets: Snippet[]
}

export type SnippetMergeSuggestion = {
  suggestion_id: string
  snippet_id: string
  candidate_identity_id: string
  candidate_identity_name?: string | null
  candidate_identity_canonical_snippet_id?: string | null
  similarity_score: number
  decision: string
  snippet_preview_url?: string | null
  candidate_identity_preview_url?: string | null
  metadata?: Record<string, unknown>
  created_at?: string
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

export type GenerationMode = 'image' | 'video' | 'insert_frames' | 'replace_frames'

export type GenerationFrameRange = {
  start_frame: number
  end_frame: number
}

export type GenerationCreatePayload = {
  prompt: string
  mode: GenerationMode
  target_asset_id?: string | null
  frame_range?: GenerationFrameRange | null
  frame_indices?: number[] | null
  frame_repeat_count?: number | null
  reference_asset_id?: string | null
  reference_snippet_id?: string | null
  reference_identity_id?: string | null
  reference_character_model_id?: string | null
  model?: string | null
  parameters?: Record<string, unknown>
  timeline_id?: string | null
  request_context?: Record<string, unknown>
}

export type GenerationDecisionPayload = {
  decision: 'approve' | 'deny'
  reason?: string | null
}

export type GenerationRecord = {
  generation_id: string
  project_id: string
  timeline_id?: string | null
  request_origin: string
  requestor: string
  provider: string
  model: string
  mode: GenerationMode | string
  status: string
  prompt: string
  parameters: Record<string, unknown>
  reference_asset_id?: string | null
  reference_snippet_id?: string | null
  reference_identity_id?: string | null
  reference_character_model_id?: string | null
  target_asset_id?: string | null
  frame_range?: Record<string, unknown> | null
  frame_indices?: number[] | null
  frame_repeat_count?: number | null
  generated_asset?: Asset | null
  generated_preview_url?: string | null
  applied_asset?: Asset | null
  applied_preview_url?: string | null
  request_context?: Record<string, unknown>
  decision_reason?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
  decided_at?: string | null
  applied_at?: string | null
}

export * from './timelineTypes'
