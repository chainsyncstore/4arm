import { apiClient } from './client'
import type { Song, SongCreateRequest, SongETA, PaginatedResponse } from '@/types'

export const songsApi = {
  list: async (skip = 0, limit = 50, status?: string, priority?: string) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    if (priority) params.append('priority', priority)
    return apiClient.get<PaginatedResponse<Song>>(`/songs?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Song>(`/songs/${id}`)
  },

  getETA: async (id: string) => {
    return apiClient.get<SongETA>(`/songs/${id}/eta`)
  },

  create: async (data: SongCreateRequest) => {
    return apiClient.post<Song>('/songs', data)
  },

  update: async (id: string, data: Partial<SongCreateRequest>) => {
    return apiClient.patch<Song>(`/songs/${id}`, data)
  },

  delete: async (id: string) => {
    return apiClient.delete<void>(`/songs/${id}`)
  },

  pause: async (id: string) => {
    return apiClient.post<Song>(`/songs/${id}/pause`)
  },

  resume: async (id: string) => {
    return apiClient.post<Song>(`/songs/${id}/resume`)
  },
}
