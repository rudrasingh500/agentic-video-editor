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

  const ensureSession = useCallback(async (activeConfig: AppConfig): Promise<AppConfig> => {
    if (activeConfig.sessionToken) {
      try {
        const validation = await api.validateSession(activeConfig)
        if (validation.valid) {
          const webhookToken =
            validation.webhook_token ?? activeConfig.webhookToken ?? activeConfig.sessionToken

          if (webhookToken !== activeConfig.webhookToken) {
            setConfig((prev) => {
              if (prev.webhookToken === webhookToken) {
                return prev
              }
              return { ...prev, webhookToken }
            })
            return { ...activeConfig, webhookToken }
          }

          return activeConfig
        }
      } catch {
        // Fallback to creating a new session.
      }
    }

    try {
      const created = await api.createSession(activeConfig)
      const nextConfig = {
        ...activeConfig,
        sessionToken: created.session_token,
        webhookToken: created.webhook_token,
      }

      setConfig((prev) => {
        if (
          prev.sessionToken === nextConfig.sessionToken &&
          prev.webhookToken === nextConfig.webhookToken
        ) {
          return prev
        }
        return {
          ...prev,
          sessionToken: nextConfig.sessionToken,
          webhookToken: nextConfig.webhookToken,
        }
      })

      return nextConfig
    } catch (error) {
      if (activeConfig.devToken) {
        return activeConfig
      }
      throw error
    }
  }, [])

  const refreshProjects = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const activeConfig = await ensureSession(config)
      const response = await api.listProjects(activeConfig)
      setProjects(response.projects ?? [])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [config, ensureSession])

  useEffect(() => {
    saveConfig(config)
  }, [config])

  useEffect(() => {
    refreshProjects().catch(() => {})
  }, [refreshProjects])

  const handleCreateProject = async (name: string) => {
    try {
      const activeConfig = await ensureSession(config)
      const response = await api.createProject(activeConfig, name)
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

  const handleDeleteProject = async (projectId: string) => {
    try {
      const activeConfig = await ensureSession(config)
      await api.deleteProject(activeConfig, projectId)
      if (activeProject?.project_id === projectId) {
        setActiveProject(null)
      }
      refreshProjects().catch(() => {})
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
          onRefresh={refreshProjects}
          onDelete={handleDeleteProject}
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
