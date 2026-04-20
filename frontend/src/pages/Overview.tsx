import { useInstances } from '@/hooks/useInstances'
import { useSongs } from '@/hooks/useSongs'
import { useSystemResources } from '@/hooks/useSystem'
import { useStreamLogsSummary } from '@/hooks/useStreamLogs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Server, Activity, Music, PlayCircle } from 'lucide-react'

export function Overview() {
  const { data: instancesData } = useInstances(0, 100)
  const { data: songsData } = useSongs(0, 50, 'active')
  const { data: resources } = useSystemResources()
  const { data: summary } = useStreamLogsSummary()

  const instances = instancesData?.items || []
  const songs = songsData?.items || []
  const runningInstances = instances.filter(i => i.status === 'running')
  const activeSongs = songs.filter(s => s.status === 'active')

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold text-foreground">Overview</h1>

      {/* Stats Row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Instances</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {runningInstances.length}/{instances.length}
            </div>
            <p className="text-xs text-muted-foreground">
              {runningInstances.length > 0 ? 'Running' : 'Stopped'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Streams</CardTitle>
            <Activity className="h-4 w-4 text-spotify" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-spotify">
              {summary?.streams_today || 0}
            </div>
            <p className="text-xs text-muted-foreground">Streams today</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Songs</CardTitle>
            <Music className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeSongs.length}</div>
            <p className="text-xs text-muted-foreground">Not completed</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
            <PlayCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {summary?.success_rate?.toFixed(1) || 0}%
            </div>
            <p className="text-xs text-muted-foreground">{summary?.total_streams || 0} total</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Instance Cards */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-semibold">Instances</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {instances.slice(0, 4).map((instance) => (
              <Card key={instance.id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">{instance.name}</CardTitle>
                    <StatusBadge status={instance.status} />
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Account</span>
                    <span>{instance.assigned_account_email || (instance.assigned_account_id ? 'Assigned' : 'None')}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Created</span>
                    <span>{new Date(instance.created_at).toLocaleDateString()}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* System Resources */}
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">System Resources</h2>
          <Card>
            <CardContent className="space-y-4 pt-6">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>CPU</span>
                  <span>{resources?.cpu_percent || 0}%</span>
                </div>
                <div className="h-2 bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-spotify transition-all"
                    style={{ width: `${resources?.cpu_percent || 0}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>RAM</span>
                  <span>{resources?.ram_percent || 0}%</span>
                </div>
                <div className="h-2 bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-spotify transition-all"
                    style={{ width: `${resources?.ram_percent || 0}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Disk</span>
                  <span>{resources?.disk_percent || 0}%</span>
                </div>
                <div className="h-2 bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-spotify transition-all"
                    style={{ width: `${resources?.disk_percent || 0}%` }}
                  />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Active Songs */}
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Active Songs</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {activeSongs.slice(0, 6).map((song) => (
            <Card key={song.id}>
              <CardContent className="p-4">
                <div className="flex items-start gap-4">
                  {song.album_art_url ? (
                    <img
                      src={song.album_art_url}
                      alt={song.title}
                      className="h-12 w-12 rounded object-cover"
                    />
                  ) : (
                    <div className="h-12 w-12 rounded bg-muted flex items-center justify-center">
                      <Music className="h-6 w-6 text-muted-foreground" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{song.title}</p>
                    <p className="text-sm text-muted-foreground truncate">{song.artist}</p>
                  </div>
                </div>
                <div className="mt-4 space-y-1">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Progress</span>
                    <span>
                      {song.completed_streams.toLocaleString()} /{' '}
                      {song.total_target_streams.toLocaleString()}
                    </span>
                  </div>
                  <div className="h-2 bg-secondary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-spotify transition-all"
                      style={{
                        width: `${Math.min(
                          (song.completed_streams / song.total_target_streams) * 100,
                          100
                        )}%`,
                      }}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}
