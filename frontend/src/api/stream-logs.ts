import { apiClient } from './client'
import type { StreamLog, StreamLogSummary, StreamLogsQueryParams, PaginatedResponse } from '@/types'

export const streamLogsApi = {
  list: async (params: StreamLogsQueryParams = {}) => {
    const searchParams = new URLSearchParams()
    if (params.skip !== undefined) searchParams.append('skip', String(params.skip))
    if (params.limit !== undefined) searchParams.append('limit', String(params.limit))
    if (params.instance_id) searchParams.append('instance_id', params.instance_id)
    if (params.song_id) searchParams.append('song_id', params.song_id)
    if (params.result) searchParams.append('result', params.result)
    if (params.date_from) searchParams.append('date_from', params.date_from)
    if (params.date_to) searchParams.append('date_to', params.date_to)
    
    return apiClient.get<PaginatedResponse<StreamLog>>(`/stream-logs?${searchParams}`)
  },

  getSummary: async (dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams()
    if (dateFrom) params.append('date_from', dateFrom)
    if (dateTo) params.append('date_to', dateTo)
    return apiClient.get<StreamLogSummary>(`/stream-logs/summary?${params}`)
  },

  exportCSV: async (params: StreamLogsQueryParams = {}) => {
    const searchParams = new URLSearchParams()
    if (params.instance_id) searchParams.append('instance_id', params.instance_id)
    if (params.song_id) searchParams.append('song_id', params.song_id)
    if (params.result) searchParams.append('result', params.result)
    if (params.date_from) searchParams.append('date_from', params.date_from)
    if (params.date_to) searchParams.append('date_to', params.date_to)
    
    const response = await apiClient.get<string>(`/stream-logs/export?${searchParams}`, {
      responseType: 'blob' as const
    })
    return response
  },
}
