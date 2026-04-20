import { useEffect, useState, type ChangeEvent } from 'react'
import { useAccounts, useUpdateAccount, useImportAccounts, useDeleteAccount, useRegisterAccounts, useExtractSession, useInjectSession, useLinkProxy, useSetCooldown, useForceActive } from '@/hooks/useAccounts'
import { useInstances } from '@/hooks/useInstances'
import { useProxies } from '@/hooks/useProxies'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Upload, Trash2, Pencil, Eye, EyeOff, Download, UserPlus, RefreshCw, DownloadCloud, UploadCloud, Link2, Clock, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { accountsApi } from '@/api'
import type { Account, AccountStatus, AccountType, Instance } from '@/types'

const statusFilters: (AccountStatus | 'all')[] = ['all', 'new', 'warming', 'active', 'cooldown', 'banned']
const typeFilters: (AccountType | 'all')[] = ['all', 'free', 'premium']

export function Accounts() {
  const [statusFilter, setStatusFilter] = useState<AccountStatus | 'all'>('all')
  const [typeFilter, setTypeFilter] = useState<AccountType | 'all'>('all')
  const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set())
  const [editAccount, setEditAccount] = useState<Account | null>(null)
  const [editPassword, setEditPassword] = useState('')
  const [editType, setEditType] = useState<AccountType>('free')
  const [registerDialogOpen, setRegisterDialogOpen] = useState(false)
  const [registerCount, setRegisterCount] = useState(1)
  const [selectedRegistrationInstanceIds, setSelectedRegistrationInstanceIds] = useState<string[]>([])
  const [registrationSelectionInitialized, setRegistrationSelectionInitialized] = useState(false)

  // Dialog states for operational actions
  const [linkProxyDialogOpen, setLinkProxyDialogOpen] = useState(false)
  const [selectedAccountForAction, setSelectedAccountForAction] = useState<Account | null>(null)
  const [selectedProxyId, setSelectedProxyId] = useState('')
  const [cooldownDialogOpen, setCooldownDialogOpen] = useState(false)
  const [cooldownHours, setCooldownHours] = useState(24)
  const [forceActiveDialogOpen, setForceActiveDialogOpen] = useState(false)

  const { data: accountsData, refetch } = useAccounts(
    0,
    50,
    statusFilter === 'all' ? undefined : statusFilter,
    typeFilter === 'all' ? undefined : typeFilter
  )
  const { data: runningInstancesData } = useInstances(0, 100, 'running')
  const { data: proxiesData } = useProxies(0, 100, undefined, true) // Get unlinked proxies
  const updateAccount = useUpdateAccount()
  const importAccounts = useImportAccounts()
  const deleteAccount = useDeleteAccount()
  const registerAccounts = useRegisterAccounts()
  const extractSession = useExtractSession()
  const injectSession = useInjectSession()
  const linkProxy = useLinkProxy()
  const setCooldown = useSetCooldown()
  const forceActive = useForceActive()

  const proxies = proxiesData || []
  const runningInstances = runningInstancesData?.items || []

  const accounts: Account[] = accountsData?.items ?? []

  useEffect(() => {
    if (!registerDialogOpen || registrationSelectionInitialized || runningInstances.length === 0) {
      return
    }

    setSelectedRegistrationInstanceIds(runningInstances.map((instance) => instance.id))
    setRegistrationSelectionInitialized(true)
  }, [registerDialogOpen, registrationSelectionInitialized, runningInstances])

  const togglePasswordVisibility = (id: string) => {
    setVisiblePasswords(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleImport = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await importAccounts.mutateAsync(file)
      toast.success('Accounts imported')
      refetch()
    } catch {
      toast.error('Failed to import accounts')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this account?')) return
    try {
      await deleteAccount.mutateAsync(id)
      toast.success('Account deleted')
      refetch()
    } catch {
      toast.error('Failed to delete account')
    }
  }

  const handleReplaceProxy = async (account: Account) => {
    if (!account.proxy_id) {
      toast.error('No proxy linked to this account')
      return
    }
    if (!confirm('Replace proxy for this account? The current proxy will be burned and a fresh one provisioned.')) return
    try {
      const result = await accountsApi.replaceProxy(account.id)
      toast.success(`Proxy replaced: ${result.host}:${result.port}`)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to replace proxy')
    }
  }

  const handleEdit = (account: Account) => {
    setEditAccount(account)
    setEditPassword(account.password || '')
    setEditType(account.type)
  }

  const handleExtractSession = async (account: Account) => {
    try {
      const result = await extractSession.mutateAsync({ accountId: account.id }) as { session_blob_path: string }
      const pathName = result.session_blob_path.split('/').pop()
      toast.success(`Session extracted: ${pathName}`)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to extract session')
    }
  }

  const handleInjectSession = async (account: Account) => {
    if (!account.session_blob_path) {
      toast.error('No stored session to inject')
      return
    }
    try {
      await injectSession.mutateAsync({ accountId: account.id })
      toast.success('Session injected successfully')
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to inject session')
    }
  }

  const handleSaveEdit = async () => {
    if (!editAccount) return
    try {
      await updateAccount.mutateAsync({
        id: editAccount.id,
        data: { password: editPassword, type: editType }
      })
      toast.success('Account updated')
      setEditAccount(null)
      refetch()
    } catch {
      toast.error('Failed to update account')
    }
  }

  const handleLinkProxyClick = (account: Account) => {
    setSelectedAccountForAction(account)
    setSelectedProxyId('')
    setLinkProxyDialogOpen(true)
  }

  const handleLinkProxy = async () => {
    if (!selectedAccountForAction || !selectedProxyId) return
    try {
      await linkProxy.mutateAsync({ accountId: selectedAccountForAction.id, proxyId: selectedProxyId })
      toast.success('Proxy linked successfully')
      setLinkProxyDialogOpen(false)
      setSelectedAccountForAction(null)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to link proxy')
    }
  }

  const handleSetCooldownClick = (account: Account) => {
    setSelectedAccountForAction(account)
    setCooldownHours(24)
    setCooldownDialogOpen(true)
  }

  const handleSetCooldown = async () => {
    if (!selectedAccountForAction) return
    try {
      await setCooldown.mutateAsync({ accountId: selectedAccountForAction.id, hours: cooldownHours })
      toast.success(`Cooldown set for ${cooldownHours} hours`)
      setCooldownDialogOpen(false)
      setSelectedAccountForAction(null)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to set cooldown')
    }
  }

  const handleForceActiveClick = (account: Account) => {
    setSelectedAccountForAction(account)
    setForceActiveDialogOpen(true)
  }

  const handleForceActive = async () => {
    if (!selectedAccountForAction) return
    try {
      await forceActive.mutateAsync(selectedAccountForAction.id)
      toast.success('Account forced to active status')
      setForceActiveDialogOpen(false)
      setSelectedAccountForAction(null)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to force active')
    }
  }

  const handleOpenRegisterDialog = () => {
    setRegistrationSelectionInitialized(false)
    setSelectedRegistrationInstanceIds([])
    setRegisterDialogOpen(true)
  }

  const handleRegistrationInstanceSelection = (event: ChangeEvent<HTMLSelectElement>) => {
    const values = Array.from(event.target.selectedOptions, (option) => option.value)
    setSelectedRegistrationInstanceIds(values)
  }

  const handleRegisterAccounts = async () => {
    setRegisterDialogOpen(false)
    toast.info(`Registering ${registerCount} accounts...`)
    try {
      const result = await registerAccounts.mutateAsync({
        count: registerCount,
        instance_ids: selectedRegistrationInstanceIds.length > 0 ? selectedRegistrationInstanceIds : undefined,
      })
      toast.success(`${result.registered} accounts registered, ${result.failed} failed`)
      if (result.capped_at) {
        toast.info(`Daily cap reached. Only created ${result.capped_at} accounts.`)
      }
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to register accounts')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-foreground">Accounts</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => accountsApi.downloadTemplate()}>
            <Download className="h-4 w-4 mr-2" />
            Download Template
          </Button>
          <Label className="cursor-pointer">
            <Input type="file" accept=".csv" className="hidden" onChange={handleImport} />
            <Button variant="outline" asChild>
              <span>
                <Upload className="h-4 w-4 mr-2" />
                Import CSV
              </span>
            </Button>
          </Label>
          <Button onClick={handleOpenRegisterDialog}>
            <UserPlus className="h-4 w-4 mr-2" />
            Register New
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <Tabs value={statusFilter} onValueChange={(v) => setStatusFilter(v as AccountStatus | 'all')}>
          <TabsList>
            {statusFilters.map((status) => (
              <TabsTrigger key={status} value={status}>
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <Tabs value={typeFilter} onValueChange={(v) => setTypeFilter(v as AccountType | 'all')}>
          <TabsList>
            {typeFilters.map((t) => (
              <TabsTrigger key={t} value={t}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Password</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Proxy</TableHead>
                <TableHead>Session</TableHead>
                <TableHead>Streams</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((account) => (
                <TableRow key={account.id}>
                  <TableCell className="font-medium">{account.email}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm">
                        {visiblePasswords.has(account.id)
                          ? (account.password || '—')
                          : '••••••••'}
                      </span>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => togglePasswordVisibility(account.id)}
                      >
                        {visiblePasswords.has(account.id) ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={account.type === 'premium' ? 'default' : 'secondary'}>
                      {account.type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={account.status} />
                  </TableCell>
                  <TableCell>
                    {account.proxy_host && account.proxy_port
                      ? `${account.proxy_host}:${account.proxy_port}`
                      : 'None'}
                  </TableCell>
                  <TableCell>
                    <Badge variant={account.session_blob_path ? 'default' : 'secondary'}>
                      {account.session_blob_path ? 'Stored' : 'None'}
                    </Badge>
                  </TableCell>
                  <TableCell>{account.streams_today} / {account.total_streams}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {!account.proxy_id && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleLinkProxyClick(account)}
                          title="Link Proxy"
                          disabled={linkProxy.isPending}
                        >
                          <Link2 className="h-4 w-4 text-blue-500" />
                        </Button>
                      )}
                      {account.proxy_id && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleReplaceProxy(account)}
                          title="Replace Proxy"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </Button>
                      )}
                      {account.status === 'active' && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleSetCooldownClick(account)}
                          title="Set Cooldown"
                          disabled={setCooldown.isPending}
                        >
                          <Clock className="h-4 w-4 text-yellow-500" />
                        </Button>
                      )}
                      {(account.status === 'new' || account.status === 'warming' || account.status === 'cooldown') && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleForceActiveClick(account)}
                          title="Force Active"
                          disabled={forceActive.isPending}
                        >
                          <Zap className="h-4 w-4 text-green-500" />
                        </Button>
                      )}
                      {account.assigned_instance_id && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleExtractSession(account)}
                          title="Extract Session"
                          disabled={extractSession.isPending}
                        >
                          <DownloadCloud className="h-4 w-4" />
                        </Button>
                      )}
                      {account.session_blob_path && account.assigned_instance_id && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => handleInjectSession(account)}
                          title="Inject Session"
                          disabled={injectSession.isPending}
                        >
                          <UploadCloud className="h-4 w-4" />
                        </Button>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleEdit(account)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleDelete(account.id)}
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

      <Dialog open={!!editAccount} onOpenChange={(open) => !open && setEditAccount(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Account</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Email</Label>
              <div className="text-sm text-muted-foreground">{editAccount?.email}</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="text"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="type">Type</Label>
              <Select value={editType} onValueChange={(v) => setEditType(v as AccountType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="free">Free</SelectItem>
                  <SelectItem value="premium">Premium</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditAccount(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveEdit} className="bg-spotify hover:bg-spotify-dark">
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={registerDialogOpen} onOpenChange={setRegisterDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Register New Accounts</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Auto-create Spotify accounts using temporary emails. All accounts are created as Free type.
            </p>
            <div className="space-y-2">
              <Label htmlFor="count">Number of accounts (1-10)</Label>
              <Input
                id="count"
                type="number"
                min={1}
                max={10}
                value={registerCount}
                onChange={(e) => setRegisterCount(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="registration-instances">Running Instances for Registration</Label>
              <select
                id="registration-instances"
                multiple
                className="flex min-h-28 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                value={selectedRegistrationInstanceIds}
                onChange={handleRegistrationInstanceSelection}
              >
                {runningInstances.map((instance: Instance) => (
                  <option key={instance.id} value={instance.id}>
                    {instance.name} ({instance.port ?? 'no adb port'})
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                Real-mode registration uses the selected running instances. In mock mode, this selection is ignored.
              </p>
              {runningInstances.length === 0 && (
                <p className="text-sm text-orange-500">
                  No running instances detected. Real-mode registration requires at least one running instance.
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegisterDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleRegisterAccounts}
              className="bg-spotify hover:bg-spotify-dark"
              disabled={registerAccounts.isPending}
            >
              {registerAccounts.isPending ? 'Registering...' : 'Register'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Link Proxy Dialog */}
      <Dialog open={linkProxyDialogOpen} onOpenChange={setLinkProxyDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Link Proxy to Account</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Account</Label>
              <div className="text-sm text-muted-foreground">{selectedAccountForAction?.email}</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="proxy">Select Unlinked Proxy</Label>
              <select
                id="proxy"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={selectedProxyId}
                onChange={(e) => setSelectedProxyId(e.target.value)}
              >
                <option value="">Select a proxy...</option>
                {proxies.map((proxy) => (
                  <option key={proxy.id} value={proxy.id}>
                    {proxy.host}:{proxy.port} ({proxy.protocol})
                  </option>
                ))}
              </select>
              {proxies.length === 0 && (
                <p className="text-sm text-muted-foreground text-orange-500">
                  No unlinked proxies available. Add proxies first.
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkProxyDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleLinkProxy}
              disabled={!selectedProxyId || linkProxy.isPending}
              className="bg-spotify hover:bg-spotify-dark"
            >
              {linkProxy.isPending ? 'Linking...' : 'Link Proxy'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Set Cooldown Dialog */}
      <Dialog open={cooldownDialogOpen} onOpenChange={setCooldownDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set Account Cooldown</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Account</Label>
              <div className="text-sm text-muted-foreground">{selectedAccountForAction?.email}</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="hours">Cooldown Duration (hours)</Label>
              <Input
                id="hours"
                type="number"
                min={1}
                max={168}
                value={cooldownHours}
                onChange={(e) => setCooldownHours(Math.max(1, Math.min(168, parseInt(e.target.value) || 1)))}
              />
              <p className="text-xs text-muted-foreground">
                Account will be unavailable for streaming during cooldown.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCooldownDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSetCooldown}
              disabled={setCooldown.isPending}
              className="bg-spotify hover:bg-spotify-dark"
            >
              {setCooldown.isPending ? 'Setting...' : 'Set Cooldown'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Force Active Dialog */}
      <Dialog open={forceActiveDialogOpen} onOpenChange={setForceActiveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Force Account to Active</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Account</Label>
              <div className="text-sm text-muted-foreground">{selectedAccountForAction?.email}</div>
            </div>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                This will force the account status to <strong>active</strong>, allowing it to participate in streaming immediately.
              </p>
              <p className="text-xs text-orange-500">
                Use with caution - this bypasses normal warmup/cooldown logic.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setForceActiveDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleForceActive}
              disabled={forceActive.isPending}
              className="bg-spotify hover:bg-spotify-dark"
            >
              {forceActive.isPending ? 'Activating...' : 'Force Active'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
