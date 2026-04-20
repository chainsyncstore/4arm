import { useState } from 'react'
import { useChallenges, useResolveChallenge, usePendingChallengeCount } from '@/hooks/useChallenges'
import type { Challenge, ChallengeStatus, ChallengeType } from '@/types'
import { challengesApi } from '@/api'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ShieldAlert, Clock, CheckCircle, XCircle, SkipForward, ImageOff } from 'lucide-react'
import { toast } from 'sonner'

const statusFilters: Array<ChallengeStatus | 'all'> = ['all', 'pending', 'resolved', 'expired', 'failed']

function getChallengeTypeColor(type: ChallengeType): string {
  switch (type) {
    case 'captcha':
      return 'bg-red-500/20 text-red-500 border-red-500/50'
    case 'email_verify':
      return 'bg-yellow-500/20 text-yellow-500 border-yellow-500/50'
    case 'phone_verify':
      return 'bg-orange-500/20 text-orange-500 border-orange-500/50'
    case 'terms_accept':
      return 'bg-blue-500/20 text-blue-500 border-blue-500/50'
    default:
      return 'bg-gray-500/20 text-gray-500 border-gray-500/50'
  }
}

function getStatusColor(status: ChallengeStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-yellow-500/20 text-yellow-500 border-yellow-500/50'
    case 'resolved':
      return 'bg-green-500/20 text-green-500 border-green-500/50'
    case 'expired':
      return 'bg-gray-500/20 text-gray-500 border-gray-500/50'
    case 'failed':
      return 'bg-red-500/20 text-red-500 border-red-500/50'
    default:
      return 'bg-gray-500/20 text-gray-500 border-gray-500/50'
  }
}

function formatTimeRemaining(expiresAt: string): string {
  const now = new Date()
  const expires = new Date(expiresAt)
  const diff = expires.getTime() - now.getTime()

  if (diff <= 0) {
    return 'Expired'
  }

  const minutes = Math.floor(diff / 60000)
  const seconds = Math.floor((diff % 60000) / 1000)

  if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  }
  return `${seconds}s`
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  return `${days}d ago`
}

