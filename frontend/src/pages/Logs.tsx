import { useState, type ReactNode } from 'react'
import { useStreamLogs, useStreamLogsSummary } from '@/hooks/useStreamLogs'
import { streamLogsApi } from '@/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { CheckCircle, XCircle, AlertCircle, Heart } from 'lucide-react'
import { toast } from 'sonner'
import type { StreamResult } from '@/types'

const resultIcons: Record<StreamResult, ReactNode> = {
  success: <CheckCircle className="h-4 w-4 text-green-500" />,
  fail: <XCircle className="h-4 w-4 text-red-500" />,
  shuffle_miss: <AlertCircle className="h-4 w-4 text-yellow-500" />,
  health_check: <Heart className="h-4 w-4 text-blue-500" />,
}

export function Logs() {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [result, setResult] = useState<StreamResult | ''>('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  
  const { data: logsData } = useStreamLogs({
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    result: result || undefined,
    autoRefresh,
  })
  
  const { data: summary } = useStreamLogsSummary(dateFrom || undefined, dateTo || undefined)

  const logs = logsData?.items || []

  const [isExporting, setIsExporting] = useState(false)

  const handleExport = async () => {
    setIsExporting(true)
    try {
      const blob = await streamLogsApi.exportCSV({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        result: result || undefined,
      })

      // Create download link
      const url = window.URL.createObjectURL(new Blob([blob], { type: 'text/csv' }))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `stream_logs_${new Date().toISOString().split('T')[0]}.csv`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)

      toast.success('Export downloaded successfully')
    } catch (error) {
      toast.error('Failed to export logs')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-foreground">Stream Logs</h1>
        <Button onClick={handleExport} variant="outline" disabled={isExporting}>
          {isExporting ? 'Exporting...' : 'Export CSV'}
        </Button>
      </div>

      {/* Summary Stats */}
      {summary && (
        <div className="grid gap-4 md:grid-cols-5">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Streams</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary.total_streams.toLocaleString()}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-500">{summary.success_rate.toFixed(1)}%</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Avg Duration</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{Math.round(summary.avg_duration)}s</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Today</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-spotify">{summary.streams_today.toLocaleString()}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Failed</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-500">{summary.failed_streams.toLocaleString()}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap gap-4">
            <div className="space-y-2">
              <Label>Date From</Label>
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Date To</Label>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Result</Label>
              <Select value={result || 'all'} onValueChange={(v) => setResult(v === 'all' ? '' : v as StreamResult)}>
                <SelectTrigger className="w-[150px]">
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="success">Success</SelectItem>
                  <SelectItem value="fail">Fail</SelectItem>
                  <SelectItem value="shuffle_miss">Shuffle Miss</SelectItem>
                  <SelectItem value="health_check">Health Check</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                variant={autoRefresh ? 'default' : 'outline'}
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={autoRefresh ? 'bg-spotify hover:bg-spotify-dark' : ''}
              >
                Auto Refresh
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Logs Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Instance</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Song</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="text-sm">
                    {new Date(log.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>{log.instance_name || log.instance_id.slice(0, 8)}</TableCell>
                  <TableCell>{log.account_email || log.account_id.slice(0, 8)}</TableCell>
                  <TableCell>{log.song_title || log.song_id.slice(0, 8)}</TableCell>
                  <TableCell>{log.duration_sec}s</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {resultIcons[log.result]}
                      <span className="text-sm capitalize">{log.result.replace('_', ' ')}</span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
