import { useCallback, useEffect, useMemo, useState } from 'react'
import Modal from '../Modal'
import { api } from '../../lib/api'
import type { AppConfig } from '../../lib/config'
import type {
  Asset,
  GenerationCreatePayload,
  GenerationMode,
  GenerationRecord,
  Snippet,
  SnippetIdentity,
  SnippetIdentityWithSnippets,
} from '../../lib/types'

type GenerationFormState = {
  prompt: string
  mode: GenerationMode
  targetAssetId: string
  frameRangeStart: string
  frameRangeEnd: string
  frameIndices: string
  frameRepeatCount: string
  videoAspectRatio: string
  videoResolution: string
  videoNegativePrompt: string
  referenceIdentityId: string
  referenceAssetId: string
}

const INITIAL_FORM: GenerationFormState = {
  prompt: '',
  mode: 'image',
  targetAssetId: '',
  frameRangeStart: '',
  frameRangeEnd: '',
  frameIndices: '',
  frameRepeatCount: '1',
  videoAspectRatio: '16:9',
  videoResolution: '720p',
  videoNegativePrompt: '',
  referenceIdentityId: '',
  referenceAssetId: '',
}

const hasLinkedSnippets = (
  identity: SnippetIdentity | SnippetIdentityWithSnippets,
): identity is SnippetIdentityWithSnippets =>
  Array.isArray((identity as SnippetIdentityWithSnippets).snippets)

type GenerateModalProps = {
  open: boolean
  onClose: () => void
  config: AppConfig
  projectId: string
  assets: Asset[]
  onAssetsUpsert: (incoming: Array<Asset | null | undefined>) => void
  onAssetsRefresh: () => void
}

