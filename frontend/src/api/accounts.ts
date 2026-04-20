import { apiClient } from './client'
import type { Account, AccountBatchCreateRequest, AccountCreateRequest, AccountRegistrationResult, PaginatedResponse } from '@/types'

export const accountsApi = {
  list: async (skip = 0, limit = 50, status?: string, type?: string) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    if (type) params.append('type', type)
    return apiClient.get<PaginatedResponse<Account>>(`/accounts?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Account>(`/accounts/${id}`)
  },

  create: async (data: AccountCreateRequest) => {
    return apiClient.post<Account>('/accounts', data)
  },

  register: async ({ count, instance_ids }: AccountBatchCreateRequest) => {
    const params = new URLSearchParams({ count: String(count) })
    instance_ids?.forEach((instanceId) => params.append('instance_ids', instanceId))

    return apiClient.post<AccountRegistrationResult>(
      `/accounts/register?${params}`,
      null,
    )
  },

  createBatch: async ({ count, instance_ids }: AccountBatchCreateRequest) => {
    const params = new URLSearchParams({ count: String(count) })
    instance_ids?.forEach((instanceId) => params.append('instance_ids', instanceId))

    return apiClient.post<AccountRegistrationResult>(`/accounts/create-batch?${params}`, null)
  },

  importCSV: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<{ imported: number; errors: string[] }>('/accounts/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  downloadTemplate: () => {
    const isLocal = import.meta.env.DEV && ['localhost', '127.0.0.1'].includes(window.location.hostname)
    const base = isLocal
      ? `${window.location.protocol}//${window.location.hostname}:8000/api`
      : '/api'
    window.open(`${base}/accounts/csv-template`, '_blank')
  },

  update: async (id: string, data: Partial<AccountCreateRequest>) => {
    return apiClient.patch<Account>(`/accounts/${id}`, data)
  },

  delete: async (id: string) => {
    return apiClient.delete<void>(`/accounts/${id}`)
  },

  linkProxy: async (accountId: string, proxyId: string) => {
    return apiClient.post<Account>(`/accounts/${accountId}/link-proxy?proxy_id=${proxyId}`)
  },

  setCooldown: async (accountId: string, hours: number) => {
    return apiClient.post<Account>(`/accounts/${accountId}/set-cooldown?hours=${hours}`)
  },

  forceActive: async (accountId: string) => {
    return apiClient.post<Account>(`/accounts/${accountId}/force-active`)
  },

  replaceProxy: async (accountId: string) => {
    return apiClient.post<{ message: string; proxy_id: string; host: string; port: number }>(
      `/accounts/${accountId}/replace-proxy`
    )
  },

  extractSession: async (accountId: string, deviceId?: string) => {
    return apiClient.post<{ message: string; session_blob_path: string; account_id: string }>(
      `/accounts/${accountId}/extract-session`,
      null,
      { params: deviceId ? { device_id: deviceId } : undefined }
    )
  },

  injectSession: async (accountId: string, deviceId?: string) => {
    return apiClient.post<{ message: string; account_id: string; device_id: string }>(
      `/accounts/${accountId}/inject-session`,
      null,
      { params: deviceId ? { device_id: deviceId } : undefined }
    )
  },
}
