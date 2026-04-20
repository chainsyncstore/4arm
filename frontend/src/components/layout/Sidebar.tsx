import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  Users,
  Music,
  Globe,
  FileText,
  ShieldAlert,
  Settings,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { usePendingChallengeCount } from '@/hooks/useChallenges'

const navItems = [
  { icon: LayoutDashboard, label: 'Overview', path: '/' },
  { icon: Server, label: 'Instances', path: '/instances' },
  { icon: Users, label: 'Accounts', path: '/accounts' },
  { icon: Music, label: 'Songs', path: '/songs' },
  { icon: Globe, label: 'Proxies', path: '/proxies' },
  { icon: FileText, label: 'Logs', path: '/logs' },
  { icon: ShieldAlert, label: 'Challenges', path: '/challenges', showBadge: true },
  { icon: Settings, label: 'Settings', path: '/settings' },
]

interface SidebarProps {
  isCollapsed: boolean
  onToggle: () => void
}

export function Sidebar({ isCollapsed, onToggle }: SidebarProps) {
  const { data: pendingCount } = usePendingChallengeCount()
  const pending = pendingCount?.count || 0

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-screen bg-card border-r border-border transition-all duration-300',
        isCollapsed ? 'w-16' : 'w-64'
      )}
    >
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex h-16 items-center justify-between px-4 border-b border-border">
          {!isCollapsed && (
            <span className="text-xl font-bold text-spotify">4ARM</span>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            className={cn('ml-auto', isCollapsed && 'mx-auto')}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </Button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-spotify/20 text-spotify'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  isCollapsed && 'justify-center'
                )
              }
            >
              <item.icon className="h-5 w-5 flex-shrink-0" />
              {!isCollapsed && (
                <span className="flex-1">{item.label}</span>
              )}
              {!isCollapsed && item.showBadge && pending > 0 && (
                <Badge variant="secondary" className="bg-red-500/20 text-red-500 text-xs px-1.5 py-0">
                  {pending}
                </Badge>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-border p-4">
          {!isCollapsed && (
            <p className="text-xs text-muted-foreground">
              v1.0.0 · Phase 5
            </p>
          )}
        </div>
      </div>
    </aside>
  )
}