const GenerateModal = ({
  open,
  onClose,
  config,
  projectId,
  assets,
  onAssetsUpsert,
  onAssetsRefresh,
}: GenerateModalProps) => {
  const [generationForm, setGenerationForm] = useState<GenerationFormState>(INITIAL_FORM)
  const [generationBusy, setGenerationBusy] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [generationIdentities, setGenerationIdentities] = useState<SnippetIdentityWithSnippets[]>(
    [],
  )
  const [generationIdentitiesLoading, setGenerationIdentitiesLoading] = useState(false)
  const [generationReviewOpen, setGenerationReviewOpen] = useState(false)
  const [pendingGeneration, setPendingGeneration] = useState<GenerationRecord | null>(null)

  const isVerifiedFaceSnippet = useCallback((snippet: Snippet) => {
    if (snippet.snippet_type !== 'face') {
      return false
    }

    const verification =
      snippet.source_ref && typeof snippet.source_ref === 'object'
        ? (snippet.source_ref.verification as Record<string, unknown> | undefined)
        : undefined

    const label = typeof verification?.label === 'string' ? verification.label.toLowerCase() : ''
    const confidence =
      typeof verification?.confidence === 'number' ? verification.confidence : Number.NaN

    if (label !== 'face') {
      return false
    }
    if (!Number.isFinite(confidence) || confidence < 0.9) {
      return false
    }

    return true
  }, [])

  const loadGenerationIdentities = useCallback(async () => {
    setGenerationIdentitiesLoading(true)
    try {
      const response = await api.listSnippetIdentities(config, projectId, true)
      const nextIdentities = (response.identities ?? [])
        .filter(hasLinkedSnippets)
        .map((identity) => ({
          ...identity,
          snippets: (identity.snippets ?? []).filter(isVerifiedFaceSnippet),
        }))
        .filter((identity) => identity.snippets.length > 0)
      setGenerationIdentities(nextIdentities)
    } catch {
      setGenerationIdentities([])
    } finally {
      setGenerationIdentitiesLoading(false)
    }
  }, [config, isVerifiedFaceSnippet, projectId])

  useEffect(() => {
    if (!open) {
      return
    }
    setGenerationError(null)
    loadGenerationIdentities().catch(() => {})
  }, [open, loadGenerationIdentities])

  const imageAssets = useMemo(
    () => assets.filter((asset) => asset.asset_type?.startsWith('image/')),
    [assets],
  )

  const videoAssets = useMemo(
    () => assets.filter((asset) => asset.asset_type?.startsWith('video/')),
    [assets],
  )

  const parseFrameIndices = (raw: string): number[] | null => {
    const items = raw
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    if (items.length === 0) {
      return null
    }
    const numbers = items
      .map((item) => Number(item))
      .filter((value) => Number.isInteger(value) && value >= 0)
      .map((value) => Math.trunc(value))
    if (numbers.length === 0) {
      return null
    }
    return Array.from(new Set(numbers)).sort((a, b) => a - b)
  }

  const handleCreateGeneration = async () => {
    const prompt = generationForm.prompt.trim()
    if (!prompt) {
      setGenerationError('Prompt is required.')
      return
    }

    const payload: GenerationCreatePayload = {
      prompt,
      mode: generationForm.mode,
      request_context: {
        source: 'desktop_editor',
      },
    }

    if (generationForm.referenceIdentityId) {
      payload.reference_identity_id = generationForm.referenceIdentityId
    }
    if (generationForm.referenceAssetId) {
      payload.reference_asset_id = generationForm.referenceAssetId
    }

    const isFrameMode =
      generationForm.mode === 'insert_frames' || generationForm.mode === 'replace_frames'
    const isVideoMode = generationForm.mode === 'video'

    if (isVideoMode) {
      payload.model = 'veo-3.1-generate-preview'
      const videoParameters: Record<string, unknown> = {}
      if (generationForm.videoAspectRatio) {
        videoParameters.aspect_ratio = generationForm.videoAspectRatio
      }
      if (generationForm.videoResolution) {
        videoParameters.resolution = generationForm.videoResolution
      }
      const negativePrompt = generationForm.videoNegativePrompt.trim()
      if (negativePrompt) {
        videoParameters.negative_prompt = negativePrompt
      }
      if (Object.keys(videoParameters).length > 0) {
        payload.parameters = {
          ...(payload.parameters ?? {}),
          ...videoParameters,
        }
      }
    }

    if (isFrameMode) {
      if (!generationForm.targetAssetId) {
        setGenerationError('Select a target video asset for frame operations.')
        return
      }
      payload.target_asset_id = generationForm.targetAssetId

      const repeatCountValue = Number(generationForm.frameRepeatCount || '1')
      if (!Number.isInteger(repeatCountValue) || repeatCountValue < 1) {
        setGenerationError('Frame repeat count must be a whole number >= 1.')
        return
      }
      payload.frame_repeat_count = Math.trunc(repeatCountValue)

      const hasRangeStart = generationForm.frameRangeStart.trim().length > 0
      const hasRangeEnd = generationForm.frameRangeEnd.trim().length > 0
      if (hasRangeStart !== hasRangeEnd) {
        setGenerationError('Provide both frame range start and end, or leave both empty.')
        return
      }
      if (hasRangeStart && hasRangeEnd) {
        const startFrame = Number(generationForm.frameRangeStart)
        const endFrame = Number(generationForm.frameRangeEnd)
        if (!Number.isInteger(startFrame) || !Number.isInteger(endFrame)) {
          setGenerationError('Frame range values must be whole numbers.')
          return
        }
        if (startFrame < 0 || endFrame < 0) {
          setGenerationError('Frame range values must be non-negative.')
          return
        }
        payload.frame_range = {
          start_frame: Math.trunc(startFrame),
          end_frame: Math.trunc(endFrame),
        }
      }

      const parsedIndices = parseFrameIndices(generationForm.frameIndices)
      if (parsedIndices && parsedIndices.length > 0) {
        payload.frame_indices = parsedIndices
      }

      if (!payload.frame_range && !payload.frame_indices) {
        setGenerationError('Provide frame range or frame indices for frame operations.')
        return
      }
    }

    setGenerationBusy(true)
    setGenerationError(null)
    try {
      const response = await api.createGeneration(config, projectId, payload)
      const generation = response.generation
      setPendingGeneration(generation)
      onAssetsUpsert([generation.generated_asset ?? null, generation.applied_asset ?? null])
      onClose()
      setGenerationReviewOpen(true)
      onAssetsRefresh()
    } catch (error) {
      setGenerationError((error as Error).message)
    } finally {
      setGenerationBusy(false)
    }
  }

  const handleGenerationDecision = async (decision: 'approve' | 'deny') => {
    if (!pendingGeneration) {
      return
    }
    setGenerationBusy(true)
    setGenerationError(null)
    try {
      const response = await api.decideGeneration(
        config,
        projectId,
        pendingGeneration.generation_id,
        { decision },
      )
      const generation = response.generation
      onAssetsUpsert([generation.generated_asset ?? null, generation.applied_asset ?? null])
      if (generation.status === 'failed' && generation.error_message) {
        setGenerationError(generation.error_message)
      }
      setGenerationReviewOpen(false)
      setPendingGeneration(null)
      onAssetsRefresh()
    } catch (error) {
      setGenerationError((error as Error).message)
    } finally {
      setGenerationBusy(false)
    }
  }

  return (
    <>
      <Modal
        open={open}
        title="Generate Asset"
        onClose={() => {
          if (!generationBusy) {
            onClose()
          }
        }}
      >
        <div className="space-y-4">
          {generationError && (
            <div className="rounded border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-400">
              {generationError}
            </div>
          )}

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Prompt</span>
            <textarea
              rows={3}
              value={generationForm.prompt}
              onChange={(event) =>
                setGenerationForm((prev) => ({ ...prev, prompt: event.target.value }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
              placeholder="Describe what to generate"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Mode</span>
            <select
              value={generationForm.mode}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  mode: event.target.value as GenerationMode,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="image">Image Generation</option>
              <option value="video">Video Generation (Veo 3.1)</option>
              <option value="replace_frames">Replace Frames</option>
              <option value="insert_frames">Insert Frames</option>
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Reference Person (optional)</span>
            <select
              value={generationForm.referenceIdentityId}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  referenceIdentityId: event.target.value,
                  referenceAssetId: event.target.value ? '' : prev.referenceAssetId,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="">None</option>
              {generationIdentities.map((identity) => (
                <option key={identity.identity_id} value={identity.identity_id}>
                  {identity.name}
                </option>
              ))}
            </select>
            {generationIdentitiesLoading && (
              <p className="text-2xs text-neutral-500">Loading people...</p>
            )}
            {!generationIdentitiesLoading && generationIdentities.length === 0 && (
              <p className="text-2xs text-neutral-500">
                No verified people identities available yet.
              </p>
            )}
          </label>

          <label className="block space-y-1">
            <span className="text-xs text-neutral-400">Reference Image Asset (optional)</span>
            <select
              value={generationForm.referenceAssetId}
              onChange={(event) =>
                setGenerationForm((prev) => ({
                  ...prev,
                  referenceAssetId: event.target.value,
                  referenceIdentityId: event.target.value ? '' : prev.referenceIdentityId,
                }))
              }
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="">None</option>
              {imageAssets.map((asset) => (
                <option key={asset.asset_id} value={asset.asset_id}>
                  {asset.asset_name}
                </option>
              ))}
            </select>
          </label>

          {(generationForm.mode === 'insert_frames' ||
            generationForm.mode === 'replace_frames') && (
            <>
              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Target Video Asset</span>
                <select
                  value={generationForm.targetAssetId}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      targetAssetId: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="">Select video asset</option>
                  {videoAssets.map((asset) => (
                    <option key={asset.asset_id} value={asset.asset_id}>
                      {asset.asset_name}
                    </option>
                  ))}
                </select>
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-1">
                  <span className="text-xs text-neutral-400">Frame Start</span>
                  <input
                    type="number"
                    min={0}
                    value={generationForm.frameRangeStart}
                    onChange={(event) =>
                      setGenerationForm((prev) => ({
                        ...prev,
                        frameRangeStart: event.target.value,
                      }))
                    }
                    className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                    placeholder="e.g. 10"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-neutral-400">Frame End</span>
                  <input
                    type="number"
                    min={0}
                    value={generationForm.frameRangeEnd}
                    onChange={(event) =>
                      setGenerationForm((prev) => ({
                        ...prev,
                        frameRangeEnd: event.target.value,
                      }))
                    }
                    className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                    placeholder="e.g. 20"
                  />
                </label>
              </div>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">
                  Frame Indices (optional, comma-separated)
                </span>
                <input
                  type="text"
                  value={generationForm.frameIndices}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      frameIndices: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="e.g. 12,18,24"
                />
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Frame Repeat Count</span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={generationForm.frameRepeatCount}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      frameRepeatCount: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="1"
                />
                <p className="text-2xs text-neutral-500">
                  Reuse the same generated image across this many consecutive frames per selected
                  frame.
                </p>
              </label>
            </>
          )}

          {generationForm.mode === 'video' && (
            <>
              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Aspect Ratio</span>
                <select
                  value={generationForm.videoAspectRatio}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoAspectRatio: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="16:9">16:9 (Landscape)</option>
                  <option value="9:16">9:16 (Portrait)</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Resolution</span>
                <select
                  value={generationForm.videoResolution}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoResolution: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                >
                  <option value="720p">720p</option>
                  <option value="1080p">1080p</option>
                  <option value="4k">4K</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-neutral-400">Negative Prompt (optional)</span>
                <input
                  type="text"
                  value={generationForm.videoNegativePrompt}
                  onChange={(event) =>
                    setGenerationForm((prev) => ({
                      ...prev,
                      videoNegativePrompt: event.target.value,
                    }))
                  }
                  className="w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-neutral-200 focus:border-accent-500 focus:outline-none"
                  placeholder="e.g. cartoon, low quality"
                />
              </label>
            </>
          )}

          <div className="flex justify-end gap-3">
            <button
              onClick={() => onClose()}
              disabled={generationBusy}
              className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                void handleCreateGeneration()
              }}
              disabled={generationBusy}
              className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 disabled:opacity-60"
            >
              {generationBusy ? 'Generating...' : 'Generate'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        open={generationReviewOpen && Boolean(pendingGeneration)}
        title="Review Generated Asset"
        onClose={() => {
          if (!generationBusy) {
            setGenerationReviewOpen(false)
            setPendingGeneration(null)
          }
        }}
      >
        <div className="space-y-4">
          {pendingGeneration?.generated_preview_url ? (
            pendingGeneration.generated_asset?.asset_type?.startsWith('video/') ? (
              <video
                src={pendingGeneration.generated_preview_url}
                controls
                className="w-full rounded border border-neutral-700 bg-neutral-950 object-contain"
              />
            ) : (
              <img
                src={pendingGeneration.generated_preview_url}
                alt="Generated preview"
                className="w-full rounded border border-neutral-700 bg-neutral-950 object-contain"
              />
            )
          ) : (
            <div className="rounded border border-neutral-800 bg-neutral-900 px-3 py-8 text-center text-xs text-neutral-500">
              Preview unavailable. You can still approve or deny.
            </div>
          )}

          <div className="rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs text-neutral-400">
            <p className="truncate">Prompt: {pendingGeneration?.prompt}</p>
            <p>Mode: {pendingGeneration?.mode}</p>
            {(pendingGeneration?.mode === 'insert_frames' ||
              pendingGeneration?.mode === 'replace_frames') && (
              <p>Frame repeat count: {pendingGeneration?.frame_repeat_count ?? 1}</p>
            )}
            {pendingGeneration?.mode === 'video' && <p>Model: {pendingGeneration?.model}</p>}
          </div>

          {generationError && (
            <div className="rounded border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-400">
              {generationError}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <button
              onClick={() => {
                void handleGenerationDecision('deny')
              }}
              disabled={generationBusy}
              className="rounded border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-60"
            >
              Deny
            </button>
            <button
              onClick={() => {
                void handleGenerationDecision('approve')
              }}
              disabled={generationBusy}
              className="rounded bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 disabled:opacity-60"
            >
              Approve
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}

export default GenerateModal
