import { useState } from 'react'
import { useInstances, useCreateInstance, useStartInstance, useStopInstance, useDestroyInstance, useAssignAccount, useUnassignAccount } from '@/hooks/useInstances'
import { useAccounts } from '@/hooks/useAccounts'
import { useSystemCapacity } from '@/hooks/useSystem'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Plus, Play, Square, Trash2, UserPlus, UserMinus } from 'lucide-react'
import { toast } from 'sonner'
import type { Instance } from '@/types'

export function Instances() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isAssignOpen, setIsAssignOpen] = useState(false)
  const [selectedInstance, setSelectedInstance] = useState<Instance | null>(null)
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [newInstance, setNewInstance] = useState({ name: '', ram_limit_mb: 2048, cpu_cores: 2 })
  const { data: instancesData, refetch } = useInstances(0, 50)
  const { data: capacity } = useSystemCapacity()
  const { data: accountsData } = useAccounts(0, 100, 'new')
  const createInstance = useCreateInstance()
  const startInstance = useStartInstance()
  const stopInstance = useStopInstance()
  const destroyInstance = useDestroyInstance()
  const assignAccount = useAssignAccount()
  const unassignAccount = useUnassignAccount()

  const accounts = accountsData?.items || []

  const instances = instancesData?.items || []
  const atCapacity = capacity ? capacity.possible_more_instances <= 0 : false

  const handleCreate = async () => {
    try {
      await createInstance.mutateAsync(newInstance)
      toast.success('Instance created successfully')
      setIsCreateOpen(false)
      setNewInstance({ name: '', ram_limit_mb: 2048, cpu_cores: 2 })
      refetch()
    } catch {
      toast.error('Failed to create instance')
    }
  }

  const handleStart = async (id: string) => {
    try {
      await startInstance.mutateAsync(id)
      toast.success('Instance started')
      refetch()
    } catch {
      toast.error('Failed to start instance')
    }
  }

  const handleStop = async (id: string) => {
    try {
      await stopInstance.mutateAsync(id)
      toast.success('Instance stopped')
      refetch()
    } catch {
      toast.error('Failed to stop instance')
    }
  }

  const handleDestroy = async (id: string) => {
    if (!confirm('Are you sure you want to destroy this instance?')) return
    try {
      await destroyInstance.mutateAsync(id)
      toast.success('Instance destroyed')
      refetch()
    } catch {
      toast.error('Failed to destroy instance')
    }
  }

  const handleAssignClick = (instance: Instance) => {
    setSelectedInstance(instance)
    setSelectedAccountId('')
    setIsAssignOpen(true)
  }

  const handleAssign = async () => {
    if (!selectedInstance || !selectedAccountId) return
    try {
      await assignAccount.mutateAsync({ instanceId: selectedInstance.id, accountId: selectedAccountId })
      toast.success('Account assigned successfully')
      setIsAssignOpen(false)
      setSelectedInstance(null)
      refetch()
    } catch {
      toast.error('Failed to assign account')
    }
  }

  const handleUnassign = async (instanceId: string) => {
    if (!confirm('Remove account assignment from this instance?')) return
    try {
      await unassignAccount.mutateAsync(instanceId)
      toast.success('Account unassigned successfully')
      refetch()
    } catch {
      toast.error('Failed to unassign account')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Instances</h1>
          {capacity && (
            <p className="text-muted-foreground mt-1">
              {capacity.running_instances}/{capacity.max_safe_instances} running ·{' '}
              {(capacity.free_ram_mb / 1024).toFixed(1)} GB free · ~
              {capacity.possible_more_instances} more possible
            </p>
          )}
        </div>
        <Button
          onClick={() => setIsCreateOpen(true)}
          disabled={atCapacity}
          className="bg-spotify hover:bg-spotify-dark"
        >
          <Plus className="h-4 w-4 mr-2" />
          Create Instance
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Proxy</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {instances.map((instance) => (
                <TableRow key={instance.id}>
                  <TableCell className="font-medium">{instance.name}</TableCell>
                  <TableCell>
                    <StatusBadge status={instance.status} />
                  </TableCell>
                  <TableCell>{instance.assigned_account_email || (instance.assigned_account_id ? 'Assigned' : 'None')}</TableCell>
                  <TableCell>{instance.assigned_proxy_host || '-'}</TableCell>
                  <TableCell>{new Date(instance.created_at).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      {!instance.assigned_account_id && instance.status === 'running' && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleAssignClick(instance)}
                          title="Assign Account"
                        >
                          <UserPlus className="h-4 w-4 text-blue-500" />
                        </Button>
                      )}
                      {instance.assigned_account_id && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleUnassign(instance.id)}
                          title="Unassign Account"
                          disabled={unassignAccount.isPending}
                        >
                          <UserMinus className="h-4 w-4 text-orange-500" />
                        </Button>
                      )}
                      {instance.status === 'stopped' && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleStart(instance.id)}
                          title="Start Instance"
                        >
                          <Play className="h-4 w-4 text-green-500" />
                        </Button>
                      )}
                      {instance.status === 'running' && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleStop(instance.id)}
                          title="Stop Instance"
                        >
                          <Square className="h-4 w-4 text-yellow-500" />
                        </Button>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleDestroy(instance.id)}
                        className="text-destructive hover:text-destructive"
                        title="Destroy Instance"
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
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Instance</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={newInstance.name}
                onChange={(e) => setNewInstance({ ...newInstance, name: e.target.value })}
                placeholder="Instance name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ram">RAM (MB)</Label>
              <Input
                id="ram"
                type="number"
                value={newInstance.ram_limit_mb}
                onChange={(e) => setNewInstance({ ...newInstance, ram_limit_mb: parseInt(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cpu">CPU Cores</Label>
              <Input
                id="cpu"
                type="number"
                step="0.5"
                value={newInstance.cpu_cores}
                onChange={(e) => setNewInstance({ ...newInstance, cpu_cores: parseFloat(e.target.value) })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} className="bg-spotify hover:bg-spotify-dark">
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isAssignOpen} onOpenChange={setIsAssignOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign Account to Instance</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Instance</Label>
              <div className="text-sm text-muted-foreground">{selectedInstance?.name}</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="account">Select Account (New status)</Label>
              <select
                id="account"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={selectedAccountId}
                onChange={(e) => setSelectedAccountId(e.target.value)}
              >
                <option value="">Select an account...</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.email} ({account.type})
                  </option>
                ))}
              </select>
              {accounts.length === 0 && (
                <p className="text-sm text-muted-foreground text-orange-500">
                  No new accounts available. Create or import accounts first.
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAssignOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleAssign}
              disabled={!selectedAccountId || assignAccount.isPending}
              className="bg-spotify hover:bg-spotify-dark"
            >
              {assignAccount.isPending ? 'Assigning...' : 'Assign'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
