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
