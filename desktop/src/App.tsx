import { useCallback, useEffect, useState } from 'react'
import ProjectSelect from './screens/ProjectSelect'
import Editor from './screens/Editor'
import SettingsModal from './components/SettingsModal'
import { api } from './lib/api'
import { loadConfig, saveConfig, type AppConfig } from './lib/config'
import type { Project } from './lib/types'

const App = () => {
  const [config, setConfig] = useState<AppConfig>(() => loadConfig())
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeProject, setActiveProject] = useState<Project | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const refreshProjects = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.listProjects(config)
      setProjects(response.projects ?? [])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [config])

  useEffect(() => {
    saveConfig(config)
    refreshProjects().catch(() => {})
  }, [config, refreshProjects])

  const handleCreateProject = async (name: string) => {
    try {
      const response = await api.createProject(config, name)
      const project: Project = {
        project_id: response.project_id,
        project_name: response.project_name,
      }
      setActiveProject(project)
      refreshProjects().catch(() => {})
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleOpenProject = async (projectId: string) => {
    try {
      const response = await api.getProject(config, projectId)
      setActiveProject({
        project_id: response.project_id,
        project_name: response.project_name,
      })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <>
      {activeProject ? (
        <Editor
          project={activeProject}
          config={config}
          onBack={() => setActiveProject(null)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      ) : (
        <ProjectSelect
          projects={projects}
          loading={loading}
          error={error}
          onCreate={handleCreateProject}
          onSelect={setActiveProject}
          onOpenById={handleOpenProject}
          onRefresh={refreshProjects}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      )}

      <SettingsModal
        open={settingsOpen}
        config={config}
        onClose={() => setSettingsOpen(false)}
        onSave={setConfig}
      />
    </>
  )
}

export default App
