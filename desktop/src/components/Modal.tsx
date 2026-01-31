import type { ReactNode } from 'react'

type ModalProps = {
  open: boolean
  title?: string
  children: ReactNode
  onClose: () => void
}

const Modal = ({ open, title, children, onClose }: ModalProps) => {
  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-50 w-full max-w-lg rounded-2xl border border-white/10 bg-panel-glass p-6 shadow-panel">
        {title ? (
          <h2 className="mb-4 font-display text-xl font-semibold text-ink-100">
            {title}
          </h2>
        ) : null}
        {children}
      </div>
    </div>
  )
}

export default Modal
