import { useEffect } from 'react'
import { create } from 'zustand'
import { api } from '../lib/api'
import type { AppConfig } from '../lib/config'

const POLL_INTERVAL_MS = 10_000
const PING_TIMEOUT_MS = 5_000

export type ConnectionState = 'online' | 'offline' | 'checking'

type ConnectionStore = {
    state: ConnectionState
    lastCheckedAt: number | null
    setState: (state: ConnectionState) => void
    setChecked: () => void
}

export const useConnectionStore = create<ConnectionStore>((set) => ({
    state: 'checking',
    lastCheckedAt: null,
    setState: (state) => set({ state }),
    setChecked: () => set({ lastCheckedAt: Date.now() }),
}))

/**
 * Hook that polls the backend /health endpoint every 10 seconds
 * and exposes the connection state globally via useConnectionStore.
 *
 * Mount this once in the Editor component.
 */
const useConnectionStatus = (config: AppConfig) => {
    const setState = useConnectionStore((s) => s.setState)
    const setChecked = useConnectionStore((s) => s.setChecked)

    useEffect(() => {
        let active = true

        const check = async () => {
            try {
                const controller = new AbortController()
                const timeout = setTimeout(() => controller.abort(), PING_TIMEOUT_MS)

                await api.health(config)
                clearTimeout(timeout)

                if (active) {
                    setState('online')
                    setChecked()
                }
            } catch {
                if (active) {
                    setState('offline')
                    setChecked()
                }
            }
        }

        void check()
        const interval = window.setInterval(() => {
            void check()
        }, POLL_INTERVAL_MS)

        return () => {
            active = false
            window.clearInterval(interval)
        }
    }, [config, setChecked, setState])

    return useConnectionStore((s) => s.state)
}

export default useConnectionStatus
