import { useEffect, useState } from 'react'
import type { AppConfig } from '../lib/config'
import Modal from './Modal'

type SettingsModalProps = {
  open: boolean
  config: AppConfig
  onClose: () => void
  onSave: (config: AppConfig) => void
}

const SettingsModal = ({ open, config, onClose, onSave }: SettingsModalProps) => {
  const [baseUrl, setBaseUrl] = useState(config.baseUrl)
  const [devToken, setDevToken] = useState(config.devToken)

  useEffect(() => {
    if (!open) {
      return
    }
    setBaseUrl(config.baseUrl)
    setDevToken(config.devToken)
  }, [config.baseUrl, config.devToken, open])

  const handleSave = () => {
    onSave({ baseUrl: baseUrl.trim(), devToken: devToken.trim() })
    onClose()
  }

  return (
    <Modal open={open} title="Settings" onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-sm text-ink-200">
          Backend URL
          <input
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            className="mt-2 w-full rounded-xl border border-white/10 bg-base-800 px-3 py-2 text-ink-100 shadow-inner"
            placeholder="http://localhost:8000"
          />
        </label>
        <label className="block text-sm text-ink-200">
          Dev API Token
          <input
            value={devToken}
            onChange={(event) => setDevToken(event.target.value)}
            className="mt-2 w-full rounded-xl border border-white/10 bg-base-800 px-3 py-2 text-ink-100 shadow-inner"
            placeholder="your-dev-token"
          />
        </label>
        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onClose}
            className="rounded-full border border-white/15 px-4 py-2 text-sm text-ink-200 hover:border-white/40"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded-full bg-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow hover:bg-accent-600"
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default SettingsModal
