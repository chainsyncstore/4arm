import { useState } from 'react'
import { useSongs, useCreateSong, usePauseSong, useResumeSong, useDeleteSong } from '@/hooks/useSongs'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Plus, Play, Pause, Trash2, Music } from 'lucide-react'
import { toast } from 'sonner'
import type { SongStatus, SongPriority } from '@/types'

const statusFilters: (SongStatus | 'all')[] = ['all', 'active', 'paused', 'completed']

export function Songs() {
  const [statusFilter, setStatusFilter] = useState<SongStatus | 'all'>('all')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [spotifyUrl, setSpotifyUrl] = useState('')
  const [newSong, setNewSong] = useState({
    title: '',
    artist: '',
    album_art_url: '',
    total_target_streams: 10000,
    daily_rate: 100,
    priority: 'medium' as SongPriority,
  })

  const { data: songsData, refetch } = useSongs(0, 50, statusFilter === 'all' ? undefined : statusFilter)
  const createSong = useCreateSong()
  const pauseSong = usePauseSong()
  const resumeSong = useResumeSong()
  const deleteSong = useDeleteSong()

  const songs = songsData?.items || []

  const extractSpotifyInfo = async (url: string) => {
    const match = url.match(/track\/([a-zA-Z0-9]+)/)
    if (!match) {
      toast.error('Invalid Spotify URL')
      return
    }

    try {
      const response = await fetch(`https://open.spotify.com/oembed?url=${encodeURIComponent(url)}`)
      const data = await response.json()
      setNewSong({
        ...newSong,
        title: data.title || '',
        album_art_url: data.thumbnail_url || '',
      })
      toast.success('Song info fetched')
    } catch {
      toast.error('Failed to fetch song info')
    }
  }

  const handleCreate = async () => {
    const match = spotifyUrl.match(/track\/([a-zA-Z0-9]+)/)
    const trackId = match ? match[1] : ''
    
    try {
      await createSong.mutateAsync({
        spotify_uri: `spotify:track:${trackId}`,
        ...newSong,
      })
      toast.success('Song added')
      setIsCreateOpen(false)
      setSpotifyUrl('')
      setNewSong({
        title: '',
        artist: '',
        album_art_url: '',
        total_target_streams: 10000,
        daily_rate: 100,
        priority: 'medium',
      })
      refetch()
    } catch {
      toast.error('Failed to add song')
    }
  }

  const handlePause = async (id: string) => {
    try {
      await pauseSong.mutateAsync(id)
      toast.success('Song paused')
      refetch()
    } catch {
      toast.error('Failed to pause song')
    }
  }

  const handleResume = async (id: string) => {
    try {
      await resumeSong.mutateAsync(id)
      toast.success('Song resumed')
      refetch()
    } catch {
      toast.error('Failed to resume song')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this song?')) return
    try {
      await deleteSong.mutateAsync(id)
      toast.success('Song deleted')
      refetch()
    } catch {
      toast.error('Failed to delete song')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-foreground">Songs</h1>
        <Button onClick={() => setIsCreateOpen(true)} className="bg-spotify hover:bg-spotify-dark">
          <Plus className="h-4 w-4 mr-2" />
          Add Song
        </Button>
      </div>

      <Tabs value={statusFilter} onValueChange={(v) => setStatusFilter(v as SongStatus | 'all')}>
        <TabsList>
          {statusFilters.map((status) => (
            <TabsTrigger key={status} value={status}>
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Song</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {songs.map((song) => (
                <TableRow key={song.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      {song.album_art_url ? (
                        <img src={song.album_art_url} alt={song.title} className="h-10 w-10 rounded object-cover" />
                      ) : (
                        <div className="h-10 w-10 rounded bg-muted flex items-center justify-center">
                          <Music className="h-5 w-5 text-muted-foreground" />
                        </div>
                      )}
                      <div>
                        <p className="font-medium">{song.title}</p>
                        <p className="text-sm text-muted-foreground">{song.artist}</p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{song.total_target_streams.toLocaleString()}</TableCell>
                  <TableCell>
                    <div className="w-32">
                      <div className="flex justify-between text-xs mb-1">
                        <span>{song.completed_streams.toLocaleString()}</span>
                        <span>{Math.round((song.completed_streams / song.total_target_streams) * 100)}%</span>
                      </div>
                      <div className="h-2 bg-secondary rounded-full overflow-hidden">
                        <div
                          className="h-full bg-spotify"
                          style={{ width: `${Math.min((song.completed_streams / song.total_target_streams) * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={song.status} />
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      {song.status === 'active' ? (
                        <Button size="icon" variant="ghost" onClick={() => handlePause(song.id)}>
                          <Pause className="h-4 w-4 text-yellow-500" />
                        </Button>
                      ) : (
                        <Button size="icon" variant="ghost" onClick={() => handleResume(song.id)}>
                          <Play className="h-4 w-4 text-green-500" />
                        </Button>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleDelete(song.id)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Song</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="url">Spotify URL</Label>
              <div className="flex gap-2">
                <Input
                  id="url"
                  value={spotifyUrl}
                  onChange={(e) => setSpotifyUrl(e.target.value)}
                  placeholder="https://open.spotify.com/track/..."
                />
                <Button variant="outline" onClick={() => extractSpotifyInfo(spotifyUrl)}>
                  Fetch
                </Button>
              </div>
            </div>
            {newSong.album_art_url && (
              <div className="flex items-center gap-4">
                <img src={newSong.album_art_url} alt="Preview" className="h-20 w-20 rounded object-cover" />
                <div>
                  <p className="font-medium">{newSong.title}</p>
                  <p className="text-sm text-muted-foreground">{newSong.artist}</p>
                </div>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="target">Target Streams</Label>
              <Input
                id="target"
                type="number"
                value={newSong.total_target_streams}
                onChange={(e) => setNewSong({ ...newSong, total_target_streams: parseInt(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="rate">Daily Rate</Label>
              <Input
                id="rate"
                type="number"
                value={newSong.daily_rate}
                onChange={(e) => setNewSong({ ...newSong, daily_rate: parseInt(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="priority">Priority</Label>
              <Select
                value={newSong.priority}
                onValueChange={(v) => setNewSong({ ...newSong, priority: v as SongPriority })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} className="bg-spotify hover:bg-spotify-dark">
              Add Song
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
