import { apiClient } from './client'
import type { Proxy, ProxyAutoAssignResult, ProxyCreateRequest, ProxyIpVerificationResult, ProxyProviderStatus, ProxyTestAllResult, ProxyTestResult } from '@/types'

export const proxiesApi = {
  list: async (skip = 0, limit = 50, status?: string, unlinked?: boolean) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    if (unlinked) params.append('unlinked', 'true')
    return apiClient.get<Proxy[]>(`/proxies?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Proxy>(`/proxies/${id}`)
  },

  create: async (data: ProxyCreateRequest) => {
    return apiClient.post<Proxy>('/proxies', data)
  },

  importCSV: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<{ imported: number; errors: string[] }>('/proxies/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  delete: async (id: string) => {
    return apiClient.delete<void>(`/proxies/${id}`)
  },

  test: async (id: string) => {
    return apiClient.post<ProxyTestResult>(`/proxies/${id}/test`)
  },

  testAll: async () => {
    return apiClient.post<ProxyTestAllResult>('/proxies/test-all')
  },

  autoAssign: async () => {
    return apiClient.post<ProxyAutoAssignResult>('/proxies/auto-assign')
  },

  verifyIp: async (id: string) => {
    return apiClient.get<ProxyIpVerificationResult>(`/proxies/${id}/verify-ip`)
  },

  getProviderStatus: async () => {
    return apiClient.get<ProxyProviderStatus>('/proxies/provider/status')
  },
}
