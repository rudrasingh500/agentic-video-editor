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
