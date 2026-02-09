import { useMemo, useState } from 'react'
import {
  Plus,
  RefreshCw,
  Settings,
  Film,
  Trash2,
  ChevronRight,
  Clock,
  Loader2,
} from 'lucide-react'
import type { Project } from '../lib/types'
import Modal from '../components/Modal'

type ProjectSelectProps = {
  projects: Project[]
  loading: boolean
  error: string | null
  onCreate: (name: string) => void
  onSelect: (project: Project) => void
  onRefresh: () => void
  onDelete?: (projectId: string) => void
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
  onRefresh,
  onDelete,
  onOpenSettings,
}: ProjectSelectProps) => {
  const [showCreate, setShowCreate] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null)

  const recentProjects = useMemo(() => projects.slice(0, 8), [projects])

  return (
    <div className="min-h-screen bg-neutral-950 bg-gradient-mesh">
      {/* Header */}
      <header className="flex h-14 items-center justify-between border-b border-neutral-800/50 px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500">
            <Film className="h-4 w-4 text-white" />
          </div>
          <span className="text-sm font-semibold text-neutral-200">Auteur</span>
        </div>
        <button
          onClick={onOpenSettings}
          className="rounded-lg p-2 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors"
        >
          <Settings className="h-4 w-4" />
        </button>
      </header>

      {/* Main content */}
      <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-8">
        <div className="w-full max-w-3xl">
          {/* Hero section */}
          <div className="mb-10 text-center">
            <h1 className="text-3xl font-semibold text-neutral-100 mb-3">
              Welcome back
            </h1>
            <p className="text-neutral-500">
              Select a project to continue editing or start a new one.
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap justify-center gap-3 mb-10">
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-600 transition-colors"
            >
              <Plus className="h-4 w-4" />
              New Project
            </button>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="flex items-center gap-2 rounded-lg border border-neutral-700 bg-neutral-800/50 px-5 py-2.5 text-sm font-medium text-neutral-300 hover:border-neutral-600 hover:bg-neutral-800 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>

          {/* Recent projects */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2 text-neutral-400">
                <Clock className="h-4 w-4" />
                <span className="text-xs font-medium uppercase tracking-wider">
                  Recent Projects
                </span>
              </div>
              {loading && (
                <div className="flex items-center gap-2 text-xs text-neutral-500">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Loading...
                </div>
              )}
            </div>

            {error && (
              <div className="mb-4 rounded-lg border border-error-500/30 bg-error-500/10 px-4 py-3 text-sm text-error-500">
                {error}
              </div>
            )}

            {recentProjects.length === 0 && !loading ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="rounded-full bg-neutral-800 p-4 mb-4">
                  <Film className="h-6 w-6 text-neutral-500" />
                </div>
                <p className="text-sm text-neutral-400 mb-1">No projects yet</p>
                <p className="text-xs text-neutral-600">
                  Create a new project to get started
                </p>
              </div>
            ) : (
              <div className="grid gap-2">
                {recentProjects.map((project) => (
                  <div
                    key={project.project_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelect(project)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onSelect(project)
                      }
                    }}
                    className="group flex cursor-pointer items-center gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-all hover:border-neutral-700 hover:bg-neutral-800/80"
                  >
                    <div className="flex h-12 w-16 items-center justify-center rounded-lg bg-neutral-800 group-hover:bg-neutral-700 transition-colors">
                      <Film className="h-5 w-5 text-neutral-500 group-hover:text-neutral-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-neutral-200 truncate">
                        {project.project_name}
                      </div>
                      <div className="flex items-center gap-2 mt-1 text-xs text-neutral-500">
                        <span>{formatDate(project.updated_at)}</span>
                        {project.project_id && (
                          <>
                            <span className="text-neutral-700">|</span>
                            <span className="font-mono text-2xs">
                              {project.project_id.slice(0, 8)}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {onDelete && (
                        <button
                          type="button"
                          aria-label={`Delete ${project.project_name}`}
                          onClick={(event) => {
                            event.stopPropagation()
                            setProjectToDelete(project)
                          }}
                          className="rounded-lg p-2 text-neutral-600 opacity-0 group-hover:opacity-100 hover:bg-neutral-700 hover:text-error-400 transition-all"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                      <ChevronRight className="h-4 w-4 text-neutral-600 group-hover:text-neutral-400 transition-colors" />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Footer links */}
          <div className="mt-8 flex items-center justify-center gap-6 text-xs text-neutral-500">
            <button
              className="hover:text-neutral-300 transition-colors"
              onClick={onOpenSettings}
            >
              Settings
            </button>
            <span className="text-neutral-700">|</span>
            <button className="hover:text-neutral-300 transition-colors">
              Documentation
            </button>
            <span className="text-neutral-700">|</span>
            <button className="hover:text-neutral-300 transition-colors">
              Help
            </button>
          </div>
        </div>
      </main>

      {/* Create Project Modal */}
      <Modal open={showCreate} title="Create Project" onClose={() => setShowCreate(false)}>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-neutral-400 mb-2">
              Project Name
            </label>
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && projectName.trim()) {
                  onCreate(projectName.trim())
                  setProjectName('')
                  setShowCreate(false)
                }
              }}
              className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-4 py-2.5 text-sm text-neutral-200 placeholder-neutral-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500/50 transition-colors"
              placeholder="My Awesome Video"
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 transition-colors"
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
              disabled={!projectName.trim()}
              className="rounded-lg bg-accent-500 px-4 py-2 text-sm font-medium text-white hover:bg-accent-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Create
            </button>
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        open={Boolean(projectToDelete)}
        title="Delete Project"
        onClose={() => setProjectToDelete(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-neutral-400">
            Are you sure you want to delete{' '}
            <span className="font-medium text-neutral-200">
              "{projectToDelete?.project_name}"
            </span>
            ? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setProjectToDelete(null)}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                if (projectToDelete && onDelete) {
                  onDelete(projectToDelete.project_id)
                }
                setProjectToDelete(null)
              }}
              className="rounded-lg bg-error-500 px-4 py-2 text-sm font-medium text-white hover:bg-error-600 transition-colors"
            >
              Delete
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default ProjectSelect
