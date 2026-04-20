import { apiClient } from './client'
import type { Challenge, PaginatedResponse } from '@/types'

export const challengesApi = {
  list: async (status?: string, skip = 0, limit = 50) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    return apiClient.get<PaginatedResponse<Challenge>>(`/challenges?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Challenge>(`/challenges/${id}`)
  },

  resolve: async (id: string, action: string, notes?: string) => {
    return apiClient.post<Challenge>(`/challenges/${id}/resolve`, { action, notes })
  },

  getPendingCount: async () => {
    return apiClient.get<{ count: number }>('/challenges/pending-count')
  },

  getScreenshotUrl: (id: string) => {
    const isLocal = import.meta.env.DEV && ['localhost', '127.0.0.1'].includes(window.location.hostname)
    const base = isLocal
      ? `${window.location.protocol}//${window.location.hostname}:8000/api` 
      : '/api'
    return `${base}/challenges/${id}/screenshot` 
  },
}
