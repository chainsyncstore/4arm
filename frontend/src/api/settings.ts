import { apiClient } from './client'
import type { SettingsUpdateRequest } from '@/types'

export const settingsApi = {
  get: async () => {
    // API returns raw string key-value pairs
    return apiClient.get<{ settings: Record<string, string> }>('/settings')
  },

  update: async (data: SettingsUpdateRequest) => {
    // API returns raw string key-value pairs
    return apiClient.patch<{ settings: Record<string, string> }>('/settings', data)
  },
}
