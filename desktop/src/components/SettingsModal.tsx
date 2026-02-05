import { useEffect, useState } from 'react'
import { Globe, Key, Shield } from 'lucide-react'
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
  const [renderWebhookSecret, setRenderWebhookSecret] = useState(
    config.renderWebhookSecret,
  )

  useEffect(() => {
    if (!open) {
      return
    }
    setBaseUrl(config.baseUrl)
    setDevToken(config.devToken)
    setRenderWebhookSecret(config.renderWebhookSecret)
  }, [config.baseUrl, config.devToken, config.renderWebhookSecret, open])

  const handleSave = () => {
    onSave({
      baseUrl: baseUrl.trim(),
      devToken: devToken.trim(),
      renderWebhookSecret: renderWebhookSecret.trim(),
    })
    onClose()
  }

  return (
    <Modal open={open} title="Settings" onClose={onClose}>
      <div className="space-y-5">
        {/* Backend URL */}
        <div>
          <label className="flex items-center gap-2 text-xs font-medium text-neutral-400 mb-2">
            <Globe className="h-3.5 w-3.5" />
            Backend URL
          </label>
          <input
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-4 py-2.5 text-sm text-neutral-200 placeholder-neutral-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
            placeholder="http://localhost:8000"
          />
        </div>

        {/* Dev API Token */}
        <div>
          <label className="flex items-center gap-2 text-xs font-medium text-neutral-400 mb-2">
            <Key className="h-3.5 w-3.5" />
            API Token
          </label>
          <input
            value={devToken}
            onChange={(event) => setDevToken(event.target.value)}
            type="password"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-4 py-2.5 font-mono text-sm text-neutral-200 placeholder-neutral-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
            placeholder="your-api-token"
          />
        </div>

        {/* Render Webhook Secret */}
        <div>
          <label className="flex items-center gap-2 text-xs font-medium text-neutral-400 mb-2">
            <Shield className="h-3.5 w-3.5" />
            Render Webhook Secret
          </label>
          <input
            value={renderWebhookSecret}
            onChange={(event) => setRenderWebhookSecret(event.target.value)}
            type="password"
            className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-4 py-2.5 font-mono text-sm text-neutral-200 placeholder-neutral-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
            placeholder="webhook-secret"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-3 border-t border-neutral-800">
          <button
            onClick={onClose}
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded-lg bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 transition-colors"
          >
            Save Changes
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default SettingsModal
