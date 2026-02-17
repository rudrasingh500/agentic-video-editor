/**
 * Build a render manifest entirely client-side, so we can render offline
 * without needing any backend API calls.
 *
 * The manifest format mirrors what `render_operator.dispatch_render_job` in the
 * backend produces and what `FFmpegRenderer.__init__` in the render-job expects.
 */

import type { Timeline, Clip, Track, Stack, TrackItem } from './timelineTypes'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RenderPreset = {
    name: string
    quality: string
    video: {
        codec: string
        container?: string
        width: number | null
        height: number | null
        framerate: number | null
        bitrate: string | null
        crf: number
        preset: string
        pixel_format: string
        two_pass?: boolean
        color_space?: string
        color_primaries?: string
        color_trc?: string
    }
    audio: {
        codec: string
        bitrate: string
        sample_rate: number
        channels: number
    }
    use_gpu: boolean
    gpu_backend?: string | null
}

export type LocalRenderManifest = {
    job_id: string
    project_id: string
    timeline_version: number
    timeline_snapshot: Timeline
    asset_map: Record<string, string>
    preset: RenderPreset
    input_bucket: string
    output_bucket: string
    output_path: string
    start_frame: number | null
    end_frame: number | null
    callback_url: string | null
    output_variants: unknown[]
    execution_mode: 'local'
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Recursively collect every asset_id referenced in the timeline. */
const collectAssetIds = (timeline: Timeline): Set<string> => {
    const ids = new Set<string>()

    const visitItem = (item: TrackItem) => {
        if (item.OTIO_SCHEMA === 'Clip.1') {
            const clip = item as Clip
            if (clip.media_reference?.OTIO_SCHEMA === 'ExternalReference.1') {
                ids.add(clip.media_reference.asset_id)
            }
            if (clip.media_reference?.OTIO_SCHEMA === 'GeneratorReference.1') {
                const params = clip.media_reference.parameters ?? {}
                for (const key of ['asset_id', 'image_asset_id', 'logo_asset_id']) {
                    const val = params[key]
                    if (typeof val === 'string' && val.length > 0) {
                        ids.add(val)
                    }
                }
            }
        } else if (item.OTIO_SCHEMA === 'Stack.1') {
            const stack = item as Stack
            for (const child of stack.children) {
                if (child.OTIO_SCHEMA === 'Track.1') {
                    for (const trackItem of (child as Track).children) {
                        visitItem(trackItem)
                    }
                } else {
                    visitItem(child as TrackItem)
                }
            }
        }
        // Gap and Transition have no asset references
    }

    for (const trackOrStack of timeline.tracks.children) {
        if (trackOrStack.OTIO_SCHEMA === 'Track.1') {
            for (const item of (trackOrStack as Track).children) {
                visitItem(item)
            }
        }
    }

    return ids
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Build a render manifest from local state.
 *
 * @param timeline         The current timeline snapshot from timelineStore.
 * @param timelineVersion  The current version (local or remote).
 * @param projectId        The project UUID.
 * @param jobId            A client-generated job ID.
 * @param preset           The encoding preset (from `buildRenderPreset`).
 * @param outputFilename   Desired output filename (e.g. "My_Project.mp4").
 * @param assetPathMap     A map of asset_id -> absolute local file path.
 *                         Typically built from `useAssetStore.assetCache`.
 */
export const buildLocalManifest = (
    timeline: Timeline,
    timelineVersion: number,
    projectId: string,
    jobId: string,
    preset: RenderPreset,
    outputFilename: string,
    assetPathMap: Record<string, string>,
): LocalRenderManifest => {
    // Build the asset_map: only include assets actually referenced in the timeline
    const referencedIds = collectAssetIds(timeline)
    const assetMap: Record<string, string> = {}
    for (const id of referencedIds) {
        const localPath = assetPathMap[id]
        if (localPath) {
            assetMap[id] = localPath
        }
        // If a referenced asset has no local path, it will be missing from
        // the map and the renderer will report a useful error.
    }

    return {
        job_id: jobId,
        project_id: projectId,
        timeline_version: timelineVersion,
        timeline_snapshot: timeline,
        asset_map: assetMap,
        preset,
        input_bucket: 'local',
        output_bucket: 'local',
        output_path: `${projectId}/renders/${outputFilename}`,
        start_frame: null,
        end_frame: null,
        callback_url: null,
        output_variants: [],
        execution_mode: 'local',
    }
}
