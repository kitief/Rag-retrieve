import { useState } from 'react'
import { Sidebar } from './Sidebar'

interface AppShellProps {
  children: React.ReactNode
}

const SIDEBAR_COLLAPSED_KEY = 'ragvault-sidebar-collapsed'

export function AppShell({ children }: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
  )

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Animated gradient background */}
      <div className="fixed inset-0 -z-10 pointer-events-none">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-blue-600/10 rounded-full blur-3xl" />
      </div>

      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() =>
          setSidebarCollapsed((v) => {
            const next = !v
            localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0')
            return next
          })
        }
      />

      {/* Main content */}
      <main className="flex-1 overflow-hidden relative z-10">{children}</main>
    </div>
  )
}
