import { useRef, type ChangeEvent, type DragEvent } from 'react'
import { Film, Upload, Trash2, Plus, Grid3X3, List } from 'lucide-react'
import Modal from '../Modal'
import { useUiStore } from '../../stores/uiStore'
import type { Asset } from '../../lib/types'

const tabs = [
  { id: 'assets', label: 'All Assets' },
  { id: 'media', label: 'Video' },
  { id: 'audio', label: 'Audio' },
  { id: 'graphics', label: 'Graphics' },
] as const

type MediaPanelProps = {
  assets: Asset[]
  assetsLoading: boolean
  assetsError: string | null
  timelineSaving: boolean
  onUploadFiles: (event: ChangeEvent<HTMLInputElement>) => void
  onAddToTimeline: (asset: Asset) => void
  onDragStart: (event: DragEvent<HTMLElement>, assetId: string) => void
  onDeleteAsset: (asset: Asset) => void
  assetToDelete: Asset | null
  onSetAssetToDelete: (asset: Asset | null) => void
}

const MediaPanel = ({
  assets,
  assetsLoading,
  assetsError,
  timelineSaving,
  onUploadFiles,
  onAddToTimeline,
  onDragStart,
  onDeleteAsset,
  assetToDelete,
  onSetAssetToDelete,
}: MediaPanelProps) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const activeTab = useUiStore((state) => state.activeAssetTab)
  const setActiveTab = useUiStore((state) => state.setActiveAssetTab)
  const assetViewMode = useUiStore((state) => state.assetViewMode)
  const setAssetViewMode = useUiStore((state) => state.setAssetViewMode)

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  return (
    <>
      <div className="w-80 flex flex-col bg-neutral-900 border-r border-neutral-800">
        {/* Assets header */}
        <div className="shrink-0 border-b border-neutral-800 p-3">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-neutral-200">Media</h2>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setAssetViewMode('grid')}
                className={`rounded p-1.5 transition-colors ${
                  assetViewMode === 'grid'
                    ? 'bg-neutral-800 text-neutral-200'
                    : 'text-neutral-500 hover:text-neutral-300'
                }`}
              >
                <Grid3X3 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setAssetViewMode('list')}
                className={`rounded p-1.5 transition-colors ${
                  assetViewMode === 'list'
                    ? 'bg-neutral-800 text-neutral-200'
                    : 'text-neutral-500 hover:text-neutral-300'
                }`}
              >
                <List className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={handleUploadClick}
              className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-xs font-medium text-neutral-300 hover:border-neutral-600 hover:bg-neutral-700 transition-colors"
            >
              <Upload className="h-3.5 w-3.5" />
              Import
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="shrink-0 flex border-b border-neutral-800">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 px-2 py-2 text-xs font-medium transition-colors relative ${
                activeTab === tab.id
                  ? 'text-neutral-200'
                  : 'text-neutral-500 hover:text-neutral-400'
              }`}
            >
              {tab.label}
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent-500 rounded-full" />
              )}
            </button>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-auto p-3 scrollbar-thin">
          {assetsError && (
                <div className="mb-3 rounded-lg border border-error-500/30 bg-error-500/10 px-3 py-2 text-xs text-error-500">
                  {assetsError}
                </div>
              )}

              {assetsLoading && assets.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-neutral-600">
                  <span className="text-xs">Loading assets...</span>
                </div>
              ) : assets.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <div className="rounded-full bg-neutral-800 p-3 mb-3">
                    <Upload className="h-5 w-5 text-neutral-500" />
                  </div>
                  <p className="text-xs text-neutral-400 mb-1">No assets yet</p>
                  <p className="text-2xs text-neutral-600">Import media to get started</p>
                </div>
              ) : assetViewMode === 'grid' ? (
                <div className="grid grid-cols-2 gap-2">
                  {assets.map((asset) => (
                    <div
                      key={asset.asset_id}
                      draggable
                      onDragStart={(event) => onDragStart(event, asset.asset_id)}
                      className="group rounded-lg border border-neutral-800 bg-neutral-850 overflow-hidden hover:border-neutral-700 transition-colors"
                    >
                      <div className="aspect-video bg-neutral-800 flex items-center justify-center relative">
                        <Film className="h-5 w-5 text-neutral-600" />
                        <button
                          type="button"
                          aria-label={`Delete ${asset.asset_name}`}
                          onClick={() => onSetAssetToDelete(asset)}
                          className="absolute top-1 right-1 rounded p-1 bg-neutral-900/80 text-neutral-500 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 hover:text-error-400 transition-all"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                      <div className="p-2">
                        <div className="truncate text-2xs font-medium text-neutral-300">
                          {asset.asset_name}
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-2">
                          <div className="text-2xs text-neutral-600">
                            {asset.indexing_status ?? 'ready'}
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              void onAddToTimeline(asset)
                            }}
                            disabled={timelineSaving}
                            className="inline-flex items-center gap-1 rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300 transition-colors hover:border-neutral-500 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Plus className="h-2.5 w-2.5" />
                            Add
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-1">
                  {assets.map((asset) => (
                    <div
                      key={asset.asset_id}
                      draggable
                      onDragStart={(event) => onDragStart(event, asset.asset_id)}
                      className="group flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-850 p-2 hover:border-neutral-700 transition-colors"
                    >
                      <div className="w-12 h-8 rounded bg-neutral-800 flex items-center justify-center shrink-0">
                        <Film className="h-4 w-4 text-neutral-600" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="truncate text-xs font-medium text-neutral-300">
                          {asset.asset_name}
                        </div>
                        <div className="text-2xs text-neutral-600">
                          {asset.indexing_status ?? 'ready'}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          void onAddToTimeline(asset)
                        }}
                        disabled={timelineSaving}
                        className="rounded border border-neutral-700 px-2 py-1 text-[10px] text-neutral-300 transition-colors hover:border-neutral-500 hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Add
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete ${asset.asset_name}`}
                        onClick={() => onSetAssetToDelete(asset)}
                        className="rounded p-1.5 text-neutral-600 opacity-0 group-hover:opacity-100 hover:bg-neutral-700 hover:text-error-400 transition-all"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
        </div>
      </div>

      {/* Delete asset confirmation modal */}
      <Modal
        open={Boolean(assetToDelete)}
        title="Delete Asset"
        onClose={() => onSetAssetToDelete(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-neutral-400">
            Delete {assetToDelete ? `"${assetToDelete.asset_name}"` : 'this asset'}?
            This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => onSetAssetToDelete(null)}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (assetToDelete) {
                  void onDeleteAsset(assetToDelete)
                }
                onSetAssetToDelete(null)
              }}
              className="rounded-lg bg-error-500 px-4 py-2 text-sm font-medium text-white hover:bg-error-600 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </Modal>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={onUploadFiles}
      />
    </>
  )
}

export default MediaPanel
