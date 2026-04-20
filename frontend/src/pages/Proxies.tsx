import { useState, useEffect, type ChangeEvent } from 'react'
import { useProxies, useCreateProxy, useImportProxies, useDeleteProxy, useTestAllProxies, useTestProxy, useAutoAssignProxies, useVerifyProxyIp } from '@/hooks/useProxies'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Plus, Upload, Trash2, Activity, CheckCircle, XCircle, Info, Globe, Link2 } from 'lucide-react'
import { toast } from 'sonner'
import { proxiesApi } from '@/api'
import type { ProxyProtocol, ProxyProviderStatus, ProxyIpVerificationResult } from '@/types'

export function Proxies() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newProxy, setNewProxy] = useState({
    host: '',
    port: 8080,
    username: '',
    password: '',
    protocol: 'http' as ProxyProtocol,
    country: '',
  })
  
  const { data: proxies, refetch } = useProxies(0, 50)
  const createProxy = useCreateProxy()
  const importProxies = useImportProxies()
  const deleteProxy = useDeleteProxy()
  const testAll = useTestAllProxies()
  const testProxy = useTestProxy()
  const autoAssign = useAutoAssignProxies()
  const verifyIp = useVerifyProxyIp()
  const [testingProxyId, setTestingProxyId] = useState<string | null>(null)

  const [verifyResult, setVerifyResult] = useState<ProxyIpVerificationResult | null>(null)
  const [providerStatus, setProviderStatus] = useState<ProxyProviderStatus | null>(null)
  const isManualProxyMode = providerStatus?.provider === 'manual'
  const isProviderManaged = !!providerStatus && !isManualProxyMode

  useEffect(() => {
    const fetchProviderStatus = async () => {
      try {
        const status = await proxiesApi.getProviderStatus()
        setProviderStatus(status)
      } catch (e) {
        console.error('Failed to fetch provider status:', e)
      }
    }
    fetchProviderStatus()
  }, [])

  const handleCreate = async () => {
    try {
      await createProxy.mutateAsync(newProxy)
      toast.success('Proxy added')
      setIsCreateOpen(false)
      setNewProxy({ host: '', port: 8080, username: '', password: '', protocol: 'http', country: '' })
      refetch()
    } catch {
      toast.error('Failed to add proxy')
    }
  }

  const handleImport = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await importProxies.mutateAsync(file)
      toast.success('Proxies imported')
      refetch()
    } catch {
      toast.error('Failed to import proxies')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this proxy?')) return
    try {
      await deleteProxy.mutateAsync(id)
      toast.success('Proxy deleted')
      refetch()
    } catch {
      toast.error('Failed to delete proxy')
    }
  }

  const handleTestAll = async () => {
    try {
      const result = await testAll.mutateAsync()
      toast.success(`Tested ${result?.total} proxies: ${result?.healthy} healthy`)
      refetch()
    } catch {
      toast.error('Failed to test proxies')
    }
  }

  const handleTestProxy = async (id: string) => {
    setTestingProxyId(id)
    try {
      const result = (await testProxy.mutateAsync(id)) as import('@/types').ProxyTestResult
      toast.success(result.healthy ? 'Proxy healthy' : 'Proxy unhealthy')
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to test proxy')
    } finally {
      setTestingProxyId(null)
    }
  }

  const handleAutoAssign = async () => {
    try {
      const result = await autoAssign.mutateAsync()
      toast.success(`Assigned ${result.assigned} proxies to accounts`)
      refetch()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to auto-assign')
    }
  }

  const handleVerifyIp = async (id: string) => {
    try {
      const result = await verifyIp.mutateAsync(id)
      setVerifyResult(result)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Failed to verify IP')
    }
  }

  return (
    <div className="space-y-6">
      {providerStatus && (
        <Card className="p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Provider:</span>
              <Badge variant="outline" className="capitalize">
                {providerStatus.provider}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Status:</span>
              {providerStatus.connected ? (
                <Badge variant="default" className="bg-green-500">
                  <CheckCircle className="h-3 w-3 mr-1" />
                  Connected
                </Badge>
              ) : (
                <Badge variant="destructive">
                  <XCircle className="h-3 w-3 mr-1" />
                  Disconnected
                </Badge>
              )}
            </div>
            {providerStatus.total_proxies !== undefined && (
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-muted-foreground">Quota:</span>
                <span className="text-sm">
                  {providerStatus.available} / {providerStatus.total_proxies} available
                </span>
              </div>
            )}
            {isProviderManaged && (
              <div className="w-full mt-2">
                <div className="flex items-start gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-sm text-blue-200">
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    Proxies are provisioned automatically through the provider. Manual add/import actions are disabled on this page.
                  </span>
                </div>
              </div>
            )}
            {providerStatus.message && (
              <div className="w-full mt-2">
                <div className="flex items-start gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-sm text-blue-200">
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    {providerStatus.provider === 'manual'
                      ? 'Proxies are managed manually. Configure WEBSHARE_API_KEY to enable auto-provisioning.'
                      : providerStatus.message}
                  </span>
                </div>
              </div>
            )}
            {providerStatus.error && (
              <div className="w-full mt-2">
                <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{providerStatus.error}</span>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-foreground">Proxies</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleTestAll}>
            <Activity className="h-4 w-4 mr-2" />
            Test All
          </Button>
          {isManualProxyMode && (
            <>
              <Button variant="outline" onClick={handleAutoAssign}>
                <Link2 className="h-4 w-4 mr-2" />
                Auto Assign
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
              <Button onClick={() => setIsCreateOpen(true)} className="bg-spotify hover:bg-spotify-dark">
                <Plus className="h-4 w-4 mr-2" />
                Add Proxy
              </Button>
            </>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Host:Port</TableHead>
                <TableHead>Protocol</TableHead>
                <TableHead>Country</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Exit IP</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Linked Account</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(proxies ?? []).map((proxy) => (
                <TableRow key={proxy.id}>
                  <TableCell className="font-medium">
                    {proxy.host}:{proxy.port}
                  </TableCell>
                  <TableCell>{proxy.protocol}</TableCell>
                  <TableCell>{proxy.country || '-'}</TableCell>
                  <TableCell>
                    <StatusBadge status={proxy.status} />
                  </TableCell>
                  <TableCell>{proxy.ip || '-'}</TableCell>
                  <TableCell>{proxy.latency_ms ? `${proxy.latency_ms}ms` : '-'}</TableCell>
                  <TableCell>{proxy.linked_account_email || (proxy.linked_account_id ? 'Linked' : 'None')}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleTestProxy(proxy.id)}
                        disabled={testingProxyId === proxy.id}
                        title="Test Proxy"
                      >
                        <Activity className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleVerifyIp(proxy.id)}
                        disabled={!proxy.linked_account_id}
                        title={proxy.linked_account_id ? 'Verify IP' : 'Requires linked account'}
                      >
                        <Globe className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDelete(proxy.id)}
                        className="text-destructive hover:text-destructive"
                        title="Delete Proxy"
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

      <Dialog open={!!verifyResult} onOpenChange={(open) => !open && setVerifyResult(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Proxy IP Verification</DialogTitle>
          </DialogHeader>
          {verifyResult && (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Exit IP:</span>
                <span className="font-medium">{verifyResult.ip || 'Unavailable'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Proxy Host:</span>
                <span>{verifyResult.proxy_host || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Matches Proxy:</span>
                <span>{verifyResult.matches_proxy ? 'Yes' : (verifyResult.matches_proxy === false ? 'No' : '-')}</span>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setVerifyResult(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isManualProxyMode && (
        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Proxy</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="host">Host</Label>
                  <Input
                    id="host"
                    value={newProxy.host}
                    onChange={(e) => setNewProxy({ ...newProxy, host: e.target.value })}
                    placeholder="proxy.example.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="port">Port</Label>
                  <Input
                    id="port"
                    type="number"
                    value={newProxy.port}
                    onChange={(e) => setNewProxy({ ...newProxy, port: parseInt(e.target.value) })}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="username">Username</Label>
                  <Input
                    id="username"
                    value={newProxy.username}
                    onChange={(e) => setNewProxy({ ...newProxy, username: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={newProxy.password}
                    onChange={(e) => setNewProxy({ ...newProxy, password: e.target.value })}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="protocol">Protocol</Label>
                  <Select
                    value={newProxy.protocol}
                    onValueChange={(v) => setNewProxy({ ...newProxy, protocol: v as ProxyProtocol })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="http">HTTP</SelectItem>
                      <SelectItem value="https">HTTPS</SelectItem>
                      <SelectItem value="socks5">SOCKS5</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="country">Country</Label>
                  <Input
                    id="country"
                    value={newProxy.country}
                    onChange={(e) => setNewProxy({ ...newProxy, country: e.target.value })}
                    placeholder="US"
                  />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreate} className="bg-spotify hover:bg-spotify-dark">
                Add Proxy
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