export function Challenges() {
  const [filter, setFilter] = useState<ChallengeStatus | 'all'>('all')
  const [selectedChallenge, setSelectedChallenge] = useState<Challenge | null>(null)
  const [notes, setNotes] = useState('')
  const [imageError, setImageError] = useState(false)

  const { data, isLoading, error } = useChallenges(filter === 'all' ? undefined : filter)
  const resolveMutation = useResolveChallenge()
  const { data: pendingCountData } = usePendingChallengeCount()

  const handleResolve = async (challenge: Challenge, action: string) => {
    try {
      await resolveMutation.mutateAsync({
        id: challenge.id,
        action,
        notes: notes || undefined,
      })

      toast.success(`Challenge ${action === 'resolve' ? 'resolved' : action === 'skip' ? 'skipped' : 'marked as failed'}`)
      setSelectedChallenge(null)
      setNotes('')
      setImageError(false)
    } catch (err) {
      toast.error('Failed to update challenge')
    }
  }

  const pendingCount = pendingCountData?.count ?? (data?.items?.filter((c: Challenge) => c.status === 'pending').length || 0)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-spotify border-t-transparent rounded-full" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        Failed to load challenges
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ShieldAlert className="h-6 w-6 text-spotify" />
          <h1 className="text-2xl font-bold">Challenges</h1>
          {pendingCount > 0 && (
            <Badge variant="secondary" className="bg-yellow-500/20 text-yellow-500">
              {pendingCount} pending
            </Badge>
          )}
        </div>
      </div>

      {/* Filter Tabs */}
      <Tabs value={filter} onValueChange={(v) => setFilter(v as ChallengeStatus | 'all')}>
        <TabsList>
          {statusFilters.map((status) => (
            <TabsTrigger key={status} value={status} className="capitalize">
              {status}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Challenges Table */}
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Account</TableHead>
              <TableHead>Instance</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                  No challenges found
                </TableCell>
              </TableRow>
            ) : (
              data?.items?.map((challenge: Challenge) => (
                <TableRow
                  key={challenge.id}
                  className="cursor-pointer hover:bg-accent/50"
                  onClick={() => {
                    setSelectedChallenge(challenge)
                    setNotes('')
                    setImageError(false)
                  }}
                >
                  <TableCell className="font-medium">
                    {challenge.account_email || challenge.account_id}
                  </TableCell>
                  <TableCell>{challenge.instance_name || '-'}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={getChallengeTypeColor(challenge.type)}>
                      {challenge.type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={getStatusColor(challenge.status)}>
                      {challenge.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {challenge.status === 'pending' ? (
                      <div className="flex items-center gap-2">
                        <Clock className="h-4 w-4 text-yellow-500" />
                        <span className="text-sm tabular-nums">
                          {formatTimeRemaining(challenge.expires_at)}
                        </span>
                      </div>
                    ) : (
                      '-'
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {formatRelativeTime(challenge.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {challenge.status === 'pending' && (
                      <div className="flex justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 w-8 p-0 text-green-500 hover:text-green-600 hover:bg-green-500/20"
                          onClick={() => handleResolve(challenge, 'resolve')}
                          disabled={resolveMutation.isPending}
                        >
                          <CheckCircle className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 w-8 p-0 text-yellow-500 hover:text-yellow-600 hover:bg-yellow-500/20"
                          onClick={() => handleResolve(challenge, 'skip')}
                          disabled={resolveMutation.isPending}
                        >
                          <SkipForward className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 w-8 p-0 text-red-500 hover:text-red-600 hover:bg-red-500/20"
                          onClick={() => handleResolve(challenge, 'fail')}
                          disabled={resolveMutation.isPending}
                        >
                          <XCircle className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      {/* Challenge Detail Dialog */}
      <Dialog open={!!selectedChallenge} onOpenChange={() => setSelectedChallenge(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5" />
              Challenge Details
            </DialogTitle>
            <DialogDescription>
              Review and resolve the detected challenge
            </DialogDescription>
          </DialogHeader>

          {selectedChallenge && (
            <div className="space-y-4">
              {/* Screenshot */}
              <div className="border rounded-lg overflow-hidden bg-muted">
                {selectedChallenge.screenshot_path && !imageError ? (
                  <img
                    src={challengesApi.getScreenshotUrl(selectedChallenge.id)}
                    alt="Challenge Screenshot"
                    className="w-full h-64 object-contain"
                    onError={() => setImageError(true)}
                  />
                ) : (
                  <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
                    <ImageOff className="h-12 w-12 mb-2" />
                    <p>No screenshot available</p>
                  </div>
                )}
              </div>

              {/* Challenge Info */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <Label className="text-muted-foreground">Account</Label>
                  <p className="font-medium">{selectedChallenge.account_email || selectedChallenge.account_id}</p>
                </div>
                <div>
                  <Label className="text-muted-foreground">Instance</Label>
                  <p className="font-medium">{selectedChallenge.instance_name || '-'}</p>
                </div>
                <div>
                  <Label className="text-muted-foreground">Type</Label>
                  <div>
                    <Badge variant="outline" className={getChallengeTypeColor(selectedChallenge.type)}>
                      {selectedChallenge.type}
                    </Badge>
                  </div>
                </div>
                <div>
                  <Label className="text-muted-foreground">Status</Label>
                  <div>
                    <Badge variant="outline" className={getStatusColor(selectedChallenge.status)}>
                      {selectedChallenge.status}
                    </Badge>
                  </div>
                </div>
                <div>
                  <Label className="text-muted-foreground">Created</Label>
                  <p>{new Date(selectedChallenge.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <Label className="text-muted-foreground">Expires</Label>
                  <p>{new Date(selectedChallenge.expires_at).toLocaleString()}</p>
                </div>
              </div>

              {/* Notes Input */}
              <div className="space-y-2">
                <Label htmlFor="notes">Notes (optional)</Label>
                <Input
                  id="notes"
                  placeholder="Add resolution notes..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              {/* Action Buttons */}
              {selectedChallenge.status === 'pending' && (
                <DialogFooter className="gap-2">
                  <Button
                    variant="outline"
                    onClick={() => handleResolve(selectedChallenge, 'fail')}
                    disabled={resolveMutation.isPending}
                    className="text-red-500 hover:text-red-600 hover:bg-red-500/20"
                  >
                    <XCircle className="h-4 w-4 mr-2" />
                    Mark Failed
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleResolve(selectedChallenge, 'skip')}
                    disabled={resolveMutation.isPending}
                    className="text-yellow-500 hover:text-yellow-600 hover:bg-yellow-500/20"
                  >
                    <SkipForward className="h-4 w-4 mr-2" />
                    Skip
                  </Button>
                  <Button
                    onClick={() => handleResolve(selectedChallenge, 'resolve')}
                    disabled={resolveMutation.isPending}
                    className="bg-spotify hover:bg-spotify/90"
                  >
                    <CheckCircle className="h-4 w-4 mr-2" />
                    Mark Resolved
                  </Button>
                </DialogFooter>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
