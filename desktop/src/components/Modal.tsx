import type { ReactNode } from 'react'
import { X } from 'lucide-react'

type ModalProps = {
  open: boolean
  title?: string
  children: ReactNode
  onClose: () => void
  maxWidth?: string
}

const Modal = ({ open, title, children, onClose, maxWidth }: ModalProps) => {
  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal panel */}
      <div className={`relative z-10 w-full ${maxWidth ?? 'max-w-md'} rounded-xl border border-neutral-800 bg-neutral-900 shadow-panel animate-fade-in-up`}>
        {/* Header */}
        {title && (
          <div className="flex items-center justify-between border-b border-neutral-800 px-6 py-4">
            <h2 className="text-lg font-semibold text-neutral-100">{title}</h2>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Content */}
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  )
}

export default Modal
