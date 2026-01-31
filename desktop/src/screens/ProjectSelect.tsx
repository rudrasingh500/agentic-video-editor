import { useMemo, useState } from 'react'
import type { Project } from '../lib/types'
import Modal from '../components/Modal'

type ProjectSelectProps = {
  projects: Project[]
  loading: boolean
  error: string | null
  onCreate: (name: string) => void
  onSelect: (project: Project) => void
  onOpenById: (projectId: string) => void
  onRefresh: () => void
  onOpenSettings: () => void
}

const formatDate = (value?: string) => {
  if (!value) {
    return 'Just now'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const ProjectSelect = ({
  projects,
  loading,
  error,
  onCreate,
  onSelect,
  onOpenById,
  onRefresh,
  onOpenSettings,
}: ProjectSelectProps) => {
  const [showCreate, setShowCreate] = useState(false)
  const [showOpen, setShowOpen] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectId, setProjectId] = useState('')

  const recentProjects = useMemo(() => projects.slice(0, 8), [projects])

  return (
    <div className="min-h-screen bg-base-900 bg-radial-slate text-ink-100">
      <div className="flex min-h-screen">
        <aside className="flex w-20 flex-col items-center gap-4 border-r border-white/5 bg-base-800/70 py-8">
          <button className="rounded-2xl bg-white/5 p-2">
            <span className="text-lg">🏠</span>
          </button>
          <button className="rounded-2xl bg-white/5 p-2">
            <span className="text-lg">📁</span>
          </button>
          <button
            className="rounded-2xl bg-white/10 p-2"
            onClick={onOpenSettings}
          >
            <span className="text-lg">⚙️</span>
          </button>
        </aside>

        <main className="flex flex-1 items-center justify-center px-10 py-12">
          <section className="w-full max-w-4xl rounded-2xl border border-white/10 bg-panel-glass p-10 shadow-panel">
            <div className="text-center">
              <h1 className="font-display text-3xl font-semibold text-ink-100">
                Granite Edit
              </h1>
              <p className="mt-2 text-sm text-ink-300">
                Choose a project to continue.
              </p>
            </div>

            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <button
                onClick={() => setShowCreate(true)}
                className="rounded-full bg-accent-500 px-6 py-2 text-sm font-semibold text-white shadow-glow hover:bg-accent-600"
              >
                + New Project
              </button>
              <button
                onClick={() => setShowOpen(true)}
                className="rounded-full border border-white/10 bg-white/5 px-5 py-2 text-sm text-ink-200 hover:border-white/30"
              >
                Open Project...
              </button>
              <button
                onClick={onRefresh}
                className="rounded-full border border-white/10 bg-white/5 px-5 py-2 text-sm text-ink-200 hover:border-white/30"
              >
                Refresh
              </button>
            </div>

            <div className="mt-10">
              <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.3em] text-ink-400">
                <span>Recent Projects</span>
                {loading ? <span>Loading…</span> : null}
              </div>
              {error ? (
                <div className="rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
                  {error}
                </div>
              ) : null}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {recentProjects.map((project, index) => (
                  <button
                    key={project.project_id}
                    onClick={() => onSelect(project)}
                    className="group flex items-center gap-4 rounded-xl border border-white/10 bg-base-800/60 p-4 text-left opacity-0 transition hover:border-accent-500/60 hover:bg-base-700/80 animate-fade-in-up"
                    style={{ animationDelay: `${index * 40}ms` }}
                  >
                    <div className="h-14 w-20 rounded-lg bg-gradient-to-br from-accent-500/80 via-glow-violet/70 to-glow-magenta/70 opacity-90 shadow-soft transition group-hover:opacity-100" />
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-ink-100">
                        {project.project_name}
                      </div>
                      <div className="mt-1 text-xs text-ink-400">
                        {formatDate(project.updated_at)}
                      </div>
                    </div>
                    <span className="text-xs text-ink-400">Open</span>
                  </button>
                ))}
                {recentProjects.length === 0 && !loading ? (
                  <div className="rounded-xl border border-white/10 bg-base-800/40 p-6 text-sm text-ink-300">
                    No projects yet. Create one to get started.
                  </div>
                ) : null}
              </div>
            </div>

            <div className="mt-10 flex items-center justify-center gap-6 text-xs text-ink-400">
              <button className="hover:text-ink-200" onClick={onOpenSettings}>
                Settings
              </button>
              <button className="hover:text-ink-200">Privacy</button>
              <button className="hover:text-ink-200">Help</button>
            </div>
          </section>
        </main>
      </div>

      <Modal open={showCreate} title="Create Project" onClose={() => setShowCreate(false)}>
        <div className="space-y-4">
          <input
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
            className="w-full rounded-xl border border-white/10 bg-base-800 px-3 py-2 text-ink-100"
            placeholder="Podcast Ep 12"
          />
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-full border border-white/10 px-4 py-2 text-xs text-ink-300"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (!projectName.trim()) {
                  return
                }
                onCreate(projectName.trim())
                setProjectName('')
                setShowCreate(false)
              }}
              className="rounded-full bg-accent-500 px-4 py-2 text-xs font-semibold text-white"
            >
              Create
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={showOpen} title="Open Project by ID" onClose={() => setShowOpen(false)}>
        <div className="space-y-4">
          <input
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            className="w-full rounded-xl border border-white/10 bg-base-800 px-3 py-2 text-ink-100"
            placeholder="project-uuid"
          />
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowOpen(false)}
              className="rounded-full border border-white/10 px-4 py-2 text-xs text-ink-300"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (!projectId.trim()) {
                  return
                }
                onOpenById(projectId.trim())
                setProjectId('')
                setShowOpen(false)
              }}
              className="rounded-full bg-accent-500 px-4 py-2 text-xs font-semibold text-white"
            >
              Open
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default ProjectSelect
