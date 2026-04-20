import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { InstanceStatus, AccountStatus, SongStatus, ProxyStatus } from '@/types'

type StatusType = InstanceStatus | AccountStatus | SongStatus | ProxyStatus | string

interface StatusBadgeProps {
  status: StatusType
  className?: string
}

const statusColors: Record<string, string> = {
  // Instance statuses
  creating: 'bg-blue-500/20 text-blue-500 hover:bg-blue-500/30',
  running: 'bg-green-500/20 text-green-500 hover:bg-green-500/30',
  stopped: 'bg-gray-500/20 text-gray-500 hover:bg-gray-500/30',
  error: 'bg-red-500/20 text-red-500 hover:bg-red-500/30',
  destroyed: 'bg-gray-500/20 text-gray-500 hover:bg-gray-500/30',
  
  // Account statuses
  new: 'bg-blue-500/20 text-blue-500 hover:bg-blue-500/30',
  warming: 'bg-yellow-500/20 text-yellow-500 hover:bg-yellow-500/30',
  active: 'bg-green-500/20 text-green-500 hover:bg-green-500/30',
  cooldown: 'bg-orange-500/20 text-orange-500 hover:bg-orange-500/30',
  banned: 'bg-red-500/20 text-red-500 hover:bg-red-500/30',
  
  // Song statuses
  paused: 'bg-yellow-500/20 text-yellow-500 hover:bg-yellow-500/30',
  completed: 'bg-green-500/20 text-green-500 hover:bg-green-500/30',
  failed: 'bg-red-500/20 text-red-500 hover:bg-red-500/30',
  
  // Proxy statuses
  healthy: 'bg-green-500/20 text-green-500 hover:bg-green-500/30',
  unhealthy: 'bg-red-500/20 text-red-500 hover:bg-red-500/30',
  unchecked: 'bg-gray-500/20 text-gray-500 hover:bg-gray-500/30',
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const colorClass = statusColors[status] || 'bg-gray-500/20 text-gray-500 hover:bg-gray-500/30'
  
  return (
    <Badge
      variant="outline"
      className={cn(colorClass, 'border-0 font-medium', className)}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  )
}
