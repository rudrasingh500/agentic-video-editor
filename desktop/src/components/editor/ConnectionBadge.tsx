import { useConnectionStore, type ConnectionState } from '../../hooks/useConnectionStatus'

const label: Record<ConnectionState, string> = {
    online: 'Online',
    offline: 'Offline',
    checking: 'Checking…',
}

const dot: Record<ConnectionState, string> = {
    online: 'bg-emerald-400',
    offline: 'bg-red-400',
    checking: 'bg-yellow-400 animate-pulse',
}

const ConnectionBadge = () => {
    const state = useConnectionStore((s) => s.state)

    return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-neutral-800 px-2.5 py-0.5 text-xs text-neutral-300">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot[state]}`} />
            {label[state]}
        </span>
    )
}

export default ConnectionBadge
