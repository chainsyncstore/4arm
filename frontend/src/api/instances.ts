import { apiClient } from './client'
import type { Instance, InstanceCreateRequest, PaginatedResponse } from '@/types'

export const instancesApi = {
  list: async (skip = 0, limit = 50, status?: string) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    return apiClient.get<PaginatedResponse<Instance>>(`/instances?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Instance>(`/instances/${id}`)
  },

  create: async (data: InstanceCreateRequest) => {
    return apiClient.post<Instance>('/instances', data)
  },

  start: async (id: string) => {
    return apiClient.post<Instance>(`/instances/${id}/start`)
  },

  stop: async (id: string) => {
    return apiClient.post<Instance>(`/instances/${id}/stop`)
  },

  restart: async (id: string) => {
    return apiClient.post<Instance>(`/instances/${id}/restart`)
  },

  destroy: async (id: string) => {
    return apiClient.delete<Instance>(`/instances/${id}`)
  },

  assignAccount: async (instanceId: string, accountId: string) => {
    return apiClient.post<Instance>(`/instances/${instanceId}/assign-account?account_id=${accountId}`)
  },

  unassignAccount: async (instanceId: string) => {
    return apiClient.post<Instance>(`/instances/${instanceId}/unassign-account`)
  },
}
