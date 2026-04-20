import { useQuery } from '@tanstack/react-query'
import { streamLogsApi } from '@/api'
import type { StreamLogsQueryParams } from '@/types'

const STREAM_LOGS_KEY = 'stream-logs'
const STREAM_LOGS_SUMMARY_KEY = 'stream-logs-summary'

type StreamLogsHookParams = StreamLogsQueryParams & {
  autoRefresh?: boolean
}

export function useStreamLogs(params: StreamLogsHookParams = {}) {
  return useQuery({
    queryKey: [STREAM_LOGS_KEY, params],
    queryFn: () => streamLogsApi.list(params),
    staleTime: 10000,
    refetchInterval: params.autoRefresh ? 10000 : false,
  })
}

export function useStreamLogsSummary(dateFrom?: string, dateTo?: string) {
  return useQuery({
    queryKey: [STREAM_LOGS_SUMMARY_KEY, dateFrom, dateTo],
    queryFn: () => streamLogsApi.getSummary(dateFrom, dateTo),
    staleTime: 30000,
  })
}
