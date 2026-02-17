import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, X, Users } from 'lucide-react'
import Modal from '../Modal'
import { api } from '../../lib/api'
import type { AppConfig } from '../../lib/config'
import type {
  Snippet,
  SnippetIdentity,
  SnippetIdentityWithSnippets,
  SnippetMergeSuggestion,
} from '../../lib/types'

type SnippetPreviewModalState = {
  imageUrl: string
  title: string
  subtitle?: string
}

const hasLinkedSnippets = (
  identity: SnippetIdentity | SnippetIdentityWithSnippets,
): identity is SnippetIdentityWithSnippets =>
  Array.isArray((identity as SnippetIdentityWithSnippets).snippets)

type PeoplePanelProps = {
  config: AppConfig
  projectId: string
}

const PeoplePanel = ({ config, projectId }: PeoplePanelProps) => {
  const [snippets, setSnippets] = useState<Snippet[]>([])
  const [peopleLoading, setPeopleLoading] = useState(false)
  const [peopleError, setPeopleError] = useState<string | null>(null)
  const [identities, setIdentities] = useState<SnippetIdentityWithSnippets[]>([])
  const [mergeSuggestions, setMergeSuggestions] = useState<SnippetMergeSuggestion[]>([])
  const [selectedIdentityIds, setSelectedIdentityIds] = useState<string[]>([])
  const [mergeTargetId, setMergeTargetId] = useState('')
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({})
  const [snippetPreviewModal, setSnippetPreviewModal] = useState<SnippetPreviewModalState | null>(
    null,
  )

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

  const loadPeopleData = useCallback(async () => {
    setPeopleLoading(true)
    setPeopleError(null)
    try {
      const [snippetsResponse, identitiesResponse, suggestionsResponse] = await Promise.all([
        api.listSnippets(config, projectId, 'face'),
        api.listSnippetIdentities(config, projectId, true),
        api.listSnippetMergeSuggestions(config, projectId),
      ])
      const nextSnippets = (snippetsResponse.snippets ?? []).filter(isVerifiedFaceSnippet)
      const verifiedSnippetIds = new Set(nextSnippets.map((snippet) => snippet.snippet_id))
      const nextIdentities = (identitiesResponse.identities ?? [])
        .filter(hasLinkedSnippets)
        .map((identity) => ({
          ...identity,
          snippets: (identity.snippets ?? []).filter(isVerifiedFaceSnippet),
        }))
        .filter((identity) => identity.snippets.length > 0)
      const nextSuggestions = (suggestionsResponse.suggestions ?? []).filter((suggestion) =>
        verifiedSnippetIds.has(suggestion.snippet_id),
      )
      setSnippets(nextSnippets)
      setIdentities(nextIdentities)
      setMergeSuggestions(nextSuggestions)
    } catch (error) {
      setPeopleError((error as Error).message)
    } finally {
      setPeopleLoading(false)
    }
  }, [config, isVerifiedFaceSnippet, projectId])

  useEffect(() => {
    loadPeopleData().catch(() => {})
  }, [loadPeopleData])

  const toggleIdentitySelection = (identityId: string) => {
    setSelectedIdentityIds((prev) =>
      prev.includes(identityId)
        ? prev.filter((item) => item !== identityId)
        : [...prev, identityId],
    )
  }

  const handleRenameIdentity = async (identity: SnippetIdentityWithSnippets) => {
    const draft = (renameDrafts[identity.identity_id] ?? identity.name).trim()
    if (!draft || draft === identity.name) {
      return
    }
    try {
      await api.updateSnippetIdentity(config, projectId, identity.identity_id, {
        name: draft,
      })
      await loadPeopleData()
    } catch (error) {
      setPeopleError((error as Error).message)
    }
  }

  const handleMergeIdentities = async () => {
    if (!mergeTargetId) {
      setPeopleError('Pick a target identity to keep before merging.')
      return
    }
    const sourceIds = selectedIdentityIds.filter((identityId) => identityId !== mergeTargetId)
    if (sourceIds.length === 0) {
      setPeopleError('Select at least two identities so one can merge into the target.')
      return
    }
    try {
      await api.mergeSnippetIdentities(config, projectId, {
        source_identity_ids: sourceIds,
        target_identity_id: mergeTargetId,
        actor: 'user',
        reason: 'Merged from desktop people panel',
      })
      setSelectedIdentityIds([])
      setMergeTargetId('')
      await loadPeopleData()
    } catch (error) {
      setPeopleError((error as Error).message)
    }
  }

  const handleSuggestionDecision = async (
    suggestionId: string,
    decision: 'accepted' | 'rejected',
  ) => {
    try {
      await api.decideSnippetMergeSuggestion(config, projectId, suggestionId, decision)
      await loadPeopleData()
    } catch (error) {
      setPeopleError((error as Error).message)
    }
  }

  const linkedSnippetIds = useMemo(() => {
    const ids = new Set<string>()
    for (const identity of identities) {
      for (const snippet of identity.snippets || []) {
        ids.add(snippet.snippet_id)
      }
    }
    return ids
  }, [identities])

  const unlinkedFaceSnippets = useMemo(
    () =>
      snippets.filter(
        (snippet) => isVerifiedFaceSnippet(snippet) && !linkedSnippetIds.has(snippet.snippet_id),
      ),
    [isVerifiedFaceSnippet, linkedSnippetIds, snippets],
  )

  const identityPreviewSnippet = (identity: SnippetIdentityWithSnippets) => {
    if (identity.canonical_snippet_id) {
      const canonical = identity.snippets.find(
        (snippet) => snippet.snippet_id === identity.canonical_snippet_id,
      )
      if (canonical) {
        return canonical
      }
    }
    return identity.snippets[0]
  }

  const openSnippetPreview = useCallback(
    (imageUrl: string | null | undefined, title: string, subtitle?: string) => {
      if (!imageUrl) {
        return
      }
      setSnippetPreviewModal({ imageUrl, title, subtitle })
    },
    [],
  )

  return (
    <>
      <div className="space-y-3">
        {peopleError && (
          <div className="rounded-lg border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-400">
            {peopleError}
          </div>
        )}

        <div className="rounded-lg border border-neutral-800 bg-neutral-850 p-2">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-neutral-300">
              <Users className="h-3.5 w-3.5" />
              {selectedIdentityIds.length} selected
            </div>
            <button
              type="button"
              onClick={() => {
                setSelectedIdentityIds([])
                setMergeTargetId('')
              }}
              className="text-2xs text-neutral-500 hover:text-neutral-300"
            >
              Clear
            </button>
          </div>
          <div className="space-y-2">
            <select
              value={mergeTargetId}
              onChange={(event) => setMergeTargetId(event.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
            >
              <option value="">Select identity to keep</option>
              {selectedIdentityIds.map((identityId) => {
                const identity = identities.find((item) => item.identity_id === identityId)
                return (
                  <option key={identityId} value={identityId}>
                    {identity?.name ?? identityId.slice(0, 8)}
                  </option>
                )
              })}
            </select>
            <button
              type="button"
              onClick={() => {
                void handleMergeIdentities()
              }}
              disabled={selectedIdentityIds.length < 2 || !mergeTargetId}
              className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs text-neutral-200 transition-colors hover:border-neutral-600 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Merge selected identities
            </button>
          </div>
        </div>

        {mergeSuggestions.length > 0 && (
          <div className="space-y-2">
            <p className="text-2xs uppercase tracking-wide text-neutral-500">
              Merge Suggestions
            </p>
            {mergeSuggestions.map((suggestion) => (
              <div
                key={suggestion.suggestion_id}
                className="rounded-lg border border-neutral-800 bg-neutral-850 p-2"
              >
                <div className="mb-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      openSnippetPreview(
                        suggestion.snippet_preview_url,
                        'Suggested Snippet',
                        suggestion.snippet_id,
                      )
                    }
                    disabled={!suggestion.snippet_preview_url}
                    className="h-14 w-14 overflow-hidden rounded border border-neutral-700 bg-neutral-900 transition-colors hover:border-neutral-500 disabled:cursor-default disabled:hover:border-neutral-700"
                  >
                    {suggestion.snippet_preview_url ? (
                      <img
                        src={suggestion.snippet_preview_url}
                        alt="Suggested snippet"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-2xs text-neutral-600">
                        No preview
                      </div>
                    )}
                  </button>
                  <div className="text-2xs text-neutral-300">
                    <p>Candidate: {suggestion.candidate_identity_name ?? 'Unknown identity'}</p>
                    <p className="text-neutral-500">
                      Similarity: {Math.round((suggestion.similarity_score ?? 0) * 100)}%
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      openSnippetPreview(
                        suggestion.candidate_identity_preview_url,
                        suggestion.candidate_identity_name ?? 'Candidate Identity',
                        suggestion.candidate_identity_id,
                      )
                    }
                    disabled={!suggestion.candidate_identity_preview_url}
                    className="h-14 w-14 overflow-hidden rounded border border-neutral-700 bg-neutral-900 transition-colors hover:border-neutral-500 disabled:cursor-default disabled:hover:border-neutral-700"
                  >
                    {suggestion.candidate_identity_preview_url ? (
                      <img
                        src={suggestion.candidate_identity_preview_url}
                        alt="Candidate identity"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-2xs text-neutral-600">
                        No preview
                      </div>
                    )}
                  </button>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      void handleSuggestionDecision(suggestion.suggestion_id, 'accepted')
                    }}
                    className="flex-1 rounded border border-emerald-700/60 bg-emerald-900/30 px-2 py-1 text-2xs text-emerald-300 hover:bg-emerald-900/50"
                  >
                    <span className="inline-flex items-center gap-1">
                      <Check className="h-3 w-3" /> Accept
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleSuggestionDecision(suggestion.suggestion_id, 'rejected')
                    }}
                    className="flex-1 rounded border border-red-700/60 bg-red-900/30 px-2 py-1 text-2xs text-red-300 hover:bg-red-900/50"
                  >
                    <span className="inline-flex items-center gap-1">
                      <X className="h-3 w-3" /> Reject
                    </span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {peopleLoading && identities.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-neutral-600">
            <span className="text-xs">Loading people...</span>
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <p className="text-2xs uppercase tracking-wide text-neutral-500">
                Identities
              </p>
              {identities.length === 0 ? (
                <p className="rounded-lg border border-neutral-800 bg-neutral-850 px-3 py-2 text-2xs text-neutral-500">
                  No identities available yet.
                </p>
              ) : (
                identities.map((identity) => {
                  const preview = identityPreviewSnippet(identity)
                  const selected = selectedIdentityIds.includes(identity.identity_id)
                  return (
                    <div
                      key={identity.identity_id}
                      className={`rounded-lg border p-2 transition-colors ${
                        selected
                          ? 'border-accent-500/60 bg-accent-500/10'
                          : 'border-neutral-800 bg-neutral-850'
                      }`}
                    >
                      <div className="mb-2 flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleIdentitySelection(identity.identity_id)}
                          className="mt-1 h-3.5 w-3.5 rounded border-neutral-600 bg-neutral-900 text-accent-500"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            openSnippetPreview(
                              preview?.preview_url,
                              identity.name,
                              preview?.snippet_id,
                            )
                          }
                          disabled={!preview?.preview_url}
                          className="h-14 w-14 overflow-hidden rounded border border-neutral-700 bg-neutral-900 transition-colors hover:border-neutral-500 disabled:cursor-default disabled:hover:border-neutral-700"
                        >
                          {preview?.preview_url ? (
                            <img
                              src={preview.preview_url}
                              alt={identity.name}
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-2xs text-neutral-600">
                              No preview
                            </div>
                          )}
                        </button>
                        <div className="min-w-0 flex-1 space-y-1">
                          <input
                            type="text"
                            value={renameDrafts[identity.identity_id] ?? identity.name}
                            onChange={(event) =>
                              setRenameDrafts((prev) => ({
                                ...prev,
                                [identity.identity_id]: event.target.value,
                              }))
                            }
                            className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs text-neutral-200 focus:border-accent-500 focus:outline-none"
                          />
                          <div className="flex items-center justify-between text-2xs text-neutral-500">
                            <span>{identity.snippets.length} snippets</span>
                            <button
                              type="button"
                              onClick={() => {
                                void handleRenameIdentity(identity)
                              }}
                              className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300 hover:bg-neutral-700"
                            >
                              Save name
                            </button>
                          </div>
                        </div>
                      </div>
                      {identity.snippets.length > 0 && (
                        <div className="grid grid-cols-4 gap-1">
                          {identity.snippets.slice(0, 8).map((snippet) => (
                            <button
                              type="button"
                              key={snippet.snippet_id}
                              onClick={() =>
                                openSnippetPreview(
                                  snippet.preview_url,
                                  identity.name,
                                  snippet.snippet_id,
                                )
                              }
                              className="aspect-square overflow-hidden rounded border border-neutral-800 bg-neutral-900 transition-colors hover:border-neutral-600"
                              title={snippet.snippet_id}
                            >
                              {snippet.preview_url ? (
                                <img
                                  src={snippet.preview_url}
                                  alt={snippet.snippet_id}
                                  className="h-full w-full object-cover"
                                />
                              ) : (
                                <div className="flex h-full w-full items-center justify-center text-[10px] text-neutral-600">
                                  N/A
                                </div>
                              )}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>

            <div className="space-y-2">
              <p className="text-2xs uppercase tracking-wide text-neutral-500">
                Unlinked Face Snippets
              </p>
              {unlinkedFaceSnippets.length === 0 ? (
                <p className="rounded-lg border border-neutral-800 bg-neutral-850 px-3 py-2 text-2xs text-neutral-500">
                  No unlinked face snippets.
                </p>
              ) : (
                <div className="grid grid-cols-4 gap-1">
                  {unlinkedFaceSnippets.map((snippet) => (
                    <button
                      type="button"
                      key={snippet.snippet_id}
                      onClick={() =>
                        openSnippetPreview(
                          snippet.preview_url,
                          'Unlinked Face Snippet',
                          snippet.snippet_id,
                        )
                      }
                      className="aspect-square overflow-hidden rounded border border-neutral-800 bg-neutral-900 transition-colors hover:border-neutral-600"
                      title={snippet.snippet_id}
                    >
                      {snippet.preview_url ? (
                        <img
                          src={snippet.preview_url}
                          alt={snippet.snippet_id}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-[10px] text-neutral-600">
                          N/A
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Snippet preview modal */}
      <Modal
        open={Boolean(snippetPreviewModal)}
        title={snippetPreviewModal?.title ?? 'Snippet Preview'}
        onClose={() => setSnippetPreviewModal(null)}
      >
        <div className="space-y-3">
          {snippetPreviewModal?.subtitle ? (
            <p className="truncate text-xs text-neutral-500">{snippetPreviewModal.subtitle}</p>
          ) : null}
          {snippetPreviewModal?.imageUrl ? (
            <img
              src={snippetPreviewModal.imageUrl}
              alt={snippetPreviewModal.title}
              className="max-h-[75vh] w-full rounded border border-neutral-700 bg-neutral-950 object-contain"
            />
          ) : (
            <div className="rounded border border-neutral-800 bg-neutral-900 px-3 py-8 text-center text-xs text-neutral-500">
              Preview unavailable.
            </div>
          )}
        </div>
      </Modal>
    </>
  )
}

export default PeoplePanel
