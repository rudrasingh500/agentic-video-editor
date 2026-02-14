import type { ReactNode } from 'react'

type EditorLayoutProps = {
  header: ReactNode
  previewPane: ReactNode
  mediaPane: ReactNode
  outputPane: ReactNode
  chatPane: ReactNode
}

const EditorLayout = ({ header, previewPane, mediaPane, outputPane, chatPane }: EditorLayoutProps) => {
  return (
    <div className="flex h-screen flex-col bg-neutral-950">
      {header}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="flex min-h-0 flex-1">
            {previewPane}
            {mediaPane}
          </div>
          {outputPane}
        </div>
        {chatPane}
      </div>
    </div>
  )
}

export default EditorLayout
